"""
WBS Housing Bot — Telegram handlers.
Professional UI with inline keyboards for all settings.
No external API dependencies.
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
    get_full_requirements,
)
from config.settings import CHAT_ID, BOT_TOKEN

logger = logging.getLogger(__name__)
_BOT_START    = _time.monotonic()
_BOT_START_DT = datetime.now(timezone.utc)

# ── Source registry ──────────────────────────────────────────────────────────
SOURCE_META = {
    # Government / large housing companies
    "gewobag":            ("Gewobag",         "🏛", True),
    "degewo":             ("Degewo",          "🏛", True),
    "howoge":             ("Howoge",          "🏛", True),
    "stadtundland":       ("Stadt und Land",  "🏛", True),
    "deutschewohnen":     ("Deutsche Wohnen", "🏛", True),
    "berlinovo":          ("Berlinovo",       "🏛", True),
    "vonovia":            ("Vonovia",         "🏛", True),
    "gesobau":            ("Gesobau",         "🏛", True),
    "wbm":                ("WBM",             "🏛", True),
    # Private platforms
    "immoscout":          ("ImmoScout24",     "🔍", False),
    "wggesucht":          ("WG-Gesucht",      "🔍", False),
    "ebay_kleinanzeigen": ("Kleinanzeigen",   "🔍", False),
    "immowelt":           ("Immowelt",        "🔍", False),
}
ALL_SOURCES = list(SOURCE_META.keys())
GOV_SOURCES = {k for k, v in SOURCE_META.items() if v[2]}

# ── Berlin districts ─────────────────────────────────────────────────────────
BERLIN_DISTRICTS = [
    ("Mitte",           "Mitte"),
    ("Friedrichshain",  "Friedrichshain"),
    ("Kreuzberg",       "Kreuzberg"),
    ("Prenzlauer Berg", "Prenzlauer Berg"),
    ("Charlottenburg",  "Charlottenburg"),
    ("Wilmersdorf",     "Wilmersdorf"),
    ("Spandau",         "Spandau"),
    ("Steglitz",        "Steglitz"),
    ("Zehlendorf",      "Zehlendorf"),
    ("Tempelhof",       "Tempelhof"),
    ("Schöneberg",      "Schöneberg"),
    ("Neukölln",        "Neukölln"),
    ("Treptow",         "Treptow"),
    ("Köpenick",        "Köpenick"),
    ("Marzahn",         "Marzahn"),
    ("Hellersdorf",     "Hellersdorf"),
    ("Lichtenberg",     "Lichtenberg"),
    ("Weißensee",       "Weißensee"),
    ("Pankow",          "Pankow"),
    ("Reinickendorf",   "Reinickendorf"),
    ("Wedding",         "Wedding"),
    ("Moabit",          "Moabit"),
]

# ── Bottom keyboard ──────────────────────────────────────────────────────────
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📊 الحالة"),      KeyboardButton("📈 الإحصائيات")],
        [KeyboardButton("⚙️ إعدادات"),    KeyboardButton("🔍 المصادر")],
        [KeyboardButton("✅ WBS فقط"),    KeyboardButton("🔓 كل الشقق")],
        [KeyboardButton("🟢 تشغيل"),      KeyboardButton("🔴 إيقاف")],
    ],
    resize_keyboard=True,
    input_field_placeholder="اكتب أمراً أو اضغط زراً…",
)

BOT_COMMANDS = [
    BotCommand("start",     "تشغيل البوت"),
    BotCommand("status",    "الحالة والإعدادات"),
    BotCommand("settings",  "لوحة التخصيص"),
    BotCommand("sources",   "اختيار المواقع"),
    BotCommand("areas",     "اختيار المناطق"),
    BotCommand("set_price", "أقصى إيجار"),
    BotCommand("set_rooms", "أقل غرف"),
    BotCommand("schedule",  "ساعات الهدوء"),
    BotCommand("social",    "فلاتر Jobcenter وWohngeld"),
    BotCommand("household", "عدد أفراد الأسرة"),
    BotCommand("wbs_on",    "WBS فقط"),
    BotCommand("wbs_off",   "كل الشقق"),
    BotCommand("on",        "تشغيل الإشعارات"),
    BotCommand("off",       "إيقاف الإشعارات"),
    BotCommand("stats",     "إحصائيات"),
    BotCommand("last",      "آخر إعلانات"),
    BotCommand("check",     "فحص المصادر"),
    BotCommand("ping",      "اختبار الاستجابة"),
    BotCommand("uptime",    "مدة التشغيل"),
    BotCommand("reset",     "إعادة الضبط"),
    BotCommand("get_chat_id", "احصل على Chat ID"),
]

# ── Helpers ──────────────────────────────────────────────────────────────────

def _is_owner(update: Update) -> bool:
    return str(update.effective_chat.id) == str(CHAT_ID)

async def _deny(update: Update) -> None:
    await update.message.reply_text("⛔ غير مصرح.")

def _time_ago(iso) -> str:
    if not iso: return "—"
    try:
        dt   = datetime.fromisoformat(iso)
        diff = int((datetime.utcnow() - dt).total_seconds())
        if diff < 60:      return f"منذ {diff}ث"
        elif diff < 3600:  return f"منذ {diff//60}د"
        elif diff < 86400: return f"منذ {diff//3600}س"
        else:              return f"منذ {diff//86400} يوم"
    except Exception:
        return "—"

def _jl(raw) -> list:
    try:
        v = json.loads(raw or "[]")
        return v if isinstance(v, list) else []
    except Exception:
        return []

def _sep() -> str:
    return "━━━━━━━━━━━━━━━━━━━━"


# ═══════════════════════════════════════════════════════════════════════════════
# /start  /help
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await update.message.reply_text(
        "\U0001f3e0 *بوت شقق WBS برلين*\n" + _sep() + "\n\n"
        "أراقب 10 مواقع كل 5 دقائق وأرسل\n"
        "فقط الشقق التي تناسب إعداداتك.\n\n"
        "📋 *الأوامر الرئيسية:*\n"
        "├ /settings — لوحة التخصيص الكاملة\n"
        "├ /sources  — اختيار المواقع\n"
        "├ /areas    — اختيار المناطق\n"
        "├ /social   — Jobcenter/Wohngeld\n"
        "├ /status   — عرض كل الإعدادات\n"
        "└ /reset    — إعادة الضبط\n\n"
        "✅ *اضغط ⚙️ إعدادات للبدء*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=MAIN_KEYBOARD,
    )



async def cmd_get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Anyone can use this — helps first-time setup."""
    cid = str(update.effective_chat.id)
    uid = str(update.effective_user.id) if update.effective_user else "?"
    await update.message.reply_text(
        f"🆔 *معلوماتك:*\n\n"
        f"Chat ID: `{cid}`\n"
        f"User ID: `{uid}`\n\n"
        f"_انسخ Chat ID وضعه في ملف .env أو setup\\_wizard.py_",
        parse_mode=ParseMode.MARKDOWN,
    )

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, context)


# ═══════════════════════════════════════════════════════════════════════════════
# Settings hub — /settings
# ═══════════════════════════════════════════════════════════════════════════════

def _build_settings_keyboard(s: dict) -> InlineKeyboardMarkup:
    sources   = _jl(s.get("sources"))
    areas     = _jl(s.get("areas"))
    n         = int(s.get("household_size") or 1)
    jc        = "✅" if s.get("jobcenter_mode") else "❌"
    wg        = "✅" if s.get("wohngeld_mode")  else "❌"
    wbs       = "✅" if s.get("wbs_only")        else "❌"
    active    = "🟢" if s.get("active", 1)       else "🔴"
    price     = float(s.get("max_price") or 600)
    rooms     = float(s.get("min_rooms") or 0)
    qs        = int(s.get("quiet_start", -1))
    qe        = int(s.get("quiet_end",   -1))
    mpc       = int(s.get("max_per_cycle") or 10)
    src_lbl   = f"{len(sources)}/{len(ALL_SOURCES)}" if sources else "الكل"
    area_lbl  = f"{len(areas)} منطقة" if areas else "كل برلين"
    rooms_lbl = f">={rooms:.0f}" if rooms else "أي"
    qs_lbl    = f"{qs:02d}-{qe:02d}" if qs >= 0 else "—"

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🌐 مواقع [{src_lbl}]",   callback_data="cfg:sources"),
            InlineKeyboardButton(f"📍 مناطق [{area_lbl}]",  callback_data="cfg:areas"),
        ],
        [
            InlineKeyboardButton(f"💰 اجار <={price:.0f}€", callback_data="cfg:price"),
            InlineKeyboardButton(f"🛏 غرف [{rooms_lbl}]",   callback_data="cfg:rooms"),
        ],
        [
            InlineKeyboardButton(f"📋 WBS [{wbs}]",          callback_data="cfg:wbs"),
            InlineKeyboardButton(f"🎚 مستوى WBS",            callback_data="cfg:wbs_level"),
        ],
        [
            InlineKeyboardButton(f"🏛 Jobcenter [{jc}]",     callback_data="cfg:jc_toggle"),
            InlineKeyboardButton(f"🏦 Wohngeld [{wg}]",      callback_data="cfg:wg_toggle"),
        ],
        [
            InlineKeyboardButton(f"👥 الأسرة [{n} فرد]",     callback_data="cfg:household"),
            InlineKeyboardButton("⚙️ المزيد من الاجتماعي",  callback_data="cfg:social"),
        ],
        [
            InlineKeyboardButton(f"🌙 هدوء [{qs_lbl}]",     callback_data="cfg:schedule"),
            InlineKeyboardButton(f"📬 حد [{mpc}/دورة]",     callback_data="cfg:maxpc"),
        ],
        [
            InlineKeyboardButton(f"🔔 [{active}]",           callback_data="cfg:toggle"),
            InlineKeyboardButton("🔄 إعادة الضبط",           callback_data="cfg:reset"),
        ],
        [InlineKeyboardButton("❌ إغلاق", callback_data="cfg:close")],
    ])


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s  = await get_settings(str(update.effective_chat.id))
    kb = _build_settings_keyboard(s)
    await update.message.reply_text(
        "⚙️ *لوحة التخصيص*\n" + _sep() + "\n"
        "اضغط أي خيار لتعديله:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )


async def _refresh_settings(q, s: dict) -> None:
    try:
        await q.edit_message_reply_markup(reply_markup=_build_settings_keyboard(s))
    except Exception:
        pass


async def callback_cfg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q       = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    data    = q.data.split(":", 1)[1]

    if data == "close":
        await q.delete_message(); return

    if data == "toggle":
        s   = await get_settings(chat_id)
        new = 0 if s.get("active", 1) else 1
        await upsert_settings(chat_id, active=new)
        s["active"] = new
        await _refresh_settings(q, s); return

    if data == "wbs":
        s   = await get_settings(chat_id)
        new = 0 if s.get("wbs_only") else 1
        await upsert_settings(chat_id, wbs_only=new)
        s["wbs_only"] = new
        await _refresh_settings(q, s); return

    if data == "reset":
        await _do_reset(chat_id)
        s = await get_settings(chat_id)
        await q.answer("✅ تم إعادة الضبط")
        await _refresh_settings(q, s); return

    s = await get_settings(chat_id)

    if data == "price":
        cur = float(s.get("max_price") or 600)
        try:
            await q.edit_message_text(
                _price_text(cur),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_price_keyboard(cur),
            )
        except Exception: pass
        return

    if data == "rooms":
        cur = float(s.get("min_rooms") or 0)
        try:
            await q.edit_message_text(
                _rooms_text(cur),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_rooms_keyboard(cur),
            )
        except Exception: pass
        return

    if data == "sources":
        sel = _jl(s.get("sources"))
        try:
            await q.edit_message_text(
                _sources_text(sel),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_sources_keyboard(sel),
            )
        except Exception: pass
        return

    if data == "areas":
        sel = _jl(s.get("areas"))
        try:
            await q.edit_message_text(
                _areas_text(sel),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_areas_keyboard(sel),
            )
        except Exception: pass
        return

    if data == "household":
        cur = int(s.get("household_size") or 1)
        try:
            await q.edit_message_text(
                _household_text(cur),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_household_keyboard(cur),
            )
        except Exception: pass
        return

    if data == "jc_toggle":
        new = 0 if s.get("jobcenter_mode") else 1
        await upsert_settings(chat_id, jobcenter_mode=new)
        s["jobcenter_mode"] = new
        await _refresh_settings(q, s); return

    if data == "wg_toggle":
        new = 0 if s.get("wohngeld_mode") else 1
        await upsert_settings(chat_id, wohngeld_mode=new)
        s["wohngeld_mode"] = new
        await _refresh_settings(q, s); return

    if data == "wbs_level":
        wmin = int(s.get("wbs_level_min") or 0)
        wmax = int(s.get("wbs_level_max") or 999)
        try:
            await q.edit_message_text(
                _wbs_level_text(wmin, wmax),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_wbs_level_keyboard(wmin, wmax),
            )
        except Exception: pass
        return

    if data == "social":
        try:
            await q.edit_message_text(
                _social_text(s),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_social_keyboard(s),
            )
        except Exception: pass
        return

    if data == "schedule":
        try:
            await q.edit_message_text(
                _schedule_text(s),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_schedule_keyboard(s, phase="start"),
            )
        except Exception: pass
        return

    if data == "maxpc":
        cur = int(s.get("max_per_cycle") or 10)
        try:
            await q.edit_message_text(
                _maxpc_text(cur),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_maxpc_keyboard(cur),
            )
        except Exception: pass
        return



# ═══════════════════════════════════════════════════════════════════════════════
# WBS Level selector (100-220)
# ═══════════════════════════════════════════════════════════════════════════════

WBS_LEVELS = [100, 140, 160, 180, 200, 220]


def _wbs_level_text(wmin: int, wmax: int) -> str:
    if wmin == 0 and wmax >= 999:
        current = "كل المستويات"
    elif wmin == wmax:
        current = f"WBS {wmin} فقط"
    else:
        current = f"WBS {wmin} — WBS {wmax}"
    lines = [
        "🎚 *مستوى WBS المقبول*",
        _sep(),
        "",
        f"الحالي: *{current}*",
        "",
        "اختر الحد الأدنى والأقصى للمستوى:",
        "_مثال: إذا اخترت 100-160 يعرض WBS 100 و140 و160 فقط_",
    ]
    return "\n".join(lines)


def _wbs_level_keyboard(wmin: int, wmax: int) -> InlineKeyboardMarkup:
    rows = []
    # Min row
    min_row = []
    for level in WBS_LEVELS:
        tick = "✓" if level == wmin else ""
        min_row.append(InlineKeyboardButton(
            f"{tick}≥{level}", callback_data=f"wlvl:min:{level}"))
    rows.append(min_row)
    # Max row
    max_row = []
    for level in WBS_LEVELS:
        tick = "✓" if level == wmax else ""
        max_row.append(InlineKeyboardButton(
            f"{tick}<={level}", callback_data=f"wlvl:max:{level}"))
    rows.append(max_row)
    # Quick presets
    rows.append([
        InlineKeyboardButton("WBS 100 فقط",       callback_data="wlvl:preset:100:100"),
        InlineKeyboardButton("WBS 100-140",         callback_data="wlvl:preset:100:140"),
        InlineKeyboardButton("كل المستويات",        callback_data="wlvl:preset:0:999"),
    ])
    rows.append([InlineKeyboardButton("◀️ رجوع", callback_data="wlvl:back")])
    return InlineKeyboardMarkup(rows)


async def callback_wbs_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q       = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    parts   = q.data.split(":", 3)
    action  = parts[1]
    s       = await get_settings(chat_id)
    wmin    = int(s.get("wbs_level_min") or 0)
    wmax    = int(s.get("wbs_level_max") or 999)

    if action == "back":
        await _refresh_settings(q, s); return
    if action == "min":
        wmin = int(parts[2])
        if wmin > wmax: wmax = wmin
        await upsert_settings(chat_id, wbs_level_min=wmin, wbs_level_max=wmax)
        await q.answer(f"✅ من WBS {wmin}")
    elif action == "max":
        wmax = int(parts[2])
        if wmax < wmin: wmin = wmax
        await upsert_settings(chat_id, wbs_level_min=wmin, wbs_level_max=wmax)
        await q.answer(f"✅ حتى WBS {wmax}")
    elif action == "preset":
        wmin, wmax = int(parts[2]), int(parts[3])
        await upsert_settings(chat_id, wbs_level_min=wmin, wbs_level_max=wmax)
        lbl = "كل المستويات" if wmin == 0 else f"WBS {wmin}-{wmax}"
        await q.answer(f"✅ {lbl}")
    try:
        await q.edit_message_text(
            _wbs_level_text(wmin, wmax),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_wbs_level_keyboard(wmin, wmax),
        )
    except Exception: pass

# ═══════════════════════════════════════════════════════════════════════════════
# Price keyboard
# ═══════════════════════════════════════════════════════════════════════════════

def _price_text(cur: float) -> str:
    lines = [
        "💰 *أقصى إيجار شهري*",
        _sep(),
        "",
        f"الحالي: *{cur:.0f} €*",
        "",
        "اضغط مبلغاً أو عدّل بـ ➕/➖:",
    ]
    return "\n".join(lines)


def _price_keyboard(cur: float) -> InlineKeyboardMarkup:
    prices = [300, 350, 400, 450, 500, 550, 600, 650, 700, 750, 800, 850, 900, 1000, 1200]
    rows   = []
    for i in range(0, len(prices), 5):
        row = []
        for p in prices[i:i+5]:
            label = f"✓{p}€" if int(cur) == p else f"{p}€"
            row.append(InlineKeyboardButton(label, callback_data=f"price:set:{p}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("➕ 25",  callback_data="price:inc:25"),
        InlineKeyboardButton("➕ 50",  callback_data="price:inc:50"),
        InlineKeyboardButton("➕ 100", callback_data="price:inc:100"),
        InlineKeyboardButton("➖ 25",  callback_data="price:dec:25"),
        InlineKeyboardButton("➖ 50",  callback_data="price:dec:50"),
    ])
    rows.append([InlineKeyboardButton("◀️ رجوع", callback_data="price:back")])
    return InlineKeyboardMarkup(rows)


async def cmd_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if context.args:
        try:
            p = float(context.args[0].replace(",", "."))
            await upsert_settings(str(update.effective_chat.id), max_price=p)
            await update.message.reply_text(
                f"✅ أقصى إيجار: *{p:.0f} €*",
                parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)
            return
        except ValueError: pass
    s   = await get_settings(str(update.effective_chat.id))
    cur = float(s.get("max_price") or 600)
    await update.message.reply_text(
        _price_text(cur), parse_mode=ParseMode.MARKDOWN, reply_markup=_price_keyboard(cur))


async def callback_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q       = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    parts   = q.data.split(":", 2)
    action  = parts[1]

    if action == "back":
        s = await get_settings(chat_id)
        await _refresh_settings(q, s); return

    s   = await get_settings(chat_id)
    cur = float(s.get("max_price") or 600)

    if action == "set":   cur = float(parts[2])
    elif action == "inc": cur = min(cur + float(parts[2]), 5000)
    elif action == "dec": cur = max(cur - float(parts[2]), 200)

    await upsert_settings(chat_id, max_price=cur)
    await q.answer(f"✅ {cur:.0f}€")
    try:
        await q.edit_message_text(
            _price_text(cur), parse_mode=ParseMode.MARKDOWN, reply_markup=_price_keyboard(cur))
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════════
# Rooms keyboard
# ═══════════════════════════════════════════════════════════════════════════════

def _rooms_text(cur: float) -> str:
    lbl = f"{cur:.0f}+ غرف" if cur else "أي عدد"
    lines = [
        "🛏 *الحد الأدنى للغرف*",
        _sep(),
        "",
        f"الحالي: *{lbl}*",
        "",
        "اضغط للاختيار:",
    ]
    return "\n".join(lines)


def _rooms_keyboard(cur: float) -> InlineKeyboardMarkup:
    opts = [
        ("أي عدد", 0), ("1", 1), ("1.5", 1.5),
        ("2", 2), ("2.5", 2.5), ("3", 3), ("3.5", 3.5), ("4+", 4),
    ]
    rows = []
    for i in range(0, len(opts), 4):
        row = []
        for lbl, r in opts[i:i+4]:
            label = f"✓{lbl}" if r == cur else lbl
            row.append(InlineKeyboardButton(label, callback_data=f"rooms:set:{r}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("◀️ رجوع", callback_data="rooms:back")])
    return InlineKeyboardMarkup(rows)


async def cmd_set_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if context.args:
        try:
            r = float(context.args[0].replace(",", "."))
            await upsert_settings(str(update.effective_chat.id), min_rooms=r)
            lbl = f">={r:.0f}" if r else "أي عدد"
            await update.message.reply_text(
                f"✅ الغرف: *{lbl}*",
                parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)
            return
        except ValueError: pass
    s   = await get_settings(str(update.effective_chat.id))
    cur = float(s.get("min_rooms") or 0)
    await update.message.reply_text(
        _rooms_text(cur), parse_mode=ParseMode.MARKDOWN, reply_markup=_rooms_keyboard(cur))


async def callback_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q       = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    parts   = q.data.split(":", 2)

    if parts[1] == "back":
        s = await get_settings(chat_id)
        await _refresh_settings(q, s); return

    r = float(parts[2])
    await upsert_settings(chat_id, min_rooms=r)
    lbl = f"{r:.0f}+ غرف" if r else "أي عدد"
    await q.answer(f"✅ {lbl}")
    try:
        await q.edit_message_text(
            _rooms_text(r), parse_mode=ParseMode.MARKDOWN, reply_markup=_rooms_keyboard(r))
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════════
# Sources keyboard
# ═══════════════════════════════════════════════════════════════════════════════

def _sources_text(selected: list) -> str:
    active = [SOURCE_META[s][0] for s in ALL_SOURCES if not selected or s in selected]
    lines = [
        "🌐 *اختيار المواقع*",
        _sep(),
        "",
        f"مفعّل: {len(active)}/{len(ALL_SOURCES)}",
        "",
        "اضغط لتفعيل أو تعطيل:",
    ]
    return "\n".join(lines)


def _sources_keyboard(selected: list) -> InlineKeyboardMarkup:
    items = list(SOURCE_META.items())
    rows  = []
    for i in range(0, len(items), 2):
        row = []
        for src, (name, icon, is_gov) in items[i:i+2]:
            on    = not selected or src in selected
            tick  = "✅" if on else "☐"
            row.append(InlineKeyboardButton(
                f"{tick} {icon} {name}", callback_data=f"src:toggle:{src}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("✅ الكل",       callback_data="src:all"),
        InlineKeyboardButton("🏛 حكومية فقط", callback_data="src:gov"),
        InlineKeyboardButton("💾 حفظ",        callback_data="src:save"),
    ])
    rows.append([InlineKeyboardButton("◀️ رجوع", callback_data="src:back")])
    return InlineKeyboardMarkup(rows)


async def cmd_sources(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s   = await get_settings(str(update.effective_chat.id))
    sel = _jl(s.get("sources"))
    await update.message.reply_text(
        _sources_text(sel), parse_mode=ParseMode.MARKDOWN, reply_markup=_sources_keyboard(sel))


async def callback_src(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q       = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    parts   = q.data.split(":", 2)
    action  = parts[1]
    s       = await get_settings(chat_id)
    sel     = _jl(s.get("sources"))

    if action == "back":
        await _refresh_settings(q, s); return

    if action == "toggle":
        src = parts[2]
        if src in sel: sel.remove(src)
        else: sel.append(src)
        if set(sel) == set(ALL_SOURCES): sel = []

    elif action == "all":
        sel = []
    elif action == "gov":
        sel = list(GOV_SOURCES)
    elif action == "save":
        lbl = f"{len(sel)}/{len(ALL_SOURCES)}" if sel else "الكل"
        await q.answer(f"✅ {lbl} مواقع")
        await upsert_settings(chat_id, sources=json.dumps(sel))
        s = await get_settings(chat_id)
        await _refresh_settings(q, s); return

    await upsert_settings(chat_id, sources=json.dumps(sel))
    s["sources"] = json.dumps(sel)
    try:
        await q.edit_message_text(
            _sources_text(sel), parse_mode=ParseMode.MARKDOWN, reply_markup=_sources_keyboard(sel))
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════════
# Areas keyboard
# ═══════════════════════════════════════════════════════════════════════════════

def _areas_text(selected: list) -> str:
    active = [de for de, _ in BERLIN_DISTRICTS if not selected or de in selected]
    lines = [
        "📍 *اختيار المناطق*",
        _sep(),
        "",
        f"محدد: {len(active)}/{len(BERLIN_DISTRICTS)}",
        "" if not selected else "المناطق: " + ", ".join(selected[:4]) + ("..." if len(selected) > 4 else ""),
        "",
        "اضغط منطقة لتفعيلها أو تعطيلها:",
    ]
    return "\n".join(lines)


def _areas_keyboard(selected: list) -> InlineKeyboardMarkup:
    rows = []
    for i in range(0, len(BERLIN_DISTRICTS), 2):
        row = []
        for de, name in BERLIN_DISTRICTS[i:i+2]:
            on    = not selected or de in selected
            tick  = "✅" if on else "☐"
            row.append(InlineKeyboardButton(
                f"{tick} {name}", callback_data=f"area:toggle:{de}"))
        rows.append(row)
    rows.append([
        InlineKeyboardButton("🌍 كل برلين", callback_data="area:all"),
        InlineKeyboardButton("💾 حفظ",       callback_data="area:save"),
    ])
    rows.append([InlineKeyboardButton("◀️ رجوع", callback_data="area:back")])
    return InlineKeyboardMarkup(rows)


async def cmd_areas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s   = await get_settings(str(update.effective_chat.id))
    sel = _jl(s.get("areas"))
    await update.message.reply_text(
        _areas_text(sel), parse_mode=ParseMode.MARKDOWN, reply_markup=_areas_keyboard(sel))


async def callback_area(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q       = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    parts   = q.data.split(":", 2)
    action  = parts[1]
    s       = await get_settings(chat_id)
    sel     = _jl(s.get("areas"))

    if action == "back":
        await _refresh_settings(q, s); return

    if action == "toggle":
        de = parts[2]
        if de in sel: sel.remove(de)
        else: sel.append(de)
        if set(sel) == {d for d, _ in BERLIN_DISTRICTS}: sel = []
    elif action == "all":
        sel = []
    elif action == "save":
        lbl = f"{len(sel)} مناطق" if sel else "كل برلين"
        await q.answer(f"✅ {lbl}")
        await upsert_settings(chat_id, areas=json.dumps(sel, ensure_ascii=False))
        s = await get_settings(chat_id)
        await _refresh_settings(q, s); return

    await upsert_settings(chat_id, areas=json.dumps(sel, ensure_ascii=False))
    try:
        await q.edit_message_text(
            _areas_text(sel), parse_mode=ParseMode.MARKDOWN, reply_markup=_areas_keyboard(sel))
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════════
# Household keyboard
# ═══════════════════════════════════════════════════════════════════════════════

def _household_text(cur: int) -> str:
    reqs = get_full_requirements(cur)
    unit = "فرد" if cur == 1 else "أفراد"
    lines = [
        "👥 *عدد أفراد الأسرة*",
        _sep(),
        "",
        f"الحالي: *{cur} {unit}*",
        "",
        f"🏛 Jobcenter: {reqs['jc_price']:.0f}€ / {reqs['jc_size_max']}m2 / {reqs['jc_rooms_min']:.0f}غرف",
        f"🏦 Wohngeld:  {reqs['wg_price']:.0f}€ / {reqs['wg_rooms_min']:.0f}غرف",
        "",
        "اضغط لتغيير:",
    ]
    return "\n".join(lines)


def _household_keyboard(cur: int, from_social: bool = False) -> InlineKeyboardMarkup:
    labels = ["1 فرد", "2 فرد", "3 أفراد", "4 أفراد", "5 أفراد", "6+ أفراد"]
    rows = [
        [InlineKeyboardButton(
            f"{'✓ ' if i == cur else ''}{labels[i-1]}",
            callback_data=f"hh:set:{i}") for i in range(1, 4)],
        [InlineKeyboardButton(
            f"{'✓ ' if i == cur else ''}{labels[i-1]}",
            callback_data=f"hh:set:{i}") for i in range(4, 7)],
    ]
    back = "hh:back:soc" if from_social else "hh:back:cfg"
    rows.append([InlineKeyboardButton("◀️ رجوع", callback_data=back)])
    return InlineKeyboardMarkup(rows)


async def cmd_household(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    if context.args:
        try:
            n = max(1, min(10, int(context.args[0])))
            await upsert_settings(str(update.effective_chat.id), household_size=n)
            await update.message.reply_text(
                f"✅ *{n} {'فرد' if n==1 else 'أفراد'}*",
                parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)
            return
        except (ValueError, AssertionError): pass
    s   = await get_settings(str(update.effective_chat.id))
    cur = int(s.get("household_size") or 1)
    await update.message.reply_text(
        _household_text(cur), parse_mode=ParseMode.MARKDOWN, reply_markup=_household_keyboard(cur))


async def callback_household(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q       = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    parts   = q.data.split(":", 2)
    action  = parts[1]
    s       = await get_settings(chat_id)

    if action == "back":
        dest = parts[2] if len(parts) > 2 else "cfg"
        if dest == "soc":
            try:
                await q.edit_message_text(
                    _social_text(s), parse_mode=ParseMode.MARKDOWN, reply_markup=_social_keyboard(s))
            except Exception: pass
        else:
            await _refresh_settings(q, s)
        return

    n = int(parts[2])
    await upsert_settings(chat_id, household_size=n)
    await q.answer(f"✅ {n} {'فرد' if n==1 else 'أفراد'}")
    try:
        await q.edit_message_text(
            _household_text(n), parse_mode=ParseMode.MARKDOWN, reply_markup=_household_keyboard(n))
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════════
# Social filter keyboard
# ═══════════════════════════════════════════════════════════════════════════════

def _social_text(s: dict) -> str:
    n    = int(s.get("household_size") or 1)
    jc   = bool(s.get("jobcenter_mode"))
    wg   = bool(s.get("wohngeld_mode"))
    reqs = get_full_requirements(n)
    unit = "فرد" if n == 1 else "أفراد"
    lines = [
        "🏛 *فلاتر Jobcenter / Wohngeld*",
        _sep(),
        "",
        f"👥 الأسرة: *{n} {unit}*",
        "",
        f"🏛 *Jobcenter KdU* {'✅ مفعّل' if jc else '❌ معطّل'}",
        f"   ✔ إيجار <= {reqs['jc_price']:.0f} €",
        f"   ✔ مساحة <= {reqs['jc_size_max']} m2",
        f"   ✔ غرف >= {reqs['jc_rooms_min']:.0f}",
        "",
        f"🏦 *Wohngeld* {'✅ مفعّل' if wg else '❌ معطّل'}",
        f"   ✔ إيجار <= {reqs['wg_price']:.0f} €",
        f"   ✔ غرف >= {reqs['wg_rooms_min']:.0f}",
        "",
        "_يجب استيفاء جميع الشروط_",
    ]
    return "\n".join(lines)


def _social_keyboard(s: dict) -> InlineKeyboardMarkup:
    jc = bool(s.get("jobcenter_mode"))
    wg = bool(s.get("wohngeld_mode"))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{'✅' if jc else '❌'} Jobcenter KdU", callback_data="soc:jc")],
        [InlineKeyboardButton(f"{'✅' if wg else '❌'} Wohngeld",      callback_data="soc:wg")],
        [InlineKeyboardButton("👥 تغيير عدد الأفراد",                  callback_data="soc:hh")],
        [InlineKeyboardButton("◀️ رجوع",                               callback_data="soc:back")],
    ])


async def cmd_social(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s = await get_settings(str(update.effective_chat.id))
    await update.message.reply_text(
        _social_text(s), parse_mode=ParseMode.MARKDOWN, reply_markup=_social_keyboard(s))


async def callback_social(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q       = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    action  = q.data.split(":", 1)[1]
    s       = await get_settings(chat_id)

    if action == "back":
        await _refresh_settings(q, s); return

    if action == "jc":
        new = 0 if s.get("jobcenter_mode") else 1
        await upsert_settings(chat_id, jobcenter_mode=new)
        s["jobcenter_mode"] = new
    elif action == "wg":
        new = 0 if s.get("wohngeld_mode") else 1
        await upsert_settings(chat_id, wohngeld_mode=new)
        s["wohngeld_mode"] = new
    elif action == "hh":
        cur = int(s.get("household_size") or 1)
        try:
            await q.edit_message_text(
                _household_text(cur),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_household_keyboard(cur, from_social=True))
        except Exception: pass
        return

    try:
        await q.edit_message_text(
            _social_text(s), parse_mode=ParseMode.MARKDOWN, reply_markup=_social_keyboard(s))
    except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════════
# Schedule (quiet hours)
# ═══════════════════════════════════════════════════════════════════════════════

def _schedule_text(s: dict) -> str:
    qs = int(s.get("quiet_start", -1))
    qe = int(s.get("quiet_end",   -1))
    if qs < 0:
        status = "🔔 لا ساعات هدوء — الإشعارات دائمة"
    else:
        status = f"🌙 هدوء من {qs:02d}:00 حتى {qe:02d}:00"
    lines = [
        "🌙 *ساعات الهدوء*",
        _sep(),
        "",
        status,
        "",
        "_خلال الهدوء: تُحفظ الإشعارات ولا تُرسل_",
    ]
    return "\n".join(lines)


def _schedule_keyboard(s: dict, phase: str = "start") -> InlineKeyboardMarkup:
    hours = [22, 23, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    rows  = []
    for i in range(0, len(hours), 4):
        rows.append([
            InlineKeyboardButton(f"{h:02d}:00", callback_data=f"sch:{phase}:{h}")
            for h in hours[i:i+4]
        ])
    rows.append([InlineKeyboardButton("🚫 إلغاء ساعات الهدوء", callback_data="sch:clear:0")])
    rows.append([InlineKeyboardButton("◀️ رجوع", callback_data="sch:back:0")])
    return InlineKeyboardMarkup(rows)


async def cmd_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s = await get_settings(str(update.effective_chat.id))
    await update.message.reply_text(
        _schedule_text(s) + "\n\n*اختر ساعة البداية:*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_schedule_keyboard(s, phase="start"))


async def callback_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q       = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    parts   = q.data.split(":", 2)
    action  = parts[1]
    val     = int(parts[2])
    s       = await get_settings(chat_id)

    if action == "back":
        await _refresh_settings(q, s); return

    if action == "clear":
        await upsert_settings(chat_id, quiet_start=-1, quiet_end=-1)
        s["quiet_start"] = -1; s["quiet_end"] = -1
        await q.answer("✅ مُلغاة")
        await _refresh_settings(q, s); return

    if action == "start":
        context.user_data["qs_pending"] = val
        try:
            await q.edit_message_text(
                f"البداية: *{val:02d}:00*\n\n*اختر ساعة النهاية:*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_schedule_keyboard(s, phase="end"))
        except Exception: pass
        return

    if action == "end":
        qs = context.user_data.pop("qs_pending", 22)
        await upsert_settings(chat_id, quiet_start=qs, quiet_end=val)
        await q.answer(f"✅ {qs:02d}:00–{val:02d}:00")
        s = await get_settings(chat_id)
        await _refresh_settings(q, s); return


# ═══════════════════════════════════════════════════════════════════════════════
# Max per cycle
# ═══════════════════════════════════════════════════════════════════════════════

def _maxpc_text(cur: int) -> str:
    lines = [
        "📬 *حد الإشعارات لكل دورة*",
        _sep(),
        "",
        f"الحالي: *{cur}* إشعار/دورة",
        "",
        "_يمنع إغراق المحادثة بعشرات الإشعارات_",
        "",
        "اضغط للاختيار:",
    ]
    return "\n".join(lines)


def _maxpc_keyboard(cur: int) -> InlineKeyboardMarkup:
    opts = [1, 3, 5, 10, 15, 20, 30, 50]
    rows = []
    for i in range(0, len(opts), 4):
        rows.append([
            InlineKeyboardButton(f"{'✓' if v == cur else ''}{v}", callback_data=f"mpc:set:{v}")
            for v in opts[i:i+4]
        ])
    rows.append([InlineKeyboardButton("◀️ رجوع", callback_data="mpc:back")])
    return InlineKeyboardMarkup(rows)


async def callback_mpc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q       = update.callback_query
    await q.answer()
    if str(q.from_user.id) != str(CHAT_ID): return
    chat_id = str(q.message.chat_id)
    parts   = q.data.split(":", 2)

    if parts[1] == "back":
        s = await get_settings(chat_id)
        await _refresh_settings(q, s); return

    v = int(parts[2])
    await upsert_settings(chat_id, max_per_cycle=v)
    await q.answer(f"✅ {v}/دورة")
    s = await get_settings(chat_id)
    await _refresh_settings(q, s)


# ═══════════════════════════════════════════════════════════════════════════════
# /status  /stats  /on  /off  /wbs  /last  /check  /ping  /uptime  /reset
# ═══════════════════════════════════════════════════════════════════════════════

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    s       = await get_settings(str(update.effective_chat.id))
    active  = "🟢 يعمل" if s.get("active", 1) else "🔴 موقوف"
    wbs     = "✅ WBS فقط" if s.get("wbs_only") else "🔓 كل الشقق"
    price   = float(s.get("max_price") or 600)
    rooms   = float(s.get("min_rooms") or 0)
    n       = int(s.get("household_size") or 1)
    sources = _jl(s.get("sources"))
    areas   = _jl(s.get("areas"))
    qs      = int(s.get("quiet_start", -1))
    qe      = int(s.get("quiet_end",   -1))
    mpc     = int(s.get("max_per_cycle") or 10)
    jc_on   = bool(s.get("jobcenter_mode"))
    wg_on   = bool(s.get("wohngeld_mode"))
    reqs    = get_full_requirements(n)

    src_str  = ", ".join(SOURCE_META[s_][0] for s_ in ALL_SOURCES if not sources or s_ in sources)
    area_str = "كل برلين" if not areas else ", ".join(areas[:3]) + ("..." if len(areas) > 3 else "")
    rooms_s  = f">={rooms:.0f}" if rooms else "أي"
    qs_str   = f"{qs:02d}:00-{qe:02d}:00" if qs >= 0 else "—"
    jc_str   = f"✅ <={reqs['jc_price']:.0f}€ /{reqs['jc_size_max']}m2 /{reqs['jc_rooms_min']:.0f}غرف" if jc_on else "❌"
    wg_str   = f"✅ <={reqs['wg_price']:.0f}€ /{reqs['wg_rooms_min']:.0f}غرف" if wg_on else "❌"

    lines = [
        "📊 *الإعدادات الكاملة*",
        _sep(),
        "",
        f"🔔 الإشعارات:  {active}",
        f"🏠 الوضع:      {wbs}",
        f"💰 الإيجار:    <={price:.0f} €",
        f"🛏 الغرف:      {rooms_s}",
        f"📍 المناطق:    {area_str}",
        f"🌐 المواقع:    {src_str}",
        f"👥 الأسرة:     {n} {'فرد' if n==1 else 'أفراد'}",
        f"🏛 Jobcenter: {jc_str}",
        f"🏦 Wohngeld:  {wg_str}",
        f"📬 حد/دورة:   {mpc}",
        f"🌙 هدوء:      {qs_str}",
        "",
        "_/settings لتعديل الإعدادات_",
    ]
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    st = await get_stats()
    lines = [
        "📈 *إحصائيات البوت*",
        _sep(),
        "",
        f"📨 إشعارات مُرسلة:  {st.get('total_sent', 0)}",
        f"🔄 دورات كشط:      {st.get('total_cycles', 0)}",
        f"🗃 إعلانات محفوظة: {st.get('db_size', 0)}",
        f"🕐 آخر إشعار:      {_time_ago(st.get('last_sent_at'))}",
    ]
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)


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


async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    n = 5
    if context.args:
        try: n = min(int(context.args[0]), 15)
        except ValueError: pass
    rows = await get_recent_listings(n)
    if not rows:
        await update.message.reply_text("📭 لا توجد إعلانات.", reply_markup=MAIN_KEYBOARD); return
    lines = [f"🕐 *آخر {n} إعلانات*", _sep(), ""]
    for i, r in enumerate(rows, 1):
        price = f"{r['price']:.0f} €" if r.get("price") else "—"
        src   = SOURCE_META.get(r.get("source", ""), (r.get("source",""), "🔍", False))[0]
        title = (r.get("title") or "شقة").strip()[:40]
        url   = r.get("url","")
        lines.append(f"*{i}.* [{title}]({url})\n   {price} · {src} · {_time_ago(r.get('created_at'))}\n")
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True, reply_markup=MAIN_KEYBOARD)


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    await update.message.reply_text("🔍 جاري الفحص…", reply_markup=MAIN_KEYBOARD)
    from scrapers.circuit_breaker import all_statuses
    hmap   = {r["source"]: r for r in await get_all_health()}
    cb_map = {s_["name"]: s_ for s_ in all_statuses()}
    lines  = ["📊 *حالة المصادر*", _sep(), ""]
    ok = 0
    for src in ALL_SOURCES:
        name, icon, _ = SOURCE_META[src]
        row      = hmap.get(src)
        cb       = cb_map.get(src, {})
        cb_icon  = {"CLOSED": "🟢", "HALF": "🟡", "OPEN": "🔴"}.get(cb.get("state", "CLOSED"), "⚪")
        if not row:
            lines.append(f"⚪ {icon} *{name}* — لم يعمل {cb_icon}")
        elif row.get("status") == "ok":
            ok += 1
            lines.append(f"✅ {icon} *{name}* {row.get('listings_found',0)} · {_time_ago(row.get('last_run'))} {cb_icon}")
        else:
            lines.append(f"❌ {icon} *{name}* `{str(row.get('last_error',''))[:35]}` {cb_icon}")
    lines.append(f"\n📈 *{ok}/{len(ALL_SOURCES)}* يعمل")
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    import time
    t0  = time.monotonic()
    msg = await update.message.reply_text("🏓 ...")
    lat = (time.monotonic() - t0) * 1000
    from scheduler.runner import _cycle
    await msg.edit_text(
        f"🏓 Pong!\n⚡ `{lat:.0f}ms`\n🔄 دورة `#{_cycle}`",
        parse_mode=ParseMode.MARKDOWN)


async def cmd_uptime(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_owner(update): return await _deny(update)
    elapsed = _time.monotonic() - _BOT_START
    h, rem  = divmod(int(elapsed), 3600)
    m, sec  = divmod(rem, 60)
    started = _BOT_START_DT.strftime("%Y-%m-%d %H:%M UTC")
    st      = await get_stats()
    lines = [
        f"⏱ *{h}س {m}د {sec}ث*",
        f"🕐 بدأ: `{started}`",
        f"🔄 دورات: `{st.get('total_cycles',0)}`",
        f"📨 مُرسل: `{st.get('total_sent',0)}`",
    ]
    await update.message.reply_text(
        "\n".join(lines), parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)


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
        "🔄 *تم إعادة الإعدادات للافتراضي*",
        parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)


# ═══════════════════════════════════════════════════════════════════════════════
# Reply keyboard dispatcher
# ═══════════════════════════════════════════════════════════════════════════════

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mapping = {
        "📊 الحالة":     cmd_status,
        "📈 الإحصائيات": cmd_stats,
        "⚙️ إعدادات":   cmd_settings,
        "🔍 المصادر":    cmd_sources,
        "✅ WBS فقط":    cmd_wbs_on,
        "🔓 كل الشقق":   cmd_wbs_off,
        "🟢 تشغيل":      cmd_on,
        "🔴 إيقاف":      cmd_off,
    }
    fn = mapping.get(update.message.text)
    if fn:
        await fn(update, context)


# ═══════════════════════════════════════════════════════════════════════════════
# Notification formatter
# ═══════════════════════════════════════════════════════════════════════════════

def _clean(t, maxlen: int = 70) -> str:
    import re
    t = re.sub(r"\s+", " ", str(t or ""))
    t = re.sub(r"\s*\|\s*", ", ", t)
    t = re.sub(r",\s*,+", ",", t)
    return t.strip(" ,|•–-/")[:maxlen].strip()


def format_listing(listing: dict) -> tuple:
    src      = listing.get("source", "")
    name, icon, is_gov = SOURCE_META.get(src, (src.title(), "🔍", False))
    src_type = "🏛 حكومية" if is_gov else "🔍 خاصة"

    price = listing.get("price")
    p_str = f"{price:,.0f} €".replace(",", ".") if isinstance(price, (int, float)) else None
    ppm2  = listing.get("price_per_m2")
    if p_str and ppm2:
        p_str += f"  (~{ppm2} €/m2)"

    rooms = listing.get("rooms")
    r_str = (str(int(rooms)) if rooms == int(rooms) else str(rooms)) if rooms else None
    size  = listing.get("size_m2")
    s_str = f"{size:.0f} m2" if size else None
    loc   = _clean(listing.get("district") or listing.get("location") or "Berlin")

    wbs_level = listing.get("wbs_level")
    wbs_line  = f"📋 WBS: ✅ {wbs_level}" if wbs_level else "📋 WBS: ❌ غير مطلوب"
    soc_badge = listing.get("social_badge", "")

    parts = [f"🏢 *{name}* — {src_type}\n"]
    if loc:                       parts.append(f"📍 الموقع:  {loc}")
    if p_str:                     parts.append(f"💰 الإيجار: {p_str}")
    if r_str:                     parts.append(f"🛏 الغرف:   {r_str}")
    if s_str:                     parts.append(f"📐 المساحة: {s_str}")
    if listing.get("floor"):      parts.append(f"🏢 الطابق:  {listing['floor']}")
    if listing.get("available_from"): parts.append(f"📅 الإتاحة: {listing['available_from']}")
    parts.append(wbs_line)
    if soc_badge: parts.append(soc_badge)

    msg = "\n".join(parts).strip()
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
    app.add_handler(CommandHandler("start",     cmd_start))
    app.add_handler(CommandHandler("get_chat_id", cmd_get_chat_id))
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
    app.add_handler(CallbackQueryHandler(callback_cfg,       pattern="^cfg:"))
    app.add_handler(CallbackQueryHandler(callback_wbs_level, pattern="^wlvl:"))
    app.add_handler(CallbackQueryHandler(callback_price,     pattern="^price:"))
    app.add_handler(CallbackQueryHandler(callback_rooms,     pattern="^rooms:"))
    app.add_handler(CallbackQueryHandler(callback_src,       pattern="^src:"))
    app.add_handler(CallbackQueryHandler(callback_area,      pattern="^area:"))
    app.add_handler(CallbackQueryHandler(callback_social,    pattern="^soc:"))
    app.add_handler(CallbackQueryHandler(callback_household, pattern="^hh:"))
    app.add_handler(CallbackQueryHandler(callback_schedule,  pattern="^sch:"))
    app.add_handler(CallbackQueryHandler(callback_mpc,       pattern="^mpc:"))
    app.add_handler(MessageHandler(tg_filters.TEXT & ~tg_filters.COMMAND, handle_text))
    return app
