"""
Shared scraper utilities — smart price/rooms parser + listing builder.
All scrapers import from here.
"""
import re
import logging
import hashlib
from urllib.parse import urlparse, urlunparse, urlencode, parse_qs

logger = logging.getLogger(__name__)

# Patterns that indicate price is not actually a number
_NON_PRICE = re.compile(r"^(preis auf anfrage|auf anfrage|n\.a\.|nan|none|-|—|–)$", re.I)

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "ref", "referrer", "source", "fbclid", "gclid", "_ga", "mc_cid",
    "tracking",
}


def normalize_url(url: str) -> str:
    """Remove common tracking query parameters to keep dedup stable."""
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
    """Deterministic short hash for a listing URL."""
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


def clean_text(text: str, max_len: int = 80) -> str:
    """
    Remove HTML artifacts, pipe separators, extra whitespace, newlines.
    Used for location and title fields scraped from raw HTML.
    """
    if not text:
        return ""
    t = str(text)
    # Collapse newlines / tabs / multiple spaces into single space
    t = re.sub(r'\s+', ' ', t)
    # Convert pipe separators (from get_text(" | ")) to comma
    t = re.sub(r'\s*\|\s*', ', ', t)
    # Remove repeated commas
    t = re.sub(r',\s*,+', ',', t)
    # Strip leading/trailing junk
    t = t.strip(' ,|•–-/')
    return t[:max_len].strip()


def parse_price(raw) -> float | None:
    """
    Smart German price parser.
    Handles: '1.250,00 €', '520.00', '520,-', '2 500,00', 'ab 450', None.
    """
    if raw is None:
        return None
    s = str(raw).replace("€", "").replace("EUR", "").replace("\xa0", "").replace("\u202f", "").strip()
    if not s or _NON_PRICE.match(s):
        return None
    # Strip non-numeric prefix/suffix words (e.g. 'ab ', 'bis ', 'ca. ')
    s = re.sub(r"^[a-zäöüß\s\.]+", "", s, flags=re.I)
    s = re.sub(r"[^0-9\.,]", "", s)  # keep only digits, comma, dot
    if not s:
        return None
    # German locale: 1.250,00 → both → '.' is thousands, ',' is decimal
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        parts = s.split(",")
        # '1,250' → 3 digits after comma → thousands separator → 1250
        # '640,00' or '1,25' → decimal
        if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isdigit():
            s = s.replace(",", "")      # 1,250 → 1250
        else:
            s = s.replace(",", ".")     # 640,00 → 640.00 | 1,25 → 1.25
    elif "." in s:
        parts = s.split(".")
        # X.XXX → thousands; X.XX or X.X → decimal
        if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isdigit():
            s = s.replace(".", "")  # 1.250 → 1250
        # else leave as decimal: 520.00
    # Remove trailing ,-
    s = s.rstrip(",- ")
    try:
        val = float(s)
        # Sanity check — Berlin rents are 200–5000
        return val if 50 < val < 5000 else None
    except (ValueError, TypeError):
        return None


def parse_rooms(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace(",", ".").strip()
    m = re.search(r"\d+\.?\d*", s)
    try:
        val = float(m.group()) if m else None
        # Sanity: 0.5 to 20 rooms
        return val if val and 0.5 <= val <= 20 else None
    except (ValueError, TypeError):
        return None


def build_listing(
    *,
    url: str,
    title: str = "",
    price=None,
    location: str = "Berlin",
    rooms=None,
    description: str = "",
    wbs_label: str = "WBS erforderlich",
    trusted_wbs: bool = True,
    source: str,
    base_url: str = "",
) -> dict | None:
    """
    Build a normalised listing dict.
    Returns None if URL is invalid, empty, or equals base_url.
    """
    if not url:
        return None

    # Resolve relative URLs
    if not url.startswith(("http://", "https://")):
        if base_url and url.startswith("/"):
            url = base_url.rstrip("/") + url
        else:
            return None

    # Must have a path beyond the domain
    if base_url and url.rstrip("/") == base_url.rstrip("/"):
        return None

    # Must not be a javascript/mailto link
    if not url.startswith(("http://", "https://")):
        return None

    # Must have meaningful path (at least one segment after domain)
    path = url.split("//", 1)[-1]
    if "/" not in path or path.rstrip("/").count("/") < 1:
        # e.g. https://degewo.de or https://degewo.de/
        if len(path.rstrip("/").split("/")) <= 1:
            return None

    return {
        "id":          make_id(url),
        "title":       clean_text(title or "", max_len=200),
        "price":       parse_price(price),
        "location":    clean_text(location or "Berlin", max_len=60),
        "rooms":       parse_rooms(rooms),
        "description": (description or "").strip()[:1000],
        "wbs_label":   wbs_label,
        "trusted_wbs": trusted_wbs,
        "url":         url,
        "source":      source,
    }
