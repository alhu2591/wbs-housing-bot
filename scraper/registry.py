"""All site scrapers (overview → listing stubs)."""
from __future__ import annotations

from scraper.berlinovo import scrape as scrape_berlinovo
from scraper.degewo import scrape as scrape_degewo
from scraper.deutschewohnen import scrape as scrape_deutschewohnen
from scraper.ebay_kleinanzeigen import scrape as scrape_kleinanzeigen
from scraper.gesobau import scrape as scrape_gesobau
from scraper.gewobag import scrape as scrape_gewobag
from scraper.howoge import scrape as scrape_howoge
from scraper.immoscout import scrape as scrape_immoscout
from scraper.immowelt import scrape as scrape_immowelt
from scraper.stadtundland import scrape as scrape_stadtundland
from scraper.vonovia import scrape as scrape_vonovia
from scraper.wbm import scrape as scrape_wbm
from scraper.wggesucht import scrape as scrape_wggesucht

ALL_SCRAPERS = [
    scrape_gewobag,
    scrape_degewo,
    scrape_howoge,
    scrape_stadtundland,
    scrape_deutschewohnen,
    scrape_berlinovo,
    scrape_vonovia,
    scrape_gesobau,
    scrape_wbm,
    scrape_immoscout,
    scrape_wggesucht,
    scrape_kleinanzeigen,
    scrape_immowelt,
]
