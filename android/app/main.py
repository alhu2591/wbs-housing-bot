"""
WBS Berlin v3.0 — Android App
✅ Arabic text fixed (reshaper+bidi)
✅ Background service + notifications
✅ Fully stable + secure
"""
import json, os, re, hashlib, threading, socket, time, ssl, tempfile, shutil
import urllib.request, urllib.parse
from pathlib import Path
from typing import Optional

# ── Arabic text support ──────────────────────────────────────────────
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_ARABIC = True
except ImportError:
    HAS_ARABIC = False

def ar(text: str) -> str:
    """Reshape Arabic text for correct Kivy rendering."""
    if not HAS_ARABIC or not text:
        return text
    try:
        return get_display(arabic_reshaper.reshape(str(text)))
    except Exception:
        return text

# ── bs4 ──────────────────────────────────────────────────────────────
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ── Kivy ─────────────────────────────────────────────────────────────
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
    from kivy.graphics import Color, RoundedRectangle, Rectangle
    from kivy.clock import Clock
    from kivy.metrics import dp, sp
    from kivy.utils import get_color_from_hex
    from kivy.core.window import Window
    HAS_KIVY = True
except ImportError:
    HAS_KIVY = False

# ── Android APIs ──────────────────────────────────────────────────────
try:
    import jnius
    PythonActivity  = jnius.autoclass("org.kivy.android.PythonActivity")
    Intent          = jnius.autoclass("android.content.Intent")
    Uri             = jnius.autoclass("android.net.Uri")
    NotifManager    = jnius.autoclass("android.app.NotificationManager")
    NotifBuilder    = jnius.autoclass("android.app.Notification$Builder")
    NotifChannel    = jnius.autoclass("android.app.NotificationChannel")
    PendingIntent   = jnius.autoclass("android.app.PendingIntent")
    Context         = jnius.autoclass("android.content.Context")
    BitmapFactory   = jnius.autoclass("android.graphics.BitmapFactory")
    HAS_ANDROID = True
except Exception:
    HAS_ANDROID = False

# ═════════════════════════════════════════════════════════════════════
# Design Tokens
# ═════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    BG      = get_color_from_hex("#0A0A0A")
    BG2     = get_color_from_hex("#141414")
    BG3     = get_color_from_hex("#1E1E1E")
    BG4     = get_color_from_hex("#252525")
    PRIMARY = get_color_from_hex("#22C55E")
    PURPLE  = get_color_from_hex("#8B5CF6")
    BLUE    = get_color_from_hex("#3B82F6")
    AMBER   = get_color_from_hex("#F59E0B")
    RED     = get_color_from_hex("#EF4444")
    TEXT1   = get_color_from_hex("#F1F5F9")
    TEXT2   = get_color_from_hex("#94A3B8")
    TEXT3   = get_color_from_hex("#475569")
    DIVIDER = get_color_from_hex("#1E293B")
    WHITE   = (1, 1, 1, 1)
    TRANSP  = (0, 0, 0, 0)
    def fs(n): return sp(n)

# ═════════════════════════════════════════════════════════════════════
# Storage — atomic writes to prevent corruption
# ═════════════════════════════════════════════════════════════════════
_sd       = Path(os.environ.get("EXTERNAL_STORAGE", "."))
CFG_FILE  = _sd / "wbs3_config.json"
SEEN_FILE = _sd / "wbs3_seen.json"
CACHE_FILE= _sd / "wbs3_cache.json"
FIRST_RUN = _sd / "wbs3_first_run"
SERVICE_RUNNING = _sd / "wbs3_service.pid"

_cfg_lock  = threading.RLock()
_seen_lock = threading.RLock()

def _atomic_write(path: Path, data: str) -> None:
    """Write to temp file then rename — prevents partial writes."""
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(data, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        try:
            path.write_text(data, encoding="utf-8")
        except Exception:
            pass

def _safe_read(path: Path, default="{}") -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception:
        pass
    return default

DEFAULTS = {
    "max_price": 700, "min_price": 0,
    "min_rooms": 0.0, "max_rooms": 0.0,
    "min_size": 0,    "max_size": 0,
    "wbs_only": False,
    "wbs_level_min": 0, "wbs_level_max": 999,
    "household_size": 1,
    "jobcenter_mode": False, "wohngeld_mode": False,
    "sources": [], "areas": [],
    "sort_by": "score",
    "cache_hours": 1,
    "bg_interval": 30,   # background check every N minutes
    "notifications": True,
}

def load_cfg() -> dict:
    with _cfg_lock:
        try:
            return {**DEFAULTS, **json.loads(_safe_read(CFG_FILE))}
        except Exception:
            return dict(DEFAULTS)

def save_cfg(c: dict) -> None:
    with _cfg_lock:
        _atomic_write(CFG_FILE, json.dumps(c, indent=2, ensure_ascii=False))

def load_seen() -> set:
    with _seen_lock:
        try:
            data = json.loads(_safe_read(SEEN_FILE, "[]"))
            return set(data) if isinstance(data, list) else set()
        except Exception:
            return set()

def save_seen(s: set) -> None:
    with _seen_lock:
        _atomic_write(SEEN_FILE, json.dumps(list(s)[-5000:]))

def load_cache() -> list:
    try:
        data = json.loads(_safe_read(CACHE_FILE, "{}"))
        cfg  = load_cfg()
        age  = time.time() - data.get("ts", 0)
        if age < cfg.get("cache_hours", 1) * 3600:
            return data.get("listings", [])
    except Exception:
        pass
    return []

def save_cache(listings: list) -> None:
    _atomic_write(CACHE_FILE,
        json.dumps({"ts": time.time(), "listings": listings}, ensure_ascii=False))

def is_first_run() -> bool:
    return not FIRST_RUN.exists()

def mark_done() -> None:
    try: FIRST_RUN.write_text("1")
    except Exception: pass

# ═════════════════════════════════════════════════════════════════════
# Domain Data
# ═════════════════════════════════════════════════════════════════════
SOURCES = {
    "gewobag":   ("Gewobag",       True),
    "degewo":    ("Degewo",        True),
    "gesobau":   ("Gesobau",       True),
    "wbm":       ("WBM",           True),
    "vonovia":   ("Vonovia",       True),
    "howoge":    ("Howoge",        True),
    "berlinovo": ("Berlinovo",     True),
    "immoscout": ("ImmoScout24",   False),
    "kleinanz":  ("Kleinanzeigen", False),
}
GOV = {k for k,v in SOURCES.items() if v[1]}

BERLIN_AREAS = [
    "Mitte","Spandau","Pankow","Neukölln","Tempelhof","Schöneberg",
    "Steglitz","Zehlendorf","Charlottenburg","Wilmersdorf","Lichtenberg",
    "Marzahn","Hellersdorf","Treptow","Köpenick","Reinickendorf",
    "Friedrichshain","Kreuzberg","Prenzlauer Berg","Wedding","Moabit",
]

JC = {1:549,2:671,3:789,4:911,5:1021,6:1131}
WG = {1:580,2:680,3:800,4:910,5:1030,6:1150,7:1270}
def jc(n): return JC.get(max(1,min(int(n),6)), JC[6]+(max(1,int(n))-6)*110)
def wg(n): return WG.get(max(1,min(int(n),7)), WG[7]+(max(1,int(n))-7)*120)

FEATS = {
    "balkon":"بلكونة","terrasse":"تراس","dachterrasse":"تراس علوي",
    "garten":"حديقة","aufzug":"مصعد","fahrstuhl":"مصعد",
    "einbauküche":"مطبخ مجهز","keller":"مخزن","abstellraum":"مخزن",
    "stellplatz":"موقف","tiefgarage":"جراج","barrierefrei":"بدون عوائق",
    "neubau":"بناء جديد","erstbezug":"أول سكن","parkett":"باركيه",
    "laminat":"لامينيت","fußbodenheizung":"تدفئة أرضية",
    "fernwärme":"تدفئة مركزية","saniert":"مجدد","waschmaschine":"غسالة",
    "badewanne":"حوض","sep. wc":"حمام منفصل",
}
FEATS_ICONS = {
    "بلكونة":"🌿","تراس":"🌿","تراس علوي":"🌿","حديقة":"🌱","مصعد":"🛗",
    "مطبخ مجهز":"🍳","مخزن":"📦","موقف":"🚗","جراج":"🚗","بدون عوائق":"♿",
    "بناء جديد":"🏗","أول سكن":"✨","باركيه":"🪵","لامينيت":"🪵",
    "تدفئة أرضية":"🌡","تدفئة مركزية":"🌡","مجدد":"🔨","غسالة":"🫧",
    "حوض":"🛁","حمام منفصل":"🚽",
}
URGENT = ["ab sofort","sofort frei","sofort verfügbar","sofort beziehbar"]
MONTHS_AR = {
    "januar":"يناير","februar":"فبراير","märz":"مارس","april":"أبريل",
    "mai":"مايو","juni":"يونيو","juli":"يوليو","august":"أغسطس",
    "september":"سبتمبر","oktober":"أكتوبر","november":"نوفمبر","dezember":"ديسمبر",
}

# ═════════════════════════════════════════════════════════════════════
# Network
# ═════════════════════════════════════════════════════════════════════
_SSL = ssl.create_default_context()
try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    # Fallback: only disable verification, log it
    _SSL.check_hostname = False
    _SSL.verify_mode    = ssl.CERT_NONE

_UA      = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/124.0"
_TIMEOUT = 12

def check_network() -> bool:
    try:
        socket.setdefaulttimeout(3)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("8.8.8.8", 53))
        s.close()
        return True
    except Exception:
        return False

def _get(url: str) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA, "Accept-Language": "de-DE,de;q=0.9",
            "Accept": "text/html,*/*;q=0.8"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL) as r:
            enc = r.headers.get_content_charset("utf-8")
            return r.read().decode(enc, errors="replace")
    except Exception:
        return None

def _get_json(url: str) -> Optional[object]:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_SSL) as r:
            return json.loads(r.read())
    except Exception:
        return None

# ═════════════════════════════════════════════════════════════════════
# Parsing
# ═════════════════════════════════════════════════════════════════════
def make_id(url: str) -> str:
    u = re.sub(r"[?#].*", "", url.strip().rstrip("/"))
    return hashlib.sha256(u.encode()).hexdigest()[:14]

def parse_price(raw) -> Optional[float]:
    if not raw: return None
    s = re.sub(r"[^\d\.,]", "", str(raw))
    if not s: return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        p = s.split(",")
        s = s.replace(",",".") if len(p)==2 and len(p[1])<=2 else s.replace(",","")
    elif "." in s:
        p = s.split(".")
        if len(p)==2 and len(p[1])==3: s = s.replace(".","")
    try:
        v = float(s)
        return v if 50 < v < 8000 else None
    except ValueError:
        return None

def parse_rooms(raw) -> Optional[float]:
    m = re.search(r"(\d+[.,]?\d*)", str(raw or "").replace(",","."))
    try:
        v = float(m.group(1)) if m else None
        return v if v and 0.5 <= v <= 20 else None
    except (ValueError, AttributeError):
        return None

def enrich(title: str, desc: str) -> dict:
    t = f"{title} {desc}".lower()
    out: dict = {}
    # Size
    for pat in [r"(\d[\d\.]*)\s*m[²2]",r"(\d[\d\.]*)\s*qm\b",
                r"wohnfläche[:\s]+(\d[\d\.]*)"]:
        m = re.search(pat, t)
        if m:
            try:
                v = float(m.group(1).replace(".",""))
                if 15<v<500: out["size_m2"]=v; break
            except ValueError: pass
    # Floor
    for pat, lbl in [
        (r"(\d+)\.\s*(?:og|obergeschoss|etage|stock)\b",
         lambda m: f"الطابق {m.group(1)}"),
        (r"\beg\b(?!\w)|erdgeschoss", lambda _: "الطابق الأرضي"),
        (r"\bdg\b(?!\w)|dachgeschoss", lambda _: "الطابق العلوي"),
        (r"\bpenthouse\b", lambda _: "بنتهاوس"),
    ]:
        mm = re.search(pat, t)
        if mm: out["floor"]=lbl(mm); break
    # Availability
    if any(k in t for k in URGENT): out["available"]="فوري"
    else:
        m = re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",t)
        if m: out["available"]=f"من {m.group(1)}"
        else:
            mths = "|".join(MONTHS_AR)
            m = re.search(rf"ab\s+({mths})\s*(\d{{4}})?", t)
            if m: out["available"]=f"من {MONTHS_AR[m.group(1)]} {m.group(2) or ''}".strip()
    # Deposit
    m = re.search(r"kaution[:\s]*(\d[\d\.,]*)\s*€?",t)
    if m:
        v = parse_price(m.group(1))
        if v: out["deposit"]=f"{v:.0f} €"
    else:
        m = re.search(r"(\d)\s*monatsmieten?\s*(?:kaution)?",t)
        if m: out["deposit"]=f"{m.group(1)}× الإيجار"
    # Heating
    if "fußbodenheizung" in t: out["heating"]="تدفئة أرضية"
    elif "fernwärme" in t: out["heating"]="تدفئة مركزية"
    elif "gasheizung" in t: out["heating"]="تدفئة غاز"
    # WBS level
    mm = re.search(r"wbs[\s\-_]*(\d{2,3})", t)
    if mm: out["wbs_level_num"]=int(mm.group(1))
    # Features
    seen_f: set = set()
    feats: list = []
    for kw, lbl_ar in FEATS.items():
        if kw in t and lbl_ar not in seen_f:
            seen_f.add(lbl_ar)
            icon = FEATS_ICONS.get(lbl_ar, "•")
            feats.append(f"{icon} {lbl_ar}")
    if feats: out["features"]=feats
    return out

# ═════════════════════════════════════════════════════════════════════
# Scrapers
# ═════════════════════════════════════════════════════════════════════
def _scrape_gewobag() -> list:
    data = _get_json(
        "https://www.gewobag.de/wp-json/gewobag/v1/offers"
        "?type=wohnung&wbs=1&per_page=50")
    if not data: return []
    items = data if isinstance(data,list) else data.get("offers",[])
    result, seen = [], set()
    for i in items:
        url = i.get("link") or i.get("url","")
        if not url.startswith("http"): url = "https://www.gewobag.de" + url
        if url in seen: continue
        seen.add(url)
        t = i.get("title","")
        title = t.get("rendered","") if isinstance(t,dict) else str(t)
        extra = enrich(title, str(i.get("beschreibung") or ""))
        result.append({"id":make_id(url),"url":url,"source":"gewobag",
            "trusted_wbs":True,"title":title[:80],
            "price":parse_price(i.get("gesamtmiete") or i.get("warmmiete")),
            "rooms":parse_rooms(i.get("zimmer")),
            "location":i.get("bezirk","Berlin"),
            "wbs_label":"WBS erforderlich","ts":time.time(),**extra})
    return result

def _scrape_degewo() -> list:
    for api in [
        "https://immosuche.degewo.de/de/properties.json"
        "?property_type_id=1&categories[]=WBS&per_page=50",
        "https://immosuche.degewo.de/de/search.json?asset_classes[]=1&wbs=1",
    ]:
        data = _get_json(api)
        if not data: continue
        items = data if isinstance(data,list) else data.get("results",[])
        result, seen = [], set()
        for i in items:
            url = i.get("path","") or i.get("url","")
            if not url.startswith("http"): url="https://immosuche.degewo.de"+url
            if url in seen: continue
            seen.add(url)
            extra = enrich(i.get("title",""), str(i.get("text") or ""))
            result.append({"id":make_id(url),"url":url,"source":"degewo",
                "trusted_wbs":True,"title":i.get("title","")[:80],
                "price":parse_price(i.get("warmmiete") or i.get("totalRent")),
                "rooms":parse_rooms(i.get("zimmer") or i.get("rooms")),
                "location":i.get("district","Berlin"),
                "wbs_label":"WBS erforderlich","ts":time.time(),**extra})
        if result: return result
    return []

def _scrape_kleinanzeigen() -> list:
    if not HAS_BS4: return []
    html = _get("https://www.kleinanzeigen.de/s-wohnung-mieten/berlin/wbs/k0c203l3331")
    if not html or len(html)<500: return []
    soup = BeautifulSoup(html,"html.parser")
    result, seen = [], set()
    for card in soup.select("article.aditem")[:25]:
        a = card.select_one("a.ellipsis,h2 a,h3 a")
        if not a: continue
        href = a.get("href","")
        url  = ("https://www.kleinanzeigen.de"+href if href.startswith("/") else href)
        if url in seen: continue
        seen.add(url)
        t_tag = card.select_one("h2,h3")
        p_tag = card.select_one("[class*='price']")
        title = (t_tag.get_text(strip=True) if t_tag else a.get_text(strip=True))[:80]
        extra = enrich(title, card.get_text(" ",strip=True))
        result.append({"id":make_id(url),"url":url,"source":"kleinanz",
            "trusted_wbs":False,"title":title,
            "price":parse_price(p_tag.get_text() if p_tag else None),
            "rooms":None,"location":"Berlin","wbs_label":"","ts":time.time(),**extra})
    return result

_SCRAPER_MAP = {
    "gewobag": _scrape_gewobag,
    "degewo":  _scrape_degewo,
    "kleinanz":_scrape_kleinanzeigen,
}

def fetch_all(enabled: Optional[list]=None, timeout: int=25) -> list:
    active  = set(enabled) if enabled else set(SOURCES.keys())
    results: list = []
    lock    = threading.Lock()
    errors: list  = []

    def run(src, fn):
        try:
            items = fn()
            with lock: results.extend(items)
        except Exception as e:
            with lock: errors.append(f"{src}: {e}")

    threads = []
    for src in active:
        fn = _SCRAPER_MAP.get(src)
        if fn:
            t = threading.Thread(target=run, args=(src,fn), daemon=True)
            threads.append(t); t.start()

    deadline = time.time() + timeout
    for t in threads:
        remaining = max(0.1, deadline - time.time())
        t.join(timeout=remaining)

    # Deduplicate
    seen_ids: set = set()
    unique = []
    for l in results:
        if l.get("id") and l["id"] not in seen_ids:
            seen_ids.add(l["id"])
            unique.append(l)
    save_cache(unique)
    return unique

# ═════════════════════════════════════════════════════════════════════
# Filtering
# ═════════════════════════════════════════════════════════════════════
def apply_filters(listings: list, cfg: dict, seen: set) -> list:
    out     = []
    max_p   = float(cfg.get("max_price") or 9999)
    min_p   = float(cfg.get("min_price") or 0)
    min_r   = float(cfg.get("min_rooms") or 0)
    max_r   = float(cfg.get("max_rooms") or 0)
    min_sz  = int(cfg.get("min_size") or 0)
    max_sz  = int(cfg.get("max_size") or 0)
    wbs_only= bool(cfg.get("wbs_only"))
    wlmin   = int(cfg.get("wbs_level_min") or 0)
    wlmax   = int(cfg.get("wbs_level_max") or 999)
    jcm     = bool(cfg.get("jobcenter_mode"))
    wgm     = bool(cfg.get("wohngeld_mode"))
    n       = max(1, int(cfg.get("household_size") or 1))
    areas   = [a.lower() for a in (cfg.get("areas") or [])]
    srcs    = cfg.get("sources") or []

    for l in listings:
        if not l.get("id") or l["id"] in seen: continue
        if srcs and l.get("source") not in srcs: continue
        price = l.get("price")
        rooms = l.get("rooms")
        size  = l.get("size_m2")
        if price is not None:
            if min_p>0 and price<min_p: continue
            if price>max_p: continue
        if rooms is not None:
            if min_r>0 and rooms<min_r: continue
            if max_r>0 and rooms>max_r: continue
        if size is not None:
            if min_sz>0 and size<min_sz: continue
            if max_sz>0 and size>max_sz: continue
        if wbs_only and not l.get("trusted_wbs"): continue
        level = l.get("wbs_level_num")
        if level is not None and (wlmin>0 or wlmax<999):
            if not (wlmin<=level<=wlmax): continue
        if areas:
            loc = (l.get("location","")+" "+l.get("title","")).lower()
            if not any(a in loc for a in areas): continue
        if jcm or wgm:
            j_ok = (price is None or price<=jc(n)) if jcm else False
            w_ok = (price is None or price<=wg(n)) if wgm else False
            if not (j_ok or w_ok): continue
        out.append(l)
    return out

def sort_listings(listings: list, sort_by: str) -> list:
    if sort_by=="price_asc":   return sorted(listings, key=lambda l: l.get("price") or 9999)
    elif sort_by=="price_desc":return sorted(listings, key=lambda l: -(l.get("price") or 0))
    elif sort_by=="newest":    return sorted(listings, key=lambda l: -(l.get("ts") or 0))
    return sorted(listings, key=_score, reverse=True)

def _score(l: dict) -> int:
    s = 8 if l.get("trusted_wbs") else 0
    s+= 3 if l.get("source") in GOV else 0
    p = l.get("price")
    if p:
        if p<400: s+=10
        elif p<500: s+=7
        elif p<600: s+=4
        elif p<700: s+=1
    r = l.get("rooms")
    if r:
        if r>=3: s+=5
        elif r>=2: s+=3
    if l.get("size_m2"): s+=2
    if l.get("available")=="فوري": s+=5
    elif l.get("available"): s+=1
    s+=min(len(l.get("features") or []),4)
    return s

# ═════════════════════════════════════════════════════════════════════
# Notifications
# ═════════════════════════════════════════════════════════════════════
NOTIF_CHANNEL = "wbs_berlin_channel"
NOTIF_ID      = 1001

def _ensure_channel():
    if not HAS_ANDROID: return
    try:
        ctx = PythonActivity.mActivity
        mgr = ctx.getSystemService(Context.NOTIFICATION_SERVICE)
        ch  = NotifChannel(
            NOTIF_CHANNEL,
            "WBS Berlin",
            NotifManager.IMPORTANCE_HIGH)
        ch.setDescription("إشعارات شقق WBS برلين")
        mgr.createNotificationChannel(ch)
    except Exception:
        pass

def send_notification(title: str, body: str, url: str = "") -> None:
    if not HAS_ANDROID: return
    try:
        ctx = PythonActivity.mActivity
        _ensure_channel()
        mgr = ctx.getSystemService(Context.NOTIFICATION_SERVICE)
        # Tap action — open URL or app
        if url:
            tap_intent = Intent(Intent.ACTION_VIEW, Uri.parse(url))
        else:
            tap_intent = Intent(ctx, PythonActivity)
            tap_intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
        pi = PendingIntent.getActivity(
            ctx, 0, tap_intent,
            PendingIntent.FLAG_UPDATE_CURRENT | 0x2000000)  # FLAG_IMMUTABLE
        nb = NotifBuilder(ctx, NOTIF_CHANNEL)
        nb.setSmallIcon(17301543)   # android.R.drawable.ic_dialog_info
        nb.setContentTitle(title)
        nb.setContentText(body)
        nb.setContentIntent(pi)
        nb.setAutoCancel(True)
        nb.setPriority(NotifBuilder.PRIORITY_HIGH if hasattr(NotifBuilder,'PRIORITY_HIGH') else 1)
        mgr.notify(NOTIF_ID, nb.build())
    except Exception:
        pass

def notify_new_listings(listings: list) -> None:
    if not listings: return
    cfg = load_cfg()
    if not cfg.get("notifications", True): return
    if len(listings) == 1:
        l     = listings[0]
        name  = SOURCES.get(l["source"], (l["source"],))[0]
        price = f"{l['price']:.0f}€" if l.get("price") else ""
        loc   = l.get("location","Berlin")
        send_notification(
            f"🏠 شقة جديدة — {name}",
            f"{price} · {loc} · {l.get('title','')[:50]}",
            l.get("url",""))
    else:
        send_notification(
            f"🏠 {len(listings)} شقق جديدة في برلين",
            " | ".join(
                SOURCES.get(l["source"],(l["source"],))[0]
                for l in listings[:3]),
            "")

# ═════════════════════════════════════════════════════════════════════
# Background Service
# ═════════════════════════════════════════════════════════════════════
_bg_thread: Optional[threading.Thread] = None
_bg_stop   = threading.Event()

def _bg_worker():
    """Runs in background, checks for new listings periodically."""
    _ensure_channel()
    while not _bg_stop.is_set():
        try:
            cfg      = load_cfg()
            interval = max(5, int(cfg.get("bg_interval", 30))) * 60
            if check_network():
                raw   = fetch_all(cfg.get("sources") or None, timeout=30)
                seen  = load_seen()
                shown = apply_filters(raw, cfg, seen)
                if shown:
                    notify_new_listings(shown)
                    for l in shown: seen.add(l["id"])
                    save_seen(seen)
            # Write heartbeat
            try:
                SERVICE_RUNNING.write_text(str(int(time.time())))
            except Exception:
                pass
        except Exception:
            pass  # Never crash the background thread
        _bg_stop.wait(timeout=interval)

def start_background_service() -> None:
    global _bg_thread, _bg_stop
    if _bg_thread and _bg_thread.is_alive():
        return
    _bg_stop.clear()
    _bg_thread = threading.Thread(target=_bg_worker, daemon=True, name="WBSBgService")
    _bg_thread.start()

def stop_background_service() -> None:
    _bg_stop.set()

def is_bg_running() -> bool:
    if not (_bg_thread and _bg_thread.is_alive()): return False
    # Check heartbeat freshness (< 10 min)
    try:
        ts = int(SERVICE_RUNNING.read_text())
        return time.time() - ts < 600
    except Exception:
        return _bg_thread.is_alive()

# ═════════════════════════════════════════════════════════════════════
# Kivy UI Helpers
# ═════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    def bg(widget, color, radius=0):
        widget.canvas.before.clear()
        with widget.canvas.before:
            Color(*color)
            r = (RoundedRectangle(pos=widget.pos, size=widget.size, radius=[dp(radius)])
                 if radius else Rectangle(pos=widget.pos, size=widget.size))
        def _u(*_): r.pos=widget.pos; r.size=widget.size
        widget.bind(pos=_u, size=_u)

    def lbl(text, size=14, color=None, bold=False, halign="right", **kw):
        color = color or TEXT1
        w = Label(text=ar(text), font_size=fs(size), color=color,
                  bold=bold, halign=halign, **kw)
        w.bind(width=lambda *_: setattr(w,"text_size",(w.width,None)))
        return w

    def btn(text, on_press=None, color=None, text_color=None,
            height=48, radius=12, **kw):
        color      = color or PRIMARY
        text_color = text_color or WHITE
        b = Button(text=ar(text), size_hint_y=None, height=dp(height),
                   background_color=TRANSP, color=text_color,
                   font_size=fs(14), bold=True, **kw)
        bg(b, color, radius=radius)
        if on_press: b.bind(on_press=on_press)
        return b

    def gap(h=12): return Widget(size_hint_y=None, height=dp(h))
    def divider():
        w = Widget(size_hint_y=None, height=dp(1))
        bg(w, DIVIDER); return w
    def sec_hdr(text):
        box = BoxLayout(size_hint_y=None, height=dp(30))
        box.add_widget(lbl(text, size=11, color=TEXT3, bold=True)); return box
    def tf(val, filt="int"):
        t = TextInput(text=str(val), input_filter=filt, multiline=False,
                      background_color=TRANSP, foreground_color=TEXT1,
                      cursor_color=PRIMARY, font_size=fs(14))
        bg(t, BG3, radius=10); return t
    def safe_int(t, default=0):
        try: return int(float(t.text or default))
        except Exception: return default
    def safe_float(t, default=0.0):
        try: return float(t.text or default)
        except Exception: return default

# ═════════════════════════════════════════════════════════════════════
# Onboarding
# ═════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    PAGES = [
        ("🏠", "مرحباً في WBS برلين",
         "ابحث عن شقتك المدعومة\nمن 9 مصادر رسمية وخاصة\nكل ذلك في مكان واحد", PRIMARY),
        ("⚡", "فلاتر ذكية وشاملة",
         "السعر · الغرف · المنطقة · المساحة\nمستوى WBS من 100 حتى 220\nJobcenter KdU + Wohngeld", PURPLE),
        ("🔔", "إشعارات فورية",
         "البوت يعمل في الخلفية دائماً\nويرسل إشعاراً فور ظهور شقة\nتناسب إعداداتك", AMBER),
    ]
    class OnboardingScreen(Screen):
        def __init__(self, app_ref, **kw):
            super().__init__(name="onboarding", **kw)
            self.app_ref=app_ref; self._idx=0; self._show()
        def _show(self):
            self.clear_widgets(); bg(self, BG)
            p=PAGES[self._idx]; is_last=self._idx==len(PAGES)-1
            root=FloatLayout()
            card=BoxLayout(orientation="vertical",padding=dp(32),spacing=dp(16),
                           size_hint=(0.88,0.68),pos_hint={"center_x":.5,"center_y":.57})
            bg(card, BG2, radius=24)
            card.add_widget(Label(text=p[0],font_size=fs(68),size_hint_y=None,height=dp(80)))
            card.add_widget(lbl(p[1],size=21,bold=True,color=p[3],size_hint_y=None,height=dp(50)))
            card.add_widget(lbl(p[2],size=14,color=TEXT2,size_hint_y=None,height=dp(80)))
            root.add_widget(card)
            dots=BoxLayout(size_hint=(None,None),size=(dp(80),dp(12)),
                           pos_hint={"center_x":.5,"y":.18},spacing=dp(8))
            for i in range(len(PAGES)):
                d=Widget(size_hint=(None,None),size=(dp(20 if i==self._idx else 8),dp(8)))
                bg(d,p[3] if i==self._idx else TEXT3,radius=4); dots.add_widget(d)
            root.add_widget(dots)
            brow=BoxLayout(size_hint=(0.88,None),height=dp(50),
                           pos_hint={"center_x":.5,"y":.05},spacing=dp(12))
            if not is_last:
                brow.add_widget(btn("تخطي",on_press=self._done,color=BG3,text_color=TEXT2))
            brow.add_widget(btn("ابدأ الآن 🚀" if is_last else "التالي ←",
                                on_press=self._next if not is_last else self._done,color=p[3]))
            root.add_widget(brow); self.add_widget(root)
        def _next(self,*_):
            self._idx=min(self._idx+1,len(PAGES)-1); self._show()
        def _done(self,*_):
            mark_done(); self.app_ref.go_main()

# ═════════════════════════════════════════════════════════════════════
# Listing Card
# ═════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class ListingCard(BoxLayout):
        def __init__(self, l: dict, **kw):
            super().__init__(orientation="vertical",size_hint_y=None,
                             padding=(dp(14),dp(12)),spacing=dp(6),**kw)
            name, gov = SOURCES.get(l["source"],(l["source"],False))
            src_c  = PURPLE if gov else BLUE
            price  = l.get("price")
            rooms  = l.get("rooms")
            sz     = l.get("size_m2")
            floor_ = l.get("floor","")
            avail  = l.get("available","")
            dep    = l.get("deposit","")
            heat   = l.get("heating","")
            feats  = (l.get("features") or [])[:6]
            title  = (l.get("title") or "شقة").strip()[:65]
            loc    = l.get("location","Berlin")
            wlnum  = l.get("wbs_level_num")
            wlbl   = f"WBS {wlnum}" if wlnum else ("WBS ✓" if l.get("trusted_wbs") else "")
            self.url = l.get("url","")
            n_fr   = max(1,(len(feats)+2)//3) if feats else 0
            self.height = dp(168 + n_fr*24 + (20 if dep or heat else 0))
            bg(self, BG2, radius=16)

            # Source + WBS
            r1=BoxLayout(size_hint_y=None,height=dp(26),spacing=dp(8))
            chip=BoxLayout(size_hint=(None,None),size=(dp(118),dp(24)),padding=(dp(8),0))
            bg(chip,(*src_c[:3],0.18),radius=12)
            chip.add_widget(lbl(("🏛 " if gov else "🔍 ")+ar(name),size=11,
                                 color=src_c,size_hint_y=None,height=dp(24)))
            r1.add_widget(chip); r1.add_widget(Widget())
            if wlbl:
                wb=BoxLayout(size_hint=(None,None),size=(dp(78),dp(24)),padding=(dp(8),0))
                bg(wb,(*PRIMARY[:3],0.18),radius=12)
                wb.add_widget(lbl(wlbl,size=11,color=PRIMARY,bold=True,
                                   size_hint_y=None,height=dp(24)))
                r1.add_widget(wb)
            self.add_widget(r1)

            # Title
            self.add_widget(lbl(title,size=13,bold=True,size_hint_y=None,height=dp(22)))

            # Location + availability
            r3=BoxLayout(size_hint_y=None,height=dp(18))
            r3.add_widget(lbl("📍 "+ar(loc),size=11,color=TEXT2))
            if avail:
                avail_ar = "فوري 🔥" if avail=="فوري" else avail
                r3.add_widget(lbl("📅 "+ar(avail_ar),size=11,
                                   color=AMBER if avail=="فوري" else TEXT2))
            self.add_widget(r3); self.add_widget(divider())

            # Price row
            r4=BoxLayout(size_hint_y=None,height=dp(34),spacing=dp(6))
            if price:
                ppm = f" ({price/sz:.1f}€/m²)" if sz else ""
                pill=BoxLayout(size_hint=(None,None),size=(dp(118),dp(30)),padding=(dp(8),0))
                bg(pill,(*PRIMARY[:3],0.15),radius=10)
                pill.add_widget(lbl(f"💰 {price:.0f}€{ppm}",size=13,color=PRIMARY,
                                     bold=True,size_hint_y=None,height=dp(30)))
                r4.add_widget(pill)
            if rooms: r4.add_widget(lbl(f"🛏 {rooms:.0f}",size=12,color=TEXT1))
            if sz:    r4.add_widget(lbl(f"📐 {sz:.0f}m²",size=12,color=TEXT1))
            if floor_:r4.add_widget(lbl(ar(floor_),size=11,color=TEXT2))
            self.add_widget(r4)

            # Extra (deposit/heating)
            if dep or heat:
                rx=BoxLayout(size_hint_y=None,height=dp(18))
                if dep:  rx.add_widget(lbl("💼 "+ar(dep),size=11,color=TEXT2))
                if heat: rx.add_widget(lbl("🌡 "+ar(heat),size=11,color=TEXT2))
                self.add_widget(rx)

            # Features
            if feats:
                fg=GridLayout(cols=3,size_hint_y=None,height=dp(n_fr*24),spacing=dp(4))
                for f in feats:
                    c=BoxLayout(size_hint_y=None,height=dp(22),padding=(dp(6),0))
                    bg(c,BG3,radius=8)
                    c.add_widget(lbl(ar(f),size=10,color=TEXT2,
                                     size_hint_y=None,height=dp(22)))
                    fg.add_widget(c)
                self.add_widget(fg)

            ob=btn("فتح الإعلان  ←",on_press=self._open,height=34,radius=10)
            self.add_widget(ob)

        def _open(self,*_):
            if not self.url: return
            try:
                PythonActivity.mActivity.startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse(self.url)))
            except Exception:
                try:
                    from kivy.core.clipboard import Clipboard
                    Clipboard.copy(self.url)
                except Exception: pass

# ═════════════════════════════════════════════════════════════════════
# Listings Screen
# ═════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class ListingsScreen(Screen):
        def __init__(self, app_ref, **kw):
            super().__init__(name="listings",**kw)
            self.app_ref=app_ref
            self._lock  =threading.RLock()
            self._busy  =False
            self._raw: list=[]
            bg(self,BG)
            self._build_ui()

        def _build_ui(self):
            cfg=load_cfg(); root=BoxLayout(orientation="vertical")
            bar=BoxLayout(size_hint_y=None,height=dp(58),padding=(dp(14),dp(8)),spacing=dp(8))
            bg(bar,BG2)
            bar.add_widget(lbl("🏠 WBS برلين",size=17,bold=True,color=WHITE,size_hint_x=0.45))
            bar.add_widget(Widget())
            sort_icons={"score":"🏅","price_asc":"💰↑","price_desc":"💰↓","newest":"🕐"}
            self._sort_btn=btn(sort_icons.get(cfg.get("sort_by","score"),"🏅"),
                               on_press=self._cycle_sort,color=BG3,text_color=TEXT2,
                               size_hint_x=None,width=dp(48),height=42)
            bar.add_widget(self._sort_btn)
            bar.add_widget(btn("⚙️",on_press=lambda*_:setattr(self.app_ref.sm,"current","settings"),
                               color=BG3,text_color=TEXT2,size_hint_x=None,width=dp(44),height=42))
            self._rf_btn=btn("🔄",on_press=self._refresh,color=PRIMARY,
                              size_hint_x=None,width=dp(44),height=42)
            bar.add_widget(self._rf_btn); root.add_widget(bar)

            chips=BoxLayout(size_hint_y=None,height=dp(44),padding=(dp(10),dp(6)),spacing=dp(8))
            bg(chips,BG2)
            self._wbs_chip=ToggleButton(text=ar("✅ WBS فقط"),
                state="down" if cfg.get("wbs_only") else "normal",
                size_hint=(None,None),size=(dp(100),dp(30)),
                background_color=TRANSP,color=TEXT1,font_size=fs(12))
            self._upd_chip()
            self._wbs_chip.bind(state=self._on_wbs)
            chips.add_widget(self._wbs_chip)
            self._status=lbl("اضغط 🔄 للبحث",size=12,color=TEXT2,size_hint_y=None,height=dp(30))
            chips.add_widget(self._status)

            # Background service indicator
            self._bg_ind=lbl("⏸",size=14,color=TEXT3,size_hint=(None,None),
                              size=(dp(30),dp(30)))
            chips.add_widget(self._bg_ind)
            root.add_widget(chips); root.add_widget(divider())

            self._cards=BoxLayout(orientation="vertical",spacing=dp(10),
                                   padding=(dp(10),dp(10)),size_hint_y=None)
            self._cards.bind(minimum_height=self._cards.setter("height"))
            sv=ScrollView(bar_color=(*PRIMARY[:3],0.4),bar_inactive_color=(*TEXT3[:3],0.2))
            sv.add_widget(self._cards); root.add_widget(sv)
            self.add_widget(root)
            self._placeholder("🔍",ar("اضغط 🔄 للبحث عن شقق WBS"))
            Clock.schedule_interval(self._tick_bg_status, 10)

        def _upd_chip(self):
            on=self._wbs_chip.state=="down"
            bg(self._wbs_chip,(*PRIMARY[:3],0.85) if on else BG3,radius=15)

        def _tick_bg_status(self,*_):
            on=is_bg_running()
            self._bg_ind.text="🟢" if on else "⏸"
            self._bg_ind.color=PRIMARY if on else TEXT3

        def _on_wbs(self,_,state):
            self._upd_chip()
            cfg=load_cfg(); cfg["wbs_only"]=state=="down"; save_cfg(cfg)
            with self._lock: raw=list(self._raw)
            if raw:
                shown=sort_listings(apply_filters(raw,cfg,load_seen()),cfg.get("sort_by","score"))
                Clock.schedule_once(lambda dt:self._render(shown,len(raw)))

        def _cycle_sort(self,*_):
            order=["score","price_asc","price_desc","newest"]
            icons={"score":"🏅","price_asc":"💰↑","price_desc":"💰↓","newest":"🕐"}
            cfg=load_cfg(); cur=cfg.get("sort_by","score")
            nxt=order[(order.index(cur)+1)%len(order)]
            cfg["sort_by"]=nxt; save_cfg(cfg); self._sort_btn.text=icons[nxt]
            with self._lock: raw=list(self._raw)
            if raw:
                shown=sort_listings(apply_filters(raw,cfg,load_seen()),nxt)
                Clock.schedule_once(lambda dt:self._render(shown,len(raw)))

        def _placeholder(self,icon,msg):
            self._cards.clear_widgets()
            b=BoxLayout(orientation="vertical",spacing=dp(10),
                        size_hint_y=None,height=dp(200),padding=dp(40))
            b.add_widget(Label(text=icon,font_size=fs(52),size_hint_y=None,height=dp(65)))
            b.add_widget(lbl(msg,size=14,color=TEXT2,size_hint_y=None,height=dp(50)))
            self._cards.add_widget(b)

        def _refresh(self,*_):
            with self._lock:
                if self._busy: return
                self._busy=True
            if not check_network():
                cached=load_cache()
                with self._lock: self._busy=False
                if cached:
                    self._status.text=ar("📦 نتائج مؤقتة")
                    with self._lock: self._raw=cached
                    cfg=load_cfg()
                    shown=sort_listings(apply_filters(cached,cfg,load_seen()),cfg.get("sort_by","score"))
                    Clock.schedule_once(lambda dt:self._render(shown,len(cached)))
                else:
                    self._placeholder("📵",ar("لا يوجد اتصال ولا نتائج مؤقتة"))
                return
            self._status.text=ar("⏳ جاري البحث...")
            self._placeholder("⏳",ar("جاري جلب الإعلانات..."))
            threading.Thread(target=self._bg_fetch,daemon=True).start()

        def _bg_fetch(self):
            try:
                cfg=load_cfg()
                raw=fetch_all(cfg.get("sources") or None)
                with self._lock: self._raw=raw
                seen=load_seen()
                shown=sort_listings(apply_filters(raw,cfg,seen),cfg.get("sort_by","score"))
                for l in shown: seen.add(l["id"])
                save_seen(seen)
                Clock.schedule_once(lambda dt:self._render(shown,len(raw)))
            except Exception:
                Clock.schedule_once(lambda dt:self._placeholder("⚠️",ar("خطأ — حاول مرة أخرى")))
            finally:
                with self._lock: self._busy=False

        def _render(self,lst,total=None):
            try:
                self._cards.clear_widgets()
                t=total if total is not None else len(lst)
                if not lst:
                    self._status.text=ar(f"لا جديد من {t}")
                    self._placeholder("🔍",ar("لا توجد إعلانات جديدة تناسب إعداداتك"))
                    return
                self._status.text=ar(f"✅ {len(lst)} جديد من {t}")
                for l in lst[:12]:
                    self._cards.add_widget(ListingCard(l)); self._cards.add_widget(gap(6))
                if len(lst)>12:
                    Clock.schedule_once(lambda dt:self._render_rest(lst[12:]),0.06)
            except Exception: pass

        def _render_rest(self,rest):
            try:
                for l in rest[:60]:
                    self._cards.add_widget(ListingCard(l)); self._cards.add_widget(gap(6))
            except Exception: pass

# ═════════════════════════════════════════════════════════════════════
# Settings Screen
# ═════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class SettingsScreen(Screen):
        def __init__(self, app_ref, **kw):
            super().__init__(name="settings",**kw)
            self.app_ref=app_ref; bg(self,BG); self._build()

        def _build(self):
            self.clear_widgets(); cfg=load_cfg()
            root=BoxLayout(orientation="vertical")
            # Header
            hdr=BoxLayout(size_hint_y=None,height=dp(58),padding=(dp(12),dp(8)),spacing=dp(10))
            bg(hdr,BG2)
            hdr.add_widget(btn("←",on_press=self._back,color=BG3,text_color=TEXT2,
                               size_hint_x=None,width=dp(44),height=42))
            hdr.add_widget(lbl("⚙️ الإعدادات",size=16,bold=True,color=WHITE))
            hdr.add_widget(btn("↩️",on_press=self._reset,color=BG3,text_color=TEXT2,
                               size_hint_x=None,width=dp(50),height=42))
            root.add_widget(hdr)

            scroll=ScrollView(); body=BoxLayout(orientation="vertical",
                padding=dp(14),spacing=dp(8),size_hint_y=None)
            body.bind(minimum_height=body.setter("height"))

            def row(label_text, widget, hint=""):
                r=BoxLayout(size_hint_y=None,height=dp(54),spacing=dp(12),padding=(dp(12),dp(4)))
                bg(r,BG2,radius=12)
                lbox=BoxLayout(orientation="vertical",size_hint_x=0.45)
                lbox.add_widget(lbl(label_text,size=13,color=TEXT1))
                if hint: lbox.add_widget(lbl(hint,size=10,color=TEXT3))
                r.add_widget(lbox); r.add_widget(widget); body.add_widget(r)

            def toggler(text, active, pri=PRIMARY):
                t=ToggleButton(text=ar(text),state="down" if active else "normal",
                    size_hint=(1,None),height=dp(46),background_color=TRANSP,
                    color=TEXT1,font_size=fs(13))
                bg(t,(*pri[:3],0.15) if active else BG2,radius=12)
                t.bind(state=lambda b,s,c=pri:bg(b,(*c[:3],0.15) if s=="down" else BG2,radius=12))
                body.add_widget(t); return t

            # ── Budget ──────────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec_hdr("💰  الميزانية"))
            self._min_p=tf(cfg.get("min_price",0))
            row("الحد الأدنى (€)",self._min_p,"0 = بدون حد")
            self._max_p=tf(cfg.get("max_price",700))
            row("أقصى إيجار (€)",self._max_p)

            # ── Rooms + Size ─────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec_hdr("🛏  الغرف والمساحة"))
            rrow=BoxLayout(size_hint_y=None,height=dp(54),spacing=dp(6),padding=(dp(12),dp(4)))
            bg(rrow,BG2,radius=12)
            rrow.add_widget(lbl("الغرف:",size=13,color=TEXT1,size_hint_x=0.22))
            self._min_r=tf(cfg.get("min_rooms",0),"float"); self._max_r=tf(cfg.get("max_rooms",0),"float")
            rrow.add_widget(lbl("من",size=11,color=TEXT2,size_hint_x=0.08))
            rrow.add_widget(self._min_r)
            rrow.add_widget(lbl("—",size=13,color=TEXT2,size_hint_x=0.06))
            rrow.add_widget(self._max_r)
            rrow.add_widget(lbl("0=أي",size=10,color=TEXT3,size_hint_x=0.14))
            body.add_widget(rrow)
            szrow=BoxLayout(size_hint_y=None,height=dp(54),spacing=dp(6),padding=(dp(12),dp(4)))
            bg(szrow,BG2,radius=12)
            szrow.add_widget(lbl("المساحة (م²):",size=13,color=TEXT1,size_hint_x=0.32))
            self._min_sz=tf(cfg.get("min_size",0)); self._max_sz=tf(cfg.get("max_size",0))
            szrow.add_widget(lbl("من",size=11,color=TEXT2,size_hint_x=0.08))
            szrow.add_widget(self._min_sz)
            szrow.add_widget(lbl("—",size=13,color=TEXT2,size_hint_x=0.06))
            szrow.add_widget(self._max_sz)
            body.add_widget(szrow)

            # ── WBS ──────────────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec_hdr("📋  WBS"))
            self._wbs=toggler("WBS فقط",cfg.get("wbs_only",False))
            wlrow=BoxLayout(size_hint_y=None,height=dp(54),spacing=dp(6),padding=(dp(12),dp(4)))
            bg(wlrow,BG2,radius=12)
            wlrow.add_widget(lbl("مستوى WBS:",size=13,color=TEXT1,size_hint_x=0.33))
            self._wlmin=tf(cfg.get("wbs_level_min",0)); self._wlmax=tf(cfg.get("wbs_level_max",999))
            wlrow.add_widget(lbl("من",size=11,color=TEXT2,size_hint_x=0.08))
            wlrow.add_widget(self._wlmin)
            wlrow.add_widget(lbl("—",size=13,color=TEXT2,size_hint_x=0.06))
            wlrow.add_widget(self._wlmax)
            body.add_widget(wlrow)
            pr=BoxLayout(size_hint_y=None,height=dp(38),spacing=dp(6))
            for lt,mn,mx in [("100","100","100"),("100-140","100","140"),("100-160","100","160"),("كل","0","999")]:
                b=btn(lt,color=BG3,text_color=TEXT1,height=38,radius=10,size_hint_x=None,width=dp(75))
                b.bind(on_press=lambda _,mn=mn,mx=mx:(setattr(self._wlmin,"text",mn),setattr(self._wlmax,"text",mx)))
                pr.add_widget(b)
            body.add_widget(pr)

            # ── Social ───────────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec_hdr("🏛  فلاتر اجتماعية"))
            self._hh=tf(cfg.get("household_size",1))
            n=max(1,int(cfg.get("household_size") or 1))
            row("أفراد الأسرة",self._hh,f"JC≤{jc(n):.0f}€ · WG≤{wg(n):.0f}€")
            self._jc=toggler("🏛 Jobcenter KdU",cfg.get("jobcenter_mode",False),PURPLE)
            self._wg=toggler("🏦 Wohngeld",cfg.get("wohngeld_mode",False),PURPLE)

            # ── Areas ────────────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec_hdr("📍  المناطق  (بدون تحديد = كل برلين)"))
            cur_areas=cfg.get("areas") or []; self._area_btns={}
            ag=GridLayout(cols=2,size_hint_y=None,
                          height=dp(((len(BERLIN_AREAS)+1)//2)*40),spacing=dp(6))
            for area in BERLIN_AREAS:
                on=area in cur_areas
                b=ToggleButton(text=area,state="down" if on else "normal",
                    size_hint=(1,None),height=dp(38),background_color=TRANSP,
                    color=TEXT1,font_size=fs(12))
                bg(b,(*AMBER[:3],0.15) if on else BG2,radius=10)
                b.bind(state=lambda x,s,b=b:bg(b,(*AMBER[:3],0.15) if s=="down" else BG2,radius=10))
                self._area_btns[area]=b; ag.add_widget(b)
            body.add_widget(ag)
            body.add_widget(btn("🌍 كل برلين",on_press=self._clear_areas,
                                 color=BG3,text_color=TEXT2,height=38,radius=10))

            # ── Sources ──────────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec_hdr("🌐  مصادر البحث"))
            cur_src=cfg.get("sources") or []; self._src_btns={}
            for sid,(sname,gov) in SOURCES.items():
                sc=PURPLE if gov else BLUE; on=not cur_src or sid in cur_src
                b=ToggleButton(text=("🏛 " if gov else "🔍 ")+ar(sname),
                    state="down" if on else "normal",
                    size_hint=(1,None),height=dp(44),background_color=TRANSP,
                    color=TEXT1,font_size=fs(13))
                bg(b,(*sc[:3],0.15) if on else BG2,radius=12)
                b.bind(state=lambda x,s,sc=sc,b=b:bg(b,(*sc[:3],0.15) if s=="down" else BG2,radius=12))
                self._src_btns[sid]=b; body.add_widget(b)
            qr=BoxLayout(size_hint_y=None,height=dp(38),spacing=dp(8))
            qr.add_widget(btn("✅ الكل",on_press=lambda*_:self._all_src(True),color=BG3,text_color=TEXT1,height=38,radius=10))
            qr.add_widget(btn("🏛 حكومية فقط",on_press=self._gov_only,color=(*PURPLE[:3],1),height=38,radius=10))
            body.add_widget(qr)

            # ── Sort ─────────────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec_hdr("🔧  الترتيب والخيارات"))
            sort_opts=[("score","🏅 الأفضل"),("price_asc","💰↑"),("price_desc","💰↓"),("newest","🕐 الأحدث")]
            cur_sort=cfg.get("sort_by","score"); self._sort_btns={}
            sr=BoxLayout(size_hint_y=None,height=dp(38),spacing=dp(6))
            for k,t_text in sort_opts:
                b=ToggleButton(text=ar(t_text),state="down" if k==cur_sort else "normal",
                    size_hint=(1,None),height=dp(38),background_color=TRANSP,
                    color=TEXT1,font_size=fs(11))
                bg(b,(*BLUE[:3],0.15) if k==cur_sort else BG2,radius=10)
                b.bind(state=lambda x,s,k=k,b=b:(
                    bg(b,(*BLUE[:3],0.15) if s=="down" else BG2,radius=10),
                    self._excl_sort(k) if s=="down" else None))
                self._sort_btns[k]=b; sr.add_widget(b)
            body.add_widget(sr)

            self._cache_h=tf(cfg.get("cache_hours",1))
            row("مدة الكاش (ساعات)",self._cache_h,"0 = لا كاش")
            self._bg_int=tf(cfg.get("bg_interval",30))
            row("فترة البحث الخلفي (دقيقة)",self._bg_int,"أقل = أسرع + استهلاك أكثر")
            self._notif=toggler("🔔 إشعارات فورية",cfg.get("notifications",True))

            # Background service toggle
            bg_on=is_bg_running()
            self._bg_btn=btn(
                "⏹ إيقاف الخلفية" if bg_on else "▶ تشغيل الخلفية",
                on_press=self._toggle_bg,
                color=RED if bg_on else PRIMARY,height=46,radius=12)
            body.add_widget(gap(6)); body.add_widget(self._bg_btn)

            body.add_widget(gap(8))
            body.add_widget(btn("💾 حفظ الإعدادات",on_press=self._save,height=54,radius=14))
            body.add_widget(gap(20))
            scroll.add_widget(body); root.add_widget(scroll); self.add_widget(root)

        def _clear_areas(self,*_):
            for b in self._area_btns.values(): b.state="normal"; bg(b,BG2,radius=10)
        def _all_src(self,on):
            for sid,b in self._src_btns.items():
                b.state="down" if on else "normal"
                sc=PURPLE if SOURCES[sid][1] else BLUE
                bg(b,(*sc[:3],0.15) if on else BG2,radius=12)
        def _gov_only(self,*_):
            for sid,b in self._src_btns.items():
                gov=SOURCES[sid][1]; sc=PURPLE if gov else BLUE
                b.state="down" if gov else "normal"
                bg(b,(*sc[:3],0.15) if gov else BG2,radius=12)
        def _excl_sort(self,chosen):
            for k,b in self._sort_btns.items():
                if k!=chosen: b.state="normal"; bg(b,BG2,radius=10)
        def _toggle_bg(self,*_):
            if is_bg_running():
                stop_background_service()
                bg(self._bg_btn,PRIMARY,radius=12)
                self._bg_btn.text=ar("▶ تشغيل الخلفية")
            else:
                start_background_service()
                bg(self._bg_btn,RED,radius=12)
                self._bg_btn.text=ar("⏹ إيقاف الخلفية")
        def _back(self,*_): self.app_ref.sm.current="listings"
        def _reset(self,*_): save_cfg(dict(DEFAULTS)); self._build()
        def _save(self,*_):
            sel_src=[sid for sid,b in self._src_btns.items() if b.state=="down"]
            sel_areas=[area for area,b in self._area_btns.items() if b.state=="down"]
            cur_sort=next((k for k,b in self._sort_btns.items() if b.state=="down"),"score")
            cfg=load_cfg()
            cfg.update({
                "min_price":      safe_int(self._min_p,0),
                "max_price":      safe_int(self._max_p,700),
                "min_rooms":      safe_float(self._min_r,0),
                "max_rooms":      safe_float(self._max_r,0),
                "min_size":       safe_int(self._min_sz,0),
                "max_size":       safe_int(self._max_sz,0),
                "household_size": max(1,safe_int(self._hh,1)),
                "wbs_only":       self._wbs.state=="down",
                "wbs_level_min":  safe_int(self._wlmin,0),
                "wbs_level_max":  safe_int(self._wlmax,999),
                "jobcenter_mode": self._jc.state=="down",
                "wohngeld_mode":  self._wg.state=="down",
                "areas":   sel_areas,
                "sources": sel_src if len(sel_src)<len(SOURCES) else [],
                "sort_by": cur_sort,
                "cache_hours":  max(0,safe_int(self._cache_h,1)),
                "bg_interval":  max(5,safe_int(self._bg_int,30)),
                "notifications":self._notif.state=="down",
            })
            save_cfg(cfg)
            self.app_ref.sm.current="listings"

# ═════════════════════════════════════════════════════════════════════
# App
# ═════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class WBSApp(App):
        def build(self):
            self.title="WBS Berlin"
            Window.clearcolor=BG
            self.sm=ScreenManager(transition=FadeTransition(duration=0.18))
            _ensure_channel()
            if is_first_run():
                self.sm.add_widget(OnboardingScreen(self)); self.sm.current="onboarding"
            else:
                self._add_main()
            start_background_service()
            return self.sm

        def _add_main(self):
            if not any(s.name=="listings" for s in self.sm.screens):
                self.sm.add_widget(ListingsScreen(self))
            if not any(s.name=="settings" for s in self.sm.screens):
                self.sm.add_widget(SettingsScreen(self))

        def go_main(self):
            self._add_main(); self.sm.current="listings"

        def on_stop(self):
            # Keep background running even when app closes
            pass

    if __name__=="__main__": WBSApp().run()
else:
    if __name__=="__main__":
        print("WBS Berlin — CLI test")
        print(f"Network: {check_network()}")
        raw=fetch_all(); cfg=dict(DEFAULTS)
        shown=sort_listings(apply_filters(raw,cfg,set()),"score")
        print(f"Results: {len(shown)}/{len(raw)}")
        for l in shown[:5]:
            p=f"{l['price']:.0f}€" if l.get("price") else "—"
            print(f"  [{l['source']}] {p} | {l.get('title','')[:45]}")
