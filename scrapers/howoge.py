"""Howoge — JS-rendered HTML scraper."""
import logging
from .base_scraper import fetch
from ._common import build_listing, parse_price, parse_rooms
from utils.soup import make_soup

logger = logging.getLogger(__name__)
SOURCE = "howoge"
BASE   = "https://www.howoge.de"
URLS   = [
    f"{BASE}/wohnungen-gewerbe/wohnungssuche.html?tx_howoge_apartments[wbs]=1",
    f"{BASE}/wohnungen-gewerbe/wohnungssuche.html",
]


async def scrape() -> list[dict]:
    results, seen = [], set()
    try:
        for url in URLS:
            html = await fetch(url, render_js=True)
            if not html or len(html) < 1000:
                continue
            soup = make_soup(html)
            cards = (
                soup.select(".apartment-list__item")
                or soup.select(".c-apartment-list__item")
                or soup.select("[class*='apartment']")
                or soup.select("[class*='wohnung']")
                or soup.select("[class*='listing']")
                or soup.select("article")
            )
            for card in cards:
                a = card.select_one("a[href]")
                if not a:
                    continue
                href = a["href"]
                full_url = href if href.startswith("http") else BASE + href
                if full_url in seen or BASE not in full_url:
                    continue
                seen.add(full_url)
                price = parse_price(next((t.get_text() for t in card.select("[class*='price'],[class*='preis'],[class*='miete']") if t), None))
                rooms = parse_rooms(next((t.get_text() for t in card.select("[class*='room'],[class*='zimmer']") if t), None))
                listing = build_listing(
                    url=full_url,
                    title=(card.select_one("h2,h3,[class*='title']") or a).get_text(strip=True),
                    price=price, rooms=rooms,
                    location=next((t.get_text(strip=True) for t in card.select("[class*='district'],[class*='bezirk'],[class*='location']") if t), "Berlin"),
                    source=SOURCE, base_url=BASE,
                )
                if listing:
                    results.append(listing)
            if results:
                break
    except Exception as e:
        logger.error("[%s] %s", SOURCE, e)
    logger.info("[%s] %d listings", SOURCE, len(results))
    return results
