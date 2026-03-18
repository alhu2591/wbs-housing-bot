"""
Telegram bot — professional Arabic UI with inline buttons and smart formatting.
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
        "أراقب أكثر من *10 مواقع* كل دقيقتين وأرسل لك "
        "فوراً كل شقة WBS جديدة في برلين.\n\n"
        "⚙️ *الأوامر:*\n"
        "├ /status — الحالة والإعدادات\n"
        "├ /stats — إحصائيات البوت\n"
        "├ /check — صحة المصادر\n"
        "├ /check\\_proxy — اختبار ScraperAPI\n"
        "├ /set\\_price 550 — أقصى إيجار\n"
        "├ /set\\_rooms 2 — أقل غرف\n"
        "├ /set\\_area Spandau — حي معين\n"
        "├ /on — تشغيل الإشعارات\n"
        "└ /off — إيقاف الإشعارات\n\n"
        "✅ *البوت يعمل الآن — يبحث كل 2 دقيقة*"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s = await get_settings(str(update.effective_chat.id))
    proxy = "✅ ScraperAPI مفعّل" if SCRAPER_API_KEY else "⚠️ غير مفعّل"
    active = "🟢 يعمل" if s.get("active") else "🔴 موقوف"
    area   = s.get("area") or "كل برلين"
    rooms  = s.get("min_rooms") or "أي عدد"
    text = (
        "📊 *الإعدادات الحالية*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔔 الإشعارات:   {active}\n"
        f"💰 أقصى إيجار: {s.get('max_price', 600)} €\n"
        f"🛏 أقل غرف:    {rooms}\n"
        f"📍 المنطقة:     {area}\n"
        f"🌐 ScraperAPI:  {proxy}"
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
        f"📨 إشعارات مُرسلة:    {st.get('total_sent', 0)}\n"
        f"🔄 دورات كشط:        {st.get('total_cycles', 0)}\n"
        f"🗃 إعلانات في DB:    {st.get('db_size', 0)}\n"
        f"🕐 آخر إشعار:        {last_str}"
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
        await update.message.reply_text(f"✅ أقصى إيجار: *{p:.0f} €*", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await update.message.reply_text("❌ رقم غير صحيح. مثال: /set_price 550")


async def cmd_set_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if not context.args:
        await update.message.reply_text("مثال: /set_rooms 2"); return
    try:
        r = float(context.args[0])
        await upsert_settings(str(update.effective_chat.id), min_rooms=r)
        await update.message.reply_text(f"✅ أقل عدد غرف: *{r}*", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await update.message.reply_text("❌ رقم غير صحيح. مثال: /set_rooms 2")


async def cmd_set_area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if not context.args:
        await update.message.reply_text("مثال: /set_area Spandau"); return
    area = " ".join(context.args)
    await upsert_settings(str(update.effective_chat.id), area=area)
    await update.message.reply_text(f"✅ المنطقة: *{area}*", parse_mode=ParseMode.MARKDOWN)


# ── /on / /off ────────────────────────────────────────────────────────────────

async def cmd_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=1)
    await update.message.reply_text("🟢 *الإشعارات شغّالة*", parse_mode=ParseMode.MARKDOWN)


async def cmd_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=0)
    await update.message.reply_text("🔴 *الإشعارات موقوفة*", parse_mode=ParseMode.MARKDOWN)


# ── /check ────────────────────────────────────────────────────────────────────

SOURCE_ARABIC = {
    "gewobag":           "Gewobag 🏛",
    "degewo":            "Degewo 🏛",
    "howoge":            "Howoge 🏛",
    "stadtundland":      "Stadt und Land 🏛",
    "deutschewohnen":    "Deutsche Wohnen 🏛",
    "berlinovo":         "Berlinovo 🏛",
    "immoscout":         "ImmobilienScout24",
    "wggesucht":         "WG-Gesucht",
    "ebay_kleinanzeigen":"Kleinanzeigen",
    "immowelt":          "Immowelt",
}
ALL_SOURCES = list(SOURCE_ARABIC.keys())


def _time_ago(iso: str | None) -> str:
    if not iso: return "—"
    try:
        dt = datetime.fromisoformat(iso)
        diff = int((datetime.utcnow() - dt).total_seconds())
        if diff < 60:    return f"منذ {diff} ث"
        elif diff < 3600: return f"منذ {diff // 60} د"
        elif diff < 86400: return f"منذ {diff // 3600} س"
        else:            return f"منذ {diff // 86400} يوم"
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
        row = hmap.get(src)
        if not row:
            never_lines.append(f"⚪ {label}")
            continue
        if row.get("status") == "ok":
            ok_lines.append(
                f"✅ *{label}*  `{row.get('listings_found',0)} إعلان` · {_time_ago(row.get('last_run'))}"
            )
        else:
            err = str(row.get("last_error",""))[:60]
            err_lines.append(
                f"❌ *{label}*\n   └ `{err}`"
            )

    lines = ["📊 *حالة المصادر*\n━━━━━━━━━━━━━━━━━━━━\n"]
    if ok_lines:
        lines += ok_lines
    if err_lines:
        lines += ["\n*❌ أخطاء:*"] + err_lines
    if never_lines:
        lines += ["\n*⚪ لم تعمل بعد:*", "  " + " · ".join(never_lines)]
    lines.append(
        f"\n📈 *{len(ok_lines)}/{len(ALL_SOURCES)}* مصدر يعمل"
    )
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── /check_proxy ──────────────────────────────────────────────────────────────

async def cmd_check_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if not SCRAPER_API_KEY:
        await update.message.reply_text(
            "⚠️ *ScraperAPI غير مفعّل*\n\n"
            "بدونه IPs الـ Railway محجوبة.\n\n"
            "1️⃣ سجّل على scraperapi.com\n"
            "2️⃣ Railway → Variables → `SCRAPER_API_KEY = مفتاحك`",
            parse_mode=ParseMode.MARKDOWN
        ); return
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
                f"✅ *ScraperAPI يعمل*\n🌐 IP المستخدم: `{ip}`",
                parse_mode=ParseMode.MARKDOWN
            )
        else:
            await update.message.reply_text(f"❌ HTTP {r.status_code}")
    except Exception as e:
        await update.message.reply_text(f"❌ خطأ: {e}")


# ── Professional Notification Formatter ──────────────────────────────────────

SOURCE_LABELS = {
    "gewobag":           "Gewobag",
    "degewo":            "Degewo",
    "howoge":            "Howoge",
    "stadtundland":      "Stadt und Land",
    "deutschewohnen":    "Deutsche Wohnen",
    "berlinovo":         "Berlinovo",
    "immoscout":         "ImmobilienScout24",
    "wggesucht":         "WG-Gesucht",
    "ebay_kleinanzeigen":"Kleinanzeigen",
    "immowelt":          "Immowelt",
}

GOV_SOURCES = {
    "gewobag", "degewo", "howoge",
    "stadtundland", "deutschewohnen", "berlinovo",
}


def format_listing(listing: dict) -> tuple[str, InlineKeyboardMarkup]:
    """Returns (message_text, inline_keyboard)."""

    # ── Header ────────────────────────────────────────────────────────────────
    score_label = listing.get("score_label") or "📋 عادي"
    urgent      = listing.get("is_urgent", False)
    urgent_line = "🔥 *متاح فوراً — تصرف الآن!*\n" if urgent else ""
    source      = listing.get("source", "")
    gov_badge   = " 🏛" if source in GOV_SOURCES else ""
    source_name = SOURCE_LABELS.get(source, source)

    # ── Core fields ───────────────────────────────────────────────────────────
    price    = f"{listing['price']:.0f} €" if listing.get("price") else "غير محدد"
    rooms    = str(int(listing["rooms"]) if listing.get("rooms") and listing["rooms"] == int(listing["rooms"])
                   else listing["rooms"]) if listing.get("rooms") else "غير محدد"
    location = listing.get("location") or "Berlin"
    title    = (listing.get("title") or "شقة للإيجار")[:60]

    # ── Optional enriched fields ──────────────────────────────────────────────
    size_line  = f"📐 المساحة:    {listing['size_m2']:.0f} m²\n" if listing.get("size_m2") else ""
    floor_line = f"🏢 الطابق:     {listing['floor']}\n"          if listing.get("floor") else ""
    avail_line = f"📅 الإتاحة:    {listing['available_from']}\n"  if listing.get("available_from") else ""
    ppm2_line  = f"💹 السعر/م²:   {listing['price_per_m2']} €\n"  if listing.get("price_per_m2") else ""

    # ── Features ──────────────────────────────────────────────────────────────
    features = listing.get("features") or []
    feat_line = "🏷 " + "  ".join(features) + "\n" if features else ""

    # ── Build message ─────────────────────────────────────────────────────────
    text = (
        f"{urgent_line}"
        f"🏠 *شقة WBS جديدة* — {score_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 *{title}*\n\n"
        f"📍 الموقع:     {location}\n"
        f"💰 الإيجار:    {price}\n"
        f"{ppm2_line}"
        f"🛏 الغرف:      {rooms}\n"
        f"{size_line}"
        f"{floor_line}"
        f"{avail_line}"
        f"{feat_line}"
        f"🏢 المصدر:     {source_name}{gov_badge}\n"
        f"📋 WBS 100:   ✅ مطلوب\n"
    )

    # ── Inline button ─────────────────────────────────────────────────────────
    url = listing.get("url", "")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 عرض الشقة", url=url)]
    ]) if url else None

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
