"""
Local JSON-based deduplication for "seen" listings.

Used to prevent sending duplicate notifications, especially across restarts.
Stores only minimal identity fields (listing `id` plus timestamps/URL).
"""

from __future__ import annotations

import json
import os
import time
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _safe_load_json(path: str) -> dict[str, Any]:
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except Exception as e:
        logger.warning("seen_store: failed to load %s: %s", path, e)
        return {}


def load_seen_ids(path: str) -> set[str]:
    data = _safe_load_json(path)
    ids = set(data.keys())
    # Backward compatibility: if file stored a list
    if not ids and isinstance(data, list):
        return {str(x) for x in data if x}
    return {str(x) for x in ids if x}


def persist_seen(path: str, new_entries: dict[str, Any]) -> None:
    """
    Merge `new_entries` into file atomically.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        # os.path.dirname can be empty in edge cases; ignore.
        pass

    current = _safe_load_json(path)
    current.update(new_entries)

    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            # No pretty printing: keeps writes small and fast on mobile storage.
            json.dump(current, f, ensure_ascii=False)
        os.replace(tmp_path, path)
    except Exception as e:
        logger.warning("seen_store: failed to persist %s: %s", path, e)
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass


def make_seen_entry(listing: dict) -> dict[str, Any]:
    """
    Create a compact JSON entry for a listing.
    """
    lid = str(listing.get("id") or "")
    url = str(listing.get("url") or "")
    now = int(time.time())
    if not lid:
        return {}
    return {
        lid: {
            "url": url,
            "ts": now,
        }
    }

