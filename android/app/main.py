"""WBS Berlin v7.0 — Modern UI · Full Customization · Dark/Light · Animations"""
import os, sys, time, threading, json, re, hashlib, socket, ssl, sqlite3
import urllib.request

# ══════════════════════════════════════════════════════════════════════
# CRASH LOG — first thing that runs
# ══════════════════════════════════════════════════════════════════════
_T0  = time.time()
_LOG = None
for _p in ["/sdcard/wbs_log.txt",
           os.path.join(os.path.dirname(os.path.abspath(__file__)), "wbs_log.txt")]:
    try:
        with open(_p, "w") as _f:
            _f.write(f"WBS Berlin v7.0 — {time.ctime()}\nPython {sys.version}\n")
        _LOG = _p; break
    except Exception:
        pass

def log(msg):
    try:
        if _LOG:
            with open(_LOG, "a") as f:
                f.write(f"[{time.time()-_T0:.2f}s] {msg}\n")
    except Exception:
        pass

log("startup")

# ══════════════════════════════════════════════════════════════════════
# ARABIC — cached module-level
# ══════════════════════════════════════════════════════════════════════
_ar_mod = None; _ar_bidi = None

def _init_arabic():
    global _ar_mod, _ar_bidi
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        _ar_mod = arabic_reshaper; _ar_bidi = get_display
        log("arabic ok")
    except Exception as e:
        log(f"arabic: {e}")

def ar(text):
    s = str(text or "")
    if not _ar_mod or not _ar_bidi: return s
    try: return _ar_bidi(_ar_mod.reshape(s))
    except Exception: return s

# ══════════════════════════════════════════════════════════════════════
# DATA DIRECTORY — Android scoped storage safe
# ══════════════════════════════════════════════════════════════════════
def _find_dir():
    # Android: internal app storage (always writable, no permissions)
    try:
        from jnius import autoclass
        ctx = autoclass("org.kivy.android.PythonActivity").mActivity
        d = ctx.getFilesDir().getAbsolutePath()
        os.makedirs(d, exist_ok=True); log(f"dir: {d}"); return d
    except Exception: pass
    try:
        from jnius import autoclass
        ctx = autoclass("org.kivy.android.PythonActivity").mActivity
        ext = ctx.getExternalFilesDir(None)
        if ext:
            d = ext.getAbsolutePath()
            os.makedirs(d, exist_ok=True); return d
    except Exception: pass
    # Desktop fallback
    for d in [os.path.expanduser("~/.wbsberlin"), "."]:
        try:
            os.makedirs(d, exist_ok=True)
            test = os.path.join(d, ".wtest")
            with open(test,"w") as f: f.write("ok")
            os.unlink(test); return d
        except Exception: pass
    return "."

_DIR = _find_dir()
log(f"data: {_DIR}")

# ══════════════════════════════════════════════════════════════════════
# DATABASE
# ══════════════════════════════════════════════════════════════════════
_DL = threading.RLock()

def _db():
    c = sqlite3.connect(os.path.join(_DIR,"wbs.db"), timeout=5, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=3000")
    return c

DDL = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY, url TEXT, source TEXT, title TEXT,
    price REAL, rooms REAL, size_m2 REAL, floor_ TEXT,
    available TEXT, location TEXT, wbs_label TEXT, wbs_level INTEGER,
    features TEXT DEFAULT '[]', deposit TEXT, heating TEXT,
    score INTEGER DEFAULT 0, trusted_wbs INTEGER DEFAULT 0,
    favorited INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, ts_found REAL
);
CREATE INDEX IF NOT EXISTS i_ts  ON listings(ts_found DESC);
CREATE INDEX IF NOT EXISTS i_fav ON listings(favorited);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS st (
    id INTEGER PRIMARY KEY CHECK(id=1),
    total INT DEFAULT 0, opens INT DEFAULT 0, last_check REAL
);
INSERT OR IGNORE INTO st(id) VALUES(1);
"""

def init_db():
    with _DL:
        c = _db()
        try: c.executescript(DDL); c.commit()
        finally: c.close()
    log("db ok")

def kv_get(k, d=None):
    try:
        with _DL:
            c = _db()
            try:
                r = c.execute("SELECT value FROM kv WHERE key=?", (k,)).fetchone()
                return json.loads(r[0]) if r else d
            finally: c.close()
    except Exception: return d

def kv_set(k, v):
    try:
        with _DL:
            c = _db()
            try:
                c.execute("INSERT OR REPLACE INTO kv VALUES(?,?)",
                          (k, json.dumps(v, ensure_ascii=False)))
                c.commit()
            finally: c.close()
    except Exception as e: log(f"kv_set: {e}")

def save_listing(l):
    lid = l.get("id")
    if not lid: return False
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
                     l.get("score",0), 1 if l.get("trusted_wbs") else 0, time.time()))
                c.execute("UPDATE st SET total=total+1 WHERE id=1")
                c.commit(); return True
            finally: c.close()
    except Exception as e:
        log(f"save: {e}"); return False

def get_rows(limit=300, unseen_only=False):
    try:
        with _DL:
            c = _db()
            try:
                q = "SELECT * FROM listings WHERE hidden=0 ORDER BY ts_found DESC LIMIT ?"
                rows = c.execute(q, (limit,)).fetchall()
                cols = [d[0] for d in c.description]
                return [dict(zip(cols,r)) for r in rows]
            finally: c.close()
    except Exception as e:
        log(f"get_rows: {e}"); return []

def toggle_fav(lid):
    try:
        with _DL:
            c = _db()
            try:
                r = c.execute("SELECT favorited FROM listings WHERE id=?", (lid,)).fetchone()
                if r:
                    nv = 0 if r[0] else 1
                    c.execute("UPDATE listings SET favorited=? WHERE id=?", (nv,lid))
                    c.commit(); return bool(nv)
            finally: c.close()
    except Exception as e: log(f"fav: {e}")
    return False

def hide_row(lid):
    try:
        with _DL:
            c = _db()
            try:
                c.execute("UPDATE listings SET hidden=1 WHERE id=?", (lid,))
                c.commit()
            finally: c.close()
    except Exception as e: log(f"hide: {e}")

def get_favs():
    try:
        with _DL:
            c = _db()
            try:
                rows = c.execute("SELECT * FROM listings WHERE favorited=1 "
                                 "ORDER BY ts_found DESC LIMIT 100").fetchall()
                cols = [d[0] for d in c.description]
                return [dict(zip(cols,r)) for r in rows]
            finally: c.close()
    except Exception: return []

def get_stats():
    try:
        with _DL:
            c = _db()
            try:
                r = c.execute("SELECT * FROM st WHERE id=1").fetchone()
                total = c.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
                favs  = c.execute("SELECT COUNT(*) FROM listings WHERE favorited=1").fetchone()[0]
                by_src= {row[0]:row[1] for row in
                         c.execute("SELECT source,COUNT(*) FROM listings GROUP BY source").fetchall()}
                return {
                    "total":r[1] if r else 0, "opens":r[2] if r else 0,
                    "last_check":r[3] if r else None, "db":total,
                    "favs":favs, "by_src":by_src
                }
            finally: c.close()
    except Exception: return {}

def bump_opens():
    try:
        with _DL:
            c = _db()
            try: c.execute("UPDATE st SET opens=opens+1 WHERE id=1"); c.commit()
            finally: c.close()
    except Exception: pass

def purge_old(days=60):
    cut = time.time() - days*86400
    try:
        with _DL:
            c = _db()
            try:
                c.execute("DELETE FROM listings WHERE ts_found<? AND favorited=0 AND hidden=0", (cut,))
                c.commit()
            finally: c.close()
    except Exception: pass

# ══════════════════════════════════════════════════════════════════════
# CONFIG + THEMES
# ══════════════════════════════════════════════════════════════════════
THEMES = {
    "غامق":    {"bg":"#0A0A0A","bg2":"#141414","bg3":"#1E1E1E","tx1":"#F1F5F9","tx2":"#94A3B8","tx3":"#475569"},
    "رمادي":  {"bg":"#111827","bg2":"#1F2937","bg3":"#374151","tx1":"#F9FAFB","tx2":"#9CA3AF","tx3":"#6B7280"},
    "بحري":   {"bg":"#0F172A","bg2":"#1E293B","bg3":"#334155","tx1":"#F1F5F9","tx2":"#94A3B8","tx3":"#64748B"},
    "فاتح":   {"bg":"#F8FAFC","bg2":"#F1F5F9","bg3":"#E2E8F0","tx1":"#0F172A","tx2":"#475569","tx3":"#94A3B8"},
}
ACCENTS = {
    "أخضر":   "#22C55E",
    "أزرق":   "#3B82F6",
    "بنفسجي": "#8B5CF6",
    "برتقالي":"#F97316",
    "وردي":   "#EC4899",
    "فيروزي": "#06B6D4",
    "ذهبي":   "#F59E0B",
    "أحمر":   "#EF4444",
}
FONT_SIZES = {"صغير":0.85, "عادي":1.0, "كبير":1.15, "كبير جداً":1.3}

DEF = {
    "max_price":700,"min_price":0,"min_rooms":0.0,"max_rooms":0.0,
    "min_size":0,"max_size":0,
    "wbs_only":False,"wbs_level_min":0,"wbs_level_max":999,
    "household_size":1,"jobcenter_mode":False,"wohngeld_mode":False,
    "sources":[],"areas":[],"sort_by":"score",
    "bg_interval":30,"notifications":True,
    "accent":"أخضر","theme":"غامق","font_size":"عادي",
    "purge_days":60,"compact_cards":False,
}

def load_cfg():
    s = kv_get("cfg", {})
    return {**DEF, **(s if isinstance(s,dict) else {})}

def save_cfg(c): kv_set("cfg", c)
def is_first(): return not kv_get("done", False)
def set_done(): kv_set("done", True)

# ══════════════════════════════════════════════════════════════════════
# DOMAIN
# ══════════════════════════════════════════════════════════════════════
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
AREAS = [
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
    "balkon":"🌿 بلكونة","terrasse":"🌿 تراس","dachterrasse":"🌿 تراس علوي",
    "garten":"🌱 حديقة","aufzug":"🛗 مصعد","fahrstuhl":"🛗 مصعد",
    "einbauküche":"🍳 مطبخ مجهز","keller":"📦 مخزن","abstellraum":"📦 مخزن",
    "stellplatz":"🚗 موقف","tiefgarage":"🚗 جراج","barrierefrei":"♿ بلا عوائق",
    "neubau":"🏗 بناء جديد","erstbezug":"✨ أول سكن","parkett":"🪵 باركيه",
    "laminat":"🪵 لامينيت","fußbodenheizung":"🌡 تدفئة أرضية",
    "fernwärme":"🌡 تدفئة مركزية","gasheizung":"🔥 تدفئة غاز",
    "saniert":"🔨 مجدد","waschmaschine":"🫧 غسالة","badewanne":"🛁 حوض",
    "rolladen":"🪟 ستائر","sep. wc":"🚽 حمام منفصل",
}
MONTHS_AR = {
    "januar":"يناير","februar":"فبراير","märz":"مارس","april":"أبريل",
    "mai":"مايو","juni":"يونيو","juli":"يوليو","august":"أغسطس",
    "september":"سبتمبر","oktober":"أكتوبر","november":"نوفمبر","dezember":"ديسمبر",
}

# ══════════════════════════════════════════════════════════════════════
# NETWORK + SCRAPERS
# ══════════════════════════════════════════════════════════════════════
_CTX = ssl.create_default_context()
_CTX.check_hostname = False; _CTX.verify_mode = ssl.CERT_NONE
_UA  = "Mozilla/5.0 (Linux; Android 13; SM-A536B) Chrome/124.0"

def _get(url, t=12):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":_UA,"Accept-Language":"de-DE"})
        with urllib.request.urlopen(req, timeout=t, context=_CTX) as r:
            return r.read().decode(r.headers.get_content_charset("utf-8") or "utf-8","replace")
    except Exception: return None

def _getj(url, t=12):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":_UA,"Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=t, context=_CTX) as r:
            return json.loads(r.read())
    except Exception: return None

def check_net():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3); s.connect(("8.8.8.8",53)); s.close(); return True
    except Exception: return False

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
    try: v=float(s); return v if 50<v<8000 else None
    except Exception: return None

def parse_rooms(raw):
    m = re.search(r"(\d+[.,]?\d*)",str(raw or "").replace(",","."))
    try: v=float(m.group(1)) if m else None; return v if v and 0.5<=v<=20 else None
    except Exception: return None

def enrich(title, desc):
    t = f"{title} {desc}".lower(); out = {}
    # Size
    for pat in [r"(\d[\d\.]*)\s*m[²2]",r"(\d[\d\.]*)\s*qm\b"]:
        m = re.search(pat, t)
        if m:
            try:
                v = float(m.group(1).replace(".",""))
                if 15<v<500: out["size_m2"]=v; break
            except Exception: pass
    # Floor
    for pat,fn in [
        (r"(\d+)\.\s*(?:og|etage|stock)\b", lambda m:f"الطابق {m.group(1)}"),
        (r"\beg\b(?!\w)|erdgeschoss",        lambda _:"الطابق الأرضي"),
        (r"\bdg\b(?!\w)|dachgeschoss",       lambda _:"الطابق العلوي"),
        (r"\bpenthouse\b",                   lambda _:"بنتهاوس"),
    ]:
        mm = re.search(pat,t)
        if mm: out["floor"]=fn(mm); break
    # Availability
    if any(k in t for k in ["ab sofort","sofort frei","sofort verfügbar","sofort beziehbar"]):
        out["available"]="فوري"
    else:
        m = re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",t)
        if m: out["available"]=m.group(1)
        else:
            mths="|".join(MONTHS_AR)
            m = re.search(rf"ab\s+({mths})\s*(\d{{4}})?",t)
            if m: out["available"]=f"من {MONTHS_AR[m.group(1)]} {m.group(2) or ''}".strip()
    # Deposit
    m = re.search(r"kaution[:\s]*(\d[\d\.,]*)\s*€?",t)
    if m:
        v=parse_price(m.group(1))
        if v: out["deposit"]=f"{v:.0f} €"
    else:
        m = re.search(r"(\d)\s*monatsmieten?\s*(?:kaution)?",t)
        if m: out["deposit"]=f"{m.group(1)}× إيجار"
    # WBS level
    mm = re.search(r"wbs[\s\-_]*(\d{2,3})",t)
    if mm: out["wbs_level_num"]=int(mm.group(1))
    # Features
    seen=set(); feats=[]
    for kw,lb in FEATS.items():
        if kw in t and lb not in seen: seen.add(lb); feats.append(lb)
    if feats: out["features"]=feats
    return out

def _score(l):
    s = 8 if l.get("trusted_wbs") else 0
    s += 3 if l.get("source") in GOV else 0
    p = l.get("price")
    if p: s += 10 if p<400 else 7 if p<500 else 4 if p<600 else 1 if p<700 else 0
    r = l.get("rooms")
    if r: s += 5 if r>=3 else 3 if r>=2 else 0
    if l.get("size_m2"): s+=2
    if l.get("available")=="فوري": s+=5
    s += min(len(l.get("features") or []),4)
    return s

def scrape_gewobag():
    data=_getj("https://www.gewobag.de/wp-json/gewobag/v1/offers?type=wohnung&wbs=1&per_page=50")
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
        data=_getj(api)
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

def scrape_howoge():
    data=_getj("https://www.howoge.de/api/v2/immobilien/suche?typ=wohnung&wbs=ja&von=0&groesse=50")
    if not data: return []
    items=data if isinstance(data,list) else data.get("treffer",data.get("items",[]))
    result=[]; seen=set()
    for i in items:
        url=i.get("url") or i.get("link","")
        if not url: continue
        if not url.startswith("http"): url="https://www.howoge.de"+url
        if url in seen: continue; seen.add(url)
        extra=enrich(i.get("bezeichnung",""),str(i.get("beschreibung") or ""))
        l={"id":make_id(url),"url":url,"source":"howoge","trusted_wbs":True,
           "title":i.get("bezeichnung","")[:80],"price":parse_price(i.get("gesamtmiete") or i.get("miete")),
           "rooms":parse_rooms(i.get("zimmer")),"location":i.get("bezirk","Berlin"),
           "wbs_label":"WBS","ts":time.time(),**extra}
        l["score"]=_score(l); result.append(l)
    return result

def scrape_wbm():
    try:
        from bs4 import BeautifulSoup
    except ImportError: return []
    html=_get("https://www.wbm.de/wohnungen-berlin/angebote/")
    if not html: return []
    soup=BeautifulSoup(html,"html.parser")
    result=[]; seen=set()
    for card in soup.select(".openimmo-search-list-item,article.listing-item")[:20]:
        a=card.select_one("a[href]")
        if not a: continue
        href=a.get("href","")
        url=href if href.startswith("http") else "https://www.wbm.de"+href
        if url in seen: continue; seen.add(url)
        title=(card.select_one("h2,h3,.title") or a).get_text(strip=True)[:80]
        p_tag=card.select_one(".price,.miete,[class*=price]")
        extra=enrich(title,card.get_text(" ",strip=True))
        l={"id":make_id(url),"url":url,"source":"wbm","trusted_wbs":True,
           "title":title,"price":parse_price(p_tag.get_text() if p_tag else None),
           "rooms":None,"location":"Berlin","wbs_label":"WBS","ts":time.time(),**extra}
        l["score"]=_score(l); result.append(l)
    return result

_SCRAPERS = {
    "gewobag":scrape_gewobag,"degewo":scrape_degewo,
    "howoge":scrape_howoge,"wbm":scrape_wbm,
}

def fetch_all(cfg=None, timeout=25):
    log("fetch_all")
    enabled=(cfg or {}).get("sources") or list(SOURCES.keys())
    results=[]; lock=threading.Lock()
    def run(src,fn):
        try:
            items=fn()
            with lock: results.extend(items)
            log(f"  {src}:{len(items)}")
        except Exception as e: log(f"  {src}:{e}")
    threads=[]
    for src in enabled:
        fn=_SCRAPERS.get(src)
        if fn:
            t=threading.Thread(target=run,args=(src,fn),daemon=True)
            threads.append(t); t.start()
    dl=time.time()+timeout
    for t in threads: t.join(timeout=max(0.1,dl-time.time()))
    seen=set(); unique=[]
    for l in results:
        if l.get("id") and l["id"] not in seen:
            seen.add(l["id"]); unique.append(l)
    log(f"fetch:{len(unique)}")
    return unique

def apply_filters(listings, cfg):
    out=[]
    max_p=float(cfg.get("max_price") or 9999); min_p=float(cfg.get("min_price") or 0)
    min_r=float(cfg.get("min_rooms") or 0); max_r=float(cfg.get("max_rooms") or 0)
    min_sz=int(cfg.get("min_size") or 0); max_sz=int(cfg.get("max_size") or 0)
    wbs=bool(cfg.get("wbs_only")); wlmin=int(cfg.get("wbs_level_min") or 0)
    wlmax=int(cfg.get("wbs_level_max") or 999)
    jcm=bool(cfg.get("jobcenter_mode")); wgm=bool(cfg.get("wohngeld_mode"))
    n=max(1,int(cfg.get("household_size") or 1))
    areas=[a.lower() for a in (cfg.get("areas") or [])]
    srcs=cfg.get("sources") or []
    for l in listings:
        if not l.get("id") or l.get("hidden"): continue
        if srcs and l.get("source") not in srcs: continue
        price=l.get("price"); rooms=l.get("rooms"); sz=l.get("size_m2")
        if price is not None:
            if min_p>0 and price<min_p: continue
            if price>max_p: continue
        if rooms is not None:
            if min_r>0 and rooms<min_r: continue
            if max_r>0 and rooms>max_r: continue
        if sz is not None:
            if min_sz>0 and sz<min_sz: continue
            if max_sz>0 and sz>max_sz: continue
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

def sort_it(listings, sort_by):
    if sort_by=="price_asc":  return sorted(listings, key=lambda l:l.get("price") or 9999)
    if sort_by=="price_desc": return sorted(listings, key=lambda l:-(l.get("price") or 0))
    if sort_by=="newest":     return sorted(listings, key=lambda l:-(l.get("ts_found") or l.get("ts") or 0))
    if sort_by=="rooms":      return sorted(listings, key=lambda l:-(l.get("rooms") or 0))
    return sorted(listings, key=lambda l:-(l.get("score") or 0))

# ══════════════════════════════════════════════════════════════════════
# BACKGROUND SERVICE
# ══════════════════════════════════════════════════════════════════════
_bg_stop=threading.Event(); _bg_th=None

def _bgw():
    time.sleep(15)
    while not _bg_stop.is_set():
        try:
            cfg=load_cfg()
            if check_net():
                raw=fetch_all(cfg,timeout=30)
                for l in raw: save_listing(l)
            purge_old(int(cfg.get("purge_days",60)))
            with _DL:
                c=_db()
                try: c.execute("UPDATE st SET last_check=? WHERE id=1",(time.time(),)); c.commit()
                finally: c.close()
        except Exception as e: log(f"bg:{e}")
        _bg_stop.wait(timeout=max(5,int(load_cfg().get("bg_interval",30)))*60)

def start_bg():
    global _bg_th,_bg_stop
    if _bg_th and _bg_th.is_alive(): return
    _bg_stop.clear()
    _bg_th=threading.Thread(target=_bgw,daemon=True,name="WBSBg"); _bg_th.start()
    log("bg started")

def stop_bg(): _bg_stop.set()
def is_bg(): return bool(_bg_th and _bg_th.is_alive())

# ══════════════════════════════════════════════════════════════════════
# KIVY UI — Modern Dark Interface
# ══════════════════════════════════════════════════════════════════════
log("kivy import...")
try:
    import kivy; kivy.require("2.0.0")
    from kivy.config import Config
    Config.set("kivy","log_level","error")
    from kivy.app import App
    from kivy.uix.screenmanager import ScreenManager,Screen,FadeTransition
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
    from kivy.graphics import Color,RoundedRectangle,Rectangle,Ellipse,Line
    from kivy.clock import Clock
    from kivy.metrics import dp,sp
    from kivy.utils import get_color_from_hex
    from kivy.core.window import Window
    from kivy.core.text import LabelBase
    from kivy.animation import Animation
    HAS_KIVY=True; log("kivy ok")
except Exception as e:
    import traceback; log(f"kivy FAILED:{e}\n{traceback.format_exc()}"); HAS_KIVY=False

if HAS_KIVY:
    # ── Runtime theme state ──────────────────────────────────────────
    _THEME  = {"bg":"#0A0A0A","bg2":"#141414","bg3":"#1E1E1E",
                "tx1":"#F1F5F9","tx2":"#94A3B8","tx3":"#475569"}
    _ACCENT = [0.134,0.773,0.369,1.0]  # green
    _FS     = [1.0]
    _FN     = ["Roboto"]

    def _apply_theme(name):
        t = THEMES.get(name, THEMES["غامق"])
        _THEME.update(t)

    def _apply_accent(name):
        c = get_color_from_hex(ACCENTS.get(name,"#22C55E"))
        _ACCENT[:] = list(c)

    def _apply_font_size(name):
        _FS[0] = FONT_SIZES.get(name, 1.0)

    # ── Color getters ────────────────────────────────────────────────
    def BG():  return get_color_from_hex(_THEME["bg"])
    def BG2(): return get_color_from_hex(_THEME["bg2"])
    def BG3(): return get_color_from_hex(_THEME["bg3"])
    def TX1(): return get_color_from_hex(_THEME["tx1"])
    def TX2(): return get_color_from_hex(_THEME["tx2"])
    def TX3(): return get_color_from_hex(_THEME["tx3"])
    def AC():  return tuple(_ACCENT)
    def FN():  return _FN[0]
    def fs(n): return sp(n * _FS[0])

    # Fixed colors
    PUR = get_color_from_hex("#8B5CF6")
    BLU = get_color_from_hex("#3B82F6")
    AMB = get_color_from_hex("#F59E0B")
    RED = get_color_from_hex("#EF4444")
    GLD = get_color_from_hex("#F59E0B")
    WH  = (1,1,1,1)
    NO  = (0,0,0,0)
    DIV = get_color_from_hex("#1E293B")

    # ── Drawing helpers ──────────────────────────────────────────────
    def bg(w, col, r=0):
        w.canvas.before.clear()
        with w.canvas.before:
            Color(*col)
            rect = (RoundedRectangle(pos=w.pos,size=w.size,radius=[dp(r)])
                    if r else Rectangle(pos=w.pos,size=w.size))
        def u(*_): rect.pos=w.pos; rect.size=w.size
        w.bind(pos=u,size=u)

    def pill(w, col, r=20):
        """Pill-shaped background."""
        bg(w, col, r=r)

    def lb(text, sz=14, col=None, bold=False, align="right", **kw):
        col = col or TX1()
        try: txt=ar(str(text or ""))
        except Exception: txt=str(text or "")
        w = Label(text=txt,font_size=fs(sz),color=col,bold=bold,
                  halign=align,font_name=FN(),**kw)
        w.bind(width=lambda *_: setattr(w,"text_size",(w.width,None)))
        return w

    def bt(text, cb=None, col=None, tc=None, h=48, r=14, **kw):
        col=col or AC(); tc=tc or WH
        try: txt=ar(str(text or ""))
        except Exception: txt=str(text or "")
        b = Button(text=txt,size_hint_y=None,height=dp(h),
                   background_color=NO,color=tc,font_size=fs(14),bold=True,
                   font_name=FN(),**kw)
        bg(b,col,r=r)
        if cb: b.bind(on_press=cb)
        return b

    def icon_bt(icon, cb=None, col=None, size=44, r=12):
        col=col or BG3()
        b=Button(text=icon,size_hint=(None,None),size=(dp(size),dp(size)),
                 background_color=NO,color=TX2(),font_size=fs(18))
        bg(b,col,r=r)
        if cb: b.bind(on_press=cb)
        return b

    def gp(h=8): return Widget(size_hint_y=None,height=dp(h))

    def dv(col=None):
        w=Widget(size_hint_y=None,height=dp(1))
        bg(w, col or DIV); return w

    def inp(val, filt="int", hint=""):
        t=TextInput(text=str(val),input_filter=filt,multiline=False,
                    background_color=NO,foreground_color=TX1(),
                    cursor_color=AC(),font_size=fs(14),
                    hint_text=hint,hint_text_color=TX3())
        bg(t,BG3(),r=12); return t

    def si(t,d=0):
        try: return int(float(t.text or d))
        except Exception: return d

    def sf(t,d=0.0):
        try: return float(t.text or d)
        except Exception: return d

    def chip(text, active=False, col=None, on_toggle=None, **kw):
        col=col or AC()
        b=ToggleButton(text=ar(text),state="down" if active else "normal",
                       background_color=NO,color=TX1(),
                       font_size=fs(12),font_name=FN(),**kw)
        def upd(inst,state):
            bg(inst,(*col[:3],0.85) if state=="down" else BG3(),r=16)
            if on_toggle: on_toggle(state=="down")
        upd(b,b.state)
        b.bind(state=upd)
        return b

    def section_title(text):
        row=BoxLayout(size_hint_y=None,height=dp(36),padding=(dp(4),dp(4)))
        row.add_widget(lb(text,sz=11,col=TX3(),bold=True))
        return row

    def card_wrap(**kw):
        b=BoxLayout(**kw); bg(b,BG2(),r=16); return b

    # ── Animated badge ───────────────────────────────────────────────
    class Badge(BoxLayout):
        def __init__(self, text, col, **kw):
            super().__init__(size_hint=(None,None),size=(dp(60),dp(22)),
                             padding=(dp(6),0),**kw)
            bg(self,(*col[:3],0.20),r=11)
            self.lbl=Label(text=ar(str(text)),font_size=fs(10),
                           color=col,font_name=FN(),bold=True)
            self.add_widget(self.lbl)
        def update(self,text,col):
            self.lbl.text=ar(str(text)); self.lbl.color=col
            bg(self,(*col[:3],0.20),r=11)

    # ── Score stars ──────────────────────────────────────────────────
    def score_stars(sc):
        if sc>=22: return "⭐⭐⭐"
        if sc>=16: return "⭐⭐"
        if sc>=10: return "⭐"
        return ""

    # ── Bottom nav bar ───────────────────────────────────────────────
    def make_navbar(app_ref, active):
        TABS=[("🏠","main","الرئيسية"),("⭐","favs","المفضلة"),
              ("📊","stats","إحصائيات"),("⚙️","cfg","إعدادات")]
        bar=BoxLayout(size_hint_y=None,height=dp(60))
        bg(bar,BG2())
        # top border
        for icon,name,label in TABS:
            on=name==active
            col=AC() if on else TX3()
            try: txt=f"{icon}\n{ar(label)}"
            except Exception: txt=f"{icon}\n{label}"
            b=Button(text=txt,background_color=NO,color=col,
                     font_size=fs(9 if not on else 10),bold=on,font_name=FN())
            if on:
                bg(b,(*AC()[:3],0.10))
            else:
                bg(b,BG2())
            n=name; b.bind(on_press=lambda _,n=n:setattr(app_ref.sm,"current",n))
            bar.add_widget(b)
        return bar

    # ══════════════════════════════════════════════════════════════════
    # LISTING CARD — Modern design
    # ══════════════════════════════════════════════════════════════════
    class ListingCard(BoxLayout):
        def __init__(self, l, compact=False, **kw):
            super().__init__(orientation="vertical",size_hint_y=None,
                             padding=(dp(14),dp(13)),spacing=dp(7),**kw)
            name,gov=SOURCES.get(l.get("source",""),("?",False))
            src_col=PUR if gov else BLU
            price=l.get("price"); rooms=l.get("rooms"); sz=l.get("size_m2")
            avail=l.get("available",""); floor_=l.get("floor_") or l.get("floor","")
            dep=l.get("deposit",""); heat=l.get("heating","")
            try:
                feats=(json.loads(l["features"]) if isinstance(l.get("features"),str)
                       else (l.get("features") or []))
            except Exception: feats=[]
            feats=feats[:6 if not compact else 3]
            title=(l.get("title") or "شقة").strip()[:65]
            wlnum=l.get("wbs_level") or l.get("wbs_level_num")
            wlbl=f"WBS {wlnum}" if wlnum else ("WBS ✓" if l.get("trusted_wbs") else "")
            sc_=l.get("score",0); stars=score_stars(sc_)
            self.url=l.get("url",""); self.lid=l.get("id","")
            is_fav=bool(l.get("favorited"))
            n_fr=max(1,(len(feats)+2)//3) if feats else 0
            extra_h=dp(24) if (dep or heat) else 0
            self.height=dp((130 if compact else 165)+n_fr*22)+extra_h
            bg(self,BG2(),r=18)

            # ── Row 1: source + badges + fav ────────────────────────
            r1=BoxLayout(size_hint_y=None,height=dp(26),spacing=dp(6))
            src_badge=BoxLayout(size_hint=(None,None),size=(dp(110),dp(24)),padding=(dp(7),0))
            bg(src_badge,(*src_col[:3],0.15),r=12)
            src_badge.add_widget(lb(("🏛 " if gov else "🔍 ")+ar(name),sz=10,
                                    col=src_col,size_hint_y=None,height=dp(24)))
            r1.add_widget(src_badge)
            if stars:
                sb=BoxLayout(size_hint=(None,None),size=(dp(50),dp(24)),padding=(dp(6),0))
                bg(sb,(*GLD[:3],0.15),r=12)
                sb.add_widget(lb(stars,sz=10,col=GLD,size_hint_y=None,height=dp(24)))
                r1.add_widget(sb)
            r1.add_widget(Widget())
            if wlbl:
                wb=BoxLayout(size_hint=(None,None),size=(dp(74),dp(24)),padding=(dp(7),0))
                bg(wb,(*AC()[:3],0.18),r=12)
                wb.add_widget(lb(wlbl,sz=10,col=AC(),bold=True,size_hint_y=None,height=dp(24)))
                r1.add_widget(wb)
            self._fb=Button(text="★" if is_fav else "☆",
                            size_hint=(None,None),size=(dp(30),dp(24)),
                            background_color=NO,color=GLD if is_fav else TX3(),
                            font_size=sp(17))
            self._fb.bind(on_press=self._fav); r1.add_widget(self._fb)
            self.add_widget(r1)

            # ── Title ────────────────────────────────────────────────
            self.add_widget(lb(title,sz=13,bold=True,size_hint_y=None,height=dp(22)))

            # ── Location + availability ──────────────────────────────
            if not compact or avail:
                r2=BoxLayout(size_hint_y=None,height=dp(18))
                r2.add_widget(lb("📍 "+ar(l.get("location","Berlin")),sz=10,col=TX2()))
                if avail:
                    a_txt="فوري 🔥" if avail=="فوري" else f"📅 {avail}"
                    r2.add_widget(lb(ar(a_txt),sz=10,col=AMB if avail=="فوري" else TX2()))
                self.add_widget(r2)

            self.add_widget(dv())

            # ── Price + details ──────────────────────────────────────
            r3=BoxLayout(size_hint_y=None,height=dp(34),spacing=dp(6))
            if price:
                ppm=f" ·{price/sz:.1f}€/m²" if sz else ""
                pp=BoxLayout(size_hint=(None,None),size=(dp(120),dp(30)),padding=(dp(8),0))
                bg(pp,(*AC()[:3],0.18),r=10)
                pp.add_widget(lb(f"💰 {price:.0f}€{ppm}",sz=12,col=AC(),
                                  bold=True,size_hint_y=None,height=dp(30)))
                r3.add_widget(pp)
            detail_items=[]
            if rooms:   detail_items.append(f"🛏 {rooms:.0f}")
            if sz:      detail_items.append(f"📐 {sz:.0f}m²")
            if floor_:  detail_items.append(ar(floor_))
            for d in detail_items:
                db=BoxLayout(size_hint=(None,None),size=(dp(68),dp(28)),padding=(dp(4),0))
                bg(db,BG3(),r=9)
                db.add_widget(lb(ar(d),sz=10,col=TX1(),size_hint_y=None,height=dp(28)))
                r3.add_widget(db)
            r3.add_widget(Widget())
            self.add_widget(r3)

            # ── Deposit / heating ────────────────────────────────────
            if dep or heat:
                rx=BoxLayout(size_hint_y=None,height=dp(18))
                if dep: rx.add_widget(lb("💼 "+ar(dep),sz=10,col=TX2()))
                if heat: rx.add_widget(lb(ar(heat),sz=10,col=TX2()))
                self.add_widget(rx)

            # ── Feature chips ────────────────────────────────────────
            if feats:
                fg=GridLayout(cols=3,size_hint_y=None,height=dp(n_fr*22),spacing=dp(4))
                for f in feats:
                    fc=BoxLayout(size_hint_y=None,height=dp(20),padding=(dp(5),0))
                    bg(fc,BG3(),r=8)
                    fc.add_widget(lb(ar(f),sz=9,col=TX2(),size_hint_y=None,height=dp(20)))
                    fg.add_widget(fc)
                self.add_widget(fg)

            # ── Action buttons ───────────────────────────────────────
            ab=BoxLayout(size_hint_y=None,height=dp(34),spacing=dp(8))
            ob=bt("فتح الإعلان ←",cb=self._open,h=34,r=10)
            hb=bt("إخفاء",cb=self._hide,col=BG3(),tc=TX2(),h=34,r=10,
                   size_hint_x=None,width=dp(76))
            ab.add_widget(ob); ab.add_widget(hb)
            self.add_widget(ab)

        def _fav(self,*_):
            if not self.lid: return
            nv=toggle_fav(self.lid)
            self._fb.color=GLD if nv else TX3(); self._fb.text="★" if nv else "☆"

        def _hide(self,*_):
            if self.lid: hide_row(self.lid)
            anim=Animation(opacity=0,height=0,duration=0.25,t="out_quad")
            anim.start(self)

        def _open(self,*_):
            if not self.url: return
            log(f"open:{self.url}")
            try:
                from jnius import autoclass
                I=autoclass("android.content.Intent"); U=autoclass("android.net.Uri")
                PA=autoclass("org.kivy.android.PythonActivity")
                PA.mActivity.startActivity(I(I.ACTION_VIEW,U.parse(self.url)))
            except Exception:
                try:
                    from kivy.core.clipboard import Clipboard; Clipboard.copy(self.url)
                except Exception: pass

    # ══════════════════════════════════════════════════════════════════
    # MAIN SCREEN
    # ══════════════════════════════════════════════════════════════════
    class MainScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="main",**kw)
            self.app=app; self._lock=threading.RLock()
            self._busy=False; self._raw=[]; self._compact=False
            bg(self,BG()); self._build()

        def _build(self):
            cfg=load_cfg(); self._compact=bool(cfg.get("compact_cards"))
            root=BoxLayout(orientation="vertical")

            # ── Top bar ───────────────────────────────────────────────
            bar=BoxLayout(size_hint_y=None,height=dp(58),
                           padding=(dp(14),dp(8)),spacing=dp(8))
            bg(bar,BG2())
            bar.add_widget(lb("🏠 WBS برلين",sz=16,bold=True,col=WH,size_hint_x=0.4))
            bar.add_widget(Widget())
            # Sort cycle button
            sort_icons={"score":"🏅","price_asc":"💰↑","price_desc":"💰↓",
                        "newest":"🕐","rooms":"🛏"}
            self._sort_bt=icon_bt(sort_icons.get(cfg.get("sort_by","score"),"🏅"),
                                   cb=self._cycle_sort)
            bar.add_widget(self._sort_bt)
            # Compact toggle
            self._cmp_bt=icon_bt("▦" if self._compact else "▤",cb=self._toggle_compact)
            bar.add_widget(self._cmp_bt)
            # Refresh
            self._rb=bt("🔄",cb=self._go,col=AC(),size_hint_x=None,h=42,width=dp(46),r=12)
            bar.add_widget(self._rb)
            root.add_widget(bar)

            # ── Filter row ────────────────────────────────────────────
            fr=BoxLayout(size_hint_y=None,height=dp(44),
                          padding=(dp(10),dp(6)),spacing=dp(8))
            bg(fr,BG2())
            self._wbs_chip=chip(ar("✅ WBS"),active=bool(cfg.get("wbs_only")),
                                 col=AC(),on_toggle=self._wbs_toggled,
                                 size_hint=(None,None),size=(dp(86),dp(28)))
            fr.add_widget(self._wbs_chip)
            self._stat_lb=lb("اضغط 🔄",sz=11,col=TX2(),size_hint_y=None,height=dp(28))
            fr.add_widget(self._stat_lb)
            fr.add_widget(Widget())
            self._bg_dot=Label(text="⏸",font_size=sp(16),color=TX3(),
                                size_hint=(None,None),size=(dp(26),dp(28)))
            fr.add_widget(self._bg_dot)
            root.add_widget(fr)
            root.add_widget(dv())

            # ── Cards ─────────────────────────────────────────────────
            self._cards=BoxLayout(orientation="vertical",spacing=dp(10),
                                   padding=(dp(10),dp(10)),size_hint_y=None)
            self._cards.bind(minimum_height=self._cards.setter("height"))
            sv=ScrollView(bar_color=(*AC()[:3],0.5),
                           bar_inactive_color=(*TX3()[:3],0.2))
            sv.add_widget(self._cards)
            root.add_widget(sv)
            root.add_widget(make_navbar(self.app,"main"))
            self.add_widget(root)
            self._placeholder("🔍",ar("اضغط 🔄 للبحث عن شقق WBS"))

        def on_enter(self,*_): Clock.schedule_interval(self._tick,8)
        def on_leave(self,*_): Clock.unschedule(self._tick)

        def _tick(self,*_):
            try:
                on=is_bg()
                self._bg_dot.text="🟢" if on else "⏸"
                self._bg_dot.color=AC() if on else TX3()
            except Exception: pass

        def _wbs_toggled(self,active):
            cfg=load_cfg(); cfg["wbs_only"]=active; save_cfg(cfg)
            with self._lock: raw=list(self._raw)
            if raw:
                shown=sort_it(apply_filters(raw,cfg),cfg.get("sort_by","score"))
                Clock.schedule_once(lambda dt:self._render(shown,len(raw)))

        def _toggle_compact(self,*_):
            self._compact=not self._compact
            self._cmp_bt.text="▦" if self._compact else "▤"
            cfg=load_cfg(); cfg["compact_cards"]=self._compact; save_cfg(cfg)
            with self._lock: raw=list(self._raw)
            if raw:
                cfg2=load_cfg()
                shown=sort_it(apply_filters(raw,cfg2),cfg2.get("sort_by","score"))
                Clock.schedule_once(lambda dt:self._render(shown,len(raw)))

        def _cycle_sort(self,*_):
            order=["score","price_asc","price_desc","newest","rooms"]
            icons={"score":"🏅","price_asc":"💰↑","price_desc":"💰↓","newest":"🕐","rooms":"🛏"}
            cfg=load_cfg(); cur=cfg.get("sort_by","score")
            nxt=order[(order.index(cur)+1)%len(order)]
            cfg["sort_by"]=nxt; save_cfg(cfg); self._sort_bt.text=icons[nxt]
            with self._lock: raw=list(self._raw)
            if raw:
                shown=sort_it(apply_filters(raw,cfg),nxt)
                Clock.schedule_once(lambda dt:self._render(shown,len(raw)))

        def _placeholder(self,icon,msg):
            self._cards.clear_widgets()
            b=BoxLayout(orientation="vertical",spacing=dp(12),size_hint_y=None,
                        height=dp(200),padding=dp(40))
            b.add_widget(Label(text=icon,font_size=sp(48),size_hint_y=None,height=dp(64)))
            b.add_widget(lb(msg,sz=14,col=TX2(),size_hint_y=None,height=dp(44)))
            self._cards.add_widget(b)

        def _go(self,*_):
            with self._lock:
                if self._busy: return
                self._busy=True
            if not check_net():
                cached=get_rows()
                with self._lock: self._busy=False
                if cached:
                    self._stat_lb.text=ar("📦 من قاعدة البيانات")
                    with self._lock: self._raw=cached
                    cfg=load_cfg()
                    shown=sort_it(apply_filters(cached,cfg),cfg.get("sort_by","score"))
                    Clock.schedule_once(lambda dt:self._render(shown,len(cached)))
                else:
                    self._placeholder("📵",ar("لا يوجد اتصال بالإنترنت"))
                return
            self._stat_lb.text=ar("⏳ جاري البحث...")
            self._placeholder("⏳",ar("جاري جلب الإعلانات..."))
            threading.Thread(target=self._fetch,daemon=True).start()

        def _fetch(self):
            try:
                cfg=load_cfg(); raw=fetch_all(cfg,timeout=25)
                nc=sum(1 for l in raw if save_listing(l))
                all_db=get_rows()
                with self._lock: self._raw=all_db
                shown=sort_it(apply_filters(all_db,cfg),cfg.get("sort_by","score"))
                Clock.schedule_once(lambda dt:self._render(shown,len(all_db),nc))
            except Exception as e:
                log(f"_fetch:{e}")
                Clock.schedule_once(lambda dt:self._placeholder("⚠️",ar(f"خطأ: {str(e)[:50]}")))
            finally:
                with self._lock: self._busy=False

        def _render(self,lst,total=None,nc=0):
            try:
                self._cards.clear_widgets()
                t=total if total is not None else len(lst)
                if not lst:
                    self._stat_lb.text=ar(f"لا إعلانات جديدة ({t} في القاعدة)")
                    self._placeholder("🔍",ar("لا توجد إعلانات تناسب فلاترك")); return
                ns=f" +{nc} جديد" if nc else ""
                self._stat_lb.text=ar(f"✅ {len(lst)} إعلان{ns}")
                for l in lst[:12]:
                    self._cards.add_widget(ListingCard(l,compact=self._compact))
                    self._cards.add_widget(gp(6))
                if len(lst)>12:
                    Clock.schedule_once(lambda dt:self._rest(lst[12:]),0.08)
            except Exception as e: log(f"_render:{e}")

        def _rest(self,rest):
            try:
                for l in rest[:60]:
                    self._cards.add_widget(ListingCard(l,compact=self._compact))
                    self._cards.add_widget(gp(6))
            except Exception: pass

    # ══════════════════════════════════════════════════════════════════
    # FAVORITES SCREEN
    # ══════════════════════════════════════════════════════════════════
    class FavsScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="favs",**kw)
            self.app=app; bg(self,BG()); self._build()

        def _build(self):
            self.clear_widgets(); root=BoxLayout(orientation="vertical")
            bar=BoxLayout(size_hint_y=None,height=dp(58),padding=(dp(14),dp(8)),spacing=dp(10))
            bg(bar,BG2())
            bar.add_widget(lb("⭐ "+ar("المفضلة"),sz=16,bold=True,col=GLD))
            bar.add_widget(Widget())
            bar.add_widget(icon_bt("🔄",cb=self._load))
            root.add_widget(bar)
            self._cards=BoxLayout(orientation="vertical",spacing=dp(10),
                                   padding=(dp(10),dp(10)),size_hint_y=None)
            self._cards.bind(minimum_height=self._cards.setter("height"))
            sv=ScrollView(bar_color=(*GLD[:3],0.5)); sv.add_widget(self._cards)
            root.add_widget(sv); root.add_widget(make_navbar(self.app,"favs"))
            self.add_widget(root); self._load()

        def on_enter(self,*_): self._load()

        def _load(self,*_):
            self._cards.clear_widgets()
            favs=get_favs()
            if not favs:
                b=BoxLayout(orientation="vertical",size_hint_y=None,height=dp(180),padding=dp(40))
                b.add_widget(Label(text="⭐",font_size=sp(48),size_hint_y=None,height=dp(64)))
                b.add_widget(lb("لا توجد مفضلة بعد\nاضغط ★ على أي إعلان",sz=13,
                                  col=TX2(),size_hint_y=None,height=dp(60)))
                self._cards.add_widget(b); return
            for l in favs:
                self._cards.add_widget(ListingCard(l)); self._cards.add_widget(gp(6))

    # ══════════════════════════════════════════════════════════════════
    # STATS SCREEN
    # ══════════════════════════════════════════════════════════════════
    class StatsScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="stats",**kw)
            self.app=app; bg(self,BG()); self._build()

        def on_enter(self,*_): self._build()

        def _build(self):
            self.clear_widgets(); st=get_stats()
            root=BoxLayout(orientation="vertical")
            bar=BoxLayout(size_hint_y=None,height=dp(58),padding=(dp(14),dp(8)))
            bg(bar,BG2())
            bar.add_widget(lb("📊 "+ar("الإحصائيات"),sz=16,bold=True,col=WH))
            root.add_widget(bar)
            sc=ScrollView(); body=BoxLayout(orientation="vertical",padding=dp(14),
                spacing=dp(10),size_hint_y=None)
            body.bind(minimum_height=body.setter("height"))

            # Stat cards
            def scard(icon,lbl_t,val,col=None):
                c=BoxLayout(size_hint_y=None,height=dp(72),
                             padding=(dp(16),dp(8)),spacing=dp(14))
                bg(c,BG2(),r=16)
                il=Label(text=icon,font_size=sp(28),size_hint=(None,None),size=(dp(44),dp(44)))
                c.add_widget(il)
                tv=BoxLayout(orientation="vertical")
                tv.add_widget(lb(ar(lbl_t),sz=11,col=TX2()))
                tv.add_widget(lb(str(val),sz=20,bold=True,col=col or AC()))
                c.add_widget(tv); return c

            def ts(t):
                if not t: return "—"
                try:
                    import datetime
                    return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")
                except Exception: return "—"

            body.add_widget(scard("🏠","إجمالي الإعلانات المحفوظة",st.get("db",0)))
            body.add_widget(scard("🆕","إعلانات تمت إضافتها",st.get("total",0),get_color_from_hex("#22C55E")))
            body.add_widget(scard("⭐","إعلانات في المفضلة",st.get("favs",0),GLD))
            body.add_widget(scard("📱","مرات فتح التطبيق",st.get("opens",0),PUR))
            body.add_widget(scard("🕐","آخر فحص",ts(st.get("last_check")),TX2()))

            # By source
            body.add_widget(gp(6)); body.add_widget(section_title("📊  حسب المصدر"))
            by_src=st.get("by_src",{})
            for src,(name,gov) in SOURCES.items():
                cnt=by_src.get(src,0)
                row=BoxLayout(size_hint_y=None,height=dp(44),padding=(dp(14),dp(4)),spacing=dp(8))
                bg(row,BG2(),r=12)
                sc_=PUR if gov else BLU
                row.add_widget(lb(("🏛 " if gov else "🔍 ")+ar(name),sz=12,col=sc_,size_hint_x=0.6))
                # Progress bar
                max_cnt=max(by_src.values()) if by_src else 1
                bar_w=max(0.05, cnt/max(max_cnt,1))
                prog=BoxLayout(size_hint=(0.3,None),height=dp(8))
                bg(prog,BG3(),r=4)
                fill=Widget(size_hint=(bar_w,1))
                bg(fill,sc_,r=4)
                prog.add_widget(fill)
                prog.add_widget(Widget(size_hint=(1-bar_w,1)))
                row.add_widget(prog)
                row.add_widget(lb(str(cnt),sz=13,bold=True,col=AC(),size_hint_x=0.1,align="left"))
                body.add_widget(row)

            body.add_widget(gp(12))
            body.add_widget(bt("🗑 "+ar("مسح الإعلانات القديمة"),cb=self._clear,
                                col=RED,h=46,r=14))
            body.add_widget(gp(20))
            sc.add_widget(body); root.add_widget(sc)
            root.add_widget(make_navbar(self.app,"stats")); self.add_widget(root)

        def _clear(self,*_):
            try:
                with _DL:
                    c=_db()
                    try:
                        c.execute("DELETE FROM listings WHERE favorited=0")
                        c.execute("UPDATE st SET total=0 WHERE id=1")
                        c.commit()
                    finally: c.close()
            except Exception as e: log(f"clear:{e}")
            self._build()

    # ══════════════════════════════════════════════════════════════════
    # SETTINGS SCREEN — Full customization
    # ══════════════════════════════════════════════════════════════════
    class CfgScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="cfg",**kw)
            self.app=app; bg(self,BG()); self._build()

        def _build(self):
            self.clear_widgets(); cfg=load_cfg()
            root=BoxLayout(orientation="vertical")

            hdr=BoxLayout(size_hint_y=None,height=dp(58),padding=(dp(14),dp(8)),spacing=dp(10))
            bg(hdr,BG2())
            hdr.add_widget(lb("⚙️ "+ar("الإعدادات"),sz=16,bold=True,col=WH))
            hdr.add_widget(Widget())
            hdr.add_widget(bt("↩️ "+ar("افتراضي"),cb=self._reset,col=BG3(),tc=TX2(),
                               size_hint_x=None,h=38,width=dp(100),r=12))
            root.add_widget(hdr)

            sc=ScrollView()
            body=BoxLayout(orientation="vertical",padding=dp(14),spacing=dp(10),size_hint_y=None)
            body.bind(minimum_height=body.setter("height"))

            def row(lbl_t,w,hint=""):
                r=BoxLayout(size_hint_y=None,height=dp(56),spacing=dp(12),padding=(dp(14),dp(6)))
                bg(r,BG2(),r=14)
                lbox=BoxLayout(orientation="vertical",size_hint_x=0.46)
                lbox.add_widget(lb(lbl_t,sz=13,col=TX1()))
                if hint: lbox.add_widget(lb(hint,sz=10,col=TX3()))
                r.add_widget(lbox); r.add_widget(w); body.add_widget(r)

            def tog(text,active,pri=None,h=44):
                pri=pri or AC()
                t=ToggleButton(text=ar(text),state="down" if active else "normal",
                    size_hint=(1,None),height=dp(h),background_color=NO,
                    color=TX1(),font_size=fs(12),font_name=FN())
                bg(t,(*pri[:3],0.18) if active else BG2(),r=14)
                t.bind(state=lambda b,s,p=pri:bg(b,(*p[:3],0.18) if s=="down" else BG2(),r=14))
                body.add_widget(t); return t

            # ── 🎨 المظهر ────────────────────────────────────────────
            body.add_widget(gp(4)); body.add_widget(section_title("🎨  المظهر والألوان"))

            # Theme selector
            theme_row=BoxLayout(size_hint_y=None,height=dp(50),padding=(dp(14),dp(6)),spacing=dp(8))
            bg(theme_row,BG2(),r=14)
            theme_row.add_widget(lb("النسق:",sz=12,col=TX1(),size_hint_x=0.28))
            self._theme_btns={}
            cur_th=cfg.get("theme","غامق")
            for th in THEMES:
                on=th==cur_th
                b=ToggleButton(text=ar(th),state="down" if on else "normal",
                    size_hint=(1,None),height=dp(36),background_color=NO,
                    color=TX1() if on else TX2(),font_size=fs(11),bold=on)
                bg(b,(*AC()[:3],0.2) if on else BG3(),r=10)
                b.bind(state=lambda x,s,th=th,b=b:self._sel_theme(th,b,s))
                self._theme_btns[th]=b; theme_row.add_widget(b)
            body.add_widget(theme_row)

            # Accent color
            acc_row=BoxLayout(size_hint_y=None,height=dp(54),padding=(dp(14),dp(8)),spacing=dp(6))
            bg(acc_row,BG2(),r=14)
            acc_row.add_widget(lb("اللون:",sz=12,col=TX1(),size_hint_x=0.22))
            self._acc_btns={}
            cur_acc=cfg.get("accent","أخضر")
            for name,hex_ in ACCENTS.items():
                col=get_color_from_hex(hex_)
                on=name==cur_acc
                b=Button(text="●" if on else "○",size_hint=(None,None),size=(dp(30),dp(30)),
                         background_color=NO,color=col,font_size=sp(18))
                b.bind(on_press=lambda _,n=name:self._sel_accent(n))
                self._acc_btns[name]=b; acc_row.add_widget(b)
            body.add_widget(acc_row)

            # Font size
            fs_row=BoxLayout(size_hint_y=None,height=dp(54),padding=(dp(14),dp(8)),spacing=dp(8))
            bg(fs_row,BG2(),r=14)
            fs_row.add_widget(lb("الخط:",sz=12,col=TX1(),size_hint_x=0.22))
            cur_fs=cfg.get("font_size","عادي"); self._fs_btns={}
            for sz_name in FONT_SIZES:
                on=sz_name==cur_fs
                b=ToggleButton(text=ar(sz_name),state="down" if on else "normal",
                    size_hint=(1,None),height=dp(36),background_color=NO,
                    color=TX1() if on else TX2(),font_size=fs(11))
                bg(b,(*AC()[:3],0.2) if on else BG3(),r=10)
                b.bind(state=lambda x,s,n=sz_name,b=b:self._sel_fs(n,b,s))
                self._fs_btns[sz_name]=b; fs_row.add_widget(b)
            body.add_widget(fs_row)

            # Compact cards
            self._compact=tog("🗜 بطاقات مضغوطة",cfg.get("compact_cards",False))

            # ── 💰 الميزانية ──────────────────────────────────────────
            body.add_widget(gp(4)); body.add_widget(section_title("💰  الميزانية والغرف"))
            self._maxp=inp(cfg.get("max_price",700),hint="€"); row("أقصى إيجار (€)",self._maxp)
            self._minp=inp(cfg.get("min_price",0),hint="€"); row("الحد الأدنى (€)",self._minp,"0=بدون حد")

            rr=BoxLayout(size_hint_y=None,height=dp(56),spacing=dp(6),padding=(dp(14),dp(6)))
            bg(rr,BG2(),r=14)
            rr.add_widget(lb("الغرف:",sz=12,col=TX1(),size_hint_x=0.2))
            self._minr=inp(cfg.get("min_rooms",0),"float"); self._maxr=inp(cfg.get("max_rooms",0),"float")
            rr.add_widget(lb("من",sz=10,col=TX2(),size_hint_x=0.07)); rr.add_widget(self._minr)
            rr.add_widget(lb("—",sz=12,col=TX2(),size_hint_x=0.05)); rr.add_widget(self._maxr)
            rr.add_widget(lb("0=أي",sz=9,col=TX3(),size_hint_x=0.13))
            body.add_widget(rr)

            # ── 📋 WBS ────────────────────────────────────────────────
            body.add_widget(gp(4)); body.add_widget(section_title("📋  WBS"))
            self._wbs=tog("WBS فقط",cfg.get("wbs_only",False))

            wlr=BoxLayout(size_hint_y=None,height=dp(56),spacing=dp(6),padding=(dp(14),dp(6)))
            bg(wlr,BG2(),r=14)
            wlr.add_widget(lb("مستوى WBS:",sz=12,col=TX1(),size_hint_x=0.32))
            self._wlmin=inp(cfg.get("wbs_level_min",0)); self._wlmax=inp(cfg.get("wbs_level_max",999))
            wlr.add_widget(lb("من",sz=10,col=TX2(),size_hint_x=0.08)); wlr.add_widget(self._wlmin)
            wlr.add_widget(lb("—",sz=12,col=TX2(),size_hint_x=0.06)); wlr.add_widget(self._wlmax)
            body.add_widget(wlr)

            pr=BoxLayout(size_hint_y=None,height=dp(38),spacing=dp(6))
            for lt,mn,mx in [("WBS 100","100","100"),("100-140","100","140"),("100-160","100","160"),("الكل","0","999")]:
                b=bt(lt,col=BG3(),tc=TX1(),h=38,r=10,size_hint_x=None,width=dp(82))
                b.bind(on_press=lambda _,mn=mn,mx=mx:(setattr(self._wlmin,"text",mn),setattr(self._wlmax,"text",mx)))
                pr.add_widget(b)
            body.add_widget(pr)

            # ── 🏛 الاجتماعي ──────────────────────────────────────────
            body.add_widget(gp(4)); body.add_widget(section_title("🏛  الفلاتر الاجتماعية"))
            self._hh=inp(cfg.get("household_size",1))
            n_=max(1,int(cfg.get("household_size") or 1))
            row("أفراد الأسرة",self._hh,f"JC≤{jc(n_):.0f}€ · WG≤{wg(n_):.0f}€")
            self._jc=tog("🏛 Jobcenter KdU",cfg.get("jobcenter_mode",False),PUR)
            self._wg=tog("🏦 Wohngeld",cfg.get("wohngeld_mode",False),PUR)

            # ── 📍 المناطق ────────────────────────────────────────────
            body.add_widget(gp(4)); body.add_widget(section_title("📍  المناطق  (بدون تحديد = كل برلين)"))
            cur_ar=cfg.get("areas") or []; self._ab={}
            ag=GridLayout(cols=2,size_hint_y=None,height=dp(((len(AREAS)+1)//2)*38),spacing=dp(5))
            for area in AREAS:
                on=area in cur_ar
                b=ToggleButton(text=area,state="down" if on else "normal",
                    size_hint=(1,None),height=dp(36),background_color=NO,
                    color=TX1(),font_size=fs(11))
                bg(b,(*AMB[:3],0.18) if on else BG2(),r=10)
                b.bind(state=lambda x,s,b=b:bg(b,(*AMB[:3],0.18) if s=="down" else BG2(),r=10))
                self._ab[area]=b; ag.add_widget(b)
            body.add_widget(ag)
            body.add_widget(bt("🌍 "+ar("كل برلين"),
                                cb=lambda *_:[setattr(b,"state","normal") or bg(b,BG2(),r=10)
                                              for b in self._ab.values()],
                                col=BG3(),tc=TX2(),h=36,r=12))

            # ── 🌐 المصادر ────────────────────────────────────────────
            body.add_widget(gp(4)); body.add_widget(section_title("🌐  مصادر البيانات"))
            cur_src=cfg.get("sources") or []; self._src={}
            for sid,(sname,gov) in SOURCES.items():
                sc=PUR if gov else BLU; on=not cur_src or sid in cur_src
                b=ToggleButton(text=("🏛 " if gov else "🔍 ")+ar(sname),
                    state="down" if on else "normal",size_hint=(1,None),height=dp(42),
                    background_color=NO,color=TX1(),font_size=fs(12))
                bg(b,(*sc[:3],0.18) if on else BG2(),r=12)
                b.bind(state=lambda x,s,sc=sc,b=b:bg(b,(*sc[:3],0.18) if s=="down" else BG2(),r=12))
                self._src[sid]=b; body.add_widget(b)
            qr=BoxLayout(size_hint_y=None,height=dp(38),spacing=dp(8))
            qr.add_widget(bt("✅ "+ar("الكل"),cb=lambda *_:[setattr(b,"state","down") for b in self._src.values()],col=BG3(),tc=TX1(),h=38,r=12))
            qr.add_widget(bt("🏛 "+ar("حكومية فقط"),cb=self._govsrc,col=(*PUR[:3],1),h=38,r=12))
            body.add_widget(qr)

            # ── ⚙️ متقدم ──────────────────────────────────────────────
            body.add_widget(gp(4)); body.add_widget(section_title("⚙️  إعدادات متقدمة"))
            self._bgi=inp(cfg.get("bg_interval",30)); row("فترة الخلفية (دق.)",self._bgi,"5 – ∞")
            self._purge=inp(cfg.get("purge_days",60)); row("حذف تلقائي (يوم)",self._purge,"60 = افتراضي")

            bg_on=is_bg()
            self._bgb=bt("⏹ "+ar("إيقاف الخلفية") if bg_on else "▶ "+ar("تشغيل الخلفية"),
                          cb=self._togbg,col=RED if bg_on else AC(),h=46,r=14)
            body.add_widget(gp(8)); body.add_widget(self._bgb)
            body.add_widget(gp(12))
            body.add_widget(bt("💾 "+ar("حفظ الإعدادات"),cb=self._save,h=54,r=16))
            body.add_widget(gp(24))

            sc.add_widget(body); root.add_widget(sc)
            root.add_widget(make_navbar(self.app,"cfg")); self.add_widget(root)

        def _sel_theme(self,name,btn,state):
            if state!="down": return
            for n,b in self._theme_btns.items():
                if n!=name:
                    b.state="normal"; bg(b,BG3(),r=10); b.color=TX2(); b.bold=False
            bg(btn,(*AC()[:3],0.2),r=10); btn.color=TX1(); btn.bold=True
            _apply_theme(name)

        def _sel_accent(self,name):
            for n,b in self._acc_btns.items(): b.text="●" if n==name else "○"
            _apply_accent(name)

        def _sel_fs(self,name,btn,state):
            if state!="down": return
            for n,b in self._fs_btns.items():
                if n!=name: b.state="normal"; bg(b,BG3(),r=10); b.color=TX2(); b.bold=False
            bg(btn,(*AC()[:3],0.2),r=10); btn.color=TX1(); btn.bold=True
            _apply_font_size(name)

        def _govsrc(self,*_):
            for sid,b in self._src.items():
                gov=SOURCES[sid][1]; sc=PUR if gov else BLU
                b.state="down" if gov else "normal"
                bg(b,(*sc[:3],0.18) if gov else BG2(),r=12)

        def _togbg(self,*_):
            if is_bg(): stop_bg(); bg(self._bgb,AC(),r=14); self._bgb.text=ar("▶ تشغيل الخلفية")
            else: start_bg(); bg(self._bgb,RED,r=14); self._bgb.text=ar("⏹ إيقاف الخلفية")

        def _reset(self,*_): save_cfg(dict(DEF)); self._build()

        def _save(self,*_):
            sel_src=[s for s,b in self._src.items() if b.state=="down"]
            sel_ar =[a for a,b in self._ab.items()  if b.state=="down"]
            cur_th =next((n for n,b in self._theme_btns.items() if b.state=="down"),"غامق")
            cur_acc=next((n for n,b in self._acc_btns.items()   if b.text=="●"),"أخضر")
            cur_fs =next((n for n,b in self._fs_btns.items()    if b.state=="down"),"عادي")
            cfg=load_cfg()
            cfg.update({
                "max_price":     si(self._maxp,700),
                "min_price":     si(self._minp,0),
                "min_rooms":     sf(self._minr,0),
                "max_rooms":     sf(self._maxr,0),
                "household_size":max(1,si(self._hh,1)),
                "wbs_only":      self._wbs.state=="down",
                "wbs_level_min": si(self._wlmin,0),
                "wbs_level_max": si(self._wlmax,999),
                "jobcenter_mode":self._jc.state=="down",
                "wohngeld_mode": self._wg.state=="down",
                "areas":    sel_ar,
                "sources":  sel_src if len(sel_src)<len(SOURCES) else [],
                "bg_interval":   max(5,si(self._bgi,30)),
                "purge_days":    max(7,si(self._purge,60)),
                "compact_cards": self._compact.state=="down",
                "theme":    cur_th,
                "accent":   cur_acc,
                "font_size":cur_fs,
            })
            save_cfg(cfg)
            _apply_theme(cur_th); _apply_accent(cur_acc); _apply_font_size(cur_fs)
            self.app.sm.current="main"

    # ══════════════════════════════════════════════════════════════════
    # ONBOARDING
    # ══════════════════════════════════════════════════════════════════
    class OnboardScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="onboard",**kw)
            self.app=app; self._i=0; self._show()

        def _show(self):
            self.clear_widgets(); bg(self,BG())
            PGS=[
                ("🏠","WBS Berlin","ابحث عن شقتك المدعومة\nمن 9 مصادر رسمية وخاصة\nكل ذلك في مكان واحد",AC()),
                ("🗄","قاعدة بيانات ذكية","لا تكرار للإعلانات أبداً\nيتذكر ما شاهدته وما فاتك",PUR),
                ("🎨","تخصيص كامل","اختر المظهر · الألوان · حجم الخط\nفلاتر ذكية: WBS · Jobcenter · Wohngeld",AMB),
                ("🔔","إشعارات فورية","يعمل في الخلفية دائماً\nيرسل إشعاراً فور ظهور شقة مناسبة",get_color_from_hex("#22C55E")),
            ]
            p=PGS[self._i]; last=self._i==len(PGS)-1
            root=FloatLayout()
            card=BoxLayout(orientation="vertical",padding=dp(32),spacing=dp(18),
                           size_hint=(0.88,0.68),pos_hint={"center_x":.5,"center_y":.57})
            bg(card,BG2(),r=24)
            card.add_widget(Label(text=p[0],font_size=sp(64),size_hint_y=None,height=dp(80)))
            card.add_widget(lb(p[1],sz=20,bold=True,col=p[3],size_hint_y=None,height=dp(50)))
            card.add_widget(lb(p[2],sz=13,col=TX2(),size_hint_y=None,height=dp(90)))
            # Dots
            dots=BoxLayout(size_hint=(None,None),size=(dp(100),dp(10)),spacing=dp(8))
            for i in range(len(PGS)):
                d=Widget(size_hint=(None,None),size=(dp(22 if i==self._i else 8),dp(8)))
                bg(d,p[3] if i==self._i else TX3(),r=4); dots.add_widget(d)
            card.add_widget(dots)
            root.add_widget(card)
            brow=BoxLayout(size_hint=(0.88,None),height=dp(54),
                           pos_hint={"center_x":.5,"y":.04},spacing=dp(12))
            if not last: brow.add_widget(bt("تخطي",cb=self._done,col=BG3(),tc=TX2()))
            brow.add_widget(bt("ابدأ الآن 🚀" if last else "التالي ←",
                                cb=self._next if not last else self._done,col=p[3]))
            root.add_widget(brow); self.add_widget(root)

        def _next(self,*_): self._i=min(self._i+1,3); self._show()
        def _done(self,*_): set_done(); self.app.go_main()

    # ══════════════════════════════════════════════════════════════════
    # SPLASH SCREEN
    # ══════════════════════════════════════════════════════════════════
    class SplashScreen(Screen):
        def __init__(self,**kw):
            super().__init__(name="splash",**kw); bg(self,BG())
            root=FloatLayout()
            card=BoxLayout(orientation="vertical",padding=dp(32),spacing=dp(16),
                           size_hint=(0.76,0.48),pos_hint={"center_x":.5,"center_y":.5})
            bg(card,BG2(),r=22)
            card.add_widget(Label(text="🏠",font_size=sp(58),size_hint_y=None,height=dp(76)))
            card.add_widget(lb("WBS Berlin",sz=20,bold=True,col=get_color_from_hex("#22C55E"),
                                size_hint_y=None,height=dp(40)))
            card.add_widget(lb("v7.0 — جاري التحميل...",sz=12,col=TX2(),
                                size_hint_y=None,height=dp(28)))
            root.add_widget(card); self.add_widget(root)

    # ══════════════════════════════════════════════════════════════════
    # APP
    # ══════════════════════════════════════════════════════════════════
    class WBSApp(App):
        def build(self):
            log("build()")
            Window.clearcolor=BG()
            self.sm=ScreenManager(transition=FadeTransition(duration=0.18))
            self.sm.add_widget(SplashScreen())
            self.sm.current="splash"
            Clock.schedule_once(self._init,0.2)
            return self.sm

        def _init(self,dt):
            log("_init")
            try:
                _init_arabic()
                cfg=load_cfg()
                _apply_theme(cfg.get("theme","غامق"))
                _apply_accent(cfg.get("accent","أخضر"))
                _apply_font_size(cfg.get("font_size","عادي"))
                Window.clearcolor=BG()
                # Font
                try:
                    fp=os.path.join(os.path.dirname(os.path.abspath(__file__)),"NotoNaskhArabic.ttf")
                    if os.path.exists(fp):
                        LabelBase.register("NotoArabic",fn_regular=fp)
                        _FN[0]="NotoArabic"; log("font ok")
                    else: log(f"font missing:{fp}")
                except Exception as e: log(f"font:{e}")
                bump_opens()
            except Exception as e:
                log(f"_init err:{e}")
            Clock.schedule_once(self._show_main,0.35)

        def _show_main(self,dt):
            log("_show_main")
            try:
                if is_first():
                    self.sm.add_widget(OnboardScreen(self)); self.sm.current="onboard"
                else:
                    self.go_main()
                Clock.schedule_once(lambda _:start_bg(),5.0)
                log("_show_main done")
            except Exception as e:
                log(f"_show_main err:{e}")
                import traceback; log(traceback.format_exc())
                try:
                    self.sm.add_widget(MainScreen(self)); self.sm.current="main"
                except Exception as e2: log(f"FATAL:{e2}")

        def go_main(self):
            for name,cls in [("main",MainScreen),("favs",FavsScreen),
                              ("stats",StatsScreen),("cfg",CfgScreen)]:
                if not any(s.name==name for s in self.sm.screens):
                    self.sm.add_widget(cls(self))
            self.sm.current="main"

    if __name__=="__main__":
        log("run()")
        try: init_db(); WBSApp().run()
        except Exception as e:
            log(f"run crashed:{e}")
            import traceback; log(traceback.format_exc()); raise

else:
    if __name__=="__main__":
        print("CLI"); init_db()
        raw=fetch_all(); cfg=dict(DEF)
        shown=sort_it(apply_filters(raw,cfg),"score")
        print(f"{len(shown)}/{len(raw)}")
        for l in shown[:3]:
            p=f"{l['price']:.0f}€" if l.get("price") else "—"
            print(f"  [{l['source']}] {p} | {l.get('title','')[:45]}")
