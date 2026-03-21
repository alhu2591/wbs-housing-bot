"""
Config-driven listing filters.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Sources scraped via WBS-specific endpoints (overview already WBS-oriented)
WBS_TRUSTED_SOURCES = frozenset({
    "gewobag", "degewo", "howoge", "stadtundland", "deutschewohnen",
    "berlinovo", "vonovia", "gesobau", "wbm", "wohnungsgilde",
})

# Canonical Berlin districts (borough-level)
BERLIN_DISTRICT_ALIASES: dict[str, tuple[str, ...]] = {
    "Mitte": ("mitte", "moabit", "wedding", "gesundbrunnen", "tiergarten"),
    "Friedrichshain-Kreuzberg": ("friedrichshain", "kreuzberg"),
    "Pankow": ("pankow", "prenzlauer berg", "weissensee", "weißensee"),
    "Charlottenburg-Wilmersdorf": ("charlottenburg", "wilmersdorf", "halensee", "grunewald"),
    "Spandau": ("spandau",),
    "Steglitz-Zehlendorf": ("steglitz", "zehlendorf", "lankwitz", "dahlem"),
    "Tempelhof-Schoeneberg": ("tempelhof", "schoneberg", "schöneberg", "friedenau"),
    "Neukoelln": ("neukolln", "neukölln", "britz", "rudow"),
    "Treptow-Koepenick": ("treptow", "köpenick", "koepenick", "adlershof"),
    "Marzahn-Hellersdorf": ("marzahn", "hellersdorf"),
    "Lichtenberg": ("lichtenberg", "hohenschonhausen", "hohenschönhausen"),
    "Reinickendorf": ("reinickendorf", "tegel", "hermsdorf"),
}


def _normalize_text(s: str) -> str:
    t = (s or "").lower().strip()
    return (
        t.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def normalize_district_name(value: str) -> str | None:
    v = _normalize_text(value)
    if not v:
        return None
    for canonical, aliases in BERLIN_DISTRICT_ALIASES.items():
        if v == _normalize_text(canonical):
            return canonical
        if any(v == _normalize_text(a) for a in aliases):
            return canonical
    return None


def normalize_districts(values: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values or []:
        c = normalize_district_name(str(raw))
        if not c or c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _matches_any_selected_district(listing: dict[str, Any], selected: list[str]) -> bool:
    if not selected:
        return True
    hay = _normalize_text(
        " ".join(
            [
                str(listing.get("location") or ""),
                str(listing.get("district") or ""),
                str(listing.get("city") or ""),
                str(listing.get("title") or ""),
                str(listing.get("description") or ""),
            ]
        )
    )
    if not hay:
        return False
    for canonical in selected:
        aliases = BERLIN_DISTRICT_ALIASES.get(canonical, ())
        tokens = (canonical,) + tuple(aliases)
        for token in tokens:
            if _normalize_text(token) in hay:
                return True
    return False


_SENIOR_CARE_EXCLUDE = re.compile(
    r"(senioren|seniorenwohn|senioren-?wohnung|altenheim|alten-?wohn|pflege|betreutes wohnen|"
    r"betreute wohnung|demenz|tagespflege|kurzzeitpflege|residenz|pflegeheim)",
    re.I,
)


def _is_senior_care_listing(listing: dict[str, Any]) -> bool:
    return bool(_SENIOR_CARE_EXCLUDE.search(_haystack(listing)))


def _extract_wbs_level(listing: dict[str, Any]) -> int | None:
    existing = listing.get("wbs_level")
    if existing is not None:
        try:
            lvl = int(existing)
            if 80 <= lvl <= 220:
                return lvl
        except Exception:
            pass
    hay = _haystack(listing)
    patterns = (
        r"wbs[\s\-_]*([0-9]{2,3})\b",
        r"\bwbsschein\s*[-]?\s*([0-9]{2,3})\b",
        r"wohnberechtigungsschein\s*[-:/]?\s*([0-9]{2,3})",
        r"\b([0-9]{2,3})\s*(?:€|eur)?\s*wbs\b",
        r"wbs\s*[:#]?\s*([0-9]{2,3})",
    )
    for pat in patterns:
        m = re.search(pat, hay, re.I)
        if not m:
            continue
        try:
            lvl = int(m.group(1))
        except Exception:
            continue
        if 80 <= lvl <= 220:
            return lvl
    return None


def _matches_jobcenter(hay: str) -> bool:
    phrases = (
        "jobcenter",
        "kdu",
        "kosten der unterkunft",
        "uebernahme jobcenter",
        "übernahme jobcenter",
        "buergergeld",
        "bürgergeld",
    )
    return any(p in hay for p in phrases)


def _matches_wohnungsgilde(hay: str) -> bool:
    phrases = (
        "wohnungsgilde",
        "wohnungs gilde",
        "wgilde",
    )
    return any(p in hay for p in phrases)


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


def _listing_price_int(listing: dict[str, Any]) -> int | None:
    p = listing.get("price")
    if p is None:
        return None
    try:
        return int(round(float(p)))
    except Exception:
        return None


def passes_filters(listing: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """Return True if listing satisfies config constraints."""
    if cfg.get("exclude_senior_housing", True) and _is_senior_care_listing(listing):
        logger.info(
            "filter drop (senior/care): %s",
            (listing.get("title") or "")[:80],
        )
        return False

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

    selected_districts = normalize_districts(cfg.get("districts") or [])
    if selected_districts and not _matches_any_selected_district(listing, selected_districts):
        return False

    max_price = cfg.get("max_price")
    if max_price is not None:
        p = _listing_price_int(listing)
        if p is None:
            return False
        try:
            if p > int(round(float(max_price))):
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

    selected_wbs_level = cfg.get("wbs_level")
    if selected_wbs_level is not None:
        try:
            lvl = int(selected_wbs_level)
        except Exception:
            lvl = None
        listing_lvl = _extract_wbs_level(listing)
        # If user requested a WBS level, keep only listings with explicit level <= selected level.
        if lvl is None or listing_lvl is None or listing_lvl > lvl:
            return False

    hay = _haystack(listing)
    if cfg.get("jobcenter_required") and not _matches_jobcenter(hay):
        return False
    if cfg.get("wohnungsgilde_required") and not _matches_wohnungsgilde(hay):
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
