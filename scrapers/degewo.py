"""Degewo — JSON API + HTML fallback."""
import logging
from bs4 import BeautifulSoup
from .base_scraper import fetch, fetch_json, build_client
from ._common import build_listing, parse_price, parse_rooms

logger = logging.getLogger(__name__)
SOURCE = "degewo"
BASE   = "https://immosuche.degewo.de"


async def scrape() -> list[dict]:
    results, seen = [], set()
    try:
        async with build_client() as client:
            for api_path in [
                "/de/properties.json?property_type_id=1&categories[]=WBS&page=1&per_page=50",
                "/de/search.json?asset_classes[]=1&wbs=1&page=1",
            ]:
                data = await fetch_json(f"{BASE}{api_path}", client)
                if not data:
                    continue
                items = data if isinstance(data, list) else data.get("results") or data.get("objects") or []
                for item in items:
                    path = item.get("path") or item.get("url") or item.get("link") or ""
                    url  = path if path.startswith("http") else BASE + path
                    if url in seen or url == BASE:
                        continue
                    seen.add(url)
                    price = next((parse_price(item.get(k)) for k in ("warmmiete","gesamtmiete","totalRent","rent") if item.get(k)), None)
                    rooms = next((parse_rooms(item.get(k)) for k in ("zimmer","rooms","numberOfRooms") if item.get(k)), None)
                    listing = build_listing(
                        url=url, title=item.get("title") or item.get("headline") or "",
                        price=price, rooms=rooms,
                        location=item.get("district") or (item.get("address") or {}).get("district") or "Berlin",
                        description=item.get("text") or "", source=SOURCE, base_url=BASE,
                    )
                    if listing:
                        results.append(listing)
                if results:
                    break

        if not results:
            html = await fetch(f"{BASE}/de/properties?property_type_id=1&categories[]=WBS", render_js=True)
            if html and len(html) >= 500:
                soup = BeautifulSoup(html, "lxml")
                for card in soup.select("[class*='immo'],[class*='listing'],[class*='property'],article"):
                    a = card.select_one("a[href]")
                    if not a:
                        continue
                    url = a["href"] if a["href"].startswith("http") else BASE + a["href"]
                    if url in seen:
                        continue
                    seen.add(url)
                    price = parse_price(next((t.get_text() for t in card.select("[class*='miete'],[class*='preis'],[class*='price']") if t), None))
                    rooms = parse_rooms(next((t.get_text() for t in card.select("[class*='zimmer'],[class*='room']") if t), None))
                    listing = build_listing(
                        url=url, title=(card.select_one("h2,h3,.title") or a).get_text(strip=True),
                        price=price, rooms=rooms,
                        location=next((t.get_text(strip=True) for t in card.select("[class*='bezirk'],[class*='district']") if t), "Berlin"),
                        source=SOURCE, base_url=BASE,
                    )
                    if listing:
                        results.append(listing)
    except Exception as e:
        logger.error("[%s] %s", SOURCE, e)
    logger.info("[%s] %d listings", SOURCE, len(results))
    return results
