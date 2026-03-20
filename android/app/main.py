"""WBS Berlin v8.1 — Minimal crash-proof bootstrap"""
# ══════════════════════════════════════════════════════════════
# STEP 0: Write proof-of-life to EVERY possible location
# This runs before ANY other import — if we see these files,
# Python started. If not, crash is at Java/JNI level.
# ══════════════════════════════════════════════════════════════
import os, sys, time

_T0 = time.time()
_LOGS = []

def _try_write(path, content):
    try:
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(content)
        _LOGS.append(path)
        return True
    except Exception:
        return False

_STAMP = f"WBS Berlin v8.1\nStarted: {time.ctime()}\nPython: {sys.version}\nPID: {os.getpid()}\n"

# Try every possible writable location
for _p in [
    "/sdcard/wbs_start.txt",
    "/sdcard/Android/data/de.alaa.wbs.wbsberlin/files/wbs_start.txt",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "wbs_start.txt"),
    os.path.expanduser("~/wbs_start.txt"),
    "/data/local/tmp/wbs_start.txt",
    "./wbs_start.txt",
]:
    _try_write(_p, _STAMP)

# Main log (appended to throughout startup)
_LOG = _LOGS[0] if _LOGS else None

def log(msg):
    ts = f"[{time.time()-_T0:.2f}s] {msg}\n"
    if _LOG:
        try:
            with open(_LOG, "a") as f:
                f.write(ts)
        except Exception:
            pass
    # Also write to Android logcat via jnius if available
    try:
        from jnius import autoclass
        Log = autoclass("android.util.Log")
        Log.d("WBSBerlin", msg)
    except Exception:
        pass

log(f"Python started OK — log at: {_LOG}")
log(f"__file__ = {os.path.abspath(__file__)}")
log(f"sys.path = {sys.path[:3]}")

# ══════════════════════════════════════════════════════════════
# STEP 1: Safe stdlib imports
# ══════════════════════════════════════════════════════════════
log("importing stdlib...")
try:
    import threading, json, re, hashlib, socket, ssl, sqlite3
    import urllib.request
    log("stdlib ok")
except Exception as e:
    log(f"STDLIB FAIL: {e}")
    import traceback; log(traceback.format_exc())

# ══════════════════════════════════════════════════════════════
# STEP 2: Arabic (optional — app works without it)
# ══════════════════════════════════════════════════════════════
_ar_mod = None; _ar_bidi = None

def _init_arabic():
    global _ar_mod, _ar_bidi
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        _ar_mod = arabic_reshaper; _ar_bidi = get_display
        log("arabic ok")
    except Exception as e:
        log(f"arabic skip: {e}")

def ar(text):
    s = str(text or "")
    if not _ar_mod or not _ar_bidi: return s
    try: return _ar_bidi(_ar_mod.reshape(s))
    except Exception: return s

# ══════════════════════════════════════════════════════════════
# STEP 3: Data directory
# ══════════════════════════════════════════════════════════════
def _find_dir():
    # Android internal storage (no permissions needed, always works)
    try:
        from jnius import autoclass
        ctx = autoclass("org.kivy.android.PythonActivity").mActivity
        d = ctx.getFilesDir().getAbsolutePath()
        os.makedirs(d, exist_ok=True)
        log(f"storage: {d}")
        return d
    except Exception as e:
        log(f"jnius storage fail: {e}")
    # External app-specific (no permissions, Android 4.4+)
    try:
        from jnius import autoclass
        ctx = autoclass("org.kivy.android.PythonActivity").mActivity
        ext = ctx.getExternalFilesDir(None)
        if ext:
            d = ext.getAbsolutePath(); os.makedirs(d, exist_ok=True); return d
    except Exception: pass
    # Desktop fallback
    for d in [os.path.expanduser("~/.wbsberlin"), "."]:
        try:
            os.makedirs(d, exist_ok=True); return d
        except Exception: pass
    return "."

_DIR = _find_dir()
log(f"data dir: {_DIR}")

# ══════════════════════════════════════════════════════════════
# STEP 4: Database
# ══════════════════════════════════════════════════════════════
_DL = threading.RLock()

def _db():
    c = sqlite3.connect(os.path.join(_DIR,"wbs.db"), timeout=5, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL"); c.execute("PRAGMA busy_timeout=3000")
    return c

DDL = """
CREATE TABLE IF NOT EXISTS listings(
    id TEXT PRIMARY KEY, url TEXT, source TEXT, title TEXT,
    price REAL, rooms REAL, size_m2 REAL, floor_ TEXT,
    available TEXT, location TEXT, wbs_label TEXT, wbs_level INTEGER,
    features TEXT DEFAULT '[]', deposit TEXT, heating TEXT,
    score INTEGER DEFAULT 0, trusted_wbs INTEGER DEFAULT 0,
    favorited INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, ts_found REAL
);
CREATE INDEX IF NOT EXISTS i_ts  ON listings(ts_found DESC);
CREATE INDEX IF NOT EXISTS i_fav ON listings(favorited);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS st(
    id INTEGER PRIMARY KEY CHECK(id=1),
    total INT DEFAULT 0, opens INT DEFAULT 0, last_check REAL
);
INSERT OR IGNORE INTO st(id) VALUES(1);
"""

def init_db():
    with _DL:
        c = _db()
        try: c.executescript(DDL); c.commit(); log("db ok")
        finally: c.close()

def kv_get(k, d=None):
    try:
        with _DL:
            c = _db()
            try:
                r = c.execute("SELECT value FROM kv WHERE key=?",(k,)).fetchone()
                return json.loads(r[0]) if r else d
            finally: c.close()
    except Exception: return d

def kv_set(k, v):
    try:
        with _DL:
            c = _db()
            try:
                c.execute("INSERT OR REPLACE INTO kv VALUES(?,?)",(k,json.dumps(v,ensure_ascii=False)))
                c.commit()
            finally: c.close()
    except Exception as e: log(f"kv_set:{e}")

def save_listing(l):
    lid = l.get("id")
    if not lid: return False
    try:
        with _DL:
            c = _db()
            try:
                if c.execute("SELECT 1 FROM listings WHERE id=?",(lid,)).fetchone():
                    return False
                feats = json.dumps(l.get("features") or [], ensure_ascii=False)
                c.execute(
                    "INSERT OR IGNORE INTO listings"
                    "(id,url,source,title,price,rooms,size_m2,floor_,available,"
                    "location,wbs_label,wbs_level,features,deposit,heating,"
                    "score,trusted_wbs,ts_found) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (lid,l.get("url"),l.get("source"),l.get("title"),
                     l.get("price"),l.get("rooms"),l.get("size_m2"),
                     l.get("floor"),l.get("available"),l.get("location"),
                     l.get("wbs_label"),l.get("wbs_level_num"),feats,
                     l.get("deposit"),l.get("heating"),
                     l.get("score",0),1 if l.get("trusted_wbs") else 0,time.time()))
                c.execute("UPDATE st SET total=total+1 WHERE id=1")
                c.commit(); return True
            finally: c.close()
    except Exception as e: log(f"save:{e}"); return False

def get_rows(limit=300):
    try:
        with _DL:
            c = _db()
            try:
                rows = c.execute("SELECT * FROM listings WHERE hidden=0 ORDER BY ts_found DESC LIMIT ?",(limit,)).fetchall()
                cols = [d[0] for d in c.description]
                return [dict(zip(cols,r)) for r in rows]
            finally: c.close()
    except Exception as e: log(f"get_rows:{e}"); return []

def toggle_fav(lid):
    try:
        with _DL:
            c = _db()
            try:
                r = c.execute("SELECT favorited FROM listings WHERE id=?",(lid,)).fetchone()
                if r:
                    nv = 0 if r[0] else 1
                    c.execute("UPDATE listings SET favorited=? WHERE id=?",(nv,lid))
                    c.commit(); return bool(nv)
            finally: c.close()
    except Exception as e: log(f"fav:{e}")
    return False

def hide_row(lid):
    try:
        with _DL:
            c = _db()
            try: c.execute("UPDATE listings SET hidden=1 WHERE id=?",(lid,)); c.commit()
            finally: c.close()
    except Exception as e: log(f"hide:{e}")

def get_favs():
    try:
        with _DL:
            c = _db()
            try:
                rows = c.execute("SELECT * FROM listings WHERE favorited=1 ORDER BY ts_found DESC LIMIT 100").fetchall()
                cols = [d[0] for d in c.description]
                return [dict(zip(cols,r)) for r in rows]
            finally: c.close()
    except Exception: return []

def get_stats():
    try:
        with _DL:
            c = _db()
            try:
                r     = c.execute("SELECT * FROM st WHERE id=1").fetchone()
                total = c.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
                favs  = c.execute("SELECT COUNT(*) FROM listings WHERE favorited=1").fetchone()[0]
                new7  = c.execute("SELECT COUNT(*) FROM listings WHERE ts_found>?",(time.time()-7*86400,)).fetchone()[0]
                by_src= {row[0]:row[1] for row in c.execute("SELECT source,COUNT(*) FROM listings GROUP BY source")}
                return {"total":r[1] if r else 0,"opens":r[2] if r else 0,
                        "last_check":r[3] if r else None,"db":total,
                        "favs":favs,"new7":new7,"by_src":by_src}
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
    cut = time.time()-days*86400
    try:
        with _DL:
            c = _db()
            try: c.execute("DELETE FROM listings WHERE ts_found<? AND favorited=0",(cut,)); c.commit()
            finally: c.close()
    except Exception: pass

# ══════════════════════════════════════════════════════════════
# STEP 5: Config
# ══════════════════════════════════════════════════════════════
THEMES = {
    "غامق":   {"bg":"#080B14","bg2":"#0F1623","bg3":"#16202E","bg4":"#1E2D40","tx1":"#E8F0FE","tx2":"#8FA3BF","tx3":"#4A6080","div":"#1E2D40"},
    "رمادي":  {"bg":"#0D0D0D","bg2":"#161616","bg3":"#202020","bg4":"#2A2A2A","tx1":"#F5F5F5","tx2":"#A0A0A0","tx3":"#606060","div":"#2A2A2A"},
    "بحري":   {"bg":"#060D1F","bg2":"#0A1628","bg3":"#112040","bg4":"#1A305A","tx1":"#DCE8FF","tx2":"#7A9CC4","tx3":"#3D6080","div":"#1A305A"},
    "زمردي":  {"bg":"#060E0A","bg2":"#0A1810","bg3":"#0F2218","bg4":"#163020","tx1":"#D4F0E0","tx2":"#68A882","tx3":"#2E6050","div":"#163020"},
    "فاتح":   {"bg":"#F0F4FF","bg2":"#FFFFFF","bg3":"#E8EDF5","bg4":"#D8E0EE","tx1":"#0D1B2A","tx2":"#4A6080","tx3":"#8FA3BF","div":"#D0D8E8"},
}
ACCENTS = {
    "أخضر نيون":"#00FF87","أزرق برقي":"#00B4FF","بنفسجي":"#A855F7",
    "وردي":"#FF2D78","برتقالي":"#FF6B00","سماوي":"#00D4D4",
    "ذهبي":"#FFD700","أخضر":"#22C55E","أزرق":"#3B82F6","أحمر":"#EF4444",
}
FONT_SIZES = {"صغير":0.82,"عادي":1.0,"كبير":1.18,"كبير جداً":1.35}
SORT_OPTIONS = [
    ("score","🏅","الأفضل"),("price_asc","💰↑","أرخص"),
    ("price_desc","💰↓","أغلى"),("newest","🕐","أحدث"),
    ("rooms","🛏","غرف"),("size","📐","مساحة"),
]
DEF = {
    "max_price":700,"min_price":0,"min_rooms":0.0,"max_rooms":0.0,
    "min_size":0,"max_size":0,
    "wbs_only":False,"wbs_level_min":0,"wbs_level_max":999,
    "household_size":1,"jobcenter_mode":False,"wohngeld_mode":False,
    "sources":[],"areas":[],"sort_by":"score",
    "bg_interval":30,"notifications":True,
    "accent":"أخضر نيون","theme":"غامق","font_size":"عادي",
    "purge_days":60,"compact_cards":False,
}
def load_cfg():
    s=kv_get("cfg",{})
    return {**DEF,**(s if isinstance(s,dict) else {})}
def save_cfg(c): kv_set("cfg",c)
def is_first(): return not kv_get("done",False)
def set_done(): kv_set("done",True)

# ══════════════════════════════════════════════════════════════
# STEP 6: Domain
# ══════════════════════════════════════════════════════════════
SOURCES = {
    "gewobag":("Gewobag",True),"degewo":("Degewo",True),
    "gesobau":("Gesobau",True),"wbm":("WBM",True),
    "vonovia":("Vonovia",True),"howoge":("Howoge",True),
    "berlinovo":("Berlinovo",True),"immoscout":("ImmoScout24",False),
    "kleinanz":("Kleinanzeigen",False),
}
GOV={k for k,v in SOURCES.items() if v[1]}
AREAS=["Mitte","Spandau","Pankow","Neukölln","Tempelhof","Schöneberg",
    "Steglitz","Zehlendorf","Charlottenburg","Wilmersdorf","Lichtenberg",
    "Marzahn","Hellersdorf","Treptow","Köpenick","Reinickendorf",
    "Friedrichshain","Kreuzberg","Prenzlauer Berg","Wedding","Moabit"]
JC={1:549,2:671,3:789,4:911,5:1021,6:1131}
WG={1:580,2:680,3:800,4:910,5:1030,6:1150,7:1270}
def jc(n): return JC.get(max(1,min(int(n),6)),JC[6]+(max(1,int(n))-6)*110)
def wg(n): return WG.get(max(1,min(int(n),7)),WG[7]+(max(1,int(n))-7)*120)
FEATS={"balkon":"🌿 بلكونة","terrasse":"🌿 تراس","garten":"🌱 حديقة",
    "aufzug":"🛗 مصعد","einbauküche":"🍳 مطبخ","keller":"📦 مخزن",
    "stellplatz":"🚗 موقف","tiefgarage":"🚗 جراج","barrierefrei":"♿",
    "neubau":"🏗 جديد","erstbezug":"✨ أول سكن","parkett":"🪵 باركيه",
    "fußbodenheizung":"🌡 تدفئة","fernwärme":"🌡 مركزية",
    "saniert":"🔨 مجدد","waschmaschine":"🫧 غسالة",}
MONTHS_AR={"januar":"يناير","februar":"فبراير","märz":"مارس","april":"أبريل",
    "mai":"مايو","juni":"يونيو","juli":"يوليو","august":"أغسطس",
    "september":"سبتمبر","oktober":"أكتوبر","november":"نوفمبر","dezember":"ديسمبر"}

# ══════════════════════════════════════════════════════════════
# STEP 7: Network + scrapers
# ══════════════════════════════════════════════════════════════
_CTX=ssl.create_default_context(); _CTX.check_hostname=False; _CTX.verify_mode=ssl.CERT_NONE
_UA ="Mozilla/5.0 (Linux; Android 14; SM-A536B) Chrome/124.0"

def _get(url,t=12):
    try:
        req=urllib.request.Request(url,headers={"User-Agent":_UA,"Accept-Language":"de-DE"})
        with urllib.request.urlopen(req,timeout=t,context=_CTX) as r:
            return r.read().decode(r.headers.get_content_charset("utf-8") or "utf-8","replace")
    except Exception: return None

def _getj(url,t=12):
    try:
        req=urllib.request.Request(url,headers={"User-Agent":_UA,"Accept":"application/json"})
        with urllib.request.urlopen(req,timeout=t,context=_CTX) as r: return json.loads(r.read())
    except Exception: return None

def check_net():
    try:
        s=socket.socket(socket.AF_INET,socket.SOCK_STREAM); s.settimeout(3); s.connect(("8.8.8.8",53)); s.close(); return True
    except Exception: return False

def make_id(url):
    u=re.sub(r"[?#].*","",url.strip().rstrip("/"))
    return hashlib.sha256(u.encode()).hexdigest()[:14]

def parse_price(raw):
    if not raw: return None
    s=re.sub(r"[^\d\.,]","",str(raw))
    if not s: return None
    if "," in s and "." in s: s=s.replace(".","").replace(",",".")
    elif "," in s: s=s.replace(",",".")
    elif "." in s:
        p=s.split(".")
        if len(p)==2 and len(p[1])==3: s=s.replace(".","")
    try: v=float(s); return v if 50<v<8000 else None
    except Exception: return None

def parse_rooms(raw):
    m=re.search(r"(\d+[.,]?\d*)",str(raw or "").replace(",","."))
    try: v=float(m.group(1)) if m else None; return v if v and 0.5<=v<=20 else None
    except Exception: return None

def enrich(title,desc):
    t=f"{title} {desc}".lower(); out={}
    for pat in [r"(\d[\d\.]*)\s*m[²2]",r"(\d[\d\.]*)\s*qm\b"]:
        m=re.search(pat,t)
        if m:
            try:
                v=float(m.group(1).replace(".",""))
                if 15<v<500: out["size_m2"]=v; break
            except Exception: pass
    for pat,fn in [(r"(\d+)\.\s*(?:og|etage)\b",lambda m:f"الطابق {m.group(1)}"),
                   (r"\beg\b(?!\w)|erdgeschoss",lambda _:"الطابق الأرضي"),
                   (r"\bdg\b(?!\w)|dachgeschoss",lambda _:"الطابق العلوي")]:
        mm=re.search(pat,t)
        if mm: out["floor"]=fn(mm); break
    if any(k in t for k in ["ab sofort","sofort frei","sofort verfügbar"]): out["available"]="فوري"
    else:
        m=re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",t)
        if m: out["available"]=m.group(1)
    mm=re.search(r"wbs[\s\-_]*(\d{2,3})",t)
    if mm: out["wbs_level_num"]=int(mm.group(1))
    seen=set(); feats=[]
    for kw,lb in FEATS.items():
        if kw in t and lb not in seen: seen.add(lb); feats.append(lb)
    if feats: out["features"]=feats
    return out

def _score(l):
    s=8 if l.get("trusted_wbs") else 0; s+=3 if l.get("source") in GOV else 0
    p=l.get("price")
    if p: s+=10 if p<400 else 7 if p<500 else 4 if p<600 else 1 if p<700 else 0
    r=l.get("rooms")
    if r: s+=5 if r>=3 else 3 if r>=2 else 0
    if l.get("size_m2"): s+=2
    if l.get("available")=="فوري": s+=5
    s+=min(len(l.get("features") or []),4); return s

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
               "title":i.get("title","")[:80],
               "price":parse_price(i.get("warmmiete") or i.get("totalRent")),
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
           "title":i.get("bezeichnung","")[:80],
           "price":parse_price(i.get("gesamtmiete") or i.get("miete")),
           "rooms":parse_rooms(i.get("zimmer")),"location":i.get("bezirk","Berlin"),
           "wbs_label":"WBS","ts":time.time(),**extra}
        l["score"]=_score(l); result.append(l)
    return result

_SCRAPERS={"gewobag":scrape_gewobag,"degewo":scrape_degewo,"howoge":scrape_howoge}

def fetch_all(cfg=None,timeout=25):
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
            t=threading.Thread(target=run,args=(src,fn),daemon=True); threads.append(t); t.start()
    dl=time.time()+timeout
    for t in threads: t.join(timeout=max(0.1,dl-time.time()))
    seen=set(); unique=[]
    for l in results:
        if l.get("id") and l["id"] not in seen: seen.add(l["id"]); unique.append(l)
    log(f"fetch:{len(unique)}")
    return unique

def apply_filters(listings,cfg):
    out=[]
    max_p=float(cfg.get("max_price") or 9999); min_p=float(cfg.get("min_price") or 0)
    min_r=float(cfg.get("min_rooms") or 0); max_r=float(cfg.get("max_rooms") or 0)
    min_sz=int(cfg.get("min_size") or 0); max_sz=int(cfg.get("max_size") or 0)
    wbs=bool(cfg.get("wbs_only")); wlmin=int(cfg.get("wbs_level_min") or 0); wlmax=int(cfg.get("wbs_level_max") or 999)
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

def sort_it(listings,sort_by):
    if sort_by=="price_asc":  return sorted(listings,key=lambda l:l.get("price") or 9999)
    if sort_by=="price_desc": return sorted(listings,key=lambda l:-(l.get("price") or 0))
    if sort_by=="newest":     return sorted(listings,key=lambda l:-(l.get("ts_found") or l.get("ts") or 0))
    if sort_by=="rooms":      return sorted(listings,key=lambda l:-(l.get("rooms") or 0))
    if sort_by=="size":       return sorted(listings,key=lambda l:-(l.get("size_m2") or 0))
    return sorted(listings,key=lambda l:-(l.get("score") or 0))

# Background
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

# ══════════════════════════════════════════════════════════════
# STEP 8: Kivy — import with detailed error logging
# ══════════════════════════════════════════════════════════════
log("importing kivy...")
try:
    import kivy; kivy.require("2.0.0")
    from kivy.config import Config
    Config.set("kivy","log_level","error")
    log("kivy base ok")
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
    from kivy.graphics import Color,RoundedRectangle,Rectangle,Line
    from kivy.clock import Clock
    from kivy.metrics import dp,sp
    from kivy.utils import get_color_from_hex
    from kivy.core.window import Window
    from kivy.core.text import LabelBase
    from kivy.animation import Animation
    HAS_KIVY=True; log("kivy ok")
except Exception as e:
    import traceback; log(f"KIVY FAILED: {e}"); log(traceback.format_exc()); HAS_KIVY=False

# ══════════════════════════════════════════════════════════════
# STEP 9: Design system
# ══════════════════════════════════════════════════════════════
if HAS_KIVY:
    _TH=dict(THEMES["غامق"]); _AC=[0.0,1.0,0.53,1.0]; _FS=[1.0]; _FN=["Roboto"]
    def _load_theme(cfg):
        _TH.update(THEMES.get(cfg.get("theme","غامق"),THEMES["غامق"]))
        c=get_color_from_hex(ACCENTS.get(cfg.get("accent","أخضر نيون"),"#00FF87"))
        _AC[:]=list(c); _FS[0]=FONT_SIZES.get(cfg.get("font_size","عادي"),1.0)
    def BG():  return get_color_from_hex(_TH["bg"])
    def BG2(): return get_color_from_hex(_TH["bg2"])
    def BG3(): return get_color_from_hex(_TH["bg3"])
    def BG4(): return get_color_from_hex(_TH["bg4"])
    def TX1(): return get_color_from_hex(_TH["tx1"])
    def TX2(): return get_color_from_hex(_TH["tx2"])
    def TX3(): return get_color_from_hex(_TH["tx3"])
    def DIV(): return get_color_from_hex(_TH["div"])
    def AC():  return tuple(_AC)
    def FN():  return _FN[0]
    def fs(n): return sp(n*_FS[0])
    _PUR=get_color_from_hex("#A855F7"); _BLU=get_color_from_hex("#3B82F6")
    _AMB=get_color_from_hex("#F59E0B"); _RED=get_color_from_hex("#EF4444")
    _GLD=get_color_from_hex("#FFD700"); _GRN=get_color_from_hex("#22C55E")
    WH=(1,1,1,1); NO=(0,0,0,0)

    def bg(w,col,r=0):
        w.canvas.before.clear()
        with w.canvas.before:
            Color(*col)
            rect=(RoundedRectangle(pos=w.pos,size=w.size,radius=[dp(r)]) if r else Rectangle(pos=w.pos,size=w.size))
        def u(*_): rect.pos=w.pos; rect.size=w.size
        w.bind(pos=u,size=u)

    def outline(w,col,r=0,lw=1.2):
        with w.canvas.after:
            Color(*col); Line(rounded_rectangle=(w.x,w.y,w.width,w.height,dp(r)),width=lw)
        def u(*_):
            w.canvas.after.clear()
            with w.canvas.after: Color(*col); Line(rounded_rectangle=(w.x,w.y,w.width,w.height,dp(r)),width=lw)
        w.bind(pos=u,size=u)

    def lb(text,sz=14,col=None,bold=False,align="right",**kw):
        col=col or TX1()
        try: txt=ar(str(text or ""))
        except Exception: txt=str(text or "")
        w=Label(text=txt,font_size=fs(sz),color=col,bold=bold,halign=align,font_name=FN(),**kw)
        w.bind(width=lambda *_:setattr(w,"text_size",(w.width,None)))
        return w

    def bt(text,cb=None,col=None,tc=None,h=48,r=14,**kw):
        col=col or AC(); tc=tc or WH
        try: txt=ar(str(text or ""))
        except Exception: txt=str(text or "")
        b=Button(text=txt,size_hint_y=None,height=dp(h),background_color=NO,
                 color=tc,font_size=fs(14),bold=True,font_name=FN(),**kw)
        bg(b,col,r=r)
        if cb: b.bind(on_press=cb)
        return b

    def ghost_bt(text,cb=None,col=None,h=40,r=12,**kw):
        col=col or AC()
        try: txt=ar(str(text or ""))
        except Exception: txt=str(text or "")
        b=Button(text=txt,size_hint_y=None,height=dp(h),background_color=NO,
                 color=col,font_size=fs(13),bold=True,font_name=FN(),**kw)
        bg(b,(*col[:3],0.08),r=r); outline(b,(*col[:3],0.5),r=r)
        if cb: b.bind(on_press=cb)
        return b

    def icon_bt(icon,cb=None,col=None,size=44,r=12,**kw):
        col=col or BG3()
        b=Button(text=icon,size_hint=(None,None),size=(dp(size),dp(size)),
                 background_color=NO,color=TX2(),font_size=fs(18),**kw)
        bg(b,col,r=r)
        if cb: b.bind(on_press=cb)
        return b

    def chip_btn(text,active=False,col=None,on_toggle=None,h=30,r=20,**kw):
        col=col or AC()
        b=ToggleButton(text=ar(str(text)),state="down" if active else "normal",
                       background_color=NO,color=TX1() if active else TX2(),
                       font_size=fs(11),bold=active,font_name=FN(),size_hint_y=None,height=dp(h),**kw)
        def upd(inst,state):
            on=state=="down"; bg(inst,(*col[:3],0.82) if on else BG3(),r=r)
            inst.color=TX1() if on else TX2(); inst.bold=on
            if on_toggle: on_toggle(on)
        upd(b,b.state); b.bind(state=upd)
        return b

    def gp(h=8): return Widget(size_hint_y=None,height=dp(h))
    def hdiv():
        w=Widget(size_hint_y=None,height=dp(1)); bg(w,DIV()); return w

    def inp(val,filt="int",hint="",**kw):
        t=TextInput(text=str(val),input_filter=filt,multiline=False,
                    background_color=NO,foreground_color=TX1(),cursor_color=AC(),
                    hint_text_color=TX3(),font_size=fs(14),hint_text=hint,**kw)
        bg(t,BG3(),r=12); outline(t,(*AC()[:3],0.3),r=12)
        return t

    def si(t,d=0):
        try: return int(float(t.text or d))
        except Exception: return d
    def sf(t,d=0.0):
        try: return float(t.text or d)
        except Exception: return d

    def pill(text,col,alpha=0.18,sz=10,h=22,w_=None):
        ww=w_ or dp(len(str(text))*7+16)
        b=BoxLayout(size_hint=(None,None),size=(ww,dp(h)),padding=(dp(6),0))
        bg(b,(*col[:3],alpha),r=h//2)
        b.add_widget(lb(text,sz=sz,col=col,size_hint_y=None,height=dp(h)))
        return b

    def sec_hdr(text,col=None):
        row=BoxLayout(size_hint_y=None,height=dp(38),padding=(dp(2),dp(6)))
        row.add_widget(lb(text,sz=11,col=col or TX3(),bold=True)); return row

    def navbar(app_ref,active):
        TABS=[("🏠","main","الرئيسية"),("⭐","favs","المفضلة"),
              ("📊","stats","إحصائيات"),("⚙️","cfg","إعدادات")]
        bar=BoxLayout(size_hint_y=None,height=dp(62)); bg(bar,BG2())
        with bar.canvas.after:
            Color(*(*AC()[:3],0.25)); Line(points=[0,bar.height,bar.width,bar.height],width=1)
        for icon,name,label in TABS:
            on=name==active
            try: txt=f"{icon}\n{ar(label)}"
            except Exception: txt=f"{icon}\n{label}"
            b=Button(text=txt,background_color=NO,color=AC() if on else TX3(),
                     font_size=fs(9 if not on else 10),bold=on,font_name=FN())
            bg(b,(*AC()[:3],0.08) if on else NO)
            n=name; b.bind(on_press=lambda _,n=n:setattr(app_ref.sm,"current",n))
            bar.add_widget(b)
        return bar

    # ── Listing Card ──────────────────────────────────────────────
    class ListingCard(BoxLayout):
        def __init__(self,l,compact=False,**kw):
            super().__init__(orientation="vertical",size_hint_y=None,
                             padding=(dp(14),dp(12)),spacing=dp(6),**kw)
            name,gov=SOURCES.get(l.get("source",""),("?",False))
            sc=_PUR if gov else _BLU; is_fav=bool(l.get("favorited"))
            price=l.get("price"); rooms=l.get("rooms"); sz=l.get("size_m2")
            avail=l.get("available",""); floor_=l.get("floor_") or l.get("floor","")
            dep=l.get("deposit",""); heat=l.get("heating","")
            try: feats=json.loads(l["features"]) if isinstance(l.get("features"),str) else (l.get("features") or [])
            except Exception: feats=[]
            feats=feats[:6 if not compact else 3]
            title=(l.get("title") or "شقة").strip()[:65]
            wlnum=l.get("wbs_level") or l.get("wbs_level_num")
            wlbl=f"WBS {wlnum}" if wlnum else ("WBS ✓" if l.get("trusted_wbs") else "")
            sc_=l.get("score",0); self.url=l.get("url",""); self.lid=l.get("id","")
            n_fr=max(1,(len(feats)+2)//3) if feats else 0
            extra_h=dp(20) if (dep or heat) else 0
            self.height=dp((126 if compact else 160)+n_fr*22)+extra_h
            bg(self,BG2(),r=18)
            if sc_>=20: outline(self,(*AC()[:3],0.4),r=18)
            # Header
            r1=BoxLayout(size_hint_y=None,height=dp(26),spacing=dp(6))
            r1.add_widget(pill(("🏛 " if gov else "🔍 ")+ar(name),sc,h=24))
            if sc_>=22: r1.add_widget(pill("⭐⭐⭐",_GLD,h=24,w_=dp(54)))
            elif sc_>=16: r1.add_widget(pill("⭐⭐",_GLD,h=24,w_=dp(44)))
            elif sc_>=10: r1.add_widget(pill("⭐",_GLD,h=24,w_=dp(34)))
            r1.add_widget(Widget())
            if wlbl: r1.add_widget(pill(wlbl,AC(),alpha=0.22,sz=10,h=24,w_=dp(74)))
            self._fb=Button(text="★" if is_fav else "☆",size_hint=(None,None),size=(dp(30),dp(24)),
                            background_color=NO,color=_GLD if is_fav else TX3(),font_size=sp(17))
            self._fb.bind(on_press=self._fav); r1.add_widget(self._fb)
            self.add_widget(r1)
            self.add_widget(lb(title,sz=13,bold=True,size_hint_y=None,height=dp(22)))
            if not compact or avail:
                r2=BoxLayout(size_hint_y=None,height=dp(18))
                r2.add_widget(lb("📍 "+ar(l.get("location","Berlin")),sz=10,col=TX2()))
                if avail: r2.add_widget(lb(ar("فوري 🔥" if avail=="فوري" else avail),sz=10,col=_AMB if avail=="فوري" else TX2()))
                self.add_widget(r2)
            self.add_widget(hdiv())
            r3=BoxLayout(size_hint_y=None,height=dp(34),spacing=dp(6))
            if price:
                ppm=f" ·{price/sz:.0f}€/m²" if sz else ""
                pp=BoxLayout(size_hint=(None,None),size=(dp(126),dp(30)),padding=(dp(8),0))
                bg(pp,(*AC()[:3],0.20),r=10)
                pp.add_widget(lb(f"💰 {price:.0f}€{ppm}",sz=12,col=AC(),bold=True,size_hint_y=None,height=dp(30)))
                r3.add_widget(pp)
            for icon,val in [("🛏",f"{rooms:.0f}" if rooms else None),
                              ("📐",f"{sz:.0f}m²" if sz else None),
                              ("",ar(floor_) if floor_ else None)]:
                if val:
                    db=BoxLayout(size_hint=(None,None),size=(dp(66),dp(28)),padding=(dp(5),0))
                    bg(db,BG3(),r=9)
                    db.add_widget(lb(f"{icon} {val}".strip(),sz=10,col=TX1(),size_hint_y=None,height=dp(28)))
                    r3.add_widget(db)
            r3.add_widget(Widget()); self.add_widget(r3)
            if dep or heat:
                rx=BoxLayout(size_hint_y=None,height=dp(18))
                if dep:  rx.add_widget(lb("💼 "+ar(dep),sz=10,col=TX2()))
                if heat: rx.add_widget(lb(ar(heat),sz=10,col=TX2()))
                self.add_widget(rx)
            if feats:
                fg=GridLayout(cols=3,size_hint_y=None,height=dp(n_fr*22),spacing=dp(4))
                for f in feats:
                    fc=BoxLayout(size_hint_y=None,height=dp(20),padding=(dp(5),0)); bg(fc,BG3(),r=8)
                    fc.add_widget(lb(ar(f),sz=9,col=TX2(),size_hint_y=None,height=dp(20)))
                    fg.add_widget(fc)
                self.add_widget(fg)
            ab=BoxLayout(size_hint_y=None,height=dp(36),spacing=dp(8))
            ab.add_widget(bt("فتح الإعلان ←",cb=self._open,h=36,r=10))
            ab.add_widget(ghost_bt("إخفاء",cb=self._hide,col=TX3(),h=36,r=10,size_hint_x=None,width=dp(78)))
            self.add_widget(ab)

        def _fav(self,*_):
            if not self.lid: return
            nv=toggle_fav(self.lid); self._fb.color=_GLD if nv else TX3(); self._fb.text="★" if nv else "☆"

        def _hide(self,*_):
            if self.lid: hide_row(self.lid)
            Animation(opacity=0,height=0,duration=0.22,t="out_quad").start(self)

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

    # ── Main Screen ────────────────────────────────────────────
    class MainScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="main",**kw)
            self.app=app; self._lock=threading.RLock()
            self._busy=False; self._raw=[]; self._compact=False
            bg(self,BG()); self._ui()
        def _ui(self):
            cfg=load_cfg(); self._compact=bool(cfg.get("compact_cards"))
            root=BoxLayout(orientation="vertical")
            bar=BoxLayout(size_hint_y=None,height=dp(60),padding=(dp(14),dp(10)),spacing=dp(8))
            bg(bar,BG2())
            trow=BoxLayout(orientation="vertical",size_hint_x=0.45)
            trow.add_widget(lb("WBS Berlin",sz=15,bold=True,col=AC()))
            trow.add_widget(lb("شقق برلين المدعومة",sz=9,col=TX3()))
            bar.add_widget(trow); bar.add_widget(Widget())
            sort_icons={k:i for k,i,_ in SORT_OPTIONS}
            self._sb=icon_bt(sort_icons.get(cfg.get("sort_by","score"),"🏅"),cb=self._cycle_sort,size=40)
            bar.add_widget(self._sb)
            self._cb=icon_bt("▦" if self._compact else "▤",cb=self._toggle_compact,size=40)
            bar.add_widget(self._cb)
            self._rb=bt("🔄",cb=self._go,col=AC(),size_hint_x=None,h=40,width=dp(46),r=12)
            bar.add_widget(self._rb); root.add_widget(bar)
            fs_=BoxLayout(size_hint_y=None,height=dp(46),padding=(dp(10),dp(7)),spacing=dp(8))
            bg(fs_,BG2())
            self._wbs_c=chip_btn(ar("✅ WBS"),active=bool(cfg.get("wbs_only")),col=AC(),
                                  on_toggle=self._wbs_toggled,size_hint_x=None,width=dp(88))
            fs_.add_widget(self._wbs_c)
            self._stlb=lb("اضغط 🔄 للبحث",sz=11,col=TX2(),size_hint_y=None,height=dp(28))
            fs_.add_widget(self._stlb); fs_.add_widget(Widget())
            self._bgi=Label(text="⏸",font_size=sp(18),color=TX3(),size_hint=(None,None),size=(dp(28),dp(28)))
            fs_.add_widget(self._bgi); root.add_widget(fs_); root.add_widget(hdiv())
            self._cl=BoxLayout(orientation="vertical",spacing=dp(10),padding=(dp(10),dp(10)),size_hint_y=None)
            self._cl.bind(minimum_height=self._cl.setter("height"))
            sv=ScrollView(bar_color=(*AC()[:3],0.5),bar_inactive_color=(0,0,0,0))
            sv.add_widget(self._cl); root.add_widget(sv)
            root.add_widget(navbar(self.app,"main")); self.add_widget(root)
            self._ph("🔍",ar("اضغط 🔄 للبحث عن شقق WBS"))
        def on_enter(self,*_): Clock.schedule_interval(self._tick,8)
        def on_leave(self,*_): Clock.unschedule(self._tick)
        def _tick(self,*_):
            try:
                on=is_bg(); self._bgi.text="🟢" if on else "⏸"; self._bgi.color=AC() if on else TX3()
            except Exception: pass
        def _wbs_toggled(self,active):
            cfg=load_cfg(); cfg["wbs_only"]=active; save_cfg(cfg)
            with self._lock: raw=list(self._raw)
            if raw:
                shown=sort_it(apply_filters(raw,cfg),cfg.get("sort_by","score"))
                Clock.schedule_once(lambda dt:self._render(shown,len(raw)))
        def _toggle_compact(self,*_):
            self._compact=not self._compact; self._cb.text="▦" if self._compact else "▤"
            cfg=load_cfg(); cfg["compact_cards"]=self._compact; save_cfg(cfg)
            with self._lock: raw=list(self._raw)
            if raw:
                cfg2=load_cfg(); shown=sort_it(apply_filters(raw,cfg2),cfg2.get("sort_by","score"))
                Clock.schedule_once(lambda dt:self._render(shown,len(raw)))
        def _cycle_sort(self,*_):
            keys=[k for k,_,_ in SORT_OPTIONS]; icons={k:i for k,i,_ in SORT_OPTIONS}
            cfg=load_cfg(); cur=cfg.get("sort_by","score"); nxt=keys[(keys.index(cur)+1)%len(keys)]
            cfg["sort_by"]=nxt; save_cfg(cfg); self._sb.text=icons[nxt]
            with self._lock: raw=list(self._raw)
            if raw:
                shown=sort_it(apply_filters(raw,cfg),nxt); Clock.schedule_once(lambda dt:self._render(shown,len(raw)))
        def _ph(self,icon,msg):
            self._cl.clear_widgets()
            b=BoxLayout(orientation="vertical",spacing=dp(14),size_hint_y=None,height=dp(210),padding=dp(44))
            b.add_widget(Label(text=icon,font_size=sp(52),size_hint_y=None,height=dp(70)))
            b.add_widget(lb(msg,sz=14,col=TX2(),size_hint_y=None,height=dp(50)))
            self._cl.add_widget(b)
        def _go(self,*_):
            with self._lock:
                if self._busy: return
                self._busy=True
            if not check_net():
                cached=get_rows()
                with self._lock: self._busy=False
                if cached:
                    self._stlb.text=ar("📦 من قاعدة البيانات")
                    with self._lock: self._raw=cached
                    cfg=load_cfg(); shown=sort_it(apply_filters(cached,cfg),cfg.get("sort_by","score"))
                    Clock.schedule_once(lambda dt:self._render(shown,len(cached)))
                else: self._ph("📵",ar("لا يوجد اتصال"))
                return
            self._stlb.text=ar("⏳ جاري البحث..."); self._ph("⏳",ar("جاري جلب الإعلانات..."))
            threading.Thread(target=self._fetch,daemon=True).start()
        def _fetch(self):
            try:
                cfg=load_cfg(); raw=fetch_all(cfg,timeout=25)
                nc=sum(1 for l in raw if save_listing(l)); all_db=get_rows()
                with self._lock: self._raw=all_db
                shown=sort_it(apply_filters(all_db,cfg),cfg.get("sort_by","score"))
                Clock.schedule_once(lambda dt:self._render(shown,len(all_db),nc))
            except Exception as e:
                log(f"_fetch:{e}"); Clock.schedule_once(lambda dt:self._ph("⚠️",ar(f"خطأ: {str(e)[:50]}")))
            finally:
                with self._lock: self._busy=False
        def _render(self,lst,total=None,nc=0):
            try:
                self._cl.clear_widgets(); t=total if total is not None else len(lst)
                if not lst: self._stlb.text=ar(f"لا إعلانات ({t})"); self._ph("🔍",ar("لا توجد إعلانات")); return
                ns=f" · +{nc} جديد" if nc else ""; self._stlb.text=ar(f"✅ {len(lst)} إعلان{ns}")
                for l in lst[:12]: self._cl.add_widget(ListingCard(l,compact=self._compact)); self._cl.add_widget(gp(6))
                if len(lst)>12: Clock.schedule_once(lambda dt:self._rest(lst[12:]),0.08)
            except Exception as e: log(f"_render:{e}")
        def _rest(self,rest):
            try:
                for l in rest[:60]: self._cl.add_widget(ListingCard(l,compact=self._compact)); self._cl.add_widget(gp(6))
            except Exception: pass

    class FavsScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="favs",**kw); self.app=app; bg(self,BG()); self._build()
        def _build(self):
            self.clear_widgets(); root=BoxLayout(orientation="vertical")
            bar=BoxLayout(size_hint_y=None,height=dp(60),padding=(dp(14),dp(10)),spacing=dp(10)); bg(bar,BG2())
            bar.add_widget(lb("⭐ "+ar("المفضلة"),sz=16,bold=True,col=_GLD)); bar.add_widget(Widget())
            bar.add_widget(icon_bt("🔄",cb=self._load,size=40)); root.add_widget(bar)
            self._cl=BoxLayout(orientation="vertical",spacing=dp(10),padding=(dp(10),dp(10)),size_hint_y=None)
            self._cl.bind(minimum_height=self._cl.setter("height"))
            sv=ScrollView(bar_color=(*_GLD[:3],0.5),bar_inactive_color=(0,0,0,0)); sv.add_widget(self._cl)
            root.add_widget(sv); root.add_widget(navbar(self.app,"favs")); self.add_widget(root); self._load()
        def on_enter(self,*_): self._load()
        def _load(self,*_):
            self._cl.clear_widgets(); favs=get_favs()
            if not favs:
                b=BoxLayout(orientation="vertical",size_hint_y=None,height=dp(200),padding=dp(44))
                b.add_widget(Label(text="⭐",font_size=sp(52),size_hint_y=None,height=dp(70)))
                b.add_widget(lb("لا توجد مفضلة بعد",sz=14,col=TX2(),size_hint_y=None,height=dp(50)))
                self._cl.add_widget(b); return
            for l in favs: self._cl.add_widget(ListingCard(l)); self._cl.add_widget(gp(6))

    class StatsScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="stats",**kw); self.app=app; bg(self,BG()); self._build()
        def on_enter(self,*_): self._build()
        def _build(self):
            self.clear_widgets(); st=get_stats()
            root=BoxLayout(orientation="vertical")
            bar=BoxLayout(size_hint_y=None,height=dp(60),padding=(dp(14),dp(10))); bg(bar,BG2())
            bar.add_widget(lb("📊 "+ar("الإحصائيات"),sz=16,bold=True,col=WH)); root.add_widget(bar)
            sc=ScrollView(); body=BoxLayout(orientation="vertical",padding=dp(14),spacing=dp(10),size_hint_y=None)
            body.bind(minimum_height=body.setter("height"))
            def ts(t):
                if not t: return "—"
                try:
                    import datetime; return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M")
                except Exception: return "—"
            sr=BoxLayout(size_hint_y=None,height=dp(90),spacing=dp(8))
            def mc(icon,val,lbl_t,col):
                c=BoxLayout(orientation="vertical",padding=(dp(12),dp(10)),spacing=dp(4)); bg(c,BG2(),r=16)
                c.add_widget(Label(text=icon,font_size=sp(22),size_hint_y=None,height=dp(28)))
                c.add_widget(lb(str(val),sz=18,bold=True,col=col,size_hint_y=None,height=dp(26)))
                c.add_widget(lb(ar(lbl_t),sz=9,col=TX3(),size_hint_y=None,height=dp(18)))
                return c
            sr.add_widget(mc("🏠",st.get("db",0),"محفوظ",AC()))
            sr.add_widget(mc("🆕",st.get("new7",0),"هذا الأسبوع",_GRN))
            sr.add_widget(mc("⭐",st.get("favs",0),"مفضلة",_GLD))
            sr.add_widget(mc("📱",st.get("opens",0),"فتحات",_PUR))
            body.add_widget(sr)
            lc=BoxLayout(size_hint_y=None,height=dp(48),padding=(dp(14),dp(8))); bg(lc,BG2(),r=14)
            lc.add_widget(lb("🕐 "+ar("آخر فحص:"),sz=12,col=TX2(),size_hint_x=0.45))
            lc.add_widget(lb(ts(st.get("last_check")),sz=12,col=TX1(),align="left")); body.add_widget(lc)
            # Log file location
            if _LOG:
                lf=BoxLayout(size_hint_y=None,height=dp(48),padding=(dp(14),dp(8))); bg(lf,BG2(),r=14)
                lf.add_widget(lb("📋 "+ar("سجل التطبيق:"),sz=11,col=TX2(),size_hint_x=0.35))
                lf.add_widget(lb(_LOG,sz=10,col=TX3(),align="left")); body.add_widget(lf)
            body.add_widget(gp(4)); body.add_widget(sec_hdr("📡  المصادر"))
            by_src=st.get("by_src",{}); max_cnt=max(by_src.values()) if by_src else 1
            for src,(name,gov) in SOURCES.items():
                cnt=by_src.get(src,0)
                row=BoxLayout(size_hint_y=None,height=dp(44),padding=(dp(12),dp(6)),spacing=dp(8)); bg(row,BG2(),r=12)
                sc_=_PUR if gov else _BLU
                row.add_widget(lb(("🏛 " if gov else "🔍 ")+ar(name),sz=12,col=sc_,size_hint_x=0.5))
                prog=BoxLayout(size_hint=(0.35,None),height=dp(8)); bg(prog,BG3(),r=4)
                fw=max(0.04,cnt/max(max_cnt,1))
                fill=Widget(size_hint=(fw,1)); bg(fill,sc_,r=4); prog.add_widget(fill)
                prog.add_widget(Widget(size_hint=(1-fw,1))); row.add_widget(prog)
                row.add_widget(lb(str(cnt),sz=13,bold=True,col=AC(),size_hint_x=0.15,align="left"))
                body.add_widget(row)
            body.add_widget(gp(12))
            body.add_widget(bt("🗑 "+ar("مسح الإعلانات"),cb=self._clear,col=_RED,h=48,r=14))
            body.add_widget(gp(24)); sc.add_widget(body); root.add_widget(sc)
            root.add_widget(navbar(self.app,"stats")); self.add_widget(root)
        def _clear(self,*_):
            try:
                with _DL:
                    c=_db()
                    try: c.execute("DELETE FROM listings WHERE favorited=0"); c.execute("UPDATE st SET total=0 WHERE id=1"); c.commit()
                    finally: c.close()
            except Exception as e: log(f"clear:{e}")
            self._build()

    class CfgScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="cfg",**kw); self.app=app; bg(self,BG()); self._build()
        def _build(self):
            self.clear_widgets(); cfg=load_cfg()
            root=BoxLayout(orientation="vertical")
            hdr=BoxLayout(size_hint_y=None,height=dp(60),padding=(dp(14),dp(10)),spacing=dp(10)); bg(hdr,BG2())
            hdr.add_widget(lb("⚙️ "+ar("الإعدادات"),sz=16,bold=True,col=WH)); hdr.add_widget(Widget())
            hdr.add_widget(ghost_bt("↩️ "+ar("افتراضي"),cb=self._reset,col=TX2(),h=36,r=12,size_hint_x=None,width=dp(100)))
            root.add_widget(hdr)
            sc=ScrollView(); body=BoxLayout(orientation="vertical",padding=dp(14),spacing=dp(10),size_hint_y=None)
            body.bind(minimum_height=body.setter("height"))
            def row(lbl_t,w,hint=""):
                r=BoxLayout(size_hint_y=None,height=dp(58),spacing=dp(12),padding=(dp(14),dp(7))); bg(r,BG2(),r=14)
                lbox=BoxLayout(orientation="vertical",size_hint_x=0.46)
                lbox.add_widget(lb(lbl_t,sz=13,col=TX1()))
                if hint: lbox.add_widget(lb(hint,sz=10,col=TX3()))
                r.add_widget(lbox); r.add_widget(w); body.add_widget(r)
            def tog(text,active,pri=None,h=44):
                pri=pri or AC()
                t=ToggleButton(text=ar(text),state="down" if active else "normal",
                    size_hint=(1,None),height=dp(h),background_color=NO,color=TX1(),font_size=fs(12),font_name=FN())
                bg(t,(*pri[:3],0.18) if active else BG2(),r=14)
                t.bind(state=lambda b,s,p=pri:bg(b,(*p[:3],0.18) if s=="down" else BG2(),r=14))
                body.add_widget(t); return t
            # Appearance
            body.add_widget(gp(4)); body.add_widget(sec_hdr("🎨  المظهر"))
            th_row=BoxLayout(size_hint_y=None,height=dp(52),padding=(dp(14),dp(8)),spacing=dp(8)); bg(th_row,BG2(),r=14)
            th_row.add_widget(lb("نسق:",sz=12,col=TX1(),size_hint_x=0.2)); self._thb={}; cur_th=cfg.get("theme","غامق")
            for tn in THEMES:
                on=tn==cur_th
                b=ToggleButton(text=ar(tn),state="down" if on else "normal",size_hint=(1,None),height=dp(36),
                               background_color=NO,color=TX1() if on else TX2(),font_size=fs(10),bold=on)
                bg(b,(*AC()[:3],0.22) if on else BG3(),r=10)
                b.bind(state=lambda x,s,n=tn,b=b:(bg(b,(*AC()[:3],0.22) if s=="down" else BG3(),r=10),
                    [setattr(ib,"state","normal") or bg(ib,BG3(),r=10) for in_,ib in self._thb.items() if in_!=n] if s=="down" else None))
                self._thb[tn]=b; th_row.add_widget(b)
            body.add_widget(th_row)
            acc_row=BoxLayout(size_hint_y=None,height=dp(60),padding=(dp(14),dp(10)),spacing=dp(5)); bg(acc_row,BG2(),r=14)
            acc_row.add_widget(lb("لون:",sz=12,col=TX1(),size_hint_x=0.14)); self._acb={}; cur_acc=cfg.get("accent","أخضر نيون")
            for aname,ahex in ACCENTS.items():
                acol=get_color_from_hex(ahex); on=aname==cur_acc
                b=Button(text="",size_hint=(None,None),size=(dp(32),dp(32)),background_color=NO); bg(b,acol,r=16)
                if on: outline(b,WH,r=16,lw=2)
                b.bind(on_press=lambda _,n=aname:self._sel_acc(n))
                self._acb[aname]=(b,acol); acc_row.add_widget(b)
            body.add_widget(acc_row)
            fs_row=BoxLayout(size_hint_y=None,height=dp(52),padding=(dp(14),dp(8)),spacing=dp(8)); bg(fs_row,BG2(),r=14)
            fs_row.add_widget(lb("خط:",sz=12,col=TX1(),size_hint_x=0.18)); self._fsb={}; cur_fs=cfg.get("font_size","عادي")
            for fn_ in FONT_SIZES:
                on=fn_==cur_fs
                b=ToggleButton(text=ar(fn_),state="down" if on else "normal",size_hint=(1,None),height=dp(36),
                               background_color=NO,color=TX1() if on else TX2(),font_size=fs(10),bold=on)
                bg(b,(*AC()[:3],0.22) if on else BG3(),r=10)
                b.bind(state=lambda x,s,n=fn_,b=b:(bg(b,(*AC()[:3],0.22) if s=="down" else BG3(),r=10),
                    [setattr(ib,"state","normal") or bg(ib,BG3(),r=10) for in_,ib in self._fsb.items() if in_!=n] if s=="down" else None))
                self._fsb[fn_]=b; fs_row.add_widget(b)
            body.add_widget(fs_row)
            self._compact=tog("🗜 بطاقات مضغوطة",cfg.get("compact_cards",False))
            # Budget
            body.add_widget(gp(4)); body.add_widget(sec_hdr("💰  الميزانية"))
            self._maxp=inp(cfg.get("max_price",700),hint="€"); row("أقصى إيجار (€)",self._maxp)
            self._minp=inp(cfg.get("min_price",0),hint="0=بدون"); row("الحد الأدنى (€)",self._minp,"0=بدون حد")
            body.add_widget(gp(4)); body.add_widget(sec_hdr("🛏  الغرف والمساحة"))
            def rrow(lt,w1,w2,unit):
                rr=BoxLayout(size_hint_y=None,height=dp(58),spacing=dp(6),padding=(dp(14),dp(7))); bg(rr,BG2(),r=14)
                rr.add_widget(lb(lt,sz=12,col=TX1(),size_hint_x=0.26))
                rr.add_widget(lb("من",sz=10,col=TX2(),size_hint_x=0.08)); rr.add_widget(w1)
                rr.add_widget(lb("—",sz=12,col=TX2(),size_hint_x=0.05)); rr.add_widget(w2)
                rr.add_widget(lb(unit,sz=10,col=TX3(),size_hint_x=0.12)); body.add_widget(rr)
            self._minr=inp(cfg.get("min_rooms",0),"float"); self._maxr=inp(cfg.get("max_rooms",0),"float")
            rrow("الغرف",self._minr,self._maxr,"0=أي")
            self._mins=inp(cfg.get("min_size",0)); self._maxs=inp(cfg.get("max_size",0))
            rrow("المساحة",self._mins,self._maxs,"m²")
            # WBS
            body.add_widget(gp(4)); body.add_widget(sec_hdr("📋  WBS"))
            self._wbs=tog("WBS فقط",cfg.get("wbs_only",False))
            wlr=BoxLayout(size_hint_y=None,height=dp(58),spacing=dp(6),padding=(dp(14),dp(7))); bg(wlr,BG2(),r=14)
            wlr.add_widget(lb("مستوى:",sz=12,col=TX1(),size_hint_x=0.28))
            self._wlmin=inp(cfg.get("wbs_level_min",0)); self._wlmax=inp(cfg.get("wbs_level_max",999))
            wlr.add_widget(lb("من",sz=10,col=TX2(),size_hint_x=0.08)); wlr.add_widget(self._wlmin)
            wlr.add_widget(lb("—",sz=12,col=TX2(),size_hint_x=0.06)); wlr.add_widget(self._wlmax)
            body.add_widget(wlr)
            pr=BoxLayout(size_hint_y=None,height=dp(40),spacing=dp(6))
            for lt,mn,mx in [("100","100","100"),("100-140","100","140"),("100-160","100","160"),("الكل","0","999")]:
                b=ghost_bt(lt,col=AC(),h=40,r=10,size_hint_x=None,width=dp(82))
                b.bind(on_press=lambda _,mn=mn,mx=mx:(setattr(self._wlmin,"text",mn),setattr(self._wlmax,"text",mx)))
                pr.add_widget(b)
            body.add_widget(pr)
            # Social
            body.add_widget(gp(4)); body.add_widget(sec_hdr("🏛  الفلاتر الاجتماعية"))
            self._hh=inp(cfg.get("household_size",1))
            n_=max(1,int(cfg.get("household_size") or 1))
            row("أفراد الأسرة",self._hh,f"JC≤{jc(n_):.0f}€ · WG≤{wg(n_):.0f}€")
            self._jc=tog("🏛 Jobcenter KdU",cfg.get("jobcenter_mode",False),_PUR)
            self._wg=tog("🏦 Wohngeld",cfg.get("wohngeld_mode",False),_PUR)
            # Areas
            body.add_widget(gp(4)); body.add_widget(sec_hdr("📍  المناطق"))
            cur_ar=cfg.get("areas") or []; self._ab={}
            ag=GridLayout(cols=2,size_hint_y=None,height=dp(((len(AREAS)+1)//2)*38),spacing=dp(5))
            for area in AREAS:
                on=area in cur_ar
                b=ToggleButton(text=area,state="down" if on else "normal",size_hint=(1,None),height=dp(36),background_color=NO,color=TX1(),font_size=fs(11))
                bg(b,(*_AMB[:3],0.18) if on else BG2(),r=10)
                b.bind(state=lambda x,s,b=b:bg(b,(*_AMB[:3],0.18) if s=="down" else BG2(),r=10))
                self._ab[area]=b; ag.add_widget(b)
            body.add_widget(ag)
            body.add_widget(ghost_bt("🌍 "+ar("كل برلين"),cb=lambda *_:[setattr(b,"state","normal") or bg(b,BG2(),r=10) for b in self._ab.values()],col=TX2(),h=38,r=12))
            # Sources
            body.add_widget(gp(4)); body.add_widget(sec_hdr("🌐  المصادر"))
            cur_src=cfg.get("sources") or []; self._src={}
            for sid,(sname,gov) in SOURCES.items():
                sc=_PUR if gov else _BLU; on=not cur_src or sid in cur_src
                b=ToggleButton(text=("🏛 " if gov else "🔍 ")+ar(sname),state="down" if on else "normal",
                    size_hint=(1,None),height=dp(42),background_color=NO,color=TX1(),font_size=fs(12))
                bg(b,(*sc[:3],0.18) if on else BG2(),r=12)
                b.bind(state=lambda x,s,sc=sc,b=b:bg(b,(*sc[:3],0.18) if s=="down" else BG2(),r=12))
                self._src[sid]=b; body.add_widget(b)
            qr=BoxLayout(size_hint_y=None,height=dp(40),spacing=dp(8))
            qr.add_widget(ghost_bt("✅ "+ar("الكل"),cb=lambda *_:[setattr(b,"state","down") for b in self._src.values()],col=AC(),h=40,r=12))
            qr.add_widget(ghost_bt("🏛 "+ar("حكومية"),cb=self._govsrc,col=_PUR,h=40,r=12))
            body.add_widget(qr)
            # Advanced
            body.add_widget(gp(4)); body.add_widget(sec_hdr("⚙️  متقدم"))
            self._bgi2=inp(cfg.get("bg_interval",30)); row("فترة الخلفية (دق.)",self._bgi2,"5+")
            self._pdays=inp(cfg.get("purge_days",60)); row("حذف تلقائي (يوم)",self._pdays,"60")
            bg_on=is_bg()
            self._bgb=bt("⏹ "+ar("إيقاف الخلفية") if bg_on else "▶ "+ar("تشغيل الخلفية"),
                          cb=self._togbg,col=_RED if bg_on else AC(),h=48,r=14)
            body.add_widget(gp(8)); body.add_widget(self._bgb); body.add_widget(gp(12))
            body.add_widget(bt("💾 "+ar("حفظ الإعدادات"),cb=self._save,h=56,r=16))
            body.add_widget(gp(28))
            sc.add_widget(body); root.add_widget(sc); root.add_widget(navbar(self.app,"cfg")); self.add_widget(root)
        def _sel_acc(self,name):
            for n,(b,col) in self._acb.items(): b.canvas.after.clear()
            b,col=self._acb[name]; outline(b,WH,r=16,lw=2)
        def _govsrc(self,*_):
            for sid,b in self._src.items():
                gov=SOURCES[sid][1]; sc=_PUR if gov else _BLU
                b.state="down" if gov else "normal"; bg(b,(*sc[:3],0.18) if gov else BG2(),r=12)
        def _togbg(self,*_):
            if is_bg(): stop_bg(); bg(self._bgb,AC(),r=14); self._bgb.text=ar("▶ تشغيل الخلفية")
            else: start_bg(); bg(self._bgb,_RED,r=14); self._bgb.text=ar("⏹ إيقاف الخلفية")
        def _reset(self,*_): save_cfg(dict(DEF)); self._build()
        def _save(self,*_):
            sel_src=[s for s,b in self._src.items() if b.state=="down"]
            sel_ar=[a for a,b in self._ab.items() if b.state=="down"]
            cur_th=next((n for n,b in self._thb.items() if b.state=="down"),"غامق")
            cur_acc=next((n for n,(b,c) in self._acb.items() if b.canvas.after.children),"أخضر نيون")
            cur_fs=next((n for n,b in self._fsb.items() if b.state=="down"),"عادي")
            cfg=load_cfg()
            cfg.update({"max_price":si(self._maxp,700),"min_price":si(self._minp,0),
                "min_rooms":sf(self._minr,0),"max_rooms":sf(self._maxr,0),
                "min_size":si(self._mins,0),"max_size":si(self._maxs,0),
                "household_size":max(1,si(self._hh,1)),"wbs_only":self._wbs.state=="down",
                "wbs_level_min":si(self._wlmin,0),"wbs_level_max":si(self._wlmax,999),
                "jobcenter_mode":self._jc.state=="down","wohngeld_mode":self._wg.state=="down",
                "areas":sel_ar,"sources":sel_src if len(sel_src)<len(SOURCES) else [],
                "bg_interval":max(5,si(self._bgi2,30)),"purge_days":max(7,si(self._pdays,60)),
                "compact_cards":self._compact.state=="down","theme":cur_th,"accent":cur_acc,"font_size":cur_fs})
            save_cfg(cfg); _load_theme(cfg); Window.clearcolor=BG()
            self.app.rebuild_all()

    class OnboardScreen(Screen):
        def __init__(self,app,**kw):
            super().__init__(name="onboard",**kw); self.app=app; self._i=0; self._show()
        def _show(self):
            self.clear_widgets(); bg(self,BG())
            PGS=[("🏠","WBS Berlin","ابحث عن شقق مدعومة (WBS)\nمن 9 مصادر رسمية وخاصة",AC()),
                 ("🗄","قاعدة بيانات","لا تكرار للإعلانات أبداً\nيحفظ تاريخ بحثك",_PUR),
                 ("🎨","تخصيص كامل","5 ثيمات · 10 ألوان\nفلاتر ذكية: WBS · Jobcenter",_AMB),
                 ("🔔","إشعارات فورية","يعمل في الخلفية دائماً\nلا تفوّت أي شقة",_GRN)]
            p=PGS[self._i]; last=self._i==3
            root=FloatLayout()
            card=BoxLayout(orientation="vertical",padding=dp(32),spacing=dp(16),size_hint=(0.9,0.70),pos_hint={"center_x":.5,"center_y":.56})
            bg(card,BG2(),r=24); outline(card,(*p[3][:3],0.3),r=24)
            card.add_widget(Label(text=p[0],font_size=sp(60),size_hint_y=None,height=dp(80)))
            card.add_widget(lb(p[1],sz=20,bold=True,col=p[3],size_hint_y=None,height=dp(46)))
            card.add_widget(lb(p[2],sz=13,col=TX2(),size_hint_y=None,height=dp(80)))
            dots=BoxLayout(size_hint=(None,None),size=(dp(100),dp(10)),spacing=dp(8))
            for i in range(4):
                d=Widget(size_hint=(None,None),size=(dp(24 if i==self._i else 8),dp(8)))
                bg(d,p[3] if i==self._i else BG4(),r=4); dots.add_widget(d)
            card.add_widget(dots); root.add_widget(card)
            brow=BoxLayout(size_hint=(0.9,None),height=dp(56),pos_hint={"center_x":.5,"y":.04},spacing=dp(12))
            if not last: brow.add_widget(ghost_bt("تخطي",cb=self._done,col=TX3()))
            brow.add_widget(bt("ابدأ الآن 🚀" if last else "التالي ←",cb=self._next if not last else self._done,col=p[3],h=52,r=16))
            root.add_widget(brow); self.add_widget(root)
        def _next(self,*_): self._i=min(self._i+1,3); self._show()
        def _done(self,*_): set_done(); self.app.go_main()

    class SplashScreen(Screen):
        def __init__(self,**kw):
            super().__init__(name="splash",**kw); bg(self,BG())
            root=FloatLayout()
            card=BoxLayout(orientation="vertical",padding=dp(32),spacing=dp(16),size_hint=(0.78,0.50),pos_hint={"center_x":.5,"center_y":.5})
            bg(card,BG2(),r=24); outline(card,(*AC()[:3],0.4),r=24)
            card.add_widget(Label(text="🏠",font_size=sp(60),size_hint_y=None,height=dp(78)))
            card.add_widget(lb("WBS Berlin",sz=20,bold=True,col=AC(),size_hint_y=None,height=dp(40)))
            card.add_widget(lb("v8.1",sz=12,col=TX3(),size_hint_y=None,height=dp(24)))
            card.add_widget(lb("جاري التحميل...",sz=12,col=TX2(),size_hint_y=None,height=dp(28)))
            root.add_widget(card); self.add_widget(root)

    class WBSApp(App):
        def build(self):
            log("App.build() called")
            try:
                cfg=load_cfg(); _load_theme(cfg)
                Window.clearcolor=BG()
                self.sm=ScreenManager(transition=FadeTransition(duration=0.20))
                self.sm.add_widget(SplashScreen()); self.sm.current="splash"
                Clock.schedule_once(self._init,0.2)
                log("build() done — splash shown")
                return self.sm
            except Exception as e:
                log(f"build() CRASH: {e}")
                import traceback; log(traceback.format_exc())
                # Absolute fallback: return a plain label
                return Label(text=f"WBS Berlin\nError: {e}\nCheck {_LOG}")

        def _init(self,dt):
            log("_init")
            try:
                _init_arabic()
                try:
                    fp=os.path.join(os.path.dirname(os.path.abspath(__file__)),"NotoNaskhArabic.ttf")
                    if os.path.exists(fp): LabelBase.register("NotoArabic",fn_regular=fp); _FN[0]="NotoArabic"; log("font ok")
                    else: log(f"no font: {fp}")
                except Exception as e: log(f"font:{e}")
                bump_opens()
            except Exception as e: log(f"_init err:{e}")
            Clock.schedule_once(self._show_main,0.35)

        def _show_main(self,dt):
            log("_show_main")
            try:
                if is_first(): self.sm.add_widget(OnboardScreen(self)); self.sm.current="onboard"
                else: self.go_main()
                Clock.schedule_once(lambda _:start_bg(),5.0); log("_show_main done")
            except Exception as e:
                log(f"_show_main err:{e}"); import traceback; log(traceback.format_exc())
                try: self.sm.add_widget(MainScreen(self)); self.sm.current="main"
                except Exception as e2: log(f"FATAL:{e2}")

        def go_main(self):
            for name,cls in [("main",MainScreen),("favs",FavsScreen),("stats",StatsScreen),("cfg",CfgScreen)]:
                if not any(s.name==name for s in self.sm.screens): self.sm.add_widget(cls(self))
            self.sm.current="main"

        def rebuild_all(self):
            log("rebuild_all")
            try:
                for s in [s for s in list(self.sm.screens) if s.name!="splash"]:
                    self.sm.remove_widget(s)
                for name,cls in [("main",MainScreen),("favs",FavsScreen),("stats",StatsScreen),("cfg",CfgScreen)]:
                    self.sm.add_widget(cls(self))
                self.sm.current="main"
            except Exception as e: log(f"rebuild_all err:{e}")

    if __name__=="__main__":
        log("run()")
        try: init_db(); WBSApp().run()
        except Exception as e:
            log(f"run crashed:{e}"); import traceback; log(traceback.format_exc()); raise

else:
    if __name__=="__main__":
        print("CLI"); init_db()
        raw=fetch_all(); cfg=dict(DEF)
        shown=sort_it(apply_filters(raw,cfg),"score")
        print(f"{len(shown)}/{len(raw)}")
        for l in shown[:3]:
            p=f"{l['price']:.0f}€" if l.get("price") else "—"
            print(f"  [{l['source']}] {p} | {l.get('title','')[:45]}")
