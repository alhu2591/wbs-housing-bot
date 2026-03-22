"""
scraper/pipeline.py — Upgraded pipeline with AI enrichment + SQLite dedup.
Backward-compatible with existing scraper modules.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from utils.filters import apply_filters

logger = logging.getLogger(__name__)


async def scrape_new_listings(
    cfg: dict[str, Any],
    seen_path: str,
) -> list[dict[str, Any]]:
    start = time.monotonic()

    raw_listings = await _run_all_scrapers(cfg)
    logger.info("Pipeline: %d raw listings from scrapers.", len(raw_listings))
    if not raw_listings:
        return []

    unseen = _deduplicate(raw_listings)
    logger.info("Pipeline: %d unseen after dedup.", len(unseen))
    if not unseen:
        return []

    concurrency = int(cfg.get("detail_concurrency") or 4)
    enriched = await _enrich_all(unseen, cfg, concurrency)
    logger.info("Pipeline: %d enriched.", len(enriched))

    filtered = [l for l in enriched if apply_filters(l, cfg)]
    logger.info("Pipeline: %d after config filters.", len(filtered))

    try:
        from ai.scorer import enrich_listing
        for listing in filtered:
            enrich_listing(listing, cfg)
    except ImportError:
        logger.debug("ai.scorer not available — skipping AI enrichment.")

    filtered.sort(key=lambda l: l.get("score", 0), reverse=True)
    logger.info("Pipeline done: %d matches in %.1fs.", len(filtered), time.monotonic() - start)
    return filtered


async def _run_all_scrapers(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from scraper.registry_adapter import get_all_scrapers
        scrapers = get_all_scrapers(cfg)
    except ImportError:
        try:
            from scraper.registry import SCRAPER_REGISTRY
            scrapers = SCRAPER_REGISTRY
        except ImportError:
            logger.warning("No scraper registry found.")
            return []

    if not scrapers:
        return []

    semaphore = asyncio.Semaphore(5)

    async def _safe_scrape(source_id: str, fn) -> list[dict]:
        async with semaphore:
            try:
                if asyncio.iscoroutinefunction(fn):
                    return await asyncio.wait_for(fn(cfg), timeout=30)
                else:
                    import functools
                    loop = asyncio.get_event_loop()
                    return await loop.run_in_executor(None, functools.partial(fn, cfg))
            except asyncio.TimeoutError:
                logger.warning("Scraper %s timed out.", source_id)
                return []
            except Exception as e:
                logger.warning("Scraper %s error: %s", source_id, e)
                return []

    tasks = [_safe_scrape(sid, fn) for sid, fn in scrapers.items()]
    results = await asyncio.gather(*tasks)
    all_listings: list[dict] = []
    for batch in results:
        if isinstance(batch, list):
            all_listings.extend(batch)
    return all_listings


def _deduplicate(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        from database.db import make_hash, bulk_is_seen
        hashes = [make_hash(l) for l in listings]
        seen_set = bulk_is_seen(hashes)
        result = []
        for listing, h in zip(listings, hashes):
            if h not in seen_set:
                listing["_hash"] = h
                result.append(listing)
        return result
    except Exception as e:
        logger.warning("SQLite dedup failed, using JSON fallback: %s", e)
        return listings


async def _enrich_all(
    listings: list[dict[str, Any]],
    cfg: dict[str, Any],
    concurrency: int,
) -> list[dict[str, Any]]:
    try:
        from scraper.detail_page import enrich_listing_detail
    except ImportError:
        return listings

    semaphore = asyncio.Semaphore(concurrency)

    async def _safe_enrich(listing: dict) -> dict:
        async with semaphore:
            try:
                return await enrich_listing_detail(listing, cfg) or listing
            except Exception:
                return listing

    results = await asyncio.gather(*[_safe_enrich(l) for l in listings])
    return list(results)
