"""
HTML parsing helper that avoids a hard dependency on `lxml`.

Primary parser: `html.parser` (built-in, always available on Termux).
Optional fallback: `lxml` (only used if `html.parser` parsing errors).
"""

from __future__ import annotations

from bs4 import BeautifulSoup


def make_soup(html: str) -> BeautifulSoup:
    """Create BeautifulSoup using the Termux-safe built-in parser."""
    return BeautifulSoup(html, "html.parser")

