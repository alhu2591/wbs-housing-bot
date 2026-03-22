"""
bot/arabic_ui.py — Full Arabic Telegram control panel.
Inline buttons for all settings. Instant listing notifications
with score, Jobcenter status, images, and link.
"""
from __future__ import annotations

import logging
from typing import Any

from telegram import (
    Bot, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto, Update,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError, BadRequest

logger = logging.getLogger(__name__)

# ── Emoji helpers ──────────────────────────────────────────────────────────

def _score_stars(score: int) -> str:
    if score >= 80:
        return "⭐⭐⭐⭐⭐"
    elif score >= 60:
        return "⭐⭐⭐⭐"
    elif score >= 40:
        return "⭐⭐⭐"
    elif score >= 20:
        return "⭐⭐"
    return "⭐"


def _jc_badge(ok: bool) -> str:
    return "✅ مناسب للجوبسنتر" if ok else "❌ غير مناسب للجوبسنتر"


def _type_badge(ai_type: str) -> str:
    badges = {
        "wg": "🏠 WG / مشترك",
        "senioren": "👴 للمسنين",
        "temporary": "⏰ مؤقت",
        "commercial": "🏢 تجاري",
        "normal": "🏡 شقة عادية",
    }
    return badges.get(ai_type, "🏡 شقة")


# ── Listing message builder ────────────────────────────────────────────────

def build_listing_caption(listing: dict[str, Any]) -> str:
    """Build Arabic caption for a listing notification."""
    title = listing.get("title") or "بدون عنوان"
    price = listing.get("price") or "—"
    location = listing.get("location") or "—"
    size = listing.get("size_m2") or "—"
    rooms = listing.get("rooms") or "—"
    wbs = listing.get("wbs_label") or ""
    score = int(listing.get("score") or 0)
    jc_ok = bool(listing.get("jobcenter_ok"))
    ai_type = listing.get("ai_type", "normal")
    desc = str(listing.get("description") or "")[:200]
    url = listing.get("url") or ""

    lines = [
        f"🏠 *{title}*",
        "",
        f"💰 *السعر:* {price} €" if price != "—" else "💰 *السعر:* غير محدد",
        f"📍 *الموقع:* {location}",
    ]

    if size != "—":
        lines.append(f"📐 *المساحة:* {size} م²")
    if rooms != "—":
        lines.append(f"🛏 *الغرف:* {rooms}")
    if wbs:
        lines.append(f"📋 *WBS:* {wbs}")

    lines += [
        "",
        f"🔢 *التقييم:* {score}/100 {_score_stars(score)}",
        f"🏛 {_jc_badge(jc_ok)}",
        f"🏷 *النوع:* {_type_badge(ai_type)}",
    ]

    if desc:
        lines += ["", f"📝 _{desc}..._"]

    if url:
        lines += ["", f"🔗 [فتح الإعلان]({url})"]

    caption = "\n".join(lines)
    # Telegram caption limit: 1024 chars
    if len(caption) > 1020:
        caption = caption[:1017] + "..."
    return caption


def build_listing_keyboard(listing: dict[str, Any]) -> InlineKeyboardMarkup | None:
    url = listing.get("url")
    if not url:
        return None
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔗 فتح الإعلان", url=url)
    ]])


async def send_listing_arabic(
    bot: Bot,
    chat_id: str,
    listing: dict[str, Any],
    send_images: bool = True,
    max_photos: int = 5,
) -> bool:
    """Send a listing to Telegram with Arabic caption + optional images."""
    caption = build_listing_caption(listing)
    keyboard = build_listing_keyboard(listing)
    images = listing.get("images") or []

    if send_images and images:
        photo_urls = [u for u in images if u and u.startswith("http")][:max_photos]
        if photo_urls:
            try:
                media = []
                for i, url in enumerate(photo_urls):
                    if i == 0:
                        media.append(InputMediaPhoto(
                            media=url,
                            caption=caption,
                            parse_mode=ParseMode.MARKDOWN,
                        ))
                    else:
                        media.append(InputMediaPhoto(media=url))
                await bot.send_media_group(chat_id=chat_id, media=media)
                if keyboard:
                    await bot.send_message(
                        chat_id=chat_id,
                        text="🔗 رابط الإعلان:",
                        reply_markup=keyboard,
                    )
                return True
            except (TelegramError, BadRequest) as e:
                logger.warning("Media group failed, fallback text: %s", e)

    # Text fallback
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
            disable_web_page_preview=False,
        )
        return True
    except Exception as e:
        logger.error("send_listing_arabic failed: %s", e)
        return False


# ── Settings Menu ──────────────────────────────────────────────────────────

def build_main_menu(cfg: dict[str, Any]) -> InlineKeyboardMarkup:
    """Build the main Arabic settings inline keyboard."""
    notify = "🔔 تفعيل" if cfg.get("notify_enabled", True) else "🔕 إيقاف"
    images = "🖼 الصور: تشغيل" if cfg.get("send_images", True) else "🖼 الصور: إيقاف"
    jc = "🏛 جوبسنتر: تشغيل" if cfg.get("jobcenter_rules", {}) else "🏛 جوبسنتر: إيقاف"
    wbs_req = "📋 WBS مطلوب" if cfg.get("wbs_required") else "📋 WBS اختياري"
    interval = cfg.get("interval_seconds", 60)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📍 اختيار المناطق", callback_data="set_city"),
            InlineKeyboardButton("💰 السعر الأقصى", callback_data="set_price"),
        ],
        [
            InlineKeyboardButton("📐 المساحة الدنيا", callback_data="set_size"),
            InlineKeyboardButton("🛏 عدد الغرف", callback_data="set_rooms"),
        ],
        [
            InlineKeyboardButton(wbs_req, callback_data="toggle_wbs"),
            InlineKeyboardButton(jc, callback_data="toggle_jc"),
        ],
        [
            InlineKeyboardButton(images, callback_data="toggle_images"),
            InlineKeyboardButton(notify, callback_data="toggle_notify"),
        ],
        [
            InlineKeyboardButton(
                f"⏱ التحديث: {interval}ث",
                callback_data="set_interval"
            ),
        ],
        [
            InlineKeyboardButton("📊 الإحصائيات", callback_data="stats"),
            InlineKeyboardButton("🔄 فحص الآن", callback_data="scan_now"),
        ],
        [
            InlineKeyboardButton("🌐 لوحة التحكم", callback_data="dashboard_link"),
        ],
    ])


def build_interval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("30 ث", callback_data="interval_30"),
            InlineKeyboardButton("60 ث", callback_data="interval_60"),
            InlineKeyboardButton("120 ث", callback_data="interval_120"),
        ],
        [InlineKeyboardButton("↩️ رجوع", callback_data="back_main")],
    ])


def build_wbs_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("WBS 100", callback_data="wbs_100"),
            InlineKeyboardButton("WBS 140", callback_data="wbs_140"),
            InlineKeyboardButton("WBS 160", callback_data="wbs_160"),
            InlineKeyboardButton("WBS 180", callback_data="wbs_180"),
            InlineKeyboardButton("WBS 200", callback_data="wbs_200"),
        ],
        [InlineKeyboardButton("↩️ رجوع", callback_data="back_main")],
    ])


# ── Admin notifications ────────────────────────────────────────────────────

async def send_admin_alert(
    bot: Bot,
    admin_chat_id: str,
    message: str,
) -> None:
    """Send a critical error alert to admin."""
    try:
        await bot.send_message(
            chat_id=admin_chat_id,
            text=f"⚠️ *تنبيه النظام*\n\n{message[:3000]}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error("Admin alert failed: %s", e)


async def send_daily_summary(
    bot: Bot,
    admin_chat_id: str,
    summary: dict[str, Any],
) -> None:
    """Send daily summary report."""
    text = (
        "📊 *التقرير اليومي — بوت السكن*\n\n"
        f"🏠 إعلانات اليوم: *{summary.get('listings_found_24h', 0)}*\n"
        f"👁 إجمالي المشاهدات: *{summary.get('total_seen', 0)}*\n"
        f"💾 إجمالي الإعلانات: *{summary.get('total_listings', 0)}*\n"
        f"❌ أخطاء اليوم: *{summary.get('errors_24h', 0)}*\n"
    )
    try:
        await bot.send_message(
            chat_id=admin_chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error("Daily summary send failed: %s", e)
