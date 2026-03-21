"""
Runtime configuration store.

Telegram can update settings at runtime; we persist them to `data/config.json`
so changes survive restarts.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def runtime_config_path() -> str:
    data_dir = os.path.join(_ROOT_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "config.json")


def _safe_load_json(path: str) -> dict[str, Any] | None:
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= 1:
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning("config_store: failed to read %s: %s", path, e)
        return None


def load_runtime_config(base_cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Load runtime config from `data/config.json`.

    If it doesn't exist yet, we initialize it from `base_cfg` (the validated
    `config.json` from project root).
    """
    path = runtime_config_path()
    existing = _safe_load_json(path)
    if existing is None:
        try:
            save_runtime_config(base_cfg, path=path)
        except Exception:
            # If persistence fails, still run with base config.
            logger.warning("config_store: failed to initialize runtime config.")
        return dict(base_cfg)
    out = dict(existing)

    # If `data/config.json` comes from an older base config, we still want new
    # portals added in the project `config.json` to become active automatically
    # (unless the user explicitly disabled all sources with an empty list).
    try:
        base_sources = set(base_cfg.get("sources") or [])
        runtime_sources = set(out.get("sources") or [])
        if base_sources and runtime_sources:
            out["sources"] = sorted(runtime_sources | (base_sources - runtime_sources))
    except Exception as e:
        logger.warning("config_store: failed to merge sources: %s", e)

    return out


def save_runtime_config(cfg: dict[str, Any], *, path: str | None = None) -> None:
    """
    Atomically persist runtime config.
    """
    path = path or runtime_config_path()
    tmp = f"{path}.tmp-{int(time.time())}"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

