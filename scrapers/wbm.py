"""WBM Berlin — Wohnungsbaugesellschaft Berlin-Mitte."""
import logging
from .base_scraper import fetch, fetch_json, build_client
from ._common import build_listing, parse_price, parse_rooms
from utils.soup import make_soup

logger = logging.getLogger(__name__)
SOURCE = "wbm"
BASE   = "https://www.wbm.de"
URLS   = [f"{BASE}/wohnungen-in-berlin/angebote/?wbs=1", f"{BASE}/wohnungen-in-berlin/angebote/"]

async def scrape() -> list[dict]:
    results, seen = [], set()
    try:
        data = await fetch_json(f"{BASE}/api/apartments?wbs=true&per_page=50")
        if data:
            for item in (data if isinstance(data, list) else data.get("results",[])):
                url = item.get("url",""); url = url if url.startswith("http") else BASE+url
                if url in seen or url==BASE: continue; seen.add(url)
                listing = build_listing(url=url,title=item.get("title",""),price=parse_price(item.get("warmmiete") or item.get("rent")),rooms=parse_rooms(item.get("zimmer")),location=item.get("district","Berlin"),source=SOURCE,base_url=BASE)
                if listing: results.append(listing)
        for url in URLS:
            if results: break
            html = await fetch(url, render_js=False)
            if not html or len(html)<500: continue
            soup = make_soup(html)
            for card in soup.select("[class*='apartment'],[class*='immo'],[class*='listing'],article"):
                a = card.select_one("a[href]")
                if not a: continue
                href=a["href"]; full=href if href.startswith("http") else BASE+href
                if full in seen or BASE not in full: continue; seen.add(full)
                listing = build_listing(url=full,title=(card.select_one("h2,h3") or a).get_text(strip=True),price=parse_price(next((t.get_text() for t in card.select("[class*='miete'],[class*='preis'],[class*='price']") if t),None)),rooms=parse_rooms(next((t.get_text() for t in card.select("[class*='zimmer']") if t),None)),source=SOURCE,base_url=BASE)
                if listing: results.append(listing)
    except Exception as e:
        logger.error("[%s] %s", SOURCE, e)
    logger.info("[%s] %d", SOURCE, len(results))
    return results
