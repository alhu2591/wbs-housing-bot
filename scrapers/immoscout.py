"""
ImmobilienScout24 — WBS listings Berlin.
Uses their search URL with WBS filter.
"""
import logging
from bs4 import BeautifulSoup
from .base_scraper import fetch, build_client
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "immoscout24"
BASE   = "https://www.immobilienscout24.de"

SEARCH_URLS = [
    f"{BASE}/Suche/de/berlin/berlin/wohnung-mieten?wbs=true&price=-600.0&numberofrooms=1.0-",
    f"{BASE}/Suche/de/berlin/berlin-spandau/wohnung-mieten?wbs=true&price=-600.0",
]


async def scrape() -> list[dict]:
    results = []
    try:
        async with build_client() as client:
            for search_url in SEARCH_URLS:
                html = await fetch(search_url, client)
                if not html:
                    continue
                soup = BeautifulSoup(html, "lxml")
                cards = soup.select(
                    "article[data-id], "
                    "li[data-id], "
                    ".result-list-entry, "
                    "[class*='result-list__listing']"
                )
                for card in cards:
                    # IS24 uses data-id on article elements
                    listing_id = card.get("data-id") or ""
                    a_tag = card.select_one("a[href*='/expose/']")
                    if not a_tag:
                        a_tag = card.select_one("a[href]")
                    if not a_tag:
                        continue
                    href = a_tag["href"]
                    full_url = href if href.startswith("http") else BASE + href

                    title_tag = card.select_one("[class*='title'], h2, h3")
                    title_text = title_tag.get_text(strip=True) if title_tag else ""

                    # Check WBS in title/description first
                    desc_tag = card.select_one("[class*='description'], [class*='criterias']")
                    description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

                    price = None
                    price_tag = card.select_one("[class*='price'], .result-list-entry__primary-criterion")
                    if price_tag:
                        raw = price_tag.get_text(strip=True)
                        cleaned = raw.replace("€", "").replace(".", "").replace(",", ".").strip()
                        digits = "".join(c for c in cleaned if c.isdigit() or c == ".")
                        try:
                            price = float(digits)
                        except ValueError:
                            pass

                    rooms = None
                    for sel in ["[class*='zimmer']", "[class*='rooms']", "[aria-label*='Zimmer']"]:
                        r = card.select_one(sel)
                        if r:
                            raw = r.get_text(strip=True).replace(",", ".")
                            digits = "".join(c for c in raw if c.isdigit() or c == ".")
                            try:
                                rooms = float(digits)
                                break
                            except ValueError:
                                pass

                    location_tag = card.select_one("[class*='address'], [class*='location']")
                    location = location_tag.get_text(strip=True) if location_tag else "Berlin"

                    listing = {
                        "id": make_id(full_url),
                        "title": title_text,
                        "price": price,
                        "location": location,
                        "rooms": rooms,
                        "description": description,
                        "wbs_label": "WBS erforderlich" if "wbs" in description.lower() else "",
                        "url": full_url,
                        "source": SOURCE,
                    }
                    results.append(listing)
    except Exception as e:
        logger.error("[%s] scrape failed: %s", SOURCE, e)
    logger.info("[%s] found %d listings", SOURCE, len(results))
    return results
