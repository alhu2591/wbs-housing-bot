"""scraper/howoge.py — Howoge Berlin scraper."""
from __future__ import annotations
import logging
from typing import Any
from scraper.base_scraper import fetch_html
from utils.soup import make_soup
from utils.parser import parse_price, parse_rooms, parse_size, build_listing

logger = logging.getLogger(__name__)
SOURCE = "howoge"
BASE_URL = "https://www.howoge.de/wohnungen-gewerbe/wohnungssuche.html"

async def scrape(cfg: dict[str, Any]) -> list[dict]:
    html = await fetch_html(BASE_URL)
    if not html:
        return []
    soup = make_soup(html)
    listings = []
    for card in soup.select(".apartment-item, .wohnung-card, .expose"):
        try:
            title_el = card.select_one("h2, h3, .title")
            title = title_el.get_text(strip=True) if title_el else "Howoge Wohnung"
            link_el = card.select_one("a[href]")
            url = link_el["href"] if link_el else ""
            if url and not url.startswith("http"):
                url = "https://www.howoge.de" + url
            price = parse_price(card.get_text())
            location_el = card.select_one(".address, .ort, .standort")
            location = location_el.get_text(strip=True) if location_el else "Berlin"
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            if not url:
                continue
            listings.append(build_listing(
                title=title, url=url, price=price, location=location,
                size_m2=size, rooms=rooms, source=SOURCE, wbs_label="WBS möglich",
            ))
        except Exception as e:
            logger.debug("howoge error: %s", e)
    logger.info("howoge: %d listings", len(listings))
    return listings
