import os
from dotenv import load_dotenv

load_dotenv()

# ── Required ──────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
CHAT_ID:   str = os.getenv("CHAT_ID", "")

# ── Optional proxy (http://user:pass@host:port) ───────────────────────────────
PROXY_URL: str | None = os.getenv("PROXY_URL") or None

# ── Scraping ──────────────────────────────────────────────────────────────────
SCRAPE_INTERVAL: int    = int(os.getenv("SCRAPE_INTERVAL", "5"))
DEFAULT_MAX_PRICE: int  = int(os.getenv("DEFAULT_MAX_PRICE", "600"))
DEFAULT_ROOMS: str      = os.getenv("DEFAULT_ROOMS", "")

# ── Storage ───────────────────────────────────────────────────────────────────
# Local: stores DB in project root
# Server: set DATA_DIR=/tmp or any writable path
_DATA_DIR = os.getenv("DATA_DIR", "")
if not _DATA_DIR or not os.path.isdir(_DATA_DIR):
    _DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH:  str = os.path.join(_DATA_DIR, "wbs_bot.db")
LOG_DIR:  str = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")

LISTING_TTL_DAYS: int = 30

# ── WBS keywords ──────────────────────────────────────────────────────────────
WBS_KEYWORDS: list[str] = [
    "wbs erforderlich", "nur mit wbs", "wohnberechtigungsschein",
    "wbs-berechtigung", "wbs voraussetzung", "sozialer wohnungsbau",
    "geförderte wohnung", "öffentlich gefördert", "mit wbs",
    "wbs notwendig", "wbs benötigt", "wbs vorlegen", "wbs pflicht",
    "wbs 100", "wbs100", "wbs 140", "wbs140",
    "wbs 160", "wbs160", "wbs 180", "wbs180",
    "wbs 200", "wbs200", "wbs 220", "wbs220",
]

# ── HTTP ──────────────────────────────────────────────────────────────────────
REQUEST_TIMEOUT: int  = 20
MAX_RETRIES:     int  = 4
RETRY_WAIT_MIN:  int  = 2
RETRY_WAIT_MAX:  int  = 30
