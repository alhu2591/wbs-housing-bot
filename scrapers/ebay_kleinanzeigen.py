"""Kleinanzeigen — WBS Berlin listings."""
import logging
from bs4 import BeautifulSoup
from .base_scraper import fetch
from ._common import build_listing, parse_price

logger = logging.getLogger(__name__)
SOURCE = "ebay_kleinanzeigen"
BASE   = "https://www.kleinanzeigen.de"
URL    = f"{BASE}/s-wohnung-mieten/berlin/wbs/k0c203l3331"


async def scrape() -> list[dict]:
    results, seen = [], set()
    try:
        html = await fetch(URL, render_js=False)
        if not html or len(html) < 1000:
            return results
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select("article.aditem, li.ad-listitem article, [class*='aditem']")
        for card in cards:
            a = (card.select_one("a.ellipsis, a[href*='/s-anzeige/']")
                 or card.select_one("h2 a, h3 a"))
            if not a:
                continue
            href = a["href"]
            full_url = href if href.startswith("http") else BASE + href
            if full_url in seen or BASE not in full_url:
                continue
            seen.add(full_url)
            title_tag = card.select_one("h2,h3,.text-module-begin")
            title = title_tag.get_text(strip=True) if title_tag else ""
            desc_tag = card.select_one("p.aditem-main--middle--description,.description")
            desc = desc_tag.get_text(" ", strip=True) if desc_tag else ""
            price_tag = card.select_one("p.aditem-main--middle--price-shipping--price,.price")
            price = parse_price(price_tag.get_text() if price_tag else None)
            loc_tag = card.select_one(".aditem-main--top--left,[class*='location']")
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
