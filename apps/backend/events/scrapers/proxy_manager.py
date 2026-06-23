"""Rotating proxy manager for scraper HTTP sessions.

Proxy routing is ON by default. Disable it by setting:

    SCRAPER_USE_PROXY=false   (or 0 / no)

Usage in scrapers:
    from .proxy_manager import get_session

    session = get_session()          # proxy Session when on; plain Session when off
    resp = session.get("https://example.com", timeout=20)

When proxy mode is active the first call downloads the public proxy list,
shuffles it, and tests candidates until one passes an HTTPS connectivity check.
The working proxy is cached in a module-level Session so all subsequent
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

_PROXY_LIST_URLS = [
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
    "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/mmpx12/proxy-list/master/http.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
]
# Test HTTPS tunneling explicitly — we need proxies that support CONNECT, since
# most scraped sites use HTTPS. Plain HTTP tests elect proxies that pass but
# then fail on HTTPS targets.
_TEST_URL = "https://httpbin.org/ip"
_CONNECT_TIMEOUT = 5   # seconds to establish TCP connection
_READ_TIMEOUT = 8      # seconds to receive first byte
_MAX_TRIES = 100       # free proxy lists are noisy; cast a wide net
_TEST_WORKERS = 20     # concurrent proxy testers

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


def _fetch_one(url: str) -> list[str]:
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return [line.strip() for line in resp.text.splitlines() if line.strip()]


def _fetch_proxy_list() -> list[str]:
    seen: set[str] = set()
    combined: list[str] = []
    with ThreadPoolExecutor(max_workers=len(_PROXY_LIST_URLS)) as pool:
        futures = {pool.submit(_fetch_one, url): url for url in _PROXY_LIST_URLS}
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                for entry in fut.result():
                    if entry not in seen:
                        seen.add(entry)
                        combined.append(entry)
                logger.info("Fetched from %s — pool now %d unique", url, len(combined))
            except Exception as exc:
                logger.warning("Failed to fetch proxy list from %s: %s", url, exc)
    logger.info("Combined proxy pool: %d unique candidates", len(combined))
    return combined


def _make_proxies(host_port: str) -> dict[str, str]:
    url = f"http://{host_port}"
    return {"http": url, "https": url}


def _test_proxy(host_port: str) -> bool:
    try:
        resp = requests.get(
            _TEST_URL,
            proxies=_make_proxies(host_port),
            timeout=(_CONNECT_TIMEOUT, _READ_TIMEOUT),
        )
        return resp.status_code == 200
    except Exception:
        return False


def get_proxy_session(force_refresh: bool = False) -> requests.Session:
    """Return a requests.Session pre-configured with a working proxy.

    On the first call (or when ``force_refresh=True``) this downloads the
    proxy list, shuffles it, and tests candidates sequentially until one
    succeeds.  Raises ``RuntimeError`` if no working proxy is found within
    ``_MAX_TRIES`` attempts.

    The cache read and write are both guarded by ``_lock``; the expensive
    proxy-election network I/O runs outside the lock so it doesn't stall
    other threads waiting for a cached session.
    """
    global _cached_session

    with _lock:
        if _cached_session is not None and not force_refresh:
            return _cached_session

    # Proxy election happens outside the lock — can take 30+ seconds.
    candidates = _fetch_proxy_list()
    random.shuffle(candidates)
    batch = candidates[: _MAX_TRIES]

    winner: str | None = None
    found = threading.Event()

    def _test_one(host_port: str) -> str | None:
        if found.is_set():
            return None
        logger.debug("Testing proxy %s", host_port)
        if _test_proxy(host_port):
            return host_port
        return None

    with ThreadPoolExecutor(max_workers=_TEST_WORKERS) as pool:
        futures = {pool.submit(_test_one, hp): hp for hp in batch}
        for fut in as_completed(futures):
            result = fut.result()
            if result and not found.is_set():
                found.set()
                winner = result
                break

    if winner:
        logger.info("Elected proxy: %s (from %d candidates)", winner, len(batch))
        session = requests.Session()
        session.proxies.update(_make_proxies(winner))
        with _lock:
            if _cached_session is not None:
                _cached_session.close()
            _cached_session = session
        return session

    raise RuntimeError(
        f"No working proxy found after testing {len(batch)} candidate(s). "
        "The list may be stale or all tested proxies are down."
    )


def reset_proxy_session() -> None:
    """Clear the cached session so the next call re-elects a proxy."""
    global _cached_session
    with _lock:
        if _cached_session is not None:
            _cached_session.close()
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
