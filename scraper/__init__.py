"""Scraper package — site modules + pipeline."""

from scraper.pipeline import scrape_new_listings
from scraper.registry import ALL_SCRAPERS

__all__ = ["scrape_new_listings", "ALL_SCRAPERS"]
