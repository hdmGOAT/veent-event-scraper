"""Residential proxy client for social networking sites.

Reserved exclusively for scrapers targeting social platforms that aggressively block datacenter IPs.

Uses DataImpulse paid residential proxies — IP rotation is handled server-side,
so every request through the same Session exits from a different residential IP.

Configuration (all required when used):
    DATAIMPULSE_USER   — proxy username, e.g. ``69358f718a3e81816efa__cr.ph``
    DATAIMPULSE_PASS   — proxy password
    DATAIMPULSE_HOST   — gateway host   (default: gw.dataimpulse.com)
    DATAIMPULSE_PORT   — gateway port   (default: 823)

Usage in social scrapers:
    from .social_proxy import get_social_session, social_proxy_configured

    if social_proxy_configured():
        session = get_social_session()
    else:
        session = requests.Session()   # or raise, depending on scraper requirements

    resp = session.get("https://www.meetup.com/...", timeout=30)
"""
from __future__ import annotations

import logging
import os
import threading

import requests

logger = logging.getLogger(__name__)


_DEFAULT_HOST = "gw.dataimpulse.com"
_DEFAULT_PORT = "823"

_lock = threading.Lock()
_cached_session: requests.Session | None = None


def social_proxy_configured() -> bool:
    """Return True if DataImpulse credentials are present in the environment."""
    return bool(
        os.environ.get("DATAIMPULSE_USER") and os.environ.get("DATAIMPULSE_PASS")
    )


def _build_proxy_url() -> str:
    user = os.environ["DATAIMPULSE_USER"]
    password = os.environ["DATAIMPULSE_PASS"]
    host = os.environ.get("DATAIMPULSE_HOST", _DEFAULT_HOST)
    port = os.environ.get("DATAIMPULSE_PORT", _DEFAULT_PORT)
    return f"http://{user}:{password}@{host}:{port}"


def get_social_session(force_refresh: bool = False) -> requests.Session:
    """Return a requests.Session routed through the DataImpulse residential proxy.

    The Session is cached so connection pools are reused; DataImpulse handles
    IP rotation transparently on their end, so no re-election is needed here.

    Raises:
        RuntimeError: if DATAIMPULSE_USER or DATAIMPULSE_PASS are not set.
        RuntimeError: if force_refresh=True is called but credentials are missing.
    """
    global _cached_session

    if not social_proxy_configured():
        raise RuntimeError(
            "DataImpulse credentials not configured. "
            "Set DATAIMPULSE_USER and DATAIMPULSE_PASS environment variables."
        )

    with _lock:
        if _cached_session is not None and not force_refresh:
            return _cached_session

    proxy_url = _build_proxy_url()
    session = requests.Session()
    session.proxies.update({"http": proxy_url, "https": proxy_url})

    host = os.environ.get("DATAIMPULSE_HOST", _DEFAULT_HOST)
    logger.info("Social proxy session created via %s", host)

    with _lock:
        _cached_session = session

    return session


def reset_social_session() -> None:
    """Clear the cached session (e.g. after a ban or credential rotation)."""
    global _cached_session
    with _lock:
        _cached_session = None
    logger.info("Social proxy session cleared.")
