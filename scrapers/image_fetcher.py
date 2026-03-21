"""
OG Image fetcher — extracts preview image from any listing URL.
Used to show apartment photos inside Telegram notifications.
"""
import asyncio
import logging
import httpx
from utils.soup import make_soup

logger = logging.getLogger(__name__)

HEADERS = {
    # Mobile UA to reduce blocks and better emulate Termux browsing
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; Mobile; wv) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

# OG / meta selectors in priority order
IMAGE_SELECTORS = [
    'meta[property="og:image"]',
    'meta[property="og:image:secure_url"]',
    'meta[name="twitter:image"]',
    'meta[name="twitter:image:src"]',
    'meta[itemprop="image"]',
]

# CSS selectors for inline images fallback
IMG_CSS = [
    ".apartment-gallery img",
    ".listing-gallery img",
    ".object-image img",
    ".expose-image img",
    ".property-image img",
    ".wohnung-bild img",
    "article img",
    ".gallery img",
    "[class*='gallery'] img",
    "[class*='image'] img",
    "[class*='photo'] img",
]


async def fetch_og_image(url: str) -> str | None:
    """
    Fetch the primary image URL for a listing page.
    Returns image URL string or None.
    Fast — single HTTP request, no JS rendering needed for OG tags.
    """
    if not url:
        return None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(
                headers=HEADERS,
                timeout=8,           # fast — if no image in 8s, skip it
                follow_redirects=True,
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    if attempt < 2:
                        await asyncio.sleep(2 * (attempt + 1))
                        continue
                    return None
                html = resp.text

            soup = make_soup(html)

            # 1. Try OG / meta tags (most reliable)
            for sel in IMAGE_SELECTORS:
                tag = soup.select_one(sel)
                if tag:
                    src = tag.get("content", "").strip()
                    if src.startswith("http"):
                        logger.debug("OG image found via %s: %s", sel, src[:60])
                        return src

            # 2. Try inline img tags
            for sel in IMG_CSS:
                tag = soup.select_one(sel)
                if tag:
                    for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                        src = tag.get(attr, "").strip()
                        if src.startswith("http") and not src.endswith(".gif"):
                            logger.debug("Inline image via %s: %s", sel, src[:60])
                            return src

            return None

        except Exception as e:
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            logger.debug("fetch_og_image failed for %s: %s", url[:60], e)

    return None
