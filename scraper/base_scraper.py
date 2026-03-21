"""
Async HTTP — Android Chrome UA, de-DE, exponential backoff, robots.txt, polite delays.

Defaults: timeout 10s, max 2 retries (3 attempts), backoff 2s → 4s.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Optional
from urllib.parse import urlparse

import httpx

from utils.fetch_runtime import get_fetch_runtime
from utils.robots_cache import can_fetch_url

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/UP1A.240305.004; wv) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-G991B Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Redmi Note 10 Build/RKQ1.210919.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; SM-A515F Build/RP1A.200720.012; wv) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
]

_domain_locks: dict[str, asyncio.Lock] = {}


def random_headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_str(name: str) -> str | None:
    v = os.getenv(name)
    return v if v else None


# Product defaults (override via env)
REQUEST_TIMEOUT = _env_int("REQUEST_TIMEOUT", 10)
# Retries *after* the first attempt (2 → 3 HTTP attempts total)
MAX_RETRIES = _env_int("MAX_RETRIES", 2)
RETRY_WAIT_MIN = _env_int("RETRY_WAIT_MIN", 2)
PROXY_URL = _env_str("PROXY_URL")


def _num_attempts() -> int:
    return max(1, 1 + max(0, MAX_RETRIES))


def _backoff_seconds(attempt_index: int) -> float:
    """After failed attempt `attempt_index` (0-based), wait before next (2s, 4s, …)."""
    return float(RETRY_WAIT_MIN) * (2**attempt_index) + random.uniform(0.0, 0.5)


def _status_is_retryable(code: int) -> bool:
    return code in (403, 429, 502, 503, 504)


def build_client(timeout: int | None = None) -> httpx.AsyncClient:
    t = timeout if timeout is not None else REQUEST_TIMEOUT
    kwargs: dict = {
        "headers": random_headers(),
        "timeout": t,
        "follow_redirects": True,
    }
    if PROXY_URL:
        try:
            return httpx.AsyncClient(**kwargs, proxy=PROXY_URL)
        except TypeError:
            return httpx.AsyncClient(**kwargs, proxies={"all://": PROXY_URL})
    return httpx.AsyncClient(**kwargs)


def _client_ua(client: httpx.AsyncClient) -> str:
    try:
        h = client.headers.get("user-agent") or client.headers.get("User-Agent")
        return str(h) if h else "*"
    except Exception:
        return "*"


async def _domain_sleep(netloc: str) -> None:
    if not netloc:
        return
    if netloc not in _domain_locks:
        _domain_locks[netloc] = asyncio.Lock()
    async with _domain_locks[netloc]:
        rt = get_fetch_runtime()
        lo = float(rt.get("scrape_delay_min") or 1)
        hi = float(rt.get("scrape_delay_max") or 3)
        if hi < lo:
            lo, hi = hi, lo
        await asyncio.sleep(random.uniform(lo, hi))


async def _maybe_robots_ok(url: str, client: httpx.AsyncClient) -> bool:
    rt = get_fetch_runtime()
    if not rt.get("respect_robots", True):
        return True
    return await can_fetch_url(url, _client_ua(client), client)


async def fetch(
    url: str,
    client: Optional[httpx.AsyncClient] = None,
    render_js: bool = False,
    direct: bool = False,
) -> Optional[str]:
    own = client is None
    if own:
        client = build_client()
    try:
        netloc = urlparse(url).netloc
        if not await _maybe_robots_ok(url, client):
            logger.warning("event=fetch_blocked robots url=%s", url[:80])
            return None
        await _domain_sleep(netloc)
        n = _num_attempts()
        for attempt in range(n):
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code == 404:
                    logger.warning("event=http_404 url=%s", url[:80])
                    return None
                if code == 500:
                    logger.warning("event=http_500 url=%s", url[:80])
                    return None
                if _status_is_retryable(code) and attempt < n - 1:
                    wait = _backoff_seconds(attempt)
                    logger.warning(
                        "event=http_retry status=%d url=%s attempt=%d/%d wait=%.1fs",
                        code,
                        url[:55],
                        attempt + 1,
                        n,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning("event=http_error status=%d url=%s", code, url[:80])
                return None
            except httpx.RequestError as e:
                if attempt < n - 1:
                    wait = _backoff_seconds(attempt)
                    logger.warning(
                        "event=network_retry err=%s url=%s attempt=%d/%d wait=%.1fs",
                        type(e).__name__,
                        url[:55],
                        attempt + 1,
                        n,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning("event=network_fail err=%s url=%s", type(e).__name__, url[:80])
                return None
        return None
    except Exception as e:
        logger.warning("event=fetch_failed url=%s err=%s", url[:60], e)
        return None
    finally:
        if own:
            await client.aclose()


async def fetch_json(
    url: str,
    client: Optional[httpx.AsyncClient] = None,
    direct: bool = False,
) -> Optional[dict | list]:
    own = client is None
    if own:
        client = build_client()
    try:
        netloc = urlparse(url).netloc
        if not await _maybe_robots_ok(url, client):
            logger.warning("event=fetch_blocked robots url=%s", url[:80])
            return None
        await _domain_sleep(netloc)
        n = _num_attempts()
        for attempt in range(n):
            try:
                resp = await client.get(url, headers={"Accept": "application/json, */*"})
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code == 404:
                    logger.warning("event=http_404 url=%s", url[:80])
                    return None
                if code == 500:
                    logger.warning("event=http_500 url=%s", url[:80])
                    return None
                if _status_is_retryable(code) and attempt < n - 1:
                    wait = _backoff_seconds(attempt)
                    logger.warning(
                        "event=json_retry status=%d url=%s attempt=%d wait=%.1fs",
                        code,
                        url[:55],
                        attempt + 1,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning("event=json_http_error status=%d url=%s", code, url[:80])
                return None
            except httpx.RequestError as e:
                if attempt < n - 1:
                    wait = _backoff_seconds(attempt)
                    logger.warning(
                        "event=json_network_retry err=%s url=%s attempt=%d wait=%.1fs",
                        type(e).__name__,
                        url[:55],
                        attempt + 1,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                logger.warning("event=json_network_fail err=%s url=%s", type(e).__name__, url[:80])
                return None
        return None
    except Exception as e:
        logger.warning("event=fetch_json_failed url=%s err=%s", url[:60], e)
        return None
    finally:
        if own:
            await client.aclose()


async def fetch_bytes(url: str, client: httpx.AsyncClient) -> Optional[bytes]:
    try:
        netloc = urlparse(url).netloc
        if not await _maybe_robots_ok(url, client):
            return None
        await _domain_sleep(netloc)
        n = _num_attempts()
        for attempt in range(n):
            try:
                r = await client.get(url)
                r.raise_for_status()
                return r.content
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code in (404, 500):
                    return None
                if _status_is_retryable(code) and attempt < n - 1:
                    await asyncio.sleep(_backoff_seconds(attempt))
                    continue
                return None
            except httpx.RequestError:
                if attempt < n - 1:
                    await asyncio.sleep(_backoff_seconds(attempt))
                    continue
                return None
    except Exception as e:
        logger.warning("event=fetch_bytes_failed url=%s err=%s", url[:60], e)
    return None
