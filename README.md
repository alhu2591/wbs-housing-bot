# WBS Housing Bot

A **Telegram bot** that continuously scrapes **housing rental listings** in Germany (with a focus on **Berlin** and **WBS** / subsidised housing), enriches each offer from its **detail page**, and notifies you on Telegram with **structured text** and **photos**.

The pipeline combines **overview scraping** (many portals), **per-listing HTTP fetch** (full description, images, size, rooms), **WBS-oriented detection** (keywords + trusted public-housing sources), **configurable filters** (`config.json`), and **deduplication** so you never get the same listing twice.

---

## Features

| Area | What it does |
|------|----------------|
| **Data extraction** | Title, **price** (normalised to whole €), **location**, **size (m²)**, **rooms**, **full description**, **listing URL**, and **image URLs** (deduplicated, up to 5 sent per message). |
| **Filtering** | `config.json`: city, max price, min size, minimum rooms, WBS requirement, include/exclude keywords, scrape interval, optional image albums. |
| **Deduplication** | Sent listing IDs are stored in `data/seen.json`; matches are skipped on later runs. |
| **Telegram** | Clean German-style caption + **media group** (first photo carries the caption; link button when useful). |
| **Termux / Android** | Runs on **Termux** with standard Python; uses `httpx`, Android-like `User-Agent`, `Accept-Language: de-DE`, and **3× retry** on network errors. |
| **Resilience** | Scrapers that fail (404, bot protection, site changes) log **WARNING** and do not crash the whole bot. |

---

## Prerequisites

- **Android** with **[Termux](https://termux.dev/)** (or any Linux/macOS/WSL environment).
- **Python ≥ 3.13** (3.11+ may work; Termux often ships recent Python—use `python --version`).
- **`pip`** and **`git`**.
- **Packages** (installed automatically from `requirements.txt`):
  - `python-telegram-bot`
  - `httpx`
  - `beautifulsoup4`
  - `apscheduler`

> **Note:** `httpx` and `apscheduler` are **already listed** in `requirements.txt`. You do not need to install them separately unless you maintain a custom environment.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/alhu2591/wbs-housing-bot.git
cd wbs-housing-bot
```

*(Replace `alhu2591` with your fork username if you use a fork.)*

### 2. Termux system packages (recommended)

Some Python wheels need build tools or crypto libraries on Termux:

```bash
pkg update
pkg install python git clang libffi openssl
```

### 3. Python dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Environment variables (Telegram)

```bash
cp .env.example .env
nano .env   # or use any editor
```

Set at least:

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | From [@BotFather](https://t.me/BotFather) (`/newbot`). |
| `CHAT_ID` | Your user or group ID (e.g. from [@userinfobot](https://t.me/userinfobot)). |

Optional: `PROXY_URL`, `REQUEST_TIMEOUT`, `MAX_RETRIES` (see `.env.example`).

### 5. Application configuration

Edit **`config.json`** next to `main.py` (see [Configuration](#configuration)).

---

## Configuration

All **search and notification behaviour** is driven by **`config.json`**.
The bot expects `config.json` to contain all keys shown below.

To disable a specific filter, set its value to `null` (for example `"max_price": null`).

Telegram button changes are persisted to **`data/config.json`** and take effect immediately (including rescheduling the scrape interval).

### Main keys

| Key | Type | Description |
|-----|------|-------------|
| `city` | string | City filter (e.g. `Berlin`). Empty string disables city filtering. |
| `max_price` | number or null | Maximum **cold/warm** rent in **€**. `null` disables the max-price filter. |
| `min_size` | number or null | Minimum **living area** in **m²**. `null` disables the min-size filter. |
| `rooms` | number or null | Minimum **number of rooms**. `null` disables the min-rooms filter. |
| `wbs_required` | bool | If `true`, listing must look WBS/social or come from a **trusted public-housing** source. |
| `wbs_filter` | array of strings | Extra phrases that count toward WBS / social wording (German). |
| `keywords_include` | array | **All** of these substrings must appear in title/location/description (case-insensitive). Empty = no include filter. |
| `keywords_exclude` | array | If any substring appears, the listing is **dropped**. |
| `sources` | array of strings | Enabled portal/source IDs (scraper modules). Examples: `gewobag`, `degewo`, `howoge`, `stadtundland`, `deutschewohnen`, `berlinovo`, `vonovia`, `gesobau`, `wbm`, `immoscout`, `wggesucht`, `ebay_kleinanzeigen`, `immowelt`, `immonet`. |
| `interval_minutes` | int | Minutes between scrape cycles (clamped **5–60** in code). |
| `notify_enabled` | bool | If `false`, scrape+dedupe runs but Telegram notifications are not sent. |
| `send_images` | bool | If `true`, send image albums as a Telegram **media group** when URLs are available. |
| `max_images` | int | Max **images per listing** (media group). |
| `max_per_cycle` | int | Max **new** listings to send per cycle (default range enforced in code). |
| `detail_concurrency` | int | Parallel detail-page fetches (bounded for stability on mobile). |

### Example `config.json`

```json
{
  "city": "Berlin",
  "max_price": 700,
  "min_size": 30,
  "rooms": 1,
  "wbs_required": true,
  "interval_minutes": 10,
  "notify_enabled": true,
  "keywords_include": [],
  "keywords_exclude": [],
  "send_images": true,
  "wbs_filter": [
    "wbs 100",
    "wbs 140",
    "wbs erforderlich",
    "wohnberechtigungsschein",
    "geförderte wohnung"
  ],
  "sources": [
    "gewobag",
    "degewo",
    "howoge",
    "stadtundland",
    "deutschewohnen",
    "berlinovo",
    "vonovia",
    "gesobau",
    "wbm",
    "immoscout",
    "wggesucht",
    "ebay_kleinanzeigen",
    "immowelt",
    "immonet"
  ],
  "max_images": 5,
  "max_per_cycle": 5,
  "detail_concurrency": 4
}
```

After editing `config.json`, restart the bot so changes take effect.

---

## Running the bot

### Foreground (testing)

```bash
cd wbs-housing-bot
python main.py
```

### One-off scrape (no Telegram)

Useful on a PC or in Termux to verify scraping without sending messages:

```bash
python main.py --test-scrape
```

### Continuous running on Termux

**Option A — `nohup` (simple background process)**

```bash
cd ~/wbs-housing-bot
nohup python main.py > bot.out 2>&1 &
```

Check output: `tail -f bot.out`  
Stop: find PID with `ps aux | grep main.py` then `kill <pid>`.

**Option B — `tmux` or `screen` (recommended)**

```bash
pkg install tmux
tmux new -s wbsbot
cd ~/wbs-housing-bot && python main.py
# Detach: Ctrl+B then D
# Reattach: tmux attach -t wbsbot
```

**Option C — Termux:Boot / Tasker / Widget**

Use your preferred **Termux widget** or automation to run a short script that `cd`s into the project and starts `python main.py` in a persistent session (same idea as tmux).

> **Battery & network:** Lower `interval_minutes` increases traffic and wakeups; values around **10–15** are a reasonable default on mobile.

---

## Project structure

```
wbs-housing-bot/
├── main.py                 # Entry point: scheduler + optional Telegram polling
├── config.json             # Base filters + behaviour
├── requirements.txt        # Python dependencies
├── .env.example            # Template for BOT_TOKEN / CHAT_ID
├── data/
│   ├── seen.json           # Deduplication store (auto-updated)
│   └── config.json        # Runtime config persisted from Telegram UI
├── logs/
│   └── bot.log             # Rotating file log (if writable)
├── scraper/
│   ├── base_scraper.py     # httpx client, headers, retries
│   ├── detail_page.py      # Per-URL enrichment (HTML → fields + images)
│   ├── pipeline.py         # Overview → dedupe → enrich → filter
│   ├── registry.py         # Portal/source registry
│   └── *.py                # One module per portal (e.g. gewobag, berlinovo, …)
├── bot/
│   └── telegram_bot.py     # Inline UI + sending listings
└── utils/
    ├── config_loader.py    # Load & validate config.json
    ├── config_store.py     # Persist Telegram runtime config to data/config.json
    ├── parser.py           # Price, rooms, size, WBS helpers, listing builder
    ├── filters.py          # Apply config rules to a listing dict
    ├── storage.py          # Read/write seen.json
    ├── soup.py             # BeautifulSoup(html.parser) helper
    └── logger.py           # Logging setup
```

---

## Usage

### How listings look in Telegram

Each notification is built as a **single caption** (plain text) with blocks such as:

- **Title** (one line)
- **Preis:** … €  
- **Ort:** … (location / district / city when known)  
- **Fläche:** … m² · **Zimmer:** …  
- **WBS:** short status or phrase when detected  
- Short **description** excerpt (truncated safely for Telegram limits)  
- **Link** to the original listing  

Exact wording may evolve slightly; the goal is **scannable, professional German labels**.

### How images are sent

- If `send_images` is **true** and image URLs were collected, the bot sends a **media group** with up to `max_images` photos.
- The **first** image carries the **caption** (Telegram limit 1024 characters for photo captions).
- If the album fails (e.g. bad URL), the bot **falls back** to a text-only message.
- A small follow-up with an **“Öffnen”** link button may appear after a successful album.

### How filtering works
1. **Overview** results from the active `sources` portals in `config.json` are merged.  
2. Listings **already in** `data/seen.json` are skipped.  
3. Each **candidate** is fetched again (**detail page**) to improve description, images, size, rooms, and WBS hints.  
4. **`utils/filters.py`** applies `config.json` (price, size, rooms, city, WBS, keywords).  
5. If `notify_enabled` is `true`, up to **`max_per_cycle`** listings are sent; successful sends are appended to **`seen.json`**.  
   If `notify_enabled` is `false`, matches are still marked as seen, but Telegram notifications are not sent.

### Telegram UI (inline settings)

- Use `/settings` to open the inline keyboard menu.
- Buttons let you update `city`, `max_price`, `min_size`, `rooms`, WBS requirement, keywords include/exclude, enabled `sources`, notification interval, and `send_images`.
- Changes persist to `data/config.json` and are applied immediately (interval changes reschedule the job).

---

## Logging

| Level | Typical content |
|-------|------------------|
| **INFO** | Cycle start/end, counts of matches, successful sends, migration notes (e.g. `seen.json`). |
| **WARNING** | HTTP 4xx/5xx from portals, JSON parse issues, Telegram album fallback, non-fatal scraper problems. |
| **ERROR** | Failed Telegram delivery after retries, unexpected exceptions in send loop or persistence. |

**Console:** All levels go to **stdout** (Termux terminal).

**File:** If the `logs/` directory is writable, a rotating file is created at **`logs/bot.log`** (size-capped; older files rotated). On read-only environments, logging stays **console-only**.

Third-party libraries (`httpx`, `telegram`, `apscheduler`, …) are toned down to **WARNING** to keep logs readable.

---

## Contributing

Contributions are welcome.

1. **Fork** the repository on GitHub.  
2. Create a **feature branch** (`git checkout -b feature/my-improvement`).  
3. Make focused changes (e.g. fix one scraper, improve parsers, docs).  
4. Run `python main.py --test-scrape` and a short live test if you use Telegram.  
5. Open a **Pull Request** with a clear description and, if relevant, sample log output.

Please respect site **terms of use** and **robots** rules; this tool is intended for **personal** monitoring, not aggressive bulk scraping.

---

## License

This project is released under the **MIT License**.

> If the repository does not yet include a `LICENSE` file, you may add one with the standard MIT text; the intention above is **permissive open source** use.

---

## Disclaimer

- Listing data depends on **third-party websites**; selectors and APIs **break** when sites change.  
- **WBS eligibility** is inferred from text and source type—it is **not legal advice**. Always verify on the official offer and with the landlord or housing company.  
- Use responsibly and in line with each portal’s policies.
