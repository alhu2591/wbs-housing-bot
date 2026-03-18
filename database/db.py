"""
Async SQLite layer — WAL mode, auto-migration, stats.
"""
import json
import logging
import aiosqlite
from datetime import datetime, timedelta
from config.settings import DB_PATH, LISTING_TTL_DAYS

logger = logging.getLogger(__name__)

# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = [
    """
    CREATE TABLE IF NOT EXISTS listings (
        id              TEXT PRIMARY KEY,
        url             TEXT NOT NULL,
        title           TEXT,
        price           REAL,
        location        TEXT,
        rooms           REAL,
        size_m2         REAL,
        floor           TEXT,
        available_from  TEXT,
        features        TEXT DEFAULT '[]',
        score           INTEGER DEFAULT 0,
        source          TEXT,
        created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_settings (
        chat_id     TEXT PRIMARY KEY,
        active      INTEGER DEFAULT 1,
        max_price   REAL    DEFAULT 600,
        min_rooms   REAL    DEFAULT 0,
        area        TEXT    DEFAULT '',
        wbs_only    INTEGER DEFAULT 0,
        updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bot_stats (
        id           INTEGER PRIMARY KEY CHECK (id = 1),
        total_sent   INTEGER DEFAULT 0,
        total_cycles INTEGER DEFAULT 0,
        last_sent_at DATETIME,
        updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "INSERT OR IGNORE INTO bot_stats (id) VALUES (1)",
]

# Columns added in later versions — migrated automatically
_MIGRATIONS = [
    ("listings",       "size_m2",        "REAL"),
    ("listings",       "floor",          "TEXT"),
    ("listings",       "available_from", "TEXT"),
    ("listings",       "features",       "TEXT DEFAULT '[]'"),
    ("listings",       "score",          "INTEGER DEFAULT 0"),
    ("user_settings",  "wbs_only",       "INTEGER DEFAULT 0"),
    ("user_settings",  "areas",          "TEXT DEFAULT '[]'"),
]


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        # WAL mode = much better concurrent read/write + crash safety
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA cache_size=-8000")   # 8 MB cache
        await db.execute("PRAGMA temp_store=MEMORY")

        for stmt in _DDL:
            await db.execute(stmt)

        # Auto-migrate: add new columns without destroying existing data
        for table, col, coltype in _MIGRATIONS:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            except Exception:
                pass  # Already exists

        await db.commit()
    logger.info("✅ Database ready — %s", DB_PATH)


# ── Listings ──────────────────────────────────────────────────────────────────

async def is_known(listing_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM listings WHERE id = ?", (listing_id,)
        ) as cur:
            return await cur.fetchone() is not None


async def save_listing(listing: dict) -> None:
    features_json = json.dumps(listing.get("features") or [], ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO listings
              (id, url, title, price, location, rooms, size_m2,
               floor, available_from, features, score, source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                listing.get("id"),
                listing.get("url"),
                listing.get("title"),
                listing.get("price"),
                listing.get("location"),
                listing.get("rooms"),
                listing.get("size_m2"),
                listing.get("floor"),
                listing.get("available_from"),
                features_json,
                listing.get("score", 0),
                listing.get("source"),
            ),
        )
        await db.commit()


async def get_recent_listings(limit: int = 5) -> list[dict]:
    """Return the N most recently saved listings."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """SELECT id, title, price, location, rooms, source, url, created_at
               FROM listings ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def purge_old_listings() -> int:
    cutoff = datetime.utcnow() - timedelta(days=LISTING_TTL_DAYS)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM listings WHERE created_at < ?", (cutoff.isoformat(),)
        )
        await db.commit()
    if cur.rowcount:
        logger.info("🗑 Purged %d old listings", cur.rowcount)
    return cur.rowcount


# ── Stats ─────────────────────────────────────────────────────────────────────

async def increment_stats(sent: int = 0, cycle: int = 0) -> None:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """UPDATE bot_stats SET
                 total_sent   = total_sent   + ?,
                 total_cycles = total_cycles + ?,
                 last_sent_at = CASE WHEN ? > 0 THEN ? ELSE last_sent_at END,
                 updated_at   = ?
               WHERE id = 1""",
            (sent, cycle, sent, now, now),
        )
        await db.commit()


async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute("SELECT * FROM bot_stats WHERE id=1")).fetchone()
        cnt = await (await db.execute("SELECT COUNT(*) FROM listings")).fetchone()
    return {
        "total_sent":   row["total_sent"]   if row else 0,
        "total_cycles": row["total_cycles"] if row else 0,
        "last_sent_at": row["last_sent_at"] if row else None,
        "db_size":      cnt[0] if cnt else 0,
    }


# ── User Settings ─────────────────────────────────────────────────────────────

async def get_settings(chat_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_settings WHERE chat_id=?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
    return {"chat_id": chat_id, "active": 1, "max_price": 600, "min_rooms": 0, "area": "", "wbs_only": 0, "areas": "[]"}


async def upsert_settings(chat_id: str, **kwargs) -> None:
    current = await get_settings(chat_id)
    current.update(kwargs)
    current["chat_id"]    = chat_id
    current["updated_at"] = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO user_settings (chat_id, active, max_price, min_rooms, area, wbs_only, areas, updated_at)
               VALUES (:chat_id,:active,:max_price,:min_rooms,:area,:wbs_only,:areas,:updated_at)
               ON CONFLICT(chat_id) DO UPDATE SET
                 active=excluded.active, max_price=excluded.max_price,
                 min_rooms=excluded.min_rooms, area=excluded.area,
                 wbs_only=excluded.wbs_only, areas=excluded.areas,
                 updated_at=excluded.updated_at""",
            current,
        )
        await db.commit()
