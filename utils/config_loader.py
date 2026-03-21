from __future__ import annotations

import json
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)


_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CONFIG: dict[str, Any] = {
    "city": "Berlin",
    "max_price": 600,
    "wbs_filter": ["wbs 100"],
    "interval_minutes": 12,
}


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        iv = int(v)
        if iv < lo:
            return lo
        if iv > hi:
            return hi
        return iv
    except Exception:
        return default


def _normalize_wbs_filter(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        # allow comma-separated config values
        parts = [p.strip() for p in v.split(",")]
        return [p for p in parts if p]
    return []


def load_config(path: str | None = None) -> dict[str, Any]:
    """Load `config.json` from project root."""
    cfg_path = path or os.path.join(_ROOT_DIR, "config.json")
    if not os.path.exists(cfg_path):
        logger.warning("config.json missing; using defaults.")
        cfg = dict(_DEFAULT_CONFIG)
    else:
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            logger.error("Failed to read config.json: %s", e)
            cfg = dict(_DEFAULT_CONFIG)

    city = str(cfg.get("city") or "Berlin")
    max_price = cfg.get("max_price", 600)
    try:
        max_price_f = float(max_price)
    except Exception:
        max_price_f = float(_DEFAULT_CONFIG["max_price"])

    interval = _clamp_int(cfg.get("interval_minutes", 12), 10, 15, 12)
    wbs_filter = _normalize_wbs_filter(cfg.get("wbs_filter") or cfg.get("WBS filter"))

    return {
        "city": city,
        "max_price": max_price_f,
        "wbs_filter": wbs_filter,
        "interval_minutes": interval,
    }

