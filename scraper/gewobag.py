"""
Gewobag — WP REST API first, JS-rendered HTML fallback.
"""
import logging
from scraper.base_scraper import fetch, fetch_json, build_client
from utils.parser import build_listing, parse_price, parse_rooms
from utils.soup import make_soup

logger = logging.getLogger(__name__)
SOURCE = "gewobag"
BASE   = "https://www.gewobag.de"


async def scrape() -> list[dict]:
    results, seen = [], set()
    try:
        async with build_client() as client:
            for page in range(1, 4):
                api = (f"{BASE}/wp-json/gewobag/v1/offers"
                       f"?type=wohnung&wbs=1&per_page=50&page={page}")
                data = await fetch_json(api, client, direct=True)
                if not data:
                    break
                items = data if isinstance(data, list) else data.get("offers", data.get("results", []))
                if not items:
                    break
                for item in items:
                    url_raw = item.get("link") or item.get("url") or ""
                    url = url_raw if url_raw.startswith("http") else BASE + url_raw
                    if url in seen:
                        continue
                    seen.add(url)
                    title = item.get("title", {})
                    title_str = title.get("rendered","") if isinstance(title, dict) else str(title or "")
                    price = None
                    for k in ("gesamtmiete","warmmiete","price"):
                        if item.get(k):
                            price = parse_price(item[k]); break
                    rooms = None
                    for k in ("zimmer","rooms"):
                        if item.get(k):
                            rooms = parse_rooms(item[k]); break
                    listing = build_listing(
                        url=url, title=title_str, price=price, rooms=rooms,
                        location=item.get("bezirk") or item.get("district") or "Berlin",
                        description=item.get("beschreibung") or "",
                        source=SOURCE, base_url=BASE,
                    )
                    if listing:
                        results.append(listing)
            if results:
                logger.info("[%s] JSON API: %d", SOURCE, len(results))
                return results

        # HTML fallback with JS rendering
        html = await fetch(
            f"{BASE}/fuer-mieter-und-eigentuemer/mietangebote/?objektart[]=wohnung&wbs=1",
            render_js=True,
        )
        if not html or len(html) < 500:
            return results
        soup = make_soup(html)
        cards = (
            soup.select("article.angebot, .angebot-item, [class*='angebot']")
            or soup.select("[class*='listing'], [class*='immo'], [class*='wohnung']")
            or soup.select("article")
        )
        for card in cards:
            a = card.select_one("a[href]")
            if not a:
                continue
            href = a["href"]
            url  = href if href.startswith("http") else BASE + href
            if url in seen or BASE not in url:
                continue
            seen.add(url)
            price = parse_price(next((t.get_text() for t in card.select("[class*='preis'],[class*='price'],[class*='miete']") if t), None))
            rooms = parse_rooms(next((t.get_text() for t in card.select("[class*='zimmer'],[class*='room']") if t), None))
            listing = build_listing(
                url=url,
                title=(card.select_one("h2,h3,.title") or a).get_text(strip=True),
                price=price, rooms=rooms,
                location=next((t.get_text(strip=True) for t in card.select("[class*='bezirk'],[class*='ort'],[class*='district']") if t), "Berlin"),
                source=SOURCE, base_url=BASE,
            )
            if listing:
                results.append(listing)
    except Exception as e:
        logger.error("[%s] %s", SOURCE, e)
    logger.info("[%s] %d listings", SOURCE, len(results))
    return results
