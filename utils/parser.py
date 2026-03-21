"""
Text/HTML parsing: prices (→ int €), rooms, size m², WBS detection, listing builder.
Termux-safe: uses stdlib + beautifulsoup4 only.
"""
from __future__ import annotations

import hashlib
import re
import logging
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs, urljoin

logger = logging.getLogger(__name__)

_NON_PRICE = re.compile(r"^(preis auf anfrage|auf anfrage|n\.a\.|nan|none|-|—|–)$", re.I)

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "referrer", "source", "fbclid", "gclid", "_ga", "mc_cid", "tracking",
}

# German WBS / social housing phrases (for detection)
DEFAULT_WBS_PHRASES = [
    "wbs erforderlich", "nur mit wbs", "wohnberechtigungsschein",
    "wbs-berechtigung", "wbs voraussetzung", "sozialer wohnungsbau",
    "geförderte wohnung", "öffentlich gefördert", "mit wbs",
    "wbs notwendig", "wbs benötigt", "wbs vorlegen", "wbs pflicht",
    "wbs 100", "wbs100", "wbs 140", "wbs140", "wbs 160", "wbs 180", "wbs 200",
]


def extract_wbs_level(text: str) -> int | None:
    if not text:
        return None
    m = re.search(r"wbs[\s\-_]*([0-9]{2,3})", text, re.I)
    if not m:
        return None
    try:
        level = int(m.group(1))
    except Exception:
        return None
    if 80 <= level <= 220:
        return level
    return None


def normalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        qs = {
            k: v
            for k, v in parse_qs(parsed.query).items()
            if k.lower() not in _TRACKING_PARAMS
        }
        return urlunparse(parsed._replace(query=urlencode(qs, doseq=True), fragment=""))
    except Exception:
        return url


def make_id(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


def clean_text(text: str, max_len: int = 500) -> str:
    if not text:
        return ""
    t = str(text)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"\s*\|\s*", ", ", t)
    t = re.sub(r",\s*,+", ",", t)
    t = t.strip(" ,|•–-/")
    return t[:max_len].strip()


def parse_price_eur(raw) -> int | None:
    """Return monthly rent as integer EUR, or None."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        v = float(raw)
        return int(round(v)) if 50 < v < 5000 else None
    s = str(raw).replace("€", "").replace("EUR", "").replace("\xa0", "").replace("\u202f", "").strip()
    if not s or _NON_PRICE.match(s):
        return None
    s = re.sub(r"^[a-zäöüß\s\.]+", "", s, flags=re.I)
    s = re.sub(r"[^0-9\.,]", "", s)
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isdigit():
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isdigit():
            s = s.replace(".", "")
    s = s.rstrip(",- ")
    try:
        val = float(s)
        if 50 < val < 5000:
            return int(round(val))
    except (ValueError, TypeError):
        pass
    return None


# Alias for site scrapers (historical name)
def parse_price(raw) -> int | None:
    return parse_price_eur(raw)


def parse_rooms(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace(",", ".").strip()
    m = re.search(r"\d+\.?\d*", s)
    try:
        val = float(m.group()) if m else None
        return val if val and 0.5 <= val <= 20 else None
    except (ValueError, TypeError):
        return None


def parse_size_m2(text: str) -> float | None:
    if not text:
        return None
    patterns = [
        r"(\d[\d\.,]*)\s*(?:m[²2²]|qm\b|quadratmeter)",
        r"wohnfläche[:\s]+(\d[\d\.,]*)\s*(?:m[²2²]|qm)?",
        r"ca\.?\s*(\d[\d\.,]*)\s*(?:m[²2²]|qm)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            raw = m.group(1).replace(".", "").replace(",", ".")
            try:
                v = float(raw)
                if 10 < v < 500:
                    return v
            except ValueError:
                pass
    return None


def detect_wbs(text: str, extra_phrases: list[str] | None = None) -> tuple[bool, str]:
    """Return (is_wbs_likely, short_label)."""
    hay = (text or "").lower()
    phrases = list(DEFAULT_WBS_PHRASES)
    if extra_phrases:
        phrases.extend(p.lower() for p in extra_phrases if p)
    for p in phrases:
        if p.lower() in hay:
            return True, "WBS / gefördert (laut Text)"
    if re.search(r"wbs[\s\-_]*\d{2,3}", hay):
        return True, "WBS (Stufe im Text)"
    return False, ""


def build_listing(
    *,
    url: str,
    title: str = "",
    price=None,
    location: str = "Berlin",
    district: str = "",
    city: str = "",
    rooms=None,
    size_m2=None,
    description: str = "",
    wbs_label: str = "",
    trusted_wbs: bool = False,
    source: str,
    base_url: str = "",
    images: list[str] | None = None,
) -> dict | None:
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        if base_url and url.startswith("/"):
            url = base_url.rstrip("/") + url
        else:
            return None
    if base_url and url.rstrip("/") == base_url.rstrip("/"):
        return None
    if not url.startswith(("http://", "https://")):
        return None
    path = url.split("//", 1)[-1]
    if "/" not in path or path.rstrip("/").count("/") < 1:
        if len(path.rstrip("/").split("/")) <= 1:
            return None

    price_int = parse_price_eur(price) if price is not None else None

    loc = clean_text(location or "Berlin", 120)
    desc = (description or "").strip()[:8000]
    is_wbs, wbs_detect = detect_wbs(f"{title} {loc} {desc}", None)
    wbs_level = extract_wbs_level(f"{title} {desc} {wbs_label}")
    final_wbs = wbs_label or (wbs_detect if is_wbs else "")

    return {
        "id": make_id(url),
        "title": clean_text(title or "", 300),
        "price": price_int,
        "location": loc,
        "district": clean_text(district, 80),
        "city": clean_text(city, 80) or "Berlin",
        "rooms": parse_rooms(rooms),
        "size_m2": float(size_m2) if size_m2 is not None else None,
        "description": desc,
        "wbs_label": final_wbs,
        "wbs_level": wbs_level,
        "trusted_wbs": trusted_wbs or bool(is_wbs),
        "url": url,
        "source": source,
        "images": list(images or []),
    }


def absolutize_image_url(base: str, src: str) -> str | None:
    if not src or src.startswith("data:"):
        return None
    src = src.strip()
    if src.startswith("//"):
        return "https:" + src
    if src.startswith(("http://", "https://")):
        return src
    try:
        return urljoin(base + "/", src)
    except Exception:
        return None


def normalize_image_url(url: str) -> str | None:
    """Prefer larger images: strip common thumb params, dedupe later."""
    if not url or not url.startswith("http"):
        return None
    # drop obvious thumbnail path segments (heuristic)
    u = url
    for bad in ("/thumb/", "/thumbnail/", "_thumb", "width=50", "width=100"):
        if bad in u.lower():
            pass  # keep URL; sites vary
    return u


def dedupe_preserve_order(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        nu = normalize_url(u)
        if not nu or nu in seen:
            continue
        seen.add(nu)
        out.append(nu)
    return out
