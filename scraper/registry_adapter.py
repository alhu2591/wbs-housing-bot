"""
scraper/registry_adapter.py — Wraps existing synchronous scrapers into
async-compatible callables for the real-time engine.

This bridges the existing scraper architecture with the new real-time loop
without breaking any existing functionality.
"""
from __future__ import annotations

import asyncio
import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def wrap_sync(fn: Callable) -> Callable:
    """Wrap a synchronous scraper function as an async coroutine."""
    @functools.wraps(fn)
    async def wrapper(cfg: dict[str, Any]) -> list[dict]:
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(None, functools.partial(fn, cfg))
            return result or []
        except Exception as e:
            logger.warning("Sync scraper %s failed: %s", fn.__name__, e)
            return []
    return wrapper


def get_all_scrapers(cfg: dict[str, Any]) -> dict[str, Callable]:
    """
    Returns a dict of source_id → async scraper function.
    Only returns sources enabled in config.

    This function imports from the existing scraper.registry module and
    wraps each scraper safely for the real-time engine.
    """
    enabled_sources = set(cfg.get("sources") or [])

    try:
        from scraper.registry import SCRAPER_REGISTRY
        scrapers = {}
        for source_id, fn in SCRAPER_REGISTRY.items():
            if enabled_sources and source_id not in enabled_sources:
                continue
            if asyncio.iscoroutinefunction(fn):
                scrapers[source_id] = fn
            else:
                scrapers[source_id] = wrap_sync(fn)
        return scrapers
    except ImportError:
        logger.warning("scraper.registry not found — using pipeline fallback")
        return _pipeline_fallback_scraper(cfg, enabled_sources)


def _pipeline_fallback_scraper(
    cfg: dict[str, Any],
    enabled_sources: set[str],
) -> dict[str, Callable]:
    """
    Fallback: treat the entire pipeline as a single async source.
    Used when scraper.registry is not available.
    """
    async def _pipeline_source(cfg: dict[str, Any]) -> list[dict]:
        from utils.storage import default_seen_path
        from scraper.pipeline import scrape_new_listings
        try:
            seen_path = default_seen_path()
            return await scrape_new_listings(cfg, seen_path)
        except Exception as e:
            logger.error("Pipeline fallback error: %s", e)
            return []

    return {"pipeline": _pipeline_source}
