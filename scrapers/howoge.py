"""
Howoge — HTML scraper with BeautifulSoup.
"""
import logging
from bs4 import BeautifulSoup
from .base_scraper import fetch, build_client
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "howoge"
BASE   = "https://www.howoge.de"
URL    = f"{BASE}/wohnungen-gewerbe/wohnungssuche.html?tx_howoge_apartments[wbs]=1"


async def scrape() -> list[dict]:
    results = []
    try:
        async with build_client() as client:
            html = await fetch(URL, client)
            if not html:
                return results
            soup = BeautifulSoup(html, "lxml")
            # Howoge listing cards
            cards = soup.select(".apartment-list__item, .c-apartment-list__item, article.apartment")
            for card in cards:
                a_tag = card.select_one("a[href]")
                if not a_tag:
                    continue
                href = a_tag["href"]
                full_url = href if href.startswith("http") else BASE + href

                title = card.select_one(".apartment__title, .c-apartment__title, h3, h2")
                title_text = title.get_text(strip=True) if title else ""

                price = None
                price_tag = card.select_one(".apartment__price, .c-apartment__price, .price")
                if price_tag:
                    raw = price_tag.get_text(strip=True).replace("€", "").replace(".", "").replace(",", ".").strip()
                    try:
                        price = float("".join(c for c in raw if c.isdigit() or c == "."))
                    except ValueError:
                        pass

                rooms = None
                rooms_tag = card.select_one(".apartment__rooms, .rooms, [data-rooms]")
                if rooms_tag:
                    raw = rooms_tag.get_text(strip=True).replace(",", ".")
                    try:
                        rooms = float("".join(c for c in raw if c.isdigit() or c == "."))
                    except ValueError:
                        pass

                location = "Berlin"
                loc_tag = card.select_one(".apartment__district, .district, .location")
                if loc_tag:
                    location = loc_tag.get_text(strip=True)

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
