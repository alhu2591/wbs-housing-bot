"""ImmobilienScout24 — JS-rendered HTML scraper."""
import logging
from bs4 import BeautifulSoup
from .base_scraper import fetch
from ._common import build_listing, parse_price, parse_rooms

logger = logging.getLogger(__name__)
SOURCE = "immoscout"
BASE   = "https://www.immobilienscout24.de"
URLS   = [
    f"{BASE}/Suche/de/berlin/berlin/wohnung-mieten?wbs=true&price=-600.0",
    f"{BASE}/Suche/de/berlin/berlin-spandau/wohnung-mieten?wbs=true&price=-600.0",
]


async def scrape() -> list[dict]:
    results, seen = [], set()
    try:
        for url in URLS:
            html = await fetch(url, render_js=True)
            if not html or len(html) < 1000:
                continue
            soup = BeautifulSoup(html, "lxml")
            cards = (
                soup.select("article[data-id]")
                or soup.select("li[data-id]")
                or soup.select("[class*='result-list-entry']")
                or soup.select("[class*='listing']")
            )
            for card in cards:
                a = card.select_one("a[href*='/expose/'], a[href*='/Expose/']") or card.select_one("a[href]")
                if not a:
                    continue
                href = a["href"]
                full_url = href if href.startswith("http") else BASE + href
                if full_url in seen or BASE not in full_url:
                    continue
                seen.add(full_url)
                desc_tag = card.select_one("[class*='description'],[class*='criteria']")
                desc = desc_tag.get_text(" ", strip=True) if desc_tag else ""
                price = parse_price(next((t.get_text() for t in card.select("[class*='price'],[class*='Price'],[data-testid*='price']") if t), None))
                rooms = parse_rooms(next((t.get_text() for t in card.select("[class*='zimmer'],[class*='room']") if t), None))
                listing = build_listing(
                    url=full_url,
                    title=(card.select_one("[class*='title'],h2,h3") or a).get_text(strip=True),
                    price=price, rooms=rooms, description=desc,
                    location=next((t.get_text(strip=True) for t in card.select("[class*='address'],[class*='location']") if t), "Berlin"),
                    wbs_label="WBS erforderlich" if "wbs" in desc.lower() else "",
                    trusted_wbs=False, source=SOURCE, base_url=BASE,
                )
                if listing:
                    results.append(listing)
    except Exception as e:
        logger.error("[%s] %s", SOURCE, e)
    logger.info("[%s] %d listings", SOURCE, len(results))
    return results
