"""
Runtime options for HTTP fetching (robots, delays, Playwright).

Set once from `main.py` after config load so `base_scraper.fetch` stays usable
without threading cfg through every call site.
"""
from __future__ import annotations

from typing import Any

_CFG: dict[str, Any] = {
    "respect_robots": True,
    "use_playwright": False,
    "scrape_delay_min": 1.0,
    "scrape_delay_max": 3.0,
    "playwright_timeout_ms": 30000,
}


def set_fetch_runtime(cfg: dict[str, Any] | None) -> None:
    global _CFG
    if not cfg:
        return
    c = dict(_CFG)
    for k in (
        "respect_robots",
        "use_playwright",
        "scrape_delay_min",
        "scrape_delay_max",
        "playwright_timeout_ms",
    ):
        if k in cfg:
            c[k] = cfg[k]
    _CFG = c


def get_fetch_runtime() -> dict[str, Any]:
    return dict(_CFG)
