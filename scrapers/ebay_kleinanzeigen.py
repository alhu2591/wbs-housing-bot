"""
eBay Kleinanzeigen (now Kleinanzeigen.de) — WBS Berlin.
"""
import logging
from bs4 import BeautifulSoup
from .base_scraper import fetch, build_client
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "kleinanzeigen"
BASE   = "https://www.kleinanzeigen.de"
URL    = f"{BASE}/s-wohnung-mieten/berlin/wbs/k0c203l3331"


async def scrape() -> list[dict]:
    results = []
    try:
        async with build_client() as client:
            html = await fetch(URL, client)
            if not html:
                return results
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select(
                "article.aditem, "
                "li.ad-listitem article, "
                "[class*='aditem']"
            )
            for card in cards:
                a_tag = card.select_one("a.ellipsis, a[href*='/s-anzeige/']")
                if not a_tag:
                    a_tag = card.select_one("h2 a, h3 a")
                if not a_tag:
                    continue
                href = a_tag["href"]
                full_url = href if href.startswith("http") else BASE + href

                title_tag = card.select_one("h2, h3, .text-module-begin")
                title_text = title_tag.get_text(strip=True) if title_tag else ""

                desc_tag = card.select_one("p.aditem-main--middle--description, .description")
                description = desc_tag.get_text(" ", strip=True) if desc_tag else ""

                price = None
                price_tag = card.select_one("p.aditem-main--middle--price-shipping--price, .price")
                if price_tag:
                    raw = price_tag.get_text(strip=True).replace("€", "").replace(".", "").replace(",", ".").strip()
                    digits = "".join(c for c in raw if c.isdigit() or c == ".")
                    try:
                        price = float(digits)
                    except ValueError:
                        pass

                location_tag = card.select_one(".aditem-main--top--left, [class*='location']")
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
