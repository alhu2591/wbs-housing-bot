"""
robots.txt caching (urllib.robotparser). Used when `respect_robots` is true.
"""
from __future__ import annotations

import asyncio
import logging
import urllib.robotparser
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_CACHE: dict[str, urllib.robotparser.RobotFileParser | None] = {}


def _robots_url(url: str) -> str:
    p = urlparse(url)
    if not p.scheme or not p.netloc:
        return ""
    return f"{p.scheme}://{p.netloc}/robots.txt"


async def _download_robots(robots_url: str, client: httpx.AsyncClient) -> str | None:
    try:
        r = await client.get(robots_url, follow_redirects=True, timeout=15.0)
        if r.status_code != 200:
            return None
        return r.text
    except Exception as e:
        logger.debug("robots fetch failed %s: %s", robots_url, e)
        return None


async def can_fetch_url(url: str, user_agent: str, client: httpx.AsyncClient | None) -> bool:
    """Return True if allowed or robots unavailable / parse error (fail-open)."""
    ru = _robots_url(url)
    if not ru:
        return True
    netloc = urlparse(url).netloc
    if netloc in _CACHE:
        rp = _CACHE[netloc]
        if rp is None:
            return True
        try:
            return rp.can_fetch(user_agent or "*", url)
        except Exception:
            return True

    own = client is None
    if own:
        client = httpx.AsyncClient(follow_redirects=True, timeout=15.0)
    try:
        body = await _download_robots(ru, client)
        if not body:
            _CACHE[netloc] = None
            logger.info("robots: no rules for %s — allowing fetch (fail-open)", netloc)
            return True
        rp = urllib.robotparser.RobotFileParser()
        await asyncio.to_thread(rp.parse, body.splitlines())
        _CACHE[netloc] = rp
        ok = rp.can_fetch(user_agent or "*", url)
        if not ok:
            logger.warning("robots.txt disallows %s for %s", url[:80], user_agent[:40])
        return ok
    except Exception as e:
        logger.warning("robots parse error %s: %s — allowing (fail-open)", ru, e)
        _CACHE[netloc] = None
        return True
    finally:
        if own and client:
            await client.aclose()
