"""Berlin listing sources registry.

Scrapers are selected based on `cfg["sources"]` so Telegram can enable/disable
portals dynamically.
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

from scraper.berlinovo import SOURCE as SRC_BERLINOVO, scrape as scrape_berlinovo
from scraper.degewo import SOURCE as SRC_DEGEWO, scrape as scrape_degewo
from scraper.deutschewohnen import (
    SOURCE as SRC_DEUTSCHEWOHNEN,
    scrape as scrape_deutschewohnen,
)
from scraper.ebay_kleinanzeigen import (
    SOURCE as SRC_EBAY_KLEINANZEIGEN,
    scrape as scrape_kleinanzeigen,
)
from scraper.gesobau import SOURCE as SRC_GESOBAU, scrape as scrape_gesobau
from scraper.gewobag import SOURCE as SRC_GEWOBA, scrape as scrape_gewobag
from scraper.howoge import SOURCE as SRC_HOWOGE, scrape as scrape_howoge
from scraper.immoscout import SOURCE as SRC_IMMOSCOUT, scrape as scrape_immoscout
from scraper.immowelt import SOURCE as SRC_IMMOWELT, scrape as scrape_immowelt
from scraper.immonet import SOURCE as SRC_IMMONET, scrape as scrape_immonet
from scraper.inberlinwohnen import SOURCE as SRC_INBERLINWOHNEN, scrape as scrape_inberlinwohnen
from scraper.stadtundland import SOURCE as SRC_STADTUNDLAND, scrape as scrape_stadtundland
from scraper.vonovia import SOURCE as SRC_VONOVIA, scrape as scrape_vonovia
from scraper.wbm import SOURCE as SRC_WBM, scrape as scrape_wbm
from scraper.wggesucht import SOURCE as SRC_WG_GESUCHT, scrape as scrape_wggesucht
from scraper.wohnungsgilde import SOURCE as SRC_WOHNUNGSGILDE, scrape as scrape_wohnungsgilde

ScraperFn = Callable[[], Awaitable[list[dict[str, Any]]]]

SCRAPERS_BY_SOURCE: dict[str, ScraperFn] = {
    SRC_GEWOBA: scrape_gewobag,
    SRC_DEGEWO: scrape_degewo,
    SRC_HOWOGE: scrape_howoge,
    SRC_STADTUNDLAND: scrape_stadtundland,
    SRC_DEUTSCHEWOHNEN: scrape_deutschewohnen,
    SRC_BERLINOVO: scrape_berlinovo,
    SRC_VONOVIA: scrape_vonovia,
    SRC_GESOBAU: scrape_gesobau,
    SRC_WBM: scrape_wbm,
    SRC_IMMOSCOUT: scrape_immoscout,
    SRC_WG_GESUCHT: scrape_wggesucht,
    SRC_EBAY_KLEINANZEIGEN: scrape_kleinanzeigen,
    SRC_IMMOWELT: scrape_immowelt,
    SRC_IMMONET: scrape_immonet,
    SRC_INBERLINWOHNEN: scrape_inberlinwohnen,
    SRC_WOHNUNGSGILDE: scrape_wohnungsgilde,
}

ALL_SOURCE_IDS: list[str] = list(SCRAPERS_BY_SOURCE.keys())


def select_scraper_pairs(cfg: dict[str, Any]) -> list[tuple[str, ScraperFn]]:
    enabled = cfg.get("sources") or []
    enabled_ids = [str(s).strip() for s in enabled if str(s).strip()]
    if not enabled_ids:
        return []
    out: list[tuple[str, ScraperFn]] = []
    for sid in enabled_ids:
        fn = SCRAPERS_BY_SOURCE.get(sid)
        if fn:
            out.append((sid, fn))
    return out


def select_scrapers(cfg: dict[str, Any]) -> list[ScraperFn]:
    return [fn for _, fn in select_scraper_pairs(cfg)]

