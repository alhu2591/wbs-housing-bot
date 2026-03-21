"""
Config-driven listing filters.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Sources scraped via WBS-specific endpoints (overview already WBS-oriented)
WBS_TRUSTED_SOURCES = frozenset({
    "gewobag", "degewo", "howoge", "stadtundland", "deutschewohnen",
    "berlinovo", "vonovia", "gesobau", "wbm",
})


def _haystack(listing: dict[str, Any]) -> str:
    parts = [
        str(listing.get("title") or ""),
        str(listing.get("location") or ""),
        str(listing.get("district") or ""),
        str(listing.get("city") or ""),
        str(listing.get("description") or ""),
        str(listing.get("wbs_label") or ""),
    ]
    return " ".join(parts).lower()


def passes_filters(listing: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """Return True if listing satisfies config constraints."""
    city_cfg = str(cfg.get("city") or "").strip()
    loc = str(listing.get("location") or "")
    dist = str(listing.get("district") or "")
    city_l = str(listing.get("city") or "")
    combined_loc = f"{loc} {dist} {city_l}".lower()

    if city_cfg:
        if city_cfg.lower() == "berlin":
            if not (loc.strip() or dist.strip() or city_l.strip()):
                return False
        elif city_cfg.lower() not in combined_loc:
            return False

    max_price = cfg.get("max_price")
    if max_price is not None:
        price = listing.get("price")
        if price is None:
            return False
        try:
            p = int(price)
            if p > int(float(max_price)):
                return False
        except Exception:
            return False

    min_size = cfg.get("min_size")
    if min_size is not None:
        try:
            ms = float(min_size)
            sz = listing.get("size_m2")
            if sz is None or float(sz) < ms:
                return False
        except Exception:
            pass

    min_rooms = cfg.get("rooms")
    if min_rooms is not None:
        try:
            mr = float(min_rooms)
            r = listing.get("rooms")
            if r is None or float(r) < mr:
                return False
        except Exception:
            pass

    if cfg.get("wbs_required"):
        src = str(listing.get("source") or "").lower()
        if (
            listing.get("trusted_wbs")
            or (listing.get("wbs_label") or "").strip()
            or src in WBS_TRUSTED_SOURCES
        ):
            pass
        else:
            hay = _haystack(listing)
            extra = cfg.get("wbs_filter") or []
            phrases = [
                "wbs", "wohnberechtigung", "gefördert", "sozialer wohnungsbau",
                "öffentlich gefördert",
            ]
            phrases.extend(str(x).lower() for x in extra if x)
            if not any(p in hay for p in phrases):
                return False

    for kw in cfg.get("keywords_include") or []:
        k = str(kw).strip().lower()
        if k and k not in _haystack(listing):
            return False

    for kw in cfg.get("keywords_exclude") or []:
        k = str(kw).strip().lower()
        if k and k in _haystack(listing):
            return False

    return True
