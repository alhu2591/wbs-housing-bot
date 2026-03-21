"""
Persistent deduplication: SQLite primary, JSON fallback.

Tracks listing id, content hash (title+price+location), and image fingerprint
to reduce duplicates across portals.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any

from utils.dedup_hash import listing_content_hash, listing_image_fingerprint

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()


def default_db_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(root, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "seen.db")


def _json_fallback_path() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(root, "data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "seen.json")


class SeenStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or default_db_path()
        self.json_path = _json_fallback_path()
        self._conn: sqlite3.Connection | None = None
        self._use_sqlite = True
        self._init_db()

    def _init_db(self) -> None:
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen (
                    listing_id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    image_fp TEXT,
                    url TEXT,
                    source TEXT,
                    ts INTEGER NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_seen_content ON seen(content_hash)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_seen_image ON seen(image_fp)"
            )
            self._conn.commit()
            self._migrate_json_if_needed()
        except Exception as e:
            logger.warning("seen SQLite unavailable (%s) — using JSON fallback", e)
            self._conn = None
            self._use_sqlite = False

    def _migrate_json_if_needed(self) -> None:
        if not self._conn:
            return
        try:
            cur = self._conn.execute("SELECT COUNT(*) FROM seen")
            n = int(cur.fetchone()[0])
        except Exception:
            n = 0
        if n > 0:
            return
        legacy = self.json_path
        if not os.path.exists(legacy) or os.path.getsize(legacy) < 3:
            root_legacy = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "seen.json"
            )
            if os.path.exists(root_legacy) and os.path.getsize(root_legacy) > 3:
                legacy = root_legacy
            else:
                return
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                data = json.load(f)
            rows = []
            if isinstance(data, dict):
                for lid, meta in data.items():
                    if not lid:
                        continue
                    url = ""
                    ts = int(time.time())
                    if isinstance(meta, dict):
                        url = str(meta.get("url") or "")
                        ts = int(meta.get("ts") or ts)
                    rows.append((str(lid), "", None, url, "", ts))
            elif isinstance(data, list):
                for lid in data:
                    if lid:
                        rows.append((str(lid), "", None, "", "", int(time.time())))
            if rows:
                self._conn.executemany(
                    "INSERT OR IGNORE INTO seen(listing_id, content_hash, image_fp, url, source, ts) VALUES (?,?,?,?,?,?)",
                    [(r[0], r[1] or "legacy", r[2], r[3], r[4], r[5]) for r in rows],
                )
                self._conn.commit()
                logger.info("Migrated %d entries from JSON → SQLite", len(rows))
        except Exception as e:
            logger.warning("JSON migration failed: %s", e)

    def load_content_hashes(self) -> set[str]:
        if self._conn:
            try:
                cur = self._conn.execute("SELECT content_hash FROM seen WHERE content_hash != ''")
                return {str(r[0]) for r in cur.fetchall() if r[0]}
            except Exception as e:
                logger.warning("seen load_content_hashes: %s", e)
        return set()

    def load_image_fingerprints(self) -> set[str]:
        if self._conn:
            try:
                cur = self._conn.execute(
                    "SELECT image_fp FROM seen WHERE image_fp IS NOT NULL AND image_fp != ''"
                )
                return {str(r[0]) for r in cur.fetchall() if r[0]}
            except Exception as e:
                logger.warning("seen load_image_fp: %s", e)
        return set()

    def load_id_set(self) -> set[str]:
        if self._conn:
            try:
                cur = self._conn.execute("SELECT listing_id FROM seen")
                return {str(r[0]) for r in cur.fetchall() if r[0]}
            except Exception as e:
                logger.warning("seen load_id_set: %s", e)
        # JSON fallback
        try:
            if not os.path.exists(self.json_path):
                return set()
            with open(self.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return {str(x) for x in data.keys() if x}
            if isinstance(data, list):
                return {str(x) for x in data if x}
        except Exception as e:
            logger.warning("seen JSON load: %s", e)
        return set()

    def is_duplicate(self, listing: dict[str, Any], seen_ids: set[str]) -> bool:
        lid = str(listing.get("id") or "")
        if lid and lid in seen_ids:
            logger.debug("dedup: id match %s", lid[:16])
            return True
        ch = listing_content_hash(listing)
        if self._conn:
            try:
                cur = self._conn.execute(
                    "SELECT 1 FROM seen WHERE content_hash = ? LIMIT 1", (ch,)
                )
                if cur.fetchone():
                    logger.info(
                        "dedup: content_hash match (cross-source?) title=%s",
                        (listing.get("title") or "")[:50],
                    )
                    return True
                ih = listing_image_fingerprint(listing)
                if ih:
                    cur = self._conn.execute(
                        "SELECT 1 FROM seen WHERE image_fp = ? AND image_fp != '' LIMIT 1",
                        (ih,),
                    )
                    if cur.fetchone():
                        logger.info("dedup: image fingerprint match")
                        return True
            except Exception as e:
                logger.warning("dedup sqlite check: %s", e)
        else:
            # JSON fallback: ids only (legacy)
            pass
        return False

    def persist_batch(self, listings: list[dict[str, Any]]) -> None:
        if not listings:
            return
        now = int(time.time())
        with _LOCK:
            if self._conn:
                try:
                    for listing in listings:
                        lid = str(listing.get("id") or "")
                        if not lid:
                            continue
                        ch = listing_content_hash(listing)
                        ih = listing_image_fingerprint(listing)
                        self._conn.execute(
                            """INSERT OR REPLACE INTO seen(listing_id, content_hash, image_fp, url, source, ts)
                               VALUES (?,?,?,?,?,?)""",
                            (
                                lid,
                                ch,
                                ih,
                                str(listing.get("url") or ""),
                                str(listing.get("source") or ""),
                                now,
                            ),
                        )
                    self._conn.commit()
                    return
                except Exception as e:
                    logger.error("seen SQLite persist: %s — falling back to JSON", e)
            # JSON fallback
            path = self.json_path
            current: dict[str, Any] = {}
            try:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        raw = json.load(f)
                    if isinstance(raw, dict):
                        current = raw
            except Exception:
                current = {}
            for listing in listings:
                lid = str(listing.get("id") or "")
                if not lid:
                    continue
                current[lid] = {
                    "url": str(listing.get("url") or ""),
                    "ts": now,
                    "content_hash": listing_content_hash(listing),
                }
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(current, f, ensure_ascii=False)
            os.replace(tmp, path)


def make_seen_entry(listing: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible shape for callers expecting dict merge."""
    lid = str(listing.get("id") or "")
    url = str(listing.get("url") or "")
    if not lid:
        return {}
    return {
        lid: {
            "url": url,
            "ts": int(time.time()),
            "content_hash": listing_content_hash(listing),
        }
    }
