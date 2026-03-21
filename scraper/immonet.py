"""Immonet — WBS (Wohnberechtigungsschein) listings in Berlin.

This scraper is best-effort because immonet's HTML can change.
We rely on `detail_page.py` for the heavy lifting (images, size, rooms, description).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from scraper.base_scraper import fetch
from utils.parser import build_listing, parse_price, parse_rooms
from utils.soup import make_soup

logger = logging.getLogger(__name__)

SOURCE = "immonet"
BASE = "https://www.immonet.de"

# Public search page for WBS-required apartments in Berlin (immonet route).
URLS = [
    f"{BASE}/suchen/miete/wohnung/wbs-ja/berlin/",
    # Example route with region id (often more reliable than the generic /berlin/ path).
    f"{BASE}/suchen/miete/wohnung/wbs-ja/berlin/berlin-10115/ad08de8634",
]


def _extract_price_from_text(text: str) -> int | None:
    """
    Quick overview price extraction so quick-prefilter can work.

    Detail-page enrichment will refine price further if needed.
    """
    if not text:
        return None
    # Prefer "1234 €" patterns.
    m = re.search(r"([\d\.,]+)\s*€", text)
    if m:
        return parse_price(m.group(1))
    # Fallback: look for "EUR" style numbers.
    m = re.search(r"([\d\.,]+)\s*EUR", text, re.I)
    if m:
        return parse_price(m.group(1))
    return None


async def scrape() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        for url in URLS:
            html = await fetch(url, render_js=True)
            if not html or len(html) < 800:
                continue

            soup = make_soup(html)

            # Collect candidate links.
            candidate_links = soup.select(
                "a[href*='/expose/'], a[href*='/angebot/'], a[href*='/immobilien/'], "
                "a[href*='/wohnungen/'], a[href*='/wohnung/'], a[href*='/immobilie/']"
            )
            if not candidate_links:
                candidate_links = soup.select("a[href*='expose'], article a[href], div a[href]")

            # If the page uses unexpected markup, do a fallback scan of all links.
            # This tends to be noisy, so we filter by "listing-like" url patterns.
            if not candidate_links or len(candidate_links) < 10:
                try:
                    all_anchors = soup.select("a[href]")
                    candidate_links = []
                    tokens = (
                        "/expose",
                        "/angebot",
                        "/immobilien",
                        "/immobilie",
                        "/wohnungen",
                        "/wohnung",
                    )
                    for a in all_anchors:
                        href = a.get("href") or ""
                        hl = href.lower()
                        if not href:
                            continue
                        if any(t in hl for t in tokens) and any(ch.isdigit() for ch in href):
                            # Exclude obvious search/filter links.
                            if "suchen" in hl or "filter" in hl:
                                continue
                            candidate_links.append(a)
                except Exception:
                    pass

            for a in candidate_links:
                href = a.get("href") or ""
                if not href:
                    continue
                full_url = href if href.startswith("http") else BASE + href
                if not full_url.startswith("http"):
                    continue
                if full_url in seen:
                    continue
                if BASE not in full_url:
                    continue

                seen.add(full_url)

                card_text = a.get_text(" ", strip=True)
                # Also include surrounding text for price/rooms parsing.
                parent_text = ""
                try:
                    parent = a.find_parent(["article", "section", "div"])
                    if parent:
                        parent_text = parent.get_text(" ", strip=True)
                except Exception:
                    parent_text = ""

                blob = f"{card_text} {parent_text}".strip()

                title = (
                    a.get("title")
                    or a.select_one("*") and card_text
                    or card_text
                    or "Immonet listing"
                )
                price = _extract_price_from_text(blob)
                rooms = parse_rooms(blob)
                desc = ""

                listing = build_listing(
                    url=full_url,
                    title=title,
                    price=price,
                    rooms=rooms,
                    description=desc,
                    location="Berlin",
                    wbs_label="",
                    trusted_wbs=False,
                    source=SOURCE,
                    base_url=BASE,
                )
                if listing:
                    results.append(listing)

            # If we found something on this search page, stop.
            if results:
                break
    except Exception as e:
        logger.error("[%s] %s", SOURCE, e)

    logger.info("[%s] %d listings", SOURCE, len(results))
    return results

