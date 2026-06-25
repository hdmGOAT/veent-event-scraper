"""Rotating proxy manager for scraper HTTP sessions.

Proxy routing is ON by default. Disable it by setting:

    SCRAPER_USE_PROXY=false   (or 0 / no)

Usage in scrapers:
    from .proxy_manager import get_session

    session = get_session()          # proxy Session when on; plain Session when off
    resp = session.get("https://example.com", timeout=20)

When proxy mode is active the first call downloads the public proxy list,
shuffles it, and tests candidates until one passes a Facebook connectivity check.
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
# Test against Facebook directly — proxies that pass a generic HTTPS check
# (e.g. httpbin.org) still fail on Facebook due to IP blocks or missing CONNECT
# support. Testing robots.txt is lightweight, requires no JS, and confirms the
# proxy can actually tunnel to Facebook's servers.
_TEST_URL = "https://www.facebook.com/robots.txt"
_TEST_MARKER = "user-agent"   # robots.txt always contains this; block pages don't
_CONNECT_TIMEOUT = 8    # seconds to establish TCP connection
_READ_TIMEOUT = 15      # seconds to receive first byte (FB through proxy is slower)
_TEST_WORKERS = 15      # concurrent proxy testers (lower to avoid triggering FB rate limits)

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
    # Fetch all sources in parallel, collect per-source lists.
    per_source: list[list[str]] = []
    with ThreadPoolExecutor(max_workers=len(_PROXY_LIST_URLS)) as pool:
        futures = {pool.submit(_fetch_one, url): url for url in _PROXY_LIST_URLS}
        source_results: dict[str, list[str]] = {}
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                entries = fut.result()
                source_results[url] = entries
                logger.info("Fetched %d proxies from %s", len(entries), url)
            except Exception as exc:
                logger.warning("Failed to fetch proxy list from %s: %s", url, exc)

    # Shuffle each source independently so we sample randomly within each,
    # then round-robin interleave so the combined list is diverse across sources
    # rather than front-loaded with whichever source had the most entries.
    sources = list(source_results.values())
    for src in sources:
        random.shuffle(src)

    seen: set[str] = set()
    combined: list[str] = []
    for i in range(max((len(s) for s in sources), default=0)):
        for src in sources:
            if i < len(src):
                entry = src[i]
                if entry not in seen:
                    seen.add(entry)
                    combined.append(entry)

    logger.info(
        "Combined proxy pool: %d unique candidates from %d source(s)",
        len(combined), len(sources),
    )
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
            headers={"User-Agent": "Mozilla/5.0"},
            allow_redirects=True,
        )
        return resp.status_code == 200 and _TEST_MARKER in resp.text.lower()
    except Exception:
        return False


def get_proxy_session(force_refresh: bool = False) -> requests.Session:
    """Return a requests.Session pre-configured with a working proxy.

    On the first call (or when ``force_refresh=True``) this fetches all
    proxy sources in parallel, round-robin interleaves them for diversity,
    then tests the full pool with ``_TEST_WORKERS`` concurrent workers,
    stopping as soon as the first candidate passes.  Raises ``RuntimeError``
    if no working proxy is found in the entire pool.

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
        futures = {pool.submit(_test_one, hp): hp for hp in candidates}
        for fut in as_completed(futures):
            result = fut.result()
            if result and not found.is_set():
                found.set()
                winner = result
                break

    if winner:
        logger.info("Elected proxy: %s (from %d candidates)", winner, len(candidates))
        session = requests.Session()
        session.proxies.update(_make_proxies(winner))
        with _lock:
            if _cached_session is not None:
                _cached_session.close()
            _cached_session = session
        return session

    raise RuntimeError(
        f"No working proxy found after testing {len(candidates)} candidate(s). "
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


def resolve_playwright_proxy(source: str = "") -> dict:
    """Return a Playwright proxy dict using DataImpulse (primary) or free list (fallback).

    Priority:
      1. DataImpulse residential proxy — verified by preflight check.
      2. Free public proxy list (subject to SCRAPER_USE_PROXY toggle).

    Raises RuntimeError if no proxy is available — never falls back to unproxied.
    """
    from .social_proxy import social_proxy_configured, dataimpulse_playwright_proxy

    tag = f"[{source}] " if source else ""

    if social_proxy_configured():
        try:
            return dataimpulse_playwright_proxy(source=source)
        except Exception as exc:
            msg = str(exc).lower()
            if "exhausted" in msg or "407" in msg:
                logger.warning("%sDataImpulse traffic exhausted — falling back to free proxy.", tag)
            else:
                logger.warning("%sDataImpulse preflight failed (%s) — falling back to free proxy.", tag, exc)

    if get_proxy_enabled():
        try:
            session = get_proxy_session()
            proxy_url = session.proxies.get("https") or session.proxies.get("http")
            if proxy_url:
                logger.info("%susing free proxy: %s", tag, proxy_url)
                return {"server": proxy_url}
        except Exception as exc:
            logger.warning("%sfree proxy election failed: %s", tag, exc)

    raise RuntimeError(
        f"{tag}No proxy available — DataImpulse traffic exhausted and "
        "free proxy list empty or disabled. Aborting to avoid unproxied scraping."
    )
