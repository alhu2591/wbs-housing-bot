"""
Public `scraper/` package wrapper.

The codebase currently keeps implementations under `scrapers/`.
This wrapper exists to match the requested architecture (`scraper/`).
"""

from scrapers import ALL_SCRAPERS

__all__ = ["ALL_SCRAPERS"]

