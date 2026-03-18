"""
Degewo — uses a public JSON search API.
"""
import logging
from .base_scraper import fetch_json, build_client
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)
SOURCE = "degewo"

BASE = "https://immosuche.degewo.de"
API  = f"{BASE}/de/properties.json?property_type_id=1&categories[]=WBS&page="


async def scrape() -> list[dict]:
    results = []
    try:
        async with build_client() as client:
            for page in range(1, 4):
                data = await fetch_json(f"{API}{page}", client)
                if not data:
                    break
                items = data.get("results") or data.get("immoObjects") or []
                if not items:
                    break
                for item in items:
                    path = item.get("path") or item.get("url") or ""
                    full_url = path if path.startswith("http") else BASE + path
                    price = None
                    for key in ("warmmiete", "gesamtmiete", "totalRent", "rent"):
                        raw = item.get(key)
                        if raw:
                            try:
                                price = float(str(raw).replace("€", "").replace(",", ".").strip())
                                break
                            except (ValueError, TypeError):
                                pass
                    rooms = None
                    for key in ("zimmer", "rooms", "numberOfRooms"):
                        raw = item.get(key)
                        if raw:
                            try:
                                rooms = float(str(raw).replace(",", "."))
                                break
                            except (ValueError, TypeError):
                                pass
                    listing = {
                        "id": make_id(full_url),
                        "title": item.get("title") or item.get("headline") or "",
                        "price": price,
                        "location": item.get("district") or item.get("address", {}).get("district", "Berlin"),
                        "rooms": rooms,
                        "description": item.get("text") or item.get("description") or "",
                        "wbs_label": "WBS erforderlich",
                        "url": full_url,
                        "source": SOURCE,
                    }
                    results.append(listing)
    except Exception as e:
        logger.error("[%s] scrape failed: %s", SOURCE, e)
    logger.info("[%s] found %d listings", SOURCE, len(results))
    return results
