"""
ImmobilienScout24 — WBS Berlin (JS rendered).
"""
import logging
import re
from bs4 import BeautifulSoup
from .base_scraper import fetch
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "immoscout"
BASE   = "https://www.immobilienscout24.de"
URLS = [
    f"{BASE}/Suche/de/berlin/berlin/wohnung-mieten?wbs=true&price=-600.0",
    f"{BASE}/Suche/de/berlin/berlin-spandau/wohnung-mieten?wbs=true&price=-600.0",
]


def _p(raw) -> float | None:
    s = str(raw or "").replace(".", "").replace(",", ".").replace("€","").replace("\xa0","").strip()
    m = re.search(r"\d+\.?\d*", s)
    try:
        return float(m.group()) if m else None
    except (ValueError, TypeError):
        return None


async def scrape() -> list[dict]:
    results = []
    seen = set()
    try:
        for url in URLS:
            html = await fetch(url, render_js=True)
            if not html or len(html) < 1000:
                continue
            soup = BeautifulSoup(html, "lxml")

            # IS24 uses data-id on article elements
            cards = (
                soup.select("article[data-id]")
                or soup.select("li[data-id]")
                or soup.select("[class*='result-list-entry']")
                or soup.select("[class*='listing']")
            )

            for card in cards:
                a = card.select_one("a[href*='/expose/'], a[href*='/Expose/']")
                if not a:
                    a = card.select_one("a[href]")
                if not a:
                    continue
                href = a["href"]
                full_url = href if href.startswith("http") else BASE + href
                if full_url in seen:
                    continue
                seen.add(full_url)

                title = (card.select_one("[class*='title'],h2,h3") or a).get_text(strip=True)
                desc  = (card.select_one("[class*='description'],[class*='criteria']") or "")
                desc_text = desc.get_text(" ", strip=True) if desc else ""

                price = _p(next((t.get_text() for t in card.select(
                    "[class*='price'],[class*='Price'],[data-testid*='price']"
                ) if t), None))
                rooms = _p(next((t.get_text() for t in card.select(
                    "[class*='zimmer'],[class*='room'],[aria-label*='Zimmer']"
                ) if t), None))
                loc = next((t.get_text(strip=True) for t in card.select(
                    "[class*='address'],[class*='location'],[class*='Location']"
                ) if t), "Berlin")

                results.append({
                    "id": make_id(full_url),
                    "title": title,
                    "price": price,
                    "location": loc,
                    "rooms": rooms,
                    "description": desc_text,
                    "wbs_label": "WBS erforderlich" if "wbs" in desc_text.lower() else "",
                    "trusted_wbs": False,
                    "url": full_url,
                    "source": SOURCE,
                })
    except Exception as e:
        logger.error("[%s] scrape failed: %s", SOURCE, e)
    logger.info("[%s] found %d listings", SOURCE, len(results))
    return results
