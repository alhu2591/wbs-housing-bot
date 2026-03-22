"""scraper/degewo.py — Degewo Berlin scraper."""
from __future__ import annotations
import logging
from typing import Any
from scraper.base_scraper import fetch_html
from utils.soup import make_soup
from utils.parser import parse_price, parse_rooms, parse_size, build_listing

logger = logging.getLogger(__name__)
SOURCE = "degewo"
BASE_URL = "https://immosuche.degewo.de/de/properties?type=1&size=&rooms=&price_switch=true&price_radio=null&price_from=null&price_to=null&price_period=monthly&anbieter=degewo&area=berlin&wbs=true"

async def scrape(cfg: dict[str, Any]) -> list[dict]:
    html = await fetch_html(BASE_URL)
    if not html:
        return []
    soup = make_soup(html)
    listings = []
    for card in soup.select(".article--property, .property-item, article"):
        try:
            title_el = card.select_one("h2, h3, .property-title")
            title = title_el.get_text(strip=True) if title_el else ""
            link_el = card.select_one("a[href]")
            url = link_el["href"] if link_el else ""
            if url and not url.startswith("http"):
                url = "https://immosuche.degewo.de" + url
            price_el = card.select_one(".property-price, .price, .kosten")
            price = parse_price(price_el.get_text() if price_el else "")
            loc_el = card.select_one(".property-address, .address")
            location = loc_el.get_text(strip=True) if loc_el else "Berlin"
            size_el = card.select_one(".property-size, .flaeche")
            size = parse_size(size_el.get_text() if size_el else "")
            rooms_el = card.select_one(".property-rooms, .zimmer")
            rooms = parse_rooms(rooms_el.get_text() if rooms_el else "")
            if not url:
                continue
            listings.append(build_listing(
                title=title or "Degewo Wohnung",
                url=url, price=price, location=location or "Berlin",
                size_m2=size, rooms=rooms, source=SOURCE,
                wbs_label="WBS erforderlich",
            ))
        except Exception as e:
            logger.debug("degewo card error: %s", e)
    logger.info("degewo: %d listings", len(listings))
    return listings
