"""
Telegram: commands, listing caption, optional photo media group.
"""
from __future__ import annotations

import logging
from typing import Any

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logger = logging.getLogger(__name__)

_CFG: dict[str, Any] = {}

BOT_COMMANDS = [
    BotCommand("start", "Start"),
    BotCommand("status", "Show config"),
    BotCommand("ping", "Health check"),
]


def set_config(cfg: dict[str, Any]) -> None:
    global _CFG
    _CFG = dict(cfg or {})


def format_listing_caption(listing: dict[str, Any]) -> str:
    title = str(listing.get("title") or "Listing").strip()
    price = listing.get("price")
    price_s = f"{int(price)} €" if price is not None else "—"
    loc = str(listing.get("location") or "").strip()
    dist = str(listing.get("district") or "").strip()
    city = str(listing.get("city") or "").strip()
    loc_line = ", ".join(x for x in (loc, dist, city) if x) or "—"
    sz = listing.get("size_m2")
    rooms = listing.get("rooms")
    sz_s = f"{sz:.0f} m²" if sz is not None else "—"
    r_s = str(rooms) if rooms is not None else "—"
    wbs = str(listing.get("wbs_label") or ("Ja" if listing.get("trusted_wbs") else "—"))
    url = str(listing.get("url") or "").strip()
    desc = str(listing.get("description") or "").strip()
    if len(desc) > 400:
        desc = desc[:397] + "…"
    lines = [
        title,
        f"Preis: {price_s}",
        f"Ort: {loc_line}",
        f"Fläche: {sz_s} · Zimmer: {r_s}",
        f"WBS: {wbs}",
    ]
    if desc:
        lines.append("")
        lines.append(desc)
    if url:
        lines.append("")
        lines.append(url)
    text = "\n".join(lines)
    if len(text) > 1024:
        text = text[:1021] + "…"
    return text


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "WBS Housing Bot läuft.\n/status zeigt die aktuelle config.json.",
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "config.json:\n"
        f"city={_CFG.get('city')}\n"
        f"max_price={_CFG.get('max_price')}\n"
        f"min_size={_CFG.get('min_size')}\n"
        f"rooms={_CFG.get('rooms')}\n"
        f"wbs_required={_CFG.get('wbs_required')}\n"
        f"interval_minutes={_CFG.get('interval_minutes')}\n"
        f"send_images={_CFG.get('send_images')}",
    )


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong")


def build_app(bot_token: str):
    app = ApplicationBuilder().token(bot_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("ping", cmd_ping))
    return app


async def send_listing(
    bot,
    chat_id: str,
    listing: dict[str, Any],
    *,
    send_images: bool = True,
    max_photos: int = 5,
) -> bool:
    """Send one listing; use media group when images available."""
    caption = format_listing_caption(listing)
    url = str(listing.get("url") or "")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Öffnen", url=url)]]) if url else None
    imgs = [u for u in (listing.get("images") or []) if isinstance(u, str) and u.startswith("http")]
    imgs = imgs[:max(1, min(max_photos, 10))]

    if send_images and len(imgs) >= 1:
        try:
            media: list[InputMediaPhoto] = []
            for i, u in enumerate(imgs[:max_photos]):
                if i == 0:
                    media.append(InputMediaPhoto(media=u, caption=caption))
                else:
                    media.append(InputMediaPhoto(media=u))
            await bot.send_media_group(chat_id=chat_id, media=media)
            if kb:
                await bot.send_message(chat_id=chat_id, text="⬆️ Anzeige", reply_markup=kb)
            return True
        except Exception as e:
            logger.warning("send_media_group failed, fallback to text: %s", e)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=kb,
            disable_web_page_preview=False,
        )
        return True
    except Exception as e:
        logger.error("send_message failed: %s", e)
        return False


__all__ = [
    "BOT_COMMANDS",
    "build_app",
    "format_listing_caption",
    "send_listing",
    "set_config",
]
