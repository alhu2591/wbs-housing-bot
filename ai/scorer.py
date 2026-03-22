"""
ai/scorer.py — AI scoring & NLP classification engine.
Scores listings 0–100 and classifies listing type without heavy ML deps.
Termux-friendly: pure Python + regex keyword approach.
"""
from __future__ import annotations

import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

# ── NLP Classification Keywords ────────────────────────────────────────────

_WG_PATTERNS = [
    r'\bwg\b', r'wohngemeinschaft', r'mitbewohner', r'zimmer in', r'wg-zimmer',
    r'shared', r'flatshare', r'mitbewohnerin',
]

_SENIOREN_PATTERNS = [
    r'senioren', r'seniorenresidenz', r'betreutes wohnen', r'altersgerecht',
    r'pflegeheim', r'55\+', r'60\+', r'rentner', r'altenwohnheim',
]

_TEMP_PATTERNS = [
    r'zwischenmiete', r'zeitlich begrenzt', r'auf zeit', r'kurzzeitmiete',
    r'temporary', r'kurzfristig', r'befristet', r'urlaubswohnung',
    r'ferienwohnung', r'airbnb', r'untermiete', r'1 monat', r'2 monate',
    r'3 monate',
]

_COMMERCIAL_PATTERNS = [
    r'gewerbe', r'büro', r'office', r'lager', r'werkstatt', r'laden',
    r'praxis', r'atelier', r'studio \(gewerbe\)',
]


def _match_any(text: str, patterns: list[str]) -> bool:
    t = text.lower()
    return any(re.search(p, t) for p in patterns)


def classify_listing(listing: dict[str, Any]) -> dict[str, str]:
    """
    Returns classification dict:
      type: 'wg' | 'senioren' | 'temporary' | 'commercial' | 'normal'
      suitable: 'yes' | 'no' | 'maybe'
    """
    text = " ".join([
        str(listing.get("title") or ""),
        str(listing.get("description") or ""),
        str(listing.get("location") or ""),
    ])

    if _match_any(text, _COMMERCIAL_PATTERNS):
        return {"type": "commercial", "suitable": "no"}
    if _match_any(text, _WG_PATTERNS):
        return {"type": "wg", "suitable": "no"}
    if _match_any(text, _SENIOREN_PATTERNS):
        return {"type": "senioren", "suitable": "no"}
    if _match_any(text, _TEMP_PATTERNS):
        return {"type": "temporary", "suitable": "maybe"}

    return {"type": "normal", "suitable": "yes"}


# ── Scoring Engine ──────────────────────────────────────────────────────────

def score_listing(listing: dict[str, Any], cfg: dict[str, Any]) -> int:
    """
    Score a listing 0–100 based on:
      - Price vs Jobcenter limit (30 pts)
      - WBS compatibility (25 pts)
      - Size fit (20 pts)
      - Room count fit (15 pts)
      - Location relevance (10 pts)
    """
    score = 0
    jc = cfg.get("jobcenter_rules", {})
    max_rent = float(jc.get("max_rent") or cfg.get("max_price") or 9999)
    ideal_size = float(jc.get("max_size") or cfg.get("min_size") or 30)
    ideal_rooms = float(jc.get("rooms") or cfg.get("rooms") or 1)
    city = str(cfg.get("city") or "Berlin").lower()

    # ── Price score (30 pts) ────────────────────────────────────────────────
    price_raw = listing.get("price")
    try:
        price = float(str(price_raw).replace(",", ".").replace("€", "").strip())
        if price <= 0:
            score += 0
        elif price <= max_rent * 0.8:
            score += 30  # well under limit
        elif price <= max_rent:
            score += 22  # within limit
        elif price <= max_rent * 1.1:
            score += 10  # slightly over
        else:
            score += 0   # too expensive
    except (ValueError, TypeError):
        score += 10  # unknown price = neutral

    # ── WBS compatibility (25 pts) ─────────────────────────────────────────
    wbs_label = str(listing.get("wbs_label") or "").lower()
    wbs_required = bool(listing.get("wbs_required"))
    if wbs_required or "wbs" in wbs_label or "wohnberechtigungsschein" in wbs_label:
        score += 25
    elif "gefördert" in wbs_label or "sozial" in wbs_label:
        score += 18
    elif cfg.get("wbs_required"):
        score += 0  # wbs required in config but not found
    else:
        score += 12  # no wbs needed and config doesn't require it

    # ── Size score (20 pts) ────────────────────────────────────────────────
    size_raw = listing.get("size_m2")
    try:
        size = float(str(size_raw).replace(",", ".").strip())
        if size >= ideal_size and size <= ideal_size * 2:
            score += 20
        elif size >= ideal_size * 0.8:
            score += 14
        elif size > 0:
            score += 6
    except (ValueError, TypeError):
        score += 8  # unknown size = neutral

    # ── Rooms score (15 pts) ───────────────────────────────────────────────
    rooms_raw = listing.get("rooms")
    try:
        rooms = float(str(rooms_raw).replace(",", ".").strip())
        if rooms >= ideal_rooms:
            score += 15
        elif rooms >= ideal_rooms - 0.5:
            score += 10
        else:
            score += 4
    except (ValueError, TypeError):
        score += 6

    # ── Location score (10 pts) ────────────────────────────────────────────
    location = str(listing.get("location") or "").lower()
    if city in location:
        score += 10
    elif location:
        score += 5

    return min(100, max(0, score))


def jobcenter_check(listing: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """Returns True if listing is within Jobcenter limits."""
    jc = cfg.get("jobcenter_rules", {})
    if not jc:
        return True

    max_rent = jc.get("max_rent")
    max_size = jc.get("max_size")
    req_rooms = jc.get("rooms")

    try:
        if max_rent:
            price = float(str(listing.get("price") or 0).replace(",", ".").replace("€", ""))
            if price > float(max_rent):
                return False
    except (ValueError, TypeError):
        pass

    try:
        if max_size:
            size = float(str(listing.get("size_m2") or 0).replace(",", "."))
            if size > float(max_size) and size > 0:
                return False
    except (ValueError, TypeError):
        pass

    try:
        if req_rooms:
            rooms = float(str(listing.get("rooms") or 0).replace(",", "."))
            if rooms < float(req_rooms) and rooms > 0:
                return False
    except (ValueError, TypeError):
        pass

    return True


def enrich_listing(listing: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Add score, classification, and Jobcenter status to a listing dict."""
    classification = classify_listing(listing)
    listing["ai_type"] = classification["type"]
    listing["ai_suitable"] = classification["suitable"]
    listing["score"] = score_listing(listing, cfg)
    listing["jobcenter_ok"] = jobcenter_check(listing, cfg)
    return listing
