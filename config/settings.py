import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
CHAT_ID: str = os.getenv("CHAT_ID", "")
PROXY_URL: str | None = os.getenv("PROXY_URL") or None
SCRAPER_API_KEY: str = os.getenv("SCRAPER_API_KEY", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
SCRAPE_INTERVAL: int = int(os.getenv("SCRAPE_INTERVAL", "2"))

DEFAULT_MAX_PRICE: int = int(os.getenv("DEFAULT_MAX_PRICE", "600"))
DEFAULT_ROOMS: str = os.getenv("DEFAULT_ROOMS", "")
DEFAULT_AREA: str = os.getenv("DEFAULT_AREA", "")

# Persistent storage:
# - Railway: /tmp persists between restarts (only wiped on redeploy)
# - Set DATA_DIR=/tmp in Railway Variables
# - Local dev: falls back to project root
_DATA_DIR = os.getenv("DATA_DIR", "/tmp")
if not os.path.isdir(_DATA_DIR):
    _DATA_DIR = os.path.dirname(os.path.dirname(__file__))

DB_PATH: str = os.path.join(_DATA_DIR, "wbs_bot.db")
LOG_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")

LISTING_TTL_DAYS: int = 30

WBS_KEYWORDS: list[str] = [
    "wbs erforderlich",
    "nur mit wbs",
    "wohnberechtigungsschein",
    "wbs-berechtigung",
    "wbs voraussetzung",
    "sozialer wohnungsbau",
    "geförderte wohnung",
    "öffentlich gefördert",
    "wbs 100",
    "wbs100",
]

REQUEST_TIMEOUT: int = 20
MAX_RETRIES: int = 4
RETRY_WAIT_MIN: int = 2
RETRY_WAIT_MAX: int = 30
