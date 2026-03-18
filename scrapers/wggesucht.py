"""
WG-Gesucht — WBS Berlin listings.
"""
import logging
from bs4 import BeautifulSoup
from .base_scraper import fetch, build_client
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "wggesucht"
BASE   = "https://www.wg-gesucht.de"
URL    = f"{BASE}/wohnungen-in-Berlin.8.2.1.0.html?oc=8&ad_type=2&city_id=8&sMin=30&rMax=600"


async def scrape() -> list[dict]:
    results = []
    try:
        async with build_client() as client:
            html = await fetch(URL, client)
            if not html:
                return results
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select(".wgg_card, .offer_list_item, article[id^='liste-'], .list-body")
            for card in cards:
                a_tag = card.select_one("a[href*='/wohnungen-in']")
                if not a_tag:
                    a_tag = card.select_one("h3 a, h2 a, .truncate_title a")
                if not a_tag:
                    continue
                href = a_tag["href"]
                full_url = href if href.startswith("http") else BASE + href

                title_tag = card.select_one("h3, h2, .truncate_title")
                title_text = title_tag.get_text(strip=True) if title_tag else ""

                desc_tag = card.select_one(".description, .offer_description, .card-body")
                description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

                price = None
                price_tag = card.select_one(".middle strong, .price, b.price, .noprint strong")
                if price_tag:
                    raw = price_tag.get_text(strip=True).replace("€", "").replace(",", ".").strip()
                    digits = "".join(c for c in raw if c.isdigit() or c == ".")
                    try:
                        price = float(digits)
                    except ValueError:
                        pass

                location_tag = card.select_one(".col-xs-11, .location, [class*='city']")
                location = location_tag.get_text(strip=True) if location_tag else "Berlin"

                listing = {
                    "id": make_id(full_url),
                    "title": title_text,
                    "price": price,
                    "location": location,
                    "rooms": None,
                    "description": description,
                    "wbs_label": "",
                    "url": full_url,
                    "source": SOURCE,
                }
                results.append(listing)
    except Exception as e:
        logger.error("[%s] scrape failed: %s", SOURCE, e)
    logger.info("[%s] found %d listings", SOURCE, len(results))
    return results
