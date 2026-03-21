from __future__ import annotations

import asyncio
import logging
from typing import Any

from scrapers import ALL_SCRAPERS
from utils.seen_store import load_seen_ids

logger = logging.getLogger(__name__)


def _matches_wbs(listing: dict[str, Any], wbs_filter: list[str]) -> bool:
    if not wbs_filter:
        return True

    hay = " ".join(
        str(listing.get(k) or "")
        for k in ("title", "description", "wbs_label", "location")
    ).lower()

    return any(kw.lower() in hay for kw in wbs_filter)


def _matches_filters(listing: dict[str, Any], cfg: dict[str, Any]) -> bool:
    price = listing.get("price")
    if price is None:
        return False
    try:
        if float(price) > float(cfg["max_price"]):
            return False
    except Exception:
        return False

    city = str(cfg.get("city") or "").strip()
    loc = str(listing.get("location") or listing.get("district") or "").strip()
    if city:
        if city.lower() == "berlin":
            if not loc:
                return False
        else:
            if city.lower() not in loc.lower():
                return False

    return _matches_wbs(listing, cfg.get("wbs_filter") or [])


def _to_notification(listing: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": listing.get("id"),
        "title": listing.get("title") or "",
        "price": listing.get("price"),
        "location": listing.get("location") or listing.get("district") or "",
        "url": listing.get("url") or "",
    }


async def _safe_scrape(source_fn) -> list[dict[str, Any]]:
    try:
        res = await source_fn()
        return res if isinstance(res, list) else []
    except Exception as e:
        logger.error("Scraper %s failed: %s", getattr(source_fn, "__name__", "<?>"), e)
        return []


async def scrape_new_listings(cfg: dict[str, Any], seen_json_path: str) -> list[dict[str, Any]]:
    """Scrape sources, filter, and dedup against `seen.json`."""
    seen_ids = load_seen_ids(seen_json_path)

    tasks = [asyncio.create_task(_safe_scrape(fn)) for fn in ALL_SCRAPERS]
    batches = await asyncio.gather(*tasks, return_exceptions=False)

    raw: list[dict[str, Any]] = []
    for batch in batches:
        raw.extend(batch)

    # Dedup within a single cycle by listing id
    by_id: dict[str, dict[str, Any]] = {}
    for listing in raw:
        lid = str(listing.get("id") or "")
        if not lid or lid in by_id:
            continue
        if lid in seen_ids:
            continue
        if not _matches_filters(listing, cfg):
            continue
        by_id[lid] = listing

    out = [_to_notification(l) for l in by_id.values()]
    # Keep order stable-ish
    out.sort(key=lambda x: (x.get("price") is None, float(x.get("price") or 0)), reverse=False)
    return out

