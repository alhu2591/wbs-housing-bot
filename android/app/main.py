"""
WBS Berlin v5.0 — Crash-proof Android App
Strategy: show loading screen FIRST, do everything else AFTER
No module-level code that can fail. All imports inside try/except.
"""

# ══════════════════════════════════════════════════════════════
# STEP 1: Write crash log immediately (before ANY other code)
# ══════════════════════════════════════════════════════════════
import os
import sys
import time

def _get_log_path():
    """Find a writable path for crash log."""
    candidates = [
        "/sdcard/wbs_crash.log",
        os.path.expanduser("~/wbs_crash.log"),
        "/data/user/0/de.alaa.wbs.wbsberlin/files/wbs_crash.log",
        "./wbs_crash.log",
    ]
    for p in candidates:
        try:
            with open(p, "a") as f:
                f.write("")
            return p
        except Exception:
            continue
    return None

_LOG_PATH = _get_log_path()

def log(msg):
    """Write to crash log — never raises."""
    try:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        if _LOG_PATH:
            with open(_LOG_PATH, "a") as f:
                f.write(line)
    except Exception:
        pass

log("=== WBS Berlin v5.0 starting ===")
log(f"Python: {sys.version}")
log(f"Platform: {sys.platform}")

# ══════════════════════════════════════════════════════════════
# STEP 2: Detect Android
# ══════════════════════════════════════════════════════════════
IS_ANDROID = False
try:
    import android  # noqa — only available on Android
    IS_ANDROID = True
    log("Running on Android")
except Exception:
    log("Not on Android (desktop mode)")

# ══════════════════════════════════════════════════════════════
# STEP 3: Get writable data directory BEFORE anything else
# ══════════════════════════════════════════════════════════════
_DATA_DIR = None

def get_data_dir():
    global _DATA_DIR
    if _DATA_DIR:
        return _DATA_DIR

    candidates = []

    # Android-specific paths
    if IS_ANDROID:
        try:
            from android.storage import app_storage_path
            candidates.append(app_storage_path())
        except Exception as e:
            log(f"app_storage_path failed: {e}")
        try:
            from jnius import autoclass
            ctx = autoclass("org.kivy.android.PythonActivity").mActivity
            candidates.append(ctx.getFilesDir().getAbsolutePath())
        except Exception as e:
            log(f"getFilesDir failed: {e}")
        candidates.extend([
            "/data/user/0/de.alaa.wbs.wbsberlin/files",
            "/sdcard/WBSBerlin",
        ])

    # Desktop fallback
    candidates.extend([
        os.path.expanduser("~/.wbsberlin"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
        "./data",
        ".",
    ])

    for p in candidates:
        try:
            os.makedirs(p, exist_ok=True)
            test_file = os.path.join(p, ".write_test")
            with open(test_file, "w") as f:
                f.write("ok")
            os.unlink(test_file)
            _DATA_DIR = p
            log(f"Data dir: {p}")
            return p
        except Exception as e:
            log(f"Candidate {p} failed: {e}")

    _DATA_DIR = "."
    log("WARNING: Using current dir for data")
    return _DATA_DIR

# Initialize data dir now
_DATA_DIR = get_data_dir()

# ══════════════════════════════════════════════════════════════
# STEP 4: Database (stdlib sqlite3 only — no p4a recipe needed)
# ══════════════════════════════════════════════════════════════
import sqlite3 as _sql
import threading
import json
import re
import hashlib
import socket
import ssl
import urllib.request

_db_lock = threading.RLock()

DDL = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY, url TEXT, source TEXT, title TEXT,
    price REAL, rooms REAL, size_m2 REAL, floor_ TEXT,
    available TEXT, location TEXT, wbs_label TEXT, wbs_level INTEGER,
    features TEXT DEFAULT '[]', deposit TEXT, heating TEXT,
    score INTEGER DEFAULT 0, trusted_wbs INTEGER DEFAULT 0,
    favorited INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0,
    seen INTEGER DEFAULT 0, ts_found REAL
);
CREATE INDEX IF NOT EXISTS i1 ON listings(ts_found DESC);
CREATE INDEX IF NOT EXISTS i2 ON listings(favorited);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS stats (
    id INTEGER PRIMARY KEY CHECK(id=1),
    found INTEGER DEFAULT 0, new_ INTEGER DEFAULT 0,
    opens INTEGER DEFAULT 0, last_check REAL
);
INSERT OR IGNORE INTO stats(id) VALUES(1);
"""

def _db():
    path = os.path.join(get_data_dir(), "wbs5.db")
    con = _sql.connect(path, timeout=10, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=3000")
    return con

def init_db():
    log("init_db start")
    with _db_lock:
        con = _db()
        con.executescript(DDL)
        con.commit()
        con.close()
    log("init_db done")

def kv_get(key, default=None):
    try:
        with _db_lock:
            con = _db()
            r = con.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
            con.close()
            return json.loads(r[0]) if r else default
    except Exception:
        return default

def kv_set(key, value):
    try:
        with _db_lock:
            con = _db()
            con.execute("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)",
                        (key, json.dumps(value, ensure_ascii=False)))
            con.commit()
            con.close()
    except Exception as e:
        log(f"kv_set error: {e}")

def save_listing(l):
    lid = l.get("id")
    if not lid:
        return False
    try:
        with _db_lock:
            con = _db()
            if con.execute("SELECT 1 FROM listings WHERE id=?", (lid,)).fetchone():
                con.close()
                return False
            feats = json.dumps(l.get("features") or [], ensure_ascii=False)
            con.execute("""INSERT OR IGNORE INTO listings
                (id,url,source,title,price,rooms,size_m2,floor_,available,
                 location,wbs_label,wbs_level,features,deposit,heating,
                 score,trusted_wbs,ts_found)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (lid, l.get("url"), l.get("source"), l.get("title"),
                 l.get("price"), l.get("rooms"), l.get("size_m2"),
                 l.get("floor"), l.get("available"), l.get("location"),
                 l.get("wbs_label"), l.get("wbs_level_num"), feats,
                 l.get("deposit"), l.get("heating"),
                 l.get("score", 0), 1 if l.get("trusted_wbs") else 0,
                 time.time()))
            con.execute("UPDATE stats SET found=found+1,new_=new_+1 WHERE id=1")
            con.commit()
            con.close()
            return True
    except Exception as e:
        log(f"save_listing error: {e}")
        return False

def get_db_listings(limit=200):
    try:
        with _db_lock:
            con = _db()
            rows = con.execute(
                "SELECT * FROM listings WHERE hidden=0 "
                "ORDER BY ts_found DESC LIMIT ?", (limit,)).fetchall()
            cols = [d[0] for d in con.description]
            con.close()
            return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        log(f"get_db_listings error: {e}")
        return []

def toggle_fav(lid):
    try:
        with _db_lock:
            con = _db()
            r = con.execute("SELECT favorited FROM listings WHERE id=?", (lid,)).fetchone()
            if r:
                nv = 0 if r[0] else 1
                con.execute("UPDATE listings SET favorited=? WHERE id=?", (nv, lid))
                con.commit()
                con.close()
                return bool(nv)
            con.close()
    except Exception as e:
        log(f"toggle_fav error: {e}")
    return False

def hide_item(lid):
    try:
        with _db_lock:
            con = _db()
            con.execute("UPDATE listings SET hidden=1 WHERE id=?", (lid,))
            con.commit()
            con.close()
    except Exception as e:
        log(f"hide_item error: {e}")

def get_favs():
    try:
        with _db_lock:
            con = _db()
            rows = con.execute("SELECT * FROM listings WHERE favorited=1 "
                               "ORDER BY ts_found DESC LIMIT 100").fetchall()
            cols = [d[0] for d in con.description]
            con.close()
            return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []

def get_stats():
    try:
        with _db_lock:
            con = _db()
            r = con.execute("SELECT * FROM stats WHERE id=1").fetchone()
            total = con.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
            by_src = {}
            for row in con.execute("SELECT source,COUNT(*) FROM listings GROUP BY source"):
                by_src[row[0]] = row[1]
            con.close()
            return {"found": r[1] if r else 0, "new_": r[2] if r else 0,
                    "opens": r[3] if r else 0, "last_check": r[4] if r else None,
                    "total": total, "by_src": by_src}
    except Exception:
        return {"found":0,"new_":0,"opens":0,"last_check":None,"total":0,"by_src":{}}

def bump_opens():
    try:
        with _db_lock:
            con = _db()
            con.execute("UPDATE stats SET opens=opens+1 WHERE id=1")
            con.commit()
            con.close()
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════
# STEP 5: Config
# ══════════════════════════════════════════════════════════════
DEFAULTS = {
    "max_price": 700, "min_price": 0, "min_rooms": 0.0,
    "wbs_only": False, "wbs_level_min": 0, "wbs_level_max": 999,
    "household_size": 1, "jobcenter_mode": False, "wohngeld_mode": False,
    "sources": [], "areas": [], "sort_by": "score",
    "bg_interval": 30, "notifications": True, "accent": "#22C55E",
}

def load_cfg():
    try:
        stored = kv_get("cfg", {})
        return {**DEFAULTS, **(stored if isinstance(stored, dict) else {})}
    except Exception:
        return dict(DEFAULTS)

def save_cfg(c):
    kv_set("cfg", c)

def is_first_run():
    return not kv_get("done", False)

def mark_done():
    kv_set("done", True)

# ══════════════════════════════════════════════════════════════
# STEP 6: Domain data (no Kivy references)
# ══════════════════════════════════════════════════════════════
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
def jc(n): return JC.get(max(1,min(int(n),6)),JC[6]+(max(1,int(n))-6)*110)
def wg(n): return WG.get(max(1,min(int(n),7)),WG[7]+(max(1,int(n))-7)*120)

FEATS = {
    "balkon":"🌿 بلكونة","terrasse":"🌿 تراس","garten":"🌱 حديقة",
    "aufzug":"🛗 مصعد","einbauküche":"🍳 مطبخ","keller":"📦 مخزن",
    "stellplatz":"🚗 موقف","tiefgarage":"🚗 جراج","barrierefrei":"♿",
    "neubau":"🏗 جديد","erstbezug":"✨ أول سكن","parkett":"🪵 باركيه",
    "fußbodenheizung":"🌡 تدفئة","fernwärme":"🌡 مركزية","saniert":"🔨 مجدد",
}

# ══════════════════════════════════════════════════════════════
# STEP 7: Network + Scrapers (all in functions, no module-level net)
# ══════════════════════════════════════════════════════════════
def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx

_UA = "Mozilla/5.0 (Linux; Android 13) Chrome/124.0"

def _get(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":_UA,"Accept-Language":"de-DE"})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
            return r.read().decode(r.headers.get_content_charset("utf-8") or "utf-8","replace")
    except Exception:
        return None

def _get_json(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":_UA,"Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx()) as r:
            return json.loads(r.read())
    except Exception:
        return None

def check_net():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(("8.8.8.8",53))
        s.close()
        return True
    except Exception:
        return False

def make_id(url):
    u = re.sub(r"[?#].*","",url.strip().rstrip("/"))
    return hashlib.sha256(u.encode()).hexdigest()[:14]

def parse_price(raw):
    if not raw: return None
    s = re.sub(r"[^\d\.,]","",str(raw))
    if not s: return None
    if "," in s and "." in s: s=s.replace(".","").replace(",",".")
    elif "," in s: s=s.replace(",",".")
    elif "." in s:
        p=s.split(".")
        if len(p)==2 and len(p[1])==3: s=s.replace(".","")
    try:
        v=float(s); return v if 50<v<8000 else None
    except Exception: return None

def parse_rooms(raw):
    m=re.search(r"(\d+[.,]?\d*)",str(raw or "").replace(",","."))
    try:
        v=float(m.group(1)) if m else None
        return v if v and 0.5<=v<=20 else None
    except Exception: return None

def enrich(title, desc):
    t=f"{title} {desc}".lower(); out={}
    for pat in [r"(\d[\d\.]*)\s*m[²2]",r"(\d[\d\.]*)\s*qm\b"]:
        m=re.search(pat,t)
        if m:
            try:
                v=float(m.group(1).replace(".",""))
                if 15<v<500: out["size_m2"]=v; break
            except Exception: pass
    for pat,fn in [(r"(\d+)\.\s*(?:og|etage)\b",lambda m:f"T{m.group(1)}"),
                   (r"\beg\b(?!\w)",lambda _:"EG"),
                   (r"\bdg\b(?!\w)",lambda _:"DG")]:
        mm=re.search(pat,t)
        if mm: out["floor"]=fn(mm); break
    if any(k in t for k in ["ab sofort","sofort frei"]): out["available"]="فوري"
    else:
        m=re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",t)
        if m: out["available"]=m.group(1)
    mm=re.search(r"wbs[\s\-_]*(\d{2,3})",t)
    if mm: out["wbs_level_num"]=int(mm.group(1))
    seen_f=set(); feats=[]
    for kw,lb in FEATS.items():
        if kw in t and lb not in seen_f: seen_f.add(lb); feats.append(lb)
    if feats: out["features"]=feats
    return out

def _score(l):
    s=8 if l.get("trusted_wbs") else 0
    s+=3 if l.get("source") in GOV else 0
    p=l.get("price")
    if p:
        if p<400: s+=10
        elif p<500: s+=7
        elif p<600: s+=4
    r=l.get("rooms")
    if r:
        if r>=3: s+=5
        elif r>=2: s+=3
    if l.get("size_m2"): s+=2
    if l.get("available")=="فوري": s+=5
    s+=min(len(l.get("features") or []),4)
    return s

def scrape_gewobag():
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
           "wbs_label":"WBS","ts":time.time(),**extra}
        l["score"]=_score(l); result.append(l)
    return result

def scrape_degewo():
    for api in ["https://immosuche.degewo.de/de/properties.json?property_type_id=1&categories[]=WBS&per_page=50",
                "https://immosuche.degewo.de/de/search.json?asset_classes[]=1&wbs=1"]:
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
               "rooms":parse_rooms(i.get("zimmer")),"location":i.get("district","Berlin"),
               "wbs_label":"WBS","ts":time.time(),**extra}
            l["score"]=_score(l); result.append(l)
        if result: return result
    return []

def fetch_all(enabled=None, timeout=25):
    log("fetch_all start")
    active=set(enabled) if enabled else set(SOURCES.keys())
    results=[]; lock=threading.Lock()
    scrapers={"gewobag":scrape_gewobag,"degewo":scrape_degewo}
    def run(src,fn):
        try:
            items=fn()
            with lock: results.extend(items)
            log(f"  {src}: {len(items)} items")
        except Exception as e:
            log(f"  {src} error: {e}")
    threads=[]
    for src in active:
        fn=scrapers.get(src)
        if fn:
            t=threading.Thread(target=run,args=(src,fn),daemon=True)
            threads.append(t); t.start()
    deadline=time.time()+timeout
    for t in threads: t.join(timeout=max(0.1,deadline-time.time()))
    seen_ids=set(); unique=[]
    for l in results:
        if l.get("id") and l["id"] not in seen_ids:
            seen_ids.add(l["id"]); unique.append(l)
    log(f"fetch_all done: {len(unique)} unique")
    return unique

def apply_filters(listings, cfg):
    out=[]; max_p=float(cfg.get("max_price") or 9999); min_p=float(cfg.get("min_price") or 0)
    min_r=float(cfg.get("min_rooms") or 0); wbs=bool(cfg.get("wbs_only"))
    wlmin=int(cfg.get("wbs_level_min") or 0); wlmax=int(cfg.get("wbs_level_max") or 999)
    jcm=bool(cfg.get("jobcenter_mode")); wgm=bool(cfg.get("wohngeld_mode"))
    n=max(1,int(cfg.get("household_size") or 1))
    areas=[a.lower() for a in (cfg.get("areas") or [])]; srcs=cfg.get("sources") or []
    for l in listings:
        if not l.get("id") or l.get("hidden"): continue
        if srcs and l.get("source") not in srcs: continue
        price=l.get("price"); rooms=l.get("rooms")
        if price is not None:
            if min_p>0 and price<min_p: continue
            if price>max_p: continue
        if rooms is not None and min_r>0 and rooms<min_r: continue
        if wbs and not l.get("trusted_wbs"): continue
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

def sort_listings(listings, sort_by):
    if sort_by=="price_asc":    return sorted(listings, key=lambda l:l.get("price") or 9999)
    elif sort_by=="price_desc": return sorted(listings, key=lambda l:-(l.get("price") or 0))
    elif sort_by=="newest":     return sorted(listings, key=lambda l:-(l.get("ts_found") or l.get("ts") or 0))
    return sorted(listings, key=lambda l:-(l.get("score") or 0))

# ══════════════════════════════════════════════════════════════
# STEP 8: Background worker
# ══════════════════════════════════════════════════════════════
_bg_stop = threading.Event()
_bg_thread = None

def _bg_worker():
    time.sleep(15)  # wait 15s after app starts
    while not _bg_stop.is_set():
        try:
            cfg = load_cfg()
            interval = max(5, int(cfg.get("bg_interval", 30))) * 60
            if check_net():
                raw = fetch_all(cfg.get("sources") or None, timeout=30)
                for l in raw:
                    save_listing(l)
            with _db_lock:
                con = _db()
                con.execute("UPDATE stats SET last_check=? WHERE id=1", (time.time(),))
                con.commit()
                con.close()
        except Exception as e:
            log(f"bg_worker error: {e}")
        _bg_stop.wait(timeout=interval)

def start_bg():
    global _bg_thread, _bg_stop
    if _bg_thread and _bg_thread.is_alive():
        return
    _bg_stop.clear()
    _bg_thread = threading.Thread(target=_bg_worker, daemon=True, name="WBSBg")
    _bg_thread.start()
    log("bg started")

def stop_bg(): _bg_stop.set()
def is_bg():
    return bool(_bg_thread and _bg_thread.is_alive())

# ══════════════════════════════════════════════════════════════
# STEP 9: Arabic text helper (100% safe fallback)
# ══════════════════════════════════════════════════════════════
_HAS_ARABIC = False
_reshaper = None
_get_display = None

def _init_arabic():
    global _HAS_ARABIC, _reshaper, _get_display
    try:
        import arabic_reshaper as _ar_mod
        from bidi.algorithm import get_display as _gd
        _reshaper = _ar_mod
        _get_display = _gd
        _HAS_ARABIC = True
        log("Arabic reshaper loaded")
    except Exception as e:
        log(f"Arabic reshaper not available: {e}")

def ar(text):
    """Reshape Arabic text. Never raises."""
    if not text:
        return ""
    s = str(text)
    if not _HAS_ARABIC:
        return s
    try:
        return _get_display(_reshaper.reshape(s))
    except Exception:
        return s

# ══════════════════════════════════════════════════════════════
# STEP 10: Kivy UI — loaded LAST, completely isolated
# ══════════════════════════════════════════════════════════════
log("Starting Kivy UI...")

try:
    import kivy
    kivy.require("2.0.0")
    from kivy.config import Config
    Config.set("graphics","width","400")
    Config.set("graphics","height","700")
    Config.set("kivy","log_level","warning")

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
    from kivy.core.text import LabelBase

    log("Kivy imported OK")
    HAS_KIVY = True

    # Colors
    BG    = get_color_from_hex("#0A0A0A")
    BG2   = get_color_from_hex("#141414")
    BG3   = get_color_from_hex("#1E1E1E")
    C_P   = get_color_from_hex("#22C55E")  # primary green
    C_PUR = get_color_from_hex("#8B5CF6")
    C_BLU = get_color_from_hex("#3B82F6")
    C_AMB = get_color_from_hex("#F59E0B")
    C_RED = get_color_from_hex("#EF4444")
    C_GLD = get_color_from_hex("#F59E0B")
    TX1   = get_color_from_hex("#F1F5F9")
    TX2   = get_color_from_hex("#94A3B8")
    TX3   = get_color_from_hex("#475569")
    DIV   = get_color_from_hex("#1E293B")
    WHITE = (1,1,1,1)
    NONE  = (0,0,0,0)

    _ACCENT = list(C_P)
    _FS     = [1.0]
    _FONT   = ["Roboto"]  # default, updated after font registration

    def ACC(): return tuple(_ACCENT)
    def fs(n): return sp(n * _FS[0])
    def FN():  return _FONT[0]

    # ── UI helpers ──────────────────────────────────────────
    def bg(w, color, r=0):
        w.canvas.before.clear()
        with w.canvas.before:
            Color(*color)
            rect = (RoundedRectangle(pos=w.pos,size=w.size,radius=[dp(r)])
                    if r else Rectangle(pos=w.pos,size=w.size))
        def _u(*_): rect.pos=w.pos; rect.size=w.size
        w.bind(pos=_u,size=_u)

    def lbl(text, sz=14, col=None, bold=False, align="right", **kw):
        col = col or TX1
        try: txt = ar(str(text)) if text else ""
        except Exception: txt = str(text) if text else ""
        w = Label(text=txt, font_size=fs(sz), color=col,
                  bold=bold, halign=align, font_name=FN(), **kw)
        w.bind(width=lambda *_: setattr(w,"text_size",(w.width,None)))
        return w

    def btn(text, cb=None, col=None, tcol=None, h=48, r=12, **kw):
        col  = col or ACC()
        tcol = tcol or WHITE
        try: txt = ar(str(text))
        except Exception: txt = str(text)
        b = Button(text=txt, size_hint_y=None, height=dp(h),
                   background_color=NONE, color=tcol,
                   font_size=fs(14), bold=True, font_name=FN(), **kw)
        bg(b, col, r=r)
        if cb: b.bind(on_press=cb)
        return b

    def gap(h=12): return Widget(size_hint_y=None, height=dp(h))
    def div():
        w=Widget(size_hint_y=None,height=dp(1)); bg(w,DIV); return w
    def sec(text):
        b=BoxLayout(size_hint_y=None,height=dp(28))
        b.add_widget(lbl(text,sz=11,col=TX3,bold=True)); return b
    def inp(val, filt="int"):
        t=TextInput(text=str(val),input_filter=filt,multiline=False,
                    background_color=NONE,foreground_color=TX1,
                    cursor_color=ACC(),font_size=fs(14))
        bg(t,BG3,r=10); return t
    def si(t,d=0):
        try: return int(float(t.text or d))
        except Exception: return d
    def sf(t,d=0.0):
        try: return float(t.text or d)
        except Exception: return d

    def navb(app, active):
        TABS=[("🏠","listings","الرئيسية"),("⭐","favs","المفضلة"),
              ("📊","stats","إحصائيات"),("⚙️","settings","إعدادات")]
        bar=BoxLayout(size_hint_y=None,height=dp(56))
        bg(bar,BG2)
        for icon,name,label in TABS:
            on=name==active
            try: txt=f"{icon}\n{ar(label)}"
            except Exception: txt=f"{icon}\n{label}"
            b=Button(text=txt,background_color=NONE,
                     color=ACC() if on else TX3,
                     font_size=fs(10 if not on else 11),
                     bold=on,font_name=FN())
            if on: bg(b,(*ACC()[:3],0.12))
            else: bg(b,BG2)
            n=name; b.bind(on_press=lambda _,n=n:setattr(app.sm,"current",n))
            bar.add_widget(b)
        return bar

    log("UI helpers defined")

except Exception as e:
    log(f"KIVY IMPORT FAILED: {e}")
    import traceback
    log(traceback.format_exc())
    HAS_KIVY = False

# ══════════════════════════════════════════════════════════════
# UI Screens
# ══════════════════════════════════════════════════════════════
if HAS_KIVY:

    class SplashScreen(Screen):
        """Shown for 0.5s while DB initializes."""
        def __init__(self,**kw):
            super().__init__(name="splash",**kw)
            bg(self,BG)
            root=FloatLayout()
            card=BoxLayout(orientation="vertical",padding=dp(32),spacing=dp(16),
                           size_hint=(0.8,0.5),pos_hint={"center_x":.5,"center_y":.5})
            bg(card,BG2,r=20)
            card.add_widget(Label(text="🏠",font_size=sp(60),size_hint_y=None,height=dp(80)))
            card.add_widget(lbl("WBS Berlin",sz=20,bold=True,col=ACC(),
                                 size_hint_y=None,height=dp(40)))
            card.add_widget(lbl("جاري التحميل...",sz=13,col=TX2,
                                  size_hint_y=None,height=dp(30)))
            root.add_widget(card)
            self.add_widget(root)

    class OnboardingScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="onboard",**kw)
            self.app=app; self._i=0; self._show()
        def _show(self):
            self.clear_widgets(); bg(self,BG)
            PAGES=[
                ("🏠","WBS Berlin","ابحث عن شقتك المدعومة\nمن مصادر رسمية وخاصة",ACC()),
                ("🗄","قاعدة بيانات","لا تكرار للإعلانات أبداً",C_PUR),
                ("🔔","إشعارات فورية","يعمل في الخلفية دائماً",C_AMB),
            ]
            p=PAGES[self._i]; last=self._i==len(PAGES)-1
            root=FloatLayout()
            card=BoxLayout(orientation="vertical",padding=dp(32),spacing=dp(16),
                           size_hint=(0.88,0.65),pos_hint={"center_x":.5,"center_y":.57})
            bg(card,BG2,r=20)
            card.add_widget(Label(text=p[0],font_size=sp(60),size_hint_y=None,height=dp(80)))
            card.add_widget(lbl(p[1],sz=20,bold=True,col=p[3],size_hint_y=None,height=dp(45)))
            card.add_widget(lbl(p[2],sz=14,col=TX2,size_hint_y=None,height=dp(60)))
            root.add_widget(card)
            brow=BoxLayout(size_hint=(0.88,None),height=dp(52),
                           pos_hint={"center_x":.5,"y":.05},spacing=dp(12))
            if not last: brow.add_widget(btn("تخطي",cb=self._done,col=BG3,tcol=TX2))
            brow.add_widget(btn("ابدأ 🚀" if last else "التالي ←",
                                cb=self._next if not last else self._done,col=p[3]))
            root.add_widget(brow); self.add_widget(root)
        def _next(self,*_): self._i=min(self._i+1,2); self._show()
        def _done(self,*_): mark_done(); self.app.go_main()

    class ListingCard(BoxLayout):
        def __init__(self,l,**kw):
            super().__init__(orientation="vertical",size_hint_y=None,
                             padding=(dp(14),dp(12)),spacing=dp(6),**kw)
            name,gov=SOURCES.get(l.get("source",""),("?",False))
            sc=C_PUR if gov else C_BLU
            price=l.get("price"); rooms=l.get("rooms"); sz=l.get("size_m2")
            floor_=l.get("floor_") or l.get("floor",""); avail=l.get("available","")
            try: feats=json.loads(l["features"]) if isinstance(l.get("features"),str) else (l.get("features") or [])
            except Exception: feats=[]
            feats=feats[:5]; title=(l.get("title") or "شقة").strip()[:65]
            wlnum=l.get("wbs_level") or l.get("wbs_level_num")
            wlbl=f"WBS {wlnum}" if wlnum else ("WBS ✓" if l.get("trusted_wbs") else "")
            self.url=l.get("url",""); self.lid=l.get("id",""); is_fav=bool(l.get("favorited"))
            n_fr=max(1,(len(feats)+2)//3) if feats else 0
            self.height=dp(165+n_fr*22)
            bg(self,BG2,r=14)

            # Header
            r1=BoxLayout(size_hint_y=None,height=dp(26),spacing=dp(6))
            ch=BoxLayout(size_hint=(None,None),size=(dp(110),dp(22)),padding=(dp(6),0))
            bg(ch,(*sc[:3],0.18),r=11)
            ch.add_widget(lbl(("🏛 " if gov else "🔍 ")+ar(name),sz=11,col=sc,size_hint_y=None,height=dp(22)))
            r1.add_widget(ch); r1.add_widget(Widget())
            if wlbl:
                wb=BoxLayout(size_hint=(None,None),size=(dp(72),dp(22)),padding=(dp(6),0))
                bg(wb,(*ACC()[:3],0.18),r=11)
                wb.add_widget(lbl(wlbl,sz=10,col=ACC(),bold=True,size_hint_y=None,height=dp(22)))
                r1.add_widget(wb)
            self._fb=Button(text="★" if is_fav else "☆",size_hint=(None,None),
                            size=(dp(28),dp(24)),background_color=NONE,
                            color=C_GLD if is_fav else TX3,font_size=sp(16))
            self._fb.bind(on_press=self._fav); r1.add_widget(self._fb)
            self.add_widget(r1)

            self.add_widget(lbl(title,sz=13,bold=True,size_hint_y=None,height=dp(22)))

            r3=BoxLayout(size_hint_y=None,height=dp(18))
            r3.add_widget(lbl("📍 "+ar(l.get("location","Berlin")),sz=11,col=TX2))
            if avail:
                avail_txt="فوري 🔥" if avail=="فوري" else avail
                r3.add_widget(lbl("📅 "+ar(avail_txt),sz=11,col=C_AMB if avail=="فوري" else TX2))
            self.add_widget(r3); self.add_widget(div())

            r4=BoxLayout(size_hint_y=None,height=dp(32),spacing=dp(6))
            if price:
                ppm=f" ({price/sz:.1f}€/m²)" if sz else ""
                p2=BoxLayout(size_hint=(None,None),size=(dp(110),dp(28)),padding=(dp(6),0))
                bg(p2,(*ACC()[:3],0.15),r=9)
                p2.add_widget(lbl(f"💰 {price:.0f}€{ppm}",sz=12,col=ACC(),bold=True,size_hint_y=None,height=dp(28)))
                r4.add_widget(p2)
            if rooms: r4.add_widget(lbl(f"🛏 {rooms:.0f}",sz=11,col=TX1))
            if sz:    r4.add_widget(lbl(f"📐 {sz:.0f}m²",sz=11,col=TX1))
            if floor_:r4.add_widget(lbl(ar(floor_),sz=10,col=TX2))
            self.add_widget(r4)

            if feats:
                fg=GridLayout(cols=3,size_hint_y=None,height=dp(n_fr*22),spacing=dp(3))
                for f in feats:
                    c=BoxLayout(size_hint_y=None,height=dp(20),padding=(dp(4),0))
                    bg(c,BG3,r=6)
                    c.add_widget(lbl(ar(f),sz=9,col=TX2,size_hint_y=None,height=dp(20)))
                    fg.add_widget(c)
                self.add_widget(fg)

            ab=BoxLayout(size_hint_y=None,height=dp(32),spacing=dp(8))
            ab.add_widget(btn("فتح ←",cb=self._open,h=32,r=9))
            ab.add_widget(btn("إخفاء",cb=self._hide,col=BG3,tcol=TX2,h=32,r=9,
                               size_hint_x=None,width=dp(74)))
            self.add_widget(ab)

        def _fav(self,*_):
            if not self.lid: return
            nv=toggle_fav(self.lid)
            self._fb.color=C_GLD if nv else TX3
            self._fb.text="★" if nv else "☆"
        def _hide(self,*_):
            if self.lid: hide_item(self.lid)
            self.opacity=0; self.height=0
        def _open(self,*_):
            if not self.url: return
            log(f"Opening: {self.url}")
            try:
                from jnius import autoclass
                I=autoclass("android.content.Intent")
                U=autoclass("android.net.Uri")
                PA=autoclass("org.kivy.android.PythonActivity")
                PA.mActivity.startActivity(I(I.ACTION_VIEW,U.parse(self.url)))
            except Exception:
                try:
                    from kivy.core.clipboard import Clipboard
                    Clipboard.copy(self.url)
                    log("URL copied to clipboard")
                except Exception: pass

    class ListingsScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="listings",**kw)
            self.app=app; self._lock=threading.RLock()
            self._busy=False; self._raw=[]; bg(self,BG)
            self._ui()
        def _ui(self):
            cfg=load_cfg(); root=BoxLayout(orientation="vertical")
            bar=BoxLayout(size_hint_y=None,height=dp(56),padding=(dp(12),dp(8)),spacing=dp(8))
            bg(bar,BG2)
            bar.add_widget(lbl("🏠 WBS برلين",sz=16,bold=True,col=WHITE,size_hint_x=0.45))
            bar.add_widget(Widget())
            self._sb=btn({"score":"🏅","price_asc":"💰↑","price_desc":"💰↓","newest":"🕐"}.get(cfg.get("sort_by","score"),"🏅"),
                         cb=self._sort,col=BG3,tcol=TX2,size_hint_x=None,h=40,width=dp(44))
            bar.add_widget(self._sb)
            bar.add_widget(btn("⚙️",cb=lambda*_:setattr(self.app.sm,"current","settings"),
                               col=BG3,tcol=TX2,size_hint_x=None,h=40,width=dp(44)))
            self._rb=btn("🔄",cb=self._refresh,col=ACC(),size_hint_x=None,h=40,width=dp(44))
            bar.add_widget(self._rb); root.add_widget(bar)

            chips=BoxLayout(size_hint_y=None,height=dp(42),padding=(dp(10),dp(5)),spacing=dp(8))
            bg(chips,BG2)
            self._wc=ToggleButton(text=ar("✅ WBS"),state="down" if cfg.get("wbs_only") else "normal",
                size_hint=(None,None),size=(dp(90),dp(28)),background_color=NONE,
                color=TX1,font_size=fs(12),font_name=FN())
            self._uc()
            self._wc.bind(state=self._wbs)
            chips.add_widget(self._wc)
            self._st=lbl("اضغط 🔄 للبحث",sz=12,col=TX2,size_hint_y=None,height=dp(28))
            chips.add_widget(self._st)
            self._bgi=Label(text="⏸",font_size=sp(14),color=TX3,size_hint=(None,None),size=(dp(26),dp(28)))
            chips.add_widget(self._bgi)
            root.add_widget(chips); root.add_widget(div())

            self._cl=BoxLayout(orientation="vertical",spacing=dp(8),padding=(dp(10),dp(8)),size_hint_y=None)
            self._cl.bind(minimum_height=self._cl.setter("height"))
            sv=ScrollView(bar_color=(*ACC()[:3],0.4)); sv.add_widget(self._cl)
            root.add_widget(sv); root.add_widget(navb(self.app,"listings"))
            self.add_widget(root)
            self._ph("🔍",ar("اضغط 🔄 للبحث"))

        def on_enter(self,*_): Clock.schedule_interval(self._tick,10)
        def on_leave(self,*_): Clock.unschedule(self._tick)

        def _tick(self,*_):
            try:
                self._bgi.text="🟢" if is_bg() else "⏸"
                self._bgi.color=ACC() if is_bg() else TX3
            except Exception: pass

        def _uc(self):
            on=self._wc.state=="down"
            bg(self._wc,(*ACC()[:3],0.85) if on else BG3,r=14)

        def _wbs(self,_,state):
            self._uc(); cfg=load_cfg(); cfg["wbs_only"]=state=="down"; save_cfg(cfg)
            with self._lock: raw=list(self._raw)
            if raw:
                shown=sort_listings(apply_filters(raw,cfg),cfg.get("sort_by","score"))
                Clock.schedule_once(lambda dt:self._render(shown,len(raw)))

        def _sort(self,*_):
            order=["score","price_asc","price_desc","newest"]
            icons={"score":"🏅","price_asc":"💰↑","price_desc":"💰↓","newest":"🕐"}
            cfg=load_cfg(); cur=cfg.get("sort_by","score")
            nxt=order[(order.index(cur)+1)%len(order)]
            cfg["sort_by"]=nxt; save_cfg(cfg); self._sb.text=icons[nxt]
            with self._lock: raw=list(self._raw)
            if raw:
                shown=sort_listings(apply_filters(raw,cfg),nxt)
                Clock.schedule_once(lambda dt:self._render(shown,len(raw)))

        def _ph(self,icon,msg):
            self._cl.clear_widgets()
            b=BoxLayout(orientation="vertical",spacing=dp(8),size_hint_y=None,height=dp(180),padding=dp(32))
            b.add_widget(Label(text=icon,font_size=sp(48),size_hint_y=None,height=dp(60)))
            b.add_widget(lbl(msg,sz=14,col=TX2,size_hint_y=None,height=dp(40)))
            self._cl.add_widget(b)

        def _refresh(self,*_):
            with self._lock:
                if self._busy: return
                self._busy=True
            if not check_net():
                cached=get_db_listings()
                with self._lock: self._busy=False
                if cached:
                    self._st.text=ar("📦 من قاعدة البيانات")
                    with self._lock: self._raw=cached
                    cfg=load_cfg()
                    shown=sort_listings(apply_filters(cached,cfg),cfg.get("sort_by","score"))
                    Clock.schedule_once(lambda dt:self._render(shown,len(cached)))
                else: self._ph("📵",ar("لا يوجد اتصال"))
                return
            self._st.text=ar("⏳ جاري البحث..."); self._ph("⏳",ar("جاري الجلب..."))
            threading.Thread(target=self._bg_fetch,daemon=True).start()

        def _bg_fetch(self):
            try:
                cfg=load_cfg(); raw=fetch_all(cfg.get("sources") or None)
                new_c=sum(1 for l in raw if save_listing(l))
                all_db=get_db_listings()
                with self._lock: self._raw=all_db
                shown=sort_listings(apply_filters(all_db,cfg),cfg.get("sort_by","score"))
                Clock.schedule_once(lambda dt:self._render(shown,len(all_db),new_c))
            except Exception as e:
                log(f"_bg_fetch error: {e}")
                Clock.schedule_once(lambda dt:self._ph("⚠️",ar(f"خطأ: {str(e)[:50]}")))
            finally:
                with self._lock: self._busy=False

        def _render(self,lst,total=None,nc=0):
            try:
                self._cl.clear_widgets()
                t=total if total is not None else len(lst)
                ns=f" (+{nc})" if nc else ""
                if not lst:
                    self._st.text=ar(f"لا إعلانات ({t})")
                    self._ph("🔍",ar("لا توجد إعلانات")); return
                self._st.text=ar(f"✅ {len(lst)} من {t}{ns}")
                for l in lst[:10]:
                    self._cl.add_widget(ListingCard(l)); self._cl.add_widget(gap(6))
                if len(lst)>10:
                    Clock.schedule_once(lambda dt:self._rest(lst[10:]),0.1)
            except Exception as e:
                log(f"_render error: {e}")

        def _rest(self,rest):
            try:
                for l in rest[:50]:
                    self._cl.add_widget(ListingCard(l)); self._cl.add_widget(gap(6))
            except Exception: pass

    class FavsScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="favs",**kw); self.app=app
            bg(self,BG); self._build()
        def _build(self):
            self.clear_widgets(); root=BoxLayout(orientation="vertical")
            bar=BoxLayout(size_hint_y=None,height=dp(56),padding=(dp(12),dp(8)))
            bg(bar,BG2)
            bar.add_widget(lbl("⭐ "+ar("المفضلة"),sz=16,bold=True,col=C_GLD))
            bar.add_widget(btn("🔄",cb=self._load,col=BG3,tcol=TX2,size_hint_x=None,h=40,width=dp(44)))
            root.add_widget(bar)
            self._cl=BoxLayout(orientation="vertical",spacing=dp(8),padding=(dp(10),dp(8)),size_hint_y=None)
            self._cl.bind(minimum_height=self._cl.setter("height"))
            sv=ScrollView(bar_color=(*C_GLD[:3],0.4)); sv.add_widget(self._cl)
            root.add_widget(sv); root.add_widget(navb(self.app,"favs"))
            self.add_widget(root); self._load()
        def on_enter(self,*_): self._load()
        def _load(self,*_):
            self._cl.clear_widgets()
            for l in get_favs():
                self._cl.add_widget(ListingCard(l)); self._cl.add_widget(gap(6))
            if not get_favs():
                b=BoxLayout(orientation="vertical",size_hint_y=None,height=dp(150),padding=dp(32))
                b.add_widget(Label(text="⭐",font_size=sp(48),size_hint_y=None,height=dp(60)))
                b.add_widget(lbl("لا توجد مفضلة",sz=14,col=TX2,size_hint_y=None,height=dp(40)))
                self._cl.add_widget(b)

    class StatsScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="stats",**kw); self.app=app
            bg(self,BG); self._build()
        def on_enter(self,*_): self._build()
        def _build(self):
            self.clear_widgets(); root=BoxLayout(orientation="vertical")
            bar=BoxLayout(size_hint_y=None,height=dp(56),padding=(dp(12),dp(8)))
            bg(bar,BG2)
            bar.add_widget(lbl("📊 "+ar("الإحصائيات"),sz=16,bold=True,col=WHITE))
            root.add_widget(bar)
            sc=ScrollView(); body=BoxLayout(orientation="vertical",padding=dp(14),spacing=dp(8),size_hint_y=None)
            body.bind(minimum_height=body.setter("height"))
            st=get_stats()
            def scard(icon,label,val,col=None):
                c=BoxLayout(size_hint_y=None,height=dp(64),padding=(dp(14),dp(8)),spacing=dp(10))
                bg(c,BG2,r=12)
                c.add_widget(Label(text=icon,font_size=sp(26),size_hint=(None,None),size=(dp(44),dp(44))))
                t=BoxLayout(orientation="vertical")
                t.add_widget(lbl(ar(label),sz=12,col=TX2))
                t.add_widget(lbl(str(val),sz=18,bold=True,col=col or ACC()))
                c.add_widget(t); return c
            def ts2s(ts):
                if not ts: return "—"
                try: return __import__("datetime").datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                except Exception: return "—"
            body.add_widget(scard("🏠","إجمالي الإعلانات",st.get("total",0)))
            body.add_widget(scard("🆕","إعلانات جديدة",st.get("new_",0),C_P))
            body.add_widget(scard("📱","مرات الفتح",st.get("opens",0),C_PUR))
            body.add_widget(scard("🕐","آخر فحص",ts2s(st.get("last_check")),TX2))
            body.add_widget(gap(8))
            body.add_widget(btn("🗑 "+ar("مسح قاعدة البيانات"),cb=self._clear,col=C_RED,h=44,r=12))
            body.add_widget(gap(20))
            sc.add_widget(body); root.add_widget(sc)
            root.add_widget(navb(self.app,"stats")); self.add_widget(root)
        def _clear(self,*_):
            try:
                with _db_lock:
                    con=_db()
                    con.execute("DELETE FROM listings WHERE favorited=0")
                    con.execute("UPDATE stats SET found=0,new_=0 WHERE id=1")
                    con.commit(); con.close()
            except Exception as e: log(f"clear error: {e}")
            self._build()

    class SettingsScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="settings",**kw); self.app=app
            bg(self,BG); self._build()
        def _build(self):
            self.clear_widgets(); cfg=load_cfg(); root=BoxLayout(orientation="vertical")
            hdr=BoxLayout(size_hint_y=None,height=dp(56),padding=(dp(12),dp(8)),spacing=dp(10))
            bg(hdr,BG2)
            hdr.add_widget(lbl("⚙️ "+ar("الإعدادات"),sz=16,bold=True,col=WHITE))
            hdr.add_widget(btn("↩️",cb=self._reset,col=BG3,tcol=TX2,size_hint_x=None,h=40,width=dp(48)))
            root.add_widget(hdr)
            sc=ScrollView(); body=BoxLayout(orientation="vertical",padding=dp(14),spacing=dp(8),size_hint_y=None)
            body.bind(minimum_height=body.setter("height"))

            def row(lbl_t,w,hint=""):
                r=BoxLayout(size_hint_y=None,height=dp(54),spacing=dp(12),padding=(dp(12),dp(4)))
                bg(r,BG2,r=12)
                lb=BoxLayout(orientation="vertical",size_hint_x=0.45)
                lb.add_widget(lbl(lbl_t,sz=13,col=TX1))
                if hint: lb.add_widget(lbl(hint,sz=10,col=TX3))
                r.add_widget(lb); r.add_widget(w); body.add_widget(r)

            def tog(text,active,pri=None):
                pri=pri or ACC()
                t=ToggleButton(text=ar(text),state="down" if active else "normal",
                    size_hint=(1,None),height=dp(44),background_color=NONE,
                    color=TX1,font_size=fs(13),font_name=FN())
                bg(t,(*pri[:3],0.15) if active else BG2,r=12)
                t.bind(state=lambda b,s,p=pri:bg(b,(*p[:3],0.15) if s=="down" else BG2,r=12))
                body.add_widget(t); return t

            body.add_widget(gap(4)); body.add_widget(sec("💰  الميزانية"))
            self._max_p=inp(cfg.get("max_price",700)); row("أقصى إيجار (€)",self._max_p)
            self._min_p=inp(cfg.get("min_price",0)); row("الحد الأدنى (€)",self._min_p,"0=بدون")

            body.add_widget(gap(4)); body.add_widget(sec("📋  WBS"))
            self._wbs=tog("WBS فقط",cfg.get("wbs_only",False))
            wlr=BoxLayout(size_hint_y=None,height=dp(54),spacing=dp(6),padding=(dp(12),dp(4)))
            bg(wlr,BG2,r=12)
            wlr.add_widget(lbl("مستوى WBS:",sz=13,col=TX1,size_hint_x=0.32))
            self._wlmin=inp(cfg.get("wbs_level_min",0)); self._wlmax=inp(cfg.get("wbs_level_max",999))
            wlr.add_widget(lbl("من",sz=11,col=TX2,size_hint_x=0.08)); wlr.add_widget(self._wlmin)
            wlr.add_widget(lbl("—",sz=13,col=TX2,size_hint_x=0.06)); wlr.add_widget(self._wlmax)
            body.add_widget(wlr)
            pr=BoxLayout(size_hint_y=None,height=dp(36),spacing=dp(6))
            for lt,mn,mx in [("100","100","100"),("100-140","100","140"),("كل","0","999")]:
                b=btn(lt,col=BG3,tcol=TX1,h=36,r=10,size_hint_x=None,width=dp(80))
                b.bind(on_press=lambda _,mn=mn,mx=mx:(setattr(self._wlmin,"text",mn),setattr(self._wlmax,"text",mx)))
                pr.add_widget(b)
            body.add_widget(pr)

            body.add_widget(gap(4)); body.add_widget(sec("🏛  اجتماعي"))
            self._hh=inp(cfg.get("household_size",1))
            n_=max(1,int(cfg.get("household_size") or 1))
            row("أفراد الأسرة",self._hh,f"JC≤{jc(n_):.0f}€")
            self._jc=tog("Jobcenter KdU",cfg.get("jobcenter_mode",False),C_PUR)
            self._wg=tog("Wohngeld",cfg.get("wohngeld_mode",False),C_PUR)

            body.add_widget(gap(4)); body.add_widget(sec("📍  المناطق"))
            cur_ar=cfg.get("areas") or []; self._ab={}
            ag=GridLayout(cols=2,size_hint_y=None,height=dp(((len(BERLIN_AREAS)+1)//2)*38),spacing=dp(4))
            for area in BERLIN_AREAS:
                on=area in cur_ar
                b=ToggleButton(text=area,state="down" if on else "normal",
                    size_hint=(1,None),height=dp(36),background_color=NONE,color=TX1,font_size=fs(11))
                bg(b,(*C_AMB[:3],0.15) if on else BG2,r=8)
                b.bind(state=lambda x,s,b=b:bg(b,(*C_AMB[:3],0.15) if s=="down" else BG2,r=8))
                self._ab[area]=b; ag.add_widget(b)
            body.add_widget(ag)
            body.add_widget(btn("🌍 "+ar("كل برلين"),cb=self._clrar,col=BG3,tcol=TX2,h=36,r=10))

            body.add_widget(gap(4)); body.add_widget(sec("🌐  المصادر"))
            cur_src=cfg.get("sources") or []; self._src={}
            for sid,(sname,gov) in SOURCES.items():
                sc=C_PUR if gov else C_BLU; on=not cur_src or sid in cur_src
                b=ToggleButton(text=("🏛 " if gov else "🔍 ")+ar(sname),
                    state="down" if on else "normal",size_hint=(1,None),height=dp(42),
                    background_color=NONE,color=TX1,font_size=fs(12))
                bg(b,(*sc[:3],0.15) if on else BG2,r=10)
                b.bind(state=lambda x,s,sc=sc,b=b:bg(b,(*sc[:3],0.15) if s=="down" else BG2,r=10))
                self._src[sid]=b; body.add_widget(b)
            qr=BoxLayout(size_hint_y=None,height=dp(36),spacing=dp(8))
            qr.add_widget(btn("✅ "+ar("الكل"),cb=lambda*_:self._allsrc(True),col=BG3,tcol=TX1,h=36,r=10))
            qr.add_widget(btn("🏛 "+ar("حكومية"),cb=self._govsrc,col=(*C_PUR[:3],1),h=36,r=10))
            body.add_widget(qr)

            body.add_widget(gap(4)); body.add_widget(sec("🔧  متقدم"))
            self._bgi=inp(cfg.get("bg_interval",30))
            row("فترة الخلفية (دق.)",self._bgi,"5+")
            self._notif=tog("🔔 إشعارات",cfg.get("notifications",True))
            bg_on=is_bg()
            self._bgb=btn("⏹ "+ar("إيقاف") if bg_on else "▶ "+ar("تشغيل الخلفية"),
                           cb=self._togbg,col=C_RED if bg_on else ACC(),h=44,r=12)
            body.add_widget(gap(6)); body.add_widget(self._bgb)
            body.add_widget(gap(8))
            body.add_widget(btn("💾 "+ar("حفظ"),cb=self._save,h=52,r=14))
            body.add_widget(gap(20))
            sc.add_widget(body); root.add_widget(sc)
            root.add_widget(navb(self.app,"settings")); self.add_widget(root)

        def _clrar(self,*_):
            for b in self._ab.values(): b.state="normal"; bg(b,BG2,r=8)
        def _allsrc(self,on):
            for sid,b in self._src.items():
                b.state="down" if on else "normal"
                sc=C_PUR if SOURCES[sid][1] else C_BLU
                bg(b,(*sc[:3],0.15) if on else BG2,r=10)
        def _govsrc(self,*_):
            for sid,b in self._src.items():
                gov=SOURCES[sid][1]; sc=C_PUR if gov else C_BLU
                b.state="down" if gov else "normal"
                bg(b,(*sc[:3],0.15) if gov else BG2,r=10)
        def _togbg(self,*_):
            if is_bg():
                stop_bg(); bg(self._bgb,ACC(),r=12); self._bgb.text=ar("▶ تشغيل الخلفية")
            else:
                start_bg(); bg(self._bgb,C_RED,r=12); self._bgb.text=ar("⏹ إيقاف")
        def _reset(self,*_): save_cfg(dict(DEFAULTS)); self._build()
        def _save(self,*_):
            sel_src=[s for s,b in self._src.items() if b.state=="down"]
            sel_ar=[a for a,b in self._ab.items() if b.state=="down"]
            cur_s=next((k for k,b in {}.items() if b.state=="down"),"score")
            cfg=load_cfg()
            cfg.update({
                "max_price":si(self._max_p,700),"min_price":si(self._min_p,0),
                "household_size":max(1,si(self._hh,1)),
                "wbs_only":self._wbs.state=="down",
                "wbs_level_min":si(self._wlmin,0),"wbs_level_max":si(self._wlmax,999),
                "jobcenter_mode":self._jc.state=="down","wohngeld_mode":self._wg.state=="down",
                "areas":sel_ar,"sources":sel_src if len(sel_src)<len(SOURCES) else [],
                "bg_interval":max(5,si(self._bgi,30)),"notifications":self._notif.state=="down",
            })
            save_cfg(cfg); self.app.sm.current="listings"

    class WBSApp(App):
        def build(self):
            log("build() start")
            # Show splash immediately — guarantees something is on screen
            self.sm = ScreenManager(transition=FadeTransition(duration=0.15))
            self.sm.add_widget(SplashScreen())
            self.sm.current = "splash"
            Window.clearcolor = BG
            # Defer ALL initialization — happens after first frame drawn
            Clock.schedule_once(self._init, 0.1)
            log("build() returning sm")
            return self.sm

        def _init(self, dt):
            """Called 0.1s after first frame — safe to do everything here."""
            log("_init start")
            try:
                # Arabic support
                _init_arabic()
                # Database
                init_db()
                bump_opens()
                # Font
                try:
                    fp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "NotoNaskhArabic.ttf")
                    if os.path.exists(fp):
                        LabelBase.register(name="NotoArabic", fn_regular=fp)
                        _FONT[0] = "NotoArabic"
                        log("Arabic font registered")
                    else:
                        log(f"Font not found: {fp}")
                except Exception as e:
                    log(f"Font registration failed: {e}")
                # Config
                cfg = load_cfg()
                try:
                    c = get_color_from_hex(cfg.get("accent","#22C55E"))
                    _ACCENT[:] = list(c)
                except Exception:
                    pass
                # Go to real screens
                Clock.schedule_once(self._show_main, 0.4)
            except Exception as e:
                log(f"_init ERROR: {e}")
                import traceback
                log(traceback.format_exc())
                # Still try to show main screens
                Clock.schedule_once(self._show_main, 0.1)

        def _show_main(self, dt):
            log("_show_main")
            try:
                if is_first_run():
                    self.sm.add_widget(OnboardingScreen(self))
                    self.sm.current = "onboard"
                else:
                    self._add_main()
                # Start background worker 5s after UI ready
                Clock.schedule_once(lambda _: start_bg(), 5.0)
            except Exception as e:
                log(f"_show_main ERROR: {e}")
                import traceback
                log(traceback.format_exc())
                # Last resort: just add listings screen
                try:
                    self.sm.add_widget(ListingsScreen(self))
                    self.sm.current = "listings"
                except Exception as e2:
                    log(f"FATAL: {e2}")

        def _add_main(self):
            for name, cls in [("listings",ListingsScreen),("favs",FavsScreen),
                               ("stats",StatsScreen),("settings",SettingsScreen)]:
                if not any(s.name==name for s in self.sm.screens):
                    self.sm.add_widget(cls(self))
            self.sm.current = "listings"

        def go_main(self):
            self._add_main()

        def on_stop(self):
            log("App stopped")

    if __name__ == "__main__":
        log("Starting WBSApp")
        try:
            WBSApp().run()
        except Exception as e:
            log(f"App.run() crashed: {e}")
            import traceback
            log(traceback.format_exc())
            raise

else:
    log("Kivy not available — CLI mode")
    if __name__ == "__main__":
        print("WBS Berlin — CLI")
        init_db()
        print(f"DB: {DB_PATH()}")
        print(f"Network: {check_net()}")
        raw = fetch_all()
        cfg = dict(DEFAULTS)
        shown = sort_listings(apply_filters(raw, cfg), "score")
        print(f"Results: {len(shown)}/{len(raw)}")
        for l in shown[:5]:
            p = f"{l['price']:.0f}€" if l.get("price") else "—"
            print(f"  [{l['source']}] {p} | {l.get('title','')[:45]}")
