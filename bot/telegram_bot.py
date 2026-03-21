"""
Telegram UI (inline keyboards) + sending listings.

The main app (`main.py`) runs the scrape scheduler; this module:
1) provides interactive filter/source/settings menus
2) persists changes to `data/config.json`
3) notifies the scheduler to rescrape immediately when relevant
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from scraper.registry import ALL_SOURCE_IDS
from utils.config_store import save_runtime_config

logger = logging.getLogger(__name__)

_CFG: dict[str, Any] = {}

BOT_COMMANDS = [
    BotCommand("start", "Start"),
    BotCommand("status", "Show config"),
    BotCommand("settings", "Open settings menu"),
    BotCommand("ping", "Health check"),
]

_runtime_on_interval_change: Callable[[int], None] | None = None
_runtime_trigger_cycle: Callable[[], Awaitable[None]] | None = None


def set_runtime_callbacks(
    on_interval_change: Callable[[int], None],
    trigger_cycle: Callable[[], Awaitable[None]],
) -> None:
    global _runtime_on_interval_change, _runtime_trigger_cycle
    _runtime_on_interval_change = on_interval_change
    _runtime_trigger_cycle = trigger_cycle


def set_config(cfg: dict[str, Any]) -> None:
    global _CFG
    _CFG = dict(cfg or {})


def get_config() -> dict[str, Any]:
    return _CFG


def _persist_cfg() -> None:
    try:
        save_runtime_config(_CFG)
    except Exception as e:
        logger.warning("persist runtime config failed: %s", e)


def _fmt_maybe_int(v: Any) -> str:
    if v is None:
        return "off"
    try:
        fv = float(v)
        if fv.is_integer():
            return str(int(fv))
        return str(fv).rstrip("0").rstrip(".")
    except Exception:
        return str(v)


def _fmt_price(v: Any) -> str:
    if v is None:
        return "off"
    try:
        return f"{int(float(v))}"
    except Exception:
        return str(v)


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


def _menu_main(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    city = cfg.get("city") or ""
    max_price = cfg.get("max_price")
    min_size = cfg.get("min_size")
    rooms = cfg.get("rooms")
    wbs_required = bool(cfg.get("wbs_required", False))
    sources = cfg.get("sources") or []
    notify_enabled = bool(cfg.get("notify_enabled", True))
    send_images = bool(cfg.get("send_images", False))
    max_images = int(cfg.get("max_images") or 5)

    text = (
        "WBS Housing Bot (Berlin)\n\n"
        f"Stadt: {city or 'alle'}\n"
        f"Max. Preis: {_fmt_price(max_price)} €\n"
        f"Min. Fläche: {_fmt_maybe_int(min_size)} m²\n"
        f"Min. Zimmer: {_fmt_maybe_int(rooms)}\n"
        f"WBS erforderlich: {'Ja' if wbs_required else 'Nein'}\n"
        f"Quellen aktiv: {len(sources)}\n"
        f"Benachrichtigungen: {'ON' if notify_enabled else 'OFF'}\n"
        f"Bilder: {'ON' if send_images else 'OFF'} (max {max_images})\n"
        f"Intervall: {int(cfg.get('interval_minutes') or 10)} min\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Filter", callback_data="ui:filters")],
            [InlineKeyboardButton("Quellen", callback_data="ui:sources")],
            [InlineKeyboardButton("Benachrichtigungen", callback_data="ui:notify")],
            [InlineKeyboardButton("Medien", callback_data="ui:media")],
        ]
    )
    return text, kb


def _menu_filters(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    city = cfg.get("city") or ""
    max_price = cfg.get("max_price")
    min_size = cfg.get("min_size")
    rooms = cfg.get("rooms")
    wbs_required = bool(cfg.get("wbs_required", False))
    kw_inc = cfg.get("keywords_include") or []
    kw_exc = cfg.get("keywords_exclude") or []

    text = (
        "Filter Einstellungen\n\n"
        f"Stadt: {city or 'alle'}\n"
        f"Max. Preis: {_fmt_price(max_price)} €\n"
        f"Min. Fläche: {_fmt_maybe_int(min_size)} m²\n"
        f"Min. Zimmer: {_fmt_maybe_int(rooms)}\n"
        f"WBS erforderlich: {'Ja' if wbs_required else 'Nein'}\n"
        f"Keywords include: {len(kw_inc)} | exclude: {len(kw_exc)}\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"Stadt: {city or 'alle'}", callback_data="ui:prompt:city")],
            [
                InlineKeyboardButton("-50 €", callback_data="ui:delta:max_price:-50"),
                InlineKeyboardButton("+50 €", callback_data="ui:delta:max_price:50"),
            ],
            [
                InlineKeyboardButton("Set Max. Preis", callback_data="ui:prompt:max_price"),
                InlineKeyboardButton("Max. Preis aus", callback_data="ui:disable:max_price"),
            ],
            [
                InlineKeyboardButton("-5 m²", callback_data="ui:delta:min_size:-5"),
                InlineKeyboardButton("+5 m²", callback_data="ui:delta:min_size:5"),
            ],
            [
                InlineKeyboardButton("Set Min. Fläche", callback_data="ui:prompt:min_size"),
                InlineKeyboardButton("Min. Fläche aus", callback_data="ui:disable:min_size"),
            ],
            [
                InlineKeyboardButton("-1 Zimmer", callback_data="ui:delta:rooms:-1"),
                InlineKeyboardButton("+1 Zimmer", callback_data="ui:delta:rooms:1"),
            ],
            [
                InlineKeyboardButton("Set Zimmer", callback_data="ui:prompt:rooms"),
                InlineKeyboardButton("Zimmer aus", callback_data="ui:disable:rooms"),
            ],
            [
                InlineKeyboardButton(f"WBS: {'Ja' if wbs_required else 'Nein'}", callback_data="ui:toggle:wbs_required"),
                InlineKeyboardButton("Keywords", callback_data="ui:keywords"),
            ],
            [InlineKeyboardButton("Zurück", callback_data="ui:main")],
        ]
    )
    return text, kb


def _menu_keywords(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    kw_inc = cfg.get("keywords_include") or []
    kw_exc = cfg.get("keywords_exclude") or []

    def _sample(items: list[str]) -> str:
        if not items:
            return "—"
        s = ", ".join(items[:6])
        if len(items) > 6:
            s += ", …"
        return s

    text = (
        "Keywords (Substrings, case-insensitive)\n\n"
        f"Include ({len(kw_inc)}): {_sample(kw_inc)}\n"
        f"Exclude ({len(kw_exc)}): {_sample(kw_exc)}\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Add include", callback_data="ui:prompt:kw_include"),
                InlineKeyboardButton("Clear include", callback_data="ui:clear:kw_include"),
            ],
            [
                InlineKeyboardButton("Add exclude", callback_data="ui:prompt:kw_exclude"),
                InlineKeyboardButton("Clear exclude", callback_data="ui:clear:kw_exclude"),
            ],
            [InlineKeyboardButton("Zurück", callback_data="ui:filters")],
        ]
    )
    return text, kb


def _menu_sources(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    enabled = set(cfg.get("sources") or [])
    text = (
        "Quellen (Portale) auswählen\n\n"
        "Aktivierte Quellen werden beim nächsten Cycle gescraped.\n"
        f"Aktiv: {len(enabled)}/{len(ALL_SOURCE_IDS)}"
    )

    buttons = []
    for sid in ALL_SOURCE_IDS:
        on = sid in enabled
        label = ("[ON] " if on else "[OFF] ") + sid
        buttons.append(InlineKeyboardButton(label, callback_data=f"ui:toggle_src:{sid}"))

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for b in buttons:
        row.append(b)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton("Alle an", callback_data="ui:sources:all"),
            InlineKeyboardButton("Alle aus", callback_data="ui:sources:none"),
        ]
    )
    rows.append([InlineKeyboardButton("Zurück", callback_data="ui:main")])

    kb = InlineKeyboardMarkup(rows)
    return text, kb


def _menu_notify(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    notify_enabled = bool(cfg.get("notify_enabled", True))
    interval = int(cfg.get("interval_minutes") or 10)

    text = (
        "Benachrichtigungen\n\n"
        f"Status: {'ON' if notify_enabled else 'OFF'}\n"
        f"Intervall: {interval} Minuten\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("-5", callback_data="ui:delta:interval_minutes:-5"),
                InlineKeyboardButton("+5", callback_data="ui:delta:interval_minutes:5"),
            ],
            [
                InlineKeyboardButton("Set Intervall", callback_data="ui:prompt:interval_minutes"),
                InlineKeyboardButton("Zurück", callback_data="ui:main"),
            ],
            [InlineKeyboardButton(f"Notify: {'ON' if notify_enabled else 'OFF'}", callback_data="ui:toggle:notify_enabled")],
        ]
    )
    return text, kb


def _menu_media(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    send_images = bool(cfg.get("send_images", False))
    max_images = int(cfg.get("max_images") or 5)

    text = (
        "Medien / Bilder\n\n"
        f"Bilder senden: {'ON' if send_images else 'OFF'}\n"
        f"Max. Bilder pro Anzeige: {max_images}\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"Bilder: {'ON' if send_images else 'OFF'}", callback_data="ui:toggle:send_images")],
            [
                InlineKeyboardButton("-1", callback_data="ui:delta:max_images:-1"),
                InlineKeyboardButton("+1", callback_data="ui:delta:max_images:1"),
            ],
            [
                InlineKeyboardButton("Set max Bilder", callback_data="ui:prompt:max_images"),
                InlineKeyboardButton("Zurück", callback_data="ui:main"),
            ],
        ]
    )
    return text, kb


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config()
    text, kb = _menu_main(cfg)
    await update.message.reply_text(text, reply_markup=kb)


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config()
    text, kb = _menu_main(cfg)
    await update.message.reply_text(text, reply_markup=kb)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config()
    text = (
        "Aktuelle Config (effektiv):\n"
        f"city={cfg.get('city')}\n"
        f"max_price={cfg.get('max_price')}\n"
        f"min_size={cfg.get('min_size')}\n"
        f"rooms={cfg.get('rooms')}\n"
        f"wbs_required={cfg.get('wbs_required')}\n"
        f"interval_minutes={cfg.get('interval_minutes')}\n"
        f"notify_enabled={cfg.get('notify_enabled')}\n"
        f"send_images={cfg.get('send_images')}\n"
        f"max_images={cfg.get('max_images')}\n"
        f"sources={cfg.get('sources')}\n"
    )
    await update.message.reply_text(text)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("pong")


def _parse_optional_float(text: str) -> float | None:
    t = (text or "").strip()
    if not t:
        return None
    if t.lower() in {"none", "off", "disabled", "aus", "null"}:
        return None
    return float(t.replace(",", "."))


def _apply_numeric_delta(cfg: dict[str, Any], key: str, delta: float) -> dict[str, Any]:
    cur = cfg.get(key)
    base = float(cur) if cur is not None else 0.0
    nxt = base + float(delta)
    if key in {"max_price"}:
        if nxt <= 0:
            cfg[key] = None
        else:
            cfg[key] = float(nxt)
    elif key in {"min_size"}:
        if nxt <= 0:
            cfg[key] = None
        else:
            cfg[key] = float(nxt)
    elif key in {"rooms"}:
        if nxt <= 0:
            cfg[key] = None
        else:
            cfg[key] = float(nxt)
    elif key in {"interval_minutes"}:
        if nxt < 5:
            nxt = 5
        if nxt > 60:
            nxt = 60
        cfg[key] = int(nxt)
    elif key in {"max_images"}:
        if nxt < 1:
            nxt = 1
        if nxt > 10:
            nxt = 10
        cfg[key] = int(nxt)
    else:
        cfg[key] = nxt
    return cfg


async def _maybe_trigger_cycle() -> None:
    cb = _runtime_trigger_cycle
    if not cb:
        return
    try:
        res = cb()
        if asyncio.iscoroutine(res):
            await res
    except Exception as e:
        logger.warning("trigger_cycle failed: %s", e)


def _set_cfg(mut: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    global _CFG
    new_cfg = dict(_CFG)
    mut(new_cfg)
    # Avoid accidental aliasing of lists.
    for k in ("sources", "keywords_include", "keywords_exclude", "wbs_filter"):
        if k in new_cfg and isinstance(new_cfg[k], list):
            new_cfg[k] = list(new_cfg[k])
    # Normalize sources uniqueness.
    if "sources" in new_cfg and isinstance(new_cfg["sources"], list):
        seen: set[str] = set()
        uniq: list[str] = []
        for s in new_cfg["sources"]:
            ss = str(s).strip()
            if not ss or ss in seen:
                continue
            seen.add(ss)
            uniq.append(ss)
        new_cfg["sources"] = uniq

    _CFG = new_cfg
    _persist_cfg()
    return _CFG


async def _show_menu_for_query(
    query_update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    menu_id: str,
) -> None:
    cfg = get_config()

    if menu_id == "main":
        text, kb = _menu_main(cfg)
    elif menu_id == "filters":
        text, kb = _menu_filters(cfg)
    elif menu_id == "keywords":
        text, kb = _menu_keywords(cfg)
    elif menu_id == "sources":
        text, kb = _menu_sources(cfg)
    elif menu_id == "notify":
        text, kb = _menu_notify(cfg)
    elif menu_id == "media":
        text, kb = _menu_media(cfg)
    else:
        text, kb = _menu_main(cfg)

    q = query_update.callback_query
    try:
        await q.edit_message_text(text=text, reply_markup=kb)
    except Exception:
        await q.message.reply_text(text=text, reply_markup=kb)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    data = query.data
    await query.answer()

    if data == "ui:main":
        await _show_menu_for_query(update, context, "main")
        return
    if data == "ui:filters":
        await _show_menu_for_query(update, context, "filters")
        return
    if data == "ui:keywords":
        await _show_menu_for_query(update, context, "keywords")
        return
    if data == "ui:sources":
        await _show_menu_for_query(update, context, "sources")
        return
    if data == "ui:notify":
        await _show_menu_for_query(update, context, "notify")
        return
    if data == "ui:media":
        await _show_menu_for_query(update, context, "media")
        return

    parts = data.split(":")
    # Toggle booleans: ui:toggle:key
    if parts[0] == "ui" and parts[1] == "toggle" and len(parts) == 3:
        key = parts[2]
        new_val = not bool(get_config().get(key))
        _set_cfg(lambda c: c.__setitem__(key, new_val))
        if key == "interval_minutes" and _runtime_on_interval_change:
            _runtime_on_interval_change(int(new_val))
        if key in {"notify_enabled"}:
            await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "main")
        return

    # Navigation to prompt: ui:prompt:key
    if parts[0] == "ui" and parts[1] == "prompt" and len(parts) == 3:
        key = parts[2]
        context.chat_data["pending_cfg_action"] = {"type": "prompt", "key": key}
        await query.message.reply_text(
            _prompt_text_for_key(key),
        )
        return

    # Disable numeric filters: ui:disable:key
    if parts[0] == "ui" and parts[1] == "disable" and len(parts) == 3:
        key = parts[2]
        _set_cfg(lambda c: c.__setitem__(key, None))
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "filters" if key in {"city", "max_price", "min_size", "rooms", "wbs_required"} else "main")
        return

    # Clear keywords:
    if parts[0] == "ui" and parts[1] == "clear" and len(parts) == 3:
        key = parts[2]  # kw_include / kw_exclude
        if key == "kw_include":
            _set_cfg(lambda c: c.__setitem__("keywords_include", []))
        elif key == "kw_exclude":
            _set_cfg(lambda c: c.__setitem__("keywords_exclude", []))
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "keywords")
        return

    # Deltas: ui:delta:key:value
    if parts[0] == "ui" and parts[1] == "delta" and len(parts) == 4:
        key = parts[2]
        try:
            delta = float(parts[3])
        except Exception:
            delta = 0.0

        was_interval = key == "interval_minutes"
        _set_cfg(lambda c: _apply_numeric_delta(c, key, delta))
        if was_interval and _runtime_on_interval_change:
            _runtime_on_interval_change(int(float(get_config().get("interval_minutes") or 10)))
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "main")
        return

    # Toggle WBS required (handled above) / but we also keep this explicit for safety
    if data.startswith("ui:toggle_src:"):
        sid = data.split(":", 2)[2]
        def mut(c: dict[str, Any]) -> None:
            enabled = set(c.get("sources") or [])
            if sid in enabled:
                enabled.remove(sid)
            else:
                enabled.add(sid)
            c["sources"] = sorted(enabled)
        _set_cfg(mut)
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "sources")
        return

    if data == "ui:sources:all":
        _set_cfg(lambda c: c.__setitem__("sources", list(ALL_SOURCE_IDS)))
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "sources")
        return

    if data == "ui:sources:none":
        _set_cfg(lambda c: c.__setitem__("sources", []))
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "sources")
        return

    # Fallback
    await _show_menu_for_query(update, context, "main")


def _prompt_text_for_key(key: str) -> str:
    if key == "city":
        return "Schreibe die Stadt (z.B. Berlin). Leere Nachricht = alle."
    if key == "max_price":
        return "Max. Preis in € als Zahl senden (z.B. 700) oder 'none' zum Deaktivieren."
    if key == "min_size":
        return "Min. Fläche in m² senden (z.B. 30) oder 'none' zum Deaktivieren."
    if key == "rooms":
        return "Min. Zimmer senden (z.B. 1) oder 'none' zum Deaktivieren."
    if key == "interval_minutes":
        return "Intervall in Minuten senden (5–60)."
    if key == "max_images":
        return "Max. Bilder senden (1–10)."
    if key == "kw_include":
        return "Include-Keyword senden (Substring)."
    if key == "kw_exclude":
        return "Exclude-Keyword senden (Substring)."
    return "Wert senden."


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    pending = context.chat_data.get("pending_cfg_action")
    if not pending:
        return

    key = pending.get("key")
    text = update.message.text.strip()

    context.chat_data.pop("pending_cfg_action", None)

    def mut(c: dict[str, Any]) -> None:
        if key == "city":
            c["city"] = str(text).strip()
        elif key == "max_price":
            v = _parse_optional_float(text)
            c["max_price"] = None if v is None or v <= 0 else float(v)
        elif key == "min_size":
            v = _parse_optional_float(text)
            c["min_size"] = None if v is None or v <= 0 else float(v)
        elif key == "rooms":
            v = _parse_optional_float(text)
            c["rooms"] = None if v is None or v <= 0 else float(v)
        elif key == "interval_minutes":
            val = _parse_optional_float(text)
            if val is None:
                return
            mins = int(val)
            if mins < 5:
                mins = 5
            if mins > 60:
                mins = 60
            c["interval_minutes"] = mins
        elif key == "max_images":
            val = _parse_optional_float(text)
            if val is None:
                return
            mi = int(val)
            if mi < 1:
                mi = 1
            if mi > 10:
                mi = 10
            c["max_images"] = mi
        elif key == "kw_include":
            item = str(text).strip()
            if item:
                c["keywords_include"] = (c.get("keywords_include") or []) + [item]
        elif key == "kw_exclude":
            item = str(text).strip()
            if item:
                c["keywords_exclude"] = (c.get("keywords_exclude") or []) + [item]

    _set_cfg(mut)

    if key == "interval_minutes" and _runtime_on_interval_change:
        _runtime_on_interval_change(int(float(get_config().get("interval_minutes") or 10)))

    await update.message.reply_text("Config updated. Neues Scraping folgt bei relevantem Change…")
    await _maybe_trigger_cycle()

    cfg = get_config()
    main_text, main_kb = _menu_main(cfg)
    await update.message.reply_text(main_text, reply_markup=main_kb)


def build_app(bot_token: str):
    app = ApplicationBuilder().token(bot_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("ping", cmd_ping))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
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
                await bot.send_message(chat_id=chat_id, text="Anzeige öffnen", reply_markup=kb)
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
    "get_config",
    "send_listing",
    "set_config",
    "set_runtime_callbacks",
]
