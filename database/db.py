import aiosqlite
import logging
from datetime import datetime, timedelta
from config.settings import DB_PATH, LISTING_TTL_DAYS

logger = logging.getLogger(__name__)

CREATE_LISTINGS = """
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
    features        TEXT,
    score           INTEGER DEFAULT 0,
    source          TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_USER_SETTINGS = """
CREATE TABLE IF NOT EXISTS user_settings (
    chat_id         TEXT PRIMARY KEY,
    active          INTEGER DEFAULT 1,
    max_price       REAL DEFAULT 600,
    min_rooms       REAL DEFAULT 0,
    area            TEXT DEFAULT '',
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_STATS = """
CREATE TABLE IF NOT EXISTS bot_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    total_sent      INTEGER DEFAULT 0,
    last_sent_at    DATETIME,
    total_cycles    INTEGER DEFAULT 0,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_LISTINGS)
        await db.execute(CREATE_USER_SETTINGS)
        await db.execute(CREATE_STATS)
        # Migrate: add new columns to existing DB if upgrading
        for col, coltype in [
            ("size_m2", "REAL"),
            ("floor", "TEXT"),
            ("available_from", "TEXT"),
            ("features", "TEXT"),
            ("score", "INTEGER DEFAULT 0"),
        ]:
            try:
                await db.execute(f"ALTER TABLE listings ADD COLUMN {col} {coltype}")
            except Exception:
                pass  # Column already exists
        await db.commit()
    logger.info("Database ready at %s", DB_PATH)


async def is_known(listing_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM listings WHERE id = ?", (listing_id,)
        ) as cur:
            return await cur.fetchone() is not None


async def save_listing(listing: dict) -> None:
    import json
    features_json = json.dumps(listing.get("features") or [], ensure_ascii=False)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO listings
              (id, url, title, price, location, rooms, size_m2, floor,
               available_from, features, score, source)
            VALUES
              (:id, :url, :title, :price, :location, :rooms, :size_m2, :floor,
               :available_from, :features_json, :score, :source)
            """,
            {**listing, "features_json": features_json},
        )
        await db.commit()


async def purge_old_listings() -> int:
    cutoff = datetime.utcnow() - timedelta(days=LISTING_TTL_DAYS)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM listings WHERE created_at < ?", (cutoff.isoformat(),)
        )
        await db.commit()
    if cur.rowcount:
        logger.info("Purged %d old listings", cur.rowcount)
    return cur.rowcount


async def increment_stats(sent: int = 0, cycle: int = 0) -> None:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        row = await (await db.execute("SELECT id, total_sent, total_cycles FROM bot_stats LIMIT 1")).fetchone()
        if row:
            await db.execute(
                "UPDATE bot_stats SET total_sent=?, total_cycles=?, last_sent_at=?, updated_at=? WHERE id=?",
                (row[1] + sent, row[2] + cycle, now if sent else None, now, row[0])
            )
        else:
            await db.execute(
                "INSERT INTO bot_stats (total_sent, total_cycles, last_sent_at, updated_at) VALUES (?,?,?,?)",
                (sent, cycle, now if sent else None, now)
            )
        await db.commit()


async def get_stats() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = await (await db.execute("SELECT * FROM bot_stats LIMIT 1")).fetchone()
        total_listings = await (await db.execute("SELECT COUNT(*) FROM listings")).fetchone()
        return {
            "total_sent":   row["total_sent"]   if row else 0,
            "total_cycles": row["total_cycles"] if row else 0,
            "last_sent_at": row["last_sent_at"] if row else None,
            "db_size":      total_listings[0]   if total_listings else 0,
        }


# ── User Settings ─────────────────────────────────────────────────────────────

async def get_settings(chat_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_settings WHERE chat_id = ?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
    return {"chat_id": chat_id, "active": 1, "max_price": 600, "min_rooms": 0, "area": ""}


async def upsert_settings(chat_id: str, **kwargs) -> None:
    current = await get_settings(chat_id)
    current.update(kwargs)
    current["chat_id"] = chat_id
    current["updated_at"] = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO user_settings (chat_id, active, max_price, min_rooms, area, updated_at)
            VALUES (:chat_id, :active, :max_price, :min_rooms, :area, :updated_at)
            ON CONFLICT(chat_id) DO UPDATE SET
                active=excluded.active, max_price=excluded.max_price,
                min_rooms=excluded.min_rooms, area=excluded.area,
                updated_at=excluded.updated_at
            """,
            current,
        )
        await db.commit()
