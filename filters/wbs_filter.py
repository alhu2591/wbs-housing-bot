"""
WBS filters, enrichment, and scoring — comprehensive extraction.
Handles all German listing formats across 13 sources.
"""
import hashlib
import re
import logging
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs
from config.settings import WBS_KEYWORDS

logger = logging.getLogger(__name__)

GOV_SOURCES = {
    "gewobag", "degewo", "howoge", "stadtundland", "deutschewohnen",
    "berlinovo", "vonovia", "gesobau", "wbm",
}

URGENT_KEYWORDS = [
    "ab sofort", "sofort frei", "sofort verfügbar", "sofort bezugsfertig",
    "sofort einziehen", "sofort beziehbar", "ab sofort frei",
]

# Comprehensive feature detection
FEATURE_KEYWORDS = {
    "balkon":          "🌿 بلكونة",
    "terrasse":        "🌿 تراس",
    "dachterrasse":    "🌿 تراس علوي",
    "loggia":          "🌿 لوجيا",
    "garten":          "🌱 حديقة",
    "gemeinschaftsgarten": "🌱 حديقة مشتركة",
    "aufzug":          "🛗 مصعد",
    "fahrstuhl":       "🛗 مصعد",
    "lift":            "🛗 مصعد",
    "einbauküche":     "🍳 مطبخ مجهز",
    "einbaukuche":     "🍳 مطبخ مجهز",
    "küche":           "🍳 مطبخ",
    "keller":          "📦 مخزن",
    "abstellraum":     "📦 مخزن",
    "abstellkammer":   "📦 غرفة تخزين",
    "stellplatz":      "🚗 موقف",
    "parkplatz":       "🚗 موقف",
    "tiefgarage":      "🚗 جراج أرضي",
    "garage":          "🚗 جراج",
    "fahrradkeller":   "🚲 تخزين دراجات",
    "waschmaschine":   "🫧 غسالة",
    "waschraum":       "🫧 غسالة مشتركة",
    "barrierefrei":    "♿ بدون عوائق",
    "rollstuhl":       "♿ مناسب للكرسي المتحرك",
    "neubau":          "🏗 بناء جديد",
    "erstbezug":       "✨ أول سكن",
    "erstbezug nach sanierung": "✨ مجدد",
    "saniert":         "🔨 مجدد",
    "fußbodenheizung": "🌡 تدفئة أرضية",
    "fernwärme":       "🌡 تدفئة مركزية",
    "einzel":          "🏠 مبنى مستقل",
    "dachgeschoss":    "🏠 علوي",
    "penthouse":       "🏠 بنتهاوس",
    "laminat":         "🪵 أرضية خشبية",
    "parkett":         "🪵 باركيه",
    "fliesen":         "🟩 بلاط",
    "duschbad":        "🚿 دش",
    "badewanne":       "🛁 حوض استحمام",
    "sep. wc":         "🚽 حمام منفصل",
    "rolladen":        "🪟 شرائح ستائر",
    "videogegensprechanlage": "📹 إنترفون مرئي",
    "gegensprechanlage": "🔔 جرس باب",
}

_TRACKING_PARAMS = {
    "utm_source","utm_medium","utm_campaign","utm_content","utm_term",
    "ref","referrer","source","fbclid","gclid","_ga","mc_cid","tracking",
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
    if not min_rooms: return True
    rooms = listing.get("rooms")
    return True if rooms is None else float(rooms) >= float(min_rooms)


def passes_area(listing: dict, areas: list) -> bool:
    if not areas: return True
    combined = " ".join(
        str(listing.get(f) or "").lower()
        for f in ("location", "district", "description", "title")
    )
    return any(a.lower() in combined for a in areas)


def passes_wbs_level(listing: dict, min_level: int, max_level: int) -> bool:
    """Filter by WBS level range. Returns True if level unknown (trusted)."""
    wbs_level = listing.get("wbs_level")
    if not wbs_level: return True
    # Extract number from "WBS 100"
    m = re.search(r"(\d{2,3})", str(wbs_level))
    if not m: return True
    level = int(m.group(1))
    return min_level <= level <= max_level


# ── URL helpers ───────────────────────────────────────────────────────────────

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


# ── Comprehensive extractors ──────────────────────────────────────────────────

def extract_size(text: str) -> float | None:
    """Extract apartment size from German text. Handles all common formats."""
    patterns = [
        r"(\d[\d\.,]*)\s*(?:m[²2²]|qm\b|quadratmeter)",
        r"wohnfläche[:\s]+(\d[\d\.,]*)\s*(?:m[²2²]|qm)?",
        r"ca\.?\s*(\d[\d\.,]*)\s*(?:m[²2²]|qm)",
        r"(\d[\d\.,]*)\s*(?:m[²2²]|qm)\s*wohnfläche",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            raw = m.group(1).replace(".", "").replace(",", ".")
            try:
                val = float(raw)
                if 10 < val < 500:
                    return val
            except ValueError:
                pass
    return None


def extract_floor(text: str) -> str | None:
    """Extract floor from German text. Handles OG, EG, DG, Stock, Etage."""
    text_l = text.lower()
    patterns = [
        (r"(\d+)\.\s*og\b",               lambda m: f"الطابق {m.group(1)}"),
        (r"(\d+)\.\s*(?:ober)?geschoss",  lambda m: f"الطابق {m.group(1)}"),
        (r"(\d+)\.\s*etage",              lambda m: f"الطابق {m.group(1)}"),
        (r"(\d+)\.\s*stock\b",            lambda m: f"الطابق {m.group(1)}"),
        (r"im\s+(\d+)\.\s*(?:og|stock|etage|geschoss)", lambda m: f"الطابق {m.group(1)}"),
        (r"\bhochparterre\b",             lambda _: "الطابق الأرضي المرتفع"),
        (r"\berdgeschoss\b|\beg\b",       lambda _: "الطابق الأرضي"),
        (r"\bdachgeschoss\b|\bdg\b",      lambda _: "الطابق العلوي"),
        (r"\bpenthouse\b",                lambda _: "بنتهاوس"),
    ]
    for pattern, formatter in patterns:
        m = re.search(pattern, text_l)
        if m:
            return formatter(m)
    return None


def extract_available(text: str) -> str | None:
    """Extract availability date from German text."""
    text_l = text.lower()
    if any(kw in text_l for kw in URGENT_KEYWORDS):
        return "فوري 🔥"
    # Date format: DD.MM.YYYY or DD/MM/YYYY
    m = re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})", text_l)
    if m: return f"من {m.group(1)}"
    # Quarter: Q1/Q2/2025
    m = re.search(r"(?:ab\s+)?q([1-4])[./\s]*(\d{4})", text_l)
    if m:
        quarter_ar = {"1":"الربع الأول","2":"الربع الثاني","3":"الربع الثالث","4":"الربع الرابع"}
        return f"{quarter_ar[m.group(1)]} {m.group(2)}"
    # Month name
    months_pattern = "|".join(_MONTHS_AR.keys())
    m = re.search(rf"(?:ab\s+)?({months_pattern})\s*(\d{{4}})?", text_l)
    if m:
        month_ar = _MONTHS_AR.get(m.group(1), m.group(1))
        year = m.group(2) or ""
        return f"من {month_ar} {year}".strip()
    # "nach vereinbarung"
    if "nach vereinbarung" in text_l or "nach absprache" in text_l:
        return "بالاتفاق"
    return None


def extract_features(text: str) -> list[str]:
    """Extract Arabic feature labels from German listing text. Deduplicated."""
    text_l = text.lower()
    seen   = set()
    result = []
    for kw, label in FEATURE_KEYWORDS.items():
        if kw in text_l and label not in seen:
            seen.add(label)
            result.append(label)
    return result


def extract_heating(text: str) -> str | None:
    """Extract heating type."""
    text_l = text.lower()
    if "fußbodenheizung" in text_l: return "تدفئة أرضية"
    if "fernwärme" in text_l: return "تدفئة مركزية"
    if "gasheizung" in text_l or "gas" in text_l: return "تدفئة غاز"
    if "ölheizung" in text_l: return "تدفئة زيت"
    if "elektroheizung" in text_l: return "تدفئة كهربائي"
    return None


def extract_deposit(text: str) -> str | None:
    """Extract deposit (Kaution) amount."""
    m = re.search(r"kaution[:\s]*(\d[\d\.,]*)\s*€?", text, re.IGNORECASE)
    if m:
        from scrapers._common import parse_price
        val = parse_price(m.group(1) + " €")
        if val: return f"{val:.0f} €"
    # "3 Monatsmieten" pattern
    m = re.search(r"(\d)\s*monatsmieten?\s*(?:kaution)?", text, re.IGNORECASE)
    if m: return f"{m.group(1)} × الإيجار"
    return None


def extract_wbs_level(listing: dict) -> str | None:
    """
    Extract WBS level. Scans German fields only (not Arabic summary).
    Returns: 'WBS 100', 'WBS 140', ..., 'WBS مطلوب', or None.
    """
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
    """
    Extract all structured data from listing text fields.
    Modifies listing in-place, returns it.
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

    listing["features"]  = extract_features(all_text)
    listing["is_urgent"] = any(kw in all_text.lower() for kw in URGENT_KEYWORDS)

    # heating + deposit (extra info)
    if not listing.get("heating"):
        listing["heating"] = extract_heating(all_text)
    if not listing.get("deposit"):
        listing["deposit"] = extract_deposit(all_text)

    # Price per m²
    price = listing.get("price")
    size  = listing.get("size_m2")
    listing["price_per_m2"] = round(price / size, 1) if price and size else None

    return listing


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_listing(listing: dict) -> int:
    score = 0
    if listing.get("trusted_wbs") or listing.get("source","").lower() in GOV_SOURCES:
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
    if listing.get("is_urgent"):   score += 4
    score += min(len(listing.get("features") or []), 3)
    return score


def get_score_label(score: int) -> str:
    if score >= 22:   return "🔥 ممتاز"
    elif score >= 15: return "⭐⭐ جيد جداً"
    elif score >= 8:  return "⭐ جيد"
    else:             return "📋 عادي"
