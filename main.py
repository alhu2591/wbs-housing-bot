"""
WBS Housing Bot — Main Entry Point
Works locally (python run_local.py) and on any server.
"""
import asyncio
import logging
import logging.handlers
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from telegram.constants import ParseMode
from telegram.error import TelegramError, RetryAfter, NetworkError, TimedOut

from utils import setup_logging, start_health_server, set_stats_fn
from database import init_db, init_health_table, get_stats
from bot import build_app, format_listing
from bot.handlers import BOT_COMMANDS
from scheduler import run_once, set_notify_callback
from config.settings import CHAT_ID, BOT_TOKEN, SCRAPE_INTERVAL

setup_logging()
logger = logging.getLogger(__name__)


async def _send_startup_message(app) -> None:
    try:
        stats = await get_stats()
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=(
                "🟢 *البوت بدأ العمل*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔄 كل {SCRAPE_INTERVAL} دقيقة\n"
                f"🗃 محفوظ: {stats.get('db_size', 0)}\n"
                f"📨 مُرسل: {stats.get('total_sent', 0)}\n\n"
                "استخدم /status · /help"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError as e:
        logger.warning("Startup message failed: %s", e)


async def _heartbeat() -> None:
    try:
        stats = await get_stats()
        logger.info(
            "💓 Heartbeat — cycles: %d | sent: %d | db: %d",
            stats.get("total_cycles", 0),
            stats.get("total_sent", 0),
            stats.get("db_size", 0),
        )
    except Exception as e:
        logger.error("Heartbeat error: %s", e)


async def _error_handler(update, context) -> None:
    logger.error("PTB error: %s", context.error, exc_info=context.error)


async def main() -> None:
    # ── Validate ──────────────────────────────────────────────────────────────
    if not BOT_TOKEN:
        logger.critical("Required env var BOT_TOKEN is missing. Exiting.")
        sys.exit(1)
    if not CHAT_ID:
        logger.critical("Required env var CHAT_ID is missing. Exiting.")
        sys.exit(1)

    # ── DB ────────────────────────────────────────────────────────────────────
    await init_db()
    await init_health_table()

    # ── Telegram app ──────────────────────────────────────────────────────────
    app = build_app()
    app.add_error_handler(_error_handler)
    await app.initialize()
    await app.start()

    try:
        await app.bot.set_my_commands(BOT_COMMANDS)
    except TelegramError as e:
        logger.warning("set_my_commands failed: %s", e)

    # ── Notify callback with retry ────────────────────────────────────────────
    async def notify(listing: dict) -> None:
        text, keyboard = format_listing(listing)
        image_url = listing.get("image_url")

        for attempt in range(3):
            try:
                if image_url:
                    try:
                        await app.bot.send_photo(
                            chat_id=CHAT_ID,
                            photo=image_url,
                            caption=text,
                            parse_mode=ParseMode.MARKDOWN,
                            reply_markup=keyboard,
                        )
                        return
                    except TelegramError:
                        image_url = None

                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard,
                    disable_web_page_preview=False,
                )
                return

            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except (NetworkError, TimedOut) as e:
                if attempt < 2:
                    await asyncio.sleep(5 * (attempt + 1))
                else:
                    logger.error("notify failed after 3 attempts: %s", e)
                    return
            except TelegramError as e:
                logger.error("notify: %s", e)
                return

    set_notify_callback(notify)

    # ── Health server (for Railway/server deployments) ────────────────────────
    set_stats_fn(get_stats)
    asyncio.create_task(start_health_server(port=8080))

    # ── Scheduler ─────────────────────────────────────────────────────────────
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")

    def _job_error(event):
        logger.error("Scheduler job '%s' error: %s", event.job_id, event.exception)

    def _job_missed(event):
        logger.warning("Scheduler job '%s' missed", event.job_id)

    scheduler.add_listener(_job_error,  EVENT_JOB_ERROR)
    scheduler.add_listener(_job_missed, EVENT_JOB_MISSED)

    scheduler.add_job(
        run_once, "interval",
        minutes=SCRAPE_INTERVAL,
        id="scrape",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(_heartbeat, "interval", hours=1, id="heartbeat",
                      misfire_grace_time=300)
    scheduler.start()
    logger.info("✅ Scheduler every %d min", SCRAPE_INTERVAL)

    # ── First scrape + startup message ────────────────────────────────────────
    await _send_startup_message(app)
    try:
        await run_once()
    except Exception as e:
        logger.error("First scrape failed: %s", e)

    # ── Polling ───────────────────────────────────────────────────────────────
    logger.info("🤖 Bot polling…")
    await app.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
        read_timeout=30,
        write_timeout=30,
        connect_timeout=15,
        pool_timeout=15,
    )

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    stop_event = asyncio.Event()

    def _handle_signal(*_):
        logger.info("🛑 Shutdown signal")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except (NotImplementedError, RuntimeError):
            # Windows doesn't support add_signal_handler
            pass

    await stop_event.wait()

    logger.info("Stopping…")
    scheduler.shutdown(wait=False)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    logger.info("👋 Stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
