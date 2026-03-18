"""
Telegram bot handlers — all commands + notification formatter.
Arabic-first UI.
"""
import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ApplicationBuilder,
    Application,
)
from telegram.constants import ParseMode

from database import get_settings, upsert_settings, get_all_health
from config.settings import CHAT_ID, BOT_TOKEN

logger = logging.getLogger(__name__)


# ── Access guard ─────────────────────────────────────────────────────────────

def _is_owner(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CHAT_ID)


async def _deny(update: Update) -> None:
    await update.message.reply_text("⛔ غير مصرح لك باستخدام هذا البوت.")


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=1)
    text = (
        "🏠 *أهلاً بك في بوت شقق WBS برلين!*\n\n"
        "سأراقب الإعلانات وأرسل لك فوراً أي شقة جديدة تحتاج WBS 100 في برلين.\n\n"
        "📋 *الأوامر المتاحة:*\n"
        "/status — الحالة الحالية والإعدادات\n"
        "/check — فحص حالة جميع المصادر\n"
        "/set\\_price [رقم] — تحديد أقصى إيجار (مثال: /set\\_price 550)\n"
        "/set\\_rooms [رقم] — أقل عدد غرف (مثال: /set\\_rooms 2)\n"
        "/set\\_area [منطقة] — تحديد الحي (مثال: /set\\_area Spandau)\n"
        "/on — تشغيل الإشعارات\n"
        "/off — إيقاف الإشعارات\n\n"
        "✅ البوت يعمل الآن ويبحث كل 2-3 دقائق."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return await _deny(update)
    s = await get_settings(str(update.effective_chat.id))
    active_icon = "✅ يعمل" if s.get("active") else "🔕 موقوف"
    area = s.get("area") or "كل برلين"
    rooms = s.get("min_rooms") or "أي عدد"
    text = (
        f"📊 *الحالة الحالية:*\n\n"
        f"🔔 الإشعارات: {active_icon}\n"
        f"💰 أقصى إيجار: {s.get('max_price', 600)} €\n"
        f"🛏 أقل غرف: {rooms}\n"
        f"📍 المنطقة: {area}\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ── /set_price ────────────────────────────────────────────────────────────────

async def cmd_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return await _deny(update)
    if not context.args:
        await update.message.reply_text("💬 أدخل الحد الأقصى للإيجار. مثال: /set_price 550")
        return
    try:
        price = float(context.args[0])
        await upsert_settings(str(update.effective_chat.id), max_price=price)
        await update.message.reply_text(f"✅ تم تحديد الحد الأقصى للإيجار: *{price} €*", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await update.message.reply_text("❌ رقم غير صحيح. مثال: /set_price 550")


# ── /set_rooms ────────────────────────────────────────────────────────────────

async def cmd_set_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return await _deny(update)
    if not context.args:
        await update.message.reply_text("💬 أدخل أقل عدد غرف. مثال: /set_rooms 2")
        return
    try:
        rooms = float(context.args[0])
        await upsert_settings(str(update.effective_chat.id), min_rooms=rooms)
        await update.message.reply_text(f"✅ أقل عدد غرف: *{rooms}*", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await update.message.reply_text("❌ رقم غير صحيح. مثال: /set_rooms 2")


# ── /set_area ─────────────────────────────────────────────────────────────────

async def cmd_set_area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return await _deny(update)
    if not context.args:
        await update.message.reply_text("💬 أدخل اسم الحي. مثال: /set_area Spandau")
        return
    area = " ".join(context.args)
    await upsert_settings(str(update.effective_chat.id), area=area)
    await update.message.reply_text(f"✅ تم تحديد المنطقة: *{area}*", parse_mode=ParseMode.MARKDOWN)


# ── /on / /off ────────────────────────────────────────────────────────────────

async def cmd_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=1)
    await update.message.reply_text("✅ تم تشغيل الإشعارات. سأبلغك بأي شقة جديدة مباشرةً!")


async def cmd_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=0)
    await update.message.reply_text("🔕 تم إيقاف الإشعارات. اكتب /on للتشغيل مرة أخرى.")


# ── /check ────────────────────────────────────────────────────────────────────

SOURCE_ARABIC = {
    "gewobag":        "Gewobag",
    "degewo":         "Degewo",
    "howoge":         "Howoge",
    "stadtundland":   "Stadt und Land",
    "deutschewohnen": "Deutsche Wohnen",
    "berlinovo":      "Berlinovo",
    "immoscout":      "ImmobilienScout24",
    "wggesucht":      "WG-Gesucht",
    "ebay_kleinanzeigen": "Kleinanzeigen",
    "immowelt":       "Immowelt",
}

ALL_SOURCES = list(SOURCE_ARABIC.keys())


def _time_ago(iso: str | None) -> str:
    if not iso:
        return "لم يعمل بعد"
    try:
        dt = datetime.fromisoformat(iso)
        diff = int((datetime.utcnow() - dt).total_seconds())
        if diff < 60:
            return f"منذ {diff} ث"
        elif diff < 3600:
            return f"منذ {diff // 60} د"
        else:
            return f"منذ {diff // 3600} س"
    except Exception:
        return "غير معروف"


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update):
        return await _deny(update)

    await update.message.reply_text("🔍 جاري فحص جميع المصادر…")

    health_rows = await get_all_health()
    health_map = {row["source"]: row for row in health_rows}

    ok_lines = []
    err_lines = []
    never_lines = []

    for src in ALL_SOURCES:
        label = SOURCE_ARABIC.get(src, src)
        row = health_map.get(src)

        if not row:
            never_lines.append(f"⚪️ {label} — لم يتم الفحص بعد")
            continue

        status = row.get("status", "unknown")
        count  = row.get("listings_found", 0)
        ago    = _time_ago(row.get("last_run"))
        runs   = row.get("total_runs", 0)
        errors = row.get("total_errors", 0)

        if status == "ok":
            ok_lines.append(
                f"✅ *{label}*\n"
                f"   📦 {count} إعلان | 🕐 {ago} | ⚡ {runs} تشغيل"
            )
        else:
            last_err = str(row.get("last_error", ""))[:80]
            err_lines.append(
                f"❌ *{label}*\n"
                f"   ⚠️ {last_err}\n"
                f"   🕐 {ago} | ❗ {errors} خطأ من {runs}"
            )

    lines = ["📊 *تقرير حالة المصادر*\n"]

    if ok_lines:
        lines.append("*✅ تعمل بنجاح:*")
        lines.extend(ok_lines)

    if err_lines:
        lines.append("\n*❌ بها أخطاء:*")
        lines.extend(err_lines)

    if never_lines:
        lines.append("\n*⚪️ لم تعمل بعد:*")
        lines.extend(never_lines)

    total_ok  = len(ok_lines)
    total_err = len(err_lines) + len(never_lines)
    lines.append(
        f"\n📈 *الملخص:* {total_ok} مصدر يعمل / {total_err} يحتاج مراجعة"
    )

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── Notification formatter ────────────────────────────────────────────────────

SOURCE_LABELS = {
    "gewobag":         "Gewobag 🏛",
    "degewo":          "Degewo 🏛",
    "howoge":          "Howoge 🏛",
    "stadtundland":    "Stadt und Land 🏛",
    "deutschewohnen":  "Deutsche Wohnen 🏛",
    "berlinovo":       "Berlinovo 🏛",
    "immoscout24":     "ImmobilienScout24",
    "wggesucht":       "WG-Gesucht",
    "kleinanzeigen":   "Kleinanzeigen",
    "immowelt":        "Immowelt",
}

SCORE_STARS = {10: "⭐⭐⭐", 5: "⭐⭐", 0: "⭐"}


def format_listing(listing: dict) -> str:
    price = f"{listing['price']:.0f} €" if listing.get("price") else "غير محدد"
    rooms = str(listing["rooms"]) if listing.get("rooms") else "غير محدد"
    location = listing.get("location") or "برلين"
    source = SOURCE_LABELS.get(listing.get("source", ""), listing.get("source", ""))
    score = listing.get("score", 0)
    stars = SCORE_STARS.get(max(k for k in SCORE_STARS if k <= score), "⭐")
    url = listing.get("url", "")

    return (
        f"🏠 *شقة جديدة — WBS مطلوب* {stars}\n\n"
        f"📌 *{listing.get('title', 'شقة للإيجار')}*\n\n"
        f"📍 الموقع: {location}\n"
        f"💰 السعر: {price}\n"
        f"🛏 عدد الغرف: {rooms}\n"
        f"📄 مطلوب: WBS 100\n"
        f"🏢 المصدر: {source}\n\n"
        f"🔗 [اضغط هنا لعرض الشقة]({url})"
    )


# ── App builder ───────────────────────────────────────────────────────────────

def build_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("set_price", cmd_set_price))
    app.add_handler(CommandHandler("set_rooms", cmd_set_rooms))
    app.add_handler(CommandHandler("set_area",  cmd_set_area))
    app.add_handler(CommandHandler("on",        cmd_on))
    app.add_handler(CommandHandler("off",       cmd_off))
    app.add_handler(CommandHandler("check",     cmd_check))
    return app
