"""
WBS filters, enrichment, and scoring — complete module.
"""
import hashlib
import re
import logging
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs
from config.settings import WBS_KEYWORDS

logger = logging.getLogger(__name__)

GOV_SOURCES = {
    "gewobag", "degewo", "howoge",
    "stadtundland", "deutschewohnen", "berlinovo",
}

URGENT_KEYWORDS = [
    "ab sofort", "sofort frei", "sofort verfügbar",
    "sofort bezugsfertig", "sofort einziehen",
]

FEATURE_KEYWORDS = {
    "balkon":       "بلكونة",
    "terrasse":     "تراس",
    "garten":       "حديقة",
    "aufzug":       "مصعد",
    "fahrstuhl":    "مصعد",        # synonym → same Arabic label
    "einbauküche":  "مطبخ مجهز",
    "keller":       "مخزن",
    "stellplatz":   "موقف سيارة",
    "parkplatz":    "موقف سيارة",  # synonym → same Arabic label
    "barrierefrei": "بدون عوائق",
    "neubau":       "بناء جديد",
    "erstbezug":    "أول سكن",
    "waschmaschine":"غسالة",
    "duschbad":     "حمام إضافي",
}

_TRACKING_PARAMS = {
    "utm_source","utm_medium","utm_campaign","utm_content","utm_term",
    "ref","referrer","source","fbclid","gclid","_ga","mc_cid",
}

_MONTHS_AR = {
    "januar":"يناير","februar":"فبراير","märz":"مارس","april":"أبريل",
    "mai":"مايو","juni":"يونيو","juli":"يوليو","august":"أغسطس",
    "september":"سبتمبر","oktober":"أكتوبر","november":"نوفمبر","dezember":"ديسمبر",
}


# ── Core filters ──────────────────────────────────────────────────────────────

def is_wbs(listing: dict) -> bool:
    haystack = " ".join(
        str(listing.get(f) or "").lower()
        for f in ("title", "description", "wbs_label")
    )
    return any(kw in haystack for kw in WBS_KEYWORDS)


def passes_price(listing: dict, max_price: float) -> bool:
    price = listing.get("price")
    return True if price is None else float(price) <= max_price


def passes_rooms(listing: dict, min_rooms: float) -> bool:
    if not min_rooms:
        return True
    rooms = listing.get("rooms")
    return True if rooms is None else float(rooms) >= float(min_rooms)


def passes_area(listing: dict, areas: list[str]) -> bool:
    """Matches ANY selected area (OR logic). Empty = all Berlin."""
    if not areas:
        return True
    combined = " ".join(
        str(listing.get(f) or "").lower()
        for f in ("location", "district", "description", "title")
    )
    return any(a.lower() in combined for a in areas)


# ── ID / URL normalization ────────────────────────────────────────────────────

def normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        qs = {k: v for k, v in parse_qs(parsed.query).items()
              if k.lower() not in _TRACKING_PARAMS}
        return urlunparse(parsed._replace(query=urlencode(qs, doseq=True), fragment=""))
    except Exception:
        return url


def make_id(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


# ── Extractors ────────────────────────────────────────────────────────────────

def extract_size(text: str) -> float | None:
    # Match formats: 62m², 62 m², 62qm, 62 qm, 62 Quadratmeter
    m = re.search(
        r"(\d[\d\.,]*)\s*(?:m[²2²]|qm\b|quadratmeter)",
        text, re.IGNORECASE,
    )
    if m:
        raw = m.group(1).replace(".", "").replace(",", ".")
        try:
            val = float(raw)
            return val if 10 < val < 500 else None
        except ValueError:
            pass
    return None


def extract_floor(text: str) -> str | None:
    text_l = text.lower()
    patterns = [
        (r"(\d+)\.\s*og\b",              lambda m: f"الطابق {m.group(1)}"),
        (r"(\d+)\.\s*(?:ober)?geschoss", lambda m: f"الطابق {m.group(1)}"),
        (r"(\d+)\.\s*etage",             lambda m: f"الطابق {m.group(1)}"),
        (r"\berdgeschoss\b|\beg\b",      lambda m: "الطابق الأرضي"),
        (r"\bdachgeschoss\b|\bdg\b",     lambda m: "الطابق العلوي"),
    ]
    for pattern, formatter in patterns:
        m = re.search(pattern, text_l)
        if m:
            return formatter(m)
    return None


def extract_available(text: str) -> str | None:
    text_l = text.lower()
    if any(kw in text_l for kw in URGENT_KEYWORDS):
        return "فوري 🔥"
    m = re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})", text_l)
    if m:
        return f"من {m.group(1)}"
    months_pattern = "|".join(_MONTHS_AR.keys())
    m = re.search(rf"ab\s+({months_pattern})\s*(\d{{4}})?", text_l)
    if m:
        month_ar = _MONTHS_AR.get(m.group(1), m.group(1))
        year = m.group(2) or ""
        return f"من {month_ar} {year}".strip()
    return None


def extract_features(text: str) -> list[str]:
    """Return deduplicated Arabic feature labels found in text."""
    text_l = text.lower()
    seen   = set()
    result = []
    for kw, label in FEATURE_KEYWORDS.items():
        if kw in text_l and label not in seen:
            seen.add(label)
            result.append(label)
    return result


def extract_wbs_level(listing: dict) -> str | None:
    """
    Extract WBS level from listing fields (NOT from Arabic summary).
    Returns 'WBS 100', 'WBS 140', ..., 'WBS مطلوب', or None.
    """
    # Only scan German-language fields — not AI-generated Arabic summary
    haystack = " ".join(
        str(listing.get(f) or "").lower()
        for f in ("title", "description", "wbs_label")
    )

    has_number  = bool(re.search(r"wbs[\s\-_]*\d{2,3}", haystack))
    has_keyword = any(kw in haystack for kw in WBS_KEYWORDS)
    is_trusted  = bool(listing.get("trusted_wbs"))

    if not has_number and not has_keyword and not is_trusted:
        return None

    m = re.search(r"wbs[\s\-_]*(\d{2,3})", haystack)
    if m:
        return f"WBS {m.group(1)}"

    return "WBS مطلوب"


def enrich(listing: dict) -> dict:
    """Extract size, floor, availability, features, price/m² from text."""
    all_text = " ".join(
        str(listing.get(f) or "")
        for f in ("title", "description", "location")
    )

    if not listing.get("size_m2"):
        listing["size_m2"] = extract_size(all_text)
    if not listing.get("floor"):
        listing["floor"] = extract_floor(all_text)
    if not listing.get("available_from"):
        listing["available_from"] = extract_available(all_text)

    listing["features"]  = extract_features(all_text)
    listing["is_urgent"] = any(kw in all_text.lower() for kw in URGENT_KEYWORDS)

    price = listing.get("price")
    size  = listing.get("size_m2")
    listing["price_per_m2"] = round(price / size, 1) if price and size else None

    return listing


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_listing(listing: dict) -> int:
    """Score 0–32. Higher = notify first."""
    score = 0
    if listing.get("trusted_wbs") or listing.get("source", "").lower() in GOV_SOURCES:
        score += 8
    price = listing.get("price")
    if price:
        if price < 450:   score += 8
        elif price < 500: score += 6
        elif price < 550: score += 4
        elif price < 600: score += 2
    rooms = listing.get("rooms")
    if rooms:
        if rooms >= 3:   score += 5
        elif rooms >= 2: score += 3
        elif rooms >= 1: score += 1
    size = listing.get("size_m2")
    if size:
        if size >= 70:   score += 4
        elif size >= 55: score += 2
    if listing.get("is_urgent"):
        score += 4
    score += min(len(listing.get("features") or []), 3)
    return score


def get_score_label(score: int) -> str:
    if score >= 22:   return "🔥 ممتاز"
    elif score >= 15: return "⭐⭐ جيد جداً"
    elif score >= 8:  return "⭐ جيد"
    else:             return "📋 عادي"
