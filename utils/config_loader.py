from __future__ import annotations

import json
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_DEFAULT: dict[str, Any] = {
    "city": "Berlin",
    "max_price": 700,
    "min_size": 30,
    "rooms": 1,
    "wbs_required": True,
    "interval_minutes": 10,
    "keywords_include": [],
    "keywords_exclude": [],
    "send_images": True,
    "wbs_filter": [],
    "max_per_cycle": 5,
    "detail_concurrency": 4,
}


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        iv = int(v)
        return max(lo, min(hi, iv))
    except Exception:
        return default


def _bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if v in (1, "1", "true", "True", "yes"):
        return True
    if v in (0, "0", "false", "False", "no"):
        return False
    return default


def _str_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        return [p.strip() for p in v.split(",") if p.strip()]
    return []


def load_config(path: str | None = None) -> dict[str, Any]:
    cfg_path = path or os.path.join(_ROOT_DIR, "config.json")
    if not os.path.exists(cfg_path):
        logger.warning("config.json missing; using defaults.")
        raw = dict(_DEFAULT)
    else:
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            logger.error("Failed to read config.json: %s", e)
            raw = dict(_DEFAULT)

    out = dict(_DEFAULT)
    out.update(raw)

    out["city"] = str(out.get("city") or "Berlin")
    try:
        out["max_price"] = float(out.get("max_price", _DEFAULT["max_price"]))
    except Exception:
        out["max_price"] = float(_DEFAULT["max_price"])
    try:
        out["min_size"] = float(out["min_size"]) if out.get("min_size") is not None else None
    except Exception:
        out["min_size"] = _DEFAULT["min_size"]
    try:
        out["rooms"] = float(out["rooms"]) if out.get("rooms") is not None else None
    except Exception:
        out["rooms"] = _DEFAULT["rooms"]

    out["wbs_required"] = _bool(out.get("wbs_required"), True)
    out["send_images"] = _bool(out.get("send_images"), True)
    out["interval_minutes"] = _clamp_int(out.get("interval_minutes"), 5, 60, 10)
    out["keywords_include"] = _str_list(out.get("keywords_include"))
    out["keywords_exclude"] = _str_list(out.get("keywords_exclude"))
    out["wbs_filter"] = _str_list(out.get("wbs_filter"))
    out["max_per_cycle"] = _clamp_int(out.get("max_per_cycle"), 1, 50, 5)
    out["detail_concurrency"] = _clamp_int(out.get("detail_concurrency"), 1, 10, 4)

    return out
