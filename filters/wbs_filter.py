import hashlib
import logging
from config.settings import WBS_KEYWORDS

logger = logging.getLogger(__name__)


def is_wbs(listing: dict) -> bool:
    """Return True if listing explicitly requires a WBS."""
    haystack = " ".join(
        str(listing.get(f, "") or "").lower()
        for f in ("title", "description", "wbs_label")
    )
    return any(kw in haystack for kw in WBS_KEYWORDS)


def passes_price(listing: dict, max_price: float) -> bool:
    price = listing.get("price")
    if price is None:
        return True           # allow unknown price through
    return float(price) <= max_price


def passes_rooms(listing: dict, min_rooms: float) -> bool:
    if not min_rooms:
        return True
    rooms = listing.get("rooms")
    if rooms is None:
        return True
    return float(rooms) >= float(min_rooms)


def passes_area(listing: dict, area: str) -> bool:
    if not area:
        return True
    loc = str(listing.get("location", "")).lower()
    return area.lower() in loc


def make_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def score_listing(listing: dict) -> int:
    """Simple scoring: government sources score higher."""
    GOV_SOURCES = {"gewobag", "degewo", "howoge", "stadtundland",
                   "deutschewohnen", "berlinovo"}
    score = 0
    if listing.get("source", "").lower() in GOV_SOURCES:
        score += 10
    price = listing.get("price")
    if price and price < 500:
        score += 5
    elif price and price < 550:
        score += 3
    rooms = listing.get("rooms")
    if rooms and rooms >= 2:
        score += 3
    return score
