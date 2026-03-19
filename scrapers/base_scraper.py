"""
Base HTTP scraper — direct requests, no proxy dependency.
Designed for local execution where IPs are not blocked.
Retry + exponential backoff + User-Agent rotation built in.
"""
import asyncio
import logging
import random
from typing import Optional

import httpx
from config.settings import REQUEST_TIMEOUT, MAX_RETRIES, RETRY_WAIT_MIN, PROXY_URL

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]


def random_headers() -> dict:
    return {
        "User-Agent":              random.choice(USER_AGENTS),
        "Accept-Language":         "de-DE,de;q=0.9,en;q=0.8",
        "Accept":                  "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Encoding":         "gzip, deflate, br",
        "Cache-Control":           "no-cache",
        "Pragma":                  "no-cache",
        "Sec-Fetch-Dest":          "document",
        "Sec-Fetch-Mode":          "navigate",
        "Sec-Fetch-Site":          "none",
        "Upgrade-Insecure-Requests": "1",
    }


def build_client(timeout: int = 30) -> httpx.AsyncClient:
    """Build AsyncClient with optional proxy support."""
    kwargs: dict = {
        "headers":          random_headers(),
        "timeout":          timeout,
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
    render_js: bool = False,   # kept for signature compatibility, ignored
    direct: bool = False,      # kept for signature compatibility, ignored
) -> Optional[str]:
    """Fetch URL with retry + exponential backoff."""
    own = client is None
    if own:
        client = build_client()
    try:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(url, headers=random_headers())
                resp.raise_for_status()
                return resp.text
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code in (403, 429, 503) and attempt < MAX_RETRIES - 1:
                    wait = RETRY_WAIT_MIN * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning("HTTP %d %s — retry %d in %.1fs", code, url[:55], attempt + 1, wait)
                    await asyncio.sleep(wait)
                else:
                    raise
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_WAIT_MIN * (2 ** attempt)
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
    direct: bool = False,   # kept for signature compatibility, ignored
) -> Optional[dict | list]:
    """Fetch JSON endpoint."""
    own = client is None
    if own:
        client = build_client(timeout=20)
    try:
        hdrs = {**random_headers(), "Accept": "application/json, */*"}
        resp = await client.get(url, headers=hdrs)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("fetch_json failed %s → %s", url[:60], e)
        return None
    finally:
        if own:
            await client.aclose()
