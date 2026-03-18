"""
Scheduler — scrape → AI-analyze → filter → dedup → notify.
"""
import asyncio
import json
import logging
import time

from scrapers import ALL_SCRAPERS
from scrapers.image_fetcher import fetch_og_image
from filters import is_wbs, passes_price, passes_rooms, passes_area, score_listing, get_score_label
from filters.ai_analyzer import ai_analyze
from filters.wbs_filter import extract_wbs_level
from database import (
    is_known, save_listing, purge_old_listings,
    get_settings, record_success, record_error, increment_stats,
)
from config.settings import CHAT_ID, DEFAULT_MAX_PRICE

logger      = logging.getLogger(__name__)
_notify_cb  = None
_cycle      = 0


def set_notify_callback(fn):
    global _notify_cb
    _notify_cb = fn


async def run_once() -> None:
    global _cycle
    _cycle += 1
    t0 = time.monotonic()
    logger.info("⏳ Cycle #%d — %d sources", _cycle, len(ALL_SCRAPERS))

    # ── 1. Scrape ─────────────────────────────────────────────────────────────
    tasks  = [asyncio.create_task(_safe_scrape(fn)) for fn in ALL_SCRAPERS]
    batches = await asyncio.gather(*tasks)
    listings = [item for batch in batches for item in batch]
    logger.info("📦 Raw: %d", len(listings))

    # ── 2. Settings ───────────────────────────────────────────────────────────
    settings  = await get_settings(CHAT_ID)
    max_price = float(settings.get("max_price") or DEFAULT_MAX_PRICE)
    min_rooms = float(settings.get("min_rooms") or 0)
    active    = bool(settings.get("active", 1))
    wbs_only  = bool(settings.get("wbs_only", 0))
    try:
        areas = json.loads(settings.get("areas") or "[]")
    except Exception:
        areas = []

    if not active:
        await increment_stats(cycle=1)
        return

    # ── 3. Filter + dedup ─────────────────────────────────────────────────────
    candidates = []
    for listing in listings:
        if wbs_only and not listing.get("trusted_wbs") and not is_wbs(listing):
            continue
        if not passes_price(listing, max_price):
            continue
        if min_rooms and not passes_rooms(listing, min_rooms):
            continue
        if areas and not passes_area(listing, areas):
            continue
        if await is_known(listing["id"]):
            continue
        candidates.append(listing)

    logger.info("🔍 Candidates: %d", len(candidates))

    # ── 4. Enrich ─────────────────────────────────────────────────────────────
    enriched = []
    for listing in candidates:
        listing = await ai_analyze(listing)
        if not listing.get("wbs_level"):
            listing["wbs_level"] = extract_wbs_level(listing)
        if not listing.get("image_url"):
            listing["image_url"] = await fetch_og_image(listing.get("url", ""))
        listing["score"]       = score_listing(listing)
        listing["score_label"] = get_score_label(listing["score"])
        await save_listing(listing)
        enriched.append(listing)

    enriched.sort(key=lambda x: x.get("score", 0), reverse=True)

    # ── 5. Notify ─────────────────────────────────────────────────────────────
    sent = 0
    if _notify_cb and enriched:
        for listing in enriched:
            try:
                await _notify_cb(listing)
                sent += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error("Notify failed: %s", e)

    await increment_stats(sent=sent, cycle=1)
    await purge_old_listings()
    logger.info("✅ Cycle #%d done in %.1fs — %d sent / %d new / %d raw",
                _cycle, time.monotonic()-t0, sent, len(enriched), len(listings))


async def _safe_scrape(fn) -> list:
    source = fn.__module__.split(".")[-1]
    try:
        results = await fn()
        await record_success(source, len(results))
        return results
    except Exception as e:
        logger.error("Scraper %s: %s", source, e)
        await record_error(source, str(e))
        return []
