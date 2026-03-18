"""
Immowelt — WBS Berlin listings.
"""
import logging
from bs4 import BeautifulSoup
from .base_scraper import fetch, build_client
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "immowelt"
BASE   = "https://www.immowelt.de"
URL    = f"{BASE}/liste/berlin/wohnungen/mieten?wbs=true&pma=600"


async def scrape() -> list[dict]:
    results = []
    try:
        async with build_client() as client:
            html = await fetch(URL, client)
            if not html:
                return results
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select(
                "[class*='EstateItem'], "
                "[data-testid*='estate'], "
                "article[class*='estate'], "
                ".iw_listitem"
            )
            for card in cards:
                a_tag = card.select_one("a[href]")
                if not a_tag:
                    continue
                href = a_tag["href"]
                full_url = href if href.startswith("http") else BASE + href

                title_tag = card.select_one("h2, h3, [class*='title']")
                title_text = title_tag.get_text(strip=True) if title_tag else ""

                desc_tag = card.select_one("[class*='description'], [class*='text']")
                description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

                price = None
                price_tag = card.select_one("[class*='price'], [class*='Price'], [data-testid*='price']")
                if price_tag:
                    raw = price_tag.get_text(strip=True).replace("€", "").replace(".", "").replace(",", ".").strip()
                    digits = "".join(c for c in raw if c.isdigit() or c == ".")
                    try:
                        price = float(digits)
                    except ValueError:
                        pass

                rooms = None
                rooms_tag = card.select_one("[class*='room'], [class*='Room'], [class*='zimmer']")
                if rooms_tag:
                    raw = rooms_tag.get_text(strip=True).replace(",", ".")
                    digits = "".join(c for c in raw if c.isdigit() or c == ".")
                    try:
                        rooms = float(digits)
                    except ValueError:
                        pass

                location_tag = card.select_one("[class*='location'], [class*='address'], [class*='Location']")
                location = location_tag.get_text(strip=True) if location_tag else "Berlin"

                listing = {
                    "id": make_id(full_url),
                    "title": title_text,
                    "price": price,
                    "location": location,
                    "rooms": rooms,
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
