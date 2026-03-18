"""
Scheduler — runs all scrapers concurrently every SCRAPE_INTERVAL minutes.
Filters results, deduplicates, saves to DB, and triggers notifications.
"""
import asyncio
import logging

from scrapers import ALL_SCRAPERS
from filters import is_wbs, passes_price, passes_rooms, passes_area, score_listing
from database import is_known, save_listing, purge_old_listings, get_settings, record_success, record_error
from config.settings import CHAT_ID, DEFAULT_MAX_PRICE, DEFAULT_ROOMS, DEFAULT_AREA

logger = logging.getLogger(__name__)

# Will be injected from main.py
_notify_callback = None


def set_notify_callback(fn):
    global _notify_callback
    _notify_callback = fn


async def run_once() -> None:
    logger.info("⏳ Starting scrape cycle across %d sources…", len(ALL_SCRAPERS))
    tasks = [asyncio.create_task(_safe_scrape(fn)) for fn in ALL_SCRAPERS]
    all_results = await asyncio.gather(*tasks)

    # Flatten
    listings = [item for batch in all_results for item in batch]
    logger.info("📦 Total raw listings collected: %d", len(listings))

    # Load user settings (single-user bot)
    settings = await get_settings(CHAT_ID)
    max_price = settings.get("max_price") or DEFAULT_MAX_PRICE
    min_rooms = settings.get("min_rooms") or DEFAULT_ROOMS
    area      = settings.get("area") or DEFAULT_AREA
    active    = bool(settings.get("active", 1))

    if not active:
        logger.info("🔕 Notifications disabled by user.")
        return

    new_listings = []
    for listing in listings:
        # WBS check
        if not is_wbs(listing):
            continue
        # Price / rooms / area filters
        if not passes_price(listing, max_price):
            continue
        if min_rooms and not passes_rooms(listing, min_rooms):
            continue
        if area and not passes_area(listing, area):
            continue
        # Deduplication
        if await is_known(listing["id"]):
            continue

        await save_listing(listing)
        listing["score"] = score_listing(listing)
        new_listings.append(listing)

    # Sort by score descending so best listings notify first
    new_listings.sort(key=lambda x: x.get("score", 0), reverse=True)
    logger.info("🆕 New matching listings to notify: %d", len(new_listings))

    if _notify_callback and new_listings:
        for listing in new_listings:
            try:
                await _notify_callback(listing)
                await asyncio.sleep(0.5)   # avoid Telegram flood
            except Exception as e:
                logger.error("Notification failed for %s: %s", listing.get("url"), e)

    # Daily cleanup — purge listings older than TTL
    await purge_old_listings()


async def _safe_scrape(fn) -> list:
    # Derive source name from function module name
    source = fn.__module__.split(".")[-1]
    try:
        results = await fn()
        await record_success(source, len(results))
        return results
    except Exception as e:
        logger.error("Scraper %s crashed: %s", fn.__name__, e)
        await record_error(source, str(e))
        return []
