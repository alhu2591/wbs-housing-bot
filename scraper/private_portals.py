"""scraper/private_portals.py — Private rental portal scrapers.
Covers: ImmobilienScout24, Immowelt, Immonet, Vonovia, Deutsche Wohnen.
"""
from __future__ import annotations
import logging
import re
from typing import Any
from scraper.base_scraper import fetch_html
from utils.soup import make_soup
from utils.parser import parse_price, parse_rooms, parse_size, build_listing

logger = logging.getLogger(__name__)


# ── ImmobilienScout24 ──────────────────────────────────────────────────────

async def scrape_immoscout(cfg: dict[str, Any]) -> list[dict]:
    SOURCE = "immoscout"
    max_price = cfg.get("max_price") or 900
    min_rooms = cfg.get("rooms") or 1
    city = cfg.get("city") or "Berlin"
    url = (
        f"https://www.immobilienscout24.de/Suche/de/{city.lower()}/wohnung-mieten"
        f"?price=-{int(max_price)}.0&numberofrooms={float(min_rooms)}-"
        f"&wohnflaeche={cfg.get('min_size') or 20}.0-"
        f"&sorting=2"  # newest first
    )
    html = await fetch_html(url)
    if not html:
        return []
    soup = make_soup(html)
    results = []
    # IS24 uses JSON-LD and data attributes
    for card in soup.select("[data-obid], .result-list-entry, article.result-list__listing"):
        try:
            title_el = card.select_one("h5, h3, .result-list-entry__brand-title")
            title = title_el.get_text(strip=True) if title_el else "IS24 Wohnung"
            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url_listing = ("https://www.immobilienscout24.de" + href) if href.startswith("/") else href
            price = parse_price(card.get_text())
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            loc_el = card.select_one(".result-list-entry__address, .address-block")
            location = loc_el.get_text(strip=True) if loc_el else city
            imgs = []
            img_el = card.select_one("img[src]")
            if img_el:
                imgs = [img_el["src"]]
            # WBS check in title/description
            text = card.get_text().lower()
            wbs = "wbs" in text or "wohnberechtigungsschein" in text
            if not url_listing:
                continue
            results.append(build_listing(
                title=title, price=price, size_m2=size, rooms=rooms,
                location=location, url=url_listing, images=imgs, source=SOURCE,
                wbs_label="WBS" if wbs else "", wbs_required=wbs,
            ))
        except Exception as e:
            logger.debug("immoscout card: %s", e)
    logger.info("immoscout: %d", len(results))
    return results


# ── Immowelt ───────────────────────────────────────────────────────────────

async def scrape_immowelt(cfg: dict[str, Any]) -> list[dict]:
    SOURCE = "immowelt"
    city = (cfg.get("city") or "Berlin").lower()
    max_price = cfg.get("max_price") or 900
    url = (
        f"https://www.immowelt.de/liste/{city}/wohnungen/mieten"
        f"?ami={int(max_price)}&wfl={(cfg.get('min_size') or 20)}"
        f"&zi={(cfg.get('rooms') or 1)}&sort=createdate_desc"
    )
    html = await fetch_html(url)
    if not html:
        return []
    soup = make_soup(html)
    results = []
    for card in soup.select("[data-estateid], .EstateItem, .listitem_wrap"):
        try:
            title_el = card.select_one("h2, h3, .ellipsis")
            title = title_el.get_text(strip=True) if title_el else "Immowelt Wohnung"
            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url_l = ("https://www.immowelt.de" + href) if href.startswith("/") else href
            price = parse_price(card.get_text())
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            loc_el = card.select_one(".location, .address")
            location = loc_el.get_text(strip=True) if loc_el else city.title()
            imgs = [i["src"] for i in card.select("img[src]") if i.get("src","").startswith("http")]
            text = card.get_text().lower()
            wbs = "wbs" in text
            if not url_l:
                continue
            results.append(build_listing(
                title=title, price=price, size_m2=size, rooms=rooms,
                location=location, url=url_l, images=imgs, source=SOURCE,
                wbs_label="WBS" if wbs else "", wbs_required=wbs,
            ))
        except Exception as e:
            logger.debug("immowelt card: %s", e)
    logger.info("immowelt: %d", len(results))
    return results


# ── Immonet ────────────────────────────────────────────────────────────────

async def scrape_immonet(cfg: dict[str, Any]) -> list[dict]:
    SOURCE = "immonet"
    city = (cfg.get("city") or "Berlin").lower()
    max_price = cfg.get("max_price") or 900
    url = (
        f"https://www.immonet.de/mieten/wohnung-{city}.html"
        f"?price={int(max_price)}&rooms={(cfg.get('rooms') or 1)}"
        f"&minarea={(cfg.get('min_size') or 20)}"
    )
    html = await fetch_html(url)
    if not html:
        return []
    soup = make_soup(html)
    results = []
    for card in soup.select(".listitem_wrap, [data-item-id], .result-list-entry"):
        try:
            title_el = card.select_one("h2, h3, .object-title")
            title = title_el.get_text(strip=True) if title_el else "Immonet Wohnung"
            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url_l = ("https://www.immonet.de" + href) if href.startswith("/") else href
            price = parse_price(card.get_text())
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            loc_el = card.select_one(".address, .location")
            location = loc_el.get_text(strip=True) if loc_el else city.title()
            imgs = [i["src"] for i in card.select("img[src]") if i.get("src","").startswith("http")]
            text = card.get_text().lower()
            wbs = "wbs" in text
            if not url_l:
                continue
            results.append(build_listing(
                title=title, price=price, size_m2=size, rooms=rooms,
                location=location, url=url_l, images=imgs, source=SOURCE,
                wbs_label="WBS" if wbs else "", wbs_required=wbs,
            ))
        except Exception as e:
            logger.debug("immonet card: %s", e)
    logger.info("immonet: %d", len(results))
    return results


# ── Vonovia ────────────────────────────────────────────────────────────────

async def scrape_vonovia(cfg: dict[str, Any]) -> list[dict]:
    SOURCE = "vonovia"
    URL = "https://www.vonovia.de/de/immobilien/mieten?ort=Berlin"
    html = await fetch_html(URL)
    if not html:
        return []
    soup = make_soup(html)
    results = []
    for card in soup.select(".teaser-object, .estate-list__item, article"):
        try:
            title_el = card.select_one("h3, h2")
            title = title_el.get_text(strip=True) if title_el else "Vonovia Wohnung"
            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url_l = ("https://www.vonovia.de" + href) if href.startswith("/") else href
            price = parse_price(card.get_text())
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            loc_el = card.select_one(".address, .location, .ort")
            location = loc_el.get_text(strip=True) if loc_el else "Berlin"
            imgs = [i.get("src","") for i in card.select("img") if i.get("src","").startswith("http")]
            if not url_l:
                continue
            results.append(build_listing(
                title=title, price=price, size_m2=size, rooms=rooms,
                location=location, url=url_l, images=imgs, source=SOURCE,
                wbs_label="", wbs_required=False,
            ))
        except Exception as e:
            logger.debug("vonovia card: %s", e)
    logger.info("vonovia: %d", len(results))
    return results


# ── Deutsche Wohnen ────────────────────────────────────────────────────────

async def scrape_deutschewohnen(cfg: dict[str, Any]) -> list[dict]:
    SOURCE = "deutschewohnen"
    URL = "https://www.deutsche-wohnen.com/immobilienangebote/#/"
    html = await fetch_html(URL)
    if not html:
        return []
    soup = make_soup(html)
    results = []
    for card in soup.select(".offer-card, .property-card, article"):
        try:
            title_el = card.select_one("h2, h3")
            title = title_el.get_text(strip=True) if title_el else "Deutsche Wohnen"
            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url_l = ("https://www.deutsche-wohnen.com" + href) if href.startswith("/") else href
            price = parse_price(card.get_text())
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            location = "Berlin"
            imgs = [i.get("src","") for i in card.select("img") if i.get("src","").startswith("http")]
            if not url_l:
                continue
            results.append(build_listing(
                title=title, price=price, size_m2=size, rooms=rooms,
                location=location, url=url_l, images=imgs, source=SOURCE,
            ))
        except Exception as e:
            logger.debug("deutschewohnen card: %s", e)
    logger.info("deutschewohnen: %d", len(results))
    return results
