"""
Optional Playwright HTML fetch (JS-heavy pages). Not installed by default.

Install: pip install playwright && playwright install chromium
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def fetch_html_playwright_sync(url: str, timeout_ms: int = 30000) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.info("Playwright not installed — skipping JS render for %s", url[:60])
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                html = page.content()
                return html if html and len(html) > 200 else None
            finally:
                browser.close()
    except Exception as e:
        logger.warning("Playwright fetch failed %s: %s", url[:60], e)
        return None


async def fetch_html_playwright(url: str, timeout_ms: int = 30000) -> str | None:
    return await asyncio.to_thread(fetch_html_playwright_sync, url, timeout_ms)
