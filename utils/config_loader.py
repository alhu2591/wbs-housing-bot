from __future__ import annotations

import json
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_required_int(v: Any, lo: int, hi: int, name: str) -> int:
    if v is None:
        raise ValueError(f"config.json: `{name}` must be set (got null).")
    try:
        iv = int(float(v))
    except Exception as e:
        raise ValueError(f"config.json: `{name}` must be an integer: {e}") from e
    return max(lo, min(hi, iv))


def _parse_required_bool(v: Any, name: str) -> bool:
    if v is None:
        raise ValueError(f"config.json: `{name}` must be set (got null).")
    if isinstance(v, bool):
        return v
    if v in (1, "1", "true", "True", "yes"):
        return True
    if v in (0, "0", "false", "False", "no"):
        return False
    raise ValueError(f"config.json: `{name}` must be boolean (true/false). Got: {v!r}")


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
        raise FileNotFoundError(
            f"config.json missing at {cfg_path}. Create it (see README) before starting the bot."
        )
    else:
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            logger.error("Failed to read config.json: %s", e)
            raise

    out: dict[str, Any] = dict(raw or {})

    required_keys = [
        "city",
        "districts",
        "max_price",
        "min_size",
        "rooms",
        "wbs_required",
        "wbs_level",
        "jobcenter_required",
        "wohnungsgilde_required",
        "interval_minutes",
        "keywords_include",
        "keywords_exclude",
        "wbs_filter",
        "send_images",
        "notify_enabled",
        "sources",
        "max_images",
        "max_per_cycle",
        "detail_concurrency",
    ]
    missing = [k for k in required_keys if k not in out]
    if missing:
        raise ValueError(f"config.json is missing required keys: {missing}")

    # City filter: empty string disables city filtering.
    out["city"] = str(out.get("city") or "").strip()
    out["districts"] = _str_list(out.get("districts"))

    # Numeric filters: set to null to disable.
    max_price = out.get("max_price")
    out["max_price"] = (
        float(max_price)
        if max_price is not None and str(max_price).strip() != ""
        else None
    )
    min_size = out.get("min_size")
    out["min_size"] = (
        float(min_size) if min_size is not None and str(min_size).strip() != "" else None
    )
    rooms = out.get("rooms")
    out["rooms"] = float(rooms) if rooms is not None and str(rooms).strip() != "" else None
    wbs_level = out.get("wbs_level")
    out["wbs_level"] = int(float(wbs_level)) if wbs_level is not None and str(wbs_level).strip() != "" else None
    if out["wbs_level"] is not None:
        if out["wbs_level"] < 100:
            out["wbs_level"] = 100
        if out["wbs_level"] > 200:
            out["wbs_level"] = 200

    # Booleans
    out["wbs_required"] = _parse_required_bool(out.get("wbs_required"), "wbs_required")
    out["jobcenter_required"] = _parse_required_bool(out.get("jobcenter_required"), "jobcenter_required")
    out["wohnungsgilde_required"] = _parse_required_bool(out.get("wohnungsgilde_required"), "wohnungsgilde_required")
    out["send_images"] = _parse_required_bool(out.get("send_images"), "send_images")
    out["notify_enabled"] = _parse_required_bool(out.get("notify_enabled"), "notify_enabled")

    # Scheduler controls
    out["interval_minutes"] = _parse_required_int(out.get("interval_minutes"), 5, 60, "interval_minutes")

    # Media controls
    out["max_images"] = _parse_required_int(out.get("max_images"), 1, 10, "max_images")

    # Keywords + WBS phrases
    out["keywords_include"] = _str_list(out.get("keywords_include"))
    out["keywords_exclude"] = _str_list(out.get("keywords_exclude"))
    out["wbs_filter"] = _str_list(out.get("wbs_filter"))

    # Sources
    out["sources"] = _str_list(out.get("sources"))

    # Pipeline limits
    out["max_per_cycle"] = _parse_required_int(out.get("max_per_cycle"), 1, 50, "max_per_cycle")
    out["detail_concurrency"] = _parse_required_int(out.get("detail_concurrency"), 1, 10, "detail_concurrency")

    return out
