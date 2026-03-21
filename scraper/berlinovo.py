"""Berlinovo — JS-rendered HTML scraper."""
import logging
from scraper.base_scraper import fetch
from utils.parser import build_listing, parse_price, parse_rooms
from utils.soup import make_soup

logger = logging.getLogger(__name__)
SOURCE = "berlinovo"
BASE   = "https://www.berlinovo.de"
URLS   = [f"{BASE}/de/suche-wohnungen?wbs=1", f"{BASE}/de/suche-wohnungen"]


async def scrape() -> list[dict]:
    results, seen = [], set()
    try:
        for url in URLS:
            html = await fetch(url, render_js=True)
            if not html or len(html) < 1000:
                continue
            soup = make_soup(html)
            cards = (
                soup.select(".views-row")
                or soup.select("[class*='apartment']")
                or soup.select("[class*='wohnung']")
                or soup.select("[class*='listing']")
                or soup.select("article")
            )
            # Fallback: direct wohnung links
            if not cards:
                for a in soup.select("a[href*='/de/wohnungen/'], a[href*='/wohnung/']"):
                    href = a["href"]
                    full_url = href if href.startswith("http") else BASE + href
                    if full_url in seen or BASE not in full_url:
                        continue
                    seen.add(full_url)
                    listing = build_listing(url=full_url, title=a.get_text(strip=True), source=SOURCE, base_url=BASE)
                    if listing:
                        results.append(listing)
                if results:
                    break
                continue

            for card in cards:
                a = card.select_one("a[href]")
                if not a:
                    continue
                href = a["href"]
                full_url = href if href.startswith("http") else BASE + href
                if full_url in seen or BASE not in full_url:
                    continue
                seen.add(full_url)
                price = parse_price(next((t.get_text() for t in card.select("[class*='gesamtmiete'],[class*='warmmiete'],[class*='miete'],[class*='price']") if t), None))
                rooms = parse_rooms(next((t.get_text() for t in card.select("[class*='zimmer'],[class*='room']") if t), None))
                listing = build_listing(
                    url=full_url,
                    title=(card.select_one("h2,h3,[class*='title'],.field-title") or a).get_text(strip=True),
                    price=price, rooms=rooms,
                    location=next((t.get_text(strip=True) for t in card.select("[class*='bezirk'],[class*='district'],[class*='location']") if t), "Berlin"),
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
