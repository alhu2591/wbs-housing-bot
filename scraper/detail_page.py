"""
Fetch listing detail page and enrich: description, images, size, rooms, WBS hints.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urljoin

import httpx

from scraper.base_scraper import fetch
from utils.parser import (
    absolutize_image_url,
    dedupe_preserve_order,
    detect_wbs,
    extract_wbs_level,
    parse_price_eur,
    parse_size_m2,
    parse_rooms,
)
from utils.soup import make_soup

logger = logging.getLogger(__name__)

# Skip tiny / tracking pixels
_MIN_IMAGE_LEN = 80


def _meta_content(soup, attrs: dict) -> str:
    tag = soup.find("meta", attrs=attrs)
    if tag and tag.get("content"):
        return str(tag["content"]).strip()
    return ""


def _extract_images(soup, page_url: str) -> list[str]:
    base = page_url.rsplit("/", 1)[0] if "/" in page_url else page_url
    found: list[str] = []

    for tag in soup.find_all("meta", property=re.compile(r"^og:image$", re.I)):
        c = tag.get("content")
        if c:
            found.append(str(c).strip())

    for tag in soup.find_all("link", rel=re.compile(r"image_src", re.I)):
        h = tag.get("href")
        if h:
            found.append(str(h).strip())

    for img in soup.find_all("img"):
        for attr in ("data-src", "data-lazy-src", "data-original", "srcset", "src"):
            val = img.get(attr)
            if not val:
                continue
            if attr == "srcset":
                # first URL in srcset
                val = val.split(",")[0].strip().split()[0]
            u = absolutize_image_url(page_url, val)
            if u and len(u) >= _MIN_IMAGE_LEN:
                found.append(u)

    out: list[str] = []
    for u in found:
        u2 = absolutize_image_url(page_url, u) or u
        if u2 and not u2.lower().endswith((".svg", ".gif")):
            out.append(u2)
    return dedupe_preserve_order(out)


def _extract_description(soup) -> str:
    t = _meta_content(soup, {"property": "og:description"})
    if len(t) > 40:
        return t
    t = _meta_content(soup, {"name": "description"})
    if len(t) > 40:
        return t
    for sel in (
        "article",
        "[class*='description']",
        "[class*='beschreibung']",
        ".field-body",
        "main",
    ):
        node = soup.select_one(sel)
        if node:
            txt = node.get_text(" ", strip=True)
            if len(txt) > 80:
                return txt[:8000]
    return ""


def _extract_rooms_from_text(text: str) -> float | None:
    m = re.search(
        r"(\d+[.,]?\d*)\s*[-]?\s*zimmer",
        text,
        re.I,
    )
    if m:
        return parse_rooms(m.group(1))
    return None


async def enrich_listing(client: httpx.AsyncClient, listing: dict[str, Any]) -> dict[str, Any]:
    url = listing.get("url")
    if not url:
        return listing
    try:
        html = await fetch(str(url), client=client)
        if not html or len(html) < 200:
            return listing
        soup = make_soup(html)
        page_url = str(url).split("#")[0]

        desc = _extract_description(soup)
        if desc and len(desc) > len(listing.get("description") or ""):
            listing["description"] = desc[:8000]

        imgs = _extract_images(soup, page_url)
        if imgs:
            listing["images"] = dedupe_preserve_order((listing.get("images") or []) + imgs)

        blob = soup.get_text(" ", strip=True)
        if listing.get("size_m2") is None:
            sm = parse_size_m2(blob)
            if sm is not None:
                listing["size_m2"] = sm
        if listing.get("rooms") is None:
            rm = _extract_rooms_from_text(blob)
            if rm is not None:
                listing["rooms"] = rm

        is_wbs, label = detect_wbs(
            f"{listing.get('title','')} {listing.get('description','')} {blob}",
            None,
        )
        if is_wbs and not listing.get("wbs_label"):
            listing["wbs_label"] = label
            listing["trusted_wbs"] = True
        if listing.get("wbs_level") is None:
            lvl = extract_wbs_level(f"{listing.get('title','')} {listing.get('description','')} {blob}")
            if lvl is not None:
                listing["wbs_level"] = lvl

        if listing.get("price") is None:
            m = re.search(
                r"(?:kaltmiete|warmmiete|gesamtmiete|miete)\s*[:\s]*([\d\.,]+)\s*€?",
                blob,
                re.I,
            )
            if m:
                p = parse_price_eur(m.group(1))
                if p is not None:
                    listing["price"] = p

        # Optional: JSON-LD
        for script in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
            raw = script.string or ""
            if "floorSize" in raw or "numberOfRooms" in raw:
                m = re.search(r'"value"\s*:\s*([\d.]+)\s*,\s*"unitCode"\s*:\s*"MTK"', raw)
                if m and listing.get("size_m2") is None:
                    try:
                        listing["size_m2"] = float(m.group(1))
                    except ValueError:
                        pass
    except Exception as e:
        logger.warning("enrich_listing %s: %s", url[:50], e)
    return listing


async def enrich_listings_batch(
    client: httpx.AsyncClient,
    listings: list[dict[str, Any]],
    concurrency: int = 4,
) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)

    async def one(l: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            try:
                return await enrich_listing(client, l)
            except Exception as e:
                logger.warning("enrich failed for %s: %s", l.get("url"), e)
                return l

    return list(await asyncio.gather(*[one(l) for l in listings]))
