"""scraper/gewobag.py — Gewobag Berlin scraper."""
from __future__ import annotations
import logging
from typing import Any
from scraper.base_scraper import fetch_html
from utils.soup import make_soup
from utils.parser import parse_price, parse_rooms, parse_size, build_listing

logger = logging.getLogger(__name__)
SOURCE = "gewobag"
BASE_URL = "https://www.gewobag.de/fuer-mieter-und-mietinteressenten/mietangebote/"

async def scrape(cfg: dict[str, Any]) -> list[dict]:
    html = await fetch_html(BASE_URL)
    if not html:
        return []
    soup = make_soup(html)
    listings = []
    for card in soup.select("article.angebot-big-layout, .angebot"):
        try:
            title_el = card.select_one("h3, .angebot-title")
            title = title_el.get_text(strip=True) if title_el else ""
            link_el = card.select_one("a[href]")
            url = link_el["href"] if link_el else ""
            if url and not url.startswith("http"):
                url = "https://www.gewobag.de" + url
            price_el = card.select_one(".angebot-kosten, .kosten")
            price = parse_price(price_el.get_text() if price_el else "")
            loc_el = card.select_one(".angebot-address, .address, .ort")
            location = loc_el.get_text(strip=True) if loc_el else "Berlin"
            size_el = card.select_one(".angebot-area, .flaeche")
            size = parse_size(size_el.get_text() if size_el else "")
            rooms_el = card.select_one(".angebot-rooms, .zimmer")
            rooms = parse_rooms(rooms_el.get_text() if rooms_el else "")
            if not title and not url:
                continue
            listings.append(build_listing(
                title=title or "Gewobag Wohnung",
                url=url, price=price, location=location or "Berlin",
                size_m2=size, rooms=rooms, source=SOURCE,
                wbs_label="WBS erforderlich",
            ))
        except Exception as e:
            logger.debug("gewobag card parse error: %s", e)
    logger.info("gewobag: %d listings", len(listings))
    return listings
