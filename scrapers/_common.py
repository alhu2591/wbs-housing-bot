"""
Shared scraper utilities — smart price/rooms parser + listing builder.
All scrapers import from here.
"""
import re
import logging
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)

# Patterns that indicate price is not actually a number
_NON_PRICE = re.compile(r"^(preis auf anfrage|auf anfrage|n\.a\.|nan|none|-|—|–)$", re.I)


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
        # Could be decimal (640,00) or thousands (1,250) — check right side
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isdigit():
            s = s.replace(",", "")  # thousands: 1,250 → 1250
        else:
            s = s.replace(",", ".")  # decimal: 640,00 → 640.00
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
        "title":       (title or "").strip()[:200],
        "price":       parse_price(price),
        "location":    (location or "Berlin").strip(),
        "rooms":       parse_rooms(rooms),
        "description": (description or "").strip()[:1000],
        "wbs_label":   wbs_label,
        "trusted_wbs": trusted_wbs,
        "url":         url,
        "source":      source,
    }
