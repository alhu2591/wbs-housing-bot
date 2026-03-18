"""
Gewobag — Berlin's largest public housing company.
API: https://www.gewobag.de/fuer-mieter-und-eigentuemer/mietangebote/
They offer a JSON feed via their internal API.
"""
import logging
from .base_scraper import fetch_json, build_client
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "gewobag"

API_URL = (
    "https://www.gewobag.de/fuer-mieter-und-eigentuemer/mietangebote/"
    "?objektart[]=wohnung&wbs=1&_=json"
)
LISTING_BASE = "https://www.gewobag.de"


async def scrape() -> list[dict]:
    results = []
    try:
        async with build_client() as client:
            # Gewobag paginates; fetch first two pages
            for page in range(1, 3):
                url = (
                    "https://www.gewobag.de/wp-json/gewobag/v1/offers"
                    f"?type=wohnung&wbs=1&per_page=50&page={page}"
                )
                data = await fetch_json(url, client)
                if not data:
                    break
                items = data if isinstance(data, list) else data.get("offers", data.get("results", []))
                if not items:
                    break
                for item in items:
                    url_rel = item.get("link") or item.get("url", "")
                    full_url = url_rel if url_rel.startswith("http") else LISTING_BASE + url_rel
                    price_raw = item.get("gesamtmiete") or item.get("warmmiete") or item.get("price", 0)
                    try:
                        price = float(str(price_raw).replace("€", "").replace(",", ".").strip())
                    except (ValueError, TypeError):
                        price = None
                    rooms_raw = item.get("zimmer") or item.get("rooms", 0)
                    try:
                        rooms = float(str(rooms_raw).replace(",", "."))
                    except (ValueError, TypeError):
                        rooms = None

                    listing = {
                        "id": make_id(full_url),
                        "title": item.get("title", {}).get("rendered", "") if isinstance(item.get("title"), dict) else str(item.get("title", "")),
                        "price": price,
                        "location": item.get("bezirk") or item.get("district") or item.get("lage") or "Berlin",
                        "rooms": rooms,
                        "description": item.get("beschreibung") or item.get("description", ""),
                        "wbs_label": "WBS erforderlich",
                        "url": full_url,
                        "source": SOURCE,
                    }
                    results.append(listing)
    except Exception as e:
        logger.error("[%s] scrape failed: %s", SOURCE, e)
    logger.info("[%s] found %d listings", SOURCE, len(results))
    return results
