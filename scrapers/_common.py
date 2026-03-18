"""
Shared scraper utilities — price parser, URL guard, listing builder.
"""
import re
import logging
from filters.wbs_filter import make_id

logger = logging.getLogger(__name__)


def parse_price(raw) -> float | None:
    """
    Smart price parser for German number formats.
    Handles: '1.250,00 €', '520.00', '640,00', 'ab 450', None
    """
    if raw is None:
        return None
    s = str(raw).replace("€", "").replace("EUR", "").replace("\xa0", "").replace(" ", "").strip()
    if not s or s.lower() in ("none", "-", "—"):
        return None
    # German: 1.250,00 → both separators → '.' is thousands, ',' is decimal
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        # X.XXX pattern → thousands separator (e.g. 1.250)
        if len(parts) == 2 and len(parts[1]) == 3 and parts[1].isdigit():
            s = s.replace(".", "")
        # else decimal (e.g. 520.00) — leave as-is
    m = re.search(r"\d+\.?\d*", s)
    try:
        return float(m.group()) if m else None
    except (ValueError, TypeError):
        return None


def parse_rooms(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).replace(",", ".").strip()
    m = re.search(r"\d+\.?\d*", s)
    try:
        return float(m.group()) if m else None
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
    Construct a normalised listing dict.
    Returns None if URL is invalid or empty.
    """
    # Resolve relative URLs
    if url and not url.startswith("http"):
        url = base_url.rstrip("/") + "/" + url.lstrip("/")

    # Validate
    if not url or url == base_url or len(url) < 12:
        return None
    if not any(d in url for d in ("http://", "https://")):
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
