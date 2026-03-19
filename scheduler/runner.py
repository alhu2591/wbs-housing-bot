"""
Scheduler — scrape → enrich → filter → dedup → notify.
Pure local execution: no external API dependencies.
Each enrichment step is individually isolated — one failure never kills the cycle.
"""
import asyncio
import json
import logging
import time

from scrapers import ALL_SCRAPERS
from scrapers.image_fetcher import fetch_og_image
from scrapers.circuit_breaker import get_breaker
from filters import is_wbs, passes_price, passes_rooms, passes_area, score_listing, get_score_label
from filters.social_filter import passes_jobcenter, passes_wohngeld, get_social_badge
from filters.wbs_filter import enrich, extract_wbs_level
from database import (
    are_known, save_listing, purge_old_listings,
    get_settings, record_success, record_error, increment_stats,
)
from config.settings import CHAT_ID, DEFAULT_MAX_PRICE

logger     = logging.getLogger(__name__)
_notify_cb = None
_cycle     = 0   # exposed for /ping and /uptime


def set_notify_callback(fn):
    global _notify_cb
    _notify_cb = fn


async def run_once() -> None:
    global _cycle
    _cycle += 1
    t0 = time.monotonic()
    logger.info("⏳ Cycle #%d — %d sources", _cycle, len(ALL_SCRAPERS))

    # ── 1. Scrape concurrently ────────────────────────────────────────────────
    tasks   = [asyncio.create_task(_safe_scrape(fn)) for fn in ALL_SCRAPERS]
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    listings: list[dict] = []
    for result in batches:
        if isinstance(result, Exception):
            logger.error("Scrape task exception: %s", result)
        elif result:
            listings.extend(result)
    logger.info("📦 Raw: %d", len(listings))

    # ── 2. Load settings ──────────────────────────────────────────────────────
    try:
        settings = await get_settings(CHAT_ID)
    except Exception as e:
        logger.error("get_settings failed: %s — using defaults", e)
        settings = {}

    max_price      = float(settings.get("max_price") or DEFAULT_MAX_PRICE)
    min_rooms      = float(settings.get("min_rooms") or 0)
    active         = bool(settings.get("active", 1))
    wbs_only       = bool(settings.get("wbs_only", 0))
    household_size = int(settings.get("household_size") or 1)
    jobcenter_mode = bool(settings.get("jobcenter_mode", 0))
    wohngeld_mode  = bool(settings.get("wohngeld_mode", 0))
    try:
        areas = json.loads(settings.get("areas") or "[]")
    except Exception:
        areas = []

    if not active:
        try: await increment_stats(cycle=1)
        except Exception: pass
        return

    # ── 3. Filter ─────────────────────────────────────────────────────────────
    pre: list[dict] = []
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
            # Social filters — OR logic: pass if either condition satisfied
            if jobcenter_mode or wohngeld_mode:
                jc_ok = passes_jobcenter(listing, household_size) if jobcenter_mode else False
                wg_ok = passes_wohngeld(listing, household_size)  if wohngeld_mode else False
                if not (jc_ok or wg_ok):
                    continue
            pre.append(listing)
        except Exception as e:
            logger.warning("Filter error: %s", e)

    # Batch dedup (1 query instead of N)
    known_ids  = await are_known([l["id"] for l in pre])
    candidates = [l for l in pre if l["id"] not in known_ids]
    logger.info("🔍 Candidates: %d", len(candidates))

    # ── 4. Enrich (regex only, no external calls except image fetch) ──────────
    enriched: list[dict] = []
    for listing in candidates:

        try:
            listing = enrich(listing)
        except Exception as e:
            logger.warning("enrich %s: %s", listing.get("url","")[:50], e)

        try:
            if not listing.get("wbs_level"):
                listing["wbs_level"] = extract_wbs_level(listing)
        except Exception as e:
            logger.warning("extract_wbs_level: %s", e)

        try:
            if not listing.get("image_url"):
                listing["image_url"] = await fetch_og_image(listing.get("url", ""))
        except Exception:
            listing["image_url"] = None

        try:
            listing["score"]       = score_listing(listing)
            listing["score_label"] = get_score_label(listing["score"])
        except Exception:
            listing["score"] = 0
            listing["score_label"] = "📋 عادي"

        try:
            jc_ok, wg_ok, badge = get_social_badge(listing, household_size)
            listing["jobcenter_ok"]  = jc_ok
            listing["wohngeld_ok"]   = wg_ok
            listing["social_badge"]  = badge
            listing["household_size"] = household_size
        except Exception:
            listing["social_badge"] = ""

        try:
            await save_listing(listing)
        except Exception as e:
            logger.error("save_listing %s: %s", listing.get("id"), e)

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
        logger.error("increment_stats: %s", e)

    try:
        await purge_old_listings()
    except Exception as e:
        logger.error("purge: %s", e)

    logger.info("✅ Cycle #%d %.1fs — sent=%d new=%d raw=%d",
                _cycle, time.monotonic()-t0, sent, len(enriched), len(listings))


async def _safe_scrape(fn) -> list:
    source = fn.__module__.split(".")[-1]
    cb     = get_breaker(source)
    if not cb.allow():
        logger.debug("⚡ CB OPEN — skipping %s", source)
        return []
    try:
        results = await fn()
        cb.record_success()
        await record_success(source, len(results))
        return results or []
    except Exception as e:
        cb.record_failure()
        logger.error("Scraper %s: %s", source, e)
        try: await record_error(source, str(e))
        except Exception: pass
        return []
