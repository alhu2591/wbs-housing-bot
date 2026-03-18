"""
Berlinovo — JS-rendered HTML scraper.
"""
import logging
import re
from bs4 import BeautifulSoup
from .base_scraper import fetch
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "berlinovo"
BASE   = "https://www.berlinovo.de"
URLS   = [
    f"{BASE}/de/suche-wohnungen?wbs=1",
    f"{BASE}/de/suche-wohnungen",
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

            # Berlinovo uses Drupal views
            cards = (
                soup.select(".views-row")
                or soup.select("[class*='apartment']")
                or soup.select("[class*='wohnung']")
                or soup.select("[class*='listing']")
                or soup.select("[class*='immo']")
                or soup.select("article")
            )
            if not cards:
                # Last resort: all links pointing to /de/wohnungen/
                all_links = soup.select("a[href*='/de/wohnungen/'], a[href*='/wohnung/']")
                for a in all_links:
                    href = a["href"]
                    full_url = href if href.startswith("http") else BASE + href
                    if "berlinovo.de" not in full_url:
                        continue
                    results.append({
                        "id": make_id(full_url),
                        "title": a.get_text(strip=True) or "Wohnung Berlinovo",
                        "price": None,
                        "location": "Berlin",
                        "rooms": None,
                        "description": "",
                        "wbs_label": "WBS erforderlich",
                        "trusted_wbs": True,
                        "url": full_url,
                        "source": SOURCE,
                    })
                if results:
                    break
                continue

            seen = set()
            for card in cards:
                a = card.select_one("a[href]")
                if not a:
                    continue
                href = a["href"]
                full_url = href if href.startswith("http") else BASE + href
                if full_url in seen:
                    continue
                seen.add(full_url)
                if "berlinovo.de" not in full_url:
                    continue
                title = (card.select_one("h2,h3,[class*='title'],.field-title") or a).get_text(strip=True)
                price = _p(next((t.get_text() for t in card.select(
                    "[class*='gesamtmiete'],[class*='warmmiete'],[class*='miete'],[class*='price'],[class*='preis']"
                ) if t), None))
                rooms = _p(next((t.get_text() for t in card.select(
                    "[class*='zimmer'],[class*='room']"
                ) if t), None))
                loc = next((t.get_text(strip=True) for t in card.select(
                    "[class*='bezirk'],[class*='district'],[class*='location'],[class*='ort']"
                ) if t), "Berlin")
                results.append({
                    "id": make_id(full_url),
                    "title": title or "Wohnung Berlinovo",
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
