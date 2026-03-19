"""
WBS Berlin Apartments — Standalone Android App
يجلب إعلانات الشقق مباشرة ويعرضها بكل تفاصيلها.
"""
import asyncio
import json
import os
import re
import hashlib
import threading
from datetime import datetime
from pathlib import Path

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
    from kivy.uix.spinner import Spinner
    from kivy.clock import Clock
    from kivy.metrics import dp
    from kivy.utils import get_color_from_hex
    HAS_KIVY = True
except ImportError:
    HAS_KIVY = False

# ── Colors ────────────────────────────────────────────────────────────────────
if HAS_KIVY:
    C_BG      = get_color_from_hex("#1a1a2e")
    C_CARD    = get_color_from_hex("#16213e")
    C_ACCENT  = get_color_from_hex("#0f3460")
    C_GREEN   = get_color_from_hex("#00b894")
    C_ORANGE  = get_color_from_hex("#fdcb6e")
    C_RED     = get_color_from_hex("#d63031")
    C_GOV     = get_color_from_hex("#6c5ce7")
    C_TEXT    = get_color_from_hex("#dfe6e9")
    C_DIM     = get_color_from_hex("#636e72")

# ── Storage ───────────────────────────────────────────────────────────────────
_storage = Path(os.environ.get("EXTERNAL_STORAGE", "."))
CFG_FILE  = _storage / "wbs_config.json"
SEEN_FILE = _storage / "wbs_seen.json"

DEFAULTS = {
    "max_price": 700, "min_rooms": 0.0,
    "wbs_only": False, "household_size": 1,
    "wbs_level_min": 0, "wbs_level_max": 999,
    "jobcenter_mode": False,
    "sources": [],   # empty = all
    "areas":   [],   # empty = all Berlin
}

def load_cfg():
    try:
        if CFG_FILE.exists():
            return {**DEFAULTS, **json.loads(CFG_FILE.read_text())}
    except Exception:
        pass
    return dict(DEFAULTS)

def save_cfg(cfg):
    try:
        CFG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))
    except Exception:
        pass

def load_seen():
    try:
        if SEEN_FILE.exists():
            return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        pass
    return set()

def save_seen(seen):
    try:
        SEEN_FILE.write_text(json.dumps(list(seen)[-3000:]))
    except Exception:
        pass


# ── Source registry ───────────────────────────────────────────────────────────
SOURCES = {
    "gewobag":       ("Gewobag",        True),
    "degewo":        ("Degewo",         True),
    "howoge":        ("Howoge",         True),
    "stadtundland":  ("Stadt und Land", True),
    "berlinovo":     ("Berlinovo",      True),
    "vonovia":       ("Vonovia",        True),
    "gesobau":       ("Gesobau",        True),
    "wbm":           ("WBM",            True),
    "kleinanzeigen": ("Kleinanzeigen",  False),
    "immoscout":     ("ImmoScout24",    False),
}

# Jobcenter KdU limits
JC_KDU = {1:549.0, 2:671.0, 3:789.0, 4:911.0, 5:1021.0, 6:1131.0}
def jc_limit(n): return JC_KDU.get(max(1,min(n,6)), JC_KDU[6] + (max(1,n)-6)*110)

# ── Parsing helpers ───────────────────────────────────────────────────────────

def norm_url(url):
    from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
    try:
        p  = urlparse(url)
        qs = {k: v for k, v in parse_qs(p.query).items()
              if k not in ("utm_source","fbclid","ref","tracking","gclid")}
        return urlunparse(p._replace(query=urlencode(qs, doseq=True), fragment=""))
    except Exception:
        return url

def make_id(url):
    return hashlib.sha256(norm_url(url).encode()).hexdigest()[:14]

def parse_price(raw):
    if not raw: return None
    s = str(raw).replace("€","").replace("EUR","").replace("\xa0","").strip()
    s = re.sub(r"^[^\d]+","",s)
    s = re.sub(r"[^\d\.,]","",s)
    if "," in s and "." in s: s = s.replace(".","").replace(",",".")
    elif "," in s: s = s.replace(",",".")
    elif "." in s:
        parts = s.split(".")
        if len(parts)==2 and len(parts[1])==3 and parts[1].isdigit():
            s = s.replace(".","")
    try:
        v = float(s)
        return v if 50 < v < 5000 else None
    except Exception:
        return None

def parse_rooms(raw):
    if not raw: return None
    m = re.search(r"(\d+[.,]?\d*)", str(raw).replace(",","."))
    try:
        v = float(m.group(1)) if m else None
        return v if v and 0.5 <= v <= 20 else None
    except Exception:
        return None

FEATURE_KW = {
    "balkon":"🌿 بلكونة","terrasse":"🌿 تراس","garten":"🌱 حديقة",
    "aufzug":"🛗 مصعد","fahrstuhl":"🛗 مصعد",
    "einbauküche":"🍳 مطبخ مجهز","keller":"📦 مخزن",
    "stellplatz":"🚗 موقف","tiefgarage":"🚗 جراج",
    "waschmaschine":"🫧 غسالة","barrierefrei":"♿ مهيأ",
    "neubau":"🏗 جديد","erstbezug":"✨ أول سكن",
    "fußbodenheizung":"🌡 تدفئة أرضية","fernwärme":"🌡 مركزية",
    "parkett":"🪵 باركيه","laminat":"🪵 لامينيت",
    "badewanne":"🛁 حوض","saniert":"🔨 مجدد",
}
URGENT_KW = ["ab sofort","sofort frei","sofort verfügbar"]
MONTH_AR  = {"januar":"يناير","februar":"فبراير","märz":"مارس","april":"أبريل",
              "mai":"مايو","juni":"يونيو","juli":"يوليو","august":"أغسطس",
              "september":"سبتمبر","oktober":"أكتوبر","november":"نوفمبر","dezember":"ديسمبر"}

def extract_all(text: str) -> dict:
    tl = text.lower()
    out = {}
    # size
    m = re.search(r"(\d[\d\.,]*)\s*(?:m[²2]|qm\b|quadratmeter)", tl)
    if m:
        try:
            v = float(m.group(1).replace(".","").replace(",","."))
            if 10 < v < 500: out["size_m2"] = v
        except Exception: pass
    # floor
    for pat, label in [
        (r"(\d+)\.\s*og\b",            lambda m: f"الطابق {m.group(1)}"),
        (r"(\d+)\.\s*(?:ober)?geschoss",lambda m: f"الطابق {m.group(1)}"),
        (r"(\d+)\.\s*etage",           lambda m: f"الطابق {m.group(1)}"),
        (r"\berdgeschoss\b|\beg\b",     lambda _: "الطابق الأرضي"),
        (r"\bdachgeschoss\b|\bdg\b",    lambda _: "الطابق العلوي"),
    ]:
        mm = re.search(pat, tl)
        if mm: out["floor"] = label(mm); break
    # availability
    if any(kw in tl for kw in URGENT_KW):
        out["available"] = "فوري 🔥"
    else:
        mm = re.search(r"ab\s+(\d{1,2}[./]\d{1,2}[./]\d{2,4})", tl)
        if mm: out["available"] = f"من {mm.group(1)}"
        else:
            mth = "|".join(MONTH_AR.keys())
            mm = re.search(rf"ab\s+({mth})\s*(\d{{4}})?", tl)
            if mm: out["available"] = f"من {MONTH_AR[mm.group(1)]} {mm.group(2) or ''}".strip()
    # features
    seen, feats = set(), []
    for kw, label in FEATURE_KW.items():
        if kw in tl and label not in seen:
            seen.add(label); feats.append(label)
    if feats: out["features"] = feats
    # deposit
    mm = re.search(r"kaution[:\s]*(\d[\d\.,]*)\s*€?", text, re.I)
    if mm:
        v = parse_price(mm.group(1))
        if v: out["deposit"] = f"{v:.0f} €"
    return out

# ── Scraping ──────────────────────────────────────────────────────────────────

async def fetch_all(enabled_sources: list = None) -> list[dict]:
    try:
        import httpx
    except ImportError:
        return []

    from bs4 import BeautifulSoup
    results = []

    async with httpx.AsyncClient(
        timeout=20, follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Linux; Android 13) Chrome/124.0"},
    ) as c:

        async def _try(coro):
            try: results.extend(await coro)
            except Exception: pass

        async def _gewobag():
            items = []
            r = await c.get("https://www.gewobag.de/wp-json/gewobag/v1/offers?type=wohnung&wbs=1&per_page=50")
            if r.status_code != 200: return items
            data = r.json()
            for item in (data if isinstance(data,list) else data.get("offers",[])):
                url = item.get("link") or item.get("url","")
                if not url.startswith("http"): url = "https://www.gewobag.de" + url
                t = item.get("title","")
                title = t.get("rendered","") if isinstance(t,dict) else str(t)
                d = item.get("beschreibung") or item.get("description","")
                extra = extract_all(f"{title} {d}")
                items.append({"id":make_id(url),"url":url,"source":"gewobag","trusted_wbs":True,
                    "title":title, "price":parse_price(item.get("gesamtmiete") or item.get("warmmiete")),
                    "rooms":parse_rooms(item.get("zimmer")), "location":item.get("bezirk","Berlin"),
                    "wbs_label":"WBS erforderlich", **extra})
            return items

        async def _degewo():
            items = []
            for api in [
                "https://immosuche.degewo.de/de/properties.json?property_type_id=1&categories[]=WBS&per_page=50",
                "https://immosuche.degewo.de/de/search.json?asset_classes[]=1&wbs=1&page=1",
            ]:
                r = await c.get(api)
                if r.status_code != 200: continue
                data = r.json()
                for item in (data if isinstance(data,list) else data.get("results",[])):
                    url = item.get("path","") or item.get("url","")
                    if not url.startswith("http"): url = "https://immosuche.degewo.de" + url
                    extra = extract_all(item.get("text",""))
                    items.append({"id":make_id(url),"url":url,"source":"degewo","trusted_wbs":True,
                        "title":item.get("title",""), "price":parse_price(item.get("warmmiete") or item.get("totalRent")),
                        "rooms":parse_rooms(item.get("zimmer") or item.get("rooms")),
                        "location":item.get("district","Berlin"),
                        "wbs_label":"WBS erforderlich", **extra})
                if items: break
            return items

        async def _kleinanzeigen():
            items = []
            r = await c.get("https://www.kleinanzeigen.de/s-wohnung-mieten/berlin/wbs/k0c203l3331")
            if r.status_code != 200: return items
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text,"lxml")
            for card in soup.select("article.aditem")[:25]:
                a = card.select_one("a.ellipsis,h2 a,h3 a")
                if not a: continue
                href = a["href"]
                url  = "https://www.kleinanzeigen.de" + href if href.startswith("/") else href
                t    = card.select_one("h2,h3,.text-module-begin")
                d    = card.select_one(".aditem-main--middle--description")
                pt   = card.select_one(".aditem-main--middle--price-shipping--price,.price")
                desc = d.get_text(" ",strip=True) if d else ""
                extra = extract_all(desc)
                items.append({"id":make_id(url),"url":url,"source":"kleinanzeigen","trusted_wbs":False,
                    "title":t.get_text(strip=True) if t else "",
                    "price":parse_price(pt.get_text() if pt else None),
                    "rooms":None, "location":"Berlin", "wbs_label":"", **extra})
            return items

        async def _immoscout():
            items = []
            r = await c.get("https://www.immobilienscout24.de/Suche/de/berlin/berlin/wohnung-mieten?wbs=true&price=-700.0")
            if r.status_code != 200: return items
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(r.text,"lxml")
            for card in soup.select("article[data-id],li[data-id],[class*='result-list-entry']")[:20]:
                a = card.select_one("a[href*='/expose/'],a[href*='/Expose/']") or card.select_one("a[href]")
                if not a: continue
                href = a["href"]
                url  = href if href.startswith("http") else "https://www.immobilienscout24.de" + href
                t    = card.select_one("[class*='title'],h2,h3")
                pt   = card.select_one("[class*='price'],[data-testid*='price']")
                rm   = card.select_one("[class*='zimmer'],[class*='room']")
                desc = card.get_text(" ", strip=True)
                extra = extract_all(desc)
                items.append({"id":make_id(url),"url":url,"source":"immoscout","trusted_wbs":False,
                    "title":t.get_text(strip=True) if t else "",
                    "price":parse_price(pt.get_text() if pt else None),
                    "rooms":parse_rooms(rm.get_text() if rm else None),
                    "location":"Berlin", "wbs_label":"", **extra})
            return items

        # Dispatch based on enabled_sources
        active = enabled_sources or list(SOURCES.keys())
        tasks  = []
        if "gewobag"      in active: tasks.append(_gewobag())
        if "degewo"       in active: tasks.append(_degewo())
        if "kleinanzeigen"in active: tasks.append(_kleinanzeigen())
        if "immoscout"    in active: tasks.append(_immoscout())
        for task in tasks:
            await _try(task)

    return results


# ── Filter engine ─────────────────────────────────────────────────────────────

def apply_filters(listings: list, cfg: dict, seen: set) -> list:
    out      = []
    max_p    = cfg.get("max_price", 9999)
    min_r    = float(cfg.get("min_rooms") or 0)
    wbs_only = cfg.get("wbs_only", False)
    wlmin    = int(cfg.get("wbs_level_min") or 0)
    wlmax    = int(cfg.get("wbs_level_max") or 999)
    jc_mode  = cfg.get("jobcenter_mode", False)
    n        = int(cfg.get("household_size") or 1)
    jc_lim   = jc_limit(n) if jc_mode else 9999
    areas    = [a.lower() for a in cfg.get("areas") or []]
    sources  = cfg.get("sources") or []

    for l in listings:
        if l["id"] in seen: continue
        if sources and l["source"] not in sources: continue
        price = l.get("price")
        if price and price > max_p: continue
        rooms = l.get("rooms")
        if rooms and min_r and rooms < min_r: continue
        if wbs_only and not l.get("trusted_wbs"): continue
        # WBS level filter
        wlabel = l.get("wbs_label","")
        mm = re.search(r"wbs[\s\-_]*(\d{2,3})", wlabel.lower())
        if mm and wlmin > 0:
            level = int(mm.group(1))
            if not (wlmin <= level <= wlmax): continue
        # Area filter
        if areas:
            loc = (l.get("location","") + " " + l.get("title","")).lower()
            if not any(a in loc for a in areas): continue
        # Jobcenter filter
        if jc_mode and price and price > jc_lim: continue
        out.append(l)
    return out


def score(l: dict) -> int:
    s = 0
    if l.get("trusted_wbs"): s += 6
    p = l.get("price")
    if p:
        if p < 450: s += 8
        elif p < 550: s += 5
        elif p < 650: s += 2
    r = l.get("rooms")
    if r:
        if r >= 3: s += 4
        elif r >= 2: s += 2
    if l.get("size_m2"): s += 2
    if l.get("available","").startswith("فوري"): s += 3
    s += min(len(l.get("features") or []), 3)
    return s


# ═══════════════════════════════════════════════════════════════════════════════
# Kivy UI
# ═══════════════════════════════════════════════════════════════════════════════

if HAS_KIVY:

    class ListingCard(BoxLayout):
        def __init__(self, listing: dict, **kw):
            super().__init__(
                orientation="vertical", size_hint_y=None,
                padding=dp(10), spacing=dp(3), **kw)
            src_name, is_gov = SOURCES.get(listing["source"], (listing["source"], False))
            icon     = "🏛" if is_gov else "🔍"
            title    = (listing.get("title") or "شقة").strip()[:55]
            price    = f"{listing['price']:.0f} €" if listing.get("price") else "—"
            rooms    = f"{listing['rooms']:.0f} غرف" if listing.get("rooms") else ""
            size     = f"{listing['size_m2']:.0f}m²" if listing.get("size_m2") else ""
            floor    = listing.get("floor","")
            avail    = listing.get("available","")
            dep      = listing.get("deposit","")
            features = listing.get("features") or []
            loc      = listing.get("location","Berlin")
            self.url = listing.get("url","")

            # Calculate height
            n_feat_rows = (len(features) + 3) // 4 if features else 0
            self.height = dp(140 + n_feat_rows * 22)

            # Header: source + WBS badge
            hdr = BoxLayout(size_hint_y=None, height=dp(26))
            hdr.add_widget(Label(
                text=f"{icon} [b]{src_name}[/b]", markup=True,
                color=C_GOV if is_gov else C_ORANGE,
                font_size=dp(13), size_hint_x=0.55, halign="right"))
            if listing.get("trusted_wbs"):
                hdr.add_widget(Label(
                    text="[b]WBS ✅[/b]", markup=True, color=C_GREEN,
                    font_size=dp(12), size_hint_x=0.25))
            wlabel = listing.get("wbs_label","")
            mm = re.search(r"wbs[\s\-_]*(\d{2,3})", wlabel.lower())
            if mm:
                hdr.add_widget(Label(
                    text=f"[b]WBS {mm.group(1)}[/b]", markup=True, color=C_GREEN,
                    font_size=dp(12), size_hint_x=0.2))
            self.add_widget(hdr)

            # Title
            self.add_widget(Label(
                text=title, color=C_TEXT, font_size=dp(13),
                size_hint_y=None, height=dp(22),
                halign="right", valign="middle"))

            # Price + Rooms + Size row
            info = BoxLayout(size_hint_y=None, height=dp(22))
            info.add_widget(Label(text=f"💰 {price}", color=C_GREEN, font_size=dp(13)))
            if rooms: info.add_widget(Label(text=f"🛏 {rooms}", color=C_TEXT, font_size=dp(12)))
            if size:  info.add_widget(Label(text=f"📐 {size}", color=C_TEXT, font_size=dp(12)))
            if floor: info.add_widget(Label(text=floor, color=C_DIM, font_size=dp(11)))
            self.add_widget(info)

            # Location + availability
            loc_row = BoxLayout(size_hint_y=None, height=dp(20))
            loc_row.add_widget(Label(text=f"📍 {loc}", color=C_DIM, font_size=dp(11)))
            if avail:
                loc_row.add_widget(Label(text=f"📅 {avail}", color=C_ORANGE, font_size=dp(11)))
            if dep:
                loc_row.add_widget(Label(text=f"💼 {dep}", color=C_DIM, font_size=dp(11)))
            self.add_widget(loc_row)

            # Features
            if features:
                feat_grid = GridLayout(cols=4, size_hint_y=None, height=dp(n_feat_rows*22), spacing=dp(2))
                for feat in features[:8]:
                    feat_grid.add_widget(Label(text=feat, font_size=dp(10), color=C_DIM))
                self.add_widget(feat_grid)

            # Open button
            btn = Button(
                text="🔗 فتح الإعلان", size_hint_y=None, height=dp(34),
                background_color=C_ACCENT, font_size=dp(12))
            btn.bind(on_press=self._open)
            self.add_widget(btn)

        def _open(self, *_):
            if not self.url: return
            try:
                import jnius
                Intent = jnius.autoclass("android.content.Intent")
                Uri    = jnius.autoclass("android.net.Uri")
                PA     = jnius.autoclass("org.kivy.android.PythonActivity")
                PA.mActivity.startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse(self.url)))
            except Exception:
                try:
                    from kivy.core.clipboard import Clipboard
                    Clipboard.copy(self.url)
                except Exception:
                    pass


    class ListingsScreen(Screen):
        def __init__(self, sm_ref, **kw):
            super().__init__(name="listings", **kw)
            self.sm_ref      = sm_ref
            self._loading    = False
            self._all        = []

            root = BoxLayout(orientation="vertical")

            # Top bar
            bar = BoxLayout(size_hint_y=None, height=dp(54), padding=dp(6), spacing=dp(6))
            bar.add_widget(Label(
                text="🏠 [b]شقق WBS برلين[/b]", markup=True,
                color=C_TEXT, font_size=dp(16), size_hint_x=0.55))
            for txt, cb in [("🔄","refresh"), ("⚙️","settings"), ("🔖","saved")]:
                btn = Button(text=txt, size_hint_x=None, width=dp(46),
                             background_color=C_ACCENT)
                if cb == "refresh":  btn.bind(on_press=self.do_refresh)
                elif cb == "settings": btn.bind(on_press=lambda *_: setattr(sm_ref,"current","settings"))
                elif cb == "saved":  btn.bind(on_press=lambda *_: setattr(sm_ref,"current","saved"))
                bar.add_widget(btn)
            root.add_widget(bar)

            # Filter chips row (quick: WBS only / all)
            chips = BoxLayout(size_hint_y=None, height=dp(38), padding=(dp(6),dp(2)), spacing=dp(6))
            self.wbs_chip = ToggleButton(
                text="WBS فقط", font_size=dp(12),
                state="down" if load_cfg().get("wbs_only") else "normal",
                size_hint_x=None, width=dp(90))
            self.wbs_chip.bind(state=self._quick_wbs)
            chips.add_widget(self.wbs_chip)
            self.status_lbl = Label(text="اضغط 🔄 لجلب الإعلانات", color=C_ORANGE, font_size=dp(12))
            chips.add_widget(self.status_lbl)
            root.add_widget(chips)

            # Cards scroll
            self.cards = BoxLayout(orientation="vertical", spacing=dp(8),
                                   padding=(dp(8), dp(4)), size_hint_y=None)
            self.cards.bind(minimum_height=self.cards.setter("height"))
            scroll = ScrollView()
            scroll.add_widget(self.cards)
            root.add_widget(scroll)
            self.add_widget(root)

        def _quick_wbs(self, btn, state):
            cfg = load_cfg()
            cfg["wbs_only"] = state == "down"
            save_cfg(cfg)
            if self._all:
                self._render(apply_filters(self._all, cfg, load_seen()))

        def do_refresh(self, *_):
            if self._loading: return
            self._loading = True
            self.status_lbl.text = "⏳ جاري الجلب..."
            self.cards.clear_widgets()
            threading.Thread(target=self._bg_fetch, daemon=True).start()

        def _bg_fetch(self):
            cfg   = load_cfg()
            loop  = asyncio.new_event_loop()
            raw   = loop.run_until_complete(fetch_all(cfg.get("sources") or None))
            loop.close()
            self._all = raw
            seen  = load_seen()
            shown = apply_filters(raw, cfg, seen)
            shown.sort(key=score, reverse=True)
            for l in shown: seen.add(l["id"])
            save_seen(seen)
            Clock.schedule_once(lambda dt: self._render(shown, len(raw)))

        def _render(self, listings, total=None):
            self._loading = False
            self.cards.clear_widgets()
            t = total if total is not None else len(listings)
            self.status_lbl.text = f"✅ {len(listings)} جديد من {t}"
            if not listings:
                self.cards.add_widget(Label(
                    text="لا إعلانات جديدة تناسب الفلاتر",
                    color=C_DIM, size_hint_y=None, height=dp(60)))
                return
            for l in listings[:60]:
                self.cards.add_widget(ListingCard(l))


    class SettingsScreen(Screen):
        def __init__(self, sm_ref, **kw):
            super().__init__(name="settings", **kw)
            cfg = load_cfg()

            layout = BoxLayout(orientation="vertical", padding=dp(14), spacing=dp(10))
            layout.add_widget(Label(
                text="⚙️ [b]الإعدادات[/b]", markup=True,
                font_size=dp(20), size_hint_y=None, height=dp(44), color=C_TEXT))

            def field(label, widget):
                row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
                row.add_widget(Label(text=label, color=C_TEXT, size_hint_x=0.45, halign="right", font_size=dp(13)))
                row.add_widget(widget)
                return row

            self.price = TextInput(text=str(cfg.get("max_price",700)), input_filter="int", multiline=False)
            layout.add_widget(field("💰 أقصى إيجار (€):", self.price))

            self.rooms = TextInput(text=str(cfg.get("min_rooms",0)), input_filter="float", multiline=False)
            layout.add_widget(field("🛏 أقل غرف:", self.rooms))

            self.hh = TextInput(text=str(cfg.get("household_size",1)), input_filter="int", multiline=False)
            layout.add_widget(field("👥 أفراد الأسرة:", self.hh))

            self.wbs_btn = ToggleButton(
                text="WBS فقط: " + ("✅" if cfg.get("wbs_only") else "❌"),
                state="down" if cfg.get("wbs_only") else "normal",
                size_hint_y=None, height=dp(46))
            self.wbs_btn.bind(state=lambda b,s: setattr(b,"text","WBS فقط: " + ("✅" if s=="down" else "❌")))
            layout.add_widget(self.wbs_btn)

            # WBS Level
            wlvl = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(6))
            wlvl.add_widget(Label(text="🎚 مستوى WBS:", color=C_TEXT, size_hint_x=0.35, font_size=dp(12)))
            self.wlmin = TextInput(text=str(cfg.get("wbs_level_min",0)), input_filter="int", multiline=False, hint_text="0=أي")
            self.wlmax = TextInput(text=str(cfg.get("wbs_level_max",999)), input_filter="int", multiline=False, hint_text="999=أي")
            wlvl.add_widget(self.wlmin)
            wlvl.add_widget(Label(text="—", size_hint_x=0.1, color=C_TEXT))
            wlvl.add_widget(self.wlmax)
            layout.add_widget(wlvl)

            # WBS presets
            presets = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(4))
            for lbl, mn, mx in [("100فقط","100","100"),("100-140","100","140"),("كل","0","999")]:
                btn = Button(text=lbl, font_size=dp(11), background_color=C_ACCENT)
                btn.bind(on_press=lambda b,mn=mn,mx=mx: (
                    setattr(self.wlmin,"text",mn), setattr(self.wlmax,"text",mx)))
                presets.add_widget(btn)
            layout.add_widget(presets)

            self.jc_btn = ToggleButton(
                text="Jobcenter KdU: " + ("✅" if cfg.get("jobcenter_mode") else "❌"),
                state="down" if cfg.get("jobcenter_mode") else "normal",
                size_hint_y=None, height=dp(46))
            self.jc_btn.bind(state=lambda b,s: setattr(b,"text","Jobcenter KdU: " + ("✅" if s=="down" else "❌")))
            layout.add_widget(self.jc_btn)

            # Source toggles
            layout.add_widget(Label(text="🌐 المصادر:", color=C_TEXT, size_hint_y=None, height=dp(28), halign="right"))
            src_grid = GridLayout(cols=2, size_hint_y=None, height=dp(len(SOURCES)//2*38+38), spacing=dp(4))
            self.src_btns = {}
            current_src = cfg.get("sources") or []
            for src_id, (src_name, is_gov) in SOURCES.items():
                active = not current_src or src_id in current_src
                btn = ToggleButton(
                    text=("🏛 " if is_gov else "🔍 ") + src_name,
                    state="down" if active else "normal",
                    font_size=dp(11))
                self.src_btns[src_id] = btn
                src_grid.add_widget(btn)
            layout.add_widget(src_grid)

            save_btn = Button(text="💾 حفظ", size_hint_y=None, height=dp(50), background_color=C_GREEN)
            save_btn.bind(on_press=self.do_save)
            layout.add_widget(save_btn)

            back_btn = Button(text="◀️ رجوع", size_hint_y=None, height=dp(44), background_color=C_ACCENT)
            back_btn.bind(on_press=lambda *_: setattr(sm_ref,"current","listings"))
            layout.add_widget(back_btn)

            scroll = ScrollView()
            scroll.add_widget(layout)
            self.add_widget(scroll)

        def do_save(self, *_):
            selected_src = [src_id for src_id, btn in self.src_btns.items() if btn.state=="down"]
            cfg = load_cfg()
            cfg.update({
                "max_price":      int(self.price.text or 700),
                "min_rooms":      float(self.rooms.text or 0),
                "household_size": int(self.hh.text or 1),
                "wbs_only":       self.wbs_btn.state == "down",
                "wbs_level_min":  int(self.wlmin.text or 0),
                "wbs_level_max":  int(self.wlmax.text or 999),
                "jobcenter_mode": self.jc_btn.state == "down",
                "sources": selected_src if len(selected_src) < len(SOURCES) else [],
            })
            save_cfg(cfg)
            self.manager.current = "listings"


    class WBSApp(App):
        def build(self):
            self.title  = "WBS Berlin"
            self.icon   = "icon.png"
            sm = ScreenManager()
            sm.add_widget(ListingsScreen(sm))
            sm.add_widget(SettingsScreen(sm))
            return sm


    if __name__ == "__main__":
        WBSApp().run()

else:
    # CLI fallback for testing
    async def cli_main():
        print("Fetching listings...")
        listings = await fetch_all()
        cfg  = DEFAULTS.copy()
        seen = set()
        shown = apply_filters(listings, cfg, seen)
        shown.sort(key=score, reverse=True)
        print(f"Found {len(shown)} listings")
        for l in shown[:5]:
            print(f"  {l.get('source')} | {l.get('price')}€ | {l.get('title','')[:40]}")

    if __name__ == "__main__":
        asyncio.run(cli_main())
