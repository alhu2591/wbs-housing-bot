"""
Scheduler — scrape → AI-analyze → filter → dedup → notify.
Includes per-cycle timing and heartbeat logging.
"""
import asyncio
import logging
import time

from scrapers import ALL_SCRAPERS
from filters import is_wbs, passes_price, passes_rooms, passes_area, score_listing, get_score_label
from filters.ai_analyzer import ai_analyze
from database import (
    is_known, save_listing, purge_old_listings,
    get_settings, record_success, record_error, increment_stats,
)
from config.settings import CHAT_ID, DEFAULT_MAX_PRICE, DEFAULT_ROOMS, DEFAULT_AREA

logger           = logging.getLogger(__name__)
_notify_callback = None
_cycle_count     = 0


def set_notify_callback(fn):
    global _notify_callback
    _notify_callback = fn


async def run_once() -> None:
    global _cycle_count
    _cycle_count += 1
    t0 = time.monotonic()

    logger.info("⏳ Cycle #%d — scraping %d sources", _cycle_count, len(ALL_SCRAPERS))

    # ── 1. Scrape all sources concurrently ───────────────────────────────────
    tasks      = [asyncio.create_task(_safe_scrape(fn)) for fn in ALL_SCRAPERS]
    all_results = await asyncio.gather(*tasks)
    listings   = [item for batch in all_results for item in batch]
    logger.info("📦 Raw listings collected: %d", len(listings))

    # ── 2. Load user settings ────────────────────────────────────────────────
    settings  = await get_settings(CHAT_ID)
    max_price = float(settings.get("max_price") or DEFAULT_MAX_PRICE)
    min_rooms = settings.get("min_rooms") or DEFAULT_ROOMS
    area      = settings.get("area") or DEFAULT_AREA
    active    = bool(settings.get("active", 1))
    wbs_only  = bool(settings.get("wbs_only", 1))

    if not active:
        logger.info("🔕 Notifications disabled.")
        await increment_stats(cycle=1)
        return

    # ── 3. Filter ─────────────────────────────────────────────────────────────
    candidates = []
    for listing in listings:
        # WBS filter — only applied when wbs_only=True
        if wbs_only:
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
        candidates.append(listing)

    logger.info("🔍 Candidates after filter/dedup: %d", len(candidates))

    # ── 4. AI enrich (rate-limited by semaphore inside ai_analyze) ───────────
    enriched = []
    for listing in candidates:
        listing = await ai_analyze(listing)

        # If AI didn't extract wbs_level, fall back to regex
        if not listing.get("wbs_level"):
            from filters import extract_wbs_level
            listing["wbs_level"] = extract_wbs_level(listing)

        listing["score"]       = score_listing(listing)
        listing["score_label"] = get_score_label(listing["score"])
        await save_listing(listing)
        enriched.append(listing)

    # ── 5. Sort best first ────────────────────────────────────────────────────
    enriched.sort(key=lambda x: x.get("score", 0), reverse=True)

    # ── 6. Notify ─────────────────────────────────────────────────────────────
    sent = 0
    if _notify_callback and enriched:
        for listing in enriched:
            try:
                await _notify_callback(listing)
                sent += 1
                await asyncio.sleep(0.5)   # Telegram flood guard
            except Exception as e:
                logger.error("Notify failed %s: %s", listing.get("url","")[:60], e)

    # ── 7. Housekeeping ───────────────────────────────────────────────────────
    await increment_stats(sent=sent, cycle=1)
    await purge_old_listings()

    elapsed = time.monotonic() - t0
    logger.info(
        "✅ Cycle #%d done in %.1fs — %d sent | %d raw | %d new",
        _cycle_count, elapsed, sent, len(listings), len(enriched),
    )


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
