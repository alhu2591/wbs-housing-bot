"""
scraper/realtime_engine.py — Continuous async scraping loop.
Replaces interval-only scheduler with a real-time loop checking
every 30–90 seconds. Manages source health and auto-disabling.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Awaitable

from database.db import (
    record_source_result, get_disabled_sources,
    set_source_disabled, make_hash, bulk_is_seen, mark_seen,
    save_listing, log_event,
)
from ai.scorer import enrich_listing, classify_listing

logger = logging.getLogger(__name__)

# Seconds between checks (configurable via config)
DEFAULT_INTERVAL = 60
MIN_INTERVAL = 30
MAX_INTERVAL = 120

# Source auto-disable: fail this many times in a row → disable
MAX_CONSECUTIVE_FAILS = 5
# Re-enable after this many minutes
AUTO_RECOVER_MINUTES = 30

_source_fail_count: dict[str, int] = {}
_source_disabled_until: dict[str, float] = {}


def _should_skip_source(source_id: str) -> bool:
    """Check if source is temporarily disabled."""
    until = _source_disabled_until.get(source_id, 0)
    if until and time.time() < until:
        return True
    elif until and time.time() >= until:
        # Auto-recover
        _source_disabled_until.pop(source_id, None)
        _source_fail_count[source_id] = 0
        set_source_disabled(source_id, False)
        logger.info("Auto-recovered source: %s", source_id)
    return False


def _record_fail(source_id: str) -> None:
    count = _source_fail_count.get(source_id, 0) + 1
    _source_fail_count[source_id] = count
    if count >= MAX_CONSECUTIVE_FAILS:
        until = time.time() + AUTO_RECOVER_MINUTES * 60
        _source_disabled_until[source_id] = until
        set_source_disabled(source_id, True)
        logger.warning(
            "Source %s auto-disabled after %d failures. Recovers in %dm.",
            source_id, count, AUTO_RECOVER_MINUTES
        )
        log_event("WARNING", f"Source {source_id} auto-disabled after {count} failures")


def _record_success(source_id: str) -> None:
    _source_fail_count[source_id] = 0


async def _scrape_source_safe(
    source_id: str,
    scrape_fn: Callable,
    cfg: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """Scrape one source with timing, error handling, and stats recording."""
    if _should_skip_source(source_id):
        return []

    async with semaphore:
        start = time.monotonic()
        try:
            results = await asyncio.wait_for(
                asyncio.coroutine(scrape_fn)(cfg) if not asyncio.iscoroutinefunction(scrape_fn)
                else scrape_fn(cfg),
                timeout=30.0
            )
            elapsed_ms = (time.monotonic() - start) * 1000
            _record_success(source_id)
            record_source_result(source_id, True, elapsed_ms)
            logger.debug("Source %s: %d results in %.0fms", source_id, len(results or []), elapsed_ms)
            return results or []
        except asyncio.TimeoutError:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning("Source %s timed out after %.0fms", source_id, elapsed_ms)
            _record_fail(source_id)
            record_source_result(source_id, False, elapsed_ms)
            return []
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.warning("Source %s error: %s", source_id, e)
            _record_fail(source_id)
            record_source_result(source_id, False, elapsed_ms)
            return []


def _filter_and_enrich(
    listings: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply AI classification, scoring, Jobcenter check, and deduplication."""
    if not listings:
        return []

    # Hash-based dedup against DB
    hashes = [make_hash(l) for l in listings]
    seen_set = bulk_is_seen(hashes)

    results = []
    for listing, h in zip(listings, hashes):
        if h in seen_set:
            continue

        # AI enrichment
        enrich_listing(listing, cfg)

        # Drop unsuitable listing types
        if listing.get("ai_suitable") == "no":
            logger.debug("AI rejected [%s]: %s", listing.get("ai_type"), listing.get("title"))
            continue

        # Score threshold — only pass high-quality listings
        min_score = int(cfg.get("min_score", 0))
        if listing.get("score", 0) < min_score:
            logger.debug("Score too low (%d): %s", listing.get("score", 0), listing.get("title"))
            continue

        listing["_hash"] = h
        results.append(listing)

    return results


async def run_realtime_loop(
    get_scrapers: Callable[[], dict[str, Callable]],
    get_cfg: Callable[[], dict[str, Any]],
    on_new_listings: Callable[[list[dict[str, Any]]], Awaitable[None]],
    stop_event: asyncio.Event,
) -> None:
    """
    Main real-time loop. Runs continuously until stop_event is set.
    Calls on_new_listings with enriched, deduplicated listings.
    """
    semaphore = asyncio.Semaphore(5)  # max 5 concurrent source fetches
    logger.info("Real-time engine started.")
    log_event("INFO", "Real-time engine started")

    while not stop_event.is_set():
        cfg = get_cfg()
        interval = max(MIN_INTERVAL, min(MAX_INTERVAL, int(cfg.get("interval_seconds", DEFAULT_INTERVAL))))

        loop_start = time.monotonic()
        scrapers = get_scrapers()

        if not scrapers:
            logger.warning("No scrapers registered.")
            await asyncio.sleep(interval)
            continue

        # Get disabled sources from DB
        db_disabled = get_disabled_sources()
        active_scrapers = {
            sid: fn for sid, fn in scrapers.items()
            if sid not in db_disabled
        }

        logger.info("Loop: checking %d/%d sources…", len(active_scrapers), len(scrapers))

        # Parallel scrape all active sources
        tasks = [
            _scrape_source_safe(sid, fn, cfg, semaphore)
            for sid, fn in active_scrapers.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=False)

        # Flatten results
        all_listings: list[dict[str, Any]] = []
        for batch in results:
            if isinstance(batch, list):
                all_listings.extend(batch)

        logger.info("Loop: %d raw listings collected.", len(all_listings))

        # Filter + enrich
        new_listings = _filter_and_enrich(all_listings, cfg)

        if new_listings:
            logger.info("Loop: %d new matched listings → notify.", len(new_listings))
            try:
                await on_new_listings(new_listings)
                # Mark as seen after successful notification
                for listing in new_listings:
                    h = listing.get("_hash", make_hash(listing))
                    mark_seen(h, listing.get("url", ""))
                    save_listing(listing)
            except Exception as e:
                logger.error("on_new_listings callback error: %s", e, exc_info=True)
                log_event("ERROR", f"Notification callback failed: {e}")
        else:
            logger.info("Loop: no new listings.")

        elapsed = time.monotonic() - loop_start
        sleep_time = max(5.0, interval - elapsed)
        logger.debug("Loop done in %.1fs. Next check in %.0fs.", elapsed, sleep_time)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=sleep_time)
        except asyncio.TimeoutError:
            pass  # Normal — timeout means continue the loop

    logger.info("Real-time engine stopped.")
    log_event("INFO", "Real-time engine stopped")
