"""
Scrape cycle: overview → dedupe → detail enrich → config filters.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

import httpx

from scraper.base_scraper import build_client
from scraper.detail_page import enrich_listings_batch
from scraper.registry import select_scraper_pairs
from utils.dedup_hash import listing_content_hash, listing_image_fingerprint
from utils.filters import passes_filters
from utils.source_health import is_in_cooldown, record_fail, record_ok
from utils.storage import get_seen_store

logger = logging.getLogger(__name__)


def _quick_prefilter(listing: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """Cheap filter before HTTP detail fetch (price + rough city)."""
    city_cfg = str(cfg.get("city") or "").strip()
    loc = f"{listing.get('location','')} {listing.get('district','')} {listing.get('city','')}".lower()
    if city_cfg:
        if city_cfg.lower() == "berlin":
            if not str(listing.get("location") or listing.get("district") or listing.get("city") or "").strip():
                return False
        elif city_cfg.lower() not in loc:
            return False
    max_price = cfg.get("max_price")
    if max_price is not None:
        p = listing.get("price")
        if p is None:
            return False
        try:
            if int(p) > int(float(max_price)):
                return False
        except Exception:
            return False
    return True


async def _safe_scrape(
    source_id: str,
    fn: Callable[[], Awaitable[list]],
    timeout: float,
    sem: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    if is_in_cooldown(source_id):
        return []
    async with sem:
        try:
            res = await asyncio.wait_for(fn(), timeout=timeout)
            lst = res if isinstance(res, list) else []
            record_ok(source_id)
            return lst
        except asyncio.TimeoutError:
            record_fail(source_id, "timeout")
            logger.error("Scraper %s timed out after %.0fs", source_id, timeout)
            return []
        except Exception as e:
            record_fail(source_id, str(e))
            logger.error("Scraper %s failed: %s", source_id, e)
            return []


async def scrape_new_listings(cfg: dict[str, Any], seen_path: str) -> list[dict[str, Any]]:
    store = get_seen_store()
    seen_ids = store.load_id_set()
    seen_content = store.load_content_hashes()
    seen_img = store.load_image_fingerprints()

    pairs = select_scraper_pairs(cfg)
    timeout = float(cfg.get("source_timeout_seconds") or 90)
    scrape_cap = min(5, max(1, int(cfg.get("scrape_concurrency") or 5)))
    sem = asyncio.Semaphore(scrape_cap)

    tasks = [
        asyncio.create_task(_safe_scrape(sid, fn, timeout, sem))
        for sid, fn in pairs
    ]
    if not tasks:
        logger.info("No scrapers enabled.")
        return []

    batches = await asyncio.gather(*tasks)
    raw: list[dict[str, Any]] = []
    for b in batches:
        raw.extend(b)

    by_id: dict[str, dict[str, Any]] = {}
    batch_hashes: set[str] = set()
    batch_img: set[str] = set()

    for listing in raw:
        lid = str(listing.get("id") or "")
        if not lid or lid in seen_ids or lid in by_id:
            continue
        ch = listing_content_hash(listing)
        if ch in seen_content or ch in batch_hashes:
            continue
        ih = listing_image_fingerprint(listing)
        if ih and (ih in seen_img or ih in batch_img):
            continue
        if not _quick_prefilter(listing, cfg):
            continue

        by_id[lid] = listing
        batch_hashes.add(ch)
        if ih:
            batch_img.add(ih)

    candidates = list(by_id.values())
    if not candidates:
        logger.info("No new listing candidates after overview + dedupe.")
        return []

    detail_conc = min(5, max(1, int(cfg.get("detail_concurrency") or 4)))
    async with build_client() as client:
        enriched = await enrich_listings_batch(
            client, candidates, concurrency=detail_conc, cfg=cfg
        )

    out: list[dict[str, Any]] = []
    for listing in enriched:
        try:
            if passes_filters(listing, cfg):
                out.append(listing)
            else:
                logger.info(
                    "filter drop: %s | %s",
                    (listing.get("title") or "")[:60],
                    listing.get("source"),
                )
        except Exception as e:
            logger.warning("filter error: %s", e)

    out.sort(key=lambda x: (x.get("price") is None, int(x.get("price") or 0)))
    return out
