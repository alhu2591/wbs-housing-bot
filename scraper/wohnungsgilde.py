"""Wohnungsgilde / social-housing style listings (best effort)."""

from __future__ import annotations

import logging

from scraper.base_scraper import fetch
from utils.parser import build_listing, parse_price, parse_rooms
from utils.soup import make_soup

logger = logging.getLogger(__name__)

SOURCE = "wohnungsgilde"
BASE = "https://wohnungsgilde.de"
URLS = [
    f"{BASE}/wohnungen-berlin",
    f"{BASE}/wohnungen",
]


async def scrape() -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    try:
        for url in URLS:
            html = await fetch(url, render_js=True)
            if not html or len(html) < 600:
                continue
            soup = make_soup(html)
            cards = (
                soup.select("article")
                or soup.select("[class*='listing']")
                or soup.select("[class*='wohnung']")
                or soup.select("a[href*='wohnung']")
            )
            for card in cards:
                a = card.select_one("a[href]") if hasattr(card, "select_one") else None
                if not a:
                    continue
                href = a.get("href")
                if not href:
                    continue
                full_url = href if href.startswith("http") else BASE + href
                if full_url in seen or "wohnungsgilde" not in full_url:
                    continue
                seen.add(full_url)

                text = card.get_text(" ", strip=True)
                title = (card.select_one("h1,h2,h3,[class*='title']") or a).get_text(strip=True)
                listing = build_listing(
                    url=full_url,
                    title=title,
                    price=parse_price(text),
                    rooms=parse_rooms(text),
                    description=text[:800],
                    location="Berlin",
                    source=SOURCE,
                    base_url=BASE,
                )
                if listing:
                    results.append(listing)
            if results:
                break
    except Exception as e:
        logger.error("[%s] %s", SOURCE, e)
    logger.info("[%s] %d listings", SOURCE, len(results))
    return results

