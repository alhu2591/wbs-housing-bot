"""
database/db.py — SQLite persistence layer.
Stores listings, seen hashes, scores, and source stats.
Thread-safe via WAL mode. Termux-friendly.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "housing.db"
)


def _db_path() -> str:
    return os.environ.get("HOUSING_DB_PATH", _DEFAULT_PATH)


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    path = _db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, check_same_thread=False, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    """Create tables if they don't exist."""
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS seen_hashes (
            hash TEXT PRIMARY KEY,
            url TEXT,
            seen_at REAL
        );

        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hash TEXT UNIQUE,
            url TEXT,
            title TEXT,
            price REAL,
            location TEXT,
            size_m2 REAL,
            rooms REAL,
            score INTEGER DEFAULT 0,
            jobcenter_ok INTEGER DEFAULT 0,
            ai_type TEXT,
            wbs_label TEXT,
            source TEXT,
            data_json TEXT,
            created_at REAL
        );

        CREATE INDEX IF NOT EXISTS idx_listings_created ON listings(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_listings_score ON listings(score DESC);

        CREATE TABLE IF NOT EXISTS source_stats (
            source TEXT PRIMARY KEY,
            total_requests INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            fail_count INTEGER DEFAULT 0,
            last_response_ms REAL DEFAULT 0,
            last_seen_at REAL DEFAULT 0,
            disabled INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS system_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            level TEXT,
            message TEXT,
            created_at REAL
        );
        """)
    logger.info("Database initialised at %s", _db_path())


# ── Hash / deduplication ───────────────────────────────────────────────────

def make_hash(listing: dict[str, Any]) -> str:
    url = str(listing.get("url") or "")
    title = str(listing.get("title") or "")
    price = str(listing.get("price") or "")
    key = f"{url}|{title}|{price}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


def is_seen(hash_val: str) -> bool:
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM seen_hashes WHERE hash=?", (hash_val,)
        ).fetchone()
        return row is not None


def mark_seen(hash_val: str, url: str = "") -> None:
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO seen_hashes(hash, url, seen_at) VALUES(?,?,?)",
            (hash_val, url, time.time())
        )


def bulk_is_seen(hashes: list[str]) -> set[str]:
    if not hashes:
        return set()
    placeholders = ",".join("?" * len(hashes))
    with _conn() as con:
        rows = con.execute(
            f"SELECT hash FROM seen_hashes WHERE hash IN ({placeholders})", hashes
        ).fetchall()
    return {r["hash"] for r in rows}


# ── Listings persistence ───────────────────────────────────────────────────

def save_listing(listing: dict[str, Any]) -> None:
    h = make_hash(listing)
    try:
        price_val = float(str(listing.get("price") or 0).replace(",", ".").replace("€", ""))
    except (ValueError, TypeError):
        price_val = 0.0
    try:
        size_val = float(str(listing.get("size_m2") or 0).replace(",", "."))
    except (ValueError, TypeError):
        size_val = 0.0
    try:
        rooms_val = float(str(listing.get("rooms") or 0).replace(",", "."))
    except (ValueError, TypeError):
        rooms_val = 0.0

    with _conn() as con:
        con.execute("""
            INSERT OR IGNORE INTO listings
              (hash, url, title, price, location, size_m2, rooms,
               score, jobcenter_ok, ai_type, wbs_label, source, data_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            h,
            listing.get("url", ""),
            listing.get("title", ""),
            price_val,
            listing.get("location", ""),
            size_val,
            rooms_val,
            listing.get("score", 0),
            1 if listing.get("jobcenter_ok") else 0,
            listing.get("ai_type", "normal"),
            listing.get("wbs_label", ""),
            listing.get("source", ""),
            json.dumps(listing, ensure_ascii=False),
            time.time(),
        ))
        mark_seen(h, listing.get("url", ""))


def get_recent_listings(limit: int = 50) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM listings ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_listings_count() -> int:
    with _conn() as con:
        row = con.execute("SELECT COUNT(*) as c FROM listings").fetchone()
        return row["c"] if row else 0


def get_seen_count() -> int:
    with _conn() as con:
        row = con.execute("SELECT COUNT(*) as c FROM seen_hashes").fetchone()
        return row["c"] if row else 0


# ── Source stats ───────────────────────────────────────────────────────────

def record_source_result(source: str, success: bool, response_ms: float = 0) -> None:
    with _conn() as con:
        con.execute("""
            INSERT INTO source_stats(source, total_requests, success_count, fail_count, last_response_ms, last_seen_at)
            VALUES (?, 1, ?, ?, ?, ?)
            ON CONFLICT(source) DO UPDATE SET
              total_requests = total_requests + 1,
              success_count = success_count + excluded.success_count,
              fail_count = fail_count + excluded.fail_count,
              last_response_ms = excluded.last_response_ms,
              last_seen_at = excluded.last_seen_at
        """, (
            source,
            1 if success else 0,
            0 if success else 1,
            response_ms,
            time.time(),
        ))


def get_source_stats() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM source_stats ORDER BY source").fetchall()
    return [dict(r) for r in rows]


def set_source_disabled(source: str, disabled: bool) -> None:
    with _conn() as con:
        con.execute(
            "INSERT INTO source_stats(source, disabled) VALUES(?,?) "
            "ON CONFLICT(source) DO UPDATE SET disabled=excluded.disabled",
            (source, 1 if disabled else 0)
        )


def get_disabled_sources() -> set[str]:
    with _conn() as con:
        rows = con.execute(
            "SELECT source FROM source_stats WHERE disabled=1"
        ).fetchall()
    return {r["source"] for r in rows}


# ── System events log ──────────────────────────────────────────────────────

def log_event(level: str, message: str) -> None:
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO system_events(level, message, created_at) VALUES(?,?,?)",
                (level, message[:2000], time.time())
            )
    except Exception:
        pass


def get_recent_events(limit: int = 100) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM system_events ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_daily_summary() -> dict:
    """Stats for the last 24 hours."""
    since = time.time() - 86400
    with _conn() as con:
        listings_today = con.execute(
            "SELECT COUNT(*) as c FROM listings WHERE created_at > ?", (since,)
        ).fetchone()["c"]
        errors_today = con.execute(
            "SELECT COUNT(*) as c FROM system_events WHERE created_at > ? AND level='ERROR'",
            (since,)
        ).fetchone()["c"]
    return {
        "listings_found_24h": listings_today,
        "errors_24h": errors_today,
        "total_listings": get_listings_count(),
        "total_seen": get_seen_count(),
    }
