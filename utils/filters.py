"""
utils/filters.py — Upgraded config filter with Jobcenter rules.
Backward-compatible: apply_filters(listing, cfg) signature preserved.
"""
from __future__ import annotations
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", ".").replace("€", "").replace("m²", "").strip())
    except (ValueError, TypeError):
        return None


def apply_filters(listing: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """
    Returns True if the listing passes all config + Jobcenter filters.
    """
    price = _safe_float(listing.get("price"))
    size = _safe_float(listing.get("size_m2"))
    rooms = _safe_float(listing.get("rooms"))
    location = str(listing.get("location") or "").lower()
    title = str(listing.get("title") or "").lower()
    desc = str(listing.get("description") or "").lower()
    full_text = f"{title} {desc} {location}"

    # ── City filter ────────────────────────────────────────────────────────
    city = str(cfg.get("city") or "").strip().lower()
    if city and city not in full_text and city not in location:
        return False

    # ── Price filter ───────────────────────────────────────────────────────
    max_price = _safe_float(cfg.get("max_price"))
    if max_price and price is not None and price > max_price:
        return False

    # ── Size filter ────────────────────────────────────────────────────────
    min_size = _safe_float(cfg.get("min_size"))
    if min_size and size is not None and size > 0 and size < min_size:
        return False

    # ── Rooms filter ───────────────────────────────────────────────────────
    min_rooms = _safe_float(cfg.get("rooms"))
    if min_rooms and rooms is not None and rooms > 0 and rooms < min_rooms:
        return False

    # ── WBS filter ─────────────────────────────────────────────────────────
    if cfg.get("wbs_required"):
        wbs_keywords = cfg.get("wbs_filter") or ["wbs", "wohnberechtigungsschein", "gefördert"]
        wbs_found = any(kw.lower() in full_text for kw in wbs_keywords)
        wbs_label = str(listing.get("wbs_label") or "").lower()
        wbs_flag = bool(listing.get("wbs_required"))
        if not (wbs_found or wbs_label or wbs_flag):
            return False

    # ── Keywords include ───────────────────────────────────────────────────
    for kw in (cfg.get("keywords_include") or []):
        if kw.lower() not in full_text:
            return False

    # ── Keywords exclude ───────────────────────────────────────────────────
    for kw in (cfg.get("keywords_exclude") or []):
        if kw.lower() in full_text:
            return False

    # ── Jobcenter rules ────────────────────────────────────────────────────
    jc = cfg.get("jobcenter_rules") or {}
    if jc:
        jc_max_rent = _safe_float(jc.get("max_rent"))
        if jc_max_rent and price is not None and price > jc_max_rent:
            # Mark but don't necessarily filter — let AI score handle
            listing["jobcenter_ok"] = False
        else:
            listing["jobcenter_ok"] = listing.get("jobcenter_ok", True)

    return True
