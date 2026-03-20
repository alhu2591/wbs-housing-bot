"""
WBS Berlin — Modern Onboarding App
واجهة عصرية مع Onboarding ولوحة بحث احترافية
Pure Python stdlib + beautifulsoup4 فقط
"""
import json, os, re, hashlib, threading, urllib.request, urllib.parse, ssl
from pathlib import Path

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
    from kivy.graphics import Color, RoundedRectangle, Rectangle
    from kivy.clock import Clock
    from kivy.metrics import dp, sp
    from kivy.utils import get_color_from_hex
    HAS_KIVY = True
except ImportError:
    HAS_KIVY = False

# ═══════════════════════════════════════════════════════════════════════
# Design System
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    # Primary palette
    BG       = get_color_from_hex("#0D0D0D")   # Almost black
    BG2      = get_color_from_hex("#141414")   # Card bg
    BG3      = get_color_from_hex("#1C1C1C")   # Input bg
    PRIMARY  = get_color_from_hex("#4CAF50")   # Green
    PRIMARY2 = get_color_from_hex("#2E7D32")   # Dark green
    ACCENT   = get_color_from_hex("#FFC107")   # Amber
    GOV_C    = get_color_from_hex("#7C4DFF")   # Purple for gov
    PRIV_C   = get_color_from_hex("#0288D1")   # Blue for private
    TEXT1    = get_color_from_hex("#F5F5F5")   # Primary text
    TEXT2    = get_color_from_hex("#9E9E9E")   # Secondary text
    TEXT3    = get_color_from_hex("#616161")   # Disabled
    SUCCESS  = get_color_from_hex("#4CAF50")
    WARN     = get_color_from_hex("#FF9800")
    ERROR    = get_color_from_hex("#F44336")
    DIVIDER  = get_color_from_hex("#1F1F1F")
    WHITE    = get_color_from_hex("#FFFFFF")
    TRANSP   = (0, 0, 0, 0)

# ═══════════════════════════════════════════════════════════════════════
# Storage & Config
# ═══════════════════════════════════════════════════════════════════════
_sd       = Path(os.environ.get("EXTERNAL_STORAGE", "."))
CFG_FILE  = _sd / "wbs_config.json"
SEEN_FILE = _sd / "wbs_seen.json"
FIRST_RUN = _sd / "wbs_first_run"

DEFAULTS = {
    "max_price": 700, "min_rooms": 0.0, "wbs_only": False,
    "household_size": 1, "wbs_level_min": 0, "wbs_level_max": 999,
    "jobcenter_mode": False, "sources": [], "areas": [],
}

def load_cfg():
    try:
        if CFG_FILE.exists():
            return {**DEFAULTS, **json.loads(CFG_FILE.read_text())}
    except Exception: pass
    return dict(DEFAULTS)

def save_cfg(c):
    try: CFG_FILE.write_text(json.dumps(c, indent=2, ensure_ascii=False))
    except Exception: pass

def load_seen():
    try:
        if SEEN_FILE.exists():
            return set(json.loads(SEEN_FILE.read_text()))
    except Exception: pass
    return set()

def save_seen(s):
    try: SEEN_FILE.write_text(json.dumps(list(s)[-3000:]))
    except Exception: pass

def is_first_run():
    return not FIRST_RUN.exists()

def mark_not_first():
    try: FIRST_RUN.write_text("1")
    except Exception: pass

# ═══════════════════════════════════════════════════════════════════════
# Sources & Data
# ═══════════════════════════════════════════════════════════════════════
SOURCES = {
    "gewobag":   ("Gewobag",         True,  "🟢"),
    "degewo":    ("Degewo",          True,  "🟢"),
    "gesobau":   ("Gesobau",         True,  "🟢"),
    "wbm":       ("WBM",             True,  "🟢"),
    "vonovia":   ("Vonovia",         True,  "🟢"),
    "howoge":    ("Howoge",          True,  "🟢"),
    "berlinovo": ("Berlinovo",       True,  "🟢"),
    "immoscout": ("ImmoScout24",     False, "🔵"),
    "kleinanz":  ("Kleinanzeigen",   False, "🔵"),
}

JC_KDU = {1:549,2:671,3:789,4:911,5:1021,6:1131}
def jc_limit(n): return JC_KDU.get(max(1,min(int(n),6)), 1131+(max(1,int(n))-6)*110)

BERLIN_AREAS = [
    "Mitte","Spandau","Pankow","Neukölln","Tempelhof","Schöneberg",
    "Steglitz","Zehlendorf","Charlottenburg","Wilmersdorf","Lichtenberg",
    "Marzahn","Hellersdorf","Treptow","Köpenick","Reinickendorf",
    "Friedrichshain","Kreuzberg","Prenzlauer Berg","Wedding","Moabit"
]

# ═══════════════════════════════════════════════════════════════════════
# HTTP + Scrapers
# ═══════════════════════════════════════════════════════════════════════
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode    = ssl.CERT_NONE
_UA  = "Mozilla/5.0 (Linux; Android 13; Pixel 7) Chrome/124.0"

def _get(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":_UA,"Accept-Language":"de-DE,de;q=0.9"})
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return r.read().decode("utf-8","replace")
    except Exception: return None

def _get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":_UA,"Accept":"application/json"})
        with urllib.request.urlopen(req, timeout=15, context=_CTX) as r:
            return json.loads(r.read())
    except Exception: return None

def make_id(url):
    u = re.sub(r"[?#].*","", url.strip())
    return hashlib.sha256(u.encode()).hexdigest()[:12]

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
        v=float(s)
        return v if 50<v<5000 else None
    except: return None

def parse_rooms(raw):
    m=re.search(r"(\d+[.,]?\d*)",str(raw or "").replace(",","."))
    try:
        v=float(m.group(1)) if m else None
        return v if v and 0.5<=v<=20 else None
    except: return None

FEATS = {"balkon":"🌿 بلكونة","terrasse":"🌿 تراس","garten":"🌱 حديقة",
         "aufzug":"🛗 مصعد","einbauküche":"🍳 مطبخ","keller":"📦 مخزن",
         "stellplatz":"🚗 موقف","tiefgarage":"🚗 جراج","barrierefrei":"♿",
         "neubau":"🏗 جديد","erstbezug":"✨ أول سكن","parkett":"🪵 باركيه",
         "fußbodenheizung":"🌡 تدفئة أرضية","saniert":"🔨 مجدد",
         "fahrstuhl":"🛗 مصعد","fernwärme":"🌡 تدفئة مركزية"}
URGENT = ["ab sofort","sofort frei","sofort verfügbar"]
MONTHS = {"januar":"يناير","februar":"فبراير","märz":"مارس","april":"أبريل",
          "mai":"مايو","juni":"يونيو","juli":"يوليو","august":"أغسطس",
          "september":"سبتمبر","oktober":"أكتوبر","november":"نوفمبر","dezember":"ديسمبر"}

def enrich(title, desc):
    t=f"{title} {desc}".lower(); out={}
    m=re.search(r"(\d[\d\.]*)\s*(?:m[²2]|qm\b)",t)
    if m:
        try:
            v=float(m.group(1).replace(".",""))
            if 10<v<500: out["size_m2"]=v
        except: pass
    for pat,lbl in [(r"(\d+)\.\s*og",lambda m:f"الطابق {m.group(1)}"),
                    (r"\beg\b|erdgeschoss",lambda _:"الطابق الأرضي"),
                    (r"\bdg\b|dachgeschoss",lambda _:"الطابق العلوي"),
                    (r"\bpenthouse\b",lambda _:"بنتهاوس")]:
        mm=re.search(pat,t)
        if mm: out["floor"]=lbl(mm); break
    if any(k in t for k in URGENT): out["available"]="فوري 🔥"
    else:
        mm=re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})",t)
        if mm: out["available"]=f"من {mm.group(1)}"
    mm=re.search(r"kaution[:\s]*(\d[\d\.,]*)\s*€?",t)
    if mm:
        v=parse_price(mm.group(1))
        if v: out["deposit"]=f"{v:.0f} €"
    feats,seen=[],set()
    for kw,lb in FEATS.items():
        if kw in t and lb not in seen: seen.add(lb); feats.append(lb)
    if feats: out["features"]=feats
    return out

def fetch_all(sources=None):
    active=set(sources) if sources else set(SOURCES.keys())
    result=[]
    if "gewobag" in active:
        try:
            data=_get_json("https://www.gewobag.de/wp-json/gewobag/v1/offers?type=wohnung&wbs=1&per_page=50")
            items=data if isinstance(data,list) else (data or {}).get("offers",[])
            for i in items:
                url=i.get("link") or i.get("url","")
                if not url.startswith("http"): url="https://www.gewobag.de"+url
                t=i.get("title",""); title=t.get("rendered","") if isinstance(t,dict) else str(t)
                extra=enrich(title,i.get("beschreibung",""))
                result.append({"id":make_id(url),"url":url,"source":"gewobag","trusted_wbs":True,
                    "title":title,"price":parse_price(i.get("gesamtmiete") or i.get("warmmiete")),
                    "rooms":parse_rooms(i.get("zimmer")),"location":i.get("bezirk","Berlin"),
                    "wbs_label":"WBS erforderlich",**extra})
        except Exception: pass
    if "degewo" in active:
        try:
            for api in ["https://immosuche.degewo.de/de/properties.json?property_type_id=1&categories[]=WBS&per_page=50",
                        "https://immosuche.degewo.de/de/search.json?asset_classes[]=1&wbs=1"]:
                data=_get_json(api)
                if not data: continue
                items=data if isinstance(data,list) else data.get("results",[])
                for i in items:
                    url=i.get("path","") or i.get("url","")
                    if not url.startswith("http"): url="https://immosuche.degewo.de"+url
                    extra=enrich(i.get("title",""),i.get("text",""))
                    result.append({"id":make_id(url),"url":url,"source":"degewo","trusted_wbs":True,
                        "title":i.get("title",""),"price":parse_price(i.get("warmmiete") or i.get("totalRent")),
                        "rooms":parse_rooms(i.get("zimmer")),"location":i.get("district","Berlin"),
                        "wbs_label":"WBS erforderlich",**extra})
                if result: break
        except Exception: pass
    if "kleinanz" in active and HAS_BS4:
        try:
            html=_get("https://www.kleinanzeigen.de/s-wohnung-mieten/berlin/wbs/k0c203l3331")
            if html and len(html)>500:
                soup=BeautifulSoup(html,"html.parser")
                for card in soup.select("article.aditem")[:20]:
                    a=card.select_one("a.ellipsis,h2 a,h3 a")
                    if not a: continue
                    href=a.get("href","")
                    url="https://www.kleinanzeigen.de"+href if href.startswith("/") else href
                    t=card.select_one("h2,h3")
                    p=card.select_one("[class*='price']")
                    desc=card.get_text(" ",strip=True)
                    extra=enrich(t.get_text(strip=True) if t else "",desc)
                    result.append({"id":make_id(url),"url":url,"source":"kleinanz","trusted_wbs":False,
                        "title":(t.get_text(strip=True) if t else "")[:60],
                        "price":parse_price(p.get_text() if p else None),
                        "rooms":None,"location":"Berlin","wbs_label":"",**extra})
        except Exception: pass
    return result

def apply_filters(listings, cfg, seen):
    out=[]
    max_p=cfg.get("max_price",9999); min_r=float(cfg.get("min_rooms") or 0)
    wbs=cfg.get("wbs_only",False); wlmin=int(cfg.get("wbs_level_min") or 0)
    wlmax=int(cfg.get("wbs_level_max") or 999); jcm=cfg.get("jobcenter_mode",False)
    n=int(cfg.get("household_size") or 1); jclim=jc_limit(n)
    areas=[a.lower() for a in (cfg.get("areas") or [])]
    srcs=cfg.get("sources") or []
    for l in listings:
        if l["id"] in seen: continue
        if srcs and l["source"] not in srcs: continue
        price=l.get("price")
        if price and price>max_p: continue
        rooms=l.get("rooms")
        if rooms and min_r and rooms<min_r: continue
        if wbs and not l.get("trusted_wbs"): continue
        if wlmin>0:
            mm=re.search(r"wbs[\s\-]*(\d{2,3})",l.get("wbs_label","").lower())
            if mm:
                level=int(mm.group(1))
                if not (wlmin<=level<=wlmax): continue
        if areas:
            loc=(l.get("location","")+" "+l.get("title","")).lower()
            if not any(a in loc for a in areas): continue
        if jcm and price and price>jclim: continue
        out.append(l)
    return out

def score(l):
    s=6 if l.get("trusted_wbs") else 0
    p=l.get("price")
    if p:
        if p<450: s+=8
        elif p<550: s+=5
        elif p<650: s+=2
    if (l.get("rooms") or 0)>=2: s+=3
    if l.get("size_m2"): s+=2
    if (l.get("available","")).startswith("فوري"): s+=3
    s+=min(len(l.get("features") or []),3)
    return s

# ═══════════════════════════════════════════════════════════════════════
# UI Helpers
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    def add_bg(widget, color, radius=0):
        with widget.canvas.before:
            Color(*color)
            if radius:
                widget._bg_rect = RoundedRectangle(pos=widget.pos, size=widget.size, radius=[radius])
            else:
                widget._bg_rect = Rectangle(pos=widget.pos, size=widget.size)
        def upd(*_):
            widget._bg_rect.pos  = widget.pos
            widget._bg_rect.size = widget.size
        widget.bind(pos=upd, size=upd)

    def Lbl(text, size=14, color=None, bold=False, halign="right", **kw):
        if color is None: color = TEXT1
        l = Label(text=text, font_size=sp(size), color=color,
                  bold=bold, halign=halign, **kw)
        l.bind(width=lambda *_: setattr(l,'text_size',(l.width, None)))
        return l

    def Btn(text, color=None, text_color=None, radius=12, size_hint_y=None, height=48, **kw):
        if color is None: color = PRIMARY
        if text_color is None: text_color = WHITE
        b = Button(text=text, size_hint_y=size_hint_y,
                   height=dp(height) if size_hint_y is None else None,
                   background_color=TRANSP, color=text_color,
                   font_size=sp(14), bold=True, **kw)
        add_bg(b, color, radius=radius)
        return b

    def Sep():
        w = Widget(size_hint_y=None, height=dp(1))
        add_bg(w, DIVIDER)
        return w

    def Space(h=12):
        return Widget(size_hint_y=None, height=dp(h))

# ═══════════════════════════════════════════════════════════════════════
# Onboarding Screen
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    ONBOARD_PAGES = [
        {
            "icon":  "🏠",
            "title": "مرحباً بك في WBS برلين",
            "body":  "ابحث عن شقتك المدعومة في برلين\nمن 9 مصادر دفعة واحدة،\nوبكل سهولة ووضوح.",
            "color": PRIMARY,
        },
        {
            "icon":  "⚡",
            "title": "بحث سريع وذكي",
            "body":  "فلترة حسب السعر · الغرف · المنطقة\nمستوى WBS من 100 حتى 220\nدعم Jobcenter KdU تلقائياً",
            "color": GOV_C,
        },
        {
            "icon":  "🎯",
            "title": "نتائج تناسبك",
            "body":  "فقط الإعلانات الجديدة التي لم تشاهدها\nمرتبة حسب الأفضل أولاً\nافتح أي إعلان مباشرة",
            "color": ACCENT,
        },
    ]

    class OnboardingScreen(Screen):
        def __init__(self, app_ref, **kw):
            super().__init__(name="onboarding", **kw)
            self.app_ref  = app_ref
            self.page_idx = 0
            self._build()

        def _build(self):
            self.clear_widgets()
            add_bg(self, BG)
            root = FloatLayout()

            # Page content
            pg   = ONBOARD_PAGES[self.page_idx]
            card = BoxLayout(orientation="vertical", padding=dp(32), spacing=dp(20),
                             size_hint=(0.9, 0.70),
                             pos_hint={"center_x": 0.5, "center_y": 0.55})
            add_bg(card, BG2, radius=24)

            # Icon
            icon_lbl = Label(text=pg["icon"], font_size=sp(72),
                             size_hint_y=None, height=dp(90))
            card.add_widget(icon_lbl)

            # Title
            title_lbl = Lbl(pg["title"], size=22, bold=True,
                             color=pg["color"], size_hint_y=None, height=dp(60))
            card.add_widget(title_lbl)

            # Body
            body_lbl = Lbl(pg["body"], size=15, color=TEXT2,
                            size_hint_y=None, height=dp(90))
            card.add_widget(body_lbl)

            root.add_widget(card)

            # Dots indicator
            dots_box = BoxLayout(size_hint=(0.5, None), height=dp(16),
                                  pos_hint={"center_x": 0.5, "y": 0.17},
                                  spacing=dp(8))
            for i in range(len(ONBOARD_PAGES)):
                dot = Widget(size_hint_x=None, width=dp(8 if i != self.page_idx else 24))
                add_bg(dot, pg["color"] if i == self.page_idx else TEXT3, radius=4)
                dots_box.add_widget(dot)
            root.add_widget(dots_box)

            # Bottom buttons
            btn_box = BoxLayout(orientation="horizontal",
                                 size_hint=(0.9, None), height=dp(52),
                                 pos_hint={"center_x": 0.5, "y": 0.05},
                                 spacing=dp(12))

            is_last = self.page_idx == len(ONBOARD_PAGES) - 1

            if not is_last:
                skip_btn = Btn("تخطي", color=BG3, text_color=TEXT2, height=52)
                skip_btn.bind(on_press=self._finish)
                btn_box.add_widget(skip_btn)

            next_lbl = "ابدأ الآن  🚀" if is_last else "التالي  ←"
            next_btn  = Btn(next_lbl, color=pg["color"], height=52)
            next_btn.bind(on_press=self._next if not is_last else self._finish)
            btn_box.add_widget(next_btn)

            root.add_widget(btn_box)
            self.add_widget(root)

        def _next(self, *_):
            self.page_idx = min(self.page_idx + 1, len(ONBOARD_PAGES) - 1)
            self._build()

        def _finish(self, *_):
            mark_not_first()
            self.app_ref.go_main()

# ═══════════════════════════════════════════════════════════════════════
# Listing Card Widget
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class ListingCard(BoxLayout):
        def __init__(self, l, **kw):
            super().__init__(orientation="vertical", size_hint_y=None,
                             padding=(dp(16), dp(14)), spacing=dp(8), **kw)
            name, gov, dot = SOURCES.get(l["source"], (l["source"], False, "⚪"))
            src_color = GOV_C if gov else PRIV_C
            price     = l.get("price")
            rooms     = l.get("rooms")
            size_m2   = l.get("size_m2")
            floor_s   = l.get("floor", "")
            avail     = l.get("available", "")
            deposit   = l.get("deposit", "")
            features  = l.get("features") or []
            title     = (l.get("title") or "شقة").strip()[:60]
            location  = l.get("location", "Berlin")
            wlabel    = l.get("wbs_label", "")
            self.url  = l.get("url", "")

            mm = re.search(r"wbs[\s\-]*(\d{2,3})", wlabel.lower())
            wbs_level = f"WBS {mm.group(1)}" if mm else ("WBS ✓" if l.get("trusted_wbs") else "")

            n_feat_rows = (len(features[:6]) + 2) // 3
            self.height = dp(170 + n_feat_rows * 22)
            add_bg(self, BG2, radius=16)

            # ── Row 1: Source chip + WBS badge ────────────────────────────
            r1 = BoxLayout(size_hint_y=None, height=dp(26), spacing=dp(8))

            src_chip = BoxLayout(size_hint=(None, None), size=(dp(120), dp(22)),
                                  padding=(dp(8), 0))
            add_bg(src_chip, (*src_color[:3], 0.15), radius=11)
            src_chip.add_widget(Lbl(f"{dot} {name}", size=11, color=src_color,
                                     size_hint_y=None, height=dp(22)))
            r1.add_widget(src_chip)

            r1.add_widget(Widget())  # spacer

            if wbs_level:
                badge = BoxLayout(size_hint=(None, None), size=(dp(80), dp(22)),
                                   padding=(dp(8), 0))
                add_bg(badge, (*SUCCESS[:3], 0.15), radius=11)
                badge.add_widget(Lbl(wbs_level, size=11, color=SUCCESS,
                                      size_hint_y=None, height=dp(22)))
                r1.add_widget(badge)

            self.add_widget(r1)

            # ── Row 2: Title ───────────────────────────────────────────────
            self.add_widget(Lbl(title, size=14, bold=True,
                                 size_hint_y=None, height=dp(22)))

            # ── Row 3: Location + Availability ────────────────────────────
            r3 = BoxLayout(size_hint_y=None, height=dp(18))
            r3.add_widget(Lbl(f"📍 {location}", size=12, color=TEXT2))
            if avail:
                avail_color = WARN if "فوري" in avail else TEXT2
                r3.add_widget(Lbl(f"📅 {avail}", size=12, color=avail_color))
            self.add_widget(r3)

            self.add_widget(Sep())

            # ── Row 4: Price + Rooms + Size ───────────────────────────────
            r4 = BoxLayout(size_hint_y=None, height=dp(32), spacing=dp(4))

            if price:
                p_box = BoxLayout(size_hint=(None, None), size=(dp(100), dp(32)),
                                   padding=(dp(8), 0))
                add_bg(p_box, (*PRIMARY[:3], 0.12), radius=8)
                p_box.add_widget(Lbl(f"💰 {price:.0f} €", size=14, color=PRIMARY,
                                      bold=True, size_hint_y=None, height=dp(32)))
                r4.add_widget(p_box)

            if rooms:
                r4.add_widget(Lbl(f"🛏 {rooms:.0f} غرف", size=13, color=TEXT1))
            if size_m2:
                r4.add_widget(Lbl(f"📐 {size_m2:.0f} م²", size=13, color=TEXT1))
            if floor_s:
                r4.add_widget(Lbl(floor_s, size=12, color=TEXT2))
            if deposit:
                r4.add_widget(Lbl(f"💼 {deposit}", size=11, color=TEXT2))

            self.add_widget(r4)

            # ── Row 5: Features ────────────────────────────────────────────
            if features:
                feat_box = BoxLayout(size_hint_y=None,
                                      height=dp(n_feat_rows * 22),
                                      spacing=dp(4))
                for f in features[:6]:
                    chip = BoxLayout(size_hint=(None, None),
                                      size=(dp(90), dp(20)), padding=(dp(4), 0))
                    add_bg(chip, BG3, radius=6)
                    chip.add_widget(Lbl(f, size=10, color=TEXT2,
                                        size_hint_y=None, height=dp(20)))
                    feat_box.add_widget(chip)
                self.add_widget(feat_box)

            # ── Open button ────────────────────────────────────────────────
            open_btn = Btn("فتح الإعلان  ←", height=36, radius=10)
            open_btn.bind(on_press=self._open)
            self.add_widget(open_btn)

        def _open(self, *_):
            if not self.url: return
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
                except Exception: pass

# ═══════════════════════════════════════════════════════════════════════
# Listings Screen
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class ListingsScreen(Screen):
        def __init__(self, app_ref, **kw):
            super().__init__(name="listings", **kw)
            self.app_ref = app_ref
            self._busy   = False
            self._raw    = []
            add_bg(self, BG)
            self._build()

        def _build(self):
            root = BoxLayout(orientation="vertical")

            # ── Top Bar ───────────────────────────────────────────────────
            bar = BoxLayout(size_hint_y=None, height=dp(58),
                             padding=(dp(16), dp(8)), spacing=dp(8))
            add_bg(bar, BG2)

            bar.add_widget(Lbl("🏠 WBS برلين", size=17, bold=True,
                                color=WHITE, size_hint_x=0.5))
            bar.add_widget(Widget())

            self._filter_btn = Btn("⚙️ فلاتر", color=BG3, text_color=TEXT1,
                                    size_hint_x=None, width=dp(90), height=40)
            self._filter_btn.bind(on_press=lambda *_: setattr(
                self.app_ref.sm, "current", "settings"))
            bar.add_widget(self._filter_btn)

            self._refresh_btn = Btn("🔄", color=PRIMARY, size_hint_x=None,
                                     width=dp(44), height=40)
            self._refresh_btn.bind(on_press=self._refresh)
            bar.add_widget(self._refresh_btn)

            root.add_widget(bar)

            # ── Quick filter chips ─────────────────────────────────────────
            chips = BoxLayout(size_hint_y=None, height=dp(44),
                               padding=(dp(12), dp(6)), spacing=dp(8))
            add_bg(chips, BG2)

            cfg = load_cfg()
            self._wbs_chip = ToggleButton(
                text="WBS فقط",
                state="down" if cfg.get("wbs_only") else "normal",
                size_hint=(None, None), size=(dp(90), dp(30)),
                background_color=TRANSP, color=TEXT1,
                font_size=sp(12))
            add_bg(self._wbs_chip,
                   (*PRIMARY[:3], 0.9) if cfg.get("wbs_only") else BG3,
                   radius=15)
            self._wbs_chip.bind(state=self._on_wbs_chip)
            chips.add_widget(self._wbs_chip)

            self._status_lbl = Lbl(
                "اضغط 🔄 لبدء البحث", size=12, color=TEXT2,
                size_hint_y=None, height=dp(30))
            chips.add_widget(self._status_lbl)
            root.add_widget(chips)
            root.add_widget(Sep())

            # ── Cards scroll ───────────────────────────────────────────────
            self._cards = BoxLayout(orientation="vertical",
                                     spacing=dp(10),
                                     padding=(dp(12), dp(10)),
                                     size_hint_y=None)
            self._cards.bind(minimum_height=self._cards.setter("height"))
            sv = ScrollView(bar_color=(*PRIMARY[:3], 0.3),
                             bar_inactive_color=(*TEXT3[:3], 0.2))
            sv.add_widget(self._cards)
            root.add_widget(sv)

            self.add_widget(root)
            self._show_empty("اضغط 🔄 للبحث عن شقق WBS")

        def _on_wbs_chip(self, btn, state):
            on = state == "down"
            with btn.canvas.before:
                btn.canvas.before.clear()
            add_bg(btn, (*PRIMARY[:3], 0.9) if on else BG3, radius=15)
            cfg = load_cfg(); cfg["wbs_only"] = on; save_cfg(cfg)
            if self._raw:
                self._render(apply_filters(self._raw, cfg, load_seen()))

        def _show_empty(self, msg):
            self._cards.clear_widgets()
            box = BoxLayout(orientation="vertical", spacing=dp(12),
                             size_hint_y=None, height=dp(200),
                             padding=dp(32))
            box.add_widget(Lbl("🔍", size=48, size_hint_y=None, height=dp(60)))
            box.add_widget(Lbl(msg, size=14, color=TEXT2,
                                size_hint_y=None, height=dp(50)))
            self._cards.add_widget(box)

        def _refresh(self, *_):
            if self._busy: return
            self._busy = True
            self._status_lbl.text = "⏳ جاري البحث..."
            self._cards.clear_widgets()

            # Loading placeholder
            load_box = BoxLayout(orientation="vertical", spacing=dp(12),
                                  size_hint_y=None, height=dp(160),
                                  padding=dp(40))
            load_box.add_widget(Lbl("⏳", size=48, size_hint_y=None, height=dp(60)))
            load_box.add_widget(Lbl("جاري جلب الإعلانات...", size=14,
                                     color=TEXT2, size_hint_y=None, height=dp(40)))
            self._cards.add_widget(load_box)

            threading.Thread(target=self._bg, daemon=True).start()

        def _bg(self):
            cfg  = load_cfg()
            raw  = fetch_all(cfg.get("sources") or None)
            self._raw = raw
            seen = load_seen()
            shown = apply_filters(raw, cfg, seen)
            shown.sort(key=score, reverse=True)
            for l in shown: seen.add(l["id"])
            save_seen(seen)
            Clock.schedule_once(lambda dt: self._render(shown, len(raw)))

        def _render(self, lst, total=None):
            self._busy = False
            self._cards.clear_widgets()
            t = total if total is not None else len(lst)
            if not lst:
                self._status_lbl.text = f"لا إعلانات جديدة (إجمالي {t})"
                self._show_empty("لا توجد إعلانات جديدة تناسب إعداداتك")
                return
            self._status_lbl.text = f"✅ {len(lst)} جديد من {t} إعلان"
            for l in lst[:60]:
                self._cards.add_widget(ListingCard(l))
                self._cards.add_widget(Space(6))

# ═══════════════════════════════════════════════════════════════════════
# Settings Screen
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class SettingsScreen(Screen):
        def __init__(self, app_ref, **kw):
            super().__init__(name="settings", **kw)
            self.app_ref = app_ref
            add_bg(self, BG)
            cfg = load_cfg()

            root = BoxLayout(orientation="vertical")

            # Header
            hdr = BoxLayout(size_hint_y=None, height=dp(58),
                             padding=(dp(16), dp(8)), spacing=dp(8))
            add_bg(hdr, BG2)
            back = Btn("←", color=BG3, text_color=TEXT1,
                        size_hint_x=None, width=dp(44), height=40)
            back.bind(on_press=lambda *_: setattr(app_ref.sm, "current", "listings"))
            hdr.add_widget(back)
            hdr.add_widget(Lbl("⚙️ الفلاتر والإعدادات", size=16, bold=True,
                                 color=WHITE))
            root.add_widget(hdr)

            scroll = ScrollView()
            body   = BoxLayout(orientation="vertical", padding=dp(16),
                                spacing=dp(12), size_hint_y=None)
            body.bind(minimum_height=body.setter("height"))

            def section(title):
                box = BoxLayout(size_hint_y=None, height=dp(32))
                box.add_widget(Lbl(title, size=13, color=TEXT2, bold=True))
                body.add_widget(Space(4))
                body.add_widget(box)

            def field_row(label, widget):
                row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(12))
                add_bg(row, BG2, radius=12)
                row.add_widget(Lbl(label, size=13, color=TEXT1,
                                    size_hint_x=0.45, halign="right"))
                row.add_widget(widget)
                body.add_widget(row)

            def inp(val, filt="int"):
                t = TextInput(text=str(val), input_filter=filt, multiline=False,
                               background_color=TRANSP, foreground_color=TEXT1,
                               cursor_color=PRIMARY, font_size=sp(14),
                               size_hint_x=0.55)
                return t

            # ── Budget ────────────────────────────────────────────────────
            section("💰 الميزانية")
            self._price = inp(cfg.get("max_price",700))
            field_row("أقصى إيجار (€)", self._price)

            self._rooms = inp(cfg.get("min_rooms",0),"float")
            field_row("أقل غرف", self._rooms)

            # ── WBS ───────────────────────────────────────────────────────
            section("📋 WBS")
            self._wbs = ToggleButton(
                text="WBS فقط ✅" if cfg.get("wbs_only") else "WBS فقط ❌",
                state="down" if cfg.get("wbs_only") else "normal",
                size_hint=(1, None), height=dp(46),
                background_color=TRANSP, color=TEXT1, font_size=sp(14))
            add_bg(self._wbs, (*PRIMARY[:3],0.15) if cfg.get("wbs_only") else BG2, radius=12)
            self._wbs.bind(state=lambda b,s: (
                setattr(b,"text","WBS فقط ✅" if s=="down" else "WBS فقط ❌"),
                add_bg(b, (*PRIMARY[:3],0.15) if s=="down" else BG2, radius=12)
            ))
            body.add_widget(self._wbs)

            # WBS level range
            wl_row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
            add_bg(wl_row, BG2, radius=12)
            wl_row.add_widget(Lbl("مستوى WBS:", size=13, color=TEXT1,
                                   size_hint_x=0.3, halign="right"))
            self._wlmin = inp(cfg.get("wbs_level_min",0))
            self._wlmax = inp(cfg.get("wbs_level_max",999))
            wl_row.add_widget(self._wlmin)
            wl_row.add_widget(Lbl("—", size=13, color=TEXT2, size_hint_x=None, width=dp(20)))
            wl_row.add_widget(self._wlmax)
            body.add_widget(wl_row)

            # WBS presets
            pre = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
            for lbl, mn, mx in [("WBS 100","100","100"),("100-140","100","140"),
                                  ("100-160","100","160"),("الكل","0","999")]:
                b = Btn(lbl, color=BG3, text_color=TEXT1, height=40, radius=10)
                b.bind(on_press=lambda _,mn=mn,mx=mx: (
                    setattr(self._wlmin,"text",mn), setattr(self._wlmax,"text",mx)))
                pre.add_widget(b)
            body.add_widget(pre)

            # ── Social ────────────────────────────────────────────────────
            section("🏛 فلاتر اجتماعية")
            self._hh = inp(cfg.get("household_size",1))
            field_row("أفراد الأسرة", self._hh)

            self._jc = ToggleButton(
                text="Jobcenter KdU ✅" if cfg.get("jobcenter_mode") else "Jobcenter KdU ❌",
                state="down" if cfg.get("jobcenter_mode") else "normal",
                size_hint=(1, None), height=dp(46),
                background_color=TRANSP, color=TEXT1, font_size=sp(14))
            add_bg(self._jc, (*GOV_C[:3],0.15) if cfg.get("jobcenter_mode") else BG2, radius=12)
            self._jc.bind(state=lambda b,s: (
                setattr(b,"text","Jobcenter KdU ✅" if s=="down" else "Jobcenter KdU ❌"),
                add_bg(b, (*GOV_C[:3],0.15) if s=="down" else BG2, radius=12)
            ))
            body.add_widget(self._jc)

            # ── Sources ───────────────────────────────────────────────────
            section("🌐 مصادر البحث")
            self._srcs = {}
            cur_src = cfg.get("sources") or []
            for sid, (sname, gov, dot) in SOURCES.items():
                on  = not cur_src or sid in cur_src
                c   = GOV_C if gov else PRIV_C
                btn = ToggleButton(
                    text=f"{dot} {sname}",
                    state="down" if on else "normal",
                    size_hint=(1, None), height=dp(42),
                    background_color=TRANSP, color=TEXT1, font_size=sp(13))
                add_bg(btn, (*c[:3],0.15) if on else BG2, radius=10)
                btn.bind(state=lambda b,s,c=c: add_bg(
                    b, (*c[:3],0.15) if s=="down" else BG2, radius=10))
                self._srcs[sid] = btn
                body.add_widget(btn)

            body.add_widget(Space(16))

            # Save button
            save_btn = Btn("💾 حفظ الإعدادات", height=52, radius=14)
            save_btn.bind(on_press=self._save)
            body.add_widget(save_btn)
            body.add_widget(Space(20))

            scroll.add_widget(body)
            root.add_widget(scroll)
            self.add_widget(root)

        def _save(self, *_):
            sel = [sid for sid,b in self._srcs.items() if b.state=="down"]
            cfg = load_cfg()
            cfg.update({
                "max_price":      int(self._price.text or 700),
                "min_rooms":      float(self._rooms.text or 0),
                "household_size": int(self._hh.text or 1),
                "wbs_only":       self._wbs.state=="down",
                "wbs_level_min":  int(self._wlmin.text or 0),
                "wbs_level_max":  int(self._wlmax.text or 999),
                "jobcenter_mode": self._jc.state=="down",
                "sources": sel if len(sel)<len(SOURCES) else [],
            })
            save_cfg(cfg)
            self.manager.current = "listings"

# ═══════════════════════════════════════════════════════════════════════
# App
# ═══════════════════════════════════════════════════════════════════════
if HAS_KIVY:
    class WBSApp(App):
        def build(self):
            self.title = "WBS Berlin"
            self.sm = ScreenManager(transition=FadeTransition(duration=0.2))
            if is_first_run():
                self.sm.add_widget(OnboardingScreen(self))
                self.sm.current = "onboarding"
            else:
                self._add_main()
            return self.sm

        def _add_main(self):
            if not any(s.name == "listings" for s in self.sm.screens):
                self.sm.add_widget(ListingsScreen(self))
            if not any(s.name == "settings" for s in self.sm.screens):
                self.sm.add_widget(SettingsScreen(self))

        def go_main(self):
            self._add_main()
            self.sm.current = "listings"

    if __name__ == "__main__":
        WBSApp().run()
else:
    if __name__ == "__main__":
        print("Testing (no Kivy)...")
        raw = fetch_all()
        shown = apply_filters(raw, DEFAULTS.copy(), set())
        shown.sort(key=score, reverse=True)
        print(f"Found: {len(shown)}")
        for l in shown[:3]:
            print(f"  {l['source']} | {l.get('price','-')}€ | {l.get('title','')[:40]}")
