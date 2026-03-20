"""
WBS Berlin v2.0 — Android App
Modern dark UI · Onboarding · Full customization
Pure stdlib + beautifulsoup4 only (no C extensions)
"""
import json, os, re, hashlib, threading, socket
import urllib.request, urllib.parse, ssl, time
from pathlib import Path
from typing import Optional

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from kivy.app import App
    from kivy.uix.screenmanager import ScreenManager, Screen, FadeTransition
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.gridlayout import GridLayout
    from kivy.uix.floatlayout import FloatLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.textinput import TextInput
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.togglebutton import ToggleButton
    from kivy.uix.widget import Widget
    from kivy.uix.popup import Popup
    from kivy.graphics import Color, RoundedRectangle, Rectangle, Line
    from kivy.clock import Clock
    from kivy.metrics import dp, sp
    from kivy.utils import get_color_from_hex
    from kivy.core.window import Window
    HAS_KIVY = True
except ImportError:
    HAS_KIVY = False

# ═══════════════════════════════════════════════════════════════════════
# Design Tokens
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    BG      = get_color_from_hex("#0A0A0A")
    BG2     = get_color_from_hex("#141414")
    BG3     = get_color_from_hex("#1E1E1E")
    BG4     = get_color_from_hex("#252525")
    PRIMARY = get_color_from_hex("#22C55E")  # green-500
    PRI_DIM = get_color_from_hex("#16A34A")  # green-600
    AMBER   = get_color_from_hex("#F59E0B")  # urgent
    PURPLE  = get_color_from_hex("#8B5CF6")  # gov sources
    BLUE    = get_color_from_hex("#3B82F6")  # private sources
    RED     = get_color_from_hex("#EF4444")  # error
    TEXT1   = get_color_from_hex("#F1F5F9")
    TEXT2   = get_color_from_hex("#94A3B8")
    TEXT3   = get_color_from_hex("#475569")
    DIVIDER = get_color_from_hex("#1E293B")
    WHITE   = (1, 1, 1, 1)
    TRANSP  = (0, 0, 0, 0)

    # Safe font size helper
    def fs(n): return sp(n)

# ═══════════════════════════════════════════════════════════════════════
# Storage
# ═══════════════════════════════════════════════════════════════════════
_sd          = Path(os.environ.get("EXTERNAL_STORAGE", "."))
CFG_FILE     = _sd / "wbs_v2_config.json"
SEEN_FILE    = _sd / "wbs_v2_seen.json"
FIRST_RUN    = _sd / "wbs_v2_first_run"
LISTINGS_CACHE = _sd / "wbs_v2_cache.json"

DEFAULTS = {
    "max_price": 700,
    "min_price": 0,
    "min_rooms": 0.0,
    "max_rooms": 0.0,       # 0 = any
    "min_size": 0,          # m²
    "max_size": 0,          # 0 = any
    "wbs_only": False,
    "wbs_level_min": 0,
    "wbs_level_max": 999,
    "household_size": 1,
    "jobcenter_mode": False,
    "wohngeld_mode": False,
    "sources": [],
    "areas": [],
    "sort_by": "score",     # score | price_asc | price_desc | newest
    "notify_new": True,
    "cache_hours": 1,
    "dark_mode": True,
}

_cfg_lock  = threading.Lock()
_seen_lock = threading.Lock()

def load_cfg() -> dict:
    try:
        with _cfg_lock:
            if CFG_FILE.exists():
                return {**DEFAULTS, **json.loads(CFG_FILE.read_text())}
    except Exception:
        pass
    return dict(DEFAULTS)

def save_cfg(c: dict) -> None:
    try:
        with _cfg_lock:
            CFG_FILE.write_text(json.dumps(c, indent=2, ensure_ascii=False))
    except Exception:
        pass

def load_seen() -> set:
    try:
        with _seen_lock:
            if SEEN_FILE.exists():
                return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        pass
    return set()

def save_seen(s: set) -> None:
    try:
        with _seen_lock:
            SEEN_FILE.write_text(json.dumps(list(s)[-5000:]))
    except Exception:
        pass

def load_cache() -> list:
    try:
        if LISTINGS_CACHE.exists():
            data = json.loads(LISTINGS_CACHE.read_text())
            # Check age
            if time.time() - data.get("ts", 0) < load_cfg().get("cache_hours", 1) * 3600:
                return data.get("listings", [])
    except Exception:
        pass
    return []

def save_cache(listings: list) -> None:
    try:
        LISTINGS_CACHE.write_text(json.dumps({"ts": time.time(), "listings": listings}, ensure_ascii=False))
    except Exception:
        pass

def is_first_run() -> bool:
    return not FIRST_RUN.exists()

def mark_done() -> None:
    try:
        FIRST_RUN.write_text("1")
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════════════
# Domain Data
# ═══════════════════════════════════════════════════════════════════════
SOURCES = {
    "gewobag":    ("Gewobag",         True,  PURPLE if HAS_KIVY else None),
    "degewo":     ("Degewo",          True,  PURPLE if HAS_KIVY else None),
    "gesobau":    ("Gesobau",         True,  PURPLE if HAS_KIVY else None),
    "wbm":        ("WBM",             True,  PURPLE if HAS_KIVY else None),
    "vonovia":    ("Vonovia",         True,  PURPLE if HAS_KIVY else None),
    "howoge":     ("Howoge",          True,  PURPLE if HAS_KIVY else None),
    "berlinovo":  ("Berlinovo",       True,  PURPLE if HAS_KIVY else None),
    "immoscout":  ("ImmoScout24",     False, BLUE   if HAS_KIVY else None),
    "kleinanz":   ("Kleinanzeigen",   False, BLUE   if HAS_KIVY else None),
}
GOV_SOURCES = {k for k, v in SOURCES.items() if v[1]}

BERLIN_AREAS = [
    "Mitte","Spandau","Pankow","Neukölln","Tempelhof","Schöneberg",
    "Steglitz","Zehlendorf","Charlottenburg","Wilmersdorf","Lichtenberg",
    "Marzahn","Hellersdorf","Treptow","Köpenick","Reinickendorf",
    "Friedrichshain","Kreuzberg","Prenzlauer Berg","Wedding","Moabit",
]

WBS_LEVELS = [100, 140, 160, 180, 200, 220]

JC_KDU = {1:549, 2:671, 3:789, 4:911, 5:1021, 6:1131}
WG_LIM = {1:580, 2:680, 3:800, 4:910, 5:1030, 6:1150, 7:1270}

def jc_limit(n: int) -> float:
    n = max(1, min(int(n), 10))
    return JC_KDU.get(min(n, 6), JC_KDU[6] + (n - 6) * 110)

def wg_limit(n: int) -> float:
    n = max(1, min(int(n), 10))
    return WG_LIM.get(min(n, 7), WG_LIM[7] + (n - 7) * 120)

FEATURES_DE = {
    "balkon":           "🌿 بلكونة",
    "terrasse":         "🌿 تراس",
    "dachterrasse":     "🌿 تراس علوي",
    "garten":           "🌱 حديقة",
    "aufzug":           "🛗 مصعد",
    "fahrstuhl":        "🛗 مصعد",
    "einbauküche":      "🍳 مطبخ مجهز",
    "keller":           "📦 مخزن",
    "abstellraum":      "📦 مخزن",
    "stellplatz":       "🚗 موقف",
    "tiefgarage":       "🚗 جراج",
    "barrierefrei":     "♿ بدون عوائق",
    "neubau":           "🏗 بناء جديد",
    "erstbezug":        "✨ أول سكن",
    "parkett":          "🪵 باركيه",
    "laminat":          "🪵 لامينيت",
    "fußbodenheizung":  "🌡 تدفئة أرضية",
    "fernwärme":        "🌡 تدفئة مركزية",
    "gasheizung":       "🔥 تدفئة غاز",
    "saniert":          "🔨 مجدد",
    "waschmaschine":    "🫧 غسالة",
    "badewanne":        "🛁 حوض استحمام",
    "sep. wc":          "🚽 حمام منفصل",
    "rolladen":         "🪟 ستائر",
    "videogegensprechanlage": "📹 إنترفون",
}

URGENT_KW = ["ab sofort", "sofort frei", "sofort verfügbar", "sofort beziehbar"]

MONTHS_AR = {
    "januar":"يناير","februar":"فبراير","märz":"مارس","april":"أبريل",
    "mai":"مايو","juni":"يونيو","juli":"يوليو","august":"أغسطس",
    "september":"سبتمبر","oktober":"أكتوبر","november":"نوفمبر","dezember":"ديسمبر",
}

# ═══════════════════════════════════════════════════════════════════════
# Network + Scraping
# ═══════════════════════════════════════════════════════════════════════
_SSL = ssl.create_default_context()
try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL.check_hostname = False
    _SSL.verify_mode    = ssl.CERT_NONE

_UA      = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/124.0"
_TIMEOUT = 15

def check_network() -> bool:
    try:
        socket.setdefaulttimeout(3)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        return True
    except Exception:
        return False

def _get(url: str, timeout: int = _TIMEOUT) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA,
            "Accept-Language": "de-DE,de;q=0.9",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        })
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
            raw = r.read()
            enc = r.headers.get_content_charset("utf-8")
            return raw.decode(enc, errors="replace")
    except Exception:
        return None

def _get_json(url: str, timeout: int = _TIMEOUT) -> Optional[object]:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA,
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
            return json.loads(r.read())
    except Exception:
        return None

# ── Parsing ───────────────────────────────────────────────────────────

def make_id(url: str) -> str:
    u = re.sub(r"[?#].*", "", url.strip().rstrip("/"))
    return hashlib.sha256(u.encode()).hexdigest()[:14]

def parse_price(raw) -> Optional[float]:
    if not raw:
        return None
    s = re.sub(r"[^\d\.,]", "", str(raw))
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        p = s.split(",")
        s = s.replace(",", ".") if len(p) == 2 and len(p[1]) <= 2 else s.replace(",", "")
    elif "." in s:
        p = s.split(".")
        if len(p) == 2 and len(p[1]) == 3:
            s = s.replace(".", "")
    try:
        v = float(s)
        return v if 50 < v < 8000 else None
    except ValueError:
        return None

def parse_rooms(raw) -> Optional[float]:
    if not raw:
        return None
    m = re.search(r"(\d+[.,]?\d*)", str(raw).replace(",", "."))
    try:
        v = float(m.group(1)) if m else None
        return v if v and 0.5 <= v <= 20 else None
    except (ValueError, AttributeError):
        return None

def enrich(title: str, desc: str) -> dict:
    t  = f"{title} {desc}".lower()
    out: dict = {}

    # Size
    for pat in [r"(\d[\d\.]*)\s*m[²2]", r"(\d[\d\.]*)\s*qm\b",
                r"wohnfläche[:\s]+(\d[\d\.]*)", r"ca\.?\s*(\d[\d\.]*)\s*m"]:
        m = re.search(pat, t)
        if m:
            try:
                v = float(m.group(1).replace(".", ""))
                if 15 < v < 500:
                    out["size_m2"] = v
                    break
            except ValueError:
                pass

    # Floor
    for pat, lbl in [
        (r"(\d+)\.\s*(?:og|obergeschoss|etage|stock)\b", lambda m: f"الطابق {m.group(1)}"),
        (r"\berdgeschoss\b|\beg\b(?!\w)", lambda _: "الطابق الأرضي"),
        (r"\bdachgeschoss\b|\bdg\b(?!\w)", lambda _: "الطابق العلوي"),
        (r"\bhochparterre\b", lambda _: "الطابق الأرضي المرتفع"),
        (r"\bpenthouse\b", lambda _: "بنتهاوس"),
    ]:
        mm = re.search(pat, t)
        if mm:
            out["floor"] = lbl(mm)
            break

    # Availability
    if any(k in t for k in URGENT_KW):
        out["available"] = "فوري 🔥"
    else:
        m = re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})", t)
        if m:
            out["available"] = f"من {m.group(1)}"
        else:
            m = re.search(r"q([1-4])[./\s]*(\d{4})", t)
            if m:
                qmap = {"1":"الربع الأول","2":"الربع الثاني",
                        "3":"الربع الثالث","4":"الربع الرابع"}
                out["available"] = f"{qmap[m.group(1)]} {m.group(2)}"
            else:
                mths = "|".join(MONTHS_AR)
                m = re.search(rf"ab\s+({mths})\s*(\d{{4}})?", t)
                if m:
                    out["available"] = f"من {MONTHS_AR[m.group(1)]} {m.group(2) or ''}".strip()

    # Deposit
    m = re.search(r"kaution[:\s]*(\d[\d\.,]*)\s*€?", t)
    if m:
        v = parse_price(m.group(1))
        if v:
            out["deposit"] = f"{v:.0f} €"
    else:
        m = re.search(r"(\d)\s*monatsmieten?\s*(?:kaution)?", t)
        if m:
            out["deposit"] = f"{m.group(1)} × الإيجار"

    # Heating
    if "fußbodenheizung" in t:
        out["heating"] = "🌡 تدفئة أرضية"
    elif "fernwärme" in t:
        out["heating"] = "🌡 تدفئة مركزية"
    elif "gasheizung" in t or " gas " in t:
        out["heating"] = "🔥 غاز"

    # WBS level
    mm = re.search(r"wbs[\s\-_]*(\d{2,3})", t)
    if mm:
        out["wbs_level_num"] = int(mm.group(1))

    # Features (deduplicated)
    seen_f: set = set()
    feats: list = []
    for kw, lbl in FEATURES_DE.items():
        if kw in t and lbl not in seen_f:
            seen_f.add(lbl)
            feats.append(lbl)
    if feats:
        out["features"] = feats

    return out

# ── Scrapers ──────────────────────────────────────────────────────────

def _scrape_gewobag() -> list:
    data = _get_json(
        "https://www.gewobag.de/wp-json/gewobag/v1/offers"
        "?type=wohnung&wbs=1&per_page=50")
    if not data:
        return []
    items = data if isinstance(data, list) else data.get("offers", [])
    result = []
    seen: set = set()
    for i in items:
        url = i.get("link") or i.get("url", "")
        if not url.startswith("http"):
            url = "https://www.gewobag.de" + url
        if url in seen:
            continue
        seen.add(url)
        t = i.get("title", "")
        title = t.get("rendered", "") if isinstance(t, dict) else str(t)
        desc  = str(i.get("beschreibung") or i.get("description") or "")
        extra = enrich(title, desc)
        result.append({
            "id": make_id(url), "url": url, "source": "gewobag",
            "trusted_wbs": True, "title": title[:80],
            "price": parse_price(i.get("gesamtmiete") or i.get("warmmiete")),
            "rooms": parse_rooms(i.get("zimmer")),
            "location": i.get("bezirk", "Berlin"),
            "wbs_label": "WBS erforderlich",
            "ts": time.time(), **extra,
        })
    return result

def _scrape_degewo() -> list:
    for api in [
        "https://immosuche.degewo.de/de/properties.json"
        "?property_type_id=1&categories[]=WBS&per_page=50",
        "https://immosuche.degewo.de/de/search.json?asset_classes[]=1&wbs=1",
    ]:
        data = _get_json(api)
        if not data:
            continue
        items = data if isinstance(data, list) else data.get("results", [])
        result = []
        seen: set = set()
        for i in items:
            url = i.get("path", "") or i.get("url", "")
            if not url.startswith("http"):
                url = "https://immosuche.degewo.de" + url
            if url in seen:
                continue
            seen.add(url)
            extra = enrich(i.get("title", ""), i.get("text", "") or "")
            result.append({
                "id": make_id(url), "url": url, "source": "degewo",
                "trusted_wbs": True, "title": i.get("title", "")[:80],
                "price": parse_price(i.get("warmmiete") or i.get("totalRent")),
                "rooms": parse_rooms(i.get("zimmer") or i.get("rooms")),
                "location": i.get("district", "Berlin"),
                "wbs_label": "WBS erforderlich",
                "ts": time.time(), **extra,
            })
        if result:
            return result
    return []

def _scrape_kleinanzeigen() -> list:
    if not HAS_BS4:
        return []
    html = _get("https://www.kleinanzeigen.de/s-wohnung-mieten/berlin/wbs/k0c203l3331")
    if not html or len(html) < 500:
        return []
    soup   = BeautifulSoup(html, "html.parser")
    result = []
    seen: set = set()
    for card in soup.select("article.aditem")[:25]:
        a = card.select_one("a.ellipsis,h2 a,h3 a")
        if not a:
            continue
        href = a.get("href", "")
        url  = ("https://www.kleinanzeigen.de" + href
                if href.startswith("/") else href)
        if url in seen:
            continue
        seen.add(url)
        t_tag = card.select_one("h2,h3")
        p_tag = card.select_one("[class*='price-shipping--price'],[class*='price']")
        title = (t_tag.get_text(strip=True) if t_tag else a.get_text(strip=True))[:80]
        desc  = card.get_text(" ", strip=True)
        extra = enrich(title, desc)
        result.append({
            "id": make_id(url), "url": url, "source": "kleinanz",
            "trusted_wbs": False, "title": title,
            "price": parse_price(p_tag.get_text() if p_tag else None),
            "rooms": None, "location": "Berlin", "wbs_label": "",
            "ts": time.time(), **extra,
        })
    return result

def _scrape_immoscout() -> list:
    if not HAS_BS4:
        return []
    html = _get(
        "https://www.immobilienscout24.de/Suche/de/berlin/berlin"
        "/wohnung-mieten?wbs=true&price=-700.0")
    if not html or len(html) < 500:
        return []
    soup   = BeautifulSoup(html, "html.parser")
    result = []
    seen: set = set()
    for card in soup.select("li[data-id],article[data-id]")[:20]:
        a = card.select_one("a[href*='/expose/']") or card.select_one("a[href]")
        if not a:
            continue
        href = a.get("href", "")
        url  = (href if href.startswith("http")
                else "https://www.immobilienscout24.de" + href)
        if url in seen or "/expose/" not in url:
            continue
        seen.add(url)
        t_tag = card.select_one("[class*='title'],h2,h3")
        p_tag = card.select_one("[class*='price'],[data-testid*='price']")
        r_tag = card.select_one("[class*='zimmer'],[class*='room']")
        title = (t_tag.get_text(strip=True) if t_tag else "")[:80]
        extra = enrich(title, card.get_text(" ", strip=True))
        result.append({
            "id": make_id(url), "url": url, "source": "immoscout",
            "trusted_wbs": False, "title": title,
            "price": parse_price(p_tag.get_text() if p_tag else None),
            "rooms": parse_rooms(r_tag.get_text() if r_tag else None),
            "location": "Berlin", "wbs_label": "",
            "ts": time.time(), **extra,
        })
    return result

_SCRAPER_MAP = {
    "gewobag":   _scrape_gewobag,
    "degewo":    _scrape_degewo,
    "kleinanz":  _scrape_kleinanzeigen,
    "immoscout": _scrape_immoscout,
}

def fetch_all(enabled: Optional[list] = None, use_cache: bool = False) -> list:
    if use_cache:
        cached = load_cache()
        if cached:
            return cached
    active  = set(enabled) if enabled else set(SOURCES.keys())
    result  = []
    lock    = threading.Lock()
    threads = []

    def run(src, fn):
        try:
            items = fn()
            with lock:
                result.extend(items)
        except Exception:
            pass

    for src in active:
        fn = _SCRAPER_MAP.get(src)
        if fn:
            t = threading.Thread(target=run, args=(src, fn), daemon=True)
            threads.append(t)
            t.start()

    # Wait max 25s total
    deadline = time.time() + 25
    for t in threads:
        remaining = max(0, deadline - time.time())
        t.join(timeout=remaining)

    # Deduplicate by ID
    seen_ids: set = set()
    unique = []
    for l in result:
        if l["id"] not in seen_ids:
            seen_ids.add(l["id"])
            unique.append(l)

    save_cache(unique)
    return unique

# ── Filtering & Sorting ───────────────────────────────────────────────

def apply_filters(listings: list, cfg: dict, seen: set) -> list:
    out      = []
    max_p    = float(cfg.get("max_price") or 9999)
    min_p    = float(cfg.get("min_price") or 0)
    min_r    = float(cfg.get("min_rooms") or 0)
    max_r    = float(cfg.get("max_rooms") or 0)
    min_sz   = int(cfg.get("min_size") or 0)
    max_sz   = int(cfg.get("max_size") or 0)
    wbs_only = bool(cfg.get("wbs_only"))
    wlmin    = int(cfg.get("wbs_level_min") or 0)
    wlmax    = int(cfg.get("wbs_level_max") or 999)
    jcm      = bool(cfg.get("jobcenter_mode"))
    wgm      = bool(cfg.get("wohngeld_mode"))
    n        = int(cfg.get("household_size") or 1)
    jclim    = jc_limit(n)
    wglim    = wg_limit(n)
    areas    = [a.lower() for a in (cfg.get("areas") or [])]
    srcs     = cfg.get("sources") or []

    for l in listings:
        if l["id"] in seen:
            continue
        if srcs and l["source"] not in srcs:
            continue

        price = l.get("price")
        rooms = l.get("rooms")
        size  = l.get("size_m2")

        if price is not None:
            if min_p > 0 and price < min_p:
                continue
            if price > max_p:
                continue

        if rooms is not None:
            if min_r > 0 and rooms < min_r:
                continue
            if max_r > 0 and rooms > max_r:
                continue

        if size is not None:
            if min_sz > 0 and size < min_sz:
                continue
            if max_sz > 0 and size > max_sz:
                continue

        if wbs_only and not l.get("trusted_wbs"):
            continue

        if wlmin > 0 or wlmax < 999:
            level = l.get("wbs_level_num")
            if level is not None and not (wlmin <= level <= wlmax):
                continue

        if areas:
            loc = (l.get("location", "") + " " + l.get("title", "")).lower()
            if not any(a in loc for a in areas):
                continue

        # Social filters (OR logic)
        if jcm or wgm:
            jc_ok = (price is None or price <= jclim) if jcm else False
            wg_ok = (price is None or price <= wglim) if wgm else False
            if not (jc_ok or wg_ok):
                continue

        out.append(l)
    return out

def sort_listings(listings: list, sort_by: str) -> list:
    if sort_by == "price_asc":
        return sorted(listings, key=lambda l: l.get("price") or 9999)
    elif sort_by == "price_desc":
        return sorted(listings, key=lambda l: -(l.get("price") or 0))
    elif sort_by == "newest":
        return sorted(listings, key=lambda l: -(l.get("ts") or 0))
    else:  # score
        return sorted(listings, key=_score, reverse=True)

def _score(l: dict) -> int:
    s  = 8 if l.get("trusted_wbs") else 0
    s += 3 if l.get("source") in GOV_SOURCES else 0
    p  = l.get("price")
    if p:
        if p < 400: s += 10
        elif p < 500: s += 7
        elif p < 600: s += 4
        elif p < 700: s += 1
    r = l.get("rooms")
    if r:
        if r >= 3: s += 5
        elif r >= 2: s += 3
    if l.get("size_m2"): s += 2
    avail = l.get("available", "")
    if "فوري" in avail: s += 5
    elif avail: s += 1
    s += min(len(l.get("features") or []), 4)
    if l.get("deposit"): s -= 1  # slight penalty for high deposit
    return s

# ═══════════════════════════════════════════════════════════════════════
# Kivy UI Helpers
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:

    def bg(widget, color, radius=0):
        """Apply background color, clearing old instructions first."""
        widget.canvas.before.clear()
        with widget.canvas.before:
            Color(*color)
            if radius:
                r = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[dp(radius)])
            else:
                r = Rectangle(pos=widget.pos, size=widget.size)
        def _upd(*_):
            r.pos  = widget.pos
            r.size = widget.size
        widget.bind(pos=_upd, size=_upd)

    def lbl(text, size=14, color=None, bold=False, halign="right", **kw):
        color = color or TEXT1
        w = Label(text=text, font_size=fs(size), color=color,
                  bold=bold, halign=halign, **kw)
        w.bind(width=lambda *_: setattr(w, "text_size", (w.width, None)))
        return w

    def btn(text, on_press=None, color=None, text_color=None,
            height=48, radius=12, **kw):
        color      = color or PRIMARY
        text_color = text_color or WHITE
        b = Button(text=text, size_hint_y=None, height=dp(height),
                   background_color=TRANSP, color=text_color,
                   font_size=fs(14), bold=True, **kw)
        bg(b, color, radius=radius)
        if on_press:
            b.bind(on_press=on_press)
        return b

    def gap(h=12):
        return Widget(size_hint_y=None, height=dp(h))

    def divider():
        w = Widget(size_hint_y=None, height=dp(1))
        bg(w, DIVIDER)
        return w

    def section_header(text):
        box = BoxLayout(size_hint_y=None, height=dp(28))
        box.add_widget(lbl(text, size=12, color=TEXT3, bold=True))
        return box

    def card_box(**kw):
        b = BoxLayout(**kw)
        bg(b, BG2, radius=14)
        return b

# ═══════════════════════════════════════════════════════════════════════
# Onboarding
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    PAGES = [
        ("🏠", "مرحباً في WBS برلين",
         "ابحث عن شقتك المدعومة\nمن 9 مصادر رسمية وخاصة\nكل ذلك في مكان واحد",
         PRIMARY),
        ("⚡", "فلاتر ذكية وشاملة",
         "حدّد: السعر · الغرف · المنطقة\nمستوى WBS (100–220)\nJobcenter KdU + Wohngeld",
         PURPLE),
        ("🎯", "نتائج مخصصة لك",
         "فقط الإعلانات الجديدة التي لم تشاهدها\nمرتبة حسب الأفضل أولاً\nاضغط للفتح مباشرة",
         AMBER),
    ]

    class OnboardPage(FloatLayout):
        def __init__(self, idx, go_next, go_skip, **kw):
            super().__init__(**kw)
            bg(self, BG)
            p = PAGES[idx]
            is_last = idx == len(PAGES) - 1

            card = BoxLayout(orientation="vertical", padding=dp(32),
                              spacing=dp(18), size_hint=(0.88, 0.68),
                              pos_hint={"center_x": .5, "center_y": .57})
            bg(card, BG2, radius=24)

            card.add_widget(Label(text=p[0], font_size=fs(68),
                                   size_hint_y=None, height=dp(80)))
            card.add_widget(lbl(p[1], size=22, bold=True, color=p[3],
                                 size_hint_y=None, height=dp(52)))
            card.add_widget(lbl(p[2], size=15, color=TEXT2,
                                 size_hint_y=None, height=dp(80)))
            self.add_widget(card)

            # Dots
            dots = BoxLayout(size_hint=(None, None), size=(dp(80), dp(12)),
                              pos_hint={"center_x": .5, "y": .18}, spacing=dp(8))
            for i in range(len(PAGES)):
                d = Widget(size_hint=(None, None),
                           size=(dp(20 if i == idx else 8), dp(8)))
                bg(d, p[3] if i == idx else TEXT3, radius=4)
                dots.add_widget(d)
            self.add_widget(dots)

            # Buttons
            btn_row = BoxLayout(size_hint=(0.88, None), height=dp(50),
                                 pos_hint={"center_x": .5, "y": .05},
                                 spacing=dp(12))
            if not is_last:
                btn_row.add_widget(btn("تخطي", on_press=go_skip,
                                        color=BG3, text_color=TEXT2))
            btn_row.add_widget(btn(
                "ابدأ الآن 🚀" if is_last else "التالي ←",
                on_press=go_next, color=p[3]))
            self.add_widget(btn_row)

    class OnboardingScreen(Screen):
        def __init__(self, app_ref, **kw):
            super().__init__(name="onboarding", **kw)
            self.app_ref = app_ref
            self._idx    = 0
            self._show()

        def _show(self):
            self.clear_widgets()
            self.add_widget(OnboardPage(self._idx, self._next, self._done))

        def _next(self, *_):
            if self._idx < len(PAGES) - 1:
                self._idx += 1
                self._show()
            else:
                self._done()

        def _done(self, *_):
            mark_done()
            self.app_ref.go_main()

# ═══════════════════════════════════════════════════════════════════════
# Listing Card
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class ListingCard(BoxLayout):
        def __init__(self, l: dict, **kw):
            super().__init__(orientation="vertical", size_hint_y=None,
                             padding=(dp(14), dp(12)), spacing=dp(6), **kw)
            name, gov, src_color = SOURCES.get(l["source"], (l["source"], False, BLUE))
            price    = l.get("price")
            rooms    = l.get("rooms")
            size_m2  = l.get("size_m2")
            floor_s  = l.get("floor", "")
            avail    = l.get("available", "")
            deposit  = l.get("deposit", "")
            heating  = l.get("heating", "")
            features = (l.get("features") or [])[:6]
            title    = (l.get("title") or "شقة").strip()[:65]
            location = l.get("location", "Berlin")
            wlnum    = l.get("wbs_level_num")
            wlabel   = f"WBS {wlnum}" if wlnum else ("WBS ✓" if l.get("trusted_wbs") else "")
            self.url = l.get("url", "")

            n_feat_r = max(1, (len(features) + 2) // 3) if features else 0
            self.height = dp(172 + n_feat_r * 24 + (22 if deposit or heating else 0))
            bg(self, BG2, radius=16)

            # ── Source + WBS badge ────────────────────────────────────────
            r1 = BoxLayout(size_hint_y=None, height=dp(26), spacing=dp(8))

            src_chip = BoxLayout(size_hint=(None, None),
                                  size=(dp(115), dp(24)), padding=(dp(8), 0))
            bg(src_chip, (*src_color[:3], 0.18), radius=12)
            gov_tag = "🏛 " if gov else "🔍 "
            src_chip.add_widget(lbl(gov_tag + name, size=11, color=src_color,
                                     size_hint_y=None, height=dp(24)))
            r1.add_widget(src_chip)
            r1.add_widget(Widget())

            if wlabel:
                wbadge = BoxLayout(size_hint=(None, None),
                                    size=(dp(76), dp(24)), padding=(dp(8), 0))
                bg(wbadge, (*PRIMARY[:3], 0.18), radius=12)
                wbadge.add_widget(lbl(wlabel, size=11, color=PRIMARY,
                                       bold=True, size_hint_y=None, height=dp(24)))
                r1.add_widget(wbadge)
            self.add_widget(r1)

            # ── Title ─────────────────────────────────────────────────────
            self.add_widget(lbl(title, size=13, bold=True,
                                 size_hint_y=None, height=dp(22)))

            # ── Location + Availability ───────────────────────────────────
            r3 = BoxLayout(size_hint_y=None, height=dp(18))
            r3.add_widget(lbl("📍 " + location, size=11, color=TEXT2))
            if avail:
                r3.add_widget(lbl("📅 " + avail, size=11,
                                   color=AMBER if "فوري" in avail else TEXT2))
            self.add_widget(r3)

            self.add_widget(divider())

            # ── Price row ─────────────────────────────────────────────────
            r4 = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(6))
            if price:
                pill = BoxLayout(size_hint=(None, None),
                                  size=(dp(105), dp(30)), padding=(dp(10), 0))
                bg(pill, (*PRIMARY[:3], 0.15), radius=10)
                ppm = f" ({price/size_m2:.1f}€/m²)" if size_m2 else ""
                pill.add_widget(lbl(f"💰 {price:.0f}€{ppm}", size=13,
                                     color=PRIMARY, bold=True,
                                     size_hint_y=None, height=dp(30)))
                r4.add_widget(pill)
            if rooms:
                r4.add_widget(lbl(f"🛏 {rooms:.0f}", size=12, color=TEXT1))
            if size_m2:
                r4.add_widget(lbl(f"📐 {size_m2:.0f}m²", size=12, color=TEXT1))
            if floor_s:
                r4.add_widget(lbl(floor_s, size=11, color=TEXT2))
            self.add_widget(r4)

            # ── Extra info (deposit / heating) ────────────────────────────
            if deposit or heating:
                rx = BoxLayout(size_hint_y=None, height=dp(18))
                if deposit:
                    rx.add_widget(lbl("💼 " + deposit, size=11, color=TEXT2))
                if heating:
                    rx.add_widget(lbl(heating, size=11, color=TEXT2))
                self.add_widget(rx)

            # ── Feature chips ─────────────────────────────────────────────
            if features:
                fg = GridLayout(cols=3, size_hint_y=None,
                                 height=dp(n_feat_r * 24), spacing=dp(4))
                for f in features:
                    chip = BoxLayout(size_hint_y=None, height=dp(22),
                                     padding=(dp(6), 0))
                    bg(chip, BG3, radius=8)
                    chip.add_widget(lbl(f, size=10, color=TEXT2,
                                        size_hint_y=None, height=dp(22)))
                    fg.add_widget(chip)
                self.add_widget(fg)

            # ── Open button ───────────────────────────────────────────────
            ob = btn("فتح الإعلان  ←", on_press=self._open,
                      height=34, radius=10)
            self.add_widget(ob)

        def _open(self, *_):
            if not self.url:
                return
            try:
                import jnius
                I  = jnius.autoclass("android.content.Intent")
                U  = jnius.autoclass("android.net.Uri")
                PA = jnius.autoclass("org.kivy.android.PythonActivity")
                PA.mActivity.startActivity(I(I.ACTION_VIEW, U.parse(self.url)))
            except Exception:
                try:
                    from kivy.core.clipboard import Clipboard
                    Clipboard.copy(self.url)
                except Exception:
                    pass

# ═══════════════════════════════════════════════════════════════════════
# Listings Screen
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class ListingsScreen(Screen):
        def __init__(self, app_ref, **kw):
            super().__init__(name="listings", **kw)
            self.app_ref  = app_ref
            self._lock    = threading.Lock()
            self._busy    = False
            self._raw: list = []
            bg(self, BG)
            self._build_ui()

        def _build_ui(self):
            root = BoxLayout(orientation="vertical")
            cfg  = load_cfg()

            # ── Top bar ───────────────────────────────────────────────────
            bar = BoxLayout(size_hint_y=None, height=dp(58),
                             padding=(dp(14), dp(8)), spacing=dp(8))
            bg(bar, BG2)
            bar.add_widget(lbl("🏠 WBS برلين", size=17, bold=True, color=WHITE,
                                size_hint_x=0.45))
            bar.add_widget(Widget())

            # Sort button
            sort_opts = {"score":"🏅","price_asc":"💰↑","price_desc":"💰↓","newest":"🕐"}
            self._sort_btn = btn(
                sort_opts.get(cfg.get("sort_by","score"), "🏅"),
                on_press=self._cycle_sort,
                color=BG3, text_color=TEXT2,
                size_hint_x=None, width=dp(50), height=42)
            bar.add_widget(self._sort_btn)

            filter_btn = btn("⚙️", on_press=self._go_settings,
                              color=BG3, text_color=TEXT2,
                              size_hint_x=None, width=dp(44), height=42)
            bar.add_widget(filter_btn)

            self._refresh_btn = btn("🔄", on_press=self._do_refresh,
                                     color=PRIMARY, size_hint_x=None,
                                     width=dp(44), height=42)
            bar.add_widget(self._refresh_btn)
            root.add_widget(bar)

            # ── Chip row ──────────────────────────────────────────────────
            chips = BoxLayout(size_hint_y=None, height=dp(44),
                               padding=(dp(10), dp(6)), spacing=dp(8))
            bg(chips, BG2)

            self._wbs_chip = ToggleButton(
                text="✅ WBS فقط",
                state="down" if cfg.get("wbs_only") else "normal",
                size_hint=(None, None), size=(dp(100), dp(30)),
                background_color=TRANSP, color=TEXT1, font_size=fs(12))
            self._refresh_chip_bg()
            self._wbs_chip.bind(state=self._on_wbs)
            chips.add_widget(self._wbs_chip)

            self._status = lbl("اضغط 🔄 للبحث", size=12, color=TEXT2,
                                size_hint_y=None, height=dp(30))
            chips.add_widget(self._status)
            root.add_widget(chips)
            root.add_widget(divider())

            # ── Cards ─────────────────────────────────────────────────────
            self._cards = BoxLayout(orientation="vertical", spacing=dp(10),
                                     padding=(dp(10), dp(10)), size_hint_y=None)
            self._cards.bind(minimum_height=self._cards.setter("height"))
            sv = ScrollView(bar_color=(*PRIMARY[:3], 0.4),
                             bar_inactive_color=(*TEXT3[:3], 0.2))
            sv.add_widget(self._cards)
            root.add_widget(sv)
            self.add_widget(root)
            self._show_placeholder("🔍", "اضغط 🔄 للبحث عن شقق WBS")

        def _refresh_chip_bg(self):
            on = self._wbs_chip.state == "down"
            bg(self._wbs_chip, (*PRIMARY[:3], 0.85) if on else BG3, radius=15)

        def _on_wbs(self, _, state):
            self._refresh_chip_bg()
            cfg = load_cfg()
            cfg["wbs_only"] = state == "down"
            save_cfg(cfg)
            with self._lock:
                raw = list(self._raw)
            if raw:
                shown = sort_listings(
                    apply_filters(raw, cfg, load_seen()),
                    cfg.get("sort_by","score"))
                Clock.schedule_once(lambda dt: self._render(shown, len(raw)))

        def _cycle_sort(self, *_):
            order = ["score","price_asc","price_desc","newest"]
            icons  = {"score":"🏅","price_asc":"💰↑","price_desc":"💰↓","newest":"🕐"}
            cfg = load_cfg()
            cur = cfg.get("sort_by","score")
            nxt = order[(order.index(cur)+1) % len(order)]
            cfg["sort_by"] = nxt
            save_cfg(cfg)
            self._sort_btn.text = icons[nxt]
            with self._lock:
                raw = list(self._raw)
            if raw:
                shown = sort_listings(
                    apply_filters(raw, cfg, load_seen()), nxt)
                Clock.schedule_once(lambda dt: self._render(shown, len(raw)))

        def _go_settings(self, *_):
            self.app_ref.sm.current = "settings"

        def _show_placeholder(self, icon, msg):
            self._cards.clear_widgets()
            box = BoxLayout(orientation="vertical", spacing=dp(10),
                             size_hint_y=None, height=dp(220), padding=dp(40))
            box.add_widget(Label(text=icon, font_size=fs(56),
                                  size_hint_y=None, height=dp(70)))
            box.add_widget(lbl(msg, size=14, color=TEXT2,
                                size_hint_y=None, height=dp(50)))
            self._cards.add_widget(box)

        def _do_refresh(self, *_):
            with self._lock:
                if self._busy:
                    return
                self._busy = True

            # Network check
            if not check_network():
                self._status.text = "❌ لا يوجد اتصال بالإنترنت"
                cached = load_cache()
                if cached:
                    self._status.text = "📦 يعرض النتائج المؤقتة"
                    with self._lock:
                        self._raw = cached
                        self._busy = False
                    cfg   = load_cfg()
                    shown = sort_listings(
                        apply_filters(cached, cfg, load_seen()),
                        cfg.get("sort_by","score"))
                    Clock.schedule_once(lambda dt: self._render(shown, len(cached)))
                else:
                    with self._lock:
                        self._busy = False
                    self._show_placeholder("📵", "لا يوجد اتصال ولا توجد نتائج مؤقتة")
                return

            self._status.text = "⏳ جاري البحث..."
            self._show_placeholder("⏳", "جاري جلب الإعلانات...")
            threading.Thread(target=self._bg_fetch, daemon=True).start()

        def _bg_fetch(self):
            try:
                cfg  = load_cfg()
                raw  = fetch_all(cfg.get("sources") or None)
                with self._lock:
                    self._raw = raw
                seen  = load_seen()
                shown = sort_listings(
                    apply_filters(raw, cfg, seen),
                    cfg.get("sort_by","score"))
                for l in shown:
                    seen.add(l["id"])
                save_seen(seen)
                Clock.schedule_once(lambda dt: self._render(shown, len(raw)))
            except Exception:
                Clock.schedule_once(lambda dt: self._on_fetch_error())
            finally:
                with self._lock:
                    self._busy = False

        def _on_fetch_error(self):
            self._status.text = "❌ خطأ أثناء الجلب"
            self._show_placeholder("⚠️", "حدث خطأ — حاول مرة أخرى")

        def _render(self, lst: list, total: int):
            self._cards.clear_widgets()
            if not lst:
                self._status.text = f"لا إعلانات جديدة (من {total})"
                self._show_placeholder("🔍", "لا توجد إعلانات جديدة تناسب إعداداتك")
                return
            self._status.text = f"✅ {len(lst)} جديد من {total}"
            # Lazy render: add 10 immediately, rest on next frame
            for l in lst[:10]:
                self._cards.add_widget(ListingCard(l))
                self._cards.add_widget(gap(6))
            if len(lst) > 10:
                Clock.schedule_once(lambda dt: self._render_rest(lst[10:]), 0.05)

        def _render_rest(self, rest: list):
            for l in rest[:50]:
                self._cards.add_widget(ListingCard(l))
                self._cards.add_widget(gap(6))

# ═══════════════════════════════════════════════════════════════════════
# Settings Screen
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class SettingsScreen(Screen):
        def __init__(self, app_ref, **kw):
            super().__init__(name="settings", **kw)
            self.app_ref = app_ref
            bg(self, BG)
            self._build()

        def _build(self):
            cfg  = load_cfg()
            root = BoxLayout(orientation="vertical")

            # Header
            hdr = BoxLayout(size_hint_y=None, height=dp(58),
                             padding=(dp(12), dp(8)), spacing=dp(10))
            bg(hdr, BG2)
            hdr.add_widget(btn("←", on_press=self._back,
                                color=BG3, text_color=TEXT2,
                                size_hint_x=None, width=dp(44), height=42))
            hdr.add_widget(lbl("⚙️ الإعدادات", size=16, bold=True, color=WHITE))
            hdr.add_widget(btn("↩️ افتراضي", on_press=self._reset,
                                color=BG3, text_color=TEXT2,
                                size_hint_x=None, width=dp(100), height=42))
            root.add_widget(hdr)

            scroll = ScrollView()
            body   = BoxLayout(orientation="vertical", padding=dp(14),
                                spacing=dp(8), size_hint_y=None)
            body.bind(minimum_height=body.setter("height"))

            def tf(val, filt="int"):
                t = TextInput(text=str(val), input_filter=filt,
                               multiline=False, background_color=TRANSP,
                               foreground_color=TEXT1, cursor_color=PRIMARY,
                               font_size=fs(14))
                bg(t, BG3, radius=10)
                return t

            def row(label, widget, hint=""):
                r = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(12),
                               padding=(dp(12), dp(4)))
                bg(r, BG2, radius=12)
                left = BoxLayout(orientation="vertical", size_hint_x=0.45)
                left.add_widget(lbl(label, size=13, color=TEXT1))
                if hint:
                    left.add_widget(lbl(hint, size=10, color=TEXT3))
                r.add_widget(left)
                r.add_widget(widget)
                body.add_widget(r)

            def toggle(text, active, on_change=None):
                t = ToggleButton(text=text, state="down" if active else "normal",
                                  size_hint=(1, None), height=dp(46),
                                  background_color=TRANSP, color=TEXT1,
                                  font_size=fs(13))
                bg(t, (*PRIMARY[:3], 0.15) if active else BG2, radius=12)
                def _state(b, s):
                    bg(b, (*PRIMARY[:3], 0.15) if s=="down" else BG2, radius=12)
                    if on_change:
                        on_change(s == "down")
                t.bind(state=_state)
                body.add_widget(t)
                return t

            # ── Budget ────────────────────────────────────────────────────
            body.add_widget(gap(4))
            body.add_widget(section_header("💰  الميزانية"))

            self._min_p = tf(cfg.get("min_price", 0))
            row("الحد الأدنى للإيجار (€)", self._min_p, "0 = بدون حد")
            self._max_p = tf(cfg.get("max_price", 700))
            row("أقصى إيجار (€)", self._max_p)

            # ── Size & Rooms ──────────────────────────────────────────────
            body.add_widget(gap(4))
            body.add_widget(section_header("🛏  الغرف والمساحة"))

            rr = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8),
                            padding=(dp(12), dp(4)))
            bg(rr, BG2, radius=12)
            rr.add_widget(lbl("الغرف:", size=13, color=TEXT1, size_hint_x=0.25))
            self._min_r = tf(cfg.get("min_rooms", 0), "float")
            rr.add_widget(lbl("من", size=11, color=TEXT2, size_hint_x=0.1))
            rr.add_widget(self._min_r)
            rr.add_widget(lbl("—", size=13, color=TEXT2, size_hint_x=0.1))
            self._max_r = tf(cfg.get("max_rooms", 0), "float")
            rr.add_widget(self._max_r)
            rr.add_widget(lbl("0=أي", size=10, color=TEXT3, size_hint_x=0.15))
            body.add_widget(rr)

            sz_row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8),
                                padding=(dp(12), dp(4)))
            bg(sz_row, BG2, radius=12)
            sz_row.add_widget(lbl("المساحة (م²):", size=13, color=TEXT1, size_hint_x=0.35))
            self._min_sz = tf(cfg.get("min_size", 0))
            sz_row.add_widget(lbl("من", size=11, color=TEXT2, size_hint_x=0.1))
            sz_row.add_widget(self._min_sz)
            sz_row.add_widget(lbl("—", size=13, color=TEXT2, size_hint_x=0.1))
            self._max_sz = tf(cfg.get("max_size", 0))
            sz_row.add_widget(self._max_sz)
            body.add_widget(sz_row)

            # ── WBS ───────────────────────────────────────────────────────
            body.add_widget(gap(4))
            body.add_widget(section_header("📋  WBS"))

            self._wbs = toggle("WBS فقط", cfg.get("wbs_only", False))

            # WBS level
            wl = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(8),
                            padding=(dp(12), dp(4)))
            bg(wl, BG2, radius=12)
            wl.add_widget(lbl("مستوى WBS:", size=13, color=TEXT1, size_hint_x=0.35))
            self._wlmin = tf(cfg.get("wbs_level_min", 0))
            wl.add_widget(lbl("من", size=11, color=TEXT2, size_hint_x=0.08))
            wl.add_widget(self._wlmin)
            wl.add_widget(lbl("—", size=13, color=TEXT2, size_hint_x=0.06))
            self._wlmax = tf(cfg.get("wbs_level_max", 999))
            wl.add_widget(self._wlmax)
            body.add_widget(wl)

            # WBS presets
            pr = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
            for ltext, mn, mx in [("100","100","100"),("100-140","100","140"),
                                    ("100-160","100","160"),("كل","0","999")]:
                b = btn(ltext, color=BG3, text_color=TEXT1, height=38, radius=10,
                         size_hint_x=None, width=dp(75))
                b.bind(on_press=lambda _,mn=mn,mx=mx: (
                    setattr(self._wlmin,"text",mn),
                    setattr(self._wlmax,"text",mx)))
                pr.add_widget(b)
            body.add_widget(pr)

            # ── Social ────────────────────────────────────────────────────
            body.add_widget(gap(4))
            body.add_widget(section_header("🏛  فلاتر اجتماعية"))

            self._hh = tf(cfg.get("household_size", 1))
            row("أفراد الأسرة", self._hh, "يؤثر على حدود Jobcenter/Wohngeld")

            n = int(cfg.get("household_size") or 1)
            body.add_widget(lbl(
                f"JC KdU ≤ {jc_limit(n):.0f}€   |   Wohngeld ≤ {wg_limit(n):.0f}€",
                size=11, color=TEXT3, size_hint_y=None, height=dp(20)))

            self._jc = toggle("🏛 Jobcenter KdU", cfg.get("jobcenter_mode", False))
            self._wg = toggle("🏦 Wohngeld", cfg.get("wohngeld_mode", False))

            # ── Areas ─────────────────────────────────────────────────────
            body.add_widget(gap(4))
            body.add_widget(section_header("📍  المناطق  (بدون تحديد = كل برلين)"))

            cur_areas = cfg.get("areas") or []
            self._area_btns: dict = {}
            ag = GridLayout(cols=2, size_hint_y=None,
                             height=dp(((len(BERLIN_AREAS)+1)//2)*40),
                             spacing=dp(6))
            for area in BERLIN_AREAS:
                on  = area in cur_areas
                b   = ToggleButton(text=area, state="down" if on else "normal",
                                    size_hint=(1, None), height=dp(38),
                                    background_color=TRANSP, color=TEXT1,
                                    font_size=fs(12))
                bg(b, (*AMBER[:3], 0.15) if on else BG2, radius=10)
                b.bind(state=lambda x,s,b=b: bg(
                    b, (*AMBER[:3], 0.15) if s=="down" else BG2, radius=10))
                self._area_btns[area] = b
                ag.add_widget(b)
            body.add_widget(ag)

            # Clear areas button
            body.add_widget(btn("🌍 كل برلين (إلغاء التحديد)",
                                 on_press=self._clear_areas,
                                 color=BG3, text_color=TEXT2, height=38, radius=10))

            # ── Sources ───────────────────────────────────────────────────
            body.add_widget(gap(4))
            body.add_widget(section_header("🌐  مصادر البحث"))

            cur_src = cfg.get("sources") or []
            self._src_btns: dict = {}
            for sid, (sname, gov, sc) in SOURCES.items():
                on  = not cur_src or sid in cur_src
                typ = "🏛" if gov else "🔍"
                b   = ToggleButton(
                    text=f"{typ} {sname}",
                    state="down" if on else "normal",
                    size_hint=(1, None), height=dp(44),
                    background_color=TRANSP, color=TEXT1, font_size=fs(13))
                bg(b, (*sc[:3], 0.15) if on else BG2, radius=12)
                b.bind(state=lambda x,s,sc=sc,b=b: bg(
                    b, (*sc[:3], 0.15) if s=="down" else BG2, radius=12))
                self._src_btns[sid] = b
                body.add_widget(b)

            # Quick select
            qrow = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
            qrow.add_widget(btn("✅ الكل", on_press=lambda *_: self._set_all_sources(True),
                                 color=BG3, text_color=TEXT1, height=38, radius=10))
            qrow.add_widget(btn("🏛 حكومية فقط", on_press=self._gov_only,
                                 color=(*PURPLE[:3],1), height=38, radius=10))
            body.add_widget(qrow)

            # ── Sort & Cache ──────────────────────────────────────────────
            body.add_widget(gap(4))
            body.add_widget(section_header("🔧  خيارات متقدمة"))

            sort_map = [("score","🏅 حسب الأفضل"),("price_asc","💰 السعر تصاعدي"),
                        ("price_desc","💰 السعر تنازلي"),("newest","🕐 الأحدث")]
            cur_sort = cfg.get("sort_by","score")
            self._sort_btns: dict = {}
            sr = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(6))
            for k, t_text in sort_map:
                b = ToggleButton(text=t_text, state="down" if k==cur_sort else "normal",
                                  size_hint=(1, None), height=dp(38),
                                  background_color=TRANSP, color=TEXT1,
                                  font_size=fs(11))
                bg(b, (*BLUE[:3], 0.15) if k==cur_sort else BG2, radius=10)
                b.bind(state=lambda x,s,k=k,b=b: (
                    bg(b, (*BLUE[:3], 0.15) if s=="down" else BG2, radius=10),
                    self._exclusive_sort(k) if s=="down" else None))
                self._sort_btns[k] = b
                sr.add_widget(b)
            body.add_widget(sr)

            self._cache_h = tf(cfg.get("cache_hours", 1))
            row("مدة الكاش (ساعات)", self._cache_h, "لتجنب طلبات متكررة")

            body.add_widget(gap(20))

            # Save
            body.add_widget(btn("💾 حفظ الإعدادات",
                                  on_press=self._save, height=54, radius=14))
            body.add_widget(gap(20))

            scroll.add_widget(body)
            root.add_widget(scroll)
            self.add_widget(root)

        def _clear_areas(self, *_):
            for b in self._area_btns.values():
                b.state = "normal"
                bg(b, BG2, radius=10)

        def _set_all_sources(self, on):
            for sid, b in self._src_btns.items():
                b.state = "down" if on else "normal"
                _, _, sc = SOURCES[sid]
                bg(b, (*sc[:3], 0.15) if on else BG2, radius=12)

        def _gov_only(self, *_):
            for sid, b in self._src_btns.items():
                on = SOURCES[sid][1]
                b.state = "down" if on else "normal"
                _, _, sc = SOURCES[sid]
                bg(b, (*sc[:3], 0.15) if on else BG2, radius=12)

        def _exclusive_sort(self, chosen: str):
            for k, b in self._sort_btns.items():
                if k != chosen:
                    b.state = "normal"
                    bg(b, BG2, radius=10)

        def _back(self, *_):
            self.app_ref.sm.current = "listings"

        def _reset(self, *_):
            save_cfg(dict(DEFAULTS))
            # Rebuild the screen
            self.clear_widgets()
            self._build()

        def _save(self, *_):
            sel_src   = [sid for sid,b in self._src_btns.items() if b.state=="down"]
            sel_areas = [area for area,b in self._area_btns.items() if b.state=="down"]
            cur_sort  = next((k for k,b in self._sort_btns.items() if b.state=="down"),
                              "score")
            cfg = load_cfg()
            cfg.update({
                "min_price":      int(self._min_p.text or 0),
                "max_price":      int(self._max_p.text or 700),
                "min_rooms":      float(self._min_r.text or 0),
                "max_rooms":      float(self._max_r.text or 0),
                "min_size":       int(self._min_sz.text or 0),
                "max_size":       int(self._max_sz.text or 0),
                "household_size": max(1, int(self._hh.text or 1)),
                "wbs_only":       self._wbs.state == "down",
                "wbs_level_min":  int(self._wlmin.text or 0),
                "wbs_level_max":  int(self._wlmax.text or 999),
                "jobcenter_mode": self._jc.state == "down",
                "wohngeld_mode":  self._wg.state == "down",
                "areas":    sel_areas,
                "sources":  sel_src if len(sel_src) < len(SOURCES) else [],
                "sort_by":  cur_sort,
                "cache_hours": max(0, int(self._cache_h.text or 1)),
            })
            save_cfg(cfg)
            self.app_ref.sm.current = "listings"

# ═══════════════════════════════════════════════════════════════════════
# App Entry Point
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class WBSApp(App):
        def build(self):
            self.title = "WBS Berlin"
            Window.clearcolor = BG
            self.sm = ScreenManager(transition=FadeTransition(duration=0.18))
            if is_first_run():
                self.sm.add_widget(OnboardingScreen(self))
                self.sm.current = "onboarding"
            else:
                self._add_main_screens()
            return self.sm

        def _add_main_screens(self):
            if not any(s.name == "listings" for s in self.sm.screens):
                self.sm.add_widget(ListingsScreen(self))
            if not any(s.name == "settings" for s in self.sm.screens):
                self.sm.add_widget(SettingsScreen(self))

        def go_main(self):
            self._add_main_screens()
            self.sm.current = "listings"

    if __name__ == "__main__":
        WBSApp().run()

else:
    # CLI test
    if __name__ == "__main__":
        print("=== WBS Berlin — CLI test ===")
        print("Network:", check_network())
        raw   = fetch_all()
        cfg   = dict(DEFAULTS)
        shown = sort_listings(apply_filters(raw, cfg, set()), "score")
        print(f"Results: {len(shown)} / {len(raw)}")
        for l in shown[:5]:
            p = f"{l['price']:.0f}€" if l.get("price") else "—"
            print(f"  [{l['source']}] {p} | {l.get('title','')[:45]}")
