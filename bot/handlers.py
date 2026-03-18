"""
Telegram bot — Arabic UI with persistent reply keyboard + multi-area filter.
"""
import json
import logging
import os
import time as _time
from datetime import datetime, timezone

_BOT_START = _time.monotonic()
_BOT_START_DT = datetime.now(timezone.utc)

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
from filters.social_filter import (
    JOBCENTER_KDU_WARMMIETE, WOHNGELD_RENT_LIMITS,
    get_jobcenter_limit, get_wohngeld_limit, get_size_limit,
)
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
    BotCommand("social",      "إعدادات Jobcenter / Wohngeld"),
    BotCommand("household",   "تحديد عدد أفراد الأسرة"),
    BotCommand("on",          "تشغيل الإشعارات"),
    BotCommand("off",         "إيقاف الإشعارات"),
    BotCommand("ping",        "فحص سرعة استجابة البوت"),
    BotCommand("uptime",      "مدة تشغيل البوت والإحصائيات"),
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
        "├ /areas — اختيار المناطق\n"
        "├ /social — فلتر Jobcenter / Wohngeld\n"
        "├ /household — عدد أفراد الأسرة\n"
        "├ /set\\_price — أقصى إيجار\n"
        "├ /set\\_rooms — أقل غرف\n"
        "├ /wbs\\_on / /wbs\\_off — فلتر WBS\n"
        "├ /on / /off — تشغيل/إيقاف\n"
        "├ /stats / /last / /check\n"
        "└ /ping / /reset\n\n"
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
    s         = await get_settings(str(update.effective_chat.id))
    areas     = _get_areas(s)
    ai        = "✅" if os.getenv("ANTHROPIC_API_KEY") else "⚠️"
    proxy     = "✅" if SCRAPER_API_KEY else "⚠️"
    active    = "🟢 يعمل" if s.get("active") else "🔴 موقوف"
    wbs       = "✅ WBS فقط" if s.get("wbs_only", 0) else "🔓 كل الشقق"
    rooms     = s.get("min_rooms") or "أي عدد"
    areas_str = "، ".join(areas) if areas else "كل برلين 🌍"
    n         = int(s.get("household_size") or 1)
    jc_mode   = "✅" if s.get("jobcenter_mode") else "❌"
    wg_mode   = "✅" if s.get("wohngeld_mode")  else "❌"
    jc_lim    = get_jobcenter_limit(n)
    wg_lim    = get_wohngeld_limit(n)
    sz_lim    = get_size_limit(n)

    await update.message.reply_text(
        "📊 *الإعدادات الحالية*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔔 الإشعارات:    {active}\n"
        f"🏠 وضع البحث:    {wbs}\n"
        f"💰 أقصى إيجار:  {s.get('max_price', 600)} €\n"
        f"🛏 أقل غرف:     {rooms}\n"
        f"📍 المناطق:      {areas_str}\n"
        f"👨‍👩‍👧 أفراد الأسرة: {n}\n"
        f"🏛 Jobcenter KdU: {jc_mode} حد {jc_lim:.0f}€ · {sz_lim}م²\n"
        f"🏦 Wohngeld:     {wg_mode} حد {wg_lim:.0f}€\n"
        f"🤖 الذكاء:       {ai}\n"
        f"🌐 ScraperAPI:   {proxy}\n\n"
        "_/social لإدارة Jobcenter/Wohngeld · /household للأفراد_",
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
    from scrapers.circuit_breaker import all_statuses
    hmap   = {r["source"]: r for r in await get_all_health()}
    cb_map = {s["name"]: s for s in all_statuses()}
    ok, never = [], []
    for src in ALL_SOURCES:
        lbl      = SOURCE_ARABIC.get(src, src)
        row      = hmap.get(src)
        cb       = cb_map.get(src, {})
        cb_state = cb.get("state", "CLOSED")
        cb_icon  = {"CLOSED": "🟢", "HALF": "🟡", "OPEN": "🔴"}.get(cb_state, "⚪")
        if not row:
            never.append(f"{cb_icon} {lbl}")
        elif row.get("status") == "ok":
            ok.append(f"✅ *{lbl}*  `{row.get('listings_found',0)}` · {_time_ago(row.get('last_run'))} {cb_icon}")
        else:
            ok.append(f"❌ *{lbl}*  `{str(row.get('last_error',''))[:50]}` {cb_icon}")
    lines = ["📊 *حالة المصادر*\n━━━━━━━━━━━━━━━━━━━━\n"] + ok
    if never:
        lines += ["\n⚪ *لم تعمل بعد:* " + " · ".join(never)]
    lines.append(f"\n📈 *{len(ok)}/{len(ALL_SOURCES)}* مصدر يعمل")
    lines.append("🟢طبيعي · 🟡اختبار · 🔴مغلق مؤقتاً")
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

    # Social badge (Jobcenter / Wohngeld)
    social_badge = listing.get("social_badge", "")

    # Build
    lines = [f"🏢 *{src_name}* — {src_type}\n"]
    if loc:              lines.append(f"📍 الموقع:      {loc}")
    if p_str:            lines.append(f"💰 الإيجار:     {p_str}")
    if r_str:            lines.append(f"🛏 الغرف:       {r_str}")
    if s_str:            lines.append(f"📐 المساحة:     {s_str}")
    if listing.get("floor"):          lines.append(f"🏢 الطابق:      {listing['floor']}")
    if listing.get("available_from"): lines.append(f"📅 الإتاحة:     {listing['available_from']}")
    lines.append(wbs_line)
    if social_badge:     lines.append(social_badge)

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


# ── /household ────────────────────────────────────────────────────────────────

async def cmd_household(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if context.args:
        try:
            n = int(context.args[0])
            assert 1 <= n <= 10
            await upsert_settings(str(update.effective_chat.id), household_size=n)
            jc_lim = get_jobcenter_limit(n)
            wg_lim = get_wohngeld_limit(n)
            sz_lim = get_size_limit(n)
            await update.message.reply_text(
                f"✅ *عدد أفراد الأسرة: {n}*\n\n"
                f"🏛 حد Jobcenter: {jc_lim:.0f} € / {sz_lim} م²\n"
                f"🏦 حد Wohngeld:  {wg_lim:.0f} €",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=MAIN_KEYBOARD,
            )
            return
        except (ValueError, AssertionError):
            pass
    # Show inline keyboard 1–6
    rows = [[
        InlineKeyboardButton(f"{i} فرد{'/' if i==1 else 'أفراد'[0:0]}", callback_data=f"household:{i}")
        for i in range(j, min(j+3, 7))
    ] for j in range(1, 7, 3)]
    # Better labels
    labels = ["1 فرد", "2 فرد", "3 أفراد", "4 أفراد", "5 أفراد", "6+ أفراد"]
    rows = [
        [InlineKeyboardButton(labels[i-1], callback_data=f"household:{i}") for i in range(1, 4)],
        [InlineKeyboardButton(labels[i-1], callback_data=f"household:{i}") for i in range(4, 7)],
    ]
    s = await get_settings(str(update.effective_chat.id))
    n = int(s.get("household_size") or 1)
    await update.message.reply_text(
        f"👨‍👩‍👧 *عدد أفراد الأسرة* (الحالي: {n})\n\n"
        f"يُستخدم لحساب حدود Jobcenter و Wohngeld تلقائياً.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def callback_household(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if str(query.from_user.id) != str(CHAT_ID):
        return
    n = int(query.data.split(":")[1])
    await upsert_settings(str(query.message.chat_id), household_size=n)
    jc_lim = get_jobcenter_limit(n)
    wg_lim = get_wohngeld_limit(n)
    sz_lim = get_size_limit(n)
    await query.edit_message_text(
        f"✅ *عدد الأفراد: {n}*\n\n"
        f"🏛 حد Jobcenter: {jc_lim:.0f} € · {sz_lim} م²\n"
        f"🏦 حد Wohngeld:  {wg_lim:.0f} €\n\n"
        f"_استخدم /social لتفعيل الفلاتر_",
        parse_mode=ParseMode.MARKDOWN,
    )


# ── /social ────────────────────────────────────────────────────────────────────

async def cmd_social(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s         = await get_settings(str(update.effective_chat.id))
    n         = int(s.get("household_size") or 1)
    jc_active = bool(s.get("jobcenter_mode", 0))
    wg_active = bool(s.get("wohngeld_mode",  0))
    jc_lim    = get_jobcenter_limit(n)
    wg_lim    = get_wohngeld_limit(n)
    sz_lim    = get_size_limit(n)

    jc_btn = f"{'✅' if jc_active else '❌'} Jobcenter KdU"
    wg_btn = f"{'✅' if wg_active else '❌'} Wohngeld"

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(jc_btn, callback_data="social:toggle_jc")],
        [InlineKeyboardButton(wg_btn, callback_data="social:toggle_wg")],
        [InlineKeyboardButton("👨‍👩‍👧 تغيير عدد الأفراد", callback_data="social:household")],
        [InlineKeyboardButton("✅ حفظ وإغلاق",           callback_data="social:done")],
    ])

    await update.message.reply_text(
        "🏛 *فلاتر Jobcenter / Wohngeld*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👨‍👩‍👧 أفراد الأسرة: *{n}*\n\n"
        f"🏛 *Jobcenter KdU* — {'مفعّل ✅' if jc_active else 'معطّل ❌'}\n"
        f"   الحد الأقصى: {jc_lim:.0f} € شاملة · {sz_lim} م²\n"
        f"   يعرض فقط الشقق التي يقبلها Jobcenter\n\n"
        f"🏦 *Wohngeld* — {'مفعّل ✅' if wg_active else 'معطّل ❌'}\n"
        f"   الحد الأقصى: {wg_lim:.0f} €\n"
        f"   يعرض فقط الشقق التي تندرج ضمن إعانة السكن\n\n"
        f"_اضغط لتفعيل أو تعطيل كل فلتر:_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def callback_social(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if str(query.from_user.id) != str(CHAT_ID):
        return

    chat_id = str(query.message.chat_id)
    data    = query.data  # social:toggle_jc / social:toggle_wg / social:done

    s = await get_settings(chat_id)
    n = int(s.get("household_size") or 1)

    if data == "social:toggle_jc":
        new_val = 0 if s.get("jobcenter_mode") else 1
        await upsert_settings(chat_id, jobcenter_mode=new_val)
        s["jobcenter_mode"] = new_val
    elif data == "social:toggle_wg":
        new_val = 0 if s.get("wohngeld_mode") else 1
        await upsert_settings(chat_id, wohngeld_mode=new_val)
        s["wohngeld_mode"] = new_val
    elif data == "social:household":
        await query.answer("استخدم /household لتغيير عدد الأفراد", show_alert=True)
        return
    elif data == "social:done":
        jc = "✅ مفعّل" if s.get("jobcenter_mode") else "❌ معطّل"
        wg = "✅ مفعّل" if s.get("wohngeld_mode")  else "❌ معطّل"
        await query.edit_message_text(
            f"✅ *تم الحفظ*\n\n"
            f"🏛 Jobcenter: {jc}\n"
            f"🏦 Wohngeld:  {wg}",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Refresh the social menu
    jc_active = bool(s.get("jobcenter_mode", 0))
    wg_active = bool(s.get("wohngeld_mode",  0))
    jc_lim    = get_jobcenter_limit(n)
    wg_lim    = get_wohngeld_limit(n)
    sz_lim    = get_size_limit(n)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'✅' if jc_active else '❌'} Jobcenter KdU", callback_data="social:toggle_jc")],
        [InlineKeyboardButton(f"{'✅' if wg_active else '❌'} Wohngeld",      callback_data="social:toggle_wg")],
        [InlineKeyboardButton("👨‍👩‍👧 تغيير عدد الأفراد",  callback_data="social:household")],
        [InlineKeyboardButton("✅ حفظ وإغلاق",            callback_data="social:done")],
    ])
    try:
        await query.edit_message_text(
            "🏛 *فلاتر Jobcenter / Wohngeld*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👨‍👩‍👧 أفراد الأسرة: *{n}*\n\n"
            f"🏛 *Jobcenter KdU* — {'مفعّل ✅' if jc_active else 'معطّل ❌'}\n"
            f"   الحد: {jc_lim:.0f} € · {sz_lim} م²\n\n"
            f"🏦 *Wohngeld* — {'مفعّل ✅' if wg_active else 'معطّل ❌'}\n"
            f"   الحد: {wg_lim:.0f} €\n\n"
            f"_اضغط لتبديل كل فلتر:_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )
    except Exception:
        pass


async def cmd_uptime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    import time as _t
    elapsed   = _t.monotonic() - _BOT_START
    hours, rm = divmod(int(elapsed), 3600)
    mins, secs = divmod(rm, 60)
    started   = _BOT_START_DT.strftime("%Y-%m-%d %H:%M UTC")
    st        = await get_stats()
    await update.message.reply_text(
        f"⏱ *Uptime: {hours}h {mins}m {secs}s*\n"
        f"🕐 بدأ: `{started}`\n"
        f"🔄 دورات: `{st.get('total_cycles',0)}`\n"
        f"📨 إشعارات: `{st.get('total_sent',0)}`\n"
        f"🗃 محفوظ: `{st.get('db_size',0)}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )


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
        household_size=1, jobcenter_mode=0, wohngeld_mode=0,
    )
    await update.message.reply_text(
        "🔄 *تم إعادة جميع الإعدادات للافتراضي*\n\n"
        "💰 أقصى إيجار: 600 €\n"
        "🛏 أقل غرف: أي عدد\n"
        "📍 المناطق: كل برلين\n"
        "🏠 الوضع: كل الشقق\n"
        "👨‍👩‍👧 الأسرة: 1 فرد\n"
        "🏛 Jobcenter: معطّل\n"
        "🏦 Wohngeld: معطّل\n"
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
    app.add_handler(CommandHandler("uptime",       cmd_uptime))
    app.add_handler(CommandHandler("reset",        cmd_reset))
    app.add_handler(CommandHandler("social",       cmd_social))
    app.add_handler(CommandHandler("household",    cmd_household))
    # Inline callbacks
    app.add_handler(CallbackQueryHandler(callback_area,      pattern="^area_"))
    app.add_handler(CallbackQueryHandler(callback_price,     pattern="^set_price:"))
    app.add_handler(CallbackQueryHandler(callback_rooms,     pattern="^set_rooms:"))
    app.add_handler(CallbackQueryHandler(callback_social,    pattern="^social:"))
    app.add_handler(CallbackQueryHandler(callback_household, pattern="^household:"))
    # Persistent reply keyboard
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app
