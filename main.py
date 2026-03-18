"""
WBS Housing Bot — Main Entry Point
Starts the Telegram bot and background scraping scheduler together.
"""
import asyncio
import logging
import logging.handlers
import os
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.constants import ParseMode

from utils import setup_logging
from database import init_db, init_health_table
from bot import build_app, format_listing
from scheduler import run_once, set_notify_callback
from config.settings import CHAT_ID, BOT_TOKEN, SCRAPE_INTERVAL

setup_logging()
logger = logging.getLogger(__name__)


async def main() -> None:
    # Validate critical env vars
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN is not set. Exiting.")
        sys.exit(1)
    if not CHAT_ID:
        logger.critical("CHAT_ID is not set. Exiting.")
        sys.exit(1)

    # Init DB
    await init_db()
    await init_health_table()

    # Build Telegram app
    app = build_app()
    await app.initialize()
    await app.start()

    # Notification callback — sends message to owner
    async def notify(listing: dict) -> None:
        text = format_listing(listing)
        try:
            await app.bot.send_message(
                chat_id=CHAT_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=False,
            )
        except Exception as e:
            logger.error("Failed to send notification: %s", e)

    set_notify_callback(notify)

    # APScheduler — run scraper loop every SCRAPE_INTERVAL minutes
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_once,
        "interval",
        minutes=SCRAPE_INTERVAL,
        id="scrape_loop",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("✅ Scheduler started — scraping every %d minutes", SCRAPE_INTERVAL)

    # Run first scrape immediately on startup
    asyncio.create_task(run_once())

    # Start polling
    logger.info("🤖 Bot started — polling for commands…")
    await app.updater.start_polling(drop_pending_updates=True)

    # Graceful shutdown
    stop_event = asyncio.Event()

    def _shutdown(*_):
        logger.info("Shutdown signal received")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_event_loop().add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    await stop_event.wait()

    logger.info("Stopping…")
    scheduler.shutdown(wait=False)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    logger.info("👋 Bot stopped cleanly.")


if __name__ == "__main__":
    asyncio.run(main())
