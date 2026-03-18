"""
Telegram bot — professional Arabic UI.
Company name first · AI summary · Dual inline buttons · /last command.
"""
import logging
import os
from datetime import datetime

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand,
)
from telegram.ext import (
    ContextTypes, CommandHandler,
    ApplicationBuilder, Application,
)
from telegram.constants import ParseMode

from database import (
    get_settings, upsert_settings,
    get_all_health, get_stats, get_recent_listings,
)
from filters.wbs_filter import is_wbs
from config.settings import CHAT_ID, BOT_TOKEN, SCRAPER_API_KEY

logger = logging.getLogger(__name__)

# ── Commands registered in Telegram menu ─────────────────────────────────────
BOT_COMMANDS = [
    BotCommand("start",        "تشغيل البوت وعرض المساعدة"),
    BotCommand("status",       "الحالة الحالية والإعدادات"),
    BotCommand("stats",        "إحصائيات البوت"),
    BotCommand("last",         "آخر 5 إعلانات تم رصدها"),
    BotCommand("check",        "صحة جميع المصادر"),
    BotCommand("check_proxy",  "اختبار ScraperAPI"),
    BotCommand("set_price",    "أقصى إيجار — مثال: /set_price 550"),
    BotCommand("set_rooms",    "أقل غرف — مثال: /set_rooms 2"),
    BotCommand("set_area",     "تحديد الحي — مثال: /set_area Spandau"),
    BotCommand("wbs_on",       "البحث عن شقق WBS فقط ✅"),
    BotCommand("wbs_off",      "البحث عن كل الشقق بدون قيد WBS"),
    BotCommand("on",           "تشغيل الإشعارات"),
    BotCommand("off",          "إيقاف الإشعارات"),
]


# ── Access guard ──────────────────────────────────────────────────────────────

def _is_owner(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CHAT_ID)

async def _deny(update: Update) -> None:
    await update.message.reply_text("⛔ غير مصرح.")


# ── Helper ────────────────────────────────────────────────────────────────────

def _time_ago(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt   = datetime.fromisoformat(iso)
        diff = int((datetime.utcnow() - dt).total_seconds())
        if diff < 60:       return f"منذ {diff} ث"
        elif diff < 3600:   return f"منذ {diff // 60} د"
        elif diff < 86400:  return f"منذ {diff // 3600} س"
        else:               return f"منذ {diff // 86400} يوم"
    except Exception:
        return "—"


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=1)
    text = (
        "🏠 *بوت شقق WBS برلين*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "أراقب أكثر من *10 مواقع* كل دقيقتين وأرسل لك "
        "كل شقة WBS جديدة مع تحليل ذكي كامل.\n\n"
        "📋 *الأوامر:*\n"
        "├ /status — الحالة والإعدادات\n"
        "├ /stats — إحصائيات البوت\n"
        "├ /last — آخر 5 إعلانات\n"
        "├ /check — صحة المصادر\n"
        "├ /check\\_proxy — اختبار ScraperAPI\n"
        "├ /set\\_price 550 — أقصى إيجار\n"
        "├ /set\\_rooms 2 — أقل غرف\n"
        "├ /set\\_area Spandau — تحديد الحي\n"
        "├ /wbs\\_on — شقق WBS فقط ✅\n"
        "├ /wbs\\_off — كل الشقق بدون قيد WBS\n"
        "├ /on و /off — تشغيل/إيقاف الإشعارات\n"
        "└ /help — هذه الرسالة\n\n"
        "✅ *البوت يعمل — يبحث كل 2 دقيقة*"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s        = await get_settings(str(update.effective_chat.id))
    ai       = "✅ مفعّل" if os.getenv("ANTHROPIC_API_KEY") else "⚠️ غير مفعّل"
    proxy    = "✅ مفعّل" if SCRAPER_API_KEY else "⚠️ غير مفعّل"
    active   = "🟢 يعمل" if s.get("active") else "🔴 موقوف"
    wbs_mode = "✅ WBS فقط" if s.get("wbs_only", 1) else "🔓 كل الشقق"
    area     = s.get("area") or "كل برلين"
    rooms    = s.get("min_rooms") or "أي عدد"
    await update.message.reply_text(
        "📊 *الإعدادات الحالية*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔔 الإشعارات:    {active}\n"
        f"🏠 وضع البحث:    {wbs_mode}\n"
        f"💰 أقصى إيجار:  {s.get('max_price', 600)} €\n"
        f"🛏 أقل غرف:     {rooms}\n"
        f"📍 المنطقة:      {area}\n"
        f"🤖 الذكاء:       {ai}\n"
        f"🌐 ScraperAPI:   {proxy}\n\n"
        "_لتغيير وضع البحث: /wbs\\_on أو /wbs\\_off_",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /stats ────────────────────────────────────────────────────────────────────

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    st = await get_stats()
    await update.message.reply_text(
        "📈 *إحصائيات البوت*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📨 إشعارات مُرسلة:   {st.get('total_sent', 0)}\n"
        f"🔄 دورات كشط:       {st.get('total_cycles', 0)}\n"
        f"🗃 إعلانات محفوظة:  {st.get('db_size', 0)}\n"
        f"🕐 آخر إشعار:       {_time_ago(st.get('last_sent_at'))}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /last ─────────────────────────────────────────────────────────────────────

SOURCE_LABELS = {
    "gewobag":            "Gewobag 🏛",
    "degewo":             "Degewo 🏛",
    "howoge":             "Howoge 🏛",
    "stadtundland":       "Stadt und Land 🏛",
    "deutschewohnen":     "Deutsche Wohnen 🏛",
    "berlinovo":          "Berlinovo 🏛",
    "immoscout":          "IS24",
    "wggesucht":          "WG-Gesucht",
    "ebay_kleinanzeigen": "Kleinanzeigen",
    "immowelt":           "Immowelt",
}


async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    n = 5
    if context.args:
        try:
            n = min(int(context.args[0]), 10)
        except ValueError:
            pass

    rows = await get_recent_listings(n)
    if not rows:
        await update.message.reply_text("📭 لا توجد إعلانات محفوظة بعد.")
        return

    lines = [f"🕐 *آخر {n} إعلانات تم رصدها*\n━━━━━━━━━━━━━━━━━━━━\n"]
    for i, r in enumerate(rows, 1):
        price = f"{r['price']:.0f} €" if r.get("price") else "—"
        rooms = str(r["rooms"]) if r.get("rooms") else "—"
        src   = SOURCE_LABELS.get(r.get("source",""), r.get("source",""))
        title = (r.get("title") or "شقة").strip()[:40]
        ago   = _time_ago(r.get("created_at"))
        url   = r.get("url","")
        lines.append(
            f"*{i}.* [{title}]({url})\n"
            f"   💰 {price} · 🛏 {rooms} · {src} · {ago}\n"
        )

    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


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
        await update.message.reply_text("❌ رقم غير صحيح.")


async def cmd_set_area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if not context.args:
        await update.message.reply_text("مثال: /set_area Spandau"); return
    area = " ".join(context.args)
    await upsert_settings(str(update.effective_chat.id), area=area)
    await update.message.reply_text(
        f"✅ المنطقة: *{area}*", parse_mode=ParseMode.MARKDOWN)


# ── /wbs_on / /wbs_off ───────────────────────────────────────────────────────

async def cmd_wbs_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), wbs_only=1)
    await update.message.reply_text(
        "✅ *وضع WBS فقط مفعّل*\n\n"
        "سأرسل فقط الشقق التي تتطلب WBS 100.\n"
        "لعرض كل الشقق: /wbs\\_off",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_wbs_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), wbs_only=0)
    await update.message.reply_text(
        "🔓 *وضع كل الشقق مفعّل*\n\n"
        "سأرسل جميع الشقق المتاحة بغض النظر عن WBS.\n\n"
        "⚠️ _ستزيد الإشعارات بشكل كبير._\n"
        "للعودة لـ WBS فقط: /wbs\\_on",
        parse_mode=ParseMode.MARKDOWN,
    )


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

ALL_SOURCES = list(SOURCE_LABELS.keys())
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


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await update.message.reply_text("🔍 جاري الفحص…")
    hmap = {r["source"]: r for r in await get_all_health()}

    ok, err, never = [], [], []
    for src in ALL_SOURCES:
        lbl = SOURCE_ARABIC.get(src, src)
        row = hmap.get(src)
        if not row:
            never.append(f"⚪ {lbl}")
        elif row.get("status") == "ok":
            ok.append(
                f"✅ *{lbl}*  `{row.get('listings_found',0)}` · {_time_ago(row.get('last_run'))}"
            )
        else:
            ok.append(
                f"❌ *{lbl}*  `{str(row.get('last_error',''))[:50]}`"
            )

    lines = ["📊 *حالة المصادر*\n━━━━━━━━━━━━━━━━━━━━\n"]
    lines += ok
    if never:
        lines += ["\n⚪ *لم تعمل بعد:* " + " · ".join(never)]
    lines.append(f"\n📈 *{len(ok)}/{len(ALL_SOURCES)}* مصدر يعمل")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


# ── /check_proxy ──────────────────────────────────────────────────────────────

async def cmd_check_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if not SCRAPER_API_KEY:
        await update.message.reply_text(
            "⚠️ *ScraperAPI غير مفعّل*\n"
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
        await update.message.reply_text(f"❌ {e}")


# ── Listing formatter ─────────────────────────────────────────────────────────

GOV_SOURCES = {
    "gewobag","degewo","howoge",
    "stadtundland","deutschewohnen","berlinovo",
}

SOURCE_META = {
    "gewobag":            ("Gewobag",          "🏛 حكومية"),
    "degewo":             ("Degewo",           "🏛 حكومية"),
    "howoge":             ("Howoge",           "🏛 حكومية"),
    "stadtundland":       ("Stadt und Land",   "🏛 حكومية"),
    "deutschewohnen":     ("Deutsche Wohnen",  "🏛 حكومية"),
    "berlinovo":          ("Berlinovo",        "🏛 حكومية"),
    "immoscout":          ("ImmobilienScout24","🔍 خاصة"),
    "wggesucht":          ("WG-Gesucht",       "🔍 خاصة"),
    "ebay_kleinanzeigen": ("Kleinanzeigen",    "🔍 خاصة"),
    "immowelt":           ("Immowelt",         "🔍 خاصة"),
}

FEATURE_ICONS = {
    "بلكونة":"🌿","تراس":"🌿","حديقة":"🌱",
    "مصعد":"🛗","مطبخ مجهز":"🍳","مخزن":"📦",
    "موقف سيارة":"🚗","بدون عوائق":"♿",
    "بناء جديد":"🏗","أول سكن":"✨",
    "غسالة":"🫧","حمام إضافي":"🚿",
}

_SCORE_BADGES = [(22,"🔥 ممتاز"),(15,"⭐⭐ جيد جداً"),(8,"⭐ جيد"),(0,"📋 عادي")]


def _badge(score: int) -> str:
    for lo, label in _SCORE_BADGES:
        if score >= lo:
            return label
    return "📋 عادي"


def _escape(text: str) -> str:
    """Escape Markdown V1 special characters in plain text."""
    for ch in ["_", "*", "`", "["]:
        text = text.replace(ch, f"\\{ch}")
    return text


def _row(icon: str, label: str, value) -> str:
    if value is None or value == "" or value == []:
        return ""
    return f"{icon} {label:<12}{value}\n"


def format_listing(listing: dict) -> tuple[str, InlineKeyboardMarkup | None]:
    source           = listing.get("source", "")
    src_name, src_type = SOURCE_META.get(source, (source.title(), "🔍 خاصة"))
    score            = listing.get("score", 0)
    is_urgent        = listing.get("is_urgent", False)

    # ── Price ─────────────────────────────────────────────────────────────────
    price  = listing.get("price")
    p_str  = f"{price:,.0f} €".replace(",", ".") if isinstance(price, (int, float)) else "غير محدد"
    ppm2   = listing.get("price_per_m2")
    p_str += f"  *(≈ {ppm2} €/م²)*" if ppm2 else ""

    # ── Rooms ─────────────────────────────────────────────────────────────────
    rooms = listing.get("rooms")
    r_str = (str(int(rooms)) if rooms == int(rooms) else str(rooms)) if rooms else "غير محدد"

    # ── Size ──────────────────────────────────────────────────────────────────
    size  = listing.get("size_m2")
    s_str = f"{size:.0f} م²" if size else None

    # ── Location ──────────────────────────────────────────────────────────────
    loc = (listing.get("district") or listing.get("location") or "Berlin").strip()

    # ── Features ──────────────────────────────────────────────────────────────
    features  = listing.get("features") or []
    feat_line = "  ".join(f"{FEATURE_ICONS.get(f,'•')} {f}" for f in features) if features else None

    # ── Title ─────────────────────────────────────────────────────────────────
    title   = _escape((listing.get("title") or "شقة للإيجار").strip()[:55])
    summary = listing.get("summary_ar", "").strip()

    # ── Build ─────────────────────────────────────────────────────────────────
    urgent = "🔥 *متاح فوراً — تصرف الآن\\!*\n" if is_urgent else ""

    msg = (
        f"{urgent}"
        f"🏢 *{src_name}* — {src_type}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 *{title}*\n"
    )
    if summary:
        msg += f"💬 _{_escape(summary)}_\n"

    msg += "\n"
    msg += _row("📍", "الموقع:",      loc)
    msg += _row("💰", "الإيجار:",     p_str)
    msg += _row("🛏", "الغرف:",       r_str)
    msg += _row("📐", "المساحة:",     s_str)
    msg += _row("🏢", "الطابق:",      listing.get("floor"))
    msg += _row("📅", "الإتاحة:",     listing.get("available_from"))
    msg += _row("🏷", "المميزات:",    feat_line)

    # WBS badge — show clearly whether listing requires WBS or not
    has_wbs = listing.get("trusted_wbs") or listing.get("wbs_label") or is_wbs(listing)
    wbs_line = "📋 WBS 100:    ✅ مطلوب\n" if has_wbs else "📋 WBS 100:    ❌ غير مطلوب\n"
    msg += wbs_line
    msg += f"🎯 التقييم:    {_badge(score)}\n"

    # ── Buttons ───────────────────────────────────────────────────────────────
    view_url  = listing.get("url", "")
    apply_url = listing.get("apply_url", "")

    buttons = []
    if view_url:
        buttons.append(InlineKeyboardButton("🔍 عرض الإعلان", url=view_url))
    if apply_url and apply_url != view_url:
        buttons.append(InlineKeyboardButton("📝 تقدم الآن", url=apply_url))

    keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
    return msg.strip(), keyboard


# ── App builder ───────────────────────────────────────────────────────────────

def build_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("status",      cmd_status))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("last",        cmd_last))
    app.add_handler(CommandHandler("set_price",   cmd_set_price))
    app.add_handler(CommandHandler("set_rooms",   cmd_set_rooms))
    app.add_handler(CommandHandler("set_area",    cmd_set_area))
    app.add_handler(CommandHandler("on",          cmd_on))
    app.add_handler(CommandHandler("off",         cmd_off))
    app.add_handler(CommandHandler("wbs_on",      cmd_wbs_on))
    app.add_handler(CommandHandler("wbs_off",     cmd_wbs_off))
    app.add_handler(CommandHandler("check",       cmd_check))
    app.add_handler(CommandHandler("check_proxy", cmd_check_proxy))
    return app
