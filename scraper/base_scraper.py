"""
Async HTTP — httpx.AsyncClient, Android UA, de-DE, 3 retries.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro Build/UP1A.240305.004; wv) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-G991B Build/TP1A.220624.014; wv) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 12; Redmi Note 10 Build/RKQ1.210919.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 11; SM-A515F Build/RP1A.200720.012; wv) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Mobile Safari/537.36",
]


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


REQUEST_TIMEOUT = _env_int("REQUEST_TIMEOUT", 25)
MAX_RETRIES = _env_int("MAX_RETRIES", 3)
RETRY_WAIT_MIN = _env_int("RETRY_WAIT_MIN", 2)
PROXY_URL = _env_str("PROXY_URL")


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
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code in (403, 429, 503) and attempt < MAX_RETRIES - 1:
                    wait = RETRY_WAIT_MIN * (2**attempt) + random.uniform(0, 0.8)
                    logger.warning("HTTP %d %s — retry %d in %.1fs", code, url[:55], attempt + 1, wait)
                    await asyncio.sleep(wait)
                else:
                    raise
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_WAIT_MIN * (2**attempt)
                    logger.warning("Timeout %s — retry in %.1fs", url[:55], wait)
                    await asyncio.sleep(wait)
                else:
                    raise
        return None
    except Exception as e:
        logger.warning("fetch failed %s → %s", url[:60], e)
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
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(url, headers={"Accept": "application/json, */*"})
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code in (403, 429, 503) and attempt < MAX_RETRIES - 1:
                    wait = RETRY_WAIT_MIN * (2**attempt) + random.uniform(0, 0.8)
                    logger.warning("HTTP %d %s — retry %d in %.1fs", code, url[:55], attempt + 1, wait)
                    await asyncio.sleep(wait)
                else:
                    raise
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_WAIT_MIN * (2**attempt)
                    await asyncio.sleep(wait)
                else:
                    raise
        return None
    except Exception as e:
        logger.warning("fetch_json failed %s → %s", url[:60], e)
        return None
    finally:
        if own:
            await client.aclose()


async def fetch_bytes(url: str, client: httpx.AsyncClient) -> Optional[bytes]:
    try:
        for attempt in range(MAX_RETRIES):
            try:
                r = await client.get(url)
                r.raise_for_status()
                return r.content
            except (httpx.TimeoutException, httpx.ConnectError):
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(RETRY_WAIT_MIN * (2**attempt))
                else:
                    raise
    except Exception as e:
        logger.warning("fetch_bytes failed %s → %s", url[:60], e)
    return None
