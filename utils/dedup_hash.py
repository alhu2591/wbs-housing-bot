"""
Content-based deduplication: title + price + location, and image URL sets.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from utils.parser import normalize_url, parse_price_eur


def _norm_text(s: str) -> str:
    t = (s or "").lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = (
        t.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    return t[:500]


def listing_content_hash(listing: dict[str, Any]) -> str:
    """Stable hash across sources for near-duplicate listings."""
    title = _norm_text(str(listing.get("title") or ""))
    loc = _norm_text(
        " ".join(
            [
                str(listing.get("location") or ""),
                str(listing.get("district") or ""),
                str(listing.get("city") or ""),
            ]
        )
    )
    p = listing.get("price")
    if p is None:
        price_s = "na"
    else:
        try:
            price_s = str(int(float(p)))
        except Exception:
            price_s = _norm_text(str(p))
    raw = f"{title}|{price_s}|{loc}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def listing_image_fingerprint(listing: dict[str, Any], max_urls: int = 5) -> str | None:
    imgs = listing.get("images") or []
    if not imgs:
        return None
    norm: list[str] = []
    for u in imgs[:max_urls]:
        if not isinstance(u, str) or not u.startswith("http"):
            continue
        try:
            norm.append(normalize_url(u.split("?")[0]))
        except Exception:
            norm.append(u[:200])
    if not norm:
        return None
    norm.sort()
    h = hashlib.sha256("\n".join(norm).encode("utf-8")).hexdigest()
    return h
