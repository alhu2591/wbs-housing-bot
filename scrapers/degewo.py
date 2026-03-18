"""
Degewo — JSON API + HTML fallback with JS rendering.
"""
import logging
import re
from bs4 import BeautifulSoup
from .base_scraper import fetch, fetch_json, build_client
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "degewo"
BASE   = "https://immosuche.degewo.de"


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
        async with build_client() as client:
            # Try multiple known API paths
            for api_path in [
                "/de/properties.json?property_type_id=1&categories[]=WBS&page=1&per_page=50",
                "/de/search.json?asset_classes[]=1&wbs=1&page=1",
                "/api/properties?type=apartment&wbs=true&page=1",
            ]:
                data = await fetch_json(f"{BASE}{api_path}", client)
                if not data:
                    continue
                items = (data if isinstance(data, list)
                         else data.get("results") or data.get("objects") or [])
                if not items:
                    continue
                for item in items:
                    path = item.get("path") or item.get("url") or item.get("link") or ""
                    full_url = path if path.startswith("http") else BASE + path
                    if not full_url or full_url == BASE:
                        continue
                    price = None
                    for k in ("warmmiete","gesamtmiete","totalRent","rent","kaltmiete"):
                        if item.get(k):
                            price = _p(item[k])
                            break
                    rooms = None
                    for k in ("zimmer","rooms","numberOfRooms","anzahlZimmer"):
                        if item.get(k):
                            rooms = _p(item[k])
                            break
                    results.append({
                        "id": make_id(full_url),
                        "title": item.get("title") or item.get("headline") or "Wohnung Degewo",
                        "price": price,
                        "location": (item.get("district") or
                                     (item.get("address") or {}).get("district") or "Berlin"),
                        "rooms": rooms,
                        "description": item.get("text") or "",
                        "wbs_label": "WBS erforderlich",
                        "trusted_wbs": True,
                        "url": full_url,
                        "source": SOURCE,
                    })
                if results:
                    break

        if not results:
            # HTML fallback with JS rendering
            html = await fetch(f"{BASE}/de/properties?property_type_id=1&categories[]=WBS", render_js=True)
            if html:
                soup = BeautifulSoup(html, "lxml")
                cards = soup.select("[class*='immo'],[class*='listing'],[class*='property'],article,li[class]")
                for card in cards:
                    a = card.select_one("a[href]")
                    if not a:
                        continue
                    href = a["href"]
                    full_url = href if href.startswith("http") else BASE + href
                    if "degewo" not in full_url:
                        continue
                    title = (card.select_one("h2,h3,.title") or a).get_text(strip=True)
                    price = _p(next((t.get_text() for t in card.select("[class*='miete'],[class*='preis'],[class*='price']") if t), None))
                    rooms = _p(next((t.get_text() for t in card.select("[class*='zimmer'],[class*='room']") if t), None))
                    results.append({
                        "id": make_id(full_url),
                        "title": title,
                        "price": price,
                        "location": next((t.get_text(strip=True) for t in card.select("[class*='bezirk'],[class*='district'],[class*='ort']") if t), "Berlin"),
                        "rooms": rooms,
                        "description": "",
                        "wbs_label": "WBS erforderlich",
                        "trusted_wbs": True,
                        "url": full_url,
                        "source": SOURCE,
                    })
    except Exception as e:
        logger.error("[%s] scrape failed: %s", SOURCE, e)
    logger.info("[%s] found %d listings", SOURCE, len(results))
    return results
