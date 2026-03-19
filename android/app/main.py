"""
WBS Berlin — Android App
يستخدم فقط Python standard library + beautifulsoup4 (pure Python)
لضمان نجاح بناء APK.
"""
import asyncio
import json
import os
import re
import hashlib
import threading
import urllib.request
import urllib.parse
import ssl
from datetime import datetime
from pathlib import Path

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

try:
    from kivy.app import App
    from kivy.uix.screenmanager import ScreenManager, Screen
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.gridlayout import GridLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.textinput import TextInput
    from kivy.uix.scrollview import ScrollView
    from kivy.uix.togglebutton import ToggleButton
    from kivy.clock import Clock
    from kivy.metrics import dp
    from kivy.utils import get_color_from_hex
    HAS_KIVY = True
except ImportError:
    HAS_KIVY = False

# ── Colors ─────────────────────────────────────────────────────────────────
if HAS_KIVY:
    C_BG     = get_color_from_hex("#1a1a2e")
    C_ACCENT = get_color_from_hex("#0f3460")
    C_GREEN  = get_color_from_hex("#00b894")
    C_ORANGE = get_color_from_hex("#fdcb6e")
    C_GOV    = get_color_from_hex("#6c5ce7")
    C_TEXT   = get_color_from_hex("#dfe6e9")
    C_DIM    = get_color_from_hex("#636e72")

# ── Storage ─────────────────────────────────────────────────────────────────
_sd      = Path(os.environ.get("EXTERNAL_STORAGE", "."))
CFG_FILE = _sd / "wbs_config.json"
SEEN_FILE= _sd / "wbs_seen.json"

DEFAULTS = {
    "max_price": 700, "min_rooms": 0.0, "wbs_only": False,
    "household_size": 1, "wbs_level_min": 0, "wbs_level_max": 999,
    "jobcenter_mode": False, "sources": [], "areas": [],
}
def load_cfg():
    try:
        if CFG_FILE.exists(): return {**DEFAULTS, **json.loads(CFG_FILE.read_text())}
    except Exception: pass
    return dict(DEFAULTS)
def save_cfg(c): CFG_FILE.write_text(json.dumps(c, indent=2, ensure_ascii=False))
def load_seen():
    try:
        if SEEN_FILE.exists(): return set(json.loads(SEEN_FILE.read_text()))
    except Exception: pass
    return set()
def save_seen(s): SEEN_FILE.write_text(json.dumps(list(s)[-3000:]))

# ── Sources ─────────────────────────────────────────────────────────────────
SOURCES = {
    "gewobag":    ("Gewobag",       True),
    "degewo":     ("Degewo",        True),
    "gesobau":    ("Gesobau",       True),
    "wbm":        ("WBM",           True),
    "vonovia":    ("Vonovia",       True),
    "howoge":     ("Howoge",        True),
    "berlinovo":  ("Berlinovo",     True),
    "immoscout":  ("ImmoScout24",   False),
    "kleinanz":   ("Kleinanzeigen", False),
}
JC_KDU = {1:549,2:671,3:789,4:911,5:1021,6:1131}
def jc_limit(n): return JC_KDU.get(max(1,min(int(n),6)), 1131+(max(1,int(n))-6)*110)

# ── HTTP helper (stdlib only) ───────────────────────────────────────────────
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode    = ssl.CERT_NONE
_UA  = "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 Chrome/124.0"

def _get(url: str, timeout: int = 15) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Language": "de-DE,de;q=0.9"})
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception:
        return None

def _get_json(url: str) -> dict | list | None:
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15, context=_CTX) as r:
            return json.loads(r.read())
    except Exception:
        return None

# ── Parsing helpers ─────────────────────────────────────────────────────────
def make_id(url: str) -> str:
    u = re.sub(r"[?#].*","", url.strip())
    return hashlib.sha256(u.encode()).hexdigest()[:12]

def parse_price(raw) -> float | None:
    if not raw: return None
    s = re.sub(r"[^\d\.,]", "", str(raw))
    if not s: return None
    if "," in s and "." in s: s = s.replace(".","").replace(",",".")
    elif "," in s: s = s.replace(",",".")
    elif "." in s:
        p = s.split(".")
        if len(p)==2 and len(p[1])==3: s = s.replace(".","")
    try:
        v = float(s)
        return v if 50 < v < 5000 else None
    except Exception: return None

def parse_rooms(raw) -> float | None:
    m = re.search(r"(\d+[.,]?\d*)", str(raw or "").replace(",","."))
    try:
        v = float(m.group(1)) if m else None
        return v if v and 0.5 <= v <= 20 else None
    except Exception: return None

FEAT = {"balkon":"🌿 بلكونة","terrasse":"🌿 تراس","garten":"🌱 حديقة",
        "aufzug":"🛗 مصعد","einbauküche":"🍳 مطبخ","keller":"📦 مخزن",
        "stellplatz":"🚗 موقف","tiefgarage":"🚗 جراج","barrierefrei":"♿",
        "neubau":"🏗 جديد","erstbezug":"✨ أول سكن","parkett":"🪵 باركيه",
        "fußbodenheizung":"🌡 تدفئة أرضية","saniert":"🔨 مجدد"}
URGENT = ["ab sofort","sofort frei","sofort verfügbar"]

def enrich(title: str, desc: str) -> dict:
    t = f"{title} {desc}".lower()
    out = {}
    m = re.search(r"(\d[\d\.]*)\s*(?:m[²2]|qm\b)", t)
    if m:
        try:
            v = float(m.group(1).replace(".",""))
            if 10 < v < 500: out["size_m2"] = v
        except Exception: pass
    for pat, lbl in [(r"(\d+)\.\s*og",lambda m:f"الطابق {m.group(1)}"),
                     (r"\beg\b|erdgeschoss",lambda _:"الطابق الأرضي"),
                     (r"\bdg\b|dachgeschoss",lambda _:"الطابق العلوي")]:
        mm = re.search(pat, t)
        if mm: out["floor"] = lbl(mm); break
    if any(k in t for k in URGENT): out["available"] = "فوري 🔥"
    else:
        mm = re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})", t)
        if mm: out["available"] = f"من {mm.group(1)}"
    feats = []
    for kw, lbl in FEAT.items():
        if kw in t and lbl not in feats: feats.append(lbl)
    if feats: out["features"] = feats
    return out

# ── Scrapers ─────────────────────────────────────────────────────────────────
def _scrape_gewobag() -> list:
    data = _get_json("https://www.gewobag.de/wp-json/gewobag/v1/offers?type=wohnung&wbs=1&per_page=50")
    if not data: return []
    items = data if isinstance(data, list) else data.get("offers", [])
    result = []
    for item in items:
        url = item.get("link") or item.get("url","")
        if not url.startswith("http"): url = "https://www.gewobag.de" + url
        t = item.get("title","")
        title = t.get("rendered","") if isinstance(t,dict) else str(t)
        extra = enrich(title, item.get("beschreibung",""))
        result.append({"id":make_id(url),"url":url,"source":"gewobag","trusted_wbs":True,
            "title":title, "price":parse_price(item.get("gesamtmiete") or item.get("warmmiete")),
            "rooms":parse_rooms(item.get("zimmer")), "location":item.get("bezirk","Berlin"),
            "wbs_label":"WBS erforderlich", **extra})
    return result

def _scrape_degewo() -> list:
    for api in [
        "https://immosuche.degewo.de/de/properties.json?property_type_id=1&categories[]=WBS&per_page=50",
        "https://immosuche.degewo.de/de/search.json?asset_classes[]=1&wbs=1",
    ]:
        data = _get_json(api)
        if not data: continue
        items = data if isinstance(data,list) else data.get("results",[])
        result = []
        for item in items:
            url = item.get("path","") or item.get("url","")
            if not url.startswith("http"): url = "https://immosuche.degewo.de" + url
            extra = enrich(item.get("title",""), item.get("text",""))
            result.append({"id":make_id(url),"url":url,"source":"degewo","trusted_wbs":True,
                "title":item.get("title",""), "price":parse_price(item.get("warmmiete") or item.get("totalRent")),
                "rooms":parse_rooms(item.get("zimmer")), "location":item.get("district","Berlin"),
                "wbs_label":"WBS erforderlich", **extra})
        if result: return result
    return []

def _scrape_html(url: str, source: str, is_gov: bool,
                 card_sel: str, link_sel: str, title_sel: str,
                 price_sel: str, rooms_sel: str) -> list:
    if not HAS_BS4: return []
    html = _get(url)
    if not html or len(html) < 500: return []
    soup = BeautifulSoup(html, "html.parser")
    result, seen = [], set()
    for card in soup.select(card_sel)[:30]:
        a = card.select_one(link_sel) or card.select_one("a[href]")
        if not a: continue
        href = a.get("href","")
        full = href if href.startswith("http") else urllib.parse.urljoin(url, href)
        if full in seen or len(full) < 10: continue
        seen.add(full)
        t_tag = card.select_one(title_sel)
        p_tag = card.select_one(price_sel)
        r_tag = card.select_one(rooms_sel)
        title = (t_tag or a).get_text(strip=True)[:80]
        extra = enrich(title, card.get_text(" ", strip=True))
        result.append({"id":make_id(full),"url":full,"source":source,"trusted_wbs":is_gov,
            "title":title, "price":parse_price(p_tag.get_text() if p_tag else None),
            "rooms":parse_rooms(r_tag.get_text() if r_tag else None),
            "location":"Berlin", "wbs_label":"WBS erforderlich" if is_gov else "",
            **extra})
    return result

def fetch_all(enabled: list = None) -> list:
    active = set(enabled) if enabled else set(SOURCES.keys())
    result = []
    if "gewobag" in active:
        try: result.extend(_scrape_gewobag())
        except Exception: pass
    if "degewo" in active:
        try: result.extend(_scrape_degewo())
        except Exception: pass
    for src, url, gov, c, l, t, p, r in [
        ("kleinanz",
         "https://www.kleinanzeigen.de/s-wohnung-mieten/berlin/wbs/k0c203l3331",
         False, "article.aditem", "a.ellipsis,h2 a",
         "h2,h3", "[class*='price']", "[class*='zimmer']"),
        ("immoscout",
         "https://www.immobilienscout24.de/Suche/de/berlin/berlin/wohnung-mieten?wbs=true",
         False, "article[data-id],[class*='result-list-entry']", "a[href*='/expose/']",
         "[class*='title'],h2", "[class*='price']", "[class*='zimmer']"),
    ]:
        if src in active:
            try: result.extend(_scrape_html(url, src, gov, c, l, t, p, r))
            except Exception: pass
    return result

# ── Filter + Score ───────────────────────────────────────────────────────────
def apply_filters(listings: list, cfg: dict, seen: set) -> list:
    out = []
    max_p = cfg.get("max_price", 9999)
    min_r = float(cfg.get("min_rooms") or 0)
    wbs   = cfg.get("wbs_only", False)
    wlmin = int(cfg.get("wbs_level_min") or 0)
    wlmax = int(cfg.get("wbs_level_max") or 999)
    jcm   = cfg.get("jobcenter_mode", False)
    n     = int(cfg.get("household_size") or 1)
    jclim = jc_limit(n)
    areas = [a.lower() for a in (cfg.get("areas") or [])]
    srcs  = cfg.get("sources") or []
    for l in listings:
        if l["id"] in seen: continue
        if srcs and l["source"] not in srcs: continue
        price = l.get("price")
        if price and price > max_p: continue
        rooms = l.get("rooms")
        if rooms and min_r and rooms < min_r: continue
        if wbs and not l.get("trusted_wbs"): continue
        if wlmin > 0:
            mm = re.search(r"wbs[\s\-]*(\d{2,3})", l.get("wbs_label","").lower())
            if mm:
                level = int(mm.group(1))
                if not (wlmin <= level <= wlmax): continue
        if areas:
            loc = (l.get("location","") + " " + l.get("title","")).lower()
            if not any(a in loc for a in areas): continue
        if jcm and price and price > jclim: continue
        out.append(l)
    return out

def score(l: dict) -> int:
    s = 6 if l.get("trusted_wbs") else 0
    p = l.get("price")
    if p:
        if p < 450: s += 8
        elif p < 550: s += 5
        elif p < 650: s += 2
    if (l.get("rooms") or 0) >= 2: s += 3
    if l.get("size_m2"): s += 2
    if (l.get("available","")).startswith("فوري"): s += 3
    s += min(len(l.get("features") or []), 3)
    return s

# ══════════════════════════════════════════════════════════════════════════════
# Kivy UI
# ══════════════════════════════════════════════════════════════════════════════
if HAS_KIVY:

    class Card(BoxLayout):
        def __init__(self, l: dict, **kw):
            super().__init__(orientation="vertical", size_hint_y=None,
                             padding=dp(8), spacing=dp(3), **kw)
            name, gov = SOURCES.get(l["source"], (l["source"], False))
            icon  = "🏛" if gov else "🔍"
            title = (l.get("title") or "شقة")[:55]
            price = f"{l['price']:.0f}€" if l.get("price") else "—"
            rooms = f"{l['rooms']:.0f}غرف" if l.get("rooms") else ""
            size  = f"{l['size_m2']:.0f}m²" if l.get("size_m2") else ""
            floor = l.get("floor","")
            avail = l.get("available","")
            feats = l.get("features") or []
            self.url = l.get("url","")
            feat_rows = (len(feats)+3)//4
            self.height = dp(115 + feat_rows * 20)

            # Header
            hdr = BoxLayout(size_hint_y=None, height=dp(24))
            hdr.add_widget(Label(text=f"{icon} [b]{name}[/b]", markup=True,
                color=C_GOV if gov else C_ORANGE, font_size=dp(12), size_hint_x=0.6))
            if l.get("trusted_wbs"):
                hdr.add_widget(Label(text="[b]WBS✅[/b]", markup=True,
                    color=C_GREEN, font_size=dp(12), size_hint_x=0.4))
            self.add_widget(hdr)

            self.add_widget(Label(text=title, color=C_TEXT, font_size=dp(12),
                size_hint_y=None, height=dp(22), halign="right"))

            row1 = BoxLayout(size_hint_y=None, height=dp(20))
            row1.add_widget(Label(text=f"💰{price}", color=C_GREEN, font_size=dp(12)))
            if rooms: row1.add_widget(Label(text=f"🛏{rooms}", color=C_TEXT, font_size=dp(11)))
            if size:  row1.add_widget(Label(text=f"📐{size}", color=C_TEXT, font_size=dp(11)))
            if floor: row1.add_widget(Label(text=floor, color=C_DIM, font_size=dp(10)))
            self.add_widget(row1)

            row2 = BoxLayout(size_hint_y=None, height=dp(18))
            row2.add_widget(Label(text=f"📍{l.get('location','Berlin')}", color=C_DIM, font_size=dp(11)))
            if avail: row2.add_widget(Label(text=f"📅{avail}", color=C_ORANGE, font_size=dp(11)))
            self.add_widget(row2)

            if feats:
                grid = GridLayout(cols=4, size_hint_y=None, height=dp(feat_rows*20))
                for f in feats[:8]:
                    grid.add_widget(Label(text=f, font_size=dp(9), color=C_DIM))
                self.add_widget(grid)

            btn = Button(text="🔗 فتح", size_hint_y=None, height=dp(30),
                         background_color=C_ACCENT, font_size=dp(11))
            btn.bind(on_press=self._open)
            self.add_widget(btn)

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


    class ListingsScreen(Screen):
        def __init__(self, sm, **kw):
            super().__init__(name="listings", **kw)
            self._sm = sm; self._busy = False; self._raw = []
            root = BoxLayout(orientation="vertical")

            bar = BoxLayout(size_hint_y=None, height=dp(52), padding=dp(6), spacing=dp(6))
            bar.add_widget(Label(text="🏠 [b]WBS برلين[/b]", markup=True,
                color=C_TEXT, font_size=dp(15), size_hint_x=0.55))
            for t, cb in [("🔄", self._refresh), ("⚙️", lambda *_: setattr(sm,"current","settings"))]:
                b = Button(text=t, size_hint_x=None, width=dp(48), background_color=C_ACCENT)
                b.bind(on_press=cb); bar.add_widget(b)
            root.add_widget(bar)

            chips = BoxLayout(size_hint_y=None, height=dp(36), padding=(dp(6),dp(2)), spacing=dp(6))
            self._wbs_chip = ToggleButton(text="WBS فقط", font_size=dp(11),
                state="down" if load_cfg().get("wbs_only") else "normal",
                size_hint_x=None, width=dp(85))
            self._wbs_chip.bind(state=self._quick_wbs); chips.add_widget(self._wbs_chip)
            self._status = Label(text="اضغط 🔄 لجلب الإعلانات", color=C_ORANGE, font_size=dp(12))
            chips.add_widget(self._status); root.add_widget(chips)

            self._cards = BoxLayout(orientation="vertical", spacing=dp(6),
                padding=(dp(6),dp(2)), size_hint_y=None)
            self._cards.bind(minimum_height=self._cards.setter("height"))
            sv = ScrollView(); sv.add_widget(self._cards); root.add_widget(sv)
            self.add_widget(root)

        def _quick_wbs(self, btn, state):
            c = load_cfg(); c["wbs_only"] = state=="down"; save_cfg(c)
            if self._raw: self._render(apply_filters(self._raw, c, load_seen()))

        def _refresh(self, *_):
            if self._busy: return
            self._busy = True; self._status.text = "⏳ جاري الجلب..."
            self._cards.clear_widgets()
            threading.Thread(target=self._bg, daemon=True).start()

        def _bg(self):
            c = load_cfg()
            raw = fetch_all(c.get("sources") or None)
            self._raw = raw
            seen = load_seen()
            shown = apply_filters(raw, c, seen)
            shown.sort(key=score, reverse=True)
            for l in shown: seen.add(l["id"])
            save_seen(seen)
            Clock.schedule_once(lambda dt: self._render(shown, len(raw)))

        def _render(self, lst, total=None):
            self._busy = False
            self._cards.clear_widgets()
            t = total if total is not None else len(lst)
            self._status.text = f"✅ {len(lst)} جديد من {t}"
            if not lst:
                self._cards.add_widget(Label(text="لا إعلانات جديدة", color=C_DIM,
                    size_hint_y=None, height=dp(60))); return
            for l in lst[:60]: self._cards.add_widget(Card(l))


    class SettingsScreen(Screen):
        def __init__(self, sm, **kw):
            super().__init__(name="settings", **kw)
            cfg = load_cfg()
            lay = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
            lay.add_widget(Label(text="⚙️ [b]الإعدادات[/b]", markup=True,
                font_size=dp(18), size_hint_y=None, height=dp(42), color=C_TEXT))

            def row(lbl, w):
                r = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
                r.add_widget(Label(text=lbl, color=C_TEXT, size_hint_x=0.45,
                    halign="right", font_size=dp(12))); r.add_widget(w); return r

            self._price = TextInput(text=str(cfg.get("max_price",700)), input_filter="int", multiline=False)
            lay.add_widget(row("💰 أقصى إيجار (€):", self._price))
            self._rooms = TextInput(text=str(cfg.get("min_rooms",0)), input_filter="float", multiline=False)
            lay.add_widget(row("🛏 أقل غرف:", self._rooms))
            self._hh = TextInput(text=str(cfg.get("household_size",1)), input_filter="int", multiline=False)
            lay.add_widget(row("👥 أفراد:", self._hh))

            self._wbs = ToggleButton(text="WBS فقط: " + ("✅" if cfg.get("wbs_only") else "❌"),
                state="down" if cfg.get("wbs_only") else "normal",
                size_hint_y=None, height=dp(44))
            self._wbs.bind(state=lambda b,s: setattr(b,"text","WBS فقط: "+("✅" if s=="down" else "❌")))
            lay.add_widget(self._wbs)

            # WBS Level row
            wrow = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(6))
            wrow.add_widget(Label(text="🎚 WBS Level:", color=C_TEXT, size_hint_x=0.3, font_size=dp(12)))
            self._wlmin = TextInput(text=str(cfg.get("wbs_level_min",0)), input_filter="int", multiline=False)
            self._wlmax = TextInput(text=str(cfg.get("wbs_level_max",999)), input_filter="int", multiline=False)
            wrow.add_widget(self._wlmin)
            wrow.add_widget(Label(text="—", size_hint_x=0.1, color=C_TEXT))
            wrow.add_widget(self._wlmax)
            lay.add_widget(wrow)

            # WBS presets
            pre = BoxLayout(size_hint_y=None, height=dp(36), spacing=dp(4))
            for lbl, mn, mx in [("100","100","100"),("100-140","100","140"),("كل","0","999")]:
                b = Button(text=lbl, font_size=dp(11), background_color=C_ACCENT)
                b.bind(on_press=lambda _,mn=mn,mx=mx: (
                    setattr(self._wlmin,"text",mn), setattr(self._wlmax,"text",mx)))
                pre.add_widget(b)
            lay.add_widget(pre)

            self._jc = ToggleButton(text="Jobcenter KdU: " + ("✅" if cfg.get("jobcenter_mode") else "❌"),
                state="down" if cfg.get("jobcenter_mode") else "normal",
                size_hint_y=None, height=dp(44))
            self._jc.bind(state=lambda b,s: setattr(b,"text","Jobcenter KdU: "+("✅" if s=="down" else "❌")))
            lay.add_widget(self._jc)

            # Sources
            lay.add_widget(Label(text="🌐 المصادر:", color=C_TEXT, size_hint_y=None, height=dp(26), halign="right"))
            sg = GridLayout(cols=2, size_hint_y=None, height=dp((len(SOURCES)+1)//2*40), spacing=dp(4))
            self._src = {}
            cur = cfg.get("sources") or []
            for sid, (sname, gov) in SOURCES.items():
                on = not cur or sid in cur
                b = ToggleButton(text=("🏛 " if gov else "🔍 ")+sname,
                    state="down" if on else "normal", font_size=dp(11))
                self._src[sid] = b; sg.add_widget(b)
            lay.add_widget(sg)

            s_btn = Button(text="💾 حفظ", size_hint_y=None, height=dp(48), background_color=C_GREEN)
            s_btn.bind(on_press=self._save); lay.add_widget(s_btn)
            b_btn = Button(text="◀️ رجوع", size_hint_y=None, height=dp(44), background_color=C_ACCENT)
            b_btn.bind(on_press=lambda *_: setattr(sm,"current","listings")); lay.add_widget(b_btn)

            sv = ScrollView(); sv.add_widget(lay); self.add_widget(sv)

        def _save(self, *_):
            sel = [sid for sid, b in self._src.items() if b.state=="down"]
            c = load_cfg()
            c.update({
                "max_price":      int(self._price.text or 700),
                "min_rooms":      float(self._rooms.text or 0),
                "household_size": int(self._hh.text or 1),
                "wbs_only":       self._wbs.state=="down",
                "wbs_level_min":  int(self._wlmin.text or 0),
                "wbs_level_max":  int(self._wlmax.text or 999),
                "jobcenter_mode": self._jc.state=="down",
                "sources": sel if len(sel) < len(SOURCES) else [],
            })
            save_cfg(c)
            self.manager.current = "listings"


    class WBSApp(App):
        def build(self):
            self.title = "WBS Berlin"
            sm = ScreenManager()
            sm.add_widget(ListingsScreen(sm))
            sm.add_widget(SettingsScreen(sm))
            return sm

    if __name__ == "__main__":
        WBSApp().run()

else:
    # CLI test
    if __name__ == "__main__":
        print("Testing scrapers...")
        raw = fetch_all()
        cfg = DEFAULTS.copy()
        shown = apply_filters(raw, cfg, set())
        shown.sort(key=score, reverse=True)
        print(f"Found {len(shown)} listings")
        for l in shown[:5]:
            print(f"  [{l['source']}] {l.get('price','-')}€ | {l.get('title','')[:40]}")
