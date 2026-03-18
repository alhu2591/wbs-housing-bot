"""
Immowelt — WBS Berlin listings (JS rendered).
"""
import logging
import re
from bs4 import BeautifulSoup
from .base_scraper import fetch
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "immowelt"
BASE   = "https://www.immowelt.de"
URL    = f"{BASE}/liste/berlin/wohnungen/mieten?wbs=true&pma=600"


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
        html = await fetch(URL, render_js=True)
        if not html or len(html) < 1000:
            return results
        soup = BeautifulSoup(html, "lxml")

        cards = (
            soup.select("[class*='EstateItem']")
            or soup.select("[data-testid*='estate']")
            or soup.select("[class*='listitem']")
            or soup.select("[class*='estate']")
            or soup.select("article")
        )

        for card in cards:
            a = card.select_one("a[href]")
            if not a:
                continue
            href = a["href"]
            full_url = href if href.startswith("http") else BASE + href
            if full_url in seen:
                continue
            seen.add(full_url)
            if "immowelt.de" not in full_url:
                continue

            title = (card.select_one("h2,h3,[class*='title'],[class*='Title']") or a).get_text(strip=True)
            desc  = card.select_one("[class*='description'],[class*='Description'],[class*='text']")
            desc_text = desc.get_text(" ", strip=True) if desc else ""

            price = _p(next((t.get_text() for t in card.select(
                "[class*='price'],[class*='Price'],[data-testid*='price']"
            ) if t), None))
            rooms = _p(next((t.get_text() for t in card.select(
                "[class*='room'],[class*='Room'],[class*='zimmer'],[class*='Zimmer']"
            ) if t), None))
            loc = next((t.get_text(strip=True) for t in card.select(
                "[class*='location'],[class*='address'],[class*='Location'],[class*='Address']"
            ) if t), "Berlin")

            results.append({
                "id": make_id(full_url),
                "title": title,
                "price": price,
                "location": loc,
                "rooms": rooms,
                "description": desc_text,
                "wbs_label": "WBS erforderlich" if "wbs" in (title + desc_text).lower() else "",
                "trusted_wbs": False,
                "url": full_url,
                "source": SOURCE,
            })
    except Exception as e:
        logger.error("[%s] scrape failed: %s", SOURCE, e)
    logger.info("[%s] found %d listings", SOURCE, len(results))
    return results
