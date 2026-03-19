"""
Scheduler — scrape → enrich → filter → dedup → notify.
Respects: sources, areas, price, rooms, WBS, social, quiet hours, max-per-cycle.
"""
import asyncio
import json
import logging
import time
from datetime import datetime

from scrapers import ALL_SCRAPERS
from scrapers.image_fetcher import fetch_og_image
from scrapers.circuit_breaker import get_breaker
from filters import is_wbs, passes_price, passes_rooms, score_listing, get_score_label
from filters.wbs_filter import enrich, extract_wbs_level, passes_area, passes_wbs_level
from filters.social_filter import passes_jobcenter, passes_wohngeld, get_social_badge
from database import (
    are_known, save_listing, purge_old_listings,
    get_settings, record_success, record_error, increment_stats,
)
from config.settings import CHAT_ID, DEFAULT_MAX_PRICE

logger     = logging.getLogger(__name__)
_notify_cb = None
_cycle     = 0


def set_notify_callback(fn):
    global _notify_cb
    _notify_cb = fn


def _in_quiet_hours(quiet_start: int, quiet_end: int) -> bool:
    if quiet_start < 0 or quiet_end < 0:
        return False
    h = datetime.now().hour
    if quiet_start <= quiet_end:
        return quiet_start <= h < quiet_end
    else:  # wraps midnight: e.g. 23→7
        return h >= quiet_start or h < quiet_end


async def run_once() -> None:
    global _cycle
    _cycle += 1
    t0 = time.monotonic()
    logger.info("⏳ Cycle #%d", _cycle)

    # ── Load settings ─────────────────────────────────────────────────────────
    try:
        settings = await get_settings(CHAT_ID)
    except Exception as e:
        logger.error("get_settings: %s", e)
        settings = {}

    active         = bool(settings.get("active", 1))
    max_price      = float(settings.get("max_price") or DEFAULT_MAX_PRICE)
    min_rooms      = float(settings.get("min_rooms") or 0)
    wbs_only       = bool(settings.get("wbs_only", 0))
    wbs_level_min  = int(settings.get("wbs_level_min") or 0)
    wbs_level_max  = int(settings.get("wbs_level_max") or 999)
    household_size = int(settings.get("household_size") or 1)
    jobcenter_mode = bool(settings.get("jobcenter_mode", 0))
    wohngeld_mode  = bool(settings.get("wohngeld_mode", 0))
    quiet_start    = int(settings.get("quiet_start", -1))
    quiet_end      = int(settings.get("quiet_end", -1))
    max_per_cycle  = int(settings.get("max_per_cycle") or 10)

    try:
        enabled_sources = json.loads(settings.get("sources") or "[]")
    except Exception:
        enabled_sources = []
    try:
        areas = json.loads(settings.get("areas") or "[]")
    except Exception:
        areas = []

    if not active:
        try: await increment_stats(cycle=1)
        except Exception: pass
        return

    # ── Quiet hours ───────────────────────────────────────────────────────────
    if _in_quiet_hours(quiet_start, quiet_end):
        logger.info("🌙 Quiet hours — skipping notifications")
        try: await increment_stats(cycle=1)
        except Exception: pass
        return

    # ── Scrape (only enabled sources) ─────────────────────────────────────────
    scrapers_to_run = [
        fn for fn in ALL_SCRAPERS
        if not enabled_sources or fn.__module__.split(".")[-1] in enabled_sources
    ]
    logger.info("🌐 Scraping %d/%d sources", len(scrapers_to_run), len(ALL_SCRAPERS))

    tasks   = [asyncio.create_task(_safe_scrape(fn)) for fn in scrapers_to_run]
    batches = await asyncio.gather(*tasks, return_exceptions=True)
    listings: list[dict] = []
    for result in batches:
        if isinstance(result, Exception):
            logger.error("Scrape task exception: %s", result)
        elif result:
            listings.extend(result)
    logger.info("📦 Raw: %d", len(listings))

    # ── Filter ────────────────────────────────────────────────────────────────
    pre: list[dict] = []
    for listing in listings:
        try:
            if wbs_only and not listing.get("trusted_wbs") and not is_wbs(listing):
                continue
            # WBS level filter (only after enrichment, done here on wbs_label)
            if wbs_only and (wbs_level_min > 0 or wbs_level_max < 999):
                if not passes_wbs_level(listing, wbs_level_min, wbs_level_max):
                    continue
            if not passes_price(listing, max_price):
                continue
            if min_rooms and not passes_rooms(listing, min_rooms):
                continue
            if areas and not passes_area(listing, areas):
                continue
            if jobcenter_mode or wohngeld_mode:
                jc_ok = passes_jobcenter(listing, household_size) if jobcenter_mode else False
                wg_ok = passes_wohngeld(listing, household_size)  if wohngeld_mode else False
                if not (jc_ok or wg_ok):
                    continue
            pre.append(listing)
        except Exception as e:
            logger.warning("Filter error: %s", e)

    known_ids  = await are_known([l["id"] for l in pre])
    candidates = [l for l in pre if l["id"] not in known_ids]
    logger.info("🔍 Candidates: %d", len(candidates))

    # ── Enrich ────────────────────────────────────────────────────────────────
    enriched: list[dict] = []
    for listing in candidates:
        try:    listing = enrich(listing)
        except Exception as e: logger.warning("enrich: %s", e)

        try:
            if not listing.get("wbs_level"):
                listing["wbs_level"] = extract_wbs_level(listing)
        except Exception: pass

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
            jc, wg, badge = get_social_badge(listing, household_size)
            listing["jobcenter_ok"]   = jc
            listing["wohngeld_ok"]    = wg
            listing["social_badge"]   = badge
            listing["household_size"] = household_size
        except Exception:
            listing["social_badge"] = ""

        try:    await save_listing(listing)
        except Exception as e: logger.error("save_listing: %s", e)

        enriched.append(listing)

    enriched.sort(key=lambda x: x.get("score", 0), reverse=True)

    # ── Notify (respect max_per_cycle) ────────────────────────────────────────
    sent   = 0
    to_send = enriched[:max_per_cycle]
    if _notify_cb and to_send:
        for listing in to_send:
            try:
                await _notify_cb(listing)
                sent += 1
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error("notify: %s", e)
        if len(enriched) > max_per_cycle:
            logger.info("📬 Capped at %d/%d (max_per_cycle)", max_per_cycle, len(enriched))

    try:    await increment_stats(sent=sent, cycle=1)
    except Exception as e: logger.error("increment_stats: %s", e)

    try:    await purge_old_listings()
    except Exception as e: logger.error("purge: %s", e)

    logger.info("✅ Cycle #%d %.1fs — sent=%d new=%d raw=%d",
                _cycle, time.monotonic()-t0, sent, len(enriched), len(listings))


async def _safe_scrape(fn) -> list:
    source = fn.__module__.split(".")[-1]
    cb     = get_breaker(source)
    if not cb.allow():
        logger.debug("⚡ CB OPEN — skip %s", source)
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
