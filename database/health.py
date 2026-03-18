"""
Scraper health tracking — last run, listing count, errors per source.
"""
import aiosqlite
import logging
from datetime import datetime
from config.settings import DB_PATH

logger = logging.getLogger(__name__)

CREATE_HEALTH = """
CREATE TABLE IF NOT EXISTS scraper_health (
    source          TEXT PRIMARY KEY,
    last_run        DATETIME,
    last_success    DATETIME,
    listings_found  INTEGER DEFAULT 0,
    total_runs      INTEGER DEFAULT 0,
    total_errors    INTEGER DEFAULT 0,
    last_error      TEXT    DEFAULT '',
    status          TEXT    DEFAULT 'unknown'
);
"""


async def init_health_table() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_HEALTH)
        await db.commit()


async def record_success(source: str, count: int) -> None:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO scraper_health
              (source, last_run, last_success, listings_found, total_runs, status)
            VALUES (?,?,?,?,1,'ok')
            ON CONFLICT(source) DO UPDATE SET
              last_run      = excluded.last_run,
              last_success  = excluded.last_success,
              listings_found= excluded.listings_found,
              total_runs    = total_runs + 1,
              status        = 'ok'
            """,
            (source, now, now, count),
        )
        await db.commit()


async def record_error(source: str, error: str) -> None:
    now = datetime.utcnow().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO scraper_health
              (source, last_run, total_runs, total_errors, last_error, status)
            VALUES (?,?,1,1,?,'error')
            ON CONFLICT(source) DO UPDATE SET
              last_run     = excluded.last_run,
              total_runs   = total_runs + 1,
              total_errors = total_errors + 1,
              last_error   = excluded.last_error,
              status       = 'error'
            """,
            (source, now, str(error)[:300]),
        )
        await db.commit()


async def get_all_health() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM scraper_health ORDER BY source"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
