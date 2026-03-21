"""
WBS Housing Bot — professional Telegram + scraper (Termux-ready).

Run:
  export BOT_TOKEN=... CHAT_ID=...
  python main.py

Optional:
  python main.py --test-scrape
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import time
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram.error import NetworkError, RetryAfter, TimedOut, TelegramError

from bot.telegram_bot import (
    BOT_COMMANDS,
    build_app,
    get_config,
    send_listing,
    set_config as set_bot_config,
    set_runtime_callbacks,
)
from scraper.pipeline import scrape_new_listings
from utils.config_loader import load_config
from utils.logger import setup_logging
from utils.config_store import load_runtime_config
from utils.storage import default_seen_path, make_seen_entry, persist_seen


setup_logging()
logger = logging.getLogger(__name__)


def _get_env(name: str) -> str:
    return os.getenv(name, "").strip()


async def _send_one(app, chat_id: str, listing: dict[str, Any], cfg: dict[str, Any]) -> bool:
    send_imgs = bool(cfg.get("send_images", False))
    for attempt in range(3):
        try:
            return await send_listing(
                app.bot,
                chat_id,
                listing,
                send_images=send_imgs,
                max_photos=int(cfg.get("max_images") or 5),
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
            logger.error("Telegram send failed: %s", e, exc_info=True)
    return False


async def _job_cycle(
    app,
    chat_id: str | None,
    seen_path: str,
    cfg_get,
) -> None:
    started = time.monotonic()
    cfg = cfg_get()
    try:
        listings = await scrape_new_listings(cfg, seen_path)
    except Exception as e:
        logger.error("scrape_new_listings crashed: %s", e, exc_info=True)
        return

    if not listings:
        logger.info("Cycle done: no new matches (%.1fs).", time.monotonic() - started)
        return

    max_per = int(cfg.get("max_per_cycle") or 5)
    to_send = listings[:max_per]

    if not app or not chat_id:
        logger.info("Cycle: %d listings (no Telegram).", len(to_send))
        for l in to_send:
            logger.info(
                "MATCH: %s | %s € | %s | %s img",
                l.get("title"),
                l.get("price"),
                l.get("location"),
                len(l.get("images") or []),
            )
        return

    notify_enabled = bool(cfg.get("notify_enabled", True))
    if not notify_enabled:
        logger.info("Notify disabled: marking %d listings as seen.", len(to_send))
        try:
            batch = {}
            for l in to_send:
                batch.update(make_seen_entry(l))
            persist_seen(seen_path, batch)
        except Exception as e:
            logger.error("persist seen (notify disabled): %s", e, exc_info=True)
        return

    logger.info("Sending %d listings…", len(to_send))
    sent: list[dict[str, Any]] = []
    for listing in to_send:
        try:
            ok = await _send_one(app, chat_id, listing, cfg)
            if ok:
                sent.append(listing)
            await asyncio.sleep(0.35)
        except Exception as e:
            logger.error("send loop: %s", e, exc_info=True)

    if sent:
        try:
            batch = {}
            for l in sent:
                batch.update(make_seen_entry(l))
            persist_seen(seen_path, batch)
        except Exception as e:
            logger.error("persist seen: %s", e, exc_info=True)

    logger.info(
        "Cycle done: sent=%d/%d (%.1fs).",
        len(sent),
        len(to_send),
        time.monotonic() - started,
    )


async def _test_scrape(cfg: dict[str, Any], seen_path: str) -> None:
    listings = await scrape_new_listings(cfg, seen_path)
    if not listings:
        logger.info("No listings after filters.")
        return
    for l in listings[:15]:
        logger.info(
            "%s | %s € | %s m² | rooms=%s | wbs=%s | imgs=%d | %s",
            l.get("title"),
            l.get("price"),
            l.get("size_m2"),
            l.get("rooms"),
            l.get("wbs_label"),
            len(l.get("images") or []),
            l.get("url"),
        )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-scrape", action="store_true")
    args = parser.parse_args()

    base_cfg = load_config()
    cfg = load_runtime_config(base_cfg)
    set_bot_config(cfg)

    bot_token = _get_env("BOT_TOKEN")
    chat_id = _get_env("CHAT_ID")
    seen_path = default_seen_path()

    root_seen = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json")
    if os.path.exists(root_seen) and os.path.getsize(root_seen) > 5:
        try:
            import shutil
            if not os.path.exists(seen_path) or os.path.getsize(seen_path) < 5:
                shutil.copy2(root_seen, seen_path)
                logger.info("Migrated seen.json → data/seen.json")
        except Exception as e:
            logger.warning("seen migration: %s", e)

    if args.test_scrape:
        await _test_scrape(cfg, seen_path)
        return

    app = None
    if bot_token and chat_id:
        try:
            app = build_app(bot_token)
            app.add_error_handler(
                lambda u, c: logger.error("PTB error: %s", c.error, exc_info=True)
            )
            await app.initialize()
            await app.start()
            try:
                await app.bot.set_my_commands(BOT_COMMANDS)
            except Exception as e:
                logger.warning("set_my_commands: %s", e)
        except Exception as e:
            logger.error("Telegram start failed: %s", e, exc_info=True)
            app = None
    else:
        logger.warning("BOT_TOKEN/CHAT_ID missing — scrape-only mode.")

    cfg_get = get_config
    cycle_lock = asyncio.Lock()

    async def _run_cycle() -> None:
        async with cycle_lock:
            await _job_cycle(
                app,
                chat_id if (bot_token and chat_id) else None,
                seen_path,
                cfg_get,
            )

    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(
        _run_cycle,
        "interval",
        minutes=int(cfg_get().get("interval_minutes") or 10),
        id="cycle",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120,
    )

    def _set_interval_minutes(new_minutes: int) -> None:
        try:
            mins = int(new_minutes)
            sched.reschedule_job("cycle", trigger="interval", minutes=mins)
        except Exception as e:
            logger.warning("reschedule_job failed: %s", e)

    async def _trigger_cycle() -> None:
        # Avoid blocking Telegram UI; schedule the job in background.
        asyncio.create_task(_run_cycle())

    set_runtime_callbacks(_set_interval_minutes, _trigger_cycle)

    sched.start()
    await _run_cycle()

    stop = asyncio.Event()

    def _sig(*_):
        logger.info("Shutdown signal.")
        stop.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig)
        except Exception:
            pass

    poll_task = None
    if app and chat_id:

        async def _poll():
            try:
                logger.info("Polling…")
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

    await stop.wait()
    sched.shutdown(wait=False)
    if app:
        try:
            await app.updater.stop()
        except Exception:
            pass
        try:
            await app.stop()
            await app.shutdown()
        except Exception:
            pass
    if poll_task:
        try:
            await poll_task
        except Exception:
            pass
    logger.info("Stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
