"""
Async SQLite — WAL mode, timeout guard, auto-migration.
"""
import json
import logging
import aiosqlite
from datetime import datetime, timedelta
from config.settings import DB_PATH, LISTING_TTL_DAYS

logger = logging.getLogger(__name__)

_DB_TIMEOUT = 10


async def _conn():
    db = await aiosqlite.connect(DB_PATH, timeout=_DB_TIMEOUT)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA cache_size=-8000")
    await db.execute("PRAGMA temp_store=MEMORY")
    await db.execute("PRAGMA busy_timeout=8000")
    return db


_DDL = [
    """CREATE TABLE IF NOT EXISTS listings (
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
    )""",
    """CREATE TABLE IF NOT EXISTS user_settings (
        chat_id          TEXT PRIMARY KEY,
        active           INTEGER DEFAULT 1,
        max_price        REAL    DEFAULT 600,
        min_rooms        REAL    DEFAULT 0,
        area             TEXT    DEFAULT '',
        wbs_only         INTEGER DEFAULT 0,
        areas            TEXT    DEFAULT '[]',
        sources          TEXT    DEFAULT '[]',
        household_size   INTEGER DEFAULT 1,
        jobcenter_mode   INTEGER DEFAULT 0,
        wohngeld_mode    INTEGER DEFAULT 0,
        wbs_level_min    INTEGER DEFAULT 0,
        wbs_level_max    INTEGER DEFAULT 999,
        quiet_start      INTEGER DEFAULT -1,
        quiet_end        INTEGER DEFAULT -1,
        max_per_cycle    INTEGER DEFAULT 10,
        updated_at       DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS bot_stats (
        id           INTEGER PRIMARY KEY CHECK (id = 1),
        total_sent   INTEGER DEFAULT 0,
        total_cycles INTEGER DEFAULT 0,
        last_sent_at DATETIME,
        updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
    )""",
    "INSERT OR IGNORE INTO bot_stats (id) VALUES (1)",
]

_MIGRATIONS = [
    ("listings",       "size_m2",        "REAL"),
    ("listings",       "floor",          "TEXT"),
    ("listings",       "available_from", "TEXT"),
    ("listings",       "features",       "TEXT DEFAULT '[]'"),
    ("listings",       "score",          "INTEGER DEFAULT 0"),
    ("user_settings",  "wbs_only",       "INTEGER DEFAULT 0"),
    ("user_settings",  "areas",          "TEXT DEFAULT '[]'"),
    ("user_settings",  "household_size", "INTEGER DEFAULT 1"),
    ("user_settings",  "jobcenter_mode", "INTEGER DEFAULT 0"),
    ("user_settings",  "wohngeld_mode",  "INTEGER DEFAULT 0"),
    ("user_settings",  "wbs_level_min",  "INTEGER DEFAULT 0"),
    ("user_settings",  "wbs_level_max",  "INTEGER DEFAULT 999"),
    ("user_settings",  "sources",        "TEXT DEFAULT '[]'"),
    ("user_settings",  "quiet_start",    "INTEGER DEFAULT -1"),
    ("user_settings",  "quiet_end",      "INTEGER DEFAULT -1"),
    ("user_settings",  "max_per_cycle",  "INTEGER DEFAULT 10"),
]


async def init_db() -> None:
    db = await _conn()
    try:
        for stmt in _DDL:
            await db.execute(stmt)
        for table, col, coltype in _MIGRATIONS:
            try:
                await db.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
            except Exception:
                pass
        await db.commit()
    finally:
        await db.close()
    logger.info("✅ DB ready — %s", DB_PATH)


async def is_known(listing_id: str) -> bool:
    if not listing_id:
        return False
    db = await _conn()
    try:
        async with db.execute("SELECT 1 FROM listings WHERE id=?", (listing_id,)) as cur:
            return await cur.fetchone() is not None
    finally:
        await db.close()


async def are_known(ids: list[str]) -> set[str]:
    if not ids:
        return set()
    clean = [i for i in ids if i]
    if not clean:
        return set()
    result: set[str] = set()
    for i in range(0, len(clean), 900):
        chunk = clean[i:i+900]
        placeholders = ",".join("?" * len(chunk))
        db = await _conn()
        try:
            async with db.execute(f"SELECT id FROM listings WHERE id IN ({placeholders})", chunk) as cur:
                result.update(row[0] for row in await cur.fetchall())
        finally:
            await db.close()
    return result


async def save_listing(listing: dict) -> None:
    lid = listing.get("id")
    if not lid:
        return
    features_json = json.dumps(listing.get("features") or [], ensure_ascii=False)
    db = await _conn()
    try:
        await db.execute(
            """INSERT OR IGNORE INTO listings
               (id,url,title,price,location,rooms,size_m2,floor,available_from,features,score,source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (lid, listing.get("url"), listing.get("title"),
             listing.get("price"), listing.get("location"), listing.get("rooms"),
             listing.get("size_m2"), listing.get("floor"),
             listing.get("available_from"), features_json,
             listing.get("score", 0), listing.get("source")),
        )
        await db.commit()
    finally:
        await db.close()


async def get_recent_listings(limit: int = 5) -> list[dict]:
    db = await _conn()
    try:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT id,title,price,location,rooms,source,url,created_at FROM listings ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
    finally:
        await db.close()


async def purge_old_listings() -> int:
    cutoff = datetime.utcnow() - timedelta(days=LISTING_TTL_DAYS)
    db = await _conn()
    try:
        cur = await db.execute("DELETE FROM listings WHERE created_at<?", (cutoff.isoformat(),))
        await db.commit()
        if cur.rowcount:
            logger.info("🗑 Purged %d listings", cur.rowcount)
        return cur.rowcount
    finally:
        await db.close()


async def increment_stats(sent: int = 0, cycle: int = 0) -> None:
    now = datetime.utcnow().isoformat()
    db  = await _conn()
    try:
        await db.execute(
            """UPDATE bot_stats SET
               total_sent=total_sent+?, total_cycles=total_cycles+?,
               last_sent_at=CASE WHEN ?>0 THEN ? ELSE last_sent_at END,
               updated_at=? WHERE id=1""",
            (sent, cycle, sent, now, now),
        )
        await db.commit()
    finally:
        await db.close()


async def get_stats() -> dict:
    db = await _conn()
    try:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute("SELECT * FROM bot_stats WHERE id=1")).fetchone()
        cnt = await (await db.execute("SELECT COUNT(*) FROM listings")).fetchone()
        return {
            "total_sent":   row["total_sent"]   if row else 0,
            "total_cycles": row["total_cycles"] if row else 0,
            "last_sent_at": row["last_sent_at"] if row else None,
            "db_size":      cnt[0] if cnt else 0,
        }
    finally:
        await db.close()


_DEFAULTS = {
    "chat_id": "", "active": 1, "max_price": 600,
    "min_rooms": 0, "area": "", "wbs_only": 0,
    "areas": "[]", "sources": "[]",
    "household_size": 1, "jobcenter_mode": 0, "wohngeld_mode": 0,
    "quiet_start": -1, "quiet_end": -1, "max_per_cycle": 10,
    "wbs_level_min": 0, "wbs_level_max": 999,
}


async def get_settings(chat_id: str) -> dict:
    db = await _conn()
    try:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM user_settings WHERE chat_id=?", (chat_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
    finally:
        await db.close()
    return {**_DEFAULTS, "chat_id": chat_id}


async def upsert_settings(chat_id: str, **kwargs) -> None:
    current = await get_settings(chat_id)
    current.update(kwargs)
    current["chat_id"]    = chat_id
    current["updated_at"] = datetime.utcnow().isoformat()
    for k, v in _DEFAULTS.items():
        current.setdefault(k, v)
    db = await _conn()
    try:
        await db.execute(
            """INSERT INTO user_settings
               (chat_id,active,max_price,min_rooms,area,wbs_only,areas,sources,
                household_size,jobcenter_mode,wohngeld_mode,quiet_start,quiet_end,max_per_cycle,wbs_level_min,wbs_level_max,updated_at)
               VALUES
               (:chat_id,:active,:max_price,:min_rooms,:area,:wbs_only,:areas,:sources,
                :household_size,:jobcenter_mode,:wohngeld_mode,:quiet_start,:quiet_end,:max_per_cycle,:wbs_level_min,:wbs_level_max,:updated_at)
               ON CONFLICT(chat_id) DO UPDATE SET
                 active=excluded.active, max_price=excluded.max_price,
                 min_rooms=excluded.min_rooms, area=excluded.area,
                 wbs_only=excluded.wbs_only, areas=excluded.areas,
                 sources=excluded.sources,
                 household_size=excluded.household_size,
                 jobcenter_mode=excluded.jobcenter_mode,
                 wohngeld_mode=excluded.wohngeld_mode,
                 quiet_start=excluded.quiet_start, quiet_end=excluded.quiet_end,
                 max_per_cycle=excluded.max_per_cycle,
                 wbs_level_min=excluded.wbs_level_min,
                 wbs_level_max=excluded.wbs_level_max,
                 updated_at=excluded.updated_at""",
            current,
        )
        await db.commit()
    finally:
        await db.close()
