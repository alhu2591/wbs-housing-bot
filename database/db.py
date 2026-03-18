import aiosqlite
import logging
from datetime import datetime, timedelta
from config.settings import DB_PATH, LISTING_TTL_DAYS

logger = logging.getLogger(__name__)

CREATE_LISTINGS = """
CREATE TABLE IF NOT EXISTS listings (
    id          TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    title       TEXT,
    price       REAL,
    location    TEXT,
    rooms       REAL,
    source      TEXT,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_USER_SETTINGS = """
CREATE TABLE IF NOT EXISTS user_settings (
    chat_id     TEXT PRIMARY KEY,
    active      INTEGER DEFAULT 1,
    max_price   REAL DEFAULT 600,
    min_rooms   REAL DEFAULT 0,
    area        TEXT DEFAULT '',
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);
"""


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_LISTINGS)
        await db.execute(CREATE_USER_SETTINGS)
        await db.commit()
    logger.info("Database initialised at %s", DB_PATH)


async def is_known(listing_id: str) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM listings WHERE id = ?", (listing_id,)
        ) as cur:
            return await cur.fetchone() is not None


async def save_listing(listing: dict) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO listings (id, url, title, price, location, rooms, source)
            VALUES (:id, :url, :title, :price, :location, :rooms, :source)
            """,
            listing,
        )
        await db.commit()


async def purge_old_listings() -> int:
    cutoff = datetime.utcnow() - timedelta(days=LISTING_TTL_DAYS)
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "DELETE FROM listings WHERE created_at < ?", (cutoff.isoformat(),)
        )
        await db.commit()
        deleted = cur.rowcount
    if deleted:
        logger.info("Purged %d old listings", deleted)
    return deleted


# ── User Settings ────────────────────────────────────────────────────────────

async def get_settings(chat_id: str) -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM user_settings WHERE chat_id = ?", (chat_id,)
        ) as cur:
            row = await cur.fetchone()
            if row:
                return dict(row)
    return {
        "chat_id": chat_id,
        "active": 1,
        "max_price": 600,
        "min_rooms": 0,
        "area": "",
    }


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
                active=excluded.active,
                max_price=excluded.max_price,
                min_rooms=excluded.min_rooms,
                area=excluded.area,
                updated_at=excluded.updated_at
            """,
            current,
        )
        await db.commit()
