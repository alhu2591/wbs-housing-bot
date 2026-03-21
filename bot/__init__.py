"""
Public bot package.

The project historically placed Telegram logic under `config/bot/`.
This wrapper keeps imports stable for `python main.py`.
"""

from .handlers import build_app, format_listing

__all__ = ["build_app", "format_listing"]

