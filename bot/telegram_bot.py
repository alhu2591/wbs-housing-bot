"""
Telegram UI (inline keyboards) + sending listings.

The main app (`main.py`) runs the scrape scheduler; this module:
1) provides interactive filter/source/settings menus
2) persists changes to `data/config.json`
3) notifies the scheduler to rescrape immediately when relevant
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from scraper.registry import ALL_SOURCE_IDS
from utils.config_store import save_runtime_config
from utils.fetch_runtime import set_fetch_runtime
from utils.filters import BERLIN_DISTRICT_ALIASES, normalize_districts

logger = logging.getLogger(__name__)

_CFG: dict[str, Any] = {}

BOT_COMMANDS = [
    BotCommand("start", "بدء تشغيل البوت"),
    BotCommand("status", "عرض الإعدادات الحالية"),
    BotCommand("settings", "فتح لوحة الإعدادات"),
    BotCommand("ping", "فحص حالة البوت"),
]

_runtime_on_interval_change: Callable[[int], None] | None = None
_runtime_trigger_cycle: Callable[[], Awaitable[None]] | None = None

WBS_LEVEL_OPTIONS = [100, 120, 140, 160, 180, 200]

SOURCE_LABELS_AR: dict[str, str] = {
    "immoscout": "ImmobilienScout24",
    "immonet": "Immonet",
    "wggesucht": "WG-Gesucht",
    "ebay_kleinanzeigen": "eBay Kleinanzeigen",
    "vonovia": "Vonovia",
    "gewobag": "Gewobag",
    "deutschewohnen": "Deutsche Wohnen",
    "wohnungsgilde": "Wohnungsgilde",
    "gesobau": "GESOBAU",
    "howoge": "Howoge",
    "degewo": "degewo",
    "wbm": "WBM",
    "berlinovo": "Berlinovo",
    "stadtundland": "STADT UND LAND",
    "immowelt": "Immowelt",
    "inberlinwohnen": "inberlinwohnen",
}


def set_runtime_callbacks(
    on_interval_change: Callable[[int], None],
    trigger_cycle: Callable[[], Awaitable[None]],
) -> None:
    global _runtime_on_interval_change, _runtime_trigger_cycle
    _runtime_on_interval_change = on_interval_change
    _runtime_trigger_cycle = trigger_cycle


def set_config(cfg: dict[str, Any]) -> None:
    global _CFG
    _CFG = dict(cfg or {})


def get_config() -> dict[str, Any]:
    return _CFG


def _persist_cfg() -> None:
    try:
        save_runtime_config(_CFG)
        set_fetch_runtime(_CFG)
    except Exception as e:
        logger.warning("persist runtime config failed: %s", e)


def _fmt_maybe_int(v: Any) -> str:
    if v is None:
        return "معطل"
    try:
        fv = float(v)
        if fv.is_integer():
            return str(int(fv))
        return str(fv).rstrip("0").rstrip(".")
    except Exception:
        return str(v)


def _fmt_price(v: Any) -> str:
    if v is None:
        return "معطل"
    try:
        return f"{int(float(v))}"
    except Exception:
        return str(v)


def format_listing_caption(listing: dict[str, Any]) -> str:
    title = str(listing.get("title") or "Listing").strip()
    price = listing.get("price")
    price_s = f"{int(price)} €" if price is not None else "—"
    loc = str(listing.get("location") or "").strip()
    dist = str(listing.get("district") or "").strip()
    city = str(listing.get("city") or "").strip()
    loc_line = ", ".join(x for x in (loc, dist, city) if x) or "—"
    sz = listing.get("size_m2")
    rooms = listing.get("rooms")
    sz_s = f"{sz:.0f} m²" if sz is not None else "—"
    r_s = str(rooms) if rooms is not None else "—"
    wbs_level = listing.get("wbs_level")
    wbs = str(listing.get("wbs_label") or ("نعم" if listing.get("trusted_wbs") else "—"))
    url = str(listing.get("url") or "").strip()
    desc = str(listing.get("description") or "").strip()
    if len(desc) > 400:
        desc = desc[:397] + "…"
    lines = [
        title,
        f"السعر: {price_s}",
        f"الموقع: {loc_line}",
        f"المساحة: {sz_s} · الغرف: {r_s}",
        f"WBS: {wbs}" + (f" (المستوى: {wbs_level})" if wbs_level is not None else ""),
    ]
    if desc:
        lines.append("")
        lines.append(desc)
    if url:
        lines.append("")
        lines.append(url)
    text = "\n".join(lines)
    if len(text) > 1024:
        text = text[:1021] + "…"
    return text


def _menu_main(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    city = cfg.get("city") or ""
    selected_districts = normalize_districts(cfg.get("districts") or [])
    max_price = cfg.get("max_price")
    min_size = cfg.get("min_size")
    rooms = cfg.get("rooms")
    wbs_required = bool(cfg.get("wbs_required", False))
    wbs_level = cfg.get("wbs_level")
    jobcenter_required = bool(cfg.get("jobcenter_required", False))
    wohnungsgilde_required = bool(cfg.get("wohnungsgilde_required", False))
    sources = cfg.get("sources") or []
    notify_enabled = bool(cfg.get("notify_enabled", True))
    send_images = bool(cfg.get("send_images", False))
    max_images = int(cfg.get("max_images") or 5)

    text = (
        "بوت سكن برلين (WBS)\n\n"
        f"المدينة: {city or 'الكل'}\n"
        f"المناطق المختارة: {len(selected_districts)}\n"
        f"أقصى سعر: {_fmt_price(max_price)} €\n"
        f"أقل مساحة: {_fmt_maybe_int(min_size)} م²\n"
        f"أقل عدد غرف: {_fmt_maybe_int(rooms)}\n"
        f"WBS مطلوب: {'نعم' if wbs_required else 'لا'}\n"
        f"مستوى WBS <= {wbs_level if wbs_level is not None else 'معطل'}\n"
        f"Jobcenter: {'مفعل' if jobcenter_required else 'معطل'} | Wohnungsgilde: {'مفعل' if wohnungsgilde_required else 'معطل'}\n"
        f"المصادر المفعلة: {len(sources)}\n"
        f"الإشعارات: {'مفعلة' if notify_enabled else 'متوقفة'}\n"
        f"الصور: {'نعم' if send_images else 'لا'} (الحد الأقصى {max_images})\n"
        f"الفاصل الزمني: {int(cfg.get('interval_minutes') or 10)} دقيقة\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("الفلاتر", callback_data="ui:filters")],
            [InlineKeyboardButton("مصادر السكن", callback_data="ui:sources")],
            [InlineKeyboardButton("الإشعارات", callback_data="ui:notify")],
            [InlineKeyboardButton("الصور والوسائط", callback_data="ui:media")],
            [InlineKeyboardButton("الامتثال والتقنية", callback_data="ui:ethics")],
        ]
    )
    return text, kb


def _menu_filters(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    city = cfg.get("city") or ""
    selected_districts = normalize_districts(cfg.get("districts") or [])
    max_price = cfg.get("max_price")
    min_size = cfg.get("min_size")
    rooms = cfg.get("rooms")
    wbs_required = bool(cfg.get("wbs_required", False))
    wbs_level = cfg.get("wbs_level")
    jobcenter_required = bool(cfg.get("jobcenter_required", False))
    wohnungsgilde_required = bool(cfg.get("wohnungsgilde_required", False))
    kw_inc = cfg.get("keywords_include") or []
    kw_exc = cfg.get("keywords_exclude") or []

    text = (
        "إعدادات الفلاتر\n\n"
        f"المدينة: {city or 'الكل'}\n"
        f"المناطق: {len(selected_districts)}\n"
        f"أقصى سعر: {_fmt_price(max_price)} €\n"
        f"أقل مساحة: {_fmt_maybe_int(min_size)} م²\n"
        f"أقل عدد غرف: {_fmt_maybe_int(rooms)}\n"
        f"WBS مطلوب: {'نعم' if wbs_required else 'لا'}\n"
        f"مستوى WBS <= {wbs_level if wbs_level is not None else 'معطل'}\n"
        f"Jobcenter: {'مفعل' if jobcenter_required else 'معطل'} | Wohnungsgilde: {'مفعل' if wohnungsgilde_required else 'معطل'}\n"
        f"الكلمات المفتاحية: تضمين {len(kw_inc)} | استبعاد {len(kw_exc)}\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"المدينة: {city or 'الكل'}", callback_data="ui:prompt:city")],
            [InlineKeyboardButton(f"اختيار المناطق ({len(selected_districts)})", callback_data="ui:districts")],
            [
                InlineKeyboardButton("-50 €", callback_data="ui:delta:max_price:-50"),
                InlineKeyboardButton("+50 €", callback_data="ui:delta:max_price:50"),
            ],
            [
                InlineKeyboardButton("تحديد أقصى سعر", callback_data="ui:prompt:max_price"),
                InlineKeyboardButton("تعطيل أقصى سعر", callback_data="ui:disable:max_price"),
            ],
            [
                InlineKeyboardButton("-5 m²", callback_data="ui:delta:min_size:-5"),
                InlineKeyboardButton("+5 m²", callback_data="ui:delta:min_size:5"),
            ],
            [
                InlineKeyboardButton("تحديد أقل مساحة", callback_data="ui:prompt:min_size"),
                InlineKeyboardButton("تعطيل أقل مساحة", callback_data="ui:disable:min_size"),
            ],
            [
                InlineKeyboardButton("-1 غرفة", callback_data="ui:delta:rooms:-1"),
                InlineKeyboardButton("+1 غرفة", callback_data="ui:delta:rooms:1"),
            ],
            [
                InlineKeyboardButton("تحديد عدد الغرف", callback_data="ui:prompt:rooms"),
                InlineKeyboardButton("تعطيل الغرف", callback_data="ui:disable:rooms"),
            ],
            [
                InlineKeyboardButton(f"WBS: {'نعم' if wbs_required else 'لا'}", callback_data="ui:toggle:wbs_required"),
                InlineKeyboardButton("الكلمات المفتاحية", callback_data="ui:keywords"),
            ],
            [
                InlineKeyboardButton(f"مستوى WBS: {wbs_level if wbs_level is not None else 'معطل'}", callback_data="ui:wbs_level"),
            ],
            [
                InlineKeyboardButton(
                    f"Jobcenter: {'مفعل' if jobcenter_required else 'معطل'}",
                    callback_data="ui:toggle:jobcenter_required",
                ),
                InlineKeyboardButton(
                    f"Wohnungsgilde: {'مفعل' if wohnungsgilde_required else 'معطل'}",
                    callback_data="ui:toggle:wohnungsgilde_required",
                ),
            ],
            [InlineKeyboardButton("رجوع", callback_data="ui:main")],
        ]
    )
    return text, kb


def _menu_districts(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    selected = set(normalize_districts(cfg.get("districts") or []))
    district_names = list(BERLIN_DISTRICT_ALIASES.keys())
    text = (
        "اختيار مناطق برلين (اختيار متعدد)\n\n"
        f"المختار: {len(selected)}/{len(district_names)}\n"
        "ملاحظة: سيتم إرسال الإعلانات المطابقة لمناطقك المختارة فقط."
    )
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for name in district_names:
        on = name in selected
        label = ("مفعّل · " if on else "معطّل · ") + name
        row.append(InlineKeyboardButton(label, callback_data=f"ui:toggle_district:{name}"))
        if len(row) == 1:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton("تفعيل كل المناطق", callback_data="ui:districts:all"),
            InlineKeyboardButton("إلغاء كل المناطق", callback_data="ui:districts:none"),
        ]
    )
    rows.append([InlineKeyboardButton("رجوع", callback_data="ui:filters")])
    return text, InlineKeyboardMarkup(rows)


def _menu_wbs_level(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    lvl = cfg.get("wbs_level")
    text = "فلتر مستوى WBS\n\n"
    if lvl is not None:
        text += f"المستوى المفعل: <= {lvl}"
    else:
        text += "المستوى: معطل"
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for opt in WBS_LEVEL_OPTIONS:
        label = f"{'✓' if lvl == opt else '·'} {opt}"
        row.append(InlineKeyboardButton(label, callback_data=f"ui:set_wbs_level:{opt}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("تعطيل المستوى", callback_data="ui:set_wbs_level:none")])
    rows.append([InlineKeyboardButton("رجوع", callback_data="ui:filters")])
    return text, InlineKeyboardMarkup(rows)


def _menu_keywords(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    kw_inc = cfg.get("keywords_include") or []
    kw_exc = cfg.get("keywords_exclude") or []

    def _sample(items: list[str]) -> str:
        if not items:
            return "—"
        s = ", ".join(items[:6])
        if len(items) > 6:
            s += ", …"
        return s

    text = (
        "الكلمات المفتاحية (مطابقة جزئية)\n\n"
        f"تضمين ({len(kw_inc)}): {_sample(kw_inc)}\n"
        f"استبعاد ({len(kw_exc)}): {_sample(kw_exc)}\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("إضافة تضمين", callback_data="ui:prompt:kw_include"),
                InlineKeyboardButton("مسح التضمين", callback_data="ui:clear:kw_include"),
            ],
            [
                InlineKeyboardButton("إضافة استبعاد", callback_data="ui:prompt:kw_exclude"),
                InlineKeyboardButton("مسح الاستبعاد", callback_data="ui:clear:kw_exclude"),
            ],
            [InlineKeyboardButton("رجوع", callback_data="ui:filters")],
        ]
    )
    return text, kb


def _menu_sources(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    enabled = set(cfg.get("sources") or [])
    text = (
        "اختيار مصادر السكن\n\n"
        "المصادر المفعلة يتم سحبها تلقائيا في الدورة التالية.\n"
        f"المفعل: {len(enabled)}/{len(ALL_SOURCE_IDS)}"
    )

    buttons = []
    for sid in ALL_SOURCE_IDS:
        on = sid in enabled
        label = ("مفعّل · " if on else "معطّل · ") + SOURCE_LABELS_AR.get(sid, sid)
        buttons.append(InlineKeyboardButton(label, callback_data=f"ui:toggle_src:{sid}"))

    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for b in buttons:
        row.append(b)
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton("تفعيل الكل", callback_data="ui:sources:all"),
            InlineKeyboardButton("تعطيل الكل", callback_data="ui:sources:none"),
        ]
    )
    rows.append([InlineKeyboardButton("رجوع", callback_data="ui:main")])

    kb = InlineKeyboardMarkup(rows)
    return text, kb


def _menu_notify(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    notify_enabled = bool(cfg.get("notify_enabled", True))
    interval = int(cfg.get("interval_minutes") or 10)

    text = (
        "الإشعارات\n\n"
        f"الحالة: {'مفعلة' if notify_enabled else 'متوقفة'}\n"
        f"الفاصل الزمني: {interval} دقيقة\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("-5", callback_data="ui:delta:interval_minutes:-5"),
                InlineKeyboardButton("+5", callback_data="ui:delta:interval_minutes:5"),
            ],
            [
                InlineKeyboardButton("تحديد الفاصل الزمني", callback_data="ui:prompt:interval_minutes"),
                InlineKeyboardButton("رجوع", callback_data="ui:main"),
            ],
            [InlineKeyboardButton(f"الإشعارات: {'مفعلة' if notify_enabled else 'متوقفة'}", callback_data="ui:toggle:notify_enabled")],
        ]
    )
    return text, kb


def _menu_media(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    send_images = bool(cfg.get("send_images", False))
    max_images = int(cfg.get("max_images") or 5)

    text = (
        "الصور والوسائط\n\n"
        f"إرسال الصور: {'نعم' if send_images else 'لا'}\n"
        f"الحد الأقصى للصور لكل إعلان: {max_images}\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"إرسال الصور: {'نعم' if send_images else 'لا'}", callback_data="ui:toggle:send_images")],
            [
                InlineKeyboardButton("-1", callback_data="ui:delta:max_images:-1"),
                InlineKeyboardButton("+1", callback_data="ui:delta:max_images:1"),
            ],
            [
                InlineKeyboardButton("تحديد الحد الأقصى للصور", callback_data="ui:prompt:max_images"),
                InlineKeyboardButton("رجوع", callback_data="ui:main"),
            ],
        ]
    )
    return text, kb


def _menu_ethics(cfg: dict[str, Any]) -> tuple[str, InlineKeyboardMarkup]:
    rr = cfg.get("respect_robots")
    if rr is None:
        rr = True
    pw = bool(cfg.get("use_playwright"))
    ex = cfg.get("exclude_senior_housing")
    if ex is None:
        ex = True

    text = (
        "الامتثال والتقنية\n\n"
        f"احترام robots.txt: {'نعم' if rr else 'لا'}\n"
        f"Playwright (صفحات تعتمد JS): {'مفعل' if pw else 'معطل'}\n"
        f"استبعاد سكن المسنين/الرعاية: {'نعم' if ex else 'لا'}\n\n"
        "Playwright اختياري وثقيل على Termux — ثبّت الحزمة فقط إذا احتجته.\n"
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"robots.txt: {'نعم' if rr else 'لا'}",
                    callback_data="ui:toggle:respect_robots",
                )
            ],
            [
                InlineKeyboardButton(
                    f"Playwright: {'مفعل' if pw else 'معطل'}",
                    callback_data="ui:toggle:use_playwright",
                )
            ],
            [
                InlineKeyboardButton(
                    f"استبعاد مسنين/رعاية: {'نعم' if ex else 'لا'}",
                    callback_data="ui:toggle:exclude_senior_housing",
                )
            ],
            [InlineKeyboardButton("رجوع", callback_data="ui:main")],
        ]
    )
    return text, kb


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config()
    text, kb = _menu_main(cfg)
    await update.message.reply_text(text, reply_markup=kb)


async def cmd_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config()
    text, kb = _menu_main(cfg)
    await update.message.reply_text(text, reply_markup=kb)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = get_config()
    text = (
        "📋 الإعدادات الحالية\n\n"
        f"المدينة: {cfg.get('city')}\n"
        f"المناطق: {cfg.get('districts')}\n"
        f"أقصى سعر (€): {cfg.get('max_price')}\n"
        f"أقل مساحة (م²): {cfg.get('min_size')}\n"
        f"أقل غرف: {cfg.get('rooms')}\n"
        f"WBS مطلوب: {cfg.get('wbs_required')}\n"
        f"مستوى WBS: {cfg.get('wbs_level')}\n"
        f"Jobcenter: {cfg.get('jobcenter_required')}\n"
        f"Wohnungsgilde: {cfg.get('wohnungsgilde_required')}\n"
        f"الفاصل (دقيقة): {cfg.get('interval_minutes')}\n"
        f"الإشعارات: {cfg.get('notify_enabled')}\n"
        f"إرسال الصور: {cfg.get('send_images')}\n"
        f"حد الصور: {cfg.get('max_images')}\n"
        f"احترام robots: {cfg.get('respect_robots')}\n"
        f"Playwright: {cfg.get('use_playwright')}\n"
        f"تزامن السحب: {cfg.get('scrape_concurrency')}\n"
        f"المصادر: {cfg.get('sources')}\n"
    )
    await update.message.reply_text(text)


async def cmd_ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("البوت يعمل بشكل طبيعي")


def _parse_optional_float(text: str) -> float | None:
    t = (text or "").strip()
    if not t:
        return None
    if t.lower() in {"none", "off", "disabled", "aus", "null"}:
        return None
    return float(t.replace(",", "."))


def _apply_numeric_delta(cfg: dict[str, Any], key: str, delta: float) -> dict[str, Any]:
    cur = cfg.get(key)
    base = float(cur) if cur is not None else 0.0
    nxt = base + float(delta)
    if key in {"max_price"}:
        if nxt <= 0:
            cfg[key] = None
        else:
            cfg[key] = float(nxt)
    elif key in {"min_size"}:
        if nxt <= 0:
            cfg[key] = None
        else:
            cfg[key] = float(nxt)
    elif key in {"rooms"}:
        if nxt <= 0:
            cfg[key] = None
        else:
            cfg[key] = float(nxt)
    elif key in {"interval_minutes"}:
        if nxt < 5:
            nxt = 5
        if nxt > 60:
            nxt = 60
        cfg[key] = int(nxt)
    elif key in {"max_images"}:
        if nxt < 1:
            nxt = 1
        if nxt > 10:
            nxt = 10
        cfg[key] = int(nxt)
    else:
        cfg[key] = nxt
    return cfg


async def _maybe_trigger_cycle() -> None:
    cb = _runtime_trigger_cycle
    if not cb:
        return
    try:
        res = cb()
        if asyncio.iscoroutine(res):
            await res
    except Exception as e:
        logger.warning("trigger_cycle failed: %s", e)


def _set_cfg(mut: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    global _CFG
    new_cfg = dict(_CFG)
    mut(new_cfg)
    # Avoid accidental aliasing of lists.
    for k in ("sources", "keywords_include", "keywords_exclude", "wbs_filter", "districts"):
        if k in new_cfg and isinstance(new_cfg[k], list):
            new_cfg[k] = list(new_cfg[k])
    # Normalize sources uniqueness.
    if "sources" in new_cfg and isinstance(new_cfg["sources"], list):
        seen: set[str] = set()
        uniq: list[str] = []
        for s in new_cfg["sources"]:
            ss = str(s).strip()
            if not ss or ss in seen:
                continue
            seen.add(ss)
            uniq.append(ss)
        new_cfg["sources"] = uniq
    if "districts" in new_cfg and isinstance(new_cfg["districts"], list):
        new_cfg["districts"] = normalize_districts(new_cfg["districts"])

    _CFG = new_cfg
    _persist_cfg()
    return _CFG


async def _show_menu_for_query(
    query_update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    menu_id: str,
) -> None:
    cfg = get_config()

    if menu_id == "main":
        text, kb = _menu_main(cfg)
    elif menu_id == "filters":
        text, kb = _menu_filters(cfg)
    elif menu_id == "keywords":
        text, kb = _menu_keywords(cfg)
    elif menu_id == "districts":
        text, kb = _menu_districts(cfg)
    elif menu_id == "wbs_level":
        text, kb = _menu_wbs_level(cfg)
    elif menu_id == "sources":
        text, kb = _menu_sources(cfg)
    elif menu_id == "notify":
        text, kb = _menu_notify(cfg)
    elif menu_id == "media":
        text, kb = _menu_media(cfg)
    elif menu_id == "ethics":
        text, kb = _menu_ethics(cfg)
    else:
        text, kb = _menu_main(cfg)

    q = query_update.callback_query
    try:
        await q.edit_message_text(text=text, reply_markup=kb)
    except Exception:
        await q.message.reply_text(text=text, reply_markup=kb)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not query.data:
        return
    data = query.data
    await query.answer()

    if data == "ui:main":
        await _show_menu_for_query(update, context, "main")
        return
    if data == "ui:filters":
        await _show_menu_for_query(update, context, "filters")
        return
    if data == "ui:keywords":
        await _show_menu_for_query(update, context, "keywords")
        return
    if data == "ui:districts":
        await _show_menu_for_query(update, context, "districts")
        return
    if data == "ui:wbs_level":
        await _show_menu_for_query(update, context, "wbs_level")
        return
    if data == "ui:sources":
        await _show_menu_for_query(update, context, "sources")
        return
    if data == "ui:notify":
        await _show_menu_for_query(update, context, "notify")
        return
    if data == "ui:media":
        await _show_menu_for_query(update, context, "media")
        return
    if data == "ui:ethics":
        await _show_menu_for_query(update, context, "ethics")
        return

    parts = data.split(":")
    # Toggle booleans: ui:toggle:key
    if parts[0] == "ui" and parts[1] == "toggle" and len(parts) == 3:
        key = parts[2]
        cfg_now = get_config()
        cur = cfg_now.get(key)
        if key == "respect_robots":
            cur = True if cur is None else bool(cur)
        elif key == "exclude_senior_housing":
            cur = True if cur is None else bool(cur)
        else:
            cur = bool(cur)
        new_val = not cur
        _set_cfg(lambda c: c.__setitem__(key, new_val))
        if key in {"notify_enabled", "jobcenter_required", "wohnungsgilde_required", "wbs_required"}:
            await _maybe_trigger_cycle()
        if key in {"jobcenter_required", "wohnungsgilde_required", "wbs_required"}:
            sub = "filters"
        elif key in {"respect_robots", "use_playwright", "exclude_senior_housing"}:
            sub = "ethics"
        elif key in {"notify_enabled", "send_images"}:
            sub = "main"
        else:
            sub = "main"
        await _show_menu_for_query(update, context, sub)
        return

    # Navigation to prompt: ui:prompt:key
    if parts[0] == "ui" and parts[1] == "prompt" and len(parts) == 3:
        key = parts[2]
        context.chat_data["pending_cfg_action"] = {"type": "prompt", "key": key}
        await query.message.reply_text(
            _prompt_text_for_key(key),
        )
        return

    # Disable numeric filters: ui:disable:key
    if parts[0] == "ui" and parts[1] == "disable" and len(parts) == 3:
        key = parts[2]
        _set_cfg(lambda c: c.__setitem__(key, None))
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "filters" if key in {"city", "max_price", "min_size", "rooms", "wbs_required"} else "main")
        return

    # Clear keywords:
    if parts[0] == "ui" and parts[1] == "clear" and len(parts) == 3:
        key = parts[2]  # kw_include / kw_exclude
        if key == "kw_include":
            _set_cfg(lambda c: c.__setitem__("keywords_include", []))
        elif key == "kw_exclude":
            _set_cfg(lambda c: c.__setitem__("keywords_exclude", []))
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "keywords")
        return

    # Deltas: ui:delta:key:value
    if parts[0] == "ui" and parts[1] == "delta" and len(parts) == 4:
        key = parts[2]
        try:
            delta = float(parts[3])
        except Exception:
            delta = 0.0

        was_interval = key == "interval_minutes"
        _set_cfg(lambda c: _apply_numeric_delta(c, key, delta))
        if was_interval and _runtime_on_interval_change:
            _runtime_on_interval_change(int(float(get_config().get("interval_minutes") or 10)))
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "main")
        return

    # Toggle WBS required (handled above) / but we also keep this explicit for safety
    if data.startswith("ui:toggle_src:"):
        sid = data.split(":", 2)[2]
        def mut(c: dict[str, Any]) -> None:
            enabled = set(c.get("sources") or [])
            if sid in enabled:
                enabled.remove(sid)
            else:
                enabled.add(sid)
            c["sources"] = sorted(enabled)
        _set_cfg(mut)
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "sources")
        return

    if data == "ui:sources:all":
        _set_cfg(lambda c: c.__setitem__("sources", list(ALL_SOURCE_IDS)))
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "sources")
        return

    if data == "ui:sources:none":
        _set_cfg(lambda c: c.__setitem__("sources", []))
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "sources")
        return

    if data.startswith("ui:toggle_district:"):
        district = data.split(":", 2)[2]
        def _mut_district(c: dict[str, Any]) -> None:
            cur = set(normalize_districts(c.get("districts") or []))
            normalized = normalize_districts([district])
            if not normalized:
                return
            n = normalized[0]
            if n in cur:
                cur.remove(n)
            else:
                cur.add(n)
            c["districts"] = sorted(cur)
        _set_cfg(_mut_district)
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "districts")
        return

    if data == "ui:districts:all":
        _set_cfg(lambda c: c.__setitem__("districts", list(BERLIN_DISTRICT_ALIASES.keys())))
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "districts")
        return

    if data == "ui:districts:none":
        _set_cfg(lambda c: c.__setitem__("districts", []))
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "districts")
        return

    if data.startswith("ui:set_wbs_level:"):
        raw = data.split(":", 2)[2]
        def _mut_wbs(c: dict[str, Any]) -> None:
            if raw == "none":
                c["wbs_level"] = None
                return
            try:
                lvl = int(raw)
            except Exception:
                return
            if lvl < 100:
                lvl = 100
            if lvl > 200:
                lvl = 200
            c["wbs_level"] = lvl
        _set_cfg(_mut_wbs)
        await _maybe_trigger_cycle()
        await _show_menu_for_query(update, context, "wbs_level")
        return

    # Fallback
    await _show_menu_for_query(update, context, "main")


def _prompt_text_for_key(key: str) -> str:
    if key == "city":
        return "اكتب اسم المدينة (مثال: Berlin). رسالة فارغة = كل المدن."
    if key == "max_price":
        return "أرسل أقصى سعر باليورو (مثال: 700) أو none للتعطيل."
    if key == "min_size":
        return "أرسل أقل مساحة بالمتر (مثال: 30) أو none للتعطيل."
    if key == "rooms":
        return "أرسل أقل عدد غرف (مثال: 1) أو none للتعطيل."
    if key == "interval_minutes":
        return "أرسل فترة الإشعارات بالدقائق (5-60)."
    if key == "max_images":
        return "أرسل الحد الأقصى للصور (1-10)."
    if key == "kw_include":
        return "أرسل كلمة تضمين (مطابقة جزئية)."
    if key == "kw_exclude":
        return "أرسل كلمة استبعاد (مطابقة جزئية)."
    return "أرسل القيمة المطلوبة."


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    pending = context.chat_data.get("pending_cfg_action")
    if not pending:
        return

    key = pending.get("key")
    text = update.message.text.strip()

    context.chat_data.pop("pending_cfg_action", None)

    def mut(c: dict[str, Any]) -> None:
        if key == "city":
            c["city"] = str(text).strip()
        elif key == "max_price":
            v = _parse_optional_float(text)
            c["max_price"] = None if v is None or v <= 0 else float(v)
        elif key == "min_size":
            v = _parse_optional_float(text)
            c["min_size"] = None if v is None or v <= 0 else float(v)
        elif key == "rooms":
            v = _parse_optional_float(text)
            c["rooms"] = None if v is None or v <= 0 else float(v)
        elif key == "interval_minutes":
            val = _parse_optional_float(text)
            if val is None:
                return
            mins = int(val)
            if mins < 5:
                mins = 5
            if mins > 60:
                mins = 60
            c["interval_minutes"] = mins
        elif key == "max_images":
            val = _parse_optional_float(text)
            if val is None:
                return
            mi = int(val)
            if mi < 1:
                mi = 1
            if mi > 10:
                mi = 10
            c["max_images"] = mi
        elif key == "kw_include":
            item = str(text).strip()
            if item:
                c["keywords_include"] = (c.get("keywords_include") or []) + [item]
        elif key == "kw_exclude":
            item = str(text).strip()
            if item:
                c["keywords_exclude"] = (c.get("keywords_exclude") or []) + [item]

    _set_cfg(mut)

    if key == "interval_minutes" and _runtime_on_interval_change:
        _runtime_on_interval_change(int(float(get_config().get("interval_minutes") or 10)))

    await update.message.reply_text("تم تحديث الإعدادات. سيتم تطبيقها فوراً في دورة السحب التالية.")
    await _maybe_trigger_cycle()

    cfg = get_config()
    main_text, main_kb = _menu_main(cfg)
    await update.message.reply_text(main_text, reply_markup=main_kb)


def build_app(bot_token: str):
    app = ApplicationBuilder().token(bot_token).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("settings", cmd_settings))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("ping", cmd_ping))

    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


async def send_listing(
    bot,
    chat_id: str,
    listing: dict[str, Any],
    *,
    send_images: bool = True,
    max_photos: int = 5,
) -> bool:
    """Send one listing; use media group when images available."""
    caption = format_listing_caption(listing)
    url = str(listing.get("url") or "")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("فتح الرابط", url=url)]]) if url else None
    imgs = [u for u in (listing.get("images") or []) if isinstance(u, str) and u.startswith("http")]
    imgs = imgs[:max(1, min(max_photos, 10))]

    if send_images and len(imgs) >= 1:
        try:
            media: list[InputMediaPhoto] = []
            for i, u in enumerate(imgs[:max_photos]):
                if i == 0:
                    media.append(InputMediaPhoto(media=u, caption=caption))
                else:
                    media.append(InputMediaPhoto(media=u))
            await bot.send_media_group(chat_id=chat_id, media=media)
            if kb:
                await bot.send_message(chat_id=chat_id, text="فتح الإعلان", reply_markup=kb)
            return True
        except Exception as e:
            logger.warning("send_media_group failed, fallback to text: %s", e)

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=kb,
            disable_web_page_preview=False,
        )
        return True
    except Exception as e:
        logger.error("send_message failed: %s", e)
        return False


__all__ = [
    "BOT_COMMANDS",
    "build_app",
    "format_listing_caption",
    "get_config",
    "send_listing",
    "set_config",
    "set_runtime_callbacks",
]
