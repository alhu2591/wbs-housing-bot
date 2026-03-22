"""
bot/callback_handler.py — Handles all inline button callbacks for the Arabic UI.
Integrates with config store, scheduler, and real-time engine controls.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes

from bot.arabic_ui import (
    build_main_menu, build_interval_keyboard, build_wbs_keyboard,
)

logger = logging.getLogger(__name__)

_cfg_getter: Callable[[], dict[str, Any]] = dict
_cfg_setter: Callable[[dict[str, Any]], None] = lambda x: None
_trigger_scan: Callable | None = None
_set_interval: Callable[[int], None] | None = None

AWAITING_INPUT: dict[int, str] = {}  # user_id → field being set


def set_callbacks(
    cfg_getter: Callable,
    cfg_setter: Callable,
    trigger_scan: Callable,
    set_interval_fn: Callable,
) -> None:
    global _cfg_getter, _cfg_setter, _trigger_scan, _set_interval
    _cfg_getter = cfg_getter
    _cfg_setter = cfg_setter
    _trigger_scan = trigger_scan
    _set_interval = set_interval_fn


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    cfg = _cfg_getter()
    chat_id = str(query.message.chat_id)

    # ── Main menu ──────────────────────────────────────────────────────────
    if data == "back_main":
        await query.edit_message_text(
            "⚙️ *لوحة التحكم — بوت السكن*",
            reply_markup=build_main_menu(cfg),
            parse_mode="Markdown",
        )

    # ── Toggles ────────────────────────────────────────────────────────────
    elif data == "toggle_notify":
        cfg["notify_enabled"] = not cfg.get("notify_enabled", True)
        _cfg_setter(cfg)
        status = "✅ التنبيهات مفعلة" if cfg["notify_enabled"] else "🔕 التنبيهات موقوفة"
        await query.edit_message_text(
            f"{status}\n\n⚙️ *الإعدادات*",
            reply_markup=build_main_menu(cfg),
            parse_mode="Markdown",
        )

    elif data == "toggle_images":
        cfg["send_images"] = not cfg.get("send_images", True)
        _cfg_setter(cfg)
        status = "🖼 الصور: تشغيل" if cfg["send_images"] else "🖼 الصور: إيقاف"
        await query.edit_message_text(
            f"{status}\n\n⚙️ *الإعدادات*",
            reply_markup=build_main_menu(cfg),
            parse_mode="Markdown",
        )

    elif data == "toggle_wbs":
        cfg["wbs_required"] = not cfg.get("wbs_required", False)
        _cfg_setter(cfg)
        status = "📋 WBS مطلوب الآن" if cfg["wbs_required"] else "📋 WBS اختياري الآن"
        await query.edit_message_text(
            f"{status}\n\n⚙️ *الإعدادات*",
            reply_markup=build_main_menu(cfg),
            parse_mode="Markdown",
        )

    elif data == "toggle_jc":
        jc = cfg.get("jobcenter_rules", {})
        if jc:
            cfg["_saved_jc"] = jc
            cfg["jobcenter_rules"] = {}
            status = "🏛 قواعد الجوبسنتر: إيقاف"
        else:
            cfg["jobcenter_rules"] = cfg.get("_saved_jc", {"max_rent": 700, "max_size": 50, "rooms": 1})
            status = "🏛 قواعد الجوبسنتر: تشغيل"
        _cfg_setter(cfg)
        await query.edit_message_text(
            f"{status}\n\n⚙️ *الإعدادات*",
            reply_markup=build_main_menu(cfg),
            parse_mode="Markdown",
        )

    # ── Interval selection ─────────────────────────────────────────────────
    elif data == "set_interval":
        await query.edit_message_text(
            "⏱ *اختر سرعة التحديث:*",
            reply_markup=build_interval_keyboard(),
            parse_mode="Markdown",
        )

    elif data.startswith("interval_"):
        secs = int(data.split("_")[1])
        cfg["interval_seconds"] = secs
        _cfg_setter(cfg)
        if _set_interval:
            _set_interval(secs)
        await query.edit_message_text(
            f"✅ تم تعيين التحديث كل *{secs} ثانية*\n\n⚙️ *الإعدادات*",
            reply_markup=build_main_menu(cfg),
            parse_mode="Markdown",
        )

    # ── WBS level selection ────────────────────────────────────────────────
    elif data.startswith("wbs_") and data[4:].isdigit():
        level = int(data.split("_")[1])
        wbs_filters = cfg.get("wbs_filter", [])
        label = f"wbs {level}"
        if label not in wbs_filters:
            wbs_filters.append(label)
        cfg["wbs_filter"] = wbs_filters
        cfg["wbs_required"] = True
        _cfg_setter(cfg)
        await query.edit_message_text(
            f"✅ تم إضافة *WBS {level}* للفلتر\n\n⚙️ *الإعدادات*",
            reply_markup=build_main_menu(cfg),
            parse_mode="Markdown",
        )

    # ── Scan now ───────────────────────────────────────────────────────────
    elif data == "scan_now":
        await query.edit_message_text(
            "🔍 *جاري الفحص الفوري...*\nسيتم إرسال النتائج خلال لحظات.",
            parse_mode="Markdown",
        )
        if _trigger_scan:
            import asyncio
            asyncio.create_task(_trigger_scan())

    # ── Stats ──────────────────────────────────────────────────────────────
    elif data == "stats":
        from database.db import get_daily_summary, get_source_stats
        summary = get_daily_summary()
        sources = get_source_stats()
        active = sum(1 for s in sources if not s.get("disabled"))

        text = (
            "📊 *إحصائيات النظام*\n\n"
            f"🏠 إعلانات اليوم: *{summary['listings_found_24h']}*\n"
            f"💾 إجمالي الإعلانات: *{summary['total_listings']}*\n"
            f"👁 إجمالي المشاهدات: *{summary['total_seen']}*\n"
            f"❌ أخطاء اليوم: *{summary['errors_24h']}*\n\n"
            f"🌐 المصادر النشطة: *{active}/{len(sources)}*\n"
        )
        from telegram import InlineKeyboardMarkup, InlineKeyboardButton
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ رجوع", callback_data="back_main")
        ]])
        await query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")

    # ── Input prompts ──────────────────────────────────────────────────────
    elif data == "set_city":
        AWAITING_INPUT[query.from_user.id] = "city"
        await query.edit_message_text(
            "📍 *أدخل اسم المدينة:*\nمثال: Berlin",
            parse_mode="Markdown",
        )

    elif data == "set_price":
        AWAITING_INPUT[query.from_user.id] = "max_price"
        await query.edit_message_text(
            "💰 *أدخل الحد الأقصى للسعر (€):*\nمثال: 700",
            parse_mode="Markdown",
        )

    elif data == "set_size":
        AWAITING_INPUT[query.from_user.id] = "min_size"
        await query.edit_message_text(
            "📐 *أدخل الحد الأدنى للمساحة (م²):*\nمثال: 30",
            parse_mode="Markdown",
        )

    elif data == "set_rooms":
        AWAITING_INPUT[query.from_user.id] = "rooms"
        await query.edit_message_text(
            "🛏 *أدخل الحد الأدنى لعدد الغرف:*\nمثال: 1",
            parse_mode="Markdown",
        )

    elif data == "dashboard_link":
        port = 8080
        await query.edit_message_text(
            f"🌐 *لوحة التحكم متاحة على:*\n`http://localhost:{port}`\n\n"
            "_(افتحها من جهاز الكمبيوتر أو من متصفح Termux)_",
            parse_mode="Markdown",
        )


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle free-text input for settings."""
    if not update.message or not update.effective_user:
        return

    user_id = update.effective_user.id
    field = AWAITING_INPUT.pop(user_id, None)
    if not field:
        return

    text = (update.message.text or "").strip()
    cfg = _cfg_getter()

    try:
        if field in ("max_price", "min_size", "rooms"):
            val = float(text)
            cfg[field] = val
            label = {"max_price": "السعر الأقصى", "min_size": "المساحة الدنيا", "rooms": "عدد الغرف"}.get(field, field)
            await update.message.reply_text(
                f"✅ تم تعيين *{label}* إلى *{val}*",
                reply_markup=build_main_menu(cfg),
                parse_mode="Markdown",
            )
        elif field == "city":
            cfg["city"] = text
            await update.message.reply_text(
                f"✅ تم تعيين المدينة إلى *{text}*",
                reply_markup=build_main_menu(cfg),
                parse_mode="Markdown",
            )
        _cfg_setter(cfg)
    except ValueError:
        await update.message.reply_text(
            "❌ قيمة غير صالحة، يرجى إدخال رقم صحيح.",
            parse_mode="Markdown",
        )


def get_handlers():
    """Return list of handlers to register with the Telegram app."""
    from telegram.ext import MessageHandler, filters
    return [
        CallbackQueryHandler(handle_callback),
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input),
    ]
