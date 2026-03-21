"""
WBS Housing Bot — Termux-friendly minimal CLI + Telegram bot.

Run:
  BOT_TOKEN=... CHAT_ID=... python main.py

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

from bot.handlers import BOT_COMMANDS, build_app, format_listing, set_config as set_bot_config
from scraper.scrape_cycle import scrape_new_listings
from utils.config_loader import load_config
from utils.logger import setup_logging
from utils.seen_store import make_seen_entry, persist_seen


setup_logging()
logger = logging.getLogger(__name__)


def _get_env(name: str) -> str:
    return os.getenv(name, "").strip()


async def _send_one(app, chat_id: str, listing: dict[str, Any], max_attempts: int = 3) -> bool:
    """Send a listing with retry (no crashes)."""
    text, keyboard = format_listing(listing)

    for attempt in range(max_attempts):
        try:
            await app.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                disable_web_page_preview=True,
            )
            return True
        except RetryAfter as e:
            await asyncio.sleep((getattr(e, "retry_after", 0) or 0) + 1)
        except (NetworkError, TimedOut) as e:
            if attempt < max_attempts - 1:
                await asyncio.sleep(2 * (attempt + 1))
            else:
                logger.error("Telegram network error (final): %s", e)
        except TelegramError as e:
            logger.error("Telegram error: %s", e)
            return False
        except Exception as e:
            logger.error("Telegram send failed: %s", e, exc_info=True)

    return False


async def _job_cycle(app, chat_id: str | None, cfg: dict[str, Any], seen_json_path: str) -> None:
    started = time.monotonic()
    try:
        listings = await scrape_new_listings(cfg, seen_json_path)
    except Exception as e:
        logger.error("scrape_new_listings crashed: %s", e, exc_info=True)
        return

    if not listings:
        logger.info("Cycle done: no new matches (%.1fs).", time.monotonic() - started)
        return

    max_per_cycle = int(cfg.get("max_per_cycle") or 10)
    to_send = listings[:max_per_cycle]

    if not app or not chat_id:
        logger.info("Cycle matched %d listings (no Telegram token configured).", len(to_send))
        for l in to_send:
            logger.info("MATCH: %s | %s | %s | %s", l.get("title"), l.get("price"), l.get("location"), l.get("url"))
        return

    logger.info("Cycle matched %d new listings; sending…", len(to_send))
    sent_ids: list[dict[str, Any]] = []

    for listing in to_send:
        try:
            ok = await _send_one(app, chat_id, listing)
            if ok:
                sent_ids.append(listing)
            await asyncio.sleep(0.2)
        except Exception as e:
            logger.error("Send loop error: %s", e, exc_info=True)

    if sent_ids:
        try:
            new_entries = {}
            for l in sent_ids:
                entry = make_seen_entry(l)
                if entry:
                    new_entries.update(entry)
            if new_entries:
                persist_seen(seen_json_path, new_entries)
        except Exception as e:
            logger.error("Failed to persist seen.json: %s", e, exc_info=True)

    logger.info(
        "Cycle done: sent=%d matched=%d (%.1fs).",
        len(sent_ids),
        len(to_send),
        time.monotonic() - started,
    )


async def _run_once_for_test(cfg: dict[str, Any], seen_json_path: str) -> None:
    listings = await scrape_new_listings(cfg, seen_json_path)
    if not listings:
        logger.info("No new listings.")
        return
    for l in listings:
        logger.info("TEST: %s | %s | %s | %s", l.get("title"), l.get("price"), l.get("location"), l.get("url"))


async def main() -> None:
    parser = argparse.ArgumentParser(description="WBS Housing Bot (Termux-friendly)")
    parser.add_argument("--test-scrape", action="store_true", help="Scrape once and log results (no Telegram).")
    args = parser.parse_args()

    cfg = load_config()
    set_bot_config(cfg)

    bot_token = _get_env("BOT_TOKEN")
    chat_id = _get_env("CHAT_ID")

    root_dir = os.path.dirname(os.path.abspath(__file__))
    seen_json_path = os.path.join(root_dir, "seen.json")

    if args.test_scrape:
        await _run_once_for_test(cfg, seen_json_path)
        return

    app = None
    if bot_token and chat_id:
        try:
            app = build_app(bot_token)
            app.add_error_handler(lambda update, context: logger.error("PTB error: %s", context.error, exc_info=True))
            await app.initialize()
            await app.start()
            try:
                await app.bot.set_my_commands(BOT_COMMANDS)
            except Exception as e:
                logger.warning("set_my_commands failed: %s", e)
        except Exception as e:
            logger.error("Failed to start Telegram app: %s", e, exc_info=True)
            app = None
    else:
        logger.warning("BOT_TOKEN/CHAT_ID missing; running scrape-only mode.")

    interval_minutes = int(cfg["interval_minutes"])
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _job_cycle,
        "interval",
        minutes=interval_minutes,
        max_instances=1,
        coalesce=True,
        args=[app, chat_id if bot_token and chat_id else None, cfg, seen_json_path],
        id="scrape_cycle",
        misfire_grace_time=120,
    )
    scheduler.start()

    # Immediate first run.
    await _job_cycle(app, chat_id if bot_token and chat_id else None, cfg, seen_json_path)

    stop_event = asyncio.Event()

    def _handle_signal(*_):
        logger.info("Shutdown signal received.")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_signal)
        except Exception:
            pass

    poll_task = None
    if app and chat_id:

        async def _polling_supervisor() -> None:
            try:
                logger.info("Telegram polling started.")
                await app.updater.start_polling(
                    drop_pending_updates=True,
                    allowed_updates=["message", "callback_query"],
                    read_timeout=30,
                    write_timeout=30,
                    connect_timeout=15,
                    pool_timeout=15,
                )
            except Exception as e:
                logger.error("Polling crashed: %s", e, exc_info=True)

        poll_task = asyncio.create_task(_polling_supervisor())

    await stop_event.wait()

    logger.info("Stopping scheduler…")
    scheduler.shutdown(wait=False)

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

"""
WBS Housing Bot — Termux-friendly minimal CLI + Telegram bot.

Run:
  BOT_TOKEN=... CHAT_ID=... python main.py

Optional:
  python main.py --test-scrape
"""

# NOTE: legacy/duplicated content was appended to the original file during refactor.
# It is intentionally disabled at runtime by `raise SystemExit` above, but we must also

