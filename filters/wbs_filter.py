"""
Smart filtering, scoring, and listing enrichment.
"""
import hashlib
import re
import logging
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs

from config.settings import WBS_KEYWORDS

logger = logging.getLogger(__name__)

# ── Government (trusted) sources ─────────────────────────────────────────────
GOV_SOURCES = {
    "gewobag", "degewo", "howoge", "stadtundland",
    "deutschewohnen", "berlinovo",
}

# ── Urgency signals ───────────────────────────────────────────────────────────
URGENT_KEYWORDS = [
    "ab sofort", "sofort frei", "sofort verfügbar",
    "sofort bezugsfertig", "sofort einziehen",
]

# ── Feature signals ───────────────────────────────────────────────────────────
FEATURE_KEYWORDS = {
    "balkon":     "🌿 بلكونة",
    "terrasse":   "🌿 تراس",
    "garten":     "🌱 حديقة",
    "aufzug":     "🛗 مصعد",
    "fahrstuhl":  "🛗 مصعد",
    "einbauküche":"🍳 مطبخ مجهز",
    "keller":     "📦 مخزن",
    "stellplatz": "🚗 موقف",
    "parkplatz":  "🚗 موقف",
    "barrierefrei": "♿ بدون عوائق",
    "neubau":     "🏗 بناء جديد",
    "erstbezug":  "✨ أول سكن",
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


def passes_area(listing: dict, area: str) -> bool:
    if not area:
        return True
    loc = str(listing.get("location") or "").lower()
    desc = str(listing.get("description") or "").lower()
    title = str(listing.get("title") or "").lower()
    needle = area.lower()
    return needle in loc or needle in desc or needle in title


# ── ID / URL normalization ────────────────────────────────────────────────────

# Query params that are just tracking noise — strip them for stable IDs
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "referrer", "source", "fbclid", "gclid", "_ga", "mc_cid",
}


def normalize_url(url: str) -> str:
    """Remove tracking params so the same listing doesn't get different IDs."""
    try:
        parsed = urlparse(url)
        qs = {k: v for k, v in parse_qs(parsed.query).items()
              if k.lower() not in _TRACKING_PARAMS}
        clean_query = urlencode(qs, doseq=True)
        return urlunparse(parsed._replace(query=clean_query, fragment=""))
    except Exception:
        return url


def make_id(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


# ── Enrichment ────────────────────────────────────────────────────────────────

def extract_size(text: str) -> float | None:
    """Extract m² from any text field."""
    m = re.search(r"(\d[\d\.,]*)\s*m[²2²]", text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(".", "").replace(",", "."))
        except ValueError:
            pass
    return None


def extract_floor(text: str) -> str | None:
    """Extract floor number / description."""
    patterns = [
        r"(\d+)\.\s*(?:ober)?geschoss",
        r"(\d+)\.\s*etage",
        r"erdgeschoss",
        r"eg\b",
        r"dachgeschoss",
        r"dg\b",
    ]
    text_l = text.lower()
    for p in patterns:
        m = re.search(p, text_l)
        if m:
            if "erd" in p or p == r"eg\b":
                return "الطابق الأرضي"
            if "dach" in p or p == r"dg\b":
                return "الطابق العلوي"
            try:
                return f"الطابق {m.group(1)}"
            except IndexError:
                return m.group(0)
    return None


def extract_available(text: str) -> str | None:
    """Extract availability date."""
    text_l = text.lower()
    if any(kw in text_l for kw in URGENT_KEYWORDS):
        return "فوري 🔥"
    m = re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})", text_l)
    if m:
        return f"من {m.group(1)}"
    m = re.search(
        r"ab\s+(januar|februar|märz|april|mai|juni|juli|august|september|oktober|november|dezember)\s*(\d{4})?",
        text_l
    )
    if m:
        months_ar = {
            "januar": "يناير", "februar": "فبراير", "märz": "مارس",
            "april": "أبريل", "mai": "مايو", "juni": "يونيو",
            "juli": "يوليو", "august": "أغسطس", "september": "سبتمبر",
            "oktober": "أكتوبر", "november": "نوفمبر", "dezember": "ديسمبر",
        }
        month_ar = months_ar.get(m.group(1), m.group(1))
        year = m.group(2) or ""
        return f"من {month_ar} {year}".strip()
    return None


def extract_wbs_level(listing: dict) -> str | None:
    """
    Extract WBS level from listing. Returns e.g.:
    'WBS 100', 'WBS 140', 'WBS 160', 'WBS مطلوب', or None.
    """
    import re as _re

    haystack = " ".join(
        str(listing.get(f) or "").lower()
        for f in ("title", "description", "wbs_label", "summary_ar")
    )

    has_wbs_number  = bool(_re.search(r"wbs[\s\-_]*\d{2,3}", haystack))
    has_wbs_keyword = any(kw in haystack for kw in WBS_KEYWORDS)
    is_trusted      = bool(listing.get("trusted_wbs"))

    if not has_wbs_number and not has_wbs_keyword and not is_trusted:
        return None

    # Extract specific number
    m = _re.search(r"wbs[\s\-_]*(\d{2,3})", haystack)
    if m:
        return f"WBS {m.group(1)}"

    return "WBS مطلوب"


def enrich(listing: dict) -> dict:
    """
    Parse size, floor, availability, features from all text fields.
    Adds them to the listing dict in-place and returns it.
    """
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

    listing["features"] = extract_features(all_text)
    listing["is_urgent"] = any(kw in all_text.lower() for kw in URGENT_KEYWORDS)

    # Price per m²
    price = listing.get("price")
    size  = listing.get("size_m2")
    listing["price_per_m2"] = round(price / size, 1) if price and size else None

    return listing


# ── Smart scoring ─────────────────────────────────────────────────────────────

def score_listing(listing: dict) -> int:
    """
    Score 0-30. Higher = better match to show first.
    """
    score = 0

    # Source quality
    if listing.get("trusted_wbs") or listing.get("source", "").lower() in GOV_SOURCES:
        score += 8

    # Price bands
    price = listing.get("price")
    if price:
        if price < 450:   score += 8
        elif price < 500: score += 6
        elif price < 550: score += 4
        elif price < 600: score += 2

    # Rooms
    rooms = listing.get("rooms")
    if rooms:
        if rooms >= 3:   score += 5
        elif rooms >= 2: score += 3
        elif rooms >= 1: score += 1

    # Size
    size = listing.get("size_m2")
    if size:
        if size >= 70:   score += 4
        elif size >= 55: score += 2

    # Urgency = high priority
    if listing.get("is_urgent"):
        score += 4

    # Desirable features
    features = listing.get("features", [])
    score += min(len(features), 3)

    return score


def get_score_label(score: int) -> str:
    if score >= 22:   return "🔥 ممتاز"
    elif score >= 15: return "⭐⭐ جيد جداً"
    elif score >= 8:  return "⭐ جيد"
    else:             return "📋 عادي"
