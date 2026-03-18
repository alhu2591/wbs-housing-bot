import asyncio
import logging
import random
from typing import Optional

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from config.settings import REQUEST_TIMEOUT, MAX_RETRIES, RETRY_WAIT_MIN, RETRY_WAIT_MAX, PROXY_URL

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]


def random_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "DNT": "1",
    }


def build_client() -> httpx.AsyncClient:
    proxies = {"all://": PROXY_URL} if PROXY_URL else None
    return httpx.AsyncClient(
        headers=random_headers(),
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
        proxies=proxies,
        http2=True,
    )


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    stop=stop_after_attempt(MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=RETRY_WAIT_MIN, max=RETRY_WAIT_MAX),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=False,
)
async def fetch(url: str, client: Optional[httpx.AsyncClient] = None) -> Optional[str]:
    own_client = client is None
    if own_client:
        client = build_client()
    try:
        resp = await client.get(url, headers=random_headers())
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.warning("fetch error %s → %s", url, e)
        raise
    finally:
        if own_client:
            await client.aclose()


async def fetch_json(url: str, client: Optional[httpx.AsyncClient] = None) -> Optional[dict | list]:
    own_client = client is None
    if own_client:
        client = build_client()
    try:
        resp = await client.get(url, headers=random_headers())
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("fetch_json error %s → %s", url, e)
        return None
    finally:
        if own_client:
            await client.aclose()
