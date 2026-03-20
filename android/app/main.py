"""
WBS Berlin v4.0
- SQLite database (no duplicate listings ever)
- Favorites screen
- Statistics screen
- Full customization (font, theme accent, intervals)
- Background service with notification
- Rock-solid stability
"""
import json, os, re, hashlib, threading, socket, time, ssl, sqlite3, shutil
import urllib.request, urllib.parse
from pathlib import Path
from datetime import datetime
from typing import Optional

# ── Arabic ────────────────────────────────────────────────────────────
try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    def ar(text: str) -> str:
        if not text: return ""
        try: return get_display(arabic_reshaper.reshape(str(text)))
        except Exception: return str(text)
except ImportError:
    def ar(text: str) -> str: return str(text) if text else ""

# ── bs4 ───────────────────────────────────────────────────────────────
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

# ── Kivy ──────────────────────────────────────────────────────────────
try:
    from kivy.app import App
    from kivy.uix.screenmanager import ScreenManager, Screen, FadeTransition, SlideTransition
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.gridlayout import GridLayout
    from kivy.uix.floatlayout import FloatLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.textinput import TextInput
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.togglebutton import ToggleButton
    from kivy.uix.widget import Widget
    from kivy.uix.slider import Slider
    from kivy.uix.spinner import Spinner
    from kivy.graphics import Color, RoundedRectangle, Rectangle, Ellipse, Line
    from kivy.clock import Clock
    from kivy.metrics import dp, sp
    from kivy.utils import get_color_from_hex
    from kivy.core.window import Window
    from kivy.animation import Animation
    HAS_KIVY = True
except ImportError:
    HAS_KIVY = False

# ── Android APIs ──────────────────────────────────────────────────────
try:
    import jnius
    PythonActivity = jnius.autoclass("org.kivy.android.PythonActivity")
    Intent         = jnius.autoclass("android.content.Intent")
    Uri            = jnius.autoclass("android.net.Uri")
    NM             = jnius.autoclass("android.app.NotificationManager")
    NB             = jnius.autoclass("android.app.Notification$Builder")
    NC             = jnius.autoclass("android.app.NotificationChannel")
    PI             = jnius.autoclass("android.app.PendingIntent")
    CTX            = jnius.autoclass("android.content.Context")
    HAS_ANDROID    = True
except Exception:
    HAS_ANDROID = False

# ═══════════════════════════════════════════════════════════════════════
# Design System — configurable accent color
# ═══════════════════════════════════════════════════════════════════════
ACCENT_PRESETS = {
    "أخضر":  "#22C55E",
    "أزرق":  "#3B82F6",
    "بنفسجي":"#8B5CF6",
    "ذهبي":  "#F59E0B",
    "وردي":  "#EC4899",
    "سماوي": "#06B6D4",
}

if HAS_KIVY:
    BG      = get_color_from_hex("#080808")
    BG2     = get_color_from_hex("#111111")
    BG3     = get_color_from_hex("#1A1A1A")
    BG4     = get_color_from_hex("#222222")
    PURPLE  = get_color_from_hex("#8B5CF6")
    BLUE    = get_color_from_hex("#3B82F6")
    AMBER   = get_color_from_hex("#F59E0B")
    RED     = get_color_from_hex("#EF4444")
    GREEN   = get_color_from_hex("#22C55E")
    GOLD    = get_color_from_hex("#F59E0B")
    TEXT1   = get_color_from_hex("#F1F5F9")
    TEXT2   = get_color_from_hex("#94A3B8")
    TEXT3   = get_color_from_hex("#475569")
    DIVIDER = get_color_from_hex("#1A1A1A")
    WHITE   = (1,1,1,1)
    TRANSP  = (0,0,0,0)
    _PRIMARY = [0.134, 0.773, 0.369, 1.0]  # default green

    def PRIMARY():       return tuple(_PRIMARY)
    def set_accent(hex_: str):
        c = get_color_from_hex(hex_)
        _PRIMARY[0] = c[0]; _PRIMARY[1] = c[1]
        _PRIMARY[2] = c[2]; _PRIMARY[3] = c[3]

    _FONT_SCALE = [1.0]
    def fs(n: float) -> float: return sp(n * _FONT_SCALE[0])
    def set_font_scale(s: float): _FONT_SCALE[0] = max(0.8, min(1.4, s))

# ═══════════════════════════════════════════════════════════════════════
# Storage Paths
# ═══════════════════════════════════════════════════════════════════════
_sd         = Path(os.environ.get("EXTERNAL_STORAGE", "."))
DB_PATH     = _sd / "wbs4.db"
FIRST_RUN   = _sd / "wbs4_first"
SVC_BEAT    = _sd / "wbs4_svc.beat"

# ═══════════════════════════════════════════════════════════════════════
# SQLite Database
# ═══════════════════════════════════════════════════════════════════════
_db_lock = threading.RLock()

DDL = """
CREATE TABLE IF NOT EXISTS listings (
    id          TEXT PRIMARY KEY,
    url         TEXT NOT NULL,
    source      TEXT,
    title       TEXT,
    price       REAL,
    rooms       REAL,
    size_m2     REAL,
    floor_      TEXT,
    available   TEXT,
    location    TEXT,
    wbs_label   TEXT,
    wbs_level   INTEGER,
    features    TEXT DEFAULT '[]',
    deposit     TEXT,
    heating     TEXT,
    score       INTEGER DEFAULT 0,
    trusted_wbs INTEGER DEFAULT 0,
    favorited   INTEGER DEFAULT 0,
    hidden      INTEGER DEFAULT 0,
    seen        INTEGER DEFAULT 0,
    notified    INTEGER DEFAULT 0,
    ts_found    REAL,
    ts_seen     REAL
);
CREATE INDEX IF NOT EXISTS idx_ts    ON listings(ts_found DESC);
CREATE INDEX IF NOT EXISTS idx_src   ON listings(source);
CREATE INDEX IF NOT EXISTS idx_fav   ON listings(favorited);
CREATE INDEX IF NOT EXISTS idx_seen  ON listings(seen);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS stats (
    id          INTEGER PRIMARY KEY CHECK(id=1),
    total_found INTEGER DEFAULT 0,
    total_new   INTEGER DEFAULT 0,
    total_notif INTEGER DEFAULT 0,
    last_check  REAL,
    last_new    REAL,
    app_opens   INTEGER DEFAULT 0
);
INSERT OR IGNORE INTO stats(id) VALUES(1);
"""

def _db() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH), timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con

def init_db() -> None:
    with _db_lock:
        con = _db()
        con.executescript(DDL)
        con.commit()
        con.close()

def is_known(lid: str) -> bool:
    with _db_lock:
        con = _db()
        try:
            r = con.execute("SELECT 1 FROM listings WHERE id=?", (lid,)).fetchone()
            return r is not None
        finally:
            con.close()

def are_known(ids: list) -> set:
    if not ids: return set()
    with _db_lock:
        con = _db()
        try:
            result = set()
            for i in range(0, len(ids), 500):
                chunk = ids[i:i+500]
                ph = ",".join("?"*len(chunk))
                rows = con.execute(f"SELECT id FROM listings WHERE id IN ({ph})", chunk).fetchall()
                result.update(r[0] for r in rows)
            return result
        finally:
            con.close()

def save_listing(l: dict) -> bool:
    """Returns True if it's a new listing."""
    lid = l.get("id")
    if not lid: return False
    with _db_lock:
        con = _db()
        try:
            existing = con.execute("SELECT id FROM listings WHERE id=?", (lid,)).fetchone()
            if existing: return False
            feats = json.dumps(l.get("features") or [], ensure_ascii=False)
            con.execute("""
                INSERT OR IGNORE INTO listings
                (id,url,source,title,price,rooms,size_m2,floor_,available,
                 location,wbs_label,wbs_level,features,deposit,heating,
                 score,trusted_wbs,ts_found)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (lid, l.get("url"), l.get("source"), l.get("title"),
                  l.get("price"), l.get("rooms"), l.get("size_m2"),
                  l.get("floor"), l.get("available"), l.get("location"),
                  l.get("wbs_label"), l.get("wbs_level_num"),
                  feats, l.get("deposit"), l.get("heating"),
                  l.get("score",0), 1 if l.get("trusted_wbs") else 0,
                  time.time()))
            con.execute("UPDATE stats SET total_found=total_found+1, "
                        "total_new=total_new+1, last_new=? WHERE id=1", (time.time(),))
            con.commit()
            return True
        except Exception:
            return False
        finally:
            con.close()

def mark_seen(ids: list) -> None:
    if not ids: return
    with _db_lock:
        con = _db()
        try:
            now = time.time()
            for i in range(0, len(ids), 500):
                chunk = ids[i:i+500]
                ph = ",".join("?"*len(chunk))
                con.execute(f"UPDATE listings SET seen=1, ts_seen=? WHERE id IN ({ph})",
                            [now] + chunk)
            con.commit()
        finally:
            con.close()

def toggle_favorite(lid: str) -> bool:
    """Returns new favorite state."""
    with _db_lock:
        con = _db()
        try:
            cur = con.execute("SELECT favorited FROM listings WHERE id=?", (lid,)).fetchone()
            if not cur: return False
            new_val = 0 if cur[0] else 1
            con.execute("UPDATE listings SET favorited=? WHERE id=?", (new_val, lid))
            con.commit()
            return bool(new_val)
        finally:
            con.close()

def hide_listing(lid: str) -> None:
    with _db_lock:
        con = _db()
        try:
            con.execute("UPDATE listings SET hidden=1 WHERE id=?", (lid,))
            con.commit()
        finally:
            con.close()

def get_favorites() -> list:
    with _db_lock:
        con = _db()
        try:
            rows = con.execute(
                "SELECT * FROM listings WHERE favorited=1 ORDER BY ts_found DESC LIMIT 100"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            con.close()

def get_stats_db() -> dict:
    with _db_lock:
        con = _db()
        try:
            r = con.execute("SELECT * FROM stats WHERE id=1").fetchone()
            total = con.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            sources = con.execute(
                "SELECT source, COUNT(*) as cnt FROM listings GROUP BY source"
            ).fetchall()
            return {
                "total_found":   r["total_found"] if r else 0,
                "total_new":     r["total_new"]   if r else 0,
                "total_notif":   r["total_notif"] if r else 0,
                "last_check":    r["last_check"]  if r else None,
                "last_new":      r["last_new"]    if r else None,
                "app_opens":     r["app_opens"]   if r else 0,
                "db_total":      total,
                "by_source":     {row["source"]: row["cnt"] for row in sources},
            }
        finally:
            con.close()

def bump_opens() -> None:
    with _db_lock:
        con = _db()
        try:
            con.execute("UPDATE stats SET app_opens=app_opens+1 WHERE id=1")
            con.commit()
        finally:
            con.close()

def purge_old(days: int = 60) -> int:
    cutoff = time.time() - days * 86400
    with _db_lock:
        con = _db()
        try:
            r = con.execute(
                "DELETE FROM listings WHERE ts_found<? AND favorited=0", (cutoff,)
            )
            con.commit()
            return r.rowcount
        finally:
            con.close()

# ── Settings in DB ─────────────────────────────────────────────────────
def _sget(key: str, default=None):
    with _db_lock:
        con = _db()
        try:
            r = con.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
            if r is None: return default
            return json.loads(r[0])
        except Exception:
            return default
        finally:
            con.close()

def _sset(key: str, value) -> None:
    with _db_lock:
        con = _db()
        try:
            con.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)",
                        (key, json.dumps(value, ensure_ascii=False)))
            con.commit()
        finally:
            con.close()

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
    "bg_interval": 30,
    "notifications": True,
    "font_scale": 1.0,
    "accent": "#22C55E",
    "notify_sound": True,
    "purge_days": 60,
    "show_hidden": False,
}

def load_cfg() -> dict:
    cfg = dict(DEFAULTS)
    try:
        stored = _sget("main_cfg", {})
        if isinstance(stored, dict):
            cfg.update(stored)
    except Exception:
        pass
    return cfg

def save_cfg(c: dict) -> None:
    _sset("main_cfg", c)

def is_first_run() -> bool: return not FIRST_RUN.exists()
def mark_done():
    try: FIRST_RUN.write_text("1")
    except Exception: pass

# ═══════════════════════════════════════════════════════════════════════
# Domain Data
# ═══════════════════════════════════════════════════════════════════════
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
JC_KDU = {1:549,2:671,3:789,4:911,5:1021,6:1131}
WG_LIM = {1:580,2:680,3:800,4:910,5:1030,6:1150,7:1270}
def jc(n):
    n=max(1,min(int(n),10))
    return JC_KDU.get(min(n,6), JC_KDU[6]+(n-6)*110)
def wg(n):
    n=max(1,min(int(n),10))
    return WG_LIM.get(min(n,7), WG_LIM[7]+(n-7)*120)

FEATS = {
    "balkon":"🌿 بلكونة","terrasse":"🌿 تراس","dachterrasse":"🌿 تراس علوي",
    "garten":"🌱 حديقة","aufzug":"🛗 مصعد","fahrstuhl":"🛗 مصعد",
    "einbauküche":"🍳 مطبخ مجهز","keller":"📦 مخزن","abstellraum":"📦 مخزن",
    "stellplatz":"🚗 موقف","tiefgarage":"🚗 جراج","barrierefrei":"♿ بدون عوائق",
    "neubau":"🏗 بناء جديد","erstbezug":"✨ أول سكن",
    "parkett":"🪵 باركيه","laminat":"🪵 لامينيت",
    "fußbodenheizung":"🌡 تدفئة أرضية","fernwärme":"🌡 تدفئة مركزية",
    "saniert":"🔨 مجدد","waschmaschine":"🫧 غسالة",
    "badewanne":"🛁 حوض","sep. wc":"🚽 حمام منفصل","rolladen":"🪟 ستائر",
}
URGENT = ["ab sofort","sofort frei","sofort verfügbar"]
MONTHS_AR = {
    "januar":"يناير","februar":"فبراير","märz":"مارس","april":"أبريل",
    "mai":"مايو","juni":"يونيو","juli":"يوليو","august":"أغسطس",
    "september":"سبتمبر","oktober":"أكتوبر","november":"نوفمبر","dezember":"ديسمبر",
}

# ═══════════════════════════════════════════════════════════════════════
# Network + Scrapers
# ═══════════════════════════════════════════════════════════════════════
_SSL = ssl.create_default_context()
try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL.check_hostname = False
    _SSL.verify_mode    = ssl.CERT_NONE

_UA = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/124.0"

def check_network() -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(("8.8.8.8",53)); s.close(); return True
    except Exception: return False

def _get(url: str) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent":_UA,"Accept-Language":"de-DE,de;q=0.9"})
        with urllib.request.urlopen(req,timeout=12,context=_SSL) as r:
            enc = r.headers.get_content_charset("utf-8")
            return r.read().decode(enc,"replace")
    except Exception: return None

def _get_json(url: str) -> Optional[object]:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent":_UA,"Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=12,context=_SSL) as r:
            return json.loads(r.read())
    except Exception: return None

def make_id(url: str) -> str:
    u = re.sub(r"[?#].*","",url.strip().rstrip("/"))
    return hashlib.sha256(u.encode()).hexdigest()[:14]

def parse_price(raw) -> Optional[float]:
    if not raw: return None
    s = re.sub(r"[^\d\.,]","",str(raw))
    if not s: return None
    if "," in s and "." in s: s=s.replace(".","").replace(",",".")
    elif "," in s:
        p=s.split(",")
        s=s.replace(",",".") if len(p)==2 and len(p[1])<=2 else s.replace(",","")
    elif "." in s:
        p=s.split(".")
        if len(p)==2 and len(p[1])==3: s=s.replace(".","")
    try:
        v=float(s); return v if 50<v<8000 else None
    except ValueError: return None

def parse_rooms(raw) -> Optional[float]:
    m=re.search(r"(\d+[.,]?\d*)",str(raw or "").replace(",","."))
    try:
        v=float(m.group(1)) if m else None
        return v if v and 0.5<=v<=20 else None
    except Exception: return None

def enrich(title: str, desc: str) -> dict:
    t=f"{title} {desc}".lower(); out={}
    for pat in [r"(\d[\d\.]*)\s*m[²2]",r"(\d[\d\.]*)\s*qm\b",r"wohnfläche[:\s]+(\d[\d\.]*)"]:
        m=re.search(pat,t)
        if m:
            try:
                v=float(m.group(1).replace(".",""))
                if 15<v<500: out["size_m2"]=v; break
            except ValueError: pass
    for pat,lbl_fn in [
        (r"(\d+)\.\s*(?:og|obergeschoss|etage|stock)\b",lambda m:f"الطابق {m.group(1)}"),
        (r"\beg\b(?!\w)|erdgeschoss",lambda _:"الطابق الأرضي"),
        (r"\bdg\b(?!\w)|dachgeschoss",lambda _:"الطابق العلوي"),
        (r"\bpenthouse\b",lambda _:"بنتهاوس"),
    ]:
        mm=re.search(pat,t)
        if mm: out["floor"]=lbl_fn(mm); break
    if any(k in t for k in URGENT): out["available"]="فوري"
    else:
        m=re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",t)
        if m: out["available"]=f"من {m.group(1)}"
        else:
            mths="|".join(MONTHS_AR)
            m=re.search(rf"ab\s+({mths})\s*(\d{{4}})?",t)
            if m: out["available"]=f"من {MONTHS_AR[m.group(1)]} {m.group(2) or ''}".strip()
    m=re.search(r"kaution[:\s]*(\d[\d\.,]*)\s*€?",t)
    if m:
        v=parse_price(m.group(1))
        if v: out["deposit"]=f"{v:.0f} €"
    else:
        m=re.search(r"(\d)\s*monatsmieten?\s*(?:kaution)?",t)
        if m: out["deposit"]=f"{m.group(1)}× إيجار"
    if "fußbodenheizung" in t: out["heating"]="🌡 تدفئة أرضية"
    elif "fernwärme" in t:      out["heating"]="🌡 مركزية"
    elif "gasheizung" in t:     out["heating"]="🔥 غاز"
    mm=re.search(r"wbs[\s\-_]*(\d{2,3})",t)
    if mm: out["wbs_level_num"]=int(mm.group(1))
    seen_f=set(); feats=[]
    for kw,lbl_ar in FEATS.items():
        if kw in t and lbl_ar not in seen_f: seen_f.add(lbl_ar); feats.append(lbl_ar)
    if feats: out["features"]=feats
    return out

def _score_listing(l: dict) -> int:
    s=8 if l.get("trusted_wbs") else 0
    s+=3 if l.get("source") in GOV else 0
    p=l.get("price")
    if p:
        if p<400: s+=10
        elif p<500: s+=7
        elif p<600: s+=4
        elif p<700: s+=1
    r=l.get("rooms")
    if r:
        if r>=3: s+=5
        elif r>=2: s+=3
    if l.get("size_m2"): s+=2
    if l.get("available")=="فوري": s+=5
    elif l.get("available"): s+=1
    s+=min(len(l.get("features") or []),4)
    return s

def _scrape_gewobag() -> list:
    data=_get_json("https://www.gewobag.de/wp-json/gewobag/v1/offers?type=wohnung&wbs=1&per_page=50")
    if not data: return []
    items=data if isinstance(data,list) else data.get("offers",[])
    result=[]; seen=set()
    for i in items:
        url=i.get("link") or i.get("url","")
        if not url.startswith("http"): url="https://www.gewobag.de"+url
        if url in seen: continue; seen.add(url)
        t=i.get("title",""); title=t.get("rendered","") if isinstance(t,dict) else str(t)
        extra=enrich(title,str(i.get("beschreibung") or ""))
        l={"id":make_id(url),"url":url,"source":"gewobag","trusted_wbs":True,
           "title":title[:80],"price":parse_price(i.get("gesamtmiete") or i.get("warmmiete")),
           "rooms":parse_rooms(i.get("zimmer")),"location":i.get("bezirk","Berlin"),
           "wbs_label":"WBS erforderlich","ts":time.time(),**extra}
        l["score"]=_score_listing(l); result.append(l)
    return result

def _scrape_degewo() -> list:
    for api in [
        "https://immosuche.degewo.de/de/properties.json?property_type_id=1&categories[]=WBS&per_page=50",
        "https://immosuche.degewo.de/de/search.json?asset_classes[]=1&wbs=1",
    ]:
        data=_get_json(api)
        if not data: continue
        items=data if isinstance(data,list) else data.get("results",[])
        result=[]; seen=set()
        for i in items:
            url=i.get("path","") or i.get("url","")
            if not url.startswith("http"): url="https://immosuche.degewo.de"+url
            if url in seen: continue; seen.add(url)
            extra=enrich(i.get("title",""),str(i.get("text") or ""))
            l={"id":make_id(url),"url":url,"source":"degewo","trusted_wbs":True,
               "title":i.get("title","")[:80],"price":parse_price(i.get("warmmiete") or i.get("totalRent")),
               "rooms":parse_rooms(i.get("zimmer") or i.get("rooms")),
               "location":i.get("district","Berlin"),"wbs_label":"WBS erforderlich",
               "ts":time.time(),**extra}
            l["score"]=_score_listing(l); result.append(l)
        if result: return result
    return []

def _scrape_kleinanzeigen() -> list:
    if not HAS_BS4: return []
    html=_get("https://www.kleinanzeigen.de/s-wohnung-mieten/berlin/wbs/k0c203l3331")
    if not html or len(html)<500: return []
    soup=BeautifulSoup(html,"html.parser"); result=[]; seen=set()
    for card in soup.select("article.aditem")[:25]:
        a=card.select_one("a.ellipsis,h2 a,h3 a")
        if not a: continue
        href=a.get("href","")
        url="https://www.kleinanzeigen.de"+href if href.startswith("/") else href
        if url in seen: continue; seen.add(url)
        t_tag=card.select_one("h2,h3")
        p_tag=card.select_one("[class*='price']")
        title=(t_tag.get_text(strip=True) if t_tag else a.get_text(strip=True))[:80]
        extra=enrich(title,card.get_text(" ",strip=True))
        l={"id":make_id(url),"url":url,"source":"kleinanz","trusted_wbs":False,
           "title":title,"price":parse_price(p_tag.get_text() if p_tag else None),
           "rooms":None,"location":"Berlin","wbs_label":"","ts":time.time(),**extra}
        l["score"]=_score_listing(l); result.append(l)
    return result

_SCRAPERS = {"gewobag":_scrape_gewobag,"degewo":_scrape_degewo,"kleinanz":_scrape_kleinanzeigen}

def fetch_all(enabled: Optional[list]=None, timeout: int=25) -> list:
    active=set(enabled) if enabled else set(SOURCES.keys())
    results=[]; lock=threading.Lock()
    def run(src,fn):
        try:
            items=fn()
            with lock: results.extend(items)
        except Exception: pass
    threads=[]
    for src in active:
        fn=_SCRAPERS.get(src)
        if fn:
            t=threading.Thread(target=run,args=(src,fn),daemon=True)
            threads.append(t); t.start()
    deadline=time.time()+timeout
    for t in threads: t.join(timeout=max(0.1,deadline-time.time()))
    # Dedup by ID
    seen_ids=set(); unique=[]
    for l in results:
        if l.get("id") and l["id"] not in seen_ids:
            seen_ids.add(l["id"]); unique.append(l)
    return unique

def apply_filters(listings: list, cfg: dict) -> list:
    out=[]; max_p=float(cfg.get("max_price") or 9999); min_p=float(cfg.get("min_price") or 0)
    min_r=float(cfg.get("min_rooms") or 0); max_r=float(cfg.get("max_rooms") or 0)
    min_sz=int(cfg.get("min_size") or 0); max_sz=int(cfg.get("max_size") or 0)
    wbs_only=bool(cfg.get("wbs_only")); wlmin=int(cfg.get("wbs_level_min") or 0)
    wlmax=int(cfg.get("wbs_level_max") or 999); jcm=bool(cfg.get("jobcenter_mode"))
    wgm=bool(cfg.get("wohngeld_mode")); n=max(1,int(cfg.get("household_size") or 1))
    areas=[a.lower() for a in (cfg.get("areas") or [])]; srcs=cfg.get("sources") or []
    show_hidden=bool(cfg.get("show_hidden"))
    for l in listings:
        if not l.get("id"): continue
        if not show_hidden and l.get("hidden"): continue
        if srcs and l.get("source") not in srcs: continue
        price=l.get("price"); rooms=l.get("rooms"); size=l.get("size_m2")
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
        level=l.get("wbs_level") or l.get("wbs_level_num")
        if level is not None and (wlmin>0 or wlmax<999):
            if not (wlmin<=level<=wlmax): continue
        if areas:
            loc=(l.get("location","")+" "+l.get("title","")).lower()
            if not any(a in loc for a in areas): continue
        if jcm or wgm:
            j_ok=(price is None or price<=jc(n)) if jcm else False
            w_ok=(price is None or price<=wg(n)) if wgm else False
            if not (j_ok or w_ok): continue
        out.append(l)
    return out

def sort_listings(listings: list, sort_by: str) -> list:
    if sort_by=="price_asc":   return sorted(listings, key=lambda l: l.get("price") or 9999)
    elif sort_by=="price_desc":return sorted(listings, key=lambda l: -(l.get("price") or 0))
    elif sort_by=="newest":    return sorted(listings, key=lambda l: -(l.get("ts_found") or l.get("ts") or 0))
    return sorted(listings, key=lambda l: -(l.get("score") or 0))

# ═══════════════════════════════════════════════════════════════════════
# Notifications
# ═══════════════════════════════════════════════════════════════════════
_CH = "wbs4_ch"

def _ensure_channel():
    if not HAS_ANDROID: return
    try:
        ctx=PythonActivity.mActivity; mgr=ctx.getSystemService(CTX.NOTIFICATION_SERVICE)
        ch=NC(_CH,"WBS Berlin",NM.IMPORTANCE_HIGH)
        ch.setDescription(ar("إشعارات شقق WBS")); mgr.createNotificationChannel(ch)
    except Exception: pass

def send_notif(title: str, body: str, url: str="", notif_id: int=1001) -> None:
    if not HAS_ANDROID: return
    try:
        ctx=PythonActivity.mActivity; mgr=ctx.getSystemService(CTX.NOTIFICATION_SERVICE)
        if url:
            intent=Intent(Intent.ACTION_VIEW,Uri.parse(url))
        else:
            intent=Intent(ctx,PythonActivity)
            intent.setFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP)
        pi=PI.getActivity(ctx,notif_id,intent,PI.FLAG_UPDATE_CURRENT|0x4000000)
        nb=NB(ctx,_CH)
        nb.setSmallIcon(17301543)
        nb.setContentTitle(ar(title)); nb.setContentText(ar(body))
        nb.setContentIntent(pi); nb.setAutoCancel(True); nb.setPriority(1)
        mgr.notify(notif_id,nb.build())
    except Exception: pass

def notify_new(listings: list) -> None:
    if not listings: return
    cfg=load_cfg()
    if not cfg.get("notifications",True): return
    if len(listings)==1:
        l=listings[0]; name=SOURCES.get(l.get("source",""),("","",))[0]
        price=f"{l['price']:.0f}€" if l.get("price") else ""
        send_notif(f"🏠 شقة جديدة — {name}",
                   f"{price} · {l.get('location','Berlin')} · {l.get('title','')[:45]}",
                   l.get("url",""))
    else:
        names=list({SOURCES.get(l.get("source",""),("?",))[0] for l in listings[:3]})
        send_notif(f"🏠 {len(listings)} شقق جديدة في برلين","، ".join(names))
    with _db_lock:
        con=_db()
        try:
            con.execute("UPDATE stats SET total_notif=total_notif+? WHERE id=1",(len(listings),))
            ids=[l["id"] for l in listings if l.get("id")]
            if ids:
                ph=",".join("?"*len(ids))
                con.execute(f"UPDATE listings SET notified=1 WHERE id IN ({ph})",ids)
            con.commit()
        finally: con.close()

# ═══════════════════════════════════════════════════════════════════════
# Background Service
# ═══════════════════════════════════════════════════════════════════════
_bg_stop  = threading.Event()
_bg_thread: Optional[threading.Thread] = None

def _bg_worker():
    _ensure_channel(); time.sleep(5)
    while not _bg_stop.is_set():
        try:
            cfg=load_cfg()
            interval=max(5,int(cfg.get("bg_interval",30)))*60
            # Update stats
            with _db_lock:
                con=_db()
                try: con.execute("UPDATE stats SET last_check=? WHERE id=1",(time.time(),)); con.commit()
                finally: con.close()
            try: SVC_BEAT.write_text(str(int(time.time())))
            except Exception: pass
            if check_network():
                raw=fetch_all(cfg.get("sources") or None, timeout=30)
                new_ones=[]
                for l in raw:
                    if save_listing(l): new_ones.append(l)
                shown=apply_filters(new_ones, cfg)
                if shown: notify_new(shown)
            purge_old(int(cfg.get("purge_days",60)))
        except Exception: pass
        _bg_stop.wait(timeout=interval)

def start_bg():
    global _bg_thread,_bg_stop
    if _bg_thread and _bg_thread.is_alive(): return
    _bg_stop.clear()
    _bg_thread=threading.Thread(target=_bg_worker,daemon=True,name="WBSBg")
    _bg_thread.start()

def stop_bg(): _bg_stop.set()

def is_bg() -> bool:
    if not (_bg_thread and _bg_thread.is_alive()): return False
    try: return time.time()-int(SVC_BEAT.read_text())<600
    except Exception: return _bg_thread.is_alive()

# ═══════════════════════════════════════════════════════════════════════
# UI Helpers
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    def bg(w, color, radius=0):
        w.canvas.before.clear()
        with w.canvas.before:
            Color(*color)
            r=(RoundedRectangle(pos=w.pos,size=w.size,radius=[dp(radius)])
               if radius else Rectangle(pos=w.pos,size=w.size))
        def _u(*_): r.pos=w.pos; r.size=w.size
        w.bind(pos=_u,size=_u)

    def lbl(text,size=14,color=None,bold=False,halign="right",**kw):
        color=color or TEXT1
        w=Label(text=ar(str(text)),font_size=fs(size),color=color,bold=bold,halign=halign,**kw)
        w.bind(width=lambda *_:setattr(w,"text_size",(w.width,None)))
        return w

    def btn(text,on_press=None,color=None,text_color=None,height=48,radius=12,**kw):
        color=color or PRIMARY()
        text_color=text_color or WHITE
        b=Button(text=ar(str(text)),size_hint_y=None,height=dp(height),
                 background_color=TRANSP,color=text_color,font_size=fs(14),bold=True,**kw)
        bg(b,color,radius=radius)
        if on_press: b.bind(on_press=on_press)
        return b

    def gap(h=12): return Widget(size_hint_y=None,height=dp(h))
    def div():
        w=Widget(size_hint_y=None,height=dp(1)); bg(w,DIVIDER); return w
    def sec(text):
        b=BoxLayout(size_hint_y=None,height=dp(30))
        b.add_widget(lbl(text,size=11,color=TEXT3,bold=True)); return b
    def tf(val,filt="int"):
        t=TextInput(text=str(val),input_filter=filt,multiline=False,
                    background_color=TRANSP,foreground_color=TEXT1,
                    cursor_color=PRIMARY(),font_size=fs(14))
        bg(t,BG3,radius=10); return t
    def si(t,d=0):
        try: return int(float(t.text or d))
        except Exception: return d
    def sf(t,d=0.0):
        try: return float(t.text or d)
        except Exception: return d

    def nav_bar(app_ref, active="listings"):
        TABS = [
            ("🏠","listings","الرئيسية"),
            ("⭐","favorites","المفضلة"),
            ("📊","stats_scr","الإحصائيات"),
            ("⚙️","settings","الإعدادات"),
        ]
        bar=BoxLayout(size_hint_y=None,height=dp(58),spacing=0)
        bg(bar,BG2)
        for icon,name,label in TABS:
            is_act=name==active
            b=Button(text=f"{icon}\n{ar(label)}",
                     background_color=TRANSP,
                     color=PRIMARY() if is_act else TEXT3,
                     font_size=fs(10 if not is_act else 11),
                     bold=is_act)
            if is_act: bg(b,(*PRIMARY()[:3],0.1))
            else: bg(b,BG2)
            n=name
            b.bind(on_press=lambda _,n=n: setattr(app_ref.sm,"current",n))
            bar.add_widget(b)
        return bar

# ═══════════════════════════════════════════════════════════════════════
# Onboarding
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    PAGES=[
        ("🏠","مرحباً في WBS برلين","ابحث عن شقتك المدعومة\nمن 9 مصادر رسمية وخاصة",PRIMARY()),
        ("🗄","قاعدة بيانات ذكية","لا تكرار للإعلانات أبداً\nيتذكر ما شاهدته وما فاتك",PURPLE),
        ("🔔","إشعارات فورية","يعمل في الخلفية دائماً\nويرسل إشعاراً فور ظهور شقة مناسبة",AMBER),
    ]
    class OnboardingScreen(Screen):
        def __init__(self,app_ref,**kw):
            super().__init__(name="onboarding",**kw); self.app_ref=app_ref; self._i=0; self._show()
        def _show(self):
            self.clear_widgets(); bg(self,BG); p=PAGES[self._i]; last=self._i==len(PAGES)-1
            root=FloatLayout()
            card=BoxLayout(orientation="vertical",padding=dp(32),spacing=dp(16),
                           size_hint=(0.88,0.68),pos_hint={"center_x":.5,"center_y":.57})
            bg(card,BG2,radius=24)
            card.add_widget(Label(text=p[0],font_size=fs(68),size_hint_y=None,height=dp(80)))
            card.add_widget(lbl(p[1],size=21,bold=True,color=p[3],size_hint_y=None,height=dp(50)))
            card.add_widget(lbl(p[2],size=14,color=TEXT2,size_hint_y=None,height=dp(70)))
            root.add_widget(card)
            dots=BoxLayout(size_hint=(None,None),size=(dp(80),dp(12)),
                           pos_hint={"center_x":.5,"y":.18},spacing=dp(8))
            for i in range(len(PAGES)):
                d=Widget(size_hint=(None,None),size=(dp(20 if i==self._i else 8),dp(8)))
                bg(d,p[3] if i==self._i else TEXT3,radius=4); dots.add_widget(d)
            root.add_widget(dots)
            brow=BoxLayout(size_hint=(0.88,None),height=dp(50),
                           pos_hint={"center_x":.5,"y":.05},spacing=dp(12))
            if not last: brow.add_widget(btn("تخطي",on_press=self._done,color=BG3,text_color=TEXT2))
            brow.add_widget(btn("ابدأ 🚀" if last else "التالي ←",
                                on_press=self._next if not last else self._done,color=p[3]))
            root.add_widget(brow); self.add_widget(root)
        def _next(self,*_): self._i=min(self._i+1,len(PAGES)-1); self._show()
        def _done(self,*_): mark_done(); self.app_ref.go_main()

# ═══════════════════════════════════════════════════════════════════════
# Listing Card
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class ListingCard(BoxLayout):
        def __init__(self, l: dict, show_fav_btn=True, **kw):
            super().__init__(orientation="vertical",size_hint_y=None,
                             padding=(dp(14),dp(12)),spacing=dp(6),**kw)
            name,gov=SOURCES.get(l.get("source",""),("?",False))
            src_c=PURPLE if gov else BLUE; is_fav=bool(l.get("favorited"))
            price=l.get("price"); rooms=l.get("rooms"); sz=l.get("size_m2")
            floor_=l.get("floor_") or l.get("floor",""); avail=l.get("available","")
            dep=l.get("deposit",""); heat=l.get("heating","")
            feats_raw=l.get("features")
            if isinstance(feats_raw,str):
                try: feats=json.loads(feats_raw)
                except Exception: feats=[]
            else: feats=feats_raw or []
            feats=feats[:6]; title=(l.get("title") or "شقة").strip()[:65]
            loc=l.get("location","Berlin"); wlnum=l.get("wbs_level") or l.get("wbs_level_num")
            wlbl=f"WBS {wlnum}" if wlnum else ("WBS ✓" if l.get("trusted_wbs") else "")
            score_=l.get("score",0); self.url=l.get("url",""); self.lid=l.get("id","")
            n_fr=max(1,(len(feats)+2)//3) if feats else 0
            self.height=dp(175+n_fr*24+(20 if dep or heat else 0))
            bg(self,BG2,radius=16)

            # ── Header ────────────────────────────────────────────────
            r1=BoxLayout(size_hint_y=None,height=dp(28),spacing=dp(6))
            chip=BoxLayout(size_hint=(None,None),size=(dp(120),dp(24)),padding=(dp(8),0))
            bg(chip,(*src_c[:3],0.18),radius=12)
            chip.add_widget(lbl(("🏛 " if gov else "🔍 ")+ar(name),size=11,color=src_c,
                                 size_hint_y=None,height=dp(24)))
            r1.add_widget(chip)
            if score_>=15:
                stars="⭐⭐" if score_>=20 else "⭐"
                sc_chip=BoxLayout(size_hint=(None,None),size=(dp(44),dp(24)),padding=(dp(4),0))
                bg(sc_chip,(*GOLD[:3],0.18),radius=12)
                sc_chip.add_widget(lbl(stars,size=11,color=GOLD,size_hint_y=None,height=dp(24)))
                r1.add_widget(sc_chip)
            r1.add_widget(Widget())
            if wlbl:
                wb=BoxLayout(size_hint=(None,None),size=(dp(78),dp(24)),padding=(dp(8),0))
                bg(wb,(*PRIMARY()[:3],0.18),radius=12)
                wb.add_widget(lbl(wlbl,size=11,color=tuple(PRIMARY()),bold=True,size_hint_y=None,height=dp(24)))
                r1.add_widget(wb)
            if show_fav_btn:
                self._fav_btn=Button(text="★" if is_fav else "☆",
                    size_hint=(None,None),size=(dp(30),dp(28)),
                    background_color=TRANSP,color=GOLD if is_fav else TEXT3,
                    font_size=fs(18))
                self._fav_btn.bind(on_press=self._toggle_fav)
                r1.add_widget(self._fav_btn)
            self.add_widget(r1)

            # ── Title ─────────────────────────────────────────────────
            self.add_widget(lbl(title,size=13,bold=True,size_hint_y=None,height=dp(22)))

            # ── Location ──────────────────────────────────────────────
            r3=BoxLayout(size_hint_y=None,height=dp(18))
            r3.add_widget(lbl("📍 "+ar(loc),size=11,color=TEXT2))
            if avail:
                r3.add_widget(lbl("📅 "+ar("فوري 🔥" if avail=="فوري" else avail),
                                   size=11,color=AMBER if avail=="فوري" else TEXT2))
            self.add_widget(r3); self.add_widget(div())

            # ── Price row ─────────────────────────────────────────────
            r4=BoxLayout(size_hint_y=None,height=dp(34),spacing=dp(6))
            if price:
                ppm=f" ({price/sz:.1f}€/m²)" if sz else ""
                pill=BoxLayout(size_hint=(None,None),size=(dp(120),dp(30)),padding=(dp(8),0))
                bg(pill,(*PRIMARY()[:3],0.15),radius=10)
                pill.add_widget(lbl(f"💰 {price:.0f}€{ppm}",size=13,color=tuple(PRIMARY()),
                                     bold=True,size_hint_y=None,height=dp(30)))
                r4.add_widget(pill)
            if rooms: r4.add_widget(lbl(f"🛏 {rooms:.0f}",size=12,color=TEXT1))
            if sz:    r4.add_widget(lbl(f"📐 {sz:.0f}m²",size=12,color=TEXT1))
            if floor_:r4.add_widget(lbl(ar(floor_),size=11,color=TEXT2))
            self.add_widget(r4)

            if dep or heat:
                rx=BoxLayout(size_hint_y=None,height=dp(18))
                if dep: rx.add_widget(lbl("💼 "+ar(dep),size=11,color=TEXT2))
                if heat: rx.add_widget(lbl(ar(heat),size=11,color=TEXT2))
                self.add_widget(rx)

            if feats:
                fg=GridLayout(cols=3,size_hint_y=None,height=dp(n_fr*24),spacing=dp(4))
                for f in feats:
                    c=BoxLayout(size_hint_y=None,height=dp(22),padding=(dp(6),0))
                    bg(c,BG3,radius=8)
                    c.add_widget(lbl(ar(f),size=10,color=TEXT2,size_hint_y=None,height=dp(22)))
                    fg.add_widget(c)
                self.add_widget(fg)

            # ── Action buttons ────────────────────────────────────────
            ab=BoxLayout(size_hint_y=None,height=dp(34),spacing=dp(8))
            ob=btn("فتح ←",on_press=self._open,height=34,radius=10)
            ab.add_widget(ob)
            hb=btn("إخفاء",on_press=self._hide,color=BG3,text_color=TEXT2,height=34,radius=10,
                   size_hint_x=None,width=dp(80))
            ab.add_widget(hb)
            self.add_widget(ab)

        def _toggle_fav(self,*_):
            if not self.lid: return
            new=toggle_favorite(self.lid)
            self._fav_btn.color=GOLD if new else TEXT3
            self._fav_btn.text="★" if new else "☆"

        def _hide(self,*_):
            if self.lid: hide_listing(self.lid)
            self.opacity=0; self.height=0

        def _open(self,*_):
            if not self.url: return
            mark_seen([self.lid])
            try:
                PythonActivity.mActivity.startActivity(
                    Intent(Intent.ACTION_VIEW,Uri.parse(self.url)))
            except Exception:
                try:
                    from kivy.core.clipboard import Clipboard
                    Clipboard.copy(self.url)
                except Exception: pass

# ═══════════════════════════════════════════════════════════════════════
# Listings Screen
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class ListingsScreen(Screen):
        def __init__(self,app_ref,**kw):
            super().__init__(name="listings",**kw)
            self.app_ref=app_ref; self._lock=threading.RLock()
            self._busy=False; self._raw=[]; bg(self,BG); self._build()

        def _build(self):
            self.clear_widgets(); cfg=load_cfg(); root=BoxLayout(orientation="vertical")
            bar=BoxLayout(size_hint_y=None,height=dp(58),padding=(dp(14),dp(8)),spacing=dp(8))
            bg(bar,BG2)
            bar.add_widget(lbl("🏠 WBS برلين",size=17,bold=True,color=WHITE,size_hint_x=0.4))
            bar.add_widget(Widget())
            sort_icons={"score":"🏅","price_asc":"💰↑","price_desc":"💰↓","newest":"🕐"}
            self._sort_btn=btn(sort_icons.get(cfg.get("sort_by","score"),"🏅"),
                               on_press=self._cycle_sort,color=BG3,text_color=TEXT2,
                               size_hint_x=None,width=dp(46),height=42)
            bar.add_widget(self._sort_btn)
            bar.add_widget(btn("⚙️",on_press=lambda*_:setattr(self.app_ref.sm,"current","settings"),
                               color=BG3,text_color=TEXT2,size_hint_x=None,width=dp(44),height=42))
            self._rf_btn=btn("🔄",on_press=self._refresh,color=tuple(PRIMARY()),
                              size_hint_x=None,width=dp(44),height=42)
            bar.add_widget(self._rf_btn); root.add_widget(bar)
            chips=BoxLayout(size_hint_y=None,height=dp(44),padding=(dp(10),dp(6)),spacing=dp(8))
            bg(chips,BG2)
            self._wbs_chip=ToggleButton(text=ar("✅ WBS فقط"),
                state="down" if cfg.get("wbs_only") else "normal",
                size_hint=(None,None),size=(dp(100),dp(30)),
                background_color=TRANSP,color=TEXT1,font_size=fs(12))
            self._uc()
            self._wbs_chip.bind(state=self._on_wbs); chips.add_widget(self._wbs_chip)
            self._status=lbl("اضغط 🔄 للبحث",size=12,color=TEXT2,size_hint_y=None,height=dp(30))
            chips.add_widget(self._status)
            self._bg_ind=lbl("⏸",size=14,color=TEXT3,size_hint=(None,None),size=(dp(28),dp(30)))
            chips.add_widget(self._bg_ind); root.add_widget(chips); root.add_widget(div())
            self._cards=BoxLayout(orientation="vertical",spacing=dp(10),
                                   padding=(dp(10),dp(10)),size_hint_y=None)
            self._cards.bind(minimum_height=self._cards.setter("height"))
            sv=ScrollView(bar_color=(*PRIMARY()[:3],0.4),bar_inactive_color=(*TEXT3[:3],0.2))
            sv.add_widget(self._cards); root.add_widget(sv)
            root.add_widget(nav_bar(self.app_ref,"listings")); self.add_widget(root)
            self._ph("🔍",ar("اضغط 🔄 للبحث"))
            Clock.schedule_interval(self._tick,10)

        def _uc(self):
            on=self._wbs_chip.state=="down"
            bg(self._wbs_chip,(*PRIMARY()[:3],0.85) if on else BG3,radius=15)

        def _tick(self,*_):
            on=is_bg(); self._bg_ind.text="🟢" if on else "⏸"
            self._bg_ind.color=tuple(PRIMARY()) if on else TEXT3

        def _on_wbs(self,_,state):
            self._uc(); cfg=load_cfg(); cfg["wbs_only"]=state=="down"; save_cfg(cfg)
            with self._lock: raw=list(self._raw)
            if raw:
                shown=sort_listings(apply_filters(raw,cfg),cfg.get("sort_by","score"))
                Clock.schedule_once(lambda dt:self._render(shown,len(raw)))

        def _cycle_sort(self,*_):
            order=["score","price_asc","price_desc","newest"]
            icons={"score":"🏅","price_asc":"💰↑","price_desc":"💰↓","newest":"🕐"}
            cfg=load_cfg(); cur=cfg.get("sort_by","score")
            nxt=order[(order.index(cur)+1)%len(order)]
            cfg["sort_by"]=nxt; save_cfg(cfg); self._sort_btn.text=icons[nxt]
            with self._lock: raw=list(self._raw)
            if raw:
                shown=sort_listings(apply_filters(raw,cfg),nxt)
                Clock.schedule_once(lambda dt:self._render(shown,len(raw)))

        def _ph(self,icon,msg):
            self._cards.clear_widgets()
            b=BoxLayout(orientation="vertical",spacing=dp(10),size_hint_y=None,height=dp(200),padding=dp(40))
            b.add_widget(Label(text=icon,font_size=fs(52),size_hint_y=None,height=dp(65)))
            b.add_widget(lbl(msg,size=14,color=TEXT2,size_hint_y=None,height=dp(50)))
            self._cards.add_widget(b)

        def _refresh(self,*_):
            with self._lock:
                if self._busy: return
                self._busy=True
            if not check_network():
                # Try DB cache
                with _db_lock:
                    con=_db()
                    try:
                        rows=con.execute(
                            "SELECT * FROM listings WHERE seen=0 AND hidden=0 "
                            "ORDER BY ts_found DESC LIMIT 200").fetchall()
                        cached=[dict(r) for r in rows]
                    finally: con.close()
                with self._lock: self._busy=False
                if cached:
                    self._status.text=ar("📦 من قاعدة البيانات")
                    with self._lock: self._raw=cached
                    cfg=load_cfg()
                    shown=sort_listings(apply_filters(cached,cfg),cfg.get("sort_by","score"))
                    Clock.schedule_once(lambda dt:self._render(shown,len(cached)))
                else: self._ph("📵",ar("لا يوجد اتصال ولا بيانات"))
                return
            self._status.text=ar("⏳ جاري البحث..."); self._ph("⏳",ar("جاري الجلب..."))
            threading.Thread(target=self._bg_fetch,daemon=True).start()

        def _bg_fetch(self):
            try:
                cfg=load_cfg(); raw=fetch_all(cfg.get("sources") or None)
                new_count=0
                for l in raw:
                    if save_listing(l): new_count+=1
                with _db_lock:
                    con=_db()
                    try:
                        rows=con.execute(
                            "SELECT * FROM listings WHERE hidden=0 ORDER BY ts_found DESC LIMIT 300"
                        ).fetchall()
                        all_db=[dict(r) for r in rows]
                    finally: con.close()
                with self._lock: self._raw=all_db
                shown=sort_listings(apply_filters(all_db,cfg),cfg.get("sort_by","score"))
                Clock.schedule_once(lambda dt:self._render(shown,len(all_db),new_count))
            except Exception:
                Clock.schedule_once(lambda dt:self._ph("⚠️",ar("خطأ — حاول مرة أخرى")))
            finally:
                with self._lock: self._busy=False

        def _render(self,lst,total=None,new_count=0):
            try:
                self._cards.clear_widgets()
                t=total if total is not None else len(lst)
                new_str=f" (+{new_count} جديد)" if new_count else ""
                if not lst:
                    self._status.text=ar(f"لا إعلانات ({t} في القاعدة)")
                    self._ph("🔍",ar("لا توجد إعلانات تناسب إعداداتك")); return
                self._status.text=ar(f"✅ {len(lst)} إعلان{new_str}")
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

# ═══════════════════════════════════════════════════════════════════════
# Favorites Screen
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class FavoritesScreen(Screen):
        def __init__(self,app_ref,**kw):
            super().__init__(name="favorites",**kw); self.app_ref=app_ref
            bg(self,BG); self._build()

        def _build(self):
            self.clear_widgets(); root=BoxLayout(orientation="vertical")
            bar=BoxLayout(size_hint_y=None,height=dp(58),padding=(dp(14),dp(8)))
            bg(bar,BG2); bar.add_widget(lbl("⭐ المفضلة",size=17,bold=True,color=GOLD))
            bar.add_widget(btn("🔄",on_press=self._load,color=BG3,text_color=TEXT2,
                               size_hint_x=None,width=dp(44),height=42))
            root.add_widget(bar)
            self._cards=BoxLayout(orientation="vertical",spacing=dp(10),
                                   padding=(dp(10),dp(10)),size_hint_y=None)
            self._cards.bind(minimum_height=self._cards.setter("height"))
            sv=ScrollView(bar_color=(*GOLD[:3],0.4)); sv.add_widget(self._cards); root.add_widget(sv)
            root.add_widget(nav_bar(self.app_ref,"favorites")); self.add_widget(root)
            self._load()

        def on_enter(self,*_): self._load()

        def _load(self,*_):
            self._cards.clear_widgets()
            favs=get_favorites()
            if not favs:
                b=BoxLayout(orientation="vertical",size_hint_y=None,height=dp(180),padding=dp(40))
                b.add_widget(Label(text="⭐",font_size=fs(52),size_hint_y=None,height=dp(65)))
                b.add_widget(lbl("لا توجد مفضلة بعد\nاضغط ★ على أي إعلان",size=14,
                                   color=TEXT2,size_hint_y=None,height=dp(60)))
                self._cards.add_widget(b); return
            for l in favs:
                self._cards.add_widget(ListingCard(l)); self._cards.add_widget(gap(6))

# ═══════════════════════════════════════════════════════════════════════
# Stats Screen
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class StatsScreen(Screen):
        def __init__(self,app_ref,**kw):
            super().__init__(name="stats_scr",**kw); self.app_ref=app_ref
            bg(self,BG); self._build()

        def on_enter(self,*_): self._build()

        def _build(self):
            self.clear_widgets(); root=BoxLayout(orientation="vertical")
            bar=BoxLayout(size_hint_y=None,height=dp(58),padding=(dp(14),dp(8)))
            bg(bar,BG2); bar.add_widget(lbl("📊 الإحصائيات",size=17,bold=True,color=WHITE))
            root.add_widget(bar)
            scroll=ScrollView(); body=BoxLayout(orientation="vertical",
                padding=dp(16),spacing=dp(10),size_hint_y=None)
            body.bind(minimum_height=body.setter("height"))
            st=get_stats_db()

            def stat_card(icon,label,value,color=None):
                card=BoxLayout(size_hint_y=None,height=dp(68),padding=(dp(16),dp(8)),spacing=dp(12))
                bg(card,BG2,radius=14)
                card.add_widget(Label(text=icon,font_size=fs(28),size_hint=(None,None),size=(dp(50),dp(50))))
                txt=BoxLayout(orientation="vertical")
                txt.add_widget(lbl(ar(label),size=12,color=TEXT2))
                txt.add_widget(lbl(str(value),size=20,bold=True,color=color or tuple(PRIMARY())))
                card.add_widget(txt); return card

            def ts_str(ts):
                if not ts: return "—"
                try: return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                except Exception: return "—"

            body.add_widget(stat_card("🏠","إجمالي الإعلانات المحفوظة",st.get("db_total",0)))
            body.add_widget(stat_card("🆕","إعلانات جديدة تم إيجادها",st.get("total_new",0),GREEN))
            body.add_widget(stat_card("🔔","إشعارات مُرسلة",st.get("total_notif",0),AMBER))
            body.add_widget(stat_card("📱","مرات فتح التطبيق",st.get("app_opens",0),PURPLE))
            body.add_widget(stat_card("🕐","آخر فحص",ts_str(st.get("last_check")),TEXT2))
            body.add_widget(stat_card("✨","آخر إعلان جديد",ts_str(st.get("last_new")),GREEN))

            body.add_widget(gap(4)); body.add_widget(sec("📊  حسب المصدر"))
            by_src=st.get("by_source",{})
            for src,(name,gov) in SOURCES.items():
                cnt=by_src.get(src,0)
                if cnt>0:
                    row=BoxLayout(size_hint_y=None,height=dp(42),padding=(dp(14),dp(4),dp(14),dp(4)))
                    bg(row,BG2,radius=10)
                    c=PURPLE if gov else BLUE
                    row.add_widget(lbl(("🏛 " if gov else "🔍 ")+ar(name),size=13,color=c,size_hint_x=0.65))
                    row.add_widget(lbl(str(cnt),size=16,bold=True,color=tuple(PRIMARY()),
                                       size_hint_x=0.35,halign="left"))
                    body.add_widget(row)

            body.add_widget(gap(8))
            body.add_widget(btn("🗑 إفراغ قاعدة البيانات",on_press=self._clear,
                                 color=RED,height=46,radius=12))
            body.add_widget(gap(20))
            scroll.add_widget(body); root.add_widget(scroll)
            root.add_widget(nav_bar(self.app_ref,"stats_scr")); self.add_widget(root)

        def _clear(self,*_):
            with _db_lock:
                con=_db()
                try:
                    con.execute("DELETE FROM listings WHERE favorited=0")
                    con.execute("UPDATE stats SET total_found=0,total_new=0,total_notif=0 WHERE id=1")
                    con.commit()
                finally: con.close()
            self._build()

# ═══════════════════════════════════════════════════════════════════════
# Settings Screen
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class SettingsScreen(Screen):
        def __init__(self,app_ref,**kw):
            super().__init__(name="settings",**kw); self.app_ref=app_ref
            bg(self,BG); self._build()

        def _build(self):
            self.clear_widgets(); cfg=load_cfg(); root=BoxLayout(orientation="vertical")
            hdr=BoxLayout(size_hint_y=None,height=dp(58),padding=(dp(12),dp(8)),spacing=dp(10))
            bg(hdr,BG2)
            hdr.add_widget(lbl("⚙️ الإعدادات",size=16,bold=True,color=WHITE))
            hdr.add_widget(btn("↩️",on_press=self._reset,color=BG3,text_color=TEXT2,
                               size_hint_x=None,width=dp(50),height=42))
            root.add_widget(hdr)

            scroll=ScrollView(); body=BoxLayout(orientation="vertical",
                padding=dp(14),spacing=dp(8),size_hint_y=None)
            body.bind(minimum_height=body.setter("height"))

            def row(label_t, widget, hint=""):
                r=BoxLayout(size_hint_y=None,height=dp(56),spacing=dp(12),padding=(dp(12),dp(4)))
                bg(r,BG2,radius=12)
                lb=BoxLayout(orientation="vertical",size_hint_x=0.45)
                lb.add_widget(lbl(label_t,size=13,color=TEXT1))
                if hint: lb.add_widget(lbl(hint,size=10,color=TEXT3))
                r.add_widget(lb); r.add_widget(widget); body.add_widget(r)

            def tog(text,active,pri=None):
                pri=pri or PRIMARY()
                t=ToggleButton(text=ar(text),state="down" if active else "normal",
                    size_hint=(1,None),height=dp(46),background_color=TRANSP,
                    color=TEXT1,font_size=fs(13))
                bg(t,(*pri[:3],0.15) if active else BG2,radius=12)
                t.bind(state=lambda b,s,p=pri:bg(b,(*p[:3],0.15) if s=="down" else BG2,radius=12))
                body.add_widget(t); return t

            # ── Appearance ────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec("🎨  المظهر"))

            # Accent color
            acc_row=BoxLayout(size_hint_y=None,height=dp(50),padding=(dp(12),dp(4)),spacing=dp(8))
            bg(acc_row,BG2,radius=12)
            acc_row.add_widget(lbl("لون التمييز:",size=13,color=TEXT1,size_hint_x=0.35))
            self._accent_btns={}
            cur_accent=cfg.get("accent","#22C55E")
            for name,hex_ in ACCENT_PRESETS.items():
                c=get_color_from_hex(hex_)
                b=Button(text="●" if hex_==cur_accent else "○",
                         size_hint=(None,None),size=(dp(32),dp(32)),
                         background_color=TRANSP,color=c,font_size=fs(18))
                b.bind(on_press=lambda _,h=hex_,n=name:self._set_accent(h))
                self._accent_btns[hex_]=b; acc_row.add_widget(b)
            body.add_widget(acc_row)

            # Font scale
            fs_row=BoxLayout(size_hint_y=None,height=dp(56),padding=(dp(12),dp(4)),spacing=dp(8))
            bg(fs_row,BG2,radius=12)
            fs_row.add_widget(lbl("حجم الخط:",size=13,color=TEXT1,size_hint_x=0.3))
            self._fs_slider=Slider(min=0.8,max=1.4,value=cfg.get("font_scale",1.0),step=0.1)
            self._fs_lbl=lbl(f"{cfg.get('font_scale',1.0):.1f}",size=13,color=tuple(PRIMARY()),
                              size_hint_x=None,width=dp(35))
            self._fs_slider.bind(value=lambda _,v:(
                setattr(self._fs_lbl,"text",f"{v:.1f}"),
                set_font_scale(v)))
            fs_row.add_widget(self._fs_slider); fs_row.add_widget(self._fs_lbl)
            body.add_widget(fs_row)

            # ── Budget ───────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec("💰  الميزانية"))
            self._min_p=tf(cfg.get("min_price",0)); row("الحد الأدنى (€)",self._min_p,"0=بدون حد")
            self._max_p=tf(cfg.get("max_price",700)); row("أقصى إيجار (€)",self._max_p)

            # ── Rooms + Size ─────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec("🛏  الغرف والمساحة"))
            rrow=BoxLayout(size_hint_y=None,height=dp(56),spacing=dp(6),padding=(dp(12),dp(4)))
            bg(rrow,BG2,radius=12)
            rrow.add_widget(lbl("الغرف:",size=13,color=TEXT1,size_hint_x=0.2))
            self._min_r=tf(cfg.get("min_rooms",0),"float"); self._max_r=tf(cfg.get("max_rooms",0),"float")
            rrow.add_widget(lbl("من",size=11,color=TEXT2,size_hint_x=0.07))
            rrow.add_widget(self._min_r); rrow.add_widget(lbl("—",size=13,color=TEXT2,size_hint_x=0.06))
            rrow.add_widget(self._max_r); rrow.add_widget(lbl("0=أي",size=10,color=TEXT3,size_hint_x=0.13))
            body.add_widget(rrow)
            szr=BoxLayout(size_hint_y=None,height=dp(56),spacing=dp(6),padding=(dp(12),dp(4)))
            bg(szr,BG2,radius=12)
            szr.add_widget(lbl("المساحة (م²):",size=13,color=TEXT1,size_hint_x=0.32))
            self._min_sz=tf(cfg.get("min_size",0)); self._max_sz=tf(cfg.get("max_size",0))
            szr.add_widget(lbl("من",size=11,color=TEXT2,size_hint_x=0.07))
            szr.add_widget(self._min_sz); szr.add_widget(lbl("—",size=13,color=TEXT2,size_hint_x=0.06))
            szr.add_widget(self._max_sz)
            body.add_widget(szr)

            # ── WBS ─────────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec("📋  WBS"))
            self._wbs=tog("WBS فقط",cfg.get("wbs_only",False))
            wlr=BoxLayout(size_hint_y=None,height=dp(56),spacing=dp(6),padding=(dp(12),dp(4)))
            bg(wlr,BG2,radius=12)
            wlr.add_widget(lbl("مستوى:",size=13,color=TEXT1,size_hint_x=0.28))
            self._wlmin=tf(cfg.get("wbs_level_min",0)); self._wlmax=tf(cfg.get("wbs_level_max",999))
            wlr.add_widget(lbl("من",size=11,color=TEXT2,size_hint_x=0.07))
            wlr.add_widget(self._wlmin); wlr.add_widget(lbl("—",size=13,color=TEXT2,size_hint_x=0.06))
            wlr.add_widget(self._wlmax)
            body.add_widget(wlr)
            pr=BoxLayout(size_hint_y=None,height=dp(36),spacing=dp(6))
            for lt,mn,mx in [("100","100","100"),("100-140","100","140"),("100-160","100","160"),("كل","0","999")]:
                b=btn(lt,color=BG3,text_color=TEXT1,height=36,radius=10,size_hint_x=None,width=dp(76))
                b.bind(on_press=lambda _,mn=mn,mx=mx:(setattr(self._wlmin,"text",mn),setattr(self._wlmax,"text",mx)))
                pr.add_widget(b)
            body.add_widget(pr)

            # ── Social ───────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec("🏛  فلاتر اجتماعية"))
            self._hh=tf(cfg.get("household_size",1))
            n_=max(1,int(cfg.get("household_size") or 1))
            row("أفراد الأسرة",self._hh,f"JC≤{jc(n_):.0f}€ · WG≤{wg(n_):.0f}€")
            self._jc=tog("🏛 Jobcenter KdU",cfg.get("jobcenter_mode",False),PURPLE)
            self._wg=tog("🏦 Wohngeld",cfg.get("wohngeld_mode",False),PURPLE)

            # ── Areas ────────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec("📍  المناطق"))
            cur_areas=cfg.get("areas") or []; self._area_btns={}
            ag=GridLayout(cols=2,size_hint_y=None,height=dp(((len(BERLIN_AREAS)+1)//2)*40),spacing=dp(6))
            for area in BERLIN_AREAS:
                on=area in cur_areas
                b=ToggleButton(text=area,state="down" if on else "normal",
                    size_hint=(1,None),height=dp(38),background_color=TRANSP,color=TEXT1,font_size=fs(12))
                bg(b,(*AMBER[:3],0.15) if on else BG2,radius=10)
                b.bind(state=lambda x,s,b=b:bg(b,(*AMBER[:3],0.15) if s=="down" else BG2,radius=10))
                self._area_btns[area]=b; ag.add_widget(b)
            body.add_widget(ag)
            body.add_widget(btn("🌍 كل برلين",on_press=self._clear_areas,color=BG3,text_color=TEXT2,height=36,radius=10))

            # ── Sources ──────────────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec("🌐  المصادر"))
            cur_src=cfg.get("sources") or []; self._src_btns={}
            for sid,(sname,gov) in SOURCES.items():
                sc=PURPLE if gov else BLUE; on=not cur_src or sid in cur_src
                b=ToggleButton(text=("🏛 " if gov else "🔍 ")+ar(sname),
                    state="down" if on else "normal",size_hint=(1,None),height=dp(44),
                    background_color=TRANSP,color=TEXT1,font_size=fs(13))
                bg(b,(*sc[:3],0.15) if on else BG2,radius=12)
                b.bind(state=lambda x,s,sc=sc,b=b:bg(b,(*sc[:3],0.15) if s=="down" else BG2,radius=12))
                self._src_btns[sid]=b; body.add_widget(b)
            qr=BoxLayout(size_hint_y=None,height=dp(38),spacing=dp(8))
            qr.add_widget(btn("✅ الكل",on_press=lambda*_:self._all_src(True),color=BG3,text_color=TEXT1,height=38,radius=10))
            qr.add_widget(btn("🏛 حكومية فقط",on_press=self._gov_only,color=(*PURPLE[:3],1),height=38,radius=10))
            body.add_widget(qr)

            # ── Sort + Advanced ───────────────────────────────────────
            body.add_widget(gap(4)); body.add_widget(sec("🔧  الترتيب والخيارات"))
            sort_opts=[("score","🏅 الأفضل"),("price_asc","💰↑"),("price_desc","💰↓"),("newest","🕐")]
            cur_sort=cfg.get("sort_by","score"); self._sort_btns={}
            sr=BoxLayout(size_hint_y=None,height=dp(36),spacing=dp(6))
            for k,t_text in sort_opts:
                b=ToggleButton(text=ar(t_text),state="down" if k==cur_sort else "normal",
                    size_hint=(1,None),height=dp(36),background_color=TRANSP,color=TEXT1,font_size=fs(11))
                bg(b,(*BLUE[:3],0.15) if k==cur_sort else BG2,radius=10)
                b.bind(state=lambda x,s,k=k,b=b:(bg(b,(*BLUE[:3],0.15) if s=="down" else BG2,radius=10),self._excl(k) if s=="down" else None))
                self._sort_btns[k]=b; sr.add_widget(b)
            body.add_widget(sr)
            self._bg_int=tf(cfg.get("bg_interval",30)); row("فترة الخلفية (دقيقة)",self._bg_int,"5-∞")
            self._purge=tf(cfg.get("purge_days",60)); row("حذف القديم (يوم)",self._purge,"60=افتراضي")
            self._notif=tog("🔔 إشعارات",cfg.get("notifications",True))
            self._show_hid=tog("👁 عرض المخفية",cfg.get("show_hidden",False))

            bg_on=is_bg()
            self._bg_btn=btn("⏹ إيقاف الخلفية" if bg_on else "▶ تشغيل الخلفية",
                              on_press=self._toggle_bg,color=RED if bg_on else tuple(PRIMARY()),
                              height=46,radius=12)
            body.add_widget(gap(6)); body.add_widget(self._bg_btn)
            body.add_widget(gap(8))
            body.add_widget(btn("💾 حفظ الإعدادات",on_press=self._save,height=54,radius=14))
            body.add_widget(gap(20))
            scroll.add_widget(body); root.add_widget(scroll)
            root.add_widget(nav_bar(self.app_ref,"settings")); self.add_widget(root)

        def _set_accent(self,hex_):
            set_accent(hex_)
            for h,b in self._accent_btns.items(): b.text="●" if h==hex_ else "○"

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
        def _excl(self,chosen):
            for k,b in self._sort_btns.items():
                if k!=chosen: b.state="normal"; bg(b,BG2,radius=10)
        def _toggle_bg(self,*_):
            if is_bg():
                stop_bg(); bg(self._bg_btn,tuple(PRIMARY()),radius=12)
                self._bg_btn.text=ar("▶ تشغيل الخلفية")
            else:
                start_bg(); bg(self._bg_btn,RED,radius=12)
                self._bg_btn.text=ar("⏹ إيقاف الخلفية")
        def _reset(self,*_): save_cfg(dict(DEFAULTS)); self._build()
        def _save(self,*_):
            sel_src=[sid for sid,b in self._src_btns.items() if b.state=="down"]
            sel_areas=[area for area,b in self._area_btns.items() if b.state=="down"]
            cur_sort=next((k for k,b in self._sort_btns.items() if b.state=="down"),"score")
            cfg=load_cfg(); acc=cfg.get("accent","#22C55E")
            for h,b in self._accent_btns.items():
                if b.text=="●": acc=h; break
            cfg.update({
                "min_price":si(self._min_p,0),"max_price":si(self._max_p,700),
                "min_rooms":sf(self._min_r,0),"max_rooms":sf(self._max_r,0),
                "min_size":si(self._min_sz,0),"max_size":si(self._max_sz,0),
                "household_size":max(1,si(self._hh,1)),"wbs_only":self._wbs.state=="down",
                "wbs_level_min":si(self._wlmin,0),"wbs_level_max":si(self._wlmax,999),
                "jobcenter_mode":self._jc.state=="down","wohngeld_mode":self._wg.state=="down",
                "areas":sel_areas,"sources":sel_src if len(sel_src)<len(SOURCES) else [],
                "sort_by":cur_sort,"bg_interval":max(5,si(self._bg_int,30)),
                "purge_days":max(7,si(self._purge,60)),"notifications":self._notif.state=="down",
                "show_hidden":self._show_hid.state=="down",
                "font_scale":round(self._fs_slider.value,1),"accent":acc,
            })
            save_cfg(cfg); set_font_scale(cfg["font_scale"]); set_accent(acc)
            self.app_ref.sm.current="listings"

# ═══════════════════════════════════════════════════════════════════════
# App
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class WBSApp(App):
        def build(self):
            self.title="WBS Berlin"
            init_db(); bump_opens()
            cfg=load_cfg()
            set_font_scale(cfg.get("font_scale",1.0))
            set_accent(cfg.get("accent","#22C55E"))
            Window.clearcolor=BG
            _ensure_channel(); start_bg()
            self.sm=ScreenManager(transition=FadeTransition(duration=0.15))
            if is_first_run():
                self.sm.add_widget(OnboardingScreen(self)); self.sm.current="onboarding"
            else: self._add_main()
            return self.sm

        def _add_main(self):
            for name,cls in [("listings",ListingsScreen),("favorites",FavoritesScreen),
                              ("stats_scr",StatsScreen),("settings",SettingsScreen)]:
                if not any(s.name==name for s in self.sm.screens):
                    self.sm.add_widget(cls(self))

        def go_main(self): self._add_main(); self.sm.current="listings"
        def on_stop(self): pass  # keep bg running

    if __name__=="__main__": WBSApp().run()
else:
    if __name__=="__main__":
        init_db(); print(f"Network: {check_network()}")
        raw=fetch_all(); new=sum(1 for l in raw if save_listing(l))
        cfg=dict(DEFAULTS); shown=sort_listings(apply_filters(raw,cfg),"score")
        print(f"Results: {len(shown)}/{len(raw)} ({new} new)")
        for l in shown[:5]:
            p=f"{l['price']:.0f}€" if l.get("price") else "—"
            print(f"  [{l['source']}] {p} | {l.get('title','')[:45]}")
        st=get_stats_db(); print(f"DB: {st['db_total']} total")
