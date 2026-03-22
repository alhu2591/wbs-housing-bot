"""scraper/classifieds.py — Classified ad portals: WG-Gesucht, eBay Kleinanzeigen."""
from __future__ import annotations
import logging
import re
from typing import Any
from scraper.base_scraper import fetch_html
from utils.soup import make_soup
from utils.parser import parse_price, parse_rooms, parse_size, build_listing

logger = logging.getLogger(__name__)


# ── WG-Gesucht ─────────────────────────────────────────────────────────────

async def scrape_wggesucht(cfg: dict[str, Any]) -> list[dict]:
    """
    WG-Gesucht: Only return full apartments (type 2), not WG rooms (type 0).
    Filter out WG/room listings at scrape level.
    """
    SOURCE = "wggesucht"
    city_id = 8  # Berlin
    max_rent = cfg.get("max_price") or 900
    # type_of_rent=2 = full apartment; type_of_rent=0 = WG-Zimmer (excluded)
    URL = (
        f"https://www.wg-gesucht.de/wohnungen-in-Berlin.{city_id}.2.0.0.html"
        f"?offer_filter=1&city_id={city_id}&rent_types%5B%5D=2"
        f"&rent_from=&rent_to={int(max_rent)}"
    )
    html = await fetch_html(URL)
    if not html:
        return []
    soup = make_soup(html)
    results = []
    for card in soup.select(".offer_list_item, .wgg-card, li.offer-list-item"):
        try:
            title_el = card.select_one("h3.truncate_title, .headline-list-view, h3")
            title = title_el.get_text(strip=True) if title_el else "WG-Gesucht Wohnung"
            # Skip WG rooms
            if any(kw in title.lower() for kw in ["wg", "zimmer", "mitbewohner"]):
                continue
            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url_l = ("https://www.wg-gesucht.de" + href) if href.startswith("/") else href
            price = parse_price(card.get_text())
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            loc_el = card.select_one(".col-xs-11, .address, .location")
            location = loc_el.get_text(strip=True)[:60] if loc_el else "Berlin"
            imgs = [i.get("src","") for i in card.select("img") if i.get("src","").startswith("http")]
            text = card.get_text().lower()
            wbs = "wbs" in text
            if not url_l or "wg-zimmer" in url_l:
                continue
            results.append(build_listing(
                title=title, price=price, size_m2=size, rooms=rooms,
                location=location, url=url_l, images=imgs, source=SOURCE,
                wbs_label="WBS" if wbs else "", wbs_required=wbs,
            ))
        except Exception as e:
            logger.debug("wggesucht card: %s", e)
    logger.info("wggesucht: %d", len(results))
    return results


# ── eBay Kleinanzeigen ─────────────────────────────────────────────────────

async def scrape_ebay_kleinanzeigen(cfg: dict[str, Any]) -> list[dict]:
    SOURCE = "ebay_kleinanzeigen"
    max_price = cfg.get("max_price") or 900
    min_rooms = cfg.get("rooms") or 1
    # Kleinanzeigen (formerly eBay Kleinanzeigen)
    URL = (
        f"https://www.kleinanzeigen.de/s-wohnung-mieten/berlin/"
        f"preis::{int(max_price)}/c203l3331r20+wohnung_mieten.zimmer_d:{float(min_rooms)}%2C"
    )
    html = await fetch_html(URL)
    if not html:
        return []
    soup = make_soup(html)
    results = []
    for card in soup.select("article.aditem, li.ad-listitem"):
        try:
            title_el = card.select_one("h2.text-module-begin, .ellipsis, h3")
            title = title_el.get_text(strip=True) if title_el else "Kleinanzeigen Wohnung"
            # Filter out non-apartment listings
            title_lower = title.lower()
            if any(kw in title_lower for kw in ["wg", "zimmer suche", "wg-zimmer", "zwischenmiete"]):
                continue
            link_el = card.select_one("a[href]")
            href = link_el["href"] if link_el else ""
            url_l = ("https://www.kleinanzeigen.de" + href) if href.startswith("/") else href
            price = parse_price(card.get_text())
            size = parse_size(card.get_text())
            rooms = parse_rooms(card.get_text())
            loc_el = card.select_one(".aditem-main--top--left, .location")
            location = loc_el.get_text(strip=True) if loc_el else "Berlin"
            imgs = []
            img_el = card.select_one("img[src]")
            if img_el:
                src = img_el.get("src") or img_el.get("data-src","")
                if src.startswith("http"):
                    imgs = [src]
            text = card.get_text().lower()
            wbs = "wbs" in text or "wohnberechtigungsschein" in text
            if not url_l:
                continue
            results.append(build_listing(
                title=title, price=price, size_m2=size, rooms=rooms,
                location=location, url=url_l, images=imgs, source=SOURCE,
                wbs_label="WBS" if wbs else "", wbs_required=wbs,
            ))
        except Exception as e:
            logger.debug("ebay_kleinanzeigen card: %s", e)
    logger.info("ebay_kleinanzeigen: %d", len(results))
    return results
