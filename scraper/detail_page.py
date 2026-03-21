"""
Fetch listing detail page and enrich: description, images, size, rooms, WBS hints.

Uses fallback CSS selectors and logs misses; optional Playwright when HTML is thin or parsing is empty.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from scraper.base_scraper import fetch
from utils.fetch_runtime import get_fetch_runtime
from utils.parser import (
    absolutize_image_url,
    dedupe_preserve_order,
    detect_wbs,
    extract_wbs_level,
    parse_price_eur,
    parse_size_m2,
    parse_rooms,
)
from utils.playwright_html import fetch_html_playwright
from utils.soup import make_soup

logger = logging.getLogger(__name__)

_MIN_IMAGE_LEN = 80
_MIN_HTML = 200

_DESC_SELECTORS = (
    "article",
    "[class*='description']",
    "[class*='beschreibung']",
    "[class*='exposé']",
    "[class*='expose']",
    ".field-body",
    "[itemprop='description']",
    "main",
    "#description",
)


def _meta_content(soup, attrs: dict) -> str:
    tag = soup.find("meta", attrs=attrs)
    if tag and tag.get("content"):
        return str(tag["content"]).strip()
    return ""


def _text_from_selectors(soup, field: str, selectors: tuple[str, ...]) -> str:
    for sel in selectors:
        try:
            node = soup.select_one(sel)
            if node:
                txt = node.get_text(" ", strip=True)
                if len(txt) > 80:
                    return txt[:8000]
        except Exception as e:
            logger.debug("selector try field=%s sel=%s err=%s", field, sel, e)
    logger.warning("selector_miss field=%s selectors_tried=%d", field, len(selectors))
    return ""


def _extract_images(soup, page_url: str) -> list[str]:
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
                val = val.split(",")[0].strip().split()[0]
            u = absolutize_image_url(page_url, val)
            if u and len(u) >= _MIN_IMAGE_LEN:
                found.append(u)

    out: list[str] = []
    for u in found:
        u2 = absolutize_image_url(page_url, u) or u
        if u2 and not u2.lower().endswith((".svg", ".gif")):
            out.append(u2)
    imgs = dedupe_preserve_order(out)
    if not imgs:
        logger.warning("selector_miss field=images url=%s", page_url[:80])
    return imgs


def _extract_description(soup) -> str:
    t = _meta_content(soup, {"property": "og:description"})
    if len(t) > 40:
        return t
    t = _meta_content(soup, {"name": "description"})
    if len(t) > 40:
        return t
    return _text_from_selectors(soup, "description", _DESC_SELECTORS)


def _extract_rooms_from_text(text: str) -> float | None:
    m = re.search(
        r"(\d+[.,]?\d*)\s*[-]?\s*zimmer",
        text,
        re.I,
    )
    if m:
        return parse_rooms(m.group(1))
    return None


def _apply_soup_enrichment(listing: dict[str, Any], soup, page_url: str) -> None:
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
        else:
            logger.debug("selector_miss field=size_m2 listing=%s", listing.get("id"))

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

    for script in soup.find_all("script", type=re.compile("ld\\+json", re.I)):
        raw = script.string or ""
        if "floorSize" in raw or "numberOfRooms" in raw:
            m = re.search(r'"value"\s*:\s*([\d.]+)\s*,\s*"unitCode"\s*:\s*"MTK"', raw)
            if m and listing.get("size_m2") is None:
                try:
                    listing["size_m2"] = float(m.group(1))
                except ValueError:
                    pass


def _parse_is_weak(listing: dict[str, Any]) -> bool:
    """Heuristic: BeautifulSoup likely missed JS-rendered content."""
    if len((listing.get("description") or "").strip()) >= 40:
        return False
    if len(listing.get("images") or []) >= 1:
        return False
    if listing.get("size_m2") is not None and listing.get("rooms") is not None:
        return False
    return True


async def enrich_listing(
    client: httpx.AsyncClient,
    listing: dict[str, Any],
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = cfg or {}
    url = listing.get("url")
    if not url:
        return listing
    try:
        html = await fetch(str(url), client=client)
        rt = get_fetch_runtime()
        if (not html or len(html) < _MIN_HTML) and rt.get("use_playwright"):
            pw = await fetch_html_playwright(
                str(url), int(rt.get("playwright_timeout_ms") or 30000)
            )
            if pw:
                html = pw
                logger.info("event=playwright_html_short url=%s", str(url)[:60])

        if not html or len(html) < 200:
            logger.warning("event=detail_short_html url=%s len=%s", str(url)[:60], len(html or ""))
            return listing

        page_url = str(url).split("#")[0]
        soup = make_soup(html)
        _apply_soup_enrichment(listing, soup, page_url)

        if rt.get("use_playwright") and _parse_is_weak(listing) and len(html) >= _MIN_HTML:
            pw2 = await fetch_html_playwright(
                str(url), int(rt.get("playwright_timeout_ms") or 30000)
            )
            if pw2 and len(pw2) > len(html):
                soup2 = make_soup(pw2)
                _apply_soup_enrichment(listing, soup2, page_url)
                logger.info("event=playwright_parse_repair url=%s", str(url)[:60])

    except Exception as e:
        logger.warning("enrich_listing %s: %s", url[:50], e)
    return listing


async def enrich_listings_batch(
    client: httpx.AsyncClient,
    listings: list[dict[str, Any]],
    concurrency: int = 4,
    cfg: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)
    c = cfg or {}

    async def one(l: dict[str, Any]) -> dict[str, Any]:
        async with sem:
            try:
                return await enrich_listing(client, l, c)
            except Exception as e:
                logger.warning("enrich failed for %s: %s", l.get("url"), e)
                return l

    return list(await asyncio.gather(*[one(l) for l in listings]))
