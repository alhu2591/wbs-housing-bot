"""
WBS Housing Bot — Main Entry Point
"""
import asyncio
import logging
import logging.handlers
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.constants import ParseMode
from telegram.error import TelegramError

from utils import setup_logging
from database import init_db, init_health_table, get_stats
from bot import build_app, format_listing
from bot.handlers import BOT_COMMANDS
from scheduler import run_once, set_notify_callback
from config.settings import CHAT_ID, BOT_TOKEN, SCRAPE_INTERVAL

setup_logging()
logger = logging.getLogger(__name__)


async def _send_startup_message(app, stats: dict) -> None:
    """Send a startup notification so you know the bot restarted."""
    try:
        import os
        ai     = "✅" if os.getenv("ANTHROPIC_API_KEY") else "⚠️ غير مفعّل"
        proxy  = "✅" if os.getenv("SCRAPER_API_KEY") else "⚠️ غير مفعّل"
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=(
                "🟢 *البوت بدأ العمل*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔄 كل {SCRAPE_INTERVAL} دقيقة\n"
                f"🤖 الذكاء الاصطناعي: {ai}\n"
                f"🌐 ScraperAPI: {proxy}\n"
                f"🗃 إعلانات محفوظة: {stats.get('db_size', 0)}\n"
                f"📨 إجمالي مُرسل: {stats.get('total_sent', 0)}\n\n"
                "استخدم /status للإعدادات · /help للمساعدة"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except TelegramError as e:
        logger.warning("Could not send startup message: %s", e)


async def _heartbeat() -> None:
    """Log a heartbeat every hour so you can confirm the bot is alive."""
    stats = await get_stats()
    logger.info(
        "💓 Heartbeat — cycles: %d | sent: %d | db: %d",
        stats.get("total_cycles", 0),
        stats.get("total_sent", 0),
        stats.get("db_size", 0),
    )


async def main() -> None:
    # ── Validate env ──────────────────────────────────────────────────────────
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN is not set. Exiting.")
        sys.exit(1)
    if not CHAT_ID:
        logger.critical("CHAT_ID is not set. Exiting.")
        sys.exit(1)

    # ── Init DB ───────────────────────────────────────────────────────────────
    await init_db()
    await init_health_table()
    stats = await get_stats()

    # ── Build Telegram app ────────────────────────────────────────────────────
    app = build_app()
    await app.initialize()
    await app.start()

    # Register commands in Telegram menu (shows slash-command list to user)
    try:
        await app.bot.set_my_commands(BOT_COMMANDS)
        logger.info("✅ Bot commands menu registered")
    except TelegramError as e:
        logger.warning("Could not register commands: %s", e)

    # ── Notification callback ─────────────────────────────────────────────────
    async def notify(listing: dict) -> None:
        text, keyboard = format_listing(listing)
        try:
            await app.bot.send_message(
                chat_id=CHAT_ID,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
                disable_web_page_preview=False,
            )
        except TelegramError as e:
            logger.error("Telegram send failed: %s", e)

    set_notify_callback(notify)

    # ── Scheduler ─────────────────────────────────────────────────────────────
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")
    scheduler.add_job(
        run_once,
        "interval",
        minutes=SCRAPE_INTERVAL,
        id="scrape_loop",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        _heartbeat,
        "interval",
        hours=1,
        id="heartbeat",
    )
    scheduler.start()
    logger.info("✅ Scheduler started — every %d min", SCRAPE_INTERVAL)

    # ── Startup notification + first scrape ───────────────────────────────────
    await _send_startup_message(app, stats)
    asyncio.create_task(run_once())

    # ── Start polling ─────────────────────────────────────────────────────────
    logger.info("🤖 Bot polling started")
    await app.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )

    # ── Graceful shutdown ─────────────────────────────────────────────────────
    stop_event = asyncio.Event()

    def _handle_signal(*_):
        logger.info("🛑 Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except (NotImplementedError, RuntimeError):
            pass

    await stop_event.wait()

    logger.info("Stopping bot…")
    scheduler.shutdown(wait=False)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()
    logger.info("👋 Bot stopped cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
