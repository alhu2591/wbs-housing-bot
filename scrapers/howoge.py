"""
Howoge — JS-rendered HTML scraper with wide selector net.
"""
import logging
import re
from bs4 import BeautifulSoup
from .base_scraper import fetch, build_client
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "howoge"
BASE   = "https://www.howoge.de"
URLS   = [
    f"{BASE}/wohnungen-gewerbe/wohnungssuche.html?tx_howoge_apartments[wbs]=1",
    f"{BASE}/wohnungen-gewerbe/wohnungssuche.html",
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
    try:
        for url in URLS:
            html = await fetch(url, render_js=True)
            if not html or len(html) < 1000:
                continue
            soup = BeautifulSoup(html, "lxml")

            # Try multiple selector patterns
            cards = (
                soup.select(".apartment-list__item")
                or soup.select(".c-apartment-list__item")
                or soup.select("[class*='apartment']")
                or soup.select("[class*='wohnung']")
                or soup.select("[class*='listing']")
                or soup.select("article")
            )
            if not cards:
                continue

            for card in cards:
                a = card.select_one("a[href]")
                if not a:
                    continue
                href = a["href"]
                full_url = href if href.startswith("http") else BASE + href
                if "howoge.de" not in full_url:
                    continue
                title = (card.select_one("h2,h3,[class*='title'],[class*='headline']") or a).get_text(strip=True)
                price = _p(next((t.get_text() for t in card.select("[class*='price'],[class*='preis'],[class*='miete'],[class*='cost']") if t), None))
                rooms = _p(next((t.get_text() for t in card.select("[class*='room'],[class*='zimmer']") if t), None))
                loc   = next((t.get_text(strip=True) for t in card.select("[class*='district'],[class*='bezirk'],[class*='location'],[class*='adresse']") if t), "Berlin")
                results.append({
                    "id": make_id(full_url),
                    "title": title or "Wohnung Howoge",
                    "price": price,
                    "location": loc,
                    "rooms": rooms,
                    "description": "",
                    "wbs_label": "WBS erforderlich",
                    "trusted_wbs": True,
                    "url": full_url,
                    "source": SOURCE,
                })
            if results:
                break
    except Exception as e:
        logger.error("[%s] scrape failed: %s", SOURCE, e)
    logger.info("[%s] found %d listings", SOURCE, len(results))
    return results
