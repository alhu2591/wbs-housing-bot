"""
main.py — WBS Housing Bot v2.0 — Real-Time AI Intelligence Platform.

Run:
  export BOT_TOKEN=... CHAT_ID=...
  python main.py

Options:
  --test-scrape     One-off scrape, no Telegram
  --no-dashboard    Disable web dashboard
  --port PORT       Dashboard port (default: 8080)
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import time
from typing import Any

# ── Bootstrap ──────────────────────────────────────────────────────────────
from utils.logger import setup_logging
setup_logging()
logger = logging.getLogger(__name__)

from utils.config_loader import load_config
from utils.config_store import load_runtime_config, save_runtime_config
from utils.fetch_runtime import set_fetch_runtime
from database.db import init_db, log_event

# ── Core components ────────────────────────────────────────────────────────
from scraper.pipeline import scrape_new_listings
from scraper.realtime_engine import run_realtime_loop
from scraper.registry import get_all_scrapers
from ai.scorer import enrich_listing
from bot.arabic_ui import (
    send_listing_arabic, send_admin_alert, send_daily_summary,
    build_main_menu,
)
from bot.callback_handler import (
    set_callbacks, get_handlers, AWAITING_INPUT,
)
from utils.watchdog import Watchdog, DailySummaryScheduler
from dashboard.app import start_dashboard

# PTB
from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import RetryAfter, NetworkError, TimedOut, TelegramError


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


# ── Config state ───────────────────────────────────────────────────────────
_cfg: dict[str, Any] = {}


def get_cfg() -> dict[str, Any]:
    return _cfg


def set_cfg(new_cfg: dict[str, Any]) -> None:
    global _cfg
    _cfg = new_cfg
    save_runtime_config(new_cfg)


# ── Telegram send helper ───────────────────────────────────────────────────

async def _send_one(bot, chat_id: str, listing: dict[str, Any]) -> bool:
    cfg = get_cfg()
    send_imgs = bool(cfg.get("send_images", True))
    max_photos = int(cfg.get("max_images") or 5)

    for attempt in range(3):
        try:
            return await send_listing_arabic(
                bot, chat_id, listing,
                send_images=send_imgs,
                max_photos=max_photos,
            )
        except RetryAfter as e:
            await asyncio.sleep((getattr(e, "retry_after", 0) or 0) + 1)
        except (NetworkError, TimedOut) as e:
            if attempt < 2:
                await asyncio.sleep(2 * (attempt + 1))
            else:
                logger.error("Telegram network error (final): %s", e)
        except TelegramError as e:
            logger.error("Telegram error: %s", e)
            return False
        except Exception as e:
            logger.error("Send failed: %s", e, exc_info=True)
            return False
    return False


# ── Notification callback for real-time engine ────────────────────────────

def make_notify_callback(bot, chat_id: str):
    async def on_new_listings(listings: list[dict[str, Any]]) -> None:
        cfg = get_cfg()
        if not cfg.get("notify_enabled", True):
            logger.info("Notify disabled — %d listings skipped.", len(listings))
            return

        max_per = int(cfg.get("max_per_cycle") or 10)
        to_send = listings[:max_per]
        logger.info("Notifying %d new listings…", len(to_send))

        for listing in to_send:
            try:
                ok = await _send_one(bot, chat_id, listing)
                if ok:
                    log_event("INFO", f"Sent listing: {listing.get('title', '')[:60]}")
                await asyncio.sleep(0.4)  # Telegram rate limit buffer
            except Exception as e:
                logger.error("notify callback: %s", e, exc_info=True)

    return on_new_listings


# ── Telegram command handlers ─────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_cfg()
    await update.message.reply_text(
        "🏠 *أهلاً بك في بوت السكن الذكي!*\n\n"
        "استخدم /settings لفتح لوحة التحكم\n"
        "استخدم /status لعرض حالة النظام\n"
        "استخدم /scan لبدء فحص فوري",
        parse_mode="Markdown",
        reply_markup=build_main_menu(cfg),
    )


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_cfg()
    await update.message.reply_text(
        "⚙️ *لوحة التحكم — بوت السكن*",
        parse_mode="Markdown",
        reply_markup=build_main_menu(cfg),
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from database.db import get_daily_summary, get_source_stats
    summary = get_daily_summary()
    sources = get_source_stats()
    active_sources = sum(1 for s in sources if not s.get("disabled"))
    cfg = get_cfg()

    status_text = (
        "📊 *حالة النظام*\n\n"
        f"🟢 البوت: يعمل\n"
        f"🏠 إعلانات اليوم: *{summary['listings_found_24h']}*\n"
        f"💾 إجمالي: *{summary['total_listings']}* إعلان\n"
        f"🌐 مصادر نشطة: *{active_sources}/{len(sources)}*\n"
        f"⏱ التحديث كل: *{cfg.get('interval_seconds', 60)} ث*\n"
        f"📋 WBS مطلوب: {'نعم' if cfg.get('wbs_required') else 'لا'}\n"
        f"💰 الحد الأقصى للسعر: *{cfg.get('max_price', '—')} €*\n"
    )
    await update.message.reply_text(status_text, parse_mode="Markdown")


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("🔍 *جاري الفحص الفوري...*", parse_mode="Markdown")
    # Trigger is set after main() creates the engine
    if _scan_trigger:
        asyncio.create_task(_scan_trigger())


_scan_trigger = None


# ── Test scrape mode ──────────────────────────────────────────────────────

async def _test_scrape(cfg: dict[str, Any]) -> None:
    from utils.storage import default_seen_path
    seen_path = default_seen_path()
    listings = await scrape_new_listings(cfg, seen_path)
    if not listings:
        logger.info("No listings found.")
        return
    for l in listings[:15]:
        enrich_listing(l, cfg)
        logger.info(
            "[%d/100] %s | %s€ | %sm² | %sr | JC:%s | %s",
            l.get("score", 0),
            l.get("title", "")[:40],
            l.get("price", "—"),
            l.get("size_m2", "—"),
            l.get("rooms", "—"),
            "✅" if l.get("jobcenter_ok") else "❌",
            l.get("url", ""),
        )


# ── Main ───────────────────────────────────────────────────────────────────

async def main() -> None:
    global _scan_trigger

    parser = argparse.ArgumentParser(description="WBS Housing Bot v2.0")
    parser.add_argument("--test-scrape", action="store_true")
    parser.add_argument("--no-dashboard", action="store_true")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    # Init DB
    init_db()

    # Load config
    base_cfg = load_config()
    cfg = load_runtime_config(base_cfg)
    set_cfg(cfg)
    set_fetch_runtime(cfg)

    if args.test_scrape:
        await _test_scrape(get_cfg())
        return

    bot_token = _env("BOT_TOKEN")
    chat_id = _env("CHAT_ID")
    admin_chat_id = _env("ADMIN_CHAT_ID") or chat_id

    # ── Build Telegram app ─────────────────────────────────────────────────
    app = None
    if bot_token and chat_id:
        try:
            app = Application.builder().token(bot_token).build()
            # Commands
            app.add_handler(CommandHandler("start", cmd_start))
            app.add_handler(CommandHandler("settings", cmd_settings))
            app.add_handler(CommandHandler("status", cmd_status))
            app.add_handler(CommandHandler("scan", cmd_scan))
            # Inline + text handlers
            for h in get_handlers():
                app.add_handler(h)
            app.add_error_handler(
                lambda u, c: logger.error("PTB: %s", c.error, exc_info=True)
            )
            await app.initialize()
            await app.start()
            try:
                await app.bot.set_my_commands([
                    BotCommand("start", "ابدأ البوت"),
                    BotCommand("settings", "الإعدادات"),
                    BotCommand("status", "حالة النظام"),
                    BotCommand("scan", "فحص فوري"),
                ])
            except Exception as e:
                logger.warning("set_my_commands: %s", e)
            logger.info("Telegram bot ready.")
        except Exception as e:
            logger.error("Telegram init failed: %s", e, exc_info=True)
            app = None
    else:
        logger.warning("BOT_TOKEN/CHAT_ID missing — scrape-only mode.")

    # ── Real-time scan trigger ─────────────────────────────────────────────
    stop_event = asyncio.Event()
    scan_event = asyncio.Event()  # Signals immediate scan

    async def trigger_scan() -> None:
        scan_event.set()

    _scan_trigger = trigger_scan

    # ── Config callbacks for Telegram UI ──────────────────────────────────
    interval_change_flag = {"value": None}

    def on_interval_change(secs: int) -> None:
        cfg = get_cfg()
        cfg["interval_seconds"] = secs
        set_cfg(cfg)
        interval_change_flag["value"] = secs

    set_callbacks(
        cfg_getter=get_cfg,
        cfg_setter=set_cfg,
        trigger_scan=trigger_scan,
        set_interval_fn=on_interval_change,
    )

    # ── Notification callback ──────────────────────────────────────────────
    if app and chat_id:
        notify_cb = make_notify_callback(app.bot, chat_id)
    else:
        async def notify_cb(listings):
            for l in listings:
                logger.info("MATCH [%d]: %s | %s€", l.get("score", 0), l.get("title", ""), l.get("price", ""))

    # ── Watchdog ───────────────────────────────────────────────────────────
    async def on_freeze():
        logger.error("Watchdog triggered — restarting scan loop!")
        log_event("ERROR", "Watchdog: loop freeze detected, recovery triggered")
        if app and admin_chat_id:
            await send_admin_alert(app.bot, admin_chat_id, "⚠️ النظام توقف — تم إعادة التشغيل التلقائي")
        # Signal a new scan cycle
        scan_event.set()

    watchdog = Watchdog(on_freeze, timeout=300)
    watchdog.start()

    # ── Daily summary ──────────────────────────────────────────────────────
    if app and admin_chat_id:
        async def _send_summary(s):
            await send_daily_summary(app.bot, admin_chat_id, s)
        daily = DailySummaryScheduler(_send_summary, hour=8)
        daily.start()
    else:
        daily = None

    # ── Dashboard ──────────────────────────────────────────────────────────
    if not args.no_dashboard:
        await start_dashboard(port=args.port)

    # ── Real-time engine ───────────────────────────────────────────────────
    def get_scrapers():
        return get_all_scrapers(get_cfg())

    engine_task = asyncio.create_task(
        run_realtime_loop(
            get_scrapers=get_scrapers,
            get_cfg=get_cfg,
            on_new_listings=notify_cb,
            stop_event=stop_event,
        )
    )
    logger.info("Real-time engine task started.")
    log_event("INFO", "System started — real-time mode")

    # ── Polling ────────────────────────────────────────────────────────────
    poll_task = None
    if app and chat_id:
        async def _poll():
            try:
                await app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=["message", "callback_query"],
                    read_timeout=30,
                    write_timeout=30,
                    connect_timeout=15,
                    pool_timeout=15,
                )
            except Exception as e:
                logger.error("Polling: %s", e, exc_info=True)

        poll_task = asyncio.create_task(_poll())

    # ── Signal handling ────────────────────────────────────────────────────
    def _sig(*_):
        logger.info("Shutdown signal received.")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig)
        except Exception:
            pass

    logger.info("Bot running. Press Ctrl+C to stop.")

    # ── Main wait loop ────────────────────────────────────────────────────
    await stop_event.wait()

    # ── Graceful shutdown ─────────────────────────────────────────────────
    logger.info("Shutting down…")
    log_event("INFO", "System shutdown initiated")

    await watchdog.stop()
    if daily:
        await daily.stop()

    engine_task.cancel()
    try:
        await engine_task
    except asyncio.CancelledError:
        pass

    if app:
        try:
            if app.updater.running:
                await app.updater.stop()
        except Exception:
            pass
        try:
            await app.stop()
            await app.shutdown()
        except Exception:
            pass

    if poll_task:
        poll_task.cancel()
        try:
            await poll_task
        except (asyncio.CancelledError, Exception):
            pass

    logger.info("Shutdown complete.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
