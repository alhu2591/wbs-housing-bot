"""
WBS Housing Bot — Telegram handlers.
Professional customization UI: sources, areas, price, rooms, WBS, social filters.
"""
import json
import logging
import os
import time as _time
from datetime import datetime, timezone

from telegram import (
    Update, BotCommand,
    InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.constants import ParseMode
from telegram.ext import (
    ContextTypes, CommandHandler, CallbackQueryHandler,
    MessageHandler, ApplicationBuilder, Application,
    filters as tg_filters,
)

from database import get_settings, upsert_settings, get_stats, get_recent_listings
from database.health import get_all_health
from filters.social_filter import (
    get_jobcenter_limit, get_wohngeld_limit, get_size_limit,
    get_full_requirements, get_jobcenter_min_rooms, get_wohngeld_min_rooms,
)
from config.settings import CHAT_ID, BOT_TOKEN

logger = logging.getLogger(__name__)

_BOT_START    = _time.monotonic()
_BOT_START_DT = datetime.now(timezone.utc)

# ── Source metadata ──────────────────────────────────────────────────────────
SOURCE_META = {
    "gewobag":            ("Gewobag",           "🏛", True),
    "degewo":             ("Degewo",            "🏛", True),
    "howoge":             ("Howoge",            "🏛", True),
    "stadtundland":       ("Stadt und Land",    "🏛", True),
    "deutschewohnen":     ("Deutsche Wohnen",   "🏛", True),
    "berlinovo":          ("Berlinovo",         "🏛", True),
    "immoscout":          ("ImmoScout24",       "🔍", False),
    "wggesucht":          ("WG-Gesucht",        "🔍", False),
    "ebay_kleinanzeigen": ("Kleinanzeigen",     "🔍", False),
    "immowelt":           ("Immowelt",          "🔍", False),
}
ALL_SOURCES = list(SOURCE_META.keys())
GOV_SOURCES = {k for k, v in SOURCE_META.items() if v[2]}

# ── Berlin districts ─────────────────────────────────────────────────────────
BERLIN_DISTRICTS = [
    ("Mitte",             "مركز برلين"),
    ("Friedrichshain",    "فريدريشهاين"),
    ("Kreuzberg",         "كروتسبرغ"),
    ("Prenzlauer Berg",   "برينتسلاور بيرغ"),
    ("Charlottenburg",    "شارلوتنبورغ"),
    ("Wilmersdorf",       "فيلمرسدورف"),
    ("Spandau",           "شباندو"),
    ("Steglitz",          "شتيغليتز"),
    ("Zehlendorf",        "تسيلندورف"),
    ("Tempelhof",         "تمبلهوف"),
    ("Schöneberg",        "شونيبيرغ"),
    ("Neukölln",          "نيوكولن"),
    ("Treptow",           "تريبتو"),
    ("Köpenick",          "كوبينيك"),
    ("Marzahn",           "مارتسان"),
    ("Hellersdorf",       "هيلرسدورف"),
    ("Lichtenberg",       "ليشتنبرغ"),
    ("Weißensee",         "فايسنزي"),
    ("Pankow",            "بانكو"),
    ("Reinickendorf",     "راينيكندورف"),
    ("Wedding",           "فيدينغ"),
    ("Moabit",            "موابيت"),
]

# ── Persistent bottom keyboard ───────────────────────────────────────────────
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📊 الحالة"),       KeyboardButton("📈 الإحصائيات")],
        [KeyboardButton("⚙️ إعدادات"),      KeyboardButton("🔍 المصادر")],
        [KeyboardButton("✅ WBS فقط"),      KeyboardButton("🔓 كل الشقق")],
        [KeyboardButton("🟢 تشغيل"),        KeyboardButton("🔴 إيقاف")],
    ],
    resize_keyboard=True,
    input_field_placeholder="اكتب أمراً أو اضغط زراً…",
)

# ── Bot commands ─────────────────────────────────────────────────────────────
BOT_COMMANDS = [
    BotCommand("start",     "تشغيل البوت والمساعدة"),
    BotCommand("status",    "الحالة الكاملة والإعدادات"),
    BotCommand("settings",  "لوحة التخصيص الرئيسية"),
    BotCommand("sources",   "اختيار المواقع التي يراقبها البوت"),
    BotCommand("areas",     "اختيار مناطق برلين"),
    BotCommand("set_price", "تحديد أقصى إيجار"),
    BotCommand("set_rooms", "تحديد أقل عدد غرف"),
    BotCommand("schedule",  "ساعات الهدوء — إيقاف الإشعارات ليلاً"),
    BotCommand("social",    "فلاتر Jobcenter وWohngeld"),
    BotCommand("household", "عدد أفراد الأسرة"),
    BotCommand("wbs_on",    "عرض شقق WBS فقط"),
    BotCommand("wbs_off",   "عرض كل الشقق"),
    BotCommand("on",        "تشغيل الإشعارات"),
    BotCommand("off",       "إيقاف الإشعارات"),
    BotCommand("stats",     "إحصائيات البوت"),
    BotCommand("last",      "آخر إعلانات"),
    BotCommand("check",     "فحص صحة المصادر"),
    BotCommand("ping",      "اختبار سرعة الاستجابة"),
    BotCommand("uptime",    "مدة التشغيل"),
    BotCommand("reset",     "إعادة جميع الإعدادات للافتراضي"),
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_owner(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CHAT_ID)

async def _deny(update: Update) -> None:
    await update.message.reply_text("⛔ غير مصرح.")

def _time_ago(iso: str | None) -> str:
    if not iso: return "—"
    try:
        dt   = datetime.fromisoformat(iso)
        diff = int((datetime.utcnow() - dt).total_seconds())
        if diff < 60:     return f"منذ {diff}ث"
        elif diff < 3600: return f"منذ {diff//60}د"
        elif diff < 86400:return f"منذ {diff//3600}س"
        else:             return f"منذ {diff//86400} يوم"
    except Exception:
        return "—"

def _jl(raw) -> list[str]:
    """Safe JSON list load."""
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# /start  /help
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await update.message.reply_text(
        "🏠 *بوت شقق WBS برلين*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "أراقب 10 مواقع إعلانات برلين كل 5 دقائق\n"
        "وأرسل فقط الشقق التي تناسب إعداداتك.\n\n"
        "📋 *أبرز الأوامر:*\n"
        "├ /settings — لوحة التخصيص الكاملة\n"
        "├ /sources  — اختيار المواقع\n"
        "├ /areas    — اختيار المناطق\n"
        "├ /social   — فلاتر Jobcenter/Wohngeld\n"
        "├ /status   — عرض كل الإعدادات\n"
        "└ /reset    — إعادة الضبط\n\n"
        "✅ *اضغط ⚙️ إعدادات للبدء*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


# ═══════════════════════════════════════════════════════════════════════════════
# /settings — Main customization hub
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s = await get_settings(str(update.effective_chat.id))
    await _send_settings_menu(update.message, s)

async def _send_settings_menu(msg, s: dict) -> None:
    """Render the main settings inline menu."""
    sources    = _jl(s.get("sources"))
    areas      = _jl(s.get("areas"))
    n          = int(s.get("household_size") or 1)
    jc         = "✅" if s.get("jobcenter_mode") else "❌"
    wg         = "✅" if s.get("wohngeld_mode")  else "❌"
    wbs        = "✅" if s.get("wbs_only")        else "❌"
    active     = "🟢" if s.get("active", 1)       else "🔴"
    price      = s.get("max_price", 600)
    rooms      = s.get("min_rooms") or 0
    qs         = int(s.get("quiet_start", -1))
    qe         = int(s.get("quiet_end",   -1))
    mpc        = int(s.get("max_per_cycle", 10))

    src_lbl    = f"{len(sources)}/{len(ALL_SOURCES)}" if sources else "الكل"
    area_lbl   = f"{len(areas)} منطقة" if areas else "كل برلين"
    rooms_lbl  = f"≥{rooms:.0f}" if rooms else "أي"
    qs_lbl     = f"{qs:02d}:00–{qe:02d}:00" if qs >= 0 else "—"

    keyboard = InlineKeyboardMarkup([
        # Row 1
        [
            InlineKeyboardButton(f"🌐 المواقع [{src_lbl}]",    callback_data="cfg:sources"),
            InlineKeyboardButton(f"📍 المناطق [{area_lbl}]",   callback_data="cfg:areas"),
        ],
        # Row 2
        [
            InlineKeyboardButton(f"💰 الإيجار ≤{price:.0f}€", callback_data="cfg:price"),
            InlineKeyboardButton(f"🛏 الغرف [{rooms_lbl}]",   callback_data="cfg:rooms"),
        ],
        # Row 3
        [
            InlineKeyboardButton(f"📋 WBS [{wbs}]",            callback_data="cfg:wbs"),
            InlineKeyboardButton(f"👨‍👩‍👧 الأسرة [{n} فرد]",      callback_data="cfg:household"),
        ],
        # Row 4
        [
            InlineKeyboardButton(f"🏛 Jobcenter [{jc}]",       callback_data="cfg:social"),
            InlineKeyboardButton(f"🏦 Wohngeld [{wg}]",        callback_data="cfg:social"),
        ],
        # Row 5
        [
            InlineKeyboardButton(f"🌙 هدوء [{qs_lbl}]",        callback_data="cfg:schedule"),
            InlineKeyboardButton(f"📬 حد [{mpc}/دورة]",        callback_data="cfg:maxpc"),
        ],
        # Row 6
        [
            InlineKeyboardButton(f"🔔 الإشعارات [{active}]",   callback_data="cfg:toggle"),
            InlineKeyboardButton("🔄 إعادة الضبط",             callback_data="cfg:reset"),
        ],
        [InlineKeyboardButton("❌ إغلاق", callback_data="cfg:close")],
    ])

    await msg.reply_text(
        "⚙️ *لوحة التخصيص*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "اضغط أي خيار لتعديله:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard,
    )


async def callback_cfg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dispatch from main settings menu."""
    q = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    data    = q.data.split(":", 1)[1]
    chat_id = str(q.message.chat_id)

    if data == "close":
        await q.delete_message(); return

    if data == "toggle":
        s = await get_settings(chat_id)
        new = 0 if s.get("active", 1) else 1
        await upsert_settings(chat_id, active=new)
        await q.answer("🟢 مفعّل" if new else "🔴 موقوف", show_alert=False)
        s["active"] = new
        await _edit_settings_menu(q, s); return

    if data == "reset":
        await _do_reset(chat_id)
        await q.answer("✅ تم إعادة الضبط")
        s = await get_settings(chat_id)
        await _edit_settings_menu(q, s); return

    if data == "wbs":
        s = await get_settings(chat_id)
        new = 0 if s.get("wbs_only") else 1
        await upsert_settings(chat_id, wbs_only=new)
        s["wbs_only"] = new
        await _edit_settings_menu(q, s); return

    if data == "price":
        await q.delete_message()
        await _show_price_menu(q.message.chat_id, context); return

    if data == "rooms":
        await q.delete_message()
        await _show_rooms_menu(q.message.chat_id, context); return

    if data == "sources":
        s = await get_settings(chat_id)
        await _edit_sources_menu(q, s); return

    if data == "areas":
        s = await get_settings(chat_id)
        await _edit_areas_menu(q, s); return

    if data == "household":
        await _edit_household_menu(q); return

    if data == "social":
        s = await get_settings(chat_id)
        await _edit_social_menu(q, s); return

    if data == "schedule":
        s = await get_settings(chat_id)
        await _edit_schedule_menu(q, s); return

    if data == "maxpc":
        s = await get_settings(chat_id)
        await _edit_maxpc_menu(q, s); return


async def _edit_settings_menu(q, s: dict) -> None:
    sources   = _jl(s.get("sources"))
    areas     = _jl(s.get("areas"))
    n         = int(s.get("household_size") or 1)
    jc        = "✅" if s.get("jobcenter_mode") else "❌"
    wg        = "✅" if s.get("wohngeld_mode")  else "❌"
    wbs       = "✅" if s.get("wbs_only")        else "❌"
    active    = "🟢" if s.get("active", 1)       else "🔴"
    price     = s.get("max_price", 600)
    rooms     = s.get("min_rooms") or 0
    qs        = int(s.get("quiet_start", -1))
    qe        = int(s.get("quiet_end",   -1))
    mpc       = int(s.get("max_per_cycle", 10))
    src_lbl   = f"{len(sources)}/{len(ALL_SOURCES)}" if sources else "الكل"
    area_lbl  = f"{len(areas)} منطقة" if areas else "كل برلين"
    rooms_lbl = f"≥{rooms:.0f}" if rooms else "أي"
    qs_lbl    = f"{qs:02d}:00–{qe:02d}:00" if qs >= 0 else "—"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🌐 المواقع [{src_lbl}]",    callback_data="cfg:sources"),
            InlineKeyboardButton(f"📍 المناطق [{area_lbl}]",   callback_data="cfg:areas"),
        ],
        [
            InlineKeyboardButton(f"💰 الإيجار ≤{price:.0f}€", callback_data="cfg:price"),
            InlineKeyboardButton(f"🛏 الغرف [{rooms_lbl}]",   callback_data="cfg:rooms"),
        ],
        [
            InlineKeyboardButton(f"📋 WBS [{wbs}]",            callback_data="cfg:wbs"),
            InlineKeyboardButton(f"👨‍👩‍👧 الأسرة [{n} فرد]",      callback_data="cfg:household"),
        ],
        [
            InlineKeyboardButton(f"🏛 Jobcenter [{jc}]",       callback_data="cfg:social"),
            InlineKeyboardButton(f"🏦 Wohngeld [{wg}]",        callback_data="cfg:social"),
        ],
        [
            InlineKeyboardButton(f"🌙 هدوء [{qs_lbl}]",        callback_data="cfg:schedule"),
            InlineKeyboardButton(f"📬 حد [{mpc}/دورة]",        callback_data="cfg:maxpc"),
        ],
        [
            InlineKeyboardButton(f"🔔 الإشعارات [{active}]",   callback_data="cfg:toggle"),
            InlineKeyboardButton("🔄 إعادة الضبط",             callback_data="cfg:reset"),
        ],
        [InlineKeyboardButton("❌ إغلاق", callback_data="cfg:close")],
    ])
    try:
        await q.edit_message_reply_markup(reply_markup=keyboard)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Sources
# ═══════════════════════════════════════════════════════════════════════════════

def _sources_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    """Inline keyboard showing all 10 sources with toggle state."""
    rows = []
    items = list(SOURCE_META.items())
    for i in range(0, len(items), 2):
        row = []
        for src, (name, icon, is_gov) in items[i:i+2]:
            on   = not selected or src in selected
            tick = "✅" if on else "☐"
            gov  = "🏛" if is_gov else "🔍"
            row.append(InlineKeyboardButton(
                f"{tick} {gov} {name}",
                callback_data=f"src:toggle:{src}",
            ))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("✅ تفعيل الكل",  callback_data="src:all"),
        InlineKeyboardButton("🏛 حكومية فقط",  callback_data="src:gov"),
    ])
    rows.append([InlineKeyboardButton("💾 حفظ", callback_data="src:save")])
    return InlineKeyboardMarkup(rows)


def _sources_text(selected: list[str]) -> str:
    active = [SOURCE_META[s][0] for s in ALL_SOURCES if (not selected or s in selected)]
    inactive = [SOURCE_META[s][0] for s in ALL_SOURCES if selected and s not in selected]
    t = "🌐 *اختيار المواقع*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    t += f"مفعّل ({len(active)}): " + " · ".join(active) + "\n"
    if inactive:
        t += f"مُعطّل ({len(inactive)}): " + " · ".join(inactive) + "\n"
    t += "\n_اضغط موقعاً لتفعيله أو تعطيله:_"
    return t


async def cmd_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s        = await get_settings(str(update.effective_chat.id))
    selected = _jl(s.get("sources"))
    await update.message.reply_text(
        _sources_text(selected),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_sources_keyboard(selected),
    )


async def _edit_sources_menu(q, s: dict) -> None:
    selected = _jl(s.get("sources"))
    try:
        await q.edit_message_text(
            _sources_text(selected),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_sources_keyboard(selected),
        )
    except Exception:
        pass


async def callback_src(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    action  = q.data.split(":", 2)

    s        = await get_settings(chat_id)
    selected = _jl(s.get("sources"))

    if action[1] == "toggle":
        src = action[2]
        if src in selected:
            selected.remove(src)
        else:
            selected.append(src)
        # If all selected, clear (= all)
        if set(selected) == set(ALL_SOURCES):
            selected = []
        await upsert_settings(chat_id, sources=json.dumps(selected))
        s["sources"] = json.dumps(selected)
        await _edit_sources_menu(q, s)

    elif action[1] == "all":
        selected = []
        await upsert_settings(chat_id, sources="[]")
        s["sources"] = "[]"
        await _edit_sources_menu(q, s)

    elif action[1] == "gov":
        selected = list(GOV_SOURCES)
        await upsert_settings(chat_id, sources=json.dumps(selected))
        s["sources"] = json.dumps(selected)
        await _edit_sources_menu(q, s)

    elif action[1] == "save":
        lbl = f"{len(selected)}/{len(ALL_SOURCES)}" if selected else "الكل"
        await q.answer(f"✅ تم الحفظ — {lbl} مواقع", show_alert=True)
        await q.delete_message()


# ═══════════════════════════════════════════════════════════════════════════════
# Areas
# ═══════════════════════════════════════════════════════════════════════════════

def _areas_keyboard(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(BERLIN_DISTRICTS), 2):
        row = []
        for de, ar in BERLIN_DISTRICTS[i:i+2]:
            on   = not selected or de in selected
            tick = "✅" if on else "☐"
            row.append(InlineKeyboardButton(
                f"{tick} {ar}",
                callback_data=f"area:toggle:{de}",
            ))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("🌍 كل برلين",  callback_data="area:all"),
        InlineKeyboardButton("💾 حفظ",        callback_data="area:save"),
    ])
    return InlineKeyboardMarkup(rows)


def _areas_text(selected: list[str]) -> str:
    active_ar = [ar for de, ar in BERLIN_DISTRICTS if (not selected or de in selected)]
    t = "📍 *اختيار المناطق*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    if not selected:
        t += "🌍 كل برلين محدّدة\n"
    else:
        t += "محدّد: " + "، ".join(active_ar) + "\n"
    t += "\n_اضغط منطقة لتفعيلها أو تعطيلها:_"
    return t


async def cmd_areas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s        = await get_settings(str(update.effective_chat.id))
    selected = _jl(s.get("areas"))
    await update.message.reply_text(
        _areas_text(selected),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_areas_keyboard(selected),
    )


async def _edit_areas_menu(q, s: dict) -> None:
    selected = _jl(s.get("areas"))
    try:
        await q.edit_message_text(
            _areas_text(selected),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_areas_keyboard(selected),
        )
    except Exception:
        pass


async def callback_area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    action  = q.data.split(":", 2)
    s        = await get_settings(chat_id)
    selected = _jl(s.get("areas"))

    if action[1] == "toggle":
        de = action[2]
        if de in selected:
            selected.remove(de)
        else:
            selected.append(de)
        if set(selected) == {d for d, _ in BERLIN_DISTRICTS}:
            selected = []
        await upsert_settings(chat_id, areas=json.dumps(selected, ensure_ascii=False))
        s["areas"] = json.dumps(selected, ensure_ascii=False)
        await _edit_areas_menu(q, s)

    elif action[1] == "all":
        selected = []
        await upsert_settings(chat_id, areas="[]")
        s["areas"] = "[]"
        await _edit_areas_menu(q, s)

    elif action[1] == "save":
        lbl = f"{len(selected)} مناطق" if selected else "كل برلين"
        await q.answer(f"✅ تم الحفظ — {lbl}", show_alert=True)
        await q.delete_message()


# ═══════════════════════════════════════════════════════════════════════════════
# Price & Rooms
# ═══════════════════════════════════════════════════════════════════════════════

async def _show_price_menu(chat_id, context):
    prices = [350, 400, 450, 500, 550, 600, 650, 700, 750, 800, 900, 1000]
    rows = []
    for i in range(0, len(prices), 4):
        rows.append([
            InlineKeyboardButton(f"{p}€", callback_data=f"price:set:{p}")
            for p in prices[i:i+4]
        ])
    rows.append([InlineKeyboardButton("✍️ أدخل رقماً: /set_price 550", callback_data="price:close")])
    await context.bot.send_message(
        chat_id=chat_id,
        text="💰 *اختر أقصى إيجار شهري:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _show_rooms_menu(chat_id, context):
    opts = [("أي عدد", 0), ("1+", 1), ("1.5+", 1.5), ("2+", 2),
            ("2.5+", 2.5), ("3+", 3), ("3.5+", 3.5), ("4+", 4)]
    rows = []
    for i in range(0, len(opts), 4):
        rows.append([
            InlineKeyboardButton(lbl, callback_data=f"rooms:set:{r}")
            for lbl, r in opts[i:i+4]
        ])
    await context.bot.send_message(
        chat_id=chat_id,
        text="🛏 *اختر الحد الأدنى للغرف:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def cmd_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if context.args:
        try:
            p = float(context.args[0].replace(",", "."))
            await upsert_settings(str(update.effective_chat.id), max_price=p)
            await update.message.reply_text(f"✅ أقصى إيجار: *{p:.0f} €*",
                parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD); return
        except ValueError: pass
    await _show_price_menu(update.effective_chat.id, context)


async def cmd_set_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if context.args:
        try:
            r = float(context.args[0].replace(",", "."))
            await upsert_settings(str(update.effective_chat.id), min_rooms=r)
            lbl = f"≥{r:.0f}" if r else "أي عدد"
            await update.message.reply_text(f"✅ الغرف: *{lbl}*",
                parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD); return
        except ValueError: pass
    await _show_rooms_menu(update.effective_chat.id, context)


async def callback_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    action = q.data.split(":", 2)
    if action[1] == "close":
        await q.delete_message(); return
    p = float(action[2])
    await upsert_settings(str(q.message.chat_id), max_price=p)
    await q.edit_message_text(f"✅ *أقصى إيجار: {p:.0f} €*", parse_mode=ParseMode.MARKDOWN)


async def callback_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    r = float(q.data.split(":", 2)[2])
    await upsert_settings(str(q.message.chat_id), min_rooms=r)
    lbl = f"≥{r:.0f}" if r else "أي عدد"
    await q.edit_message_text(f"✅ *الغرف: {lbl}*", parse_mode=ParseMode.MARKDOWN)


# ═══════════════════════════════════════════════════════════════════════════════
# Household & Social
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_household(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if context.args:
        try:
            n = int(context.args[0])
            assert 1 <= n <= 10
            await upsert_settings(str(update.effective_chat.id), household_size=n)
            reqs = get_full_requirements(n)
            await update.message.reply_text(
                f"✅ *عدد الأفراد: {n}*\n\n"
                f"🏛 JC: {reqs['jc_price']:.0f}€ / {reqs['jc_size_max']}م²\n"
                f"🏦 WG: {reqs['wg_price']:.0f}€",
                parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD); return
        except (ValueError, AssertionError): pass
    await _edit_household_menu_msg(update.message)


async def _edit_household_menu_msg(msg):
    labels = ["1 فرد","2 فرد","3 أفراد","4 أفراد","5 أفراد","6+ أفراد"]
    rows = [
        [InlineKeyboardButton(labels[i-1], callback_data=f"hh:set:{i}") for i in range(1,4)],
        [InlineKeyboardButton(labels[i-1], callback_data=f"hh:set:{i}") for i in range(4,7)],
    ]
    await msg.reply_text("👨‍👩‍👧 *عدد أفراد الأسرة:*",
        parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))


async def _edit_household_menu(q):
    labels = ["1 فرد","2 فرد","3 أفراد","4 أفراد","5 أفراد","6+ أفراد"]
    rows = [
        [InlineKeyboardButton(labels[i-1], callback_data=f"hh:set:{i}") for i in range(1,4)],
        [InlineKeyboardButton(labels[i-1], callback_data=f"hh:set:{i}") for i in range(4,7)],
    ]
    try:
        await q.edit_message_text("👨‍👩‍👧 *عدد أفراد الأسرة:*",
            parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(rows))
    except Exception: pass


async def callback_household(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    n = int(q.data.split(":", 2)[2])
    await upsert_settings(str(q.message.chat_id), household_size=n)
    reqs = get_full_requirements(n)
    await q.edit_message_text(
        f"✅ *{n} {'فرد' if n==1 else 'أفراد'}*\n\n"
        f"🏛 Jobcenter: {reqs['jc_price']:.0f}€ · {reqs['jc_size_max']}م² · {reqs['jc_rooms_min']:.0f} غرف\n"
        f"🏦 Wohngeld:  {reqs['wg_price']:.0f}€ · {reqs['wg_rooms_min']:.0f} غرف\n\n"
        "_/social لتفعيل الفلاتر_",
        parse_mode=ParseMode.MARKDOWN,
    )


def _social_text(s: dict) -> str:
    n    = int(s.get("household_size") or 1)
    jc   = bool(s.get("jobcenter_mode"))
    wg   = bool(s.get("wohngeld_mode"))
    reqs = get_full_requirements(n)
    return (
        "🏛 *فلاتر Jobcenter / Wohngeld*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👨‍👩‍👧 الأسرة: *{n} {'فرد' if n==1 else 'أفراد'}*\n\n"
        f"🏛 *Jobcenter KdU* {'✅ مفعّل' if jc else '❌ معطّل'}\n"
        f"   ✔ إيجار ≤ {reqs['jc_price']:.0f} €\n"
        f"   ✔ مساحة ≤ {reqs['jc_size_max']} م²\n"
        f"   ✔ غرف ≥ {reqs['jc_rooms_min']:.0f}\n\n"
        f"🏦 *Wohngeld* {'✅ مفعّل' if wg else '❌ معطّل'}\n"
        f"   ✔ إيجار ≤ {reqs['wg_price']:.0f} €\n"
        f"   ✔ غرف ≥ {reqs['wg_rooms_min']:.0f}\n\n"
        "_يجب استيفاء جميع الشروط لكل فلتر_"
    )


def _social_keyboard(s: dict) -> InlineKeyboardMarkup:
    jc = bool(s.get("jobcenter_mode"))
    wg = bool(s.get("wohngeld_mode"))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'✅' if jc else '❌'} Jobcenter KdU", callback_data="soc:jc")],
        [InlineKeyboardButton(f"{'✅' if wg else '❌'} Wohngeld",      callback_data="soc:wg")],
        [InlineKeyboardButton("👨‍👩‍👧 تغيير عدد الأفراد", callback_data="soc:hh")],
        [InlineKeyboardButton("💾 حفظ وإغلاق",         callback_data="soc:done")],
    ])


async def cmd_social(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s = await get_settings(str(update.effective_chat.id))
    await update.message.reply_text(_social_text(s), parse_mode=ParseMode.MARKDOWN,
        reply_markup=_social_keyboard(s))


async def _edit_social_menu(q, s: dict) -> None:
    try:
        await q.edit_message_text(_social_text(s), parse_mode=ParseMode.MARKDOWN,
            reply_markup=_social_keyboard(s))
    except Exception: pass


async def callback_social(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    action  = q.data.split(":", 1)[1]
    s       = await get_settings(chat_id)

    if action == "jc":
        new = 0 if s.get("jobcenter_mode") else 1
        await upsert_settings(chat_id, jobcenter_mode=new)
        s["jobcenter_mode"] = new
        await _edit_social_menu(q, s)
    elif action == "wg":
        new = 0 if s.get("wohngeld_mode") else 1
        await upsert_settings(chat_id, wohngeld_mode=new)
        s["wohngeld_mode"] = new
        await _edit_social_menu(q, s)
    elif action == "hh":
        await _edit_household_menu(q)
    elif action == "done":
        jc = "✅" if s.get("jobcenter_mode") else "❌"
        wg = "✅" if s.get("wohngeld_mode")  else "❌"
        await q.edit_message_text(f"✅ *تم الحفظ*\n\n🏛 Jobcenter: {jc}\n🏦 Wohngeld: {wg}",
            parse_mode=ParseMode.MARKDOWN)


# ═══════════════════════════════════════════════════════════════════════════════
# Schedule (quiet hours)
# ═══════════════════════════════════════════════════════════════════════════════

def _schedule_text(s: dict) -> str:
    qs = int(s.get("quiet_start", -1))
    qe = int(s.get("quiet_end",   -1))
    if qs < 0:
        status = "🔔 لا ساعات هدوء — الإشعارات دائماً مفعّلة"
    else:
        status = f"🌙 هدوء من {qs:02d}:00 حتى {qe:02d}:00"
    return (
        "🌙 *ساعات الهدوء*\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{status}\n\n"
        "_خلال ساعات الهدوء تُحفظ الإشعارات ولا تُرسل_\n"
        "_اضغط البداية ثم النهاية:_"
    )


def _schedule_keyboard(s: dict) -> InlineKeyboardMarkup:
    qs = int(s.get("quiet_start", -1))
    qe = int(s.get("quiet_end",   -1))
    phase = s.get("_schedule_phase", "start")
    hours = [22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    rows = []
    for i in range(0, len(hours), 4):
        rows.append([
            InlineKeyboardButton(f"{h:02d}:00", callback_data=f"sch:{phase}:{h}")
            for h in hours[i:i+4]
        ])
    rows.append([
        InlineKeyboardButton("🚫 إلغاء ساعات الهدوء", callback_data="sch:clear:0"),
    ])
    rows.append([InlineKeyboardButton("❌ إغلاق", callback_data="sch:close:0")])
    return InlineKeyboardMarkup(rows)


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s = await get_settings(str(update.effective_chat.id))
    s["_schedule_phase"] = "start"
    await update.message.reply_text(
        _schedule_text(s) + "\n\n*اختر ساعة البداية:*",
        parse_mode=ParseMode.MARKDOWN, reply_markup=_schedule_keyboard(s))


async def _edit_schedule_menu(q, s: dict) -> None:
    s["_schedule_phase"] = "start"
    try:
        await q.edit_message_text(
            _schedule_text(s) + "\n\n*اختر ساعة البداية:*",
            parse_mode=ParseMode.MARKDOWN, reply_markup=_schedule_keyboard(s))
    except Exception: pass


async def callback_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    _, action, val = q.data.split(":", 2)
    h = int(val)
    s = await get_settings(chat_id)

    if action == "close":
        await q.delete_message(); return
    if action == "clear":
        await upsert_settings(chat_id, quiet_start=-1, quiet_end=-1)
        s["quiet_start"] = -1; s["quiet_end"] = -1
        await q.edit_message_text("✅ *ساعات الهدوء مُلغاة*\nالإشعارات مفعّلة دائماً.",
            parse_mode=ParseMode.MARKDOWN); return
    if action == "start":
        s["_qs_pending"] = h
        s["_schedule_phase"] = "end"
        await q.edit_message_text(
            f"ساعة البداية: *{h:02d}:00*\n\n*اختر ساعة النهاية:*",
            parse_mode=ParseMode.MARKDOWN, reply_markup=_schedule_keyboard(s)); return
    if action == "end":
        qs = s.get("_qs_pending", 22)
        await upsert_settings(chat_id, quiet_start=qs, quiet_end=h)
        await q.edit_message_text(
            f"✅ *ساعات الهدوء: {qs:02d}:00 — {h:02d}:00*\n\nلن تُرسل إشعارات خلال هذا الوقت.",
            parse_mode=ParseMode.MARKDOWN); return


# ═══════════════════════════════════════════════════════════════════════════════
# Max per cycle
# ═══════════════════════════════════════════════════════════════════════════════

async def _edit_maxpc_menu(q, s: dict) -> None:
    opts = [1, 3, 5, 10, 15, 20, 30, 50]
    rows = []
    for i in range(0, len(opts), 4):
        rows.append([
            InlineKeyboardButton(f"{v}", callback_data=f"mpc:set:{v}")
            for v in opts[i:i+4]
        ])
    current = int(s.get("max_per_cycle", 10))
    try:
        await q.edit_message_text(
            f"📬 *حد الإشعارات لكل دورة* (الحالي: {current})\n\n"
            "_منع إغراق المحادثة بعشرات الإشعارات دفعة واحدة_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(rows))
    except Exception: pass


async def callback_mpc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    v = int(q.data.split(":", 2)[2])
    await upsert_settings(str(q.message.chat_id), max_per_cycle=v)
    await q.edit_message_text(f"✅ *حد الإشعارات: {v} لكل دورة*", parse_mode=ParseMode.MARKDOWN)


# ═══════════════════════════════════════════════════════════════════════════════
# /status  /stats  /on  /off  /wbs_on  /wbs_off
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s        = await get_settings(str(update.effective_chat.id))
    active   = "🟢 يعمل" if s.get("active", 1) else "🔴 موقوف"
    wbs      = "✅ WBS فقط" if s.get("wbs_only") else "🔓 كل الشقق"
    price    = s.get("max_price", 600)
    rooms    = s.get("min_rooms") or 0
    rooms_s  = f"≥{rooms:.0f}" if rooms else "أي عدد"
    n        = int(s.get("household_size") or 1)
    sources  = _jl(s.get("sources"))
    areas    = _jl(s.get("areas"))
    qs       = int(s.get("quiet_start", -1))
    qe       = int(s.get("quiet_end",   -1))
    mpc      = int(s.get("max_per_cycle", 10))
    jc_on    = bool(s.get("jobcenter_mode"))
    wg_on    = bool(s.get("wohngeld_mode"))
    reqs     = get_full_requirements(n)

    src_list = [SOURCE_META[s_][0] for s_ in ALL_SOURCES if not sources or s_ in sources]
    src_str  = " · ".join(src_list)
    area_str = "كل برلين 🌍" if not areas else "، ".join(areas)
    qs_str   = f"🌙 {qs:02d}:00–{qe:02d}:00" if qs >= 0 else "—"

    jc_str = (f"✅ ≤{reqs['jc_price']:.0f}€ / {reqs['jc_size_max']}م² / {reqs['jc_rooms_min']:.0f}غرف"
              if jc_on else "❌ معطّل")
    wg_str = (f"✅ ≤{reqs['wg_price']:.0f}€ / {reqs['wg_rooms_min']:.0f}غرف"
              if wg_on else "❌ معطّل")

    await update.message.reply_text(
        "📊 *الإعدادات الكاملة*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔔 الإشعارات:   {active}\n"
        f"🏠 وضع البحث:   {wbs}\n"
        f"💰 أقصى إيجار: {price:.0f} €\n"
        f"🛏 الغرف:       {rooms_s}\n"
        f"📍 المناطق:     {area_str}\n"
        f"🌐 المواقع:     {src_str}\n"
        f"👨‍👩‍👧 الأسرة:      {n} {'فرد' if n==1 else 'أفراد'}\n"
        f"🏛 Jobcenter:  {jc_str}\n"
        f"🏦 Wohngeld:   {wg_str}\n"
        f"📬 حد/دورة:    {mpc}\n"
        f"🌙 هدوء:       {qs_str}\n\n"
        "_/settings لتعديل الإعدادات_",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    st = await get_stats()
    await update.message.reply_text(
        "📈 *إحصائيات البوت*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📨 إشعارات مُرسلة:  {st.get('total_sent', 0)}\n"
        f"🔄 دورات كشط:      {st.get('total_cycles', 0)}\n"
        f"🗃 إعلانات محفوظة: {st.get('db_size', 0)}\n"
        f"🕐 آخر إشعار:      {_time_ago(st.get('last_sent_at'))}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )

async def cmd_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=1)
    await update.message.reply_text("🟢 *الإشعارات مفعّلة*", parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)

async def cmd_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), active=0)
    await update.message.reply_text("🔴 *الإشعارات موقوفة*", parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)

async def cmd_wbs_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), wbs_only=1)
    await update.message.reply_text("✅ *WBS فقط*", parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)

async def cmd_wbs_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await upsert_settings(str(update.effective_chat.id), wbs_only=0)
    await update.message.reply_text("🔓 *كل الشقق*", parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)


# ═══════════════════════════════════════════════════════════════════════════════
# /last  /check
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    n = 5
    if context.args:
        try: n = min(int(context.args[0]), 15)
        except ValueError: pass
    rows = await get_recent_listings(n)
    if not rows:
        await update.message.reply_text("📭 لا توجد إعلانات محفوظة.", reply_markup=MAIN_KEYBOARD); return
    lines = [f"🕐 *آخر {n} إعلانات*\n━━━━━━━━━━━━━━━━━━━━\n"]
    for i, r in enumerate(rows, 1):
        price = f"{r['price']:.0f} €" if r.get("price") else "—"
        src   = SOURCE_META.get(r.get("source", ""), (r.get("source",""), "🔍", False))[0]
        title = (r.get("title") or "شقة").strip()[:40]
        ago   = _time_ago(r.get("created_at"))
        url   = r.get("url","")
        lines.append(f"*{i}.* [{title}]({url})\n   💰 {price} · {src} · {ago}\n")
    await update.message.reply_text("\n".join(lines),
        parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True, reply_markup=MAIN_KEYBOARD)


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await update.message.reply_text("🔍 جاري الفحص…", reply_markup=MAIN_KEYBOARD)
    from scrapers.circuit_breaker import all_statuses
    hmap   = {r["source"]: r for r in await get_all_health()}
    cb_map = {s["name"]: s for s in all_statuses()}
    lines  = ["📊 *حالة المصادر*\n━━━━━━━━━━━━━━━━━━━━\n"]
    ok = err = 0
    for src in ALL_SOURCES:
        name, icon, _ = SOURCE_META[src]
        row      = hmap.get(src)
        cb       = cb_map.get(src, {})
        cb_state = {"CLOSED":"🟢","HALF":"🟡","OPEN":"🔴"}.get(cb.get("state","CLOSED"),"⚪")
        if not row:
            lines.append(f"⚪ {icon} *{name}* — لم يعمل بعد {cb_state}")
        elif row.get("status") == "ok":
            ok += 1
            lines.append(f"✅ {icon} *{name}*  `{row.get('listings_found',0)}` · {_time_ago(row.get('last_run'))} {cb_state}")
        else:
            err += 1
            lines.append(f"❌ {icon} *{name}*  `{str(row.get('last_error',''))[:40]}` {cb_state}")
    lines.append(f"\n📈 *{ok}/{len(ALL_SOURCES)}* يعمل · 🟢طبيعي 🟡اختبار 🔴مغلق")
    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)


# ═══════════════════════════════════════════════════════════════════════════════
# /ping  /uptime  /reset
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    import time
    t0  = time.monotonic()
    msg = await update.message.reply_text("🏓 …")
    lat = (time.monotonic() - t0) * 1000
    from scheduler.runner import _cycle
    await msg.edit_text(f"🏓 *Pong\\!*\n⚡ `{lat:.0f}ms`\n🔄 دورة `#{_cycle}`",
        parse_mode=ParseMode.MARKDOWN)


async def cmd_uptime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    elapsed   = _time.monotonic() - _BOT_START
    h, rem    = divmod(int(elapsed), 3600)
    m, s      = divmod(rem, 60)
    started   = _BOT_START_DT.strftime("%Y-%m-%d %H:%M UTC")
    st        = await get_stats()
    await update.message.reply_text(
        f"⏱ *{h}س {m}د {s}ث*\n"
        f"🕐 بدأ: `{started}`\n"
        f"🔄 دورات: `{st.get('total_cycles',0)}`\n"
        f"📨 مُرسل: `{st.get('total_sent',0)}`",
        parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)


async def _do_reset(chat_id: str) -> None:
    await upsert_settings(chat_id,
        active=1, max_price=600, min_rooms=0, area="", wbs_only=0,
        areas="[]", sources="[]", household_size=1,
        jobcenter_mode=0, wohngeld_mode=0,
        quiet_start=-1, quiet_end=-1, max_per_cycle=10,
    )


async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await _do_reset(str(update.effective_chat.id))
    await update.message.reply_text(
        "🔄 *تم إعادة جميع الإعدادات للافتراضي*",
        parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)


# ═══════════════════════════════════════════════════════════════════════════════
# Reply keyboard dispatcher
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mapping = {
        "📊 الحالة":       cmd_status,
        "📈 الإحصائيات":   cmd_stats,
        "⚙️ إعدادات":     cmd_settings,
        "🔍 المصادر":      cmd_sources,
        "✅ WBS فقط":      cmd_wbs_on,
        "🔓 كل الشقق":     cmd_wbs_off,
        "🟢 تشغيل":        cmd_on,
        "🔴 إيقاف":        cmd_off,
    }
    fn = mapping.get(update.message.text)
    if fn:
        await fn(update, context)


# ═══════════════════════════════════════════════════════════════════════════════
# Notification formatter
# ═══════════════════════════════════════════════════════════════════════════════

FEATURE_ICONS = {
    "بلكونة":"🌿","تراس":"🌿","حديقة":"🌱","مصعد":"🛗",
    "مطبخ مجهز":"🍳","مخزن":"📦","موقف سيارة":"🚗",
    "بدون عوائق":"♿","بناء جديد":"🏗","أول سكن":"✨",
    "غسالة":"🫧","حمام إضافي":"🚿",
}

def _clean(t: str, maxlen: int = 70) -> str:
    import re
    t = re.sub(r'\s+', ' ', str(t or ""))
    t = re.sub(r'\s*\|\s*', ', ', t)
    t = re.sub(r',\s*,+', ',', t)
    return t.strip(' ,|•–-/')[:maxlen].strip()


def format_listing(listing: dict) -> tuple[str, InlineKeyboardMarkup | None]:
    src      = listing.get("source", "")
    name, icon, _ = SOURCE_META.get(src, (src.title(), "🔍", False))
    src_type = "🏛 حكومية" if src in GOV_SOURCES else "🔍 خاصة"

    price = listing.get("price")
    p_str = f"{price:,.0f} €".replace(",", ".") if isinstance(price, (int, float)) else None
    ppm2  = listing.get("price_per_m2")
    if p_str and ppm2:
        p_str += f"  *(≈ {ppm2} €/م²)*"

    rooms = listing.get("rooms")
    r_str = (str(int(rooms)) if rooms == int(rooms) else str(rooms)) if rooms else None

    size  = listing.get("size_m2")
    s_str = f"{size:.0f} م²" if size else None

    loc   = _clean(listing.get("district") or listing.get("location") or "Berlin")

    wbs_level  = listing.get("wbs_level")
    wbs_line   = f"📋 WBS:  ✅ مطلوب {wbs_level}" if wbs_level else "📋 WBS:  ❌ غير مطلوب"
    soc_badge  = listing.get("social_badge", "")

    lines = [f"🏢 *{name}* — {src_type}\n"]
    if loc:                       lines.append(f"📍 الموقع:   {loc}")
    if p_str:                     lines.append(f"💰 الإيجار:  {p_str}")
    if r_str:                     lines.append(f"🛏 الغرف:    {r_str}")
    if s_str:                     lines.append(f"📐 المساحة:  {s_str}")
    if listing.get("floor"):      lines.append(f"🏢 الطابق:   {listing['floor']}")
    if listing.get("available_from"): lines.append(f"📅 الإتاحة:  {listing['available_from']}")
    lines.append(wbs_line)
    if soc_badge:                 lines.append(soc_badge)

    msg = "\n".join(lines).strip()
    if len(msg) > 1020:
        msg = msg[:1017] + "…"

    view_url  = listing.get("url", "")
    apply_url = listing.get("apply_url", "")
    rows = []
    if view_url:
        rows.append([InlineKeyboardButton("🔍 عرض الإعلان", url=view_url)])
    if apply_url and apply_url != view_url:
        rows.append([InlineKeyboardButton("📝 تقدم الآن", url=apply_url)])

    return msg, InlineKeyboardMarkup(rows) if rows else None


# ═══════════════════════════════════════════════════════════════════════════════
# App builder
# ═══════════════════════════════════════════════════════════════════════════════

def build_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("help",      cmd_help))
    app.add_handler(CommandHandler("settings",  cmd_settings))
    app.add_handler(CommandHandler("status",    cmd_status))
    app.add_handler(CommandHandler("stats",     cmd_stats))
    app.add_handler(CommandHandler("sources",   cmd_sources))
    app.add_handler(CommandHandler("areas",     cmd_areas))
    app.add_handler(CommandHandler("set_price", cmd_set_price))
    app.add_handler(CommandHandler("set_rooms", cmd_set_rooms))
    app.add_handler(CommandHandler("social",    cmd_social))
    app.add_handler(CommandHandler("household", cmd_household))
    app.add_handler(CommandHandler("schedule",  cmd_schedule))
    app.add_handler(CommandHandler("wbs_on",    cmd_wbs_on))
    app.add_handler(CommandHandler("wbs_off",   cmd_wbs_off))
    app.add_handler(CommandHandler("on",        cmd_on))
    app.add_handler(CommandHandler("off",       cmd_off))
    app.add_handler(CommandHandler("last",      cmd_last))
    app.add_handler(CommandHandler("check",     cmd_check))
    app.add_handler(CommandHandler("ping",      cmd_ping))
    app.add_handler(CommandHandler("uptime",    cmd_uptime))
    app.add_handler(CommandHandler("reset",     cmd_reset))

    # Inline callbacks
    app.add_handler(CallbackQueryHandler(callback_cfg,      pattern="^cfg:"))
    app.add_handler(CallbackQueryHandler(callback_src,      pattern="^src:"))
    app.add_handler(CallbackQueryHandler(callback_area,     pattern="^area:"))
    app.add_handler(CallbackQueryHandler(callback_price,    pattern="^price:"))
    app.add_handler(CallbackQueryHandler(callback_rooms,    pattern="^rooms:"))
    app.add_handler(CallbackQueryHandler(callback_social,   pattern="^soc:"))
    app.add_handler(CallbackQueryHandler(callback_household,pattern="^hh:"))
    app.add_handler(CallbackQueryHandler(callback_schedule, pattern="^sch:"))
    app.add_handler(CallbackQueryHandler(callback_mpc,      pattern="^mpc:"))

    # Text buttons
    app.add_handler(MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, handle_text))
    return app
