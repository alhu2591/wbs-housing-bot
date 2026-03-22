"""scraper/public_housing.py — Berlin public housing scrapers.
Covers: HOWOGE, Stadt und Land, WBM, Gesobau, Berlinovo.
All are WBS-eligible public landlords.
"""
from __future__ import annotations
import logging
from typing import Any
from scraper.base_scraper import fetch_html
from utils.soup import make_soup
from utils.parser import parse_price, parse_rooms, parse_size, build_listing

logger = logging.getLogger(__name__)


# ── HOWOGE ─────────────────────────────────────────────────────────────────

async def scrape_howoge(cfg: dict[str, Any]) -> list[dict]:
    SOURCE = "howoge"
    URL = "https://www.howoge.de/wohnungen-gewerbe/wohnungssuche.html"
    html = await fetch_html(URL)
    if not html:
        return []
    soup = make_soup(html)
    results = []
    for card in soup.select(".teaser--apartment, .wohnung-item, article"):
        try:
            title_el = card.select_one("h3, h2, .teaser__headline")
            title = title_el.get_text(strip=True) if title_el else "HOWOGE Wohnung"
            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url = ("https://www.howoge.de" + href) if href.startswith("/") else href
            price = parse_price(card.get_text())
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            loc_el = card.select_one(".address, .location, .ort")
            location = loc_el.get_text(strip=True) if loc_el else "Berlin"
            imgs = [i["src"] for i in card.select("img[src]") if i.get("src","").startswith("http")]
            if not url:
                continue
            results.append(build_listing(
                title=title, price=price, size_m2=size, rooms=rooms,
                location=location, url=url, images=imgs, source=SOURCE,
                wbs_label="WBS erforderlich", wbs_required=True,
            ))
        except Exception as e:
            logger.debug("howoge card: %s", e)
    logger.info("howoge: %d", len(results))
    return results


# ── Stadt und Land ─────────────────────────────────────────────────────────

async def scrape_stadtundland(cfg: dict[str, Any]) -> list[dict]:
    SOURCE = "stadtundland"
    URL = "https://www.stadtundland.de/Mieten/Wohnungssuche.php"
    html = await fetch_html(URL)
    if not html:
        return []
    soup = make_soup(html)
    results = []
    for card in soup.select(".SP-Expose, .expose-item, .wohnung"):
        try:
            title_el = card.select_one("h2, h3, .expose-title")
            title = title_el.get_text(strip=True) if title_el else "Stadt und Land Wohnung"
            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url = ("https://www.stadtundland.de" + href) if href.startswith("/") else href
            price = parse_price(card.get_text())
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            loc_el = card.select_one(".address, .ort, .bezirk")
            location = loc_el.get_text(strip=True) if loc_el else "Berlin"
            imgs = [i.get("src","") for i in card.select("img") if i.get("src","").startswith("http")]
            if not url:
                continue
            results.append(build_listing(
                title=title, price=price, size_m2=size, rooms=rooms,
                location=location, url=url, images=imgs, source=SOURCE,
                wbs_label="WBS erforderlich", wbs_required=True,
            ))
        except Exception as e:
            logger.debug("stadtundland card: %s", e)
    logger.info("stadtundland: %d", len(results))
    return results


# ── WBM ────────────────────────────────────────────────────────────────────

async def scrape_wbm(cfg: dict[str, Any]) -> list[dict]:
    SOURCE = "wbm"
    URL = "https://www.wbm.de/wohnungen-berlin/angebote/"
    html = await fetch_html(URL)
    if not html:
        return []
    soup = make_soup(html)
    results = []
    for card in soup.select(".row.openimmo-search-list-item, .result-list-entry"):
        try:
            title_el = card.select_one("h3, h2, .entry-title")
            title = title_el.get_text(strip=True) if title_el else "WBM Wohnung"
            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url = ("https://www.wbm.de" + href) if href.startswith("/") else href
            price = parse_price(card.get_text())
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            loc_el = card.select_one(".address, .location")
            location = loc_el.get_text(strip=True) if loc_el else "Berlin"
            imgs = [i.get("src","") for i in card.select("img") if i.get("src","").startswith("http")]
            if not url:
                continue
            results.append(build_listing(
                title=title, price=price, size_m2=size, rooms=rooms,
                location=location, url=url, images=imgs, source=SOURCE,
                wbs_label="WBS möglich", wbs_required=False,
            ))
        except Exception as e:
            logger.debug("wbm card: %s", e)
    logger.info("wbm: %d", len(results))
    return results


# ── Gesobau ────────────────────────────────────────────────────────────────

async def scrape_gesobau(cfg: dict[str, Any]) -> list[dict]:
    SOURCE = "gesobau"
    URL = "https://www.gesobau.de/mieten/wohnungssuche/"
    html = await fetch_html(URL)
    if not html:
        return []
    soup = make_soup(html)
    results = []
    for card in soup.select(".search-result, .angebot, article.property"):
        try:
            title_el = card.select_one("h2, h3")
            title = title_el.get_text(strip=True) if title_el else "Gesobau Wohnung"
            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url = ("https://www.gesobau.de" + href) if href.startswith("/") else href
            price = parse_price(card.get_text())
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            location = "Berlin"
            loc_el = card.select_one(".address, .bezirk")
            if loc_el:
                location = loc_el.get_text(strip=True)
            imgs = [i.get("src","") for i in card.select("img") if i.get("src","").startswith("http")]
            if not url:
                continue
            results.append(build_listing(
                title=title, price=price, size_m2=size, rooms=rooms,
                location=location, url=url, images=imgs, source=SOURCE,
                wbs_label="WBS erforderlich", wbs_required=True,
            ))
        except Exception as e:
            logger.debug("gesobau card: %s", e)
    logger.info("gesobau: %d", len(results))
    return results


# ── Berlinovo ──────────────────────────────────────────────────────────────

async def scrape_berlinovo(cfg: dict[str, Any]) -> list[dict]:
    SOURCE = "berlinovo"
    URL = "https://www.berlinovo.de/de/wohnungssuche"
    html = await fetch_html(URL)
    if not html:
        return []
    soup = make_soup(html)
    results = []
    for card in soup.select(".views-row, .property-item, article"):
        try:
            title_el = card.select_one("h2, h3, .field-title")
            title = title_el.get_text(strip=True) if title_el else "Berlinovo Wohnung"
            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url = ("https://www.berlinovo.de" + href) if href.startswith("/") else href
            price = parse_price(card.get_text())
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            location = "Berlin"
            imgs = [i.get("src","") for i in card.select("img") if i.get("src","").startswith("http")]
            if not url:
                continue
            results.append(build_listing(
                title=title, price=price, size_m2=size, rooms=rooms,
                location=location, url=url, images=imgs, source=SOURCE,
                wbs_label="", wbs_required=False,
            ))
        except Exception as e:
            logger.debug("berlinovo card: %s", e)
    logger.info("berlinovo: %d", len(results))
    return results
