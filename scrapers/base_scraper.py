"""
Base scraper — async HTTP with ScraperAPI + retry + UA rotation.
"""
import asyncio
import logging
import random
from typing import Optional
from urllib.parse import urlencode

import httpx
from config.settings import REQUEST_TIMEOUT, MAX_RETRIES, RETRY_WAIT_MIN, PROXY_URL, SCRAPER_API_KEY

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
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Upgrade-Insecure-Requests": "1",
    }


def _wrap_url(url: str, render_js: bool = False) -> str:
    if SCRAPER_API_KEY:
        params: dict = {
            "api_key": SCRAPER_API_KEY,
            "url": url,
            "country_code": "de",
            "keep_headers": "true",
        }
        if render_js:
            params["render"] = "true"
        return f"https://api.scraperapi.com/?{urlencode(params)}"
    return url


def build_client() -> httpx.AsyncClient:
    proxies = {"all://": PROXY_URL} if PROXY_URL else None
    return httpx.AsyncClient(
        headers=random_headers(),
        timeout=60,
        follow_redirects=True,
        proxies=proxies,
    )


async def fetch(url: str, client: Optional[httpx.AsyncClient] = None, render_js: bool = False) -> Optional[str]:
    wrapped   = _wrap_url(url, render_js=render_js)
    own       = client is None
    if own:
        client = build_client()
    try:
        for attempt in range(MAX_RETRIES):
            try:
                resp = await client.get(wrapped, headers=random_headers())
                resp.raise_for_status()
                if len(resp.text) < 200:
                    logger.warning("Short response (%d chars) for %s", len(resp.text), url[:60])
                return resp.text
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code in (403, 429, 503) and attempt < MAX_RETRIES - 1:
                    wait = RETRY_WAIT_MIN * (2 ** attempt) + random.uniform(0, 2)
                    logger.warning("HTTP %d %s — retry %d in %.1fs", code, url[:50], attempt+1, wait)
                    await asyncio.sleep(wait)
                else:
                    raise
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_WAIT_MIN * (2 ** attempt)
                    logger.warning("Timeout %s — retry in %.1fs", url[:50], wait)
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


async def fetch_json(url: str, client: Optional[httpx.AsyncClient] = None) -> Optional[dict | list]:
    wrapped = _wrap_url(url, render_js=False)
    own     = client is None
    if own:
        client = build_client()
    try:
        hdrs = {**random_headers(), "Accept": "application/json, */*"}
        resp = await client.get(wrapped, headers=hdrs)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("fetch_json failed %s → %s", url[:60], e)
        return None
    finally:
        if own:
            await client.aclose()
