"""WG-Gesucht — Berlin listings."""
import logging
from bs4 import BeautifulSoup
from .base_scraper import fetch
from ._common import build_listing, parse_price

logger = logging.getLogger(__name__)
SOURCE = "wggesucht"
BASE   = "https://www.wg-gesucht.de"
URL    = f"{BASE}/wohnungen-in-Berlin.8.2.1.0.html?oc=8&ad_type=2&city_id=8&sMin=30&rMax=600"


async def scrape() -> list[dict]:
    results, seen = [], set()
    try:
        html = await fetch(URL, render_js=False)
        if not html or len(html) < 1000:
            return results
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select(".wgg_card, .offer_list_item, article[id^='liste-'], .list-body")
        for card in cards:
            a = (card.select_one("a[href*='/wohnungen-in']")
                 or card.select_one("h3 a, h2 a, .truncate_title a"))
            if not a:
                continue
            href = a["href"]
            full_url = href if href.startswith("http") else BASE + href
            if full_url in seen or BASE not in full_url:
                continue
            seen.add(full_url)
            title = (card.select_one("h3,h2,.truncate_title") or a).get_text(strip=True)
            desc_tag = card.select_one(".description,.offer_description,.card-body")
            desc = desc_tag.get_text(" ", strip=True) if desc_tag else ""
            price_tag = card.select_one(".middle strong,.price,b.price,.noprint strong")
            price = parse_price(price_tag.get_text() if price_tag else None)
            loc_tag = card.select_one(".col-xs-11,.location,[class*='city']")
            listing = build_listing(
                url=full_url, title=title, price=price, description=desc,
                location=loc_tag.get_text(strip=True) if loc_tag else "Berlin",
                wbs_label="", trusted_wbs=False, source=SOURCE, base_url=BASE,
            )
            if listing:
                results.append(listing)
    except Exception as e:
        logger.error("[%s] %s", SOURCE, e)
    logger.info("[%s] %d listings", SOURCE, len(results))
    return results
