"""
scraper/registry.py — Central registry of all scraper functions.
Maps source_id strings (from config.json) to async callables.
Existing registry is EXTENDED, not replaced.
"""
from __future__ import annotations
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── Import all scrapers ────────────────────────────────────────────────────
# Each scraper module exposes an async scrape(cfg) function.
# We wrap them with the source_id key used in config.json["sources"].

def _safe_import(module_path: str, fn_name: str) -> Callable | None:
    try:
        import importlib
        mod = importlib.import_module(module_path)
        return getattr(mod, fn_name, None)
    except Exception as e:
        logger.warning("Could not import %s.%s: %s", module_path, fn_name, e)
        return None


# ── Build registry ─────────────────────────────────────────────────────────

def _build_registry() -> dict[str, Callable]:
    reg = {}

    # Public housing (WBS-focused)
    mappings = [
        ("scraper.gewobag", "scrape", "gewobag"),
        ("scraper.degewo", "scrape", "degewo"),
        ("scraper.public_housing", "scrape_howoge", "howoge"),
        ("scraper.public_housing", "scrape_stadtundland", "stadtundland"),
        ("scraper.public_housing", "scrape_wbm", "wbm"),
        ("scraper.public_housing", "scrape_gesobau", "gesobau"),
        ("scraper.public_housing", "scrape_berlinovo", "berlinovo"),
        # Private portals
        ("scraper.private_portals", "scrape_immoscout", "immoscout"),
        ("scraper.private_portals", "scrape_immowelt", "immowelt"),
        ("scraper.private_portals", "scrape_immonet", "immonet"),
        ("scraper.private_portals", "scrape_vonovia", "vonovia"),
        ("scraper.private_portals", "scrape_deutschewohnen", "deutschewohnen"),
        # Classifieds
        ("scraper.classifieds", "scrape_wggesucht", "wggesucht"),
        ("scraper.classifieds", "scrape_ebay_kleinanzeigen", "ebay_kleinanzeigen"),
    ]

    for module, fn_name, source_id in mappings:
        fn = _safe_import(module, fn_name)
        if fn:
            reg[source_id] = fn
        else:
            logger.debug("Scraper not available: %s", source_id)

    logger.info("Registry loaded: %d scrapers", len(reg))
    return reg


SCRAPER_REGISTRY: dict[str, Callable] = _build_registry()


def get_all_scrapers(cfg: dict[str, Any]) -> dict[str, Callable]:
    """
    Return only enabled scrapers per config['sources'].
    Falls back to all if sources list is empty.
    """
    enabled = set(cfg.get("sources") or [])
    if not enabled:
        return dict(SCRAPER_REGISTRY)
    return {sid: fn for sid, fn in SCRAPER_REGISTRY.items() if sid in enabled}


def list_sources() -> list[str]:
    return list(SCRAPER_REGISTRY.keys())
