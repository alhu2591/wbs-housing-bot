"""scraper/vonovia.py — Vonovia Berlin scraper."""
from __future__ import annotations
import logging
from typing import Any
from scraper.base_scraper import fetch_html
from utils.soup import make_soup
from utils.parser import parse_price, parse_rooms, parse_size, build_listing

logger = logging.getLogger(__name__)
SOURCE = "vonovia"
BASE_URL = "https://www.vonovia.de/de-de/immobilien/wohnungssuche#city=Berlin"

async def scrape(cfg: dict[str, Any]) -> list[dict]:
    html = await fetch_html(BASE_URL)
    if not html:
        return []
    soup = make_soup(html)
    listings = []
    for card in soup.select(".estate-card, .property-card, article"):
        try:
            title_el = card.select_one("h3, h2, .title")
            title = title_el.get_text(strip=True) if title_el else "Vonovia Wohnung"
            link_el = card.select_one("a[href]")
            url = link_el["href"] if link_el else ""
            if url and not url.startswith("http"):
                url = "https://www.vonovia.de" + url
            price = parse_price(card.get_text())
            location = "Berlin"
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            if not url:
                continue
            listings.append(build_listing(
                title=title, url=url, price=price, location=location,
                size_m2=size, rooms=rooms, source=SOURCE,
            ))
        except Exception as e:
            logger.debug("vonovia error: %s", e)
    logger.info("vonovia: %d listings", len(listings))
    return listings
