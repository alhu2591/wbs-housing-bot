"""Vonovia Berlin — JSON API + HTML fallback."""
import logging
from .base_scraper import fetch, fetch_json, build_client
from ._common import build_listing, parse_price, parse_rooms
from utils.soup import make_soup

logger = logging.getLogger(__name__)
SOURCE = "vonovia"
BASE   = "https://www.vonovia.de"

async def scrape() -> list[dict]:
    results, seen = [], set()
    try:
        async with build_client() as client:
            for api in [
                f"{BASE}/de-de/immobilien/berlin?sort=date&wbs=true",
                f"{BASE}/api/properties?city=berlin&wbs=1&per_page=50",
            ]:
                data = await fetch_json(api, client)
                if not data: continue
                items = data if isinstance(data, list) else data.get("results") or data.get("items") or []
                for item in items:
                    url = item.get("url") or item.get("link") or item.get("detailUrl") or ""
                    if not url.startswith("http"): url = BASE + url
                    if url in seen or url == BASE: continue
                    seen.add(url)
                    listing = build_listing(
                        url=url, title=item.get("title") or item.get("name") or "",
                        price=parse_price(item.get("warmmiete") or item.get("totalRent") or item.get("price")),
                        rooms=parse_rooms(item.get("zimmer") or item.get("rooms")),
                        location=item.get("district") or item.get("bezirk") or "Berlin",
                        description=item.get("description") or "", source=SOURCE, base_url=BASE,
                    )
                    if listing: results.append(listing)
                if results: break
        if not results:
            html = await fetch(f"{BASE}/de-de/immobilien/berlin?wbs=true", render_js=False)
            if html and len(html) > 500:
                soup = make_soup(html)
                for card in soup.select("[class*='property'],[class*='expose'],[class*='listing'],article"):
                    a = card.select_one("a[href*='/immobilien/']") or card.select_one("a[href]")
                    if not a: continue
                    url = a["href"] if a["href"].startswith("http") else BASE + a["href"]
                    if url in seen or BASE not in url: continue
                    seen.add(url)
                    listing = build_listing(
                        url=url,
                        title=(card.select_one("h2,h3,[class*='title']") or a).get_text(strip=True),
                        price=parse_price(next((t.get_text() for t in card.select("[class*='price'],[class*='rent'],[class*='miete']") if t), None)),
                        rooms=parse_rooms(next((t.get_text() for t in card.select("[class*='room'],[class*='zimmer']") if t), None)),
                        location=next((t.get_text(strip=True) for t in card.select("[class*='location'],[class*='city']") if t), "Berlin"),
                        source=SOURCE, base_url=BASE,
                    )
                    if listing: results.append(listing)
    except Exception as e:
        logger.error("[%s] %s", SOURCE, e)
    logger.info("[%s] %d listings", SOURCE, len(results))
    return results
