"""
Persistent deduplication: SQLite + content hash (see `seen_store`).

`default_seen_path()` points at the SQLite DB; legacy `seen.json` is migrated automatically.
"""
from __future__ import annotations

from typing import Any

from utils.seen_store import SeenStore, default_db_path, make_seen_entry

_STORE: SeenStore | None = None


def get_seen_store() -> SeenStore:
    global _STORE
    if _STORE is None:
        _STORE = SeenStore()
    return _STORE


def default_seen_path() -> str:
    """Primary persistence path (SQLite). Kept for logging / compatibility."""
    return default_db_path()


def load_seen_ids(path: str) -> set[str]:
    """Load seen listing IDs (SQLite or JSON fallback inside SeenStore)."""
    return get_seen_store().load_id_set()


def persist_seen_listings(listings: list[dict[str, Any]]) -> None:
    """Mark listings as seen with full records (correct content hash)."""
    get_seen_store().persist_batch(listings)


def persist_seen(path: str, new_entries: dict[str, Any]) -> None:
    """Legacy API: merge dict of id → meta. Prefer `persist_seen_listings` with full listings."""
    listings: list[dict[str, Any]] = []
    for lid, meta in (new_entries or {}).items():
        if not lid:
            continue
        m = meta if isinstance(meta, dict) else {}
        listings.append(
            {
                "id": str(lid),
                "url": str(m.get("url") or ""),
                "title": "",
                "location": "",
                "district": "",
                "city": "",
                "price": None,
                "images": [],
            }
        )
    get_seen_store().persist_batch(listings)


__all__ = [
    "default_seen_path",
    "get_seen_store",
    "load_seen_ids",
    "make_seen_entry",
    "persist_seen",
    "persist_seen_listings",
]
