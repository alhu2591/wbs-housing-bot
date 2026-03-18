"""
Deutsche Wohnen — HTML scraper.
"""
import logging
from bs4 import BeautifulSoup
from .base_scraper import fetch, build_client
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "deutschewohnen"
BASE   = "https://www.deutsche-wohnen.com"
URL    = f"{BASE}/immobilienangebote/wohnungssuche/?wbs=1"


async def scrape() -> list[dict]:
    results = []
    try:
        async with build_client() as client:
            html = await fetch(URL, client)
            if not html:
                return results
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select(".search-result-item, .property-card, article, .estate-item")
            for card in cards:
                a_tag = card.select_one("a[href]")
                if not a_tag:
                    continue
                href = a_tag["href"]
                full_url = href if href.startswith("http") else BASE + href

                title_tag = card.select_one("h2, h3, .title")
                title_text = title_tag.get_text(strip=True) if title_tag else ""

                price = _extract_price(card)
                rooms = _extract_rooms(card)

                location_tag = card.select_one(".location, .address, .city, [class*='district']")
                location = location_tag.get_text(strip=True) if location_tag else "Berlin"

                listing = {
                    "id": make_id(full_url),
                    "title": title_text,
                    "price": price,
                    "location": location,
                    "rooms": rooms,
                    "description": "",
                    "wbs_label": "WBS erforderlich",
                    "url": full_url,
                    "source": SOURCE,
                }
                results.append(listing)
    except Exception as e:
        logger.error("[%s] scrape failed: %s", SOURCE, e)
    logger.info("[%s] found %d listings", SOURCE, len(results))
    return results


def _extract_price(card) -> float | None:
    for sel in [".price", ".warmmiete", ".rent", "[class*='price']"]:
        tag = card.select_one(sel)
        if tag:
            raw = tag.get_text(strip=True).replace("€", "").replace(".", "").replace(",", ".").strip()
            digits = "".join(c for c in raw if c.isdigit() or c == ".")
            try:
                return float(digits)
            except ValueError:
                pass
    return None


def _extract_rooms(card) -> float | None:
    for sel in [".zimmer", ".rooms", "[class*='room']", "[class*='zimmer']"]:
        tag = card.select_one(sel)
        if tag:
            raw = tag.get_text(strip=True).replace(",", ".")
            digits = "".join(c for c in raw if c.isdigit() or c == ".")
            try:
                return float(digits)
            except ValueError:
                pass
    return None
