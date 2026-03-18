"""
Telegram bot — professional Arabic UI, AI-enriched listings, inline buttons.
"""
import logging
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, CommandHandler,
    ApplicationBuilder, Application,
)
from telegram.constants import ParseMode

from database import get_settings, upsert_settings, get_all_health, get_stats
from config.settings import CHAT_ID, BOT_TOKEN, SCRAPER_API_KEY

logger = logging.getLogger(__name__)


# ── Access guard ──────────────────────────────────────────────────────────────

def _is_owner(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CHAT_ID)

async def _deny(update: Update) -> None:
    await update.message.reply_text("⛔ غير مصرح.")


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=1)
    text = (
        "🏠 *بوت شقق WBS برلين*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "أراقب أكثر من *10 مواقع* كل دقيقتين "
        "وأرسل لك فوراً كل شقة WBS جديدة مع تحليل ذكي كامل.\n\n"
        "⚙️ *الأوامر:*\n"
        "├ /status — الحالة والإعدادات\n"
        "├ /stats — إحصائيات البوت\n"
        "├ /check — صحة المصادر\n"
        "├ /check\\_proxy — اختبار ScraperAPI\n"
        "├ /set\\_price 550 — أقصى إيجار (€)\n"
        "├ /set\\_rooms 2 — أقل عدد غرف\n"
        "├ /set\\_area Spandau — تحديد الحي\n"
        "├ /on — تشغيل الإشعارات\n"
        "└ /off — إيقاف الإشعارات\n\n"
        "✅ *البوت يعمل — يبحث كل 2 دقيقة*"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s = await get_settings(str(update.effective_chat.id))
    import os
    ai_status  = "✅ مفعّل (تحليل ذكي)" if os.getenv("ANTHROPIC_API_KEY") else "⚠️ غير مفعّل (regex)"
    proxy      = "✅ مفعّل" if SCRAPER_API_KEY else "⚠️ غير مفعّل"
    active     = "🟢 يعمل" if s.get("active") else "🔴 موقوف"
    area       = s.get("area") or "كل برلين"
    rooms      = s.get("min_rooms") or "أي عدد"
    text = (
        "📊 *الإعدادات الحالية*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔔 الإشعارات:    {active}\n"
        f"💰 أقصى إيجار:  {s.get('max_price', 600)} €\n"
        f"🛏 أقل غرف:     {rooms}\n"
        f"📍 المنطقة:      {area}\n"
        f"🤖 الذكاء:       {ai_status}\n"
        f"🌐 ScraperAPI:   {proxy}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ── /stats ────────────────────────────────────────────────────────────────────

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    st = await get_stats()
    last = st.get("last_sent_at")
    last_str = _time_ago(last) if last else "لم يُرسل بعد"
    text = (
        "📈 *إحصائيات البوت*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📨 إشعارات مُرسلة:   {st.get('total_sent', 0)}\n"
        f"🔄 دورات كشط:       {st.get('total_cycles', 0)}\n"
        f"🗃 إعلانات محفوظة:  {st.get('db_size', 0)}\n"
        f"🕐 آخر إشعار:       {last_str}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ── /set_price / /set_rooms / /set_area ──────────────────────────────────────

async def cmd_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if not context.args:
        await update.message.reply_text("مثال: /set_price 550"); return
    try:
        p = float(context.args[0])
        await upsert_settings(str(update.effective_chat.id), max_price=p)
        await update.message.reply_text(
            f"✅ أقصى إيجار: *{p:.0f} €*", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await update.message.reply_text("❌ رقم غير صحيح. مثال: /set_price 550")


async def cmd_set_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if not context.args:
        await update.message.reply_text("مثال: /set_rooms 2"); return
    try:
        r = float(context.args[0])
        await upsert_settings(str(update.effective_chat.id), min_rooms=r)
        await update.message.reply_text(
            f"✅ أقل عدد غرف: *{r}*", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await update.message.reply_text("❌ رقم غير صحيح. مثال: /set_rooms 2")


async def cmd_set_area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if not context.args:
        await update.message.reply_text("مثال: /set_area Spandau"); return
    area = " ".join(context.args)
    await upsert_settings(str(update.effective_chat.id), area=area)
    await update.message.reply_text(
        f"✅ المنطقة: *{area}*", parse_mode=ParseMode.MARKDOWN)


# ── /on / /off ────────────────────────────────────────────────────────────────

async def cmd_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=1)
    await update.message.reply_text(
        "🟢 *الإشعارات شغّالة*", parse_mode=ParseMode.MARKDOWN)


async def cmd_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=0)
    await update.message.reply_text(
        "🔴 *الإشعارات موقوفة*", parse_mode=ParseMode.MARKDOWN)


# ── /check ────────────────────────────────────────────────────────────────────

SOURCE_ARABIC = {
    "gewobag":            "Gewobag 🏛",
    "degewo":             "Degewo 🏛",
    "howoge":             "Howoge 🏛",
    "stadtundland":       "Stadt und Land 🏛",
    "deutschewohnen":     "Deutsche Wohnen 🏛",
    "berlinovo":          "Berlinovo 🏛",
    "immoscout":          "ImmobilienScout24",
    "wggesucht":          "WG-Gesucht",
    "ebay_kleinanzeigen": "Kleinanzeigen",
    "immowelt":           "Immowelt",
}
ALL_SOURCES = list(SOURCE_ARABIC.keys())


def _time_ago(iso: str | None) -> str:
    if not iso: return "—"
    try:
        dt = datetime.fromisoformat(iso)
        diff = int((datetime.utcnow() - dt).total_seconds())
        if diff < 60:      return f"منذ {diff} ث"
        elif diff < 3600:  return f"منذ {diff // 60} د"
        elif diff < 86400: return f"منذ {diff // 3600} س"
        else:              return f"منذ {diff // 86400} يوم"
    except Exception:
        return "—"


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await update.message.reply_text("🔍 جاري فحص المصادر…")
    health_rows = await get_all_health()
    hmap = {r["source"]: r for r in health_rows}

    ok_lines, err_lines, never_lines = [], [], []
    for src in ALL_SOURCES:
        label = SOURCE_ARABIC.get(src, src)
        row   = hmap.get(src)
        if not row:
            never_lines.append(f"⚪ {label}")
            continue
        if row.get("status") == "ok":
            ok_lines.append(
                f"✅ *{label}*  `{row.get('listings_found', 0)} إعلان` · {_time_ago(row.get('last_run'))}"
            )
        else:
            err = str(row.get("last_error", ""))[:60]
            err_lines.append(f"❌ *{label}*\n   └ `{err}`")

    lines = ["📊 *حالة المصادر*\n━━━━━━━━━━━━━━━━━━━━\n"]
    lines += ok_lines
    if err_lines:
        lines += ["\n*❌ أخطاء:*"] + err_lines
    if never_lines:
        lines += ["\n*⚪ لم تعمل بعد:*", "  " + " · ".join(never_lines)]
    lines.append(f"\n📈 *{len(ok_lines)}/{len(ALL_SOURCES)}* مصدر يعمل")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── /check_proxy ──────────────────────────────────────────────────────────────

async def cmd_check_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if not SCRAPER_API_KEY:
        await update.message.reply_text(
            "⚠️ *ScraperAPI غير مفعّل*\n\n"
            "Railway → Variables → `SCRAPER_API_KEY = مفتاحك`",
            parse_mode=ParseMode.MARKDOWN); return
    await update.message.reply_text("🔍 جاري الاختبار…")
    try:
        import httpx
        from urllib.parse import urlencode
        params = urlencode({"api_key": SCRAPER_API_KEY, "url": "https://httpbin.org/ip"})
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.get(f"https://api.scraperapi.com/?{params}")
        if r.status_code == 200:
            ip = r.json().get("origin", "?")
            await update.message.reply_text(
                f"✅ *ScraperAPI يعمل*\n🌐 IP: `{ip}`",
                parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text(f"❌ HTTP {r.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


# ── Source metadata ───────────────────────────────────────────────────────────

GOV_SOURCES = {
    "gewobag", "degewo", "howoge",
    "stadtundland", "deutschewohnen", "berlinovo",
}

SOURCE_META = {
    "gewobag":            ("Gewobag",              "🏛 حكومية"),
    "degewo":             ("Degewo",               "🏛 حكومية"),
    "howoge":             ("Howoge",               "🏛 حكومية"),
    "stadtundland":       ("Stadt und Land",        "🏛 حكومية"),
    "deutschewohnen":     ("Deutsche Wohnen",       "🏛 حكومية"),
    "berlinovo":          ("Berlinovo",             "🏛 حكومية"),
    "immoscout":          ("ImmobilienScout24",     "🔍 خاصة"),
    "wggesucht":          ("WG-Gesucht",            "🔍 خاصة"),
    "ebay_kleinanzeigen": ("Kleinanzeigen",         "🔍 خاصة"),
    "immowelt":           ("Immowelt",              "🔍 خاصة"),
}

SCORE_BADGES = {
    (22, 99): "🔥 ممتاز",
    (15, 21): "⭐⭐ جيد جداً",
    (8,  14): "⭐ جيد",
    (0,   7): "📋 عادي",
}

FEATURE_ICONS = {
    "بلكونة":       "🌿",
    "تراس":         "🌿",
    "حديقة":        "🌱",
    "مصعد":         "🛗",
    "مطبخ مجهز":    "🍳",
    "مخزن":         "📦",
    "موقف سيارة":   "🚗",
    "بدون عوائق":   "♿",
    "بناء جديد":    "🏗",
    "أول سكن":      "✨",
}


def _score_badge(score: int) -> str:
    for (lo, hi), label in SCORE_BADGES.items():
        if lo <= score <= hi:
            return label
    return "📋 عادي"


def _fmt_field(label: str, value, unit: str = "") -> str:
    """Return a formatted field line or empty string if value is None/empty."""
    if value is None or value == "" or value == []:
        return ""
    return f"{label}{value}{unit}\n"


def _safe_title(title: str, max_len: int = 55) -> str:
    title = (title or "شقة للإيجار").strip()
    # Escape Markdown special chars
    for ch in ["_", "*", "[", "]", "`"]:
        title = title.replace(ch, "\\" + ch)
    return title[:max_len] + ("…" if len(title) > max_len else "")


# ── Main formatter ────────────────────────────────────────────────────────────

def format_listing(listing: dict) -> tuple[str, InlineKeyboardMarkup]:
    """
    Returns (message_text, InlineKeyboardMarkup).
    Company name shown first. Apply button separate from view button.
    All fields validated — no errors on missing data.
    """
    source = listing.get("source", "")
    src_name, src_type = SOURCE_META.get(source, (source.title(), "🔍 خاصة"))
    score     = listing.get("score", 0)
    badge     = _score_badge(score)
    is_urgent = listing.get("is_urgent", False)

    # ── Price formatting ──────────────────────────────────────────────────────
    price = listing.get("price")
    if price and isinstance(price, (int, float)):
        price_str = f"{price:,.0f} €".replace(",", ".")
    else:
        price_str = "غير محدد"

    ppm2 = listing.get("price_per_m2")
    ppm2_str = f"  *(≈ {ppm2} €/م²)*" if ppm2 else ""

    # ── Rooms formatting ──────────────────────────────────────────────────────
    rooms = listing.get("rooms")
    if rooms is not None:
        rooms_str = str(int(rooms)) if rooms == int(rooms) else str(rooms)
    else:
        rooms_str = "غير محدد"

    # ── Size ──────────────────────────────────────────────────────────────────
    size = listing.get("size_m2")
    size_str = f"{size:.0f} م²" if size else None

    # ── Location ──────────────────────────────────────────────────────────────
    location = (
        listing.get("district")
        or listing.get("location")
        or "Berlin"
    ).strip()

    # ── Features ──────────────────────────────────────────────────────────────
    features = listing.get("features") or []
    if features:
        feat_parts = [f"{FEATURE_ICONS.get(f, '•')} {f}" for f in features]
        feat_line  = "  ".join(feat_parts)
    else:
        feat_line = None

    # ── Summary ───────────────────────────────────────────────────────────────
    summary = listing.get("summary_ar", "").strip()

    # ── Build message ─────────────────────────────────────────────────────────
    urgent_header = "🔥 *متاح فوراً — تصرف الآن\\!*\n" if is_urgent else ""

    lines = [
        urgent_header,
        f"🏢 *{src_name}* — {src_type}\n",
        f"━━━━━━━━━━━━━━━━━━━━\n",
        f"📌 *{_safe_title(listing.get('title', ''))}*\n",
    ]

    # Summary line from AI
    if summary:
        lines.append(f"💬 _{summary}_\n")

    lines.append("\n")

    # Core fields — only shown if value exists
    lines.append(_fmt_field("📍 الموقع:      ", location))
    lines.append(_fmt_field("💰 الإيجار:     ", price_str + ppm2_str))
    lines.append(_fmt_field("🛏 الغرف:       ", rooms_str))
    lines.append(_fmt_field("📐 المساحة:     ", size_str))
    lines.append(_fmt_field("🏢 الطابق:      ", listing.get("floor")))
    lines.append(_fmt_field("📅 الإتاحة:     ", listing.get("available_from")))
    lines.append(_fmt_field("🏷 المميزات:    ", feat_line))
    lines.append(f"📋 WBS 100:    ✅ مطلوب\n")
    lines.append(f"🎯 التقييم:    {badge}\n")

    text = "".join(lines).strip()

    # ── Inline keyboard — view + apply buttons ────────────────────────────────
    view_url  = listing.get("url", "")
    apply_url = listing.get("apply_url", "")

    buttons = []
    if view_url:
        buttons.append(InlineKeyboardButton("🔍 عرض الإعلان", url=view_url))
    if apply_url and apply_url != view_url:
        buttons.append(InlineKeyboardButton("📝 تقدم الآن", url=apply_url))

    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None

    return text, keyboard


# ── App builder ───────────────────────────────────────────────────────────────

def build_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("status",       cmd_status))
    app.add_handler(CommandHandler("stats",        cmd_stats))
    app.add_handler(CommandHandler("set_price",    cmd_set_price))
    app.add_handler(CommandHandler("set_rooms",    cmd_set_rooms))
    app.add_handler(CommandHandler("set_area",     cmd_set_area))
    app.add_handler(CommandHandler("on",           cmd_on))
    app.add_handler(CommandHandler("off",          cmd_off))
    app.add_handler(CommandHandler("check",        cmd_check))
    app.add_handler(CommandHandler("check_proxy",  cmd_check_proxy))
    return app
