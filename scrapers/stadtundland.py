"""
Stadt und Land — HTML scraper.
"""
import logging
from bs4 import BeautifulSoup
from .base_scraper import fetch, build_client
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "stadtundland"
BASE   = "https://www.stadtundland.de"
URL    = f"{BASE}/Wohnungssuche/Wohnungssuche.php?wbs=1"


async def scrape() -> list[dict]:
    results = []
    try:
        async with build_client() as client:
            html = await fetch(URL, client)
            if not html:
                return results
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select(".immo-list__item, .property-item, .listing-item, article")
            for card in cards:
                a_tag = card.select_one("a[href]")
                if not a_tag:
                    continue
                href = a_tag["href"]
                full_url = href if href.startswith("http") else BASE + href

                title_tag = card.select_one("h2, h3, .title, .headline")
                title_text = title_tag.get_text(strip=True) if title_tag else ""

                price = None
                for sel in [".price", ".warmmiete", ".miete", "[class*='price']", "[class*='rent']"]:
                    p = card.select_one(sel)
                    if p:
                        raw = p.get_text(strip=True)
                        cleaned = raw.replace("€", "").replace(".", "").replace(",", ".").strip()
                        digits = "".join(c for c in cleaned if c.isdigit() or c == ".")
                        try:
                            price = float(digits)
                            break
                        except ValueError:
                            pass

                rooms = None
                for sel in [".zimmer", ".rooms", "[class*='room']"]:
                    r = card.select_one(sel)
                    if r:
                        raw = r.get_text(strip=True).replace(",", ".")
                        digits = "".join(c for c in raw if c.isdigit() or c == ".")
                        try:
                            rooms = float(digits)
                            break
                        except ValueError:
                            pass

                location_tag = card.select_one(".district, .location, .address, [class*='bezirk']")
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
