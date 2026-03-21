"""inberlinwohnen.de official local portal (best effort)."""

from __future__ import annotations

import logging

from scraper.base_scraper import fetch
from utils.parser import build_listing, parse_price, parse_rooms
from utils.soup import make_soup

logger = logging.getLogger(__name__)

SOURCE = "inberlinwohnen"
BASE = "https://www.inberlinwohnen.de"
URL = f"{BASE}/wohnungsfinder/"


async def scrape() -> list[dict]:
    results: list[dict] = []
    seen: set[str] = set()
    try:
        html = await fetch(URL, render_js=True)
        if not html or len(html) < 600:
            return results
        soup = make_soup(html)
        cards = (
            soup.select("article")
            or soup.select("[class*='wohnung']")
            or soup.select("[class*='listing']")
            or soup.select("a[href*='wohnungsfinder']")
        )
        for card in cards:
            a = card.select_one("a[href]") if hasattr(card, "select_one") else None
            if not a:
                continue
            href = a.get("href")
            if not href:
                continue
            full_url = href if href.startswith("http") else BASE + href
            if full_url in seen or "inberlinwohnen.de" not in full_url:
                continue
            seen.add(full_url)
            text = card.get_text(" ", strip=True)
            title = (card.select_one("h1,h2,h3,[class*='title']") or a).get_text(strip=True)
            listing = build_listing(
                url=full_url,
                title=title,
                price=parse_price(text),
                rooms=parse_rooms(text),
                description=text[:1000],
                location="Berlin",
                source=SOURCE,
                base_url=BASE,
            )
            if listing:
                results.append(listing)
    except Exception as e:
        logger.error("[%s] %s", SOURCE, e)
    logger.info("[%s] %d listings", SOURCE, len(results))
    return results

