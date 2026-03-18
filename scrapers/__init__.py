from .gewobag import scrape as scrape_gewobag
from .degewo import scrape as scrape_degewo
from .howoge import scrape as scrape_howoge
from .stadtundland import scrape as scrape_stadtundland
from .deutschewohnen import scrape as scrape_deutschewohnen
from .berlinovo import scrape as scrape_berlinovo
from .immoscout import scrape as scrape_immoscout
from .wggesucht import scrape as scrape_wggesucht
from .ebay_kleinanzeigen import scrape as scrape_kleinanzeigen
from .immowelt import scrape as scrape_immowelt

ALL_SCRAPERS = [
    scrape_gewobag,
    scrape_degewo,
    scrape_howoge,
    scrape_stadtundland,
    scrape_deutschewohnen,
    scrape_berlinovo,
    scrape_immoscout,
    scrape_wggesucht,
    scrape_kleinanzeigen,
    scrape_immowelt,
]
