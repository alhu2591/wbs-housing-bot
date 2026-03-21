"""
Persistent deduplication store (seen listing IDs).
"""
from __future__ import annotations

import json
import os
import time
import logging
from typing import Any

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_seen_path() -> str:
    data_dir = os.path.join(_ROOT, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "seen.json")


def _safe_load(path: str) -> dict[str, Any]:
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except Exception as e:
        logger.warning("storage: failed to load %s: %s", path, e)
        return {}


def load_seen_ids(path: str) -> set[str]:
    data = _safe_load(path)
    ids = {str(x) for x in data.keys() if x}
    if not ids and isinstance(data, list):
        return {str(x) for x in data if x}
    return ids


def persist_seen(path: str, new_entries: dict[str, Any]) -> None:
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
    except Exception:
        pass

    current = _safe_load(path)
    current.update(new_entries)
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(current, f, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as e:
        logger.warning("storage: persist failed %s: %s", path, e)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


def make_seen_entry(listing: dict[str, Any]) -> dict[str, Any]:
    lid = str(listing.get("id") or "")
    url = str(listing.get("url") or "")
    if not lid:
        return {}
    return {lid: {"url": url, "ts": int(time.time())}}
