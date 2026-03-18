"""
WBS Housing Bot — Main Entry Point
Hardened for 24/7 stability on Railway/Render.
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


async def _send_startup_message(app, stats: dict) -> None:
    try:
        import os
        ai    = "✅" if os.getenv("ANTHROPIC_API_KEY") else "⚠️ غير مفعّل"
        proxy = "✅" if os.getenv("SCRAPER_API_KEY")   else "⚠️ غير مفعّل"
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=(
                "🟢 *البوت بدأ العمل*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔄 كل {SCRAPE_INTERVAL} دقيقة\n"
                f"🤖 الذكاء: {ai}\n"
                f"🌐 ScraperAPI: {proxy}\n"
                f"🗃 محفوظ: {stats.get('db_size', 0)}\n"
                f"📨 مُرسل: {stats.get('total_sent', 0)}\n\n"
                "استخدم /status · /help"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError as e:
        logger.warning("Startup message failed: %s", e)


async def _heartbeat() -> None:
    """Hourly liveness log — wrapped so DB errors never kill the job."""
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
    """Global Telegram error handler — logs all unhandled PTB exceptions."""
    logger.error("Telegram handler error: %s", context.error, exc_info=context.error)


async def main() -> None:
    # ── Validate env ──────────────────────────────────────────────────────────
    if not BOT_TOKEN:
        logger.critical("Required env var BOT_TOKEN is missing. Exiting.")
        sys.exit(1)
    if not CHAT_ID:
        logger.critical("CHAT_ID not set. Exiting.")
        sys.exit(1)

    # ── Init DB ───────────────────────────────────────────────────────────────
    await init_db()
    await init_health_table()
    stats = await get_stats()

    # ── Build Telegram app ────────────────────────────────────────────────────
    app = build_app()
    app.add_error_handler(_error_handler)   # catch all unhandled PTB errors
    await app.initialize()
    await app.start()

    # Register slash-command menu
    try:
        await app.bot.set_my_commands(BOT_COMMANDS)
        logger.info("✅ Bot commands registered")
    except TelegramError as e:
        logger.warning("set_my_commands failed: %s", e)

    # ── Notification callback with flood/retry handling ───────────────────────
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
                        image_url = None  # fall through to text

                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=keyboard,
                    disable_web_page_preview=False,
                )
                return

            except RetryAfter as e:
                wait = e.retry_after + 1
                logger.warning("Telegram flood: waiting %ds (attempt %d)", wait, attempt+1)
                await asyncio.sleep(wait)

            except (NetworkError, TimedOut) as e:
                wait = 5 * (attempt + 1)
                logger.warning("Telegram network error: %s — retry in %ds", e, wait)
                await asyncio.sleep(wait)

            except TelegramError as e:
                logger.error("Telegram send failed (no retry): %s", e)
                return

        logger.error("notify: gave up after 3 attempts for %s", listing.get("url","")[:60])

    set_notify_callback(notify)

    # ── Health server (Railway healthcheck + /metrics) ────────────────────────
    set_stats_fn(get_stats)
    asyncio.create_task(start_health_server(port=8080))
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")

    def _job_error_listener(event):
        logger.error(
            "⚠️ Scheduler job '%s' raised: %s",
            event.job_id,
            event.exception,
            exc_info=event.traceback,
        )

    def _job_missed_listener(event):
        logger.warning("⏰ Scheduler job '%s' missed at %s", event.job_id, event.scheduled_run_time)

    scheduler.add_listener(_job_error_listener, EVENT_JOB_ERROR)
    scheduler.add_listener(_job_missed_listener, EVENT_JOB_MISSED)

    scheduler.add_job(
        run_once,
        "interval",
        minutes=SCRAPE_INTERVAL,
        id="scrape_loop",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )
    scheduler.add_job(
        _heartbeat,
        "interval",
        hours=1,
        id="heartbeat",
        misfire_grace_time=300,
    )
    scheduler.start()
    logger.info("✅ Scheduler started — every %d min", SCRAPE_INTERVAL)

    # ── Startup notification + first scrape (observed) ────────────────────────
    await _send_startup_message(app, stats)
    try:
        await run_once()    # run directly, not as task — errors are logged
    except Exception as e:
        logger.error("First scrape failed: %s", e)

    # ── Start polling with network timeouts ───────────────────────────────────
    logger.info("🤖 Polling started")
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
            pass

    await stop_event.wait()

    logger.info("Stopping…")
    scheduler.shutdown(wait=False)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    logger.info("👋 Stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
