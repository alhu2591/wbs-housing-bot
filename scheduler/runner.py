"""
Scheduler — scrape → AI-enrich → filter → dedup → notify.
Every step individually wrapped — one failure never kills the cycle.
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
    is_known, are_known, save_listing, purge_old_listings,
    get_settings, record_success, record_error, increment_stats,
)
from config.settings import CHAT_ID, DEFAULT_MAX_PRICE

logger     = logging.getLogger(__name__)
_notify_cb = None
_cycle     = 0          # exposed for /ping command


def set_notify_callback(fn):
    global _notify_cb
    _notify_cb = fn


async def run_once() -> None:
    global _cycle
    _cycle += 1
    t0 = time.monotonic()
    logger.info("⏳ Cycle #%d — %d sources", _cycle, len(ALL_SCRAPERS))

    # ── 1. Scrape all sources concurrently ────────────────────────────────────
    tasks   = [asyncio.create_task(_safe_scrape(fn)) for fn in ALL_SCRAPERS]
    batches = await asyncio.gather(*tasks, return_exceptions=False)
    listings = [item for batch in batches for item in (batch or [])]
    logger.info("📦 Raw: %d", len(listings))

    # ── 2. Load settings ──────────────────────────────────────────────────────
    try:
        settings = await get_settings(CHAT_ID)
    except Exception as e:
        logger.error("get_settings failed: %s — using defaults", e)
        settings = {}

    max_price = float(settings.get("max_price") or DEFAULT_MAX_PRICE)
    min_rooms = float(settings.get("min_rooms") or 0)
    active    = bool(settings.get("active", 1))
    wbs_only  = bool(settings.get("wbs_only", 0))
    try:
        areas = json.loads(settings.get("areas") or "[]")
    except Exception:
        areas = []

    if not active:
        try:
            await increment_stats(cycle=1)
        except Exception:
            pass
        return

    # ── 3. Filter + batch dedup ───────────────────────────────────────────────
    # Pre-filter by WBS/price/rooms/area first (cheap)
    pre = []
    for listing in listings:
        try:
            if wbs_only and not listing.get("trusted_wbs") and not is_wbs(listing):
                continue
            if not passes_price(listing, max_price):
                continue
            if min_rooms and not passes_rooms(listing, min_rooms):
                continue
            if areas and not passes_area(listing, areas):
                continue
            pre.append(listing)
        except Exception as e:
            logger.warning("Filter error: %s", e)

    # Batch dedup — 1 DB query instead of N
    known_ids = await are_known([l["id"] for l in pre])
    candidates = [l for l in pre if l["id"] not in known_ids]

    logger.info("🔍 Candidates: %d", len(candidates))

    # ── 4. Enrich each listing individually (one failure ≠ whole batch) ───────
    enriched = []
    for listing in candidates:
        try:
            listing = await ai_analyze(listing)
        except Exception as e:
            logger.warning("ai_analyze failed for %s: %s", listing.get("url","")[:50], e)

        try:
            if not listing.get("wbs_level"):
                listing["wbs_level"] = extract_wbs_level(listing)
        except Exception as e:
            logger.warning("extract_wbs_level error: %s", e)

        try:
            if not listing.get("image_url"):
                listing["image_url"] = await fetch_og_image(listing.get("url", ""))
        except Exception as e:
            logger.debug("fetch_og_image error: %s", e)
            listing["image_url"] = None

        try:
            listing["score"]       = score_listing(listing)
            listing["score_label"] = get_score_label(listing["score"])
        except Exception as e:
            listing["score"] = 0
            listing["score_label"] = "📋 عادي"

        try:
            await save_listing(listing)
        except Exception as e:
            logger.error("save_listing failed for %s: %s", listing.get("id"), e)

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
                logger.error("notify error: %s", e)

    # ── 6. Housekeeping ───────────────────────────────────────────────────────
    try:
        await increment_stats(sent=sent, cycle=1)
    except Exception as e:
        logger.error("increment_stats failed: %s", e)

    try:
        await purge_old_listings()
    except Exception as e:
        logger.error("purge_old_listings failed: %s", e)

    logger.info(
        "✅ Cycle #%d done %.1fs — sent=%d new=%d raw=%d",
        _cycle, time.monotonic()-t0, sent, len(enriched), len(listings),
    )


async def _safe_scrape(fn) -> list:
    source = fn.__module__.split(".")[-1]
    try:
        results = await fn()
        await record_success(source, len(results))
        return results or []
    except Exception as e:
        logger.error("Scraper %s: %s", source, e)
        try:
            await record_error(source, str(e))
        except Exception:
            pass
        return []
