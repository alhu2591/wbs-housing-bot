"""
Telegram bot — Arabic UI with persistent reply keyboard + multi-area filter.
"""
import json
import logging
import os
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
    BotCommand,
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

# ── All Berlin districts ──────────────────────────────────────────────────────
BERLIN_DISTRICTS = [
    "Mitte", "Friedrichshain", "Kreuzberg", "Prenzlauer Berg",
    "Charlottenburg", "Wilmersdorf", "Spandau", "Steglitz",
    "Zehlendorf", "Tempelhof", "Schöneberg", "Neukölln",
    "Treptow", "Köpenick", "Marzahn", "Hellersdorf",
    "Lichtenberg", "Weißensee", "Pankow", "Reinickendorf",
    "Wedding", "Moabit", "Tiergarten",
]

# ── Persistent bottom keyboard ────────────────────────────────────────────────
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📊 الحالة"),      KeyboardButton("📈 الإحصائيات")],
        [KeyboardButton("🗺 المناطق"),      KeyboardButton("🔍 فحص المصادر")],
        [KeyboardButton("✅ WBS فقط"),     KeyboardButton("🔓 كل الشقق")],
        [KeyboardButton("🟢 تشغيل"),       KeyboardButton("🔴 إيقاف")],
    ],
    resize_keyboard=True,
    input_field_placeholder="اختر أمراً أو اكتب /help",
)

# ── Bot commands menu ─────────────────────────────────────────────────────────
BOT_COMMANDS = [
    BotCommand("start",       "تشغيل البوت"),
    BotCommand("status",      "الحالة والإعدادات"),
    BotCommand("stats",       "الإحصائيات"),
    BotCommand("areas",       "إدارة المناطق المفضلة"),
    BotCommand("last",        "آخر 5 إعلانات"),
    BotCommand("check",       "صحة المصادر"),
    BotCommand("set_price",   "أقصى إيجار — مثال: /set_price 550 أو اضغط للخيارات"),
    BotCommand("set_rooms",   "أقل غرف — مثال: /set_rooms 2 أو اضغط للخيارات"),
    BotCommand("wbs_on",      "البحث عن شقق WBS فقط"),
    BotCommand("wbs_off",     "كل الشقق (افتراضي)"),
    BotCommand("on",          "تشغيل الإشعارات"),
    BotCommand("off",         "إيقاف الإشعارات"),
    BotCommand("ping",        "فحص سرعة استجابة البوت"),
    BotCommand("reset",       "إعادة جميع الإعدادات للافتراضي"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_owner(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CHAT_ID)

async def _deny(update: Update) -> None:
    await update.message.reply_text("⛔ غير مصرح.")

def _time_ago(iso: str | None) -> str:
    if not iso: return "—"
    try:
        dt   = datetime.fromisoformat(iso)
        diff = int((datetime.utcnow() - dt).total_seconds())
        if diff < 60:       return f"منذ {diff} ث"
        elif diff < 3600:   return f"منذ {diff // 60} د"
        elif diff < 86400:  return f"منذ {diff // 3600} س"
        else:               return f"منذ {diff // 86400} يوم"
    except Exception:
        return "—"

def _get_areas(settings: dict) -> list[str]:
    try:
        return json.loads(settings.get("areas") or "[]")
    except Exception:
        return []


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=1)
    text = (
        "🏠 *بوت شقق WBS برلين*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "أراقب أكثر من *10 مواقع* كل دقيقتين وأرسل لك "
        "كل شقة جديدة مع تحليل ذكي.\n\n"
        "📋 *الأوامر:*\n"
        "├ /status — الحالة والإعدادات\n"
        "├ /areas — إدارة المناطق المفضلة\n"
        "├ /set\\_price 550 — أقصى إيجار\n"
        "├ /set\\_rooms 2 — أقل غرف\n"
        "├ /wbs\\_on / /wbs\\_off — تبديل فلتر WBS\n"
        "├ /on / /off — تشغيل/إيقاف\n"
        "└ /last — آخر 5 إعلانات\n\n"
        "✅ *البوت يعمل — استخدم الأزرار أدناه*"
    )
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


# ── /status ───────────────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s      = await get_settings(str(update.effective_chat.id))
    areas  = _get_areas(s)
    ai     = "✅" if os.getenv("ANTHROPIC_API_KEY") else "⚠️"
    proxy  = "✅" if SCRAPER_API_KEY else "⚠️"
    active = "🟢 يعمل" if s.get("active") else "🔴 موقوف"
    wbs    = "✅ WBS فقط" if s.get("wbs_only", 0) else "🔓 كل الشقق"
    rooms  = s.get("min_rooms") or "أي عدد"
    areas_str = "، ".join(areas) if areas else "كل برلين 🌍"

    await update.message.reply_text(
        "📊 *الإعدادات الحالية*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔔 الإشعارات:    {active}\n"
        f"🏠 وضع البحث:    {wbs}\n"
        f"💰 أقصى إيجار:  {s.get('max_price', 600)} €\n"
        f"🛏 أقل غرف:     {rooms}\n"
        f"📍 المناطق:      {areas_str}\n"
        f"🤖 الذكاء:       {ai}\n"
        f"🌐 ScraperAPI:   {proxy}\n\n"
        "_/areas لإدارة المناطق_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
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
        reply_markup=MAIN_KEYBOARD,
    )


# ── /areas ────────────────────────────────────────────────────────────────────

def _areas_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    """Build inline keyboard with all districts, ✅ for selected ones."""
    rows = []
    row  = []
    for i, district in enumerate(BERLIN_DISTRICTS):
        mark  = "✅ " if district in selected else ""
        btn   = InlineKeyboardButton(
            f"{mark}{district}",
            callback_data=f"area_toggle:{district}",
        )
        row.append(btn)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # Control buttons
    rows.append([
        InlineKeyboardButton("🌍 كل برلين (إلغاء الكل)", callback_data="area_clear"),
    ])
    rows.append([
        InlineKeyboardButton("✅ حفظ وإغلاق", callback_data="area_done"),
    ])
    return InlineKeyboardMarkup(rows)


async def cmd_areas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s      = await get_settings(str(update.effective_chat.id))
    areas  = _get_areas(s)
    label  = "، ".join(areas) if areas else "كل برلين 🌍"

    await update.message.reply_text(
        f"📍 *اختر المناطق المفضلة*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"المحدّد حالياً: *{label}*\n\n"
        f"اضغط على منطقة لتحديدها أو إلغائها.\n"
        f"إذا لم تحدد شيئاً → يبحث في كل برلين.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_areas_keyboard(areas),
    )


async def callback_area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline button presses for area selection."""
    query = update.callback_query
    await query.answer()

    if not str(query.from_user.id) == str(CHAT_ID):
        return

    chat_id = str(query.message.chat_id)
    s       = await get_settings(chat_id)
    areas   = _get_areas(s)
    data    = query.data

    if data == "area_clear":
        areas = []
    elif data == "area_done":
        label = "، ".join(areas) if areas else "كل برلين 🌍"
        await query.edit_message_text(
            f"✅ *تم الحفظ*\n\n📍 المناطق: *{label}*",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    elif data.startswith("area_toggle:"):
        district = data.split(":", 1)[1]
        if district in areas:
            areas.remove(district)
        else:
            areas.append(district)

    await upsert_settings(chat_id, areas=json.dumps(areas, ensure_ascii=False))

    # Refresh keyboard
    label = "، ".join(areas) if areas else "كل برلين 🌍"
    try:
        await query.edit_message_text(
            f"📍 *اختر المناطق المفضلة*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"المحدّد حالياً: *{label}*\n\n"
            f"اضغط على منطقة لتحديدها أو إلغائها.\n"
            f"إذا لم تحدد شيئاً → يبحث في كل برلين.",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_areas_keyboard(areas),
        )
    except Exception:
        pass  # Message unchanged — Telegram raises error if text identical


async def callback_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle quick-price inline button press."""
    query = update.callback_query
    await query.answer()
    if not str(query.from_user.id) == str(CHAT_ID):
        return
    price = float(query.data.split(":")[1])
    chat_id = str(query.message.chat_id)
    await upsert_settings(chat_id, max_price=price)
    await query.edit_message_text(
        f"✅ *أقصى إيجار: {price:.0f} €*",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /set_price / /set_rooms ───────────────────────────────────────────────────

async def cmd_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if context.args:
        try:
            p = float(context.args[0])
            await upsert_settings(str(update.effective_chat.id), max_price=p)
            await update.message.reply_text(
                f"✅ أقصى إيجار: *{p:.0f} €*",
                parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)
            return
        except ValueError:
            pass
    # No args — show quick-select keyboard
    prices = [400, 450, 500, 550, 600, 650, 700, 800]
    rows = []
    for i in range(0, len(prices), 4):
        rows.append([
            InlineKeyboardButton(f"{p} €", callback_data=f"set_price:{p}")
            for p in prices[i:i+4]
        ])
    await update.message.reply_text(
        "💰 *اختر أقصى إيجار أو أرسل: /set\\_price 550*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def cmd_set_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if context.args:
        try:
            r = float(context.args[0].replace(",", "."))
            await upsert_settings(str(update.effective_chat.id), min_rooms=r)
            await update.message.reply_text(
                f"✅ أقل غرف: *{r}*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=MAIN_KEYBOARD,
            )
            return
        except ValueError:
            pass
    # No args — show quick-select keyboard
    room_opts = [1, 1.5, 2, 2.5, 3, 3.5, 4, 5]
    rows = []
    for i in range(0, len(room_opts), 4):
        rows.append([
            InlineKeyboardButton(f"{r} غرف", callback_data=f"set_rooms:{r}")
            for r in room_opts[i:i+4]
        ])
    rows.append([InlineKeyboardButton("🔓 أي عدد غرف", callback_data="set_rooms:0")])
    await update.message.reply_text(
        "🛏 *اختر أقل عدد غرف أو أرسل: /set\\_rooms 2*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def callback_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if str(query.from_user.id) != str(CHAT_ID):
        return
    rooms = float(query.data.split(":")[1])
    await upsert_settings(str(query.message.chat_id), min_rooms=rooms)
    label = f"{rooms} غرف" if rooms > 0 else "أي عدد غرف"
    await query.edit_message_text(
        f"✅ *أقل غرف: {label}*",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /on / /off ────────────────────────────────────────────────────────────────

async def cmd_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=1)
    await update.message.reply_text(
        "🟢 *الإشعارات شغّالة*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )

async def cmd_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=0)
    await update.message.reply_text(
        "🔴 *الإشعارات موقوفة*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )


# ── /wbs_on / /wbs_off ────────────────────────────────────────────────────────

async def cmd_wbs_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), wbs_only=1)
    await update.message.reply_text(
        "✅ *WBS فقط* — سأرسل فقط الشقق التي تتطلب WBS.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )

async def cmd_wbs_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), wbs_only=0)
    await update.message.reply_text(
        "🔓 *كل الشقق* \\(الوضع الافتراضي\\) — سأرسل جميع الشقق.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )


# ── /last ─────────────────────────────────────────────────────────────────────

SOURCE_LABELS = {
    "gewobag":"Gewobag 🏛","degewo":"Degewo 🏛","howoge":"Howoge 🏛",
    "stadtundland":"Stadt und Land 🏛","deutschewohnen":"Deutsche Wohnen 🏛",
    "berlinovo":"Berlinovo 🏛","immoscout":"IS24","wggesucht":"WG-Gesucht",
    "ebay_kleinanzeigen":"Kleinanzeigen","immowelt":"Immowelt",
}

async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    n = 5
    if context.args:
        try: n = min(int(context.args[0]), 10)
        except ValueError: pass
    rows = await get_recent_listings(n)
    if not rows:
        await update.message.reply_text("📭 لا توجد إعلانات محفوظة بعد.", reply_markup=MAIN_KEYBOARD); return
    lines = [f"🕐 *آخر {n} إعلانات*\n━━━━━━━━━━━━━━━━━━━━\n"]
    for i, r in enumerate(rows, 1):
        price = f"{r['price']:.0f} €" if r.get("price") else "—"
        rooms = str(r["rooms"]) if r.get("rooms") else "—"
        src   = SOURCE_LABELS.get(r.get("source",""), r.get("source",""))
        title = (r.get("title") or "شقة").strip()[:40]
        ago   = _time_ago(r.get("created_at"))
        url   = r.get("url","")
        lines.append(f"*{i}.* [{title}]({url})\n   💰 {price} · 🛏 {rooms} · {src} · {ago}\n")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
        reply_markup=MAIN_KEYBOARD,
    )


# ── /check ────────────────────────────────────────────────────────────────────

ALL_SOURCES = list(SOURCE_LABELS.keys())
SOURCE_ARABIC = {
    "gewobag":"Gewobag 🏛","degewo":"Degewo 🏛","howoge":"Howoge 🏛",
    "stadtundland":"Stadt und Land 🏛","deutschewohnen":"Deutsche Wohnen 🏛",
    "berlinovo":"Berlinovo 🏛","immoscout":"ImmobilienScout24",
    "wggesucht":"WG-Gesucht","ebay_kleinanzeigen":"Kleinanzeigen","immowelt":"Immowelt",
}

async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await update.message.reply_text("🔍 جاري الفحص…", reply_markup=MAIN_KEYBOARD)
    hmap = {r["source"]: r for r in await get_all_health()}
    ok, never = [], []
    for src in ALL_SOURCES:
        lbl = SOURCE_ARABIC.get(src, src)
        row = hmap.get(src)
        if not row:
            never.append(f"⚪ {lbl}")
        elif row.get("status") == "ok":
            ok.append(f"✅ *{lbl}*  `{row.get('listings_found',0)}` · {_time_ago(row.get('last_run'))}")
        else:
            ok.append(f"❌ *{lbl}*  `{str(row.get('last_error',''))[:50]}`")
    lines = ["📊 *حالة المصادر*\n━━━━━━━━━━━━━━━━━━━━\n"] + ok
    if never:
        lines += ["\n⚪ *لم تعمل بعد:* " + " · ".join(never)]
    lines.append(f"\n📈 *{len(ok)}/{len(ALL_SOURCES)}* مصدر يعمل")
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )


# ── /check_proxy ──────────────────────────────────────────────────────────────

async def cmd_check_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if not SCRAPER_API_KEY:
        await update.message.reply_text(
            "⚠️ *ScraperAPI غير مفعّل*\nRailway → Variables → `SCRAPER_API_KEY`",
            parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD); return
    await update.message.reply_text("🔍 جاري الاختبار…", reply_markup=MAIN_KEYBOARD)
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
                parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)
        else:
            await update.message.reply_text(f"❌ HTTP {r.status_code}", reply_markup=MAIN_KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=MAIN_KEYBOARD)


# ── Reply keyboard handler ────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Map persistent button text to commands."""
    text = update.message.text
    mapping = {
        "📊 الحالة":       cmd_status,
        "📈 الإحصائيات":   cmd_stats,
        "🗺 المناطق":       cmd_areas,
        "🔍 فحص المصادر":  cmd_check,
        "✅ WBS فقط":      cmd_wbs_on,
        "🔓 كل الشقق":     cmd_wbs_off,
        "🟢 تشغيل":        cmd_on,
        "🔴 إيقاف":        cmd_off,
    }
    fn = mapping.get(text)
    if fn:
        await fn(update, context)


# ── Notification formatter ────────────────────────────────────────────────────

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
    "بلكونة":"🌿","تراس":"🌿","حديقة":"🌱","مصعد":"🛗",
    "مطبخ مجهز":"🍳","مخزن":"📦","موقف سيارة":"🚗",
    "بدون عوائق":"♿","بناء جديد":"🏗","أول سكن":"✨",
}


def _escape(text: str) -> str:
    for ch in ["_", "*", "`", "["]:
        text = text.replace(ch, f"\\{ch}")
    return text


def format_listing(listing: dict) -> tuple[str, InlineKeyboardMarkup | None]:
    source             = listing.get("source", "")
    src_name, src_type = SOURCE_META.get(source, (source.title(), "🔍 خاصة"))

    # Price
    price = listing.get("price")
    p_str = f"{price:,.0f} €".replace(",", ".") if isinstance(price, (int, float)) else None
    ppm2  = listing.get("price_per_m2")
    if p_str and ppm2:
        p_str += f"  *(≈ {ppm2} €/م²)*"

    # Rooms
    rooms = listing.get("rooms")
    r_str = (str(int(rooms)) if rooms == int(rooms) else str(rooms)) if rooms else None

    # Size
    size  = listing.get("size_m2")
    s_str = f"{size:.0f} م²" if size else None

    # Location
    loc = (listing.get("district") or listing.get("location") or "Berlin").strip()

    # WBS
    wbs_level = listing.get("wbs_level")
    wbs_line  = f"📋 WBS:         ✅ مطلوب {wbs_level}" if wbs_level else "📋 WBS:         ❌ غير مطلوب"

    # Build
    lines = [f"🏢 *{src_name}* — {src_type}\n"]
    if loc:              lines.append(f"📍 الموقع:      {loc}")
    if p_str:            lines.append(f"💰 الإيجار:     {p_str}")
    if r_str:            lines.append(f"🛏 الغرف:       {r_str}")
    if s_str:            lines.append(f"📐 المساحة:     {s_str}")
    if listing.get("floor"):          lines.append(f"🏢 الطابق:      {listing['floor']}")
    if listing.get("available_from"): lines.append(f"📅 الإتاحة:     {listing['available_from']}")
    lines.append(wbs_line)

    msg = "\n".join(lines).strip()
    if len(msg) > 1020:
        msg = msg[:1017] + "…"

    # Buttons — each on its own row
    view_url  = listing.get("url", "")
    apply_url = listing.get("apply_url", "")
    rows = []
    if view_url:
        rows.append([InlineKeyboardButton("🔍 عرض الإعلان", url=view_url)])
    if apply_url and apply_url != view_url:
        rows.append([InlineKeyboardButton("📝 تقدم الآن", url=apply_url)])

    return msg, InlineKeyboardMarkup(rows) if rows else None


# ── /ping ─────────────────────────────────────────────────────────────────────

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    import time
    t0 = time.monotonic()
    msg = await update.message.reply_text("🏓 ...")
    latency = (time.monotonic() - t0) * 1000
    from scheduler.runner import _cycle as cycle_count
    await msg.edit_text(
        f"🏓 *Pong\\!*\n⚡ الاستجابة: `{latency:.0f}ms`\n🔄 دورات: `{cycle_count}`",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /reset ────────────────────────────────────────────────────────────────────

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(
        str(update.effective_chat.id),
        active=1, max_price=600, min_rooms=0,
        area="", wbs_only=0, areas="[]",
    )
    await update.message.reply_text(
        "🔄 *تم إعادة جميع الإعدادات للافتراضي*\n\n"
        "💰 أقصى إيجار: 600 €\n"
        "🛏 أقل غرف: أي عدد\n"
        "📍 المناطق: كل برلين\n"
        "🏠 الوضع: كل الشقق\n"
        "🔔 الإشعارات: شغّالة",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )


# ── App builder ───────────────────────────────────────────────────────────────

def build_app() -> Application:
    from telegram.ext import CallbackQueryHandler, MessageHandler, filters

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("help",         cmd_help))
    app.add_handler(CommandHandler("status",       cmd_status))
    app.add_handler(CommandHandler("stats",        cmd_stats))
    app.add_handler(CommandHandler("areas",        cmd_areas))
    app.add_handler(CommandHandler("last",         cmd_last))
    app.add_handler(CommandHandler("set_price",    cmd_set_price))
    app.add_handler(CommandHandler("set_rooms",    cmd_set_rooms))
    app.add_handler(CommandHandler("wbs_on",       cmd_wbs_on))
    app.add_handler(CommandHandler("wbs_off",      cmd_wbs_off))
    app.add_handler(CommandHandler("on",           cmd_on))
    app.add_handler(CommandHandler("off",          cmd_off))
    app.add_handler(CommandHandler("check",        cmd_check))
    app.add_handler(CommandHandler("check_proxy",  cmd_check_proxy))
    app.add_handler(CommandHandler("ping",         cmd_ping))
    app.add_handler(CommandHandler("reset",        cmd_reset))
    # Inline callbacks
    app.add_handler(CallbackQueryHandler(callback_area,  pattern="^area_"))
    app.add_handler(CallbackQueryHandler(callback_price, pattern="^set_price:"))
    app.add_handler(CallbackQueryHandler(callback_rooms, pattern="^set_rooms:"))
    # Persistent reply keyboard
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app
