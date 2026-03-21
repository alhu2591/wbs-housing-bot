from __future__ import annotations

import logging
from typing import Any

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)

_CFG: dict[str, Any] = {}


BOT_COMMANDS = [
    BotCommand("start", "Start"),
    BotCommand("status", "Show current filters"),
    BotCommand("ping", "Health check"),
]


def set_config(cfg: dict[str, Any]) -> None:
    global _CFG
    _CFG = dict(cfg or {})


def _fmt_price(price: Any) -> str | None:
    if price is None:
        return None
    try:
        return f"{float(price):.0f} €"
    except Exception:
        return None


def format_listing(listing: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup | None]:
    title = str(listing.get("title") or "").strip()
    loc = str(listing.get("location") or "").strip()
    url = str(listing.get("url") or "").strip()
    price = _fmt_price(listing.get("price"))

    lines = ["🏠 " + (title or "Listing")]
    if loc:
        lines.append("📍 " + loc)
    if price:
        lines.append("💰 " + price)
    if url:
        lines.append("🔗 " + url)

    msg = "\n".join(lines).strip()
    if url:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("Open", url=url)]])
        return msg, kb
    return msg, None


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "WBS Housing Bot is running.\nUse /status to view current filters.",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    city = str(_CFG.get("city") or "")
    max_price = _CFG.get("max_price")
    interval = _CFG.get("interval_minutes")
    await update.message.reply_text(
        "Current config:\n"
        f"- city: {city}\n"
        f"- max_price: {max_price}\n"
        f"- interval_minutes: {interval}",
    )


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong")


def build_app(bot_token: str):
    """Build Telegram Application (python-telegram-bot)."""
    app = ApplicationBuilder().token(bot_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("ping", cmd_ping))
    return app


__all__ = ["BOT_COMMANDS", "build_app", "format_listing", "set_config"]



