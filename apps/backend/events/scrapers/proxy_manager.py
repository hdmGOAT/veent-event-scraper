"""Rotating proxy manager for scraper HTTP sessions.

Proxy routing is ON by default. Disable it by setting:

    SCRAPER_USE_PROXY=false   (or 0 / no)

Combines three public proxy lists (HTTP, SOCKS4, SOCKS5) fetched in parallel
and shuffled into a single candidate pool. Requires PySocks:

    pip install requests[socks]

Usage in scrapers:
    from .proxy_manager import get_session

    session = get_session()          # proxy Session when on; plain Session when off
    resp = session.get("https://example.com", timeout=20)

When proxy mode is active the first call downloads all proxy lists, shuffles
the combined pool, and tests candidates until one passes an HTTPS connectivity
check. The working proxy is cached in a module-level Session so all subsequent
``get_session()`` calls reuse the same proxy without re-testing.

To force a new proxy election (e.g. after a 403 or ban):
    from .proxy_manager import reset_proxy_session
    reset_proxy_session()
    session = get_session()
"""
from __future__ import annotations

import logging
import os
import random
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

logger = logging.getLogger(__name__)

# (scheme, list_url) pairs — fetched in parallel during election.
_PROXY_SOURCES: list[tuple[str, str]] = [
    ("socks5", "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt"),
    ("socks4", "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks4.txt"),
    ("http",   "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt"),
]

_TEST_URL = "https://httpbin.org/ip"
_CONNECT_TIMEOUT = 5   # seconds to establish TCP connection
_READ_TIMEOUT = 8      # seconds to receive first byte
_MAX_TRIES = 150       # larger combined pool; still a sensible cap

_cached_session: requests.Session | None = None

# Runtime toggle set from the UI. None = fall back to env var / default.
_runtime_enabled: bool | None = None

# RLock (reentrant) so set_proxy_enabled() → reset_proxy_session() doesn't
# deadlock when both acquire the same lock on the same thread.
_lock = threading.RLock()


def get_proxy_enabled() -> bool:
    """Return the current effective proxy-enabled state."""
    with _lock:
        if _runtime_enabled is not None:
            return _runtime_enabled
    val = os.environ.get("SCRAPER_USE_PROXY", "").strip().lower()
    if val in ("0", "false", "no"):
        return False
    return True  # ON by default


def set_proxy_enabled(val: bool) -> None:
    """Toggle proxy on/off at runtime (called from the UI API endpoint)."""
    global _runtime_enabled
    with _lock:
        _runtime_enabled = val
        if not val:
            reset_proxy_session()  # RLock allows re-entry from the same thread


def _fetch_one(scheme: str, url: str) -> list[tuple[str, str]]:
    """Fetch a single proxy list and return [(scheme, host:port), ...]."""
    try:
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        entries = [line.strip() for line in resp.text.splitlines() if line.strip()]
        logger.info("Fetched %d %s proxies", len(entries), scheme)
        return [(scheme, e) for e in entries]
    except Exception as exc:
        logger.warning("Failed to fetch %s proxy list: %s", scheme, exc)
        return []


def _fetch_all_proxies() -> list[tuple[str, str]]:
    """Fetch all proxy lists in parallel and return a shuffled combined pool."""
    combined: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=len(_PROXY_SOURCES)) as pool:
        futures = {pool.submit(_fetch_one, scheme, url): scheme for scheme, url in _PROXY_SOURCES}
        for future in as_completed(futures):
            combined.extend(future.result())
    random.shuffle(combined)
    return combined


def _make_proxies(scheme: str, host_port: str) -> dict[str, str]:
    url = f"{scheme}://{host_port}"
    return {"http": url, "https": url}


def _test_proxy(scheme: str, host_port: str) -> bool:
    try:
        resp = requests.get(
            _TEST_URL,
            proxies=_make_proxies(scheme, host_port),
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
        )
        return resp.status_code == 200
    except Exception:
        return False


def get_proxy_session(force_refresh: bool = False) -> requests.Session:
    """Return a requests.Session pre-configured with a working proxy.

    On the first call (or when ``force_refresh=True``) this downloads all
    proxy lists in parallel, shuffles the combined pool, and tests candidates
    sequentially until one succeeds.  Raises ``RuntimeError`` if no working
    proxy is found within ``_MAX_TRIES`` attempts.

    The cache read and write are both guarded by ``_lock``; the expensive
    proxy-election network I/O runs outside the lock so it doesn't stall
    other threads waiting for a cached session.
    """
    global _cached_session

    with _lock:
        if _cached_session is not None and not force_refresh:
            return _cached_session

    # Proxy election happens outside the lock — can take 30+ seconds.
    candidates = _fetch_all_proxies()

    tried = 0
    for scheme, host_port in candidates:
        if tried >= _MAX_TRIES:
            break
        tried += 1
        logger.debug(
            "Testing %s proxy %s (%d/%d)",
            scheme, host_port, tried, min(len(candidates), _MAX_TRIES),
        )
        if _test_proxy(scheme, host_port):
            logger.info(
                "Elected %s proxy: %s (tested %d candidate(s))",
                scheme, host_port, tried,
            )
            session = requests.Session()
            session.proxies.update(_make_proxies(scheme, host_port))
            with _lock:
                _cached_session = session
            return session

    raise RuntimeError(
        f"No working proxy found after {tried} attempt(s) across all protocol types. "
        "The lists may be stale or all tested proxies are down."
    )


def reset_proxy_session() -> None:
    """Clear the cached session so the next call re-elects a proxy."""
    global _cached_session
    with _lock:
        _cached_session = None
    logger.info("Proxy session cleared; next get_session() will re-elect.")


def get_session() -> requests.Session:
    """Return the appropriate Session based on the current proxy-enabled state.

    Proxy is ON by default. Disable via env var SCRAPER_USE_PROXY=false or
    via the UI toggle (which calls set_proxy_enabled()).
    """
    if get_proxy_enabled():
        return get_proxy_session()
    return requests.Session()
