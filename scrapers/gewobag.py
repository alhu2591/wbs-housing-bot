"""
Gewobag — tries JSON API first, falls back to rendered HTML.
"""
import logging
import re
from bs4 import BeautifulSoup
from .base_scraper import fetch, fetch_json, build_client
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "gewobag"
BASE   = "https://www.gewobag.de"


def _parse_price(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace("\xa0", "").replace(".", "").replace(",", ".").strip()
    m = re.search(r"[\d]+\.?\d*", s)
    try:
        return float(m.group()) if m else None
    except (ValueError, TypeError):
        return None


def _parse_rooms(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace(",", ".").strip()
    m = re.search(r"[\d]+\.?\d*", s)
    try:
        return float(m.group()) if m else None
    except (ValueError, TypeError):
        return None


async def scrape() -> list[dict]:
    results = []
    try:
        # Try WP REST API first (no JS needed, fast)
        async with build_client() as client:
            for page in range(1, 4):
                api = (
                    f"{BASE}/wp-json/gewobag/v1/offers"
                    f"?type=wohnung&wbs=1&per_page=50&page={page}"
                )
                data = await fetch_json(api, client)
                if not data:
                    break
                items = data if isinstance(data, list) else data.get("offers", data.get("results", []))
                if not items:
                    break
                for item in items:
                    url_raw = item.get("link") or item.get("url") or ""
                    full_url = url_raw if url_raw.startswith("http") else BASE + url_raw
                    if not full_url or full_url == BASE:
                        continue
                    title = item.get("title", {})
                    title_str = title.get("rendered", "") if isinstance(title, dict) else str(title)
                    price = _parse_price(
                        item.get("gesamtmiete") or item.get("warmmiete") or item.get("price")
                    )
                    rooms = _parse_rooms(item.get("zimmer") or item.get("rooms"))
                    results.append({
                        "id": make_id(full_url),
                        "title": title_str or "Wohnung Gewobag",
                        "price": price,
                        "location": item.get("bezirk") or item.get("district") or "Berlin",
                        "rooms": rooms,
                        "description": item.get("beschreibung") or "",
                        "wbs_label": "WBS erforderlich",
                        "trusted_wbs": True,
                        "url": full_url,
                        "source": SOURCE,
                    })
            if results:
                logger.info("[%s] JSON API: %d listings", SOURCE, len(results))
                return results

        # Fallback: rendered HTML
        url = f"{BASE}/fuer-mieter-und-eigentuemer/mietangebote/?objektart[]=wohnung&wbs=1"
        html = await fetch(url, render_js=True)
        if not html:
            return results
        soup = BeautifulSoup(html, "lxml")

        # Wide selector net
        cards = (
            soup.select("article.angebot, .angebot-item, [class*='angebot'], "
                        "[class*='listing'], [class*='immo'], [class*='wohnung']")
            or soup.select("article") or soup.select("li")
        )
        for card in cards:
            a = card.select_one("a[href]")
            if not a:
                continue
            href = a["href"]
            full_url = href if href.startswith("http") else BASE + href
            if "gewobag.de" not in full_url:
                continue
            title = (card.select_one("h2,h3,.title") or a).get_text(strip=True)
            price = _parse_price(
                next((t.get_text() for t in card.select("[class*='preis'],[class*='price'],[class*='miete']") if t), None)
            )
            rooms = _parse_rooms(
                next((t.get_text() for t in card.select("[class*='zimmer'],[class*='room']") if t), None)
            )
            loc = next((t.get_text(strip=True) for t in card.select("[class*='bezirk'],[class*='ort'],[class*='district']") if t), "Berlin")
            results.append({
                "id": make_id(full_url),
                "title": title,
                "price": price,
                "location": loc,
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


async def _fetch_image(url: str, client) -> str | None:
    """Try to extract OG image from listing page."""
    try:
        from bs4 import BeautifulSoup
        html = await fetch(url, client, render_js=False)
        if not html:
            return None
        soup = BeautifulSoup(html, "lxml")
        for sel in [
            'meta[property="og:image"]',
            'meta[name="og:image"]',
            'meta[property="twitter:image"]',
            '.listing-image img', '.apartment-image img',
            'article img', '.gallery img',
        ]:
            tag = soup.select_one(sel)
            if tag:
                src = tag.get("content") or tag.get("src") or ""
                if src and src.startswith("http"):
                    return src
    except Exception:
        pass
    return None
