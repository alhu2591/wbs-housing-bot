"""
Scrape cycle: overview → dedupe → detail enrich → config filters.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Awaitable

import httpx

from scraper.base_scraper import build_client
from scraper.detail_page import enrich_listings_batch
from scraper.registry import select_scrapers
from utils.filters import passes_filters
from utils.storage import load_seen_ids

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


async def _safe_scrape(fn: Callable[[], Awaitable[list]]) -> list[dict[str, Any]]:
    try:
        res = await fn()
        return res if isinstance(res, list) else []
    except Exception as e:
        logger.error("Scraper %s failed: %s", getattr(fn, "__name__", "<?>"), e)
        return []


async def scrape_new_listings(cfg: dict[str, Any], seen_path: str) -> list[dict[str, Any]]:
    seen = load_seen_ids(seen_path)

    scrapers = select_scrapers(cfg)
    tasks = [asyncio.create_task(_safe_scrape(fn)) for fn in scrapers]
    batches = await asyncio.gather(*tasks)
    raw: list[dict[str, Any]] = []
    for b in batches:
        raw.extend(b)

    by_id: dict[str, dict[str, Any]] = {}
    for listing in raw:
        lid = str(listing.get("id") or "")
        if not lid or lid in by_id or lid in seen:
            continue
        if not _quick_prefilter(listing, cfg):
            continue
        by_id[lid] = listing

    candidates = list(by_id.values())
    if not candidates:
        logger.info("No new listing candidates after overview + dedupe.")
        return []

    detail_conc = int(cfg.get("detail_concurrency") or 4)
    async with build_client() as client:
        enriched = await enrich_listings_batch(client, candidates, concurrency=max(1, detail_conc))

    out: list[dict[str, Any]] = []
    for listing in enriched:
        try:
            if passes_filters(listing, cfg):
                out.append(listing)
        except Exception as e:
            logger.warning("filter error: %s", e)

    out.sort(key=lambda x: (x.get("price") is None, int(x.get("price") or 0)))
    return out
