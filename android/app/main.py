"""WBS Berlin v6.0 — All issues fixed"""
import os, sys, time, threading, json, re, hashlib, socket, ssl, sqlite3
import urllib.request

# ── Crash log ──────────────────────────────────────────────────────────
_T0 = time.time()
_LOG = None
for _p in ["/sdcard/wbs_log.txt",
           os.path.join(os.path.dirname(os.path.abspath(__file__)), "wbs_log.txt")]:
    try:
        with open(_p, "w") as _f:  # FIX: use 'with' to close properly
            _f.write(f"START {time.ctime()}\nPython {sys.version}\n")
        _LOG = _p
        break
    except Exception:
        pass

def log(msg):
    try:
        if _LOG:
            with open(_LOG, "a") as f:
                f.write(f"[{time.time()-_T0:.2f}] {msg}\n")
    except Exception:
        pass

log("imports done")

# ── Arabic — cached at module level, not re-imported every call ────────
_ar_reshaper = None
_ar_display = None

def _init_arabic():
    global _ar_reshaper, _ar_display
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        _ar_reshaper = arabic_reshaper
        _ar_display = get_display
        log("arabic ok")
    except Exception as e:
        log(f"arabic unavailable: {e}")

def ar(text):
    s = str(text or "")
    if _ar_reshaper is None or _ar_display is None:
        return s
    try:
        return _ar_display(_ar_reshaper.reshape(s))
    except Exception:
        return s

# ── Data directory (Android scoped storage safe) ──────────────────────
def _find_dir():
    """
    Find a writable directory. Strategy:
    1. Android internal app storage via jnius (always works, no permissions needed)
    2. External app-specific dir via jnius (no permissions needed on any Android version)
    3. Desktop fallback
    Avoids /sdcard root (blocked on Android 10+ scoped storage).
    """
    # Try Android via jnius first
    try:
        from jnius import autoclass
        ctx = autoclass("org.kivy.android.PythonActivity").mActivity
        # Internal files dir — always writable, no permissions needed
        d = ctx.getFilesDir().getAbsolutePath()
        os.makedirs(d, exist_ok=True)
        log(f"Using internal dir: {d}")
        return d
    except Exception as e:
        log(f"jnius dir failed: {e}")

    # Try external app-specific dir (no WRITE_EXTERNAL_STORAGE needed on Android 4.4+)
    try:
        from jnius import autoclass
        ctx = autoclass("org.kivy.android.PythonActivity").mActivity
        ext = ctx.getExternalFilesDir(None)
        if ext:
            d = ext.getAbsolutePath()
            os.makedirs(d, exist_ok=True)
            log(f"Using external app dir: {d}")
            return d
    except Exception:
        pass

    # Desktop fallbacks
    for d in [os.path.expanduser("~/.wbsberlin"), "."]:
        try:
            os.makedirs(d, exist_ok=True)
            test = os.path.join(d, ".wtest")
            with open(test, "w") as f:
                f.write("ok")
            os.unlink(test)
            log(f"Using dir: {d}")
            return d
        except Exception:
            pass

    return "."

_DIR = _find_dir()
log(f"data dir: {_DIR}")

# ── Database ───────────────────────────────────────────────────────────
_DL = threading.RLock()

def _db():
    c = sqlite3.connect(
        os.path.join(_DIR, "wbs.db"),
        timeout=5,
        check_same_thread=False
    )
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=3000")
    return c

def init_db():
    with _DL:
        c = _db()
        try:
            c.executescript("""
            CREATE TABLE IF NOT EXISTS listings (
                id TEXT PRIMARY KEY, url TEXT, source TEXT, title TEXT,
                price REAL, rooms REAL, size_m2 REAL, floor_ TEXT,
                available TEXT, location TEXT, wbs_label TEXT, wbs_level INTEGER,
                features TEXT DEFAULT '[]', deposit TEXT, heating TEXT,
                score INTEGER DEFAULT 0, trusted_wbs INTEGER DEFAULT 0,
                favorited INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0,
                ts_found REAL
            );
            CREATE INDEX IF NOT EXISTS i1 ON listings(ts_found DESC);
            CREATE INDEX IF NOT EXISTS i2 ON listings(favorited);
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS st (
                id INTEGER PRIMARY KEY CHECK(id=1),
                total INTEGER DEFAULT 0, opens INTEGER DEFAULT 0, last_check REAL
            );
            INSERT OR IGNORE INTO st(id) VALUES(1);
            """)
            c.commit()
        finally:
            c.close()
    log("db ok")

def kv_get(k, d=None):
    try:
        with _DL:
            c = _db()
            try:
                r = c.execute("SELECT value FROM kv WHERE key=?", (k,)).fetchone()
                return json.loads(r[0]) if r else d
            finally:
                c.close()
    except Exception:
        return d

def kv_set(k, v):
    try:
        with _DL:
            c = _db()
            try:
                c.execute("INSERT OR REPLACE INTO kv VALUES(?,?)",
                          (k, json.dumps(v, ensure_ascii=False)))
                c.commit()
            finally:
                c.close()
    except Exception as e:
        log(f"kv_set: {e}")

def save_listing(l):
    lid = l.get("id")
    if not lid:
        return False
    try:
        with _DL:
            c = _db()
            try:
                if c.execute("SELECT 1 FROM listings WHERE id=?", (lid,)).fetchone():
                    return False
                feats = json.dumps(l.get("features") or [], ensure_ascii=False)
                c.execute(
                    "INSERT OR IGNORE INTO listings"
                    "(id,url,source,title,price,rooms,size_m2,floor_,available,"
                    "location,wbs_label,wbs_level,features,deposit,heating,"
                    "score,trusted_wbs,ts_found) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (lid, l.get("url"), l.get("source"), l.get("title"),
                     l.get("price"), l.get("rooms"), l.get("size_m2"),
                     l.get("floor"), l.get("available"), l.get("location"),
                     l.get("wbs_label"), l.get("wbs_level_num"), feats,
                     l.get("deposit"), l.get("heating"),
                     l.get("score", 0), 1 if l.get("trusted_wbs") else 0,
                     time.time()))
                c.execute("UPDATE st SET total=total+1 WHERE id=1")
                c.commit()
                return True
            finally:
                c.close()
    except Exception as e:
        log(f"save: {e}")
        return False

def get_rows(limit=200):
    try:
        with _DL:
            c = _db()
            try:
                rows = c.execute(
                    "SELECT * FROM listings WHERE hidden=0 "
                    "ORDER BY ts_found DESC LIMIT ?", (limit,)).fetchall()
                cols = [d[0] for d in c.description]
                return [dict(zip(cols, r)) for r in rows]
            finally:
                c.close()
    except Exception as e:
        log(f"get_rows: {e}")
        return []

def toggle_fav(lid):
    try:
        with _DL:
            c = _db()
            try:
                r = c.execute("SELECT favorited FROM listings WHERE id=?", (lid,)).fetchone()
                if r:
                    nv = 0 if r[0] else 1
                    c.execute("UPDATE listings SET favorited=? WHERE id=?", (nv, lid))
                    c.commit()
                    return bool(nv)
            finally:
                c.close()
    except Exception as e:
        log(f"fav: {e}")
    return False

def hide_row(lid):
    try:
        with _DL:
            c = _db()
            try:
                c.execute("UPDATE listings SET hidden=1 WHERE id=?", (lid,))
                c.commit()
            finally:
                c.close()
    except Exception as e:
        log(f"hide: {e}")

def get_favs():
    try:
        with _DL:
            c = _db()
            try:
                rows = c.execute(
                    "SELECT * FROM listings WHERE favorited=1 "
                    "ORDER BY ts_found DESC LIMIT 100").fetchall()
                cols = [d[0] for d in c.description]
                return [dict(zip(cols, r)) for r in rows]
            finally:
                c.close()
    except Exception:
        return []

def bump_opens():
    try:
        with _DL:
            c = _db()
            try:
                c.execute("UPDATE st SET opens=opens+1 WHERE id=1")
                c.commit()
            finally:
                c.close()
    except Exception:
        pass

# ── Config ─────────────────────────────────────────────────────────────
DEF = {
    "max_price": 700, "min_price": 0, "min_rooms": 0.0,
    "wbs_only": False, "wbs_level_min": 0, "wbs_level_max": 999,
    "household_size": 1, "jobcenter_mode": False, "wohngeld_mode": False,
    "sources": [], "areas": [], "sort_by": "score",
    "bg_interval": 30, "notifications": True, "accent": "#22C55E",
}

def load_cfg():
    s = kv_get("cfg", {})
    return {**DEF, **(s if isinstance(s, dict) else {})}

def save_cfg(c): kv_set("cfg", c)
def is_first(): return not kv_get("done", False)
def set_done(): kv_set("done", True)

# ── Domain ─────────────────────────────────────────────────────────────
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
GOV = {k for k, v in SOURCES.items() if v[1]}
AREAS = [
    "Mitte", "Spandau", "Pankow", "Neukölln", "Tempelhof", "Schöneberg",
    "Steglitz", "Zehlendorf", "Charlottenburg", "Wilmersdorf", "Lichtenberg",
    "Marzahn", "Hellersdorf", "Treptow", "Köpenick", "Reinickendorf",
    "Friedrichshain", "Kreuzberg", "Prenzlauer Berg", "Wedding", "Moabit",
]
JC = {1:549,2:671,3:789,4:911,5:1021,6:1131}
WG = {1:580,2:680,3:800,4:910,5:1030,6:1150,7:1270}
def jc(n): return JC.get(max(1,min(int(n),6)), JC[6]+(max(1,int(n))-6)*110)
def wg(n): return WG.get(max(1,min(int(n),7)), WG[7]+(max(1,int(n))-7)*120)

FEATS = {
    "balkon":"🌿 بلكونة","terrasse":"🌿 تراس","garten":"🌱 حديقة",
    "aufzug":"🛗 مصعد","einbauküche":"🍳 مطبخ","keller":"📦 مخزن",
    "stellplatz":"🚗 موقف","barrierefrei":"♿","neubau":"🏗 جديد",
    "erstbezug":"✨ أول سكن","fußbodenheizung":"🌡 تدفئة أرضية",
    "fernwärme":"🌡 مركزية","saniert":"🔨 مجدد","waschmaschine":"🫧 غسالة",
    "parkett":"🪵 باركيه","tiefgarage":"🚗 جراج",
}

# ── Network ────────────────────────────────────────────────────────────
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE
_UA = "Mozilla/5.0 (Linux; Android 13) Chrome/124.0"

def _get(url, t=12):
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": _UA, "Accept-Language": "de-DE"})
        with urllib.request.urlopen(req, timeout=t, context=_CTX) as r:
            return r.read().decode(
                r.headers.get_content_charset("utf-8") or "utf-8", "replace")
    except Exception:
        return None

def _getj(url, t=12):
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": _UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=t, context=_CTX) as r:
            return json.loads(r.read())
    except Exception:
        return None

def check_net():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        s.connect(("8.8.8.8", 53))
        s.close()
        return True
    except Exception:
        return False

def make_id(url):
    u = re.sub(r"[?#].*", "", url.strip().rstrip("/"))
    return hashlib.sha256(u.encode()).hexdigest()[:14]

def parse_price(raw):
    if not raw: return None
    s = re.sub(r"[^\d\.,]", "", str(raw))
    if not s: return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif "." in s:
        parts = s.split(".")
        if len(parts) == 2 and len(parts[1]) == 3:
            s = s.replace(".", "")
    try:
        v = float(s)
        return v if 50 < v < 8000 else None
    except Exception:
        return None

def parse_rooms(raw):
    m = re.search(r"(\d+[.,]?\d*)", str(raw or "").replace(",", "."))
    try:
        v = float(m.group(1)) if m else None
        return v if v and 0.5 <= v <= 20 else None
    except Exception:
        return None

def enrich(title, desc):
    t = f"{title} {desc}".lower()
    out = {}
    for pat in [r"(\d[\d\.]*)\s*m[²2]", r"(\d[\d\.]*)\s*qm\b"]:
        m = re.search(pat, t)
        if m:
            try:
                v = float(m.group(1).replace(".", ""))
                if 15 < v < 500:
                    out["size_m2"] = v
                    break
            except Exception:
                pass
    for pat, fn in [
        (r"(\d+)\.\s*(?:og|etage|stock)\b", lambda m: f"T{m.group(1)}"),
        (r"\beg\b(?!\w)|erdgeschoss",        lambda _: "EG"),
        (r"\bdg\b(?!\w)|dachgeschoss",       lambda _: "DG"),
    ]:
        mm = re.search(pat, t)
        if mm:
            out["floor"] = fn(mm)
            break
    mm = re.search(r"wbs[\s\-_]*(\d{2,3})", t)
    if mm:
        out["wbs_level_num"] = int(mm.group(1))
    if any(k in t for k in ["ab sofort", "sofort frei", "sofort verfügbar"]):
        out["available"] = "فوري"
    else:
        m = re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})", t)
        if m:
            out["available"] = m.group(1)
    m = re.search(r"kaution[:\s]*(\d[\d\.,]*)\s*€?", t)
    if m:
        v = parse_price(m.group(1))
        if v:
            out["deposit"] = f"{v:.0f} €"
    seen = set()
    feats = []
    for kw, lb in FEATS.items():
        if kw in t and lb not in seen:
            seen.add(lb)
            feats.append(lb)
    if feats:
        out["features"] = feats
    return out

def _score(l):
    s = 8 if l.get("trusted_wbs") else 0
    s += 3 if l.get("source") in GOV else 0
    p = l.get("price")
    if p:
        s += 10 if p < 400 else 7 if p < 500 else 4 if p < 600 else 1 if p < 700 else 0
    r = l.get("rooms")
    if r:
        s += 5 if r >= 3 else 3 if r >= 2 else 0
    if l.get("size_m2"): s += 2
    if l.get("available") == "فوري": s += 5
    s += min(len(l.get("features") or []), 4)
    return s

# ── Scrapers ───────────────────────────────────────────────────────────
def scrape_gewobag():
    data = _getj("https://www.gewobag.de/wp-json/gewobag/v1/offers"
                 "?type=wohnung&wbs=1&per_page=50")
    if not data: return []
    items = data if isinstance(data, list) else data.get("offers", [])
    result = []; seen = set()
    for i in items:
        url = i.get("link") or i.get("url", "")
        if not url.startswith("http"): url = "https://www.gewobag.de" + url
        if url in seen: continue
        seen.add(url)
        t = i.get("title", "")
        title = t.get("rendered", "") if isinstance(t, dict) else str(t)
        extra = enrich(title, str(i.get("beschreibung") or ""))
        l = {"id": make_id(url), "url": url, "source": "gewobag", "trusted_wbs": True,
             "title": title[:80],
             "price": parse_price(i.get("gesamtmiete") or i.get("warmmiete")),
             "rooms": parse_rooms(i.get("zimmer")),
             "location": i.get("bezirk", "Berlin"),
             "wbs_label": "WBS", "ts": time.time(), **extra}
        l["score"] = _score(l); result.append(l)
    return result

def scrape_degewo():
    for api in [
        "https://immosuche.degewo.de/de/properties.json"
        "?property_type_id=1&categories[]=WBS&per_page=50",
        "https://immosuche.degewo.de/de/search.json?asset_classes[]=1&wbs=1",
    ]:
        data = _getj(api)
        if not data: continue
        items = data if isinstance(data, list) else data.get("results", [])
        result = []; seen = set()
        for i in items:
            url = i.get("path", "") or i.get("url", "")
            if not url.startswith("http"): url = "https://immosuche.degewo.de" + url
            if url in seen: continue
            seen.add(url)
            extra = enrich(i.get("title", ""), str(i.get("text") or ""))
            l = {"id": make_id(url), "url": url, "source": "degewo", "trusted_wbs": True,
                 "title": i.get("title", "")[:80],
                 "price": parse_price(i.get("warmmiete") or i.get("totalRent")),
                 "rooms": parse_rooms(i.get("zimmer")),
                 "location": i.get("district", "Berlin"),
                 "wbs_label": "WBS", "ts": time.time(), **extra}
            l["score"] = _score(l); result.append(l)
        if result: return result
    return []

def scrape_howoge():
    data = _getj("https://www.howoge.de/api/v2/immobilien/suche"
                 "?typ=wohnung&wbs=ja&von=0&groesse=50")
    if not data: return []
    items = data if isinstance(data, list) else data.get("treffer", data.get("items", []))
    result = []; seen = set()
    for i in items:
        url = i.get("url") or i.get("link", "")
        if not url: continue
        if not url.startswith("http"): url = "https://www.howoge.de" + url
        if url in seen: continue
        seen.add(url)
        extra = enrich(i.get("bezeichnung", ""), str(i.get("beschreibung") or ""))
        l = {"id": make_id(url), "url": url, "source": "howoge", "trusted_wbs": True,
             "title": i.get("bezeichnung", "")[:80],
             "price": parse_price(i.get("gesamtmiete") or i.get("miete")),
             "rooms": parse_rooms(i.get("zimmer")),
             "location": i.get("bezirk", "Berlin"),
             "wbs_label": "WBS", "ts": time.time(), **extra}
        l["score"] = _score(l); result.append(l)
    return result

def scrape_wbm():
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    html = _get("https://www.wbm.de/wohnungen-berlin/angebote/")
    if not html: return []
    soup = BeautifulSoup(html, "html.parser")
    result = []; seen = set()
    for card in soup.select(".openimmo-search-list-item, article.listing-item")[:20]:
        a = card.select_one("a[href]")
        if not a: continue
        href = a.get("href", "")
        url = href if href.startswith("http") else "https://www.wbm.de" + href
        if url in seen: continue
        seen.add(url)
        title = (card.select_one("h2,h3,.title") or a).get_text(strip=True)[:80]
        p_tag = card.select_one(".price,.miete,[class*=price]")
        extra = enrich(title, card.get_text(" ", strip=True))
        l = {"id": make_id(url), "url": url, "source": "wbm", "trusted_wbs": True,
             "title": title, "price": parse_price(p_tag.get_text() if p_tag else None),
             "rooms": None, "location": "Berlin", "wbs_label": "WBS",
             "ts": time.time(), **extra}
        l["score"] = _score(l); result.append(l)
    return result

# FIX: fetch_all now includes ALL configured scrapers (was only gewobag+degewo)
_SCRAPERS = {
    "gewobag":  scrape_gewobag,
    "degewo":   scrape_degewo,
    "howoge":   scrape_howoge,
    "wbm":      scrape_wbm,
}

def fetch_all(cfg=None):
    log("fetch_all")
    enabled = (cfg or {}).get("sources") or list(SOURCES.keys())
    results = []; lock = threading.Lock()

    def run(src, fn):
        try:
            items = fn()
            with lock:
                results.extend(items)
            log(f"  {src}: {len(items)}")
        except Exception as e:
            log(f"  {src} err: {e}")

    threads = []
    for src in enabled:
        fn = _SCRAPERS.get(src)
        if fn:
            t = threading.Thread(target=run, args=(src, fn), daemon=True)
            threads.append(t); t.start()
    deadline = time.time() + 25
    for t in threads:
        t.join(timeout=max(0.1, deadline - time.time()))
    seen_ids = set(); unique = []
    for l in results:
        if l.get("id") and l["id"] not in seen_ids:
            seen_ids.add(l["id"]); unique.append(l)
    log(f"fetch done: {len(unique)}")
    return unique

def apply_filters(listings, cfg):
    out = []
    max_p = float(cfg.get("max_price") or 9999)
    min_p = float(cfg.get("min_price") or 0)
    min_r = float(cfg.get("min_rooms") or 0)
    wbs   = bool(cfg.get("wbs_only"))
    wlmin = int(cfg.get("wbs_level_min") or 0)
    wlmax = int(cfg.get("wbs_level_max") or 999)
    jcm   = bool(cfg.get("jobcenter_mode"))
    wgm   = bool(cfg.get("wohngeld_mode"))
    n     = max(1, int(cfg.get("household_size") or 1))
    areas = [a.lower() for a in (cfg.get("areas") or [])]
    srcs  = cfg.get("sources") or []
    for l in listings:
        if not l.get("id") or l.get("hidden"): continue
        if srcs and l.get("source") not in srcs: continue
        price = l.get("price"); rooms = l.get("rooms")
        if price is not None:
            if min_p > 0 and price < min_p: continue
            if price > max_p: continue
        if rooms is not None and min_r > 0 and rooms < min_r: continue
        if wbs and not l.get("trusted_wbs"): continue
        level = l.get("wbs_level") or l.get("wbs_level_num")
        if level is not None and (wlmin > 0 or wlmax < 999):
            if not (wlmin <= level <= wlmax): continue
        if areas:
            loc = (l.get("location", "") + " " + l.get("title", "")).lower()
            if not any(a in loc for a in areas): continue
        if jcm or wgm:
            j_ok = (price is None or price <= jc(n)) if jcm else False
            w_ok = (price is None or price <= wg(n)) if wgm else False
            if not (j_ok or w_ok): continue
        out.append(l)
    return out

def sort_it(listings, sort_by):
    if sort_by == "price_asc":
        return sorted(listings, key=lambda l: l.get("price") or 9999)
    if sort_by == "price_desc":
        return sorted(listings, key=lambda l: -(l.get("price") or 0))
    if sort_by == "newest":
        return sorted(listings, key=lambda l: -(l.get("ts_found") or l.get("ts") or 0))
    return sorted(listings, key=lambda l: -(l.get("score") or 0))

# ── Background ─────────────────────────────────────────────────────────
_bg_stop = threading.Event()
_bg_th = None

def _bgw():
    time.sleep(15)
    while not _bg_stop.is_set():
        try:
            cfg = load_cfg()
            if check_net():
                raw = fetch_all(cfg)
                for l in raw:
                    save_listing(l)
            with _DL:
                c = _db()
                try:
                    c.execute("UPDATE st SET last_check=? WHERE id=1", (time.time(),))
                    c.commit()
                finally:
                    c.close()
        except Exception as e:
            log(f"bg: {e}")
        interval = max(5, int(load_cfg().get("bg_interval", 30))) * 60
        _bg_stop.wait(timeout=interval)

def start_bg():
    global _bg_th, _bg_stop
    if _bg_th and _bg_th.is_alive(): return
    _bg_stop.clear()
    _bg_th = threading.Thread(target=_bgw, daemon=True, name="WBSBg")
    _bg_th.start()
    log("bg started")

def stop_bg(): _bg_stop.set()
def is_bg(): return bool(_bg_th and _bg_th.is_alive())

# ══════════════════════════════════════════════════════════════════════
# Kivy UI
# ══════════════════════════════════════════════════════════════════════
log("importing kivy...")
try:
    import kivy
    kivy.require("2.0.0")
    from kivy.config import Config
    Config.set("kivy", "log_level", "error")
    from kivy.app import App
    from kivy.uix.screenmanager import ScreenManager, Screen, NoTransition
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
    HAS_KIVY = True
    log("kivy ok")
except Exception as e:
    import traceback
    log(f"kivy FAILED: {e}\n{traceback.format_exc()}")
    HAS_KIVY = False

if HAS_KIVY:
    BG  = get_color_from_hex("#0A0A0A"); BG2 = get_color_from_hex("#141414")
    BG3 = get_color_from_hex("#1E1E1E"); GRN = get_color_from_hex("#22C55E")
    PUR = get_color_from_hex("#8B5CF6"); BLU = get_color_from_hex("#3B82F6")
    AMB = get_color_from_hex("#F59E0B"); RED = get_color_from_hex("#EF4444")
    TX1 = get_color_from_hex("#F1F5F9"); TX2 = get_color_from_hex("#94A3B8")
    TX3 = get_color_from_hex("#475569"); DIV = get_color_from_hex("#1E293B")
    WH  = (1,1,1,1); NO = (0,0,0,0)
    _AC = list(GRN); _FN = ["Roboto"]; _FS = [1.0]

    def AC(): return tuple(_AC)
    def FN(): return _FN[0]
    def fs(n): return sp(n * _FS[0])

    def bg(w, col, r=0):
        w.canvas.before.clear()
        with w.canvas.before:
            Color(*col)
            rect = (RoundedRectangle(pos=w.pos, size=w.size, radius=[dp(r)])
                    if r else Rectangle(pos=w.pos, size=w.size))
        def u(*_): rect.pos=w.pos; rect.size=w.size
        w.bind(pos=u, size=u)

    def lb(text, sz=14, col=None, bold=False, align="right", **kw):
        col = col or TX1
        try: txt = ar(str(text or ""))
        except Exception: txt = str(text or "")
        w = Label(text=txt, font_size=fs(sz), color=col,
                  bold=bold, halign=align, font_name=FN(), **kw)
        w.bind(width=lambda *_: setattr(w, "text_size", (w.width, None)))
        return w

    def bt(text, cb=None, col=None, tc=None, h=48, r=12, **kw):
        col = col or AC(); tc = tc or WH
        try: txt = ar(str(text or ""))
        except Exception: txt = str(text or "")
        b = Button(text=txt, size_hint_y=None, height=dp(h),
                   background_color=NO, color=tc,
                   font_size=fs(14), bold=True, font_name=FN(), **kw)
        bg(b, col, r=r)
        if cb: b.bind(on_press=cb)
        return b

    def gp(h=10): return Widget(size_hint_y=None, height=dp(h))
    def dv():
        w = Widget(size_hint_y=None, height=dp(1)); bg(w, DIV); return w

    def inp(val, filt="int"):
        t = TextInput(text=str(val), input_filter=filt, multiline=False,
                      background_color=NO, foreground_color=TX1,
                      cursor_color=AC(), font_size=fs(14))
        bg(t, BG3, r=10); return t

    def si(t, d=0):
        try: return int(float(t.text or d))
        except Exception: return d

    def sf(t, d=0.0):
        try: return float(t.text or d)
        except Exception: return d

    def navbar(app, active):
        TABS = [("🏠","main","الرئيسية"),("⭐","favs","المفضلة"),("⚙️","cfg","إعدادات")]
        bar = BoxLayout(size_hint_y=None, height=dp(56))
        bg(bar, BG2)
        for icon, name, lbl_t in TABS:
            on = name == active
            try: txt = f"{icon}\n{ar(lbl_t)}"
            except Exception: txt = f"{icon}\n{lbl_t}"
            b = Button(text=txt, background_color=NO,
                       color=AC() if on else TX3,
                       font_size=fs(10 if not on else 11), bold=on, font_name=FN())
            bg(b, (*AC()[:3], 0.12) if on else BG2)
            n = name
            b.bind(on_press=lambda _, n=n: setattr(app.sm, "current", n))
            bar.add_widget(b)
        return bar

    class Card(BoxLayout):
        def __init__(self, l, **kw):
            super().__init__(orientation="vertical", size_hint_y=None,
                             padding=(dp(12), dp(10)), spacing=dp(5), **kw)
            name, gov = SOURCES.get(l.get("source", ""), ("?", False))
            sc = PUR if gov else BLU; is_fav = bool(l.get("favorited"))
            price = l.get("price"); rooms = l.get("rooms"); sz = l.get("size_m2")
            avail = l.get("available", "")
            try:
                feats = (json.loads(l["features"]) if isinstance(l.get("features"), str)
                         else (l.get("features") or []))
            except Exception:
                feats = []
            feats = feats[:4]
            title = (l.get("title") or "شقة").strip()[:60]
            wlnum = l.get("wbs_level") or l.get("wbs_level_num")
            wlbl = f"WBS {wlnum}" if wlnum else ("WBS ✓" if l.get("trusted_wbs") else "")
            self.url = l.get("url", ""); self.lid = l.get("id", "")
            n_fr = max(1, (len(feats)+2)//3) if feats else 0
            self.height = dp(155 + n_fr*20)
            bg(self, BG2, r=14)

            r1 = BoxLayout(size_hint_y=None, height=dp(24), spacing=dp(6))
            ch = BoxLayout(size_hint=(None,None), size=(dp(104),dp(20)), padding=(dp(5),0))
            bg(ch, (*sc[:3],0.18), r=10)
            ch.add_widget(lb(("🏛 " if gov else "🔍 ")+ar(name), sz=10, col=sc,
                              size_hint_y=None, height=dp(20)))
            r1.add_widget(ch); r1.add_widget(Widget())
            if wlbl:
                wb = BoxLayout(size_hint=(None,None), size=(dp(68),dp(20)), padding=(dp(5),0))
                bg(wb, (*AC()[:3],0.18), r=10)
                wb.add_widget(lb(wlbl, sz=10, col=AC(), bold=True,
                                  size_hint_y=None, height=dp(20)))
                r1.add_widget(wb)
            self._fb = Button(text="★" if is_fav else "☆",
                              size_hint=(None,None), size=(dp(26),dp(22)),
                              background_color=NO, color=AMB if is_fav else TX3, font_size=sp(15))
            self._fb.bind(on_press=self._fav); r1.add_widget(self._fb)
            self.add_widget(r1)
            self.add_widget(lb(title, sz=12, bold=True, size_hint_y=None, height=dp(20)))

            r3 = BoxLayout(size_hint_y=None, height=dp(17))
            r3.add_widget(lb("📍 "+ar(l.get("location","Berlin")), sz=10, col=TX2))
            if avail:
                r3.add_widget(lb("📅 "+ar("فوري 🔥" if avail=="فوري" else avail),
                                  sz=10, col=AMB if avail=="فوري" else TX2))
            self.add_widget(r3); self.add_widget(dv())

            r4 = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(5))
            if price:
                ppm = f" ({price/sz:.1f}€/m²)" if sz else ""
                p2 = BoxLayout(size_hint=(None,None), size=(dp(104),dp(26)), padding=(dp(5),0))
                bg(p2, (*AC()[:3],0.15), r=8)
                p2.add_widget(lb(f"💰 {price:.0f}€{ppm}", sz=11, col=AC(),
                                  bold=True, size_hint_y=None, height=dp(26)))
                r4.add_widget(p2)
            if rooms: r4.add_widget(lb(f"🛏 {rooms:.0f}", sz=11, col=TX1))
            if sz:    r4.add_widget(lb(f"📐 {sz:.0f}m²", sz=11, col=TX1))
            self.add_widget(r4)

            if feats:
                fg = GridLayout(cols=3, size_hint_y=None, height=dp(n_fr*20), spacing=dp(3))
                for f in feats:
                    c = BoxLayout(size_hint_y=None, height=dp(18), padding=(dp(4),0))
                    bg(c, BG3, r=6)
                    c.add_widget(lb(ar(f), sz=9, col=TX2, size_hint_y=None, height=dp(18)))
                    fg.add_widget(c)
                self.add_widget(fg)

            ab = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(6))
            ab.add_widget(bt("فتح ←", cb=self._open, h=30, r=8))
            ab.add_widget(bt("إخفاء", cb=self._hide, col=BG3, tc=TX2, h=30, r=8,
                              size_hint_x=None, width=dp(70)))
            self.add_widget(ab)

        def _fav(self, *_):
            if not self.lid: return
            nv = toggle_fav(self.lid)
            self._fb.color = AMB if nv else TX3
            self._fb.text = "★" if nv else "☆"

        def _hide(self, *_):
            if self.lid: hide_row(self.lid)
            self.opacity = 0; self.height = 0

        def _open(self, *_):
            if not self.url: return
            log(f"open: {self.url}")
            try:
                from jnius import autoclass
                I  = autoclass("android.content.Intent")
                U  = autoclass("android.net.Uri")
                PA = autoclass("org.kivy.android.PythonActivity")
                PA.mActivity.startActivity(I(I.ACTION_VIEW, U.parse(self.url)))
            except Exception:
                try:
                    from kivy.core.clipboard import Clipboard
                    Clipboard.copy(self.url)
                except Exception:
                    pass

    class MainScreen(Screen):
        def __init__(self, app, **kw):
            super().__init__(name="main", **kw)
            self.app = app; self._lock = threading.RLock()
            self._busy = False; self._raw = []
            bg(self, BG); self._ui()

        def _ui(self):
            cfg = load_cfg(); root = BoxLayout(orientation="vertical")
            bar = BoxLayout(size_hint_y=None, height=dp(54),
                             padding=(dp(12),dp(8)), spacing=dp(8))
            bg(bar, BG2)
            bar.add_widget(lb("🏠 WBS برلين", sz=15, bold=True, col=WH, size_hint_x=0.45))
            bar.add_widget(Widget())
            bar.add_widget(bt("⚙️", cb=lambda *_: setattr(self.app.sm,"current","cfg"),
                               col=BG3, tc=TX2, size_hint_x=None, h=38, width=dp(42)))
            self._rb = bt("🔄", cb=self._go, col=AC(), size_hint_x=None, h=38, width=dp(42))
            bar.add_widget(self._rb); root.add_widget(bar)

            chips = BoxLayout(size_hint_y=None, height=dp(40),
                               padding=(dp(10),dp(5)), spacing=dp(8))
            bg(chips, BG2)
            self._wc = ToggleButton(
                text=ar("WBS فقط"),
                state="down" if cfg.get("wbs_only") else "normal",
                size_hint=(None,None), size=(dp(86),dp(26)),
                background_color=NO, color=TX1, font_size=fs(11), font_name=FN())
            self._uc(); self._wc.bind(state=self._wbs); chips.add_widget(self._wc)
            self._st = lb("اضغط 🔄", sz=11, col=TX2, size_hint_y=None, height=dp(26))
            chips.add_widget(self._st)
            self._bgi = Label(text="⏸", font_size=sp(13), color=TX3,
                               size_hint=(None,None), size=(dp(24),dp(26)))
            chips.add_widget(self._bgi)
            root.add_widget(chips); root.add_widget(dv())

            self._cl = BoxLayout(orientation="vertical", spacing=dp(8),
                                  padding=(dp(10),dp(8)), size_hint_y=None)
            self._cl.bind(minimum_height=self._cl.setter("height"))
            sv = ScrollView(bar_color=(*AC()[:3],0.4)); sv.add_widget(self._cl)
            root.add_widget(sv); root.add_widget(navbar(self.app,"main"))
            self.add_widget(root); self._ph("🔍", ar("اضغط 🔄 للبحث"))

        def on_enter(self, *_): Clock.schedule_interval(self._tick, 10)
        def on_leave(self, *_): Clock.unschedule(self._tick)

        def _tick(self, *_):
            try:
                self._bgi.text = "🟢" if is_bg() else "⏸"
                self._bgi.color = AC() if is_bg() else TX3
            except Exception: pass

        def _uc(self):
            on = self._wc.state == "down"
            bg(self._wc, (*AC()[:3],0.85) if on else BG3, r=13)

        def _wbs(self, _, s):
            self._uc(); cfg = load_cfg(); cfg["wbs_only"] = s=="down"; save_cfg(cfg)
            with self._lock: raw = list(self._raw)
            if raw:
                shown = sort_it(apply_filters(raw, cfg), cfg.get("sort_by","score"))
                Clock.schedule_once(lambda dt: self._render(shown, len(raw)))

        def _ph(self, icon, msg):
            self._cl.clear_widgets()
            b = BoxLayout(orientation="vertical", spacing=dp(8),
                          size_hint_y=None, height=dp(160), padding=dp(28))
            b.add_widget(Label(text=icon, font_size=sp(44), size_hint_y=None, height=dp(55)))
            b.add_widget(lb(msg, sz=13, col=TX2, size_hint_y=None, height=dp(40)))
            self._cl.add_widget(b)

        def _go(self, *_):
            with self._lock:
                if self._busy: return
                self._busy = True
            if not check_net():
                cached = get_rows()
                with self._lock: self._busy = False
                if cached:
                    self._st.text = ar("📦 من القاعدة")
                    with self._lock: self._raw = cached
                    cfg = load_cfg()
                    shown = sort_it(apply_filters(cached,cfg), cfg.get("sort_by","score"))
                    Clock.schedule_once(lambda dt: self._render(shown, len(cached)))
                else:
                    self._ph("📵", ar("لا يوجد اتصال"))
                return
            self._st.text = ar("⏳ جاري البحث...")
            self._ph("⏳", ar("جاري الجلب..."))
            threading.Thread(target=self._fetch, daemon=True).start()

        def _fetch(self):
            try:
                cfg = load_cfg(); raw = fetch_all(cfg)
                nc = sum(1 for l in raw if save_listing(l))
                all_db = get_rows()
                with self._lock: self._raw = all_db
                shown = sort_it(apply_filters(all_db,cfg), cfg.get("sort_by","score"))
                Clock.schedule_once(lambda dt: self._render(shown, len(all_db), nc))
            except Exception as e:
                log(f"_fetch: {e}")
                Clock.schedule_once(lambda dt: self._ph("⚠️", ar(f"خطأ: {str(e)[:40]}")))
            finally:
                with self._lock: self._busy = False

        def _render(self, lst, total=None, nc=0):
            try:
                self._cl.clear_widgets()
                t = total if total is not None else len(lst)
                if not lst:
                    self._st.text = ar(f"لا إعلانات ({t})")
                    self._ph("🔍", ar("لا توجد إعلانات")); return
                ns = f" (+{nc})" if nc else ""
                self._st.text = ar(f"✅ {len(lst)} من {t}{ns}")
                for l in lst[:10]:
                    self._cl.add_widget(Card(l)); self._cl.add_widget(gp(6))
                if len(lst) > 10:
                    Clock.schedule_once(lambda dt: self._rest(lst[10:]), 0.1)
            except Exception as e:
                log(f"_render: {e}")

        def _rest(self, rest):
            try:
                for l in rest[:50]:
                    self._cl.add_widget(Card(l)); self._cl.add_widget(gp(6))
            except Exception: pass

    class FavsScreen(Screen):
        def __init__(self, app, **kw):
            super().__init__(name="favs", **kw)
            self.app = app; bg(self, BG); self._build()

        def _build(self):
            self.clear_widgets(); root = BoxLayout(orientation="vertical")
            bar = BoxLayout(size_hint_y=None, height=dp(54), padding=(dp(12),dp(8)))
            bg(bar, BG2)
            bar.add_widget(lb("⭐ "+ar("المفضلة"), sz=15, bold=True, col=AMB))
            bar.add_widget(bt("🔄", cb=self._load, col=BG3, tc=TX2,
                               size_hint_x=None, h=38, width=dp(42)))
            root.add_widget(bar)
            self._cl = BoxLayout(orientation="vertical", spacing=dp(8),
                                  padding=(dp(10),dp(8)), size_hint_y=None)
            self._cl.bind(minimum_height=self._cl.setter("height"))
            sv = ScrollView(bar_color=(*AMB[:3],0.4)); sv.add_widget(self._cl)
            root.add_widget(sv); root.add_widget(navbar(self.app,"favs"))
            self.add_widget(root); self._load()

        def on_enter(self, *_): self._load()

        def _load(self, *_):
            self._cl.clear_widgets()
            favs = get_favs()
            if not favs:
                b = BoxLayout(orientation="vertical", size_hint_y=None,
                              height=dp(140), padding=dp(28))
                b.add_widget(Label(text="⭐", font_size=sp(44), size_hint_y=None, height=dp(55)))
                b.add_widget(lb("لا توجد مفضلة", sz=13, col=TX2, size_hint_y=None, height=dp(36)))
                self._cl.add_widget(b); return
            for l in favs:
                self._cl.add_widget(Card(l)); self._cl.add_widget(gp(6))

    class CfgScreen(Screen):
        def __init__(self, app, **kw):
            super().__init__(name="cfg", **kw)
            self.app = app; bg(self, BG); self._build()

        def _build(self):
            self.clear_widgets(); cfg = load_cfg(); root = BoxLayout(orientation="vertical")
            hdr = BoxLayout(size_hint_y=None, height=dp(54),
                             padding=(dp(12),dp(8)), spacing=dp(10))
            bg(hdr, BG2)
            hdr.add_widget(lb("⚙️ "+ar("الإعدادات"), sz=15, bold=True, col=WH))
            hdr.add_widget(bt("↩️", cb=self._reset, col=BG3, tc=TX2,
                               size_hint_x=None, h=38, width=dp(46)))
            root.add_widget(hdr)
            sc = ScrollView()
            body = BoxLayout(orientation="vertical", padding=dp(14),
                              spacing=dp(8), size_hint_y=None)
            body.bind(minimum_height=body.setter("height"))

            def row(lbl_t, w, hint=""):
                r = BoxLayout(size_hint_y=None, height=dp(52),
                               spacing=dp(12), padding=(dp(12),dp(4)))
                bg(r, BG2, r=12)
                lb2 = BoxLayout(orientation="vertical", size_hint_x=0.45)
                lb2.add_widget(lb(lbl_t, sz=12, col=TX1))
                if hint: lb2.add_widget(lb(hint, sz=10, col=TX3))
                r.add_widget(lb2); r.add_widget(w); body.add_widget(r)

            def tog(text, active, pri=None):
                pri = pri or AC()
                t = ToggleButton(text=ar(text), state="down" if active else "normal",
                                  size_hint=(1,None), height=dp(42),
                                  background_color=NO, color=TX1,
                                  font_size=fs(12), font_name=FN())
                bg(t, (*pri[:3],0.15) if active else BG2, r=12)
                t.bind(state=lambda b,s,p=pri: bg(b, (*p[:3],0.15) if s=="down" else BG2, r=12))
                body.add_widget(t); return t

            self._maxp = inp(cfg.get("max_price",700)); row("أقصى إيجار (€)", self._maxp)
            self._minp = inp(cfg.get("min_price",0)); row("الحد الأدنى (€)", self._minp, "0=بدون")
            self._minr = inp(cfg.get("min_rooms",0),"float"); row("أقل غرف", self._minr, "0=أي")
            self._wbs = tog("WBS فقط", cfg.get("wbs_only",False))

            wlr = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(6), padding=(dp(12),dp(4)))
            bg(wlr, BG2, r=12)
            wlr.add_widget(lb("مستوى WBS:", sz=12, col=TX1, size_hint_x=0.32))
            self._wlmin = inp(cfg.get("wbs_level_min",0))
            self._wlmax = inp(cfg.get("wbs_level_max",999))
            wlr.add_widget(lb("من", sz=11, col=TX2, size_hint_x=0.08))
            wlr.add_widget(self._wlmin)
            wlr.add_widget(lb("—", sz=12, col=TX2, size_hint_x=0.06))
            wlr.add_widget(self._wlmax)
            body.add_widget(wlr)

            pr = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(6))
            for lt,mn,mx in [("100","100","100"),("100-140","100","140"),("كل","0","999")]:
                b = bt(lt, col=BG3, tc=TX1, h=36, r=10, size_hint_x=None, width=dp(80))
                b.bind(on_press=lambda _,mn=mn,mx=mx: (
                    setattr(self._wlmin,"text",mn), setattr(self._wlmax,"text",mx)))
                pr.add_widget(b)
            body.add_widget(pr)

            self._hh = inp(cfg.get("household_size",1))
            n_ = max(1, int(cfg.get("household_size") or 1))
            row("أفراد الأسرة", self._hh, f"JC≤{jc(n_):.0f}€")
            self._jc = tog("Jobcenter KdU", cfg.get("jobcenter_mode",False), PUR)
            self._wg = tog("Wohngeld", cfg.get("wohngeld_mode",False), PUR)

            cur_ar = cfg.get("areas") or []; self._ab = {}
            ag = GridLayout(cols=2, size_hint_y=None,
                             height=dp(((len(AREAS)+1)//2)*36), spacing=dp(4))
            for area in AREAS:
                on = area in cur_ar
                b = ToggleButton(text=area, state="down" if on else "normal",
                                  size_hint=(1,None), height=dp(34),
                                  background_color=NO, color=TX1, font_size=fs(11))
                bg(b, (*AMB[:3],0.15) if on else BG2, r=8)
                b.bind(state=lambda x,s,b=b: bg(b, (*AMB[:3],0.15) if s=="down" else BG2, r=8))
                self._ab[area] = b; ag.add_widget(b)
            body.add_widget(ag)
            body.add_widget(bt("🌍 "+ar("كل برلين"),
                                cb=lambda *_: [setattr(b,"state","normal") or bg(b,BG2,r=8)
                                               for b in self._ab.values()],
                                col=BG3, tc=TX2, h=34, r=10))

            cur_src = cfg.get("sources") or []; self._src = {}
            for sid,(sname,gov) in SOURCES.items():
                sc = PUR if gov else BLU; on = not cur_src or sid in cur_src
                b = ToggleButton(text=("🏛 " if gov else "🔍 ")+ar(sname),
                                  state="down" if on else "normal",
                                  size_hint=(1,None), height=dp(40),
                                  background_color=NO, color=TX1, font_size=fs(12))
                bg(b, (*sc[:3],0.15) if on else BG2, r=10)
                b.bind(state=lambda x,s,sc=sc,b=b: bg(b, (*sc[:3],0.15) if s=="down" else BG2, r=10))
                self._src[sid] = b; body.add_widget(b)

            qr = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(8))
            qr.add_widget(bt("✅ "+ar("الكل"),
                              cb=lambda *_: [setattr(b,"state","down") for b in self._src.values()],
                              col=BG3, tc=TX1, h=36, r=10))
            qr.add_widget(bt("🏛 "+ar("حكومية"), cb=self._govsrc,
                               col=(*PUR[:3],1), h=36, r=10))
            body.add_widget(qr)

            self._bgi2 = inp(cfg.get("bg_interval",30))
            row("فترة الخلفية (دق.)", self._bgi2, "5+")
            bg_on = is_bg()
            self._bgb = bt(
                "⏹ "+ar("إيقاف الخلفية") if bg_on else "▶ "+ar("تشغيل الخلفية"),
                cb=self._togbg, col=RED if bg_on else AC(), h=42, r=12)
            body.add_widget(gp(6)); body.add_widget(self._bgb); body.add_widget(gp(8))
            body.add_widget(bt("💾 "+ar("حفظ"), cb=self._save, h=50, r=14))
            body.add_widget(gp(20))
            sc.add_widget(body); root.add_widget(sc)
            root.add_widget(navbar(self.app,"cfg")); self.add_widget(root)

        def _govsrc(self, *_):
            for sid,b in self._src.items():
                gov = SOURCES[sid][1]; sc = PUR if gov else BLU
                b.state = "down" if gov else "normal"
                bg(b, (*sc[:3],0.15) if gov else BG2, r=10)

        def _togbg(self, *_):
            if is_bg():
                stop_bg(); bg(self._bgb, AC(), r=12)
                self._bgb.text = ar("▶ تشغيل الخلفية")
            else:
                start_bg(); bg(self._bgb, RED, r=12)
                self._bgb.text = ar("⏹ إيقاف الخلفية")

        def _reset(self, *_):
            save_cfg(dict(DEF)); self._build()

        def _save(self, *_):
            sel_src = [s for s,b in self._src.items() if b.state=="down"]
            sel_ar  = [a for a,b in self._ab.items()  if b.state=="down"]
            cfg = load_cfg()
            cfg.update({
                "max_price":      si(self._maxp, 700),
                "min_price":      si(self._minp, 0),
                "min_rooms":      sf(self._minr, 0),
                "household_size": max(1, si(self._hh, 1)),
                "wbs_only":       self._wbs.state == "down",
                "wbs_level_min":  si(self._wlmin, 0),
                "wbs_level_max":  si(self._wlmax, 999),
                "jobcenter_mode": self._jc.state == "down",
                "wohngeld_mode":  self._wg.state == "down",
                "areas":   sel_ar,
                "sources": sel_src if len(sel_src) < len(SOURCES) else [],
                "bg_interval": max(5, si(self._bgi2, 30)),
            })
            save_cfg(cfg); self.app.sm.current = "main"

    class SplashScreen(Screen):
        def __init__(self, **kw):
            super().__init__(name="splash", **kw); bg(self, BG)
            root = FloatLayout()
            card = BoxLayout(orientation="vertical", padding=dp(28), spacing=dp(14),
                             size_hint=(0.78,0.46), pos_hint={"center_x":.5,"center_y":.5})
            bg(card, BG2, r=18)
            card.add_widget(Label(text="🏠", font_size=sp(56), size_hint_y=None, height=dp(70)))
            card.add_widget(lb("WBS Berlin", sz=19, bold=True, col=GRN,
                                size_hint_y=None, height=dp(38)))
            card.add_widget(lb("جاري التحميل...", sz=13, col=TX2,
                                size_hint_y=None, height=dp(28)))
            root.add_widget(card); self.add_widget(root)

    class OnboardScreen(Screen):
        def __init__(self, app, **kw):
            super().__init__(name="onboard", **kw)
            self.app = app; self._i = 0; self._show()

        def _show(self):
            self.clear_widgets(); bg(self, BG)
            PGS = [
                ("🏠","WBS Berlin","ابحث عن شقتك المدعومة\nمن مصادر رسمية وخاصة",GRN),
                ("🗄","قاعدة بيانات","لا تكرار للإعلانات أبداً",PUR),
                ("🔔","إشعارات فورية","يعمل في الخلفية دائماً",AMB),
            ]
            p = PGS[self._i]; last = self._i == 2
            root = FloatLayout()
            card = BoxLayout(orientation="vertical", padding=dp(28), spacing=dp(14),
                             size_hint=(0.86,0.62), pos_hint={"center_x":.5,"center_y":.57})
            bg(card, BG2, r=18)
            card.add_widget(Label(text=p[0], font_size=sp(56), size_hint_y=None, height=dp(72)))
            card.add_widget(lb(p[1], sz=18, bold=True, col=p[3], size_hint_y=None, height=dp(42)))
            card.add_widget(lb(p[2], sz=13, col=TX2, size_hint_y=None, height=dp(52)))
            root.add_widget(card)
            brow = BoxLayout(size_hint=(0.86,None), height=dp(50),
                             pos_hint={"center_x":.5,"y":.05}, spacing=dp(12))
            if not last: brow.add_widget(bt("تخطي", cb=self._done, col=BG3, tc=TX2))
            brow.add_widget(bt("ابدأ 🚀" if last else "التالي ←",
                                cb=self._next if not last else self._done, col=p[3]))
            root.add_widget(brow); self.add_widget(root)

        def _next(self, *_): self._i = min(self._i+1, 2); self._show()
        def _done(self, *_): set_done(); self.app.go_main()

    class WBSApp(App):
        def build(self):
            log("build() start")
            Window.clearcolor = BG
            self.sm = ScreenManager(transition=NoTransition())
            self.sm.add_widget(SplashScreen())
            self.sm.current = "splash"
            Clock.schedule_once(self._init, 0.2)
            log("build() done")
            return self.sm

        def _init(self, dt):
            log("_init")
            try:
                # Arabic
                _init_arabic()
                # Font
                try:
                    fp = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                      "NotoNaskhArabic.ttf")
                    if os.path.exists(fp):
                        LabelBase.register("NotoArabic", fn_regular=fp)
                        _FN[0] = "NotoArabic"
                        log("font registered")
                    else:
                        log(f"font missing: {fp}")
                except Exception as e:
                    log(f"font: {e}")
                # Accent colour
                try:
                    c = get_color_from_hex(load_cfg().get("accent","#22C55E"))
                    _AC[:] = list(c)
                except Exception:
                    pass
                # Open count
                bump_opens()
            except Exception as e:
                log(f"_init err: {e}")
            Clock.schedule_once(self._show_main, 0.3)

        def _show_main(self, dt):
            log("_show_main")
            try:
                if is_first():
                    self.sm.add_widget(OnboardScreen(self))
                    self.sm.current = "onboard"
                else:
                    self.go_main()
                Clock.schedule_once(lambda _: start_bg(), 5.0)
                log("_show_main done")
            except Exception as e:
                log(f"_show_main err: {e}")
                import traceback; log(traceback.format_exc())
                try:
                    self.sm.add_widget(MainScreen(self))
                    self.sm.current = "main"
                except Exception as e2:
                    log(f"FATAL: {e2}")

        def go_main(self):
            for name,cls in [("main",MainScreen),("favs",FavsScreen),("cfg",CfgScreen)]:
                if not any(s.name==name for s in self.sm.screens):
                    self.sm.add_widget(cls(self))
            self.sm.current = "main"

    if __name__ == "__main__":
        log("run() start")
        try:
            init_db(); WBSApp().run()
        except Exception as e:
            log(f"run() crashed: {e}")
            import traceback; log(traceback.format_exc()); raise

else:
    if __name__ == "__main__":
        print("CLI mode"); init_db()
        raw = fetch_all()
        cfg = dict(DEF)
        shown = sort_it(apply_filters(raw, cfg), "score")
        print(f"Results: {len(shown)}/{len(raw)}")
        for l in shown[:3]:
            p = f"{l['price']:.0f}€" if l.get("price") else "—"
            print(f"  [{l['source']}] {p} | {l.get('title','')[:45]}")
