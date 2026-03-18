"""
Scheduler — runs all scrapers concurrently, enriches, filters, and notifies.
"""
import asyncio
import logging

from scrapers import ALL_SCRAPERS
from filters import (
    is_wbs, passes_price, passes_rooms, passes_area,
    score_listing, get_score_label, enrich,
)
from database import (
    is_known, save_listing, purge_old_listings,
    get_settings, record_success, record_error, increment_stats,
)
from config.settings import CHAT_ID, DEFAULT_MAX_PRICE, DEFAULT_ROOMS, DEFAULT_AREA

logger = logging.getLogger(__name__)

_notify_callback = None


def set_notify_callback(fn):
    global _notify_callback
    _notify_callback = fn


async def run_once() -> None:
    logger.info("⏳ Scrape cycle — %d sources", len(ALL_SCRAPERS))
    tasks = [asyncio.create_task(_safe_scrape(fn)) for fn in ALL_SCRAPERS]
    all_results = await asyncio.gather(*tasks)

    listings = [item for batch in all_results for item in batch]
    logger.info("📦 Raw listings collected: %d", len(listings))

    settings  = await get_settings(CHAT_ID)
    max_price = float(settings.get("max_price") or DEFAULT_MAX_PRICE)
    min_rooms = settings.get("min_rooms") or DEFAULT_ROOMS
    area      = settings.get("area") or DEFAULT_AREA
    active    = bool(settings.get("active", 1))

    if not active:
        logger.info("🔕 Notifications disabled.")
        await increment_stats(cycle=1)
        return

    new_listings = []
    for listing in listings:
        # WBS check — trusted gov sources bypass text filter
        if not listing.get("trusted_wbs") and not is_wbs(listing):
            continue
        if not passes_price(listing, max_price):
            continue
        if min_rooms and not passes_rooms(listing, min_rooms):
            continue
        if area and not passes_area(listing, area):
            continue
        if await is_known(listing["id"]):
            continue

        # Enrich with size, floor, availability, features, price/m²
        listing = enrich(listing)
        listing["score"] = score_listing(listing)
        listing["score_label"] = get_score_label(listing["score"])

        await save_listing(listing)
        new_listings.append(listing)

    # Best first
    new_listings.sort(key=lambda x: x.get("score", 0), reverse=True)
    logger.info("🆕 New listings to notify: %d", len(new_listings))

    sent = 0
    if _notify_callback and new_listings:
        for listing in new_listings:
            try:
                await _notify_callback(listing)
                sent += 1
                await asyncio.sleep(0.4)   # Telegram flood guard
            except Exception as e:
                logger.error("Notify failed %s: %s", listing.get("url"), e)

    await increment_stats(sent=sent, cycle=1)
    await purge_old_listings()


async def _safe_scrape(fn) -> list:
    source = fn.__module__.split(".")[-1]
    try:
        results = await fn()
        await record_success(source, len(results))
        return results
    except Exception as e:
        logger.error("Scraper %s crashed: %s", fn.__name__, e)
        await record_error(source, str(e))
        return []
