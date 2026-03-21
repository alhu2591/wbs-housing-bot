# WBS Housing Bot (Termux / Telegram)

Professional scraper + Telegram notifications for Berlin WBS-oriented listings.

## Features

- **13 site scrapers** (overview) + **detail-page enrichment** (description, images, size, rooms, WBS hints)
- **config.json** filters: city, max price, min size, min rooms, WBS required, include/exclude keywords, images on/off
- **Dedup** in `data/seen.json`
- **httpx** + Android UA, `de-DE`, 3× retry
- Dependencies: `python-telegram-bot`, `httpx`, `beautifulsoup4`, `apscheduler` only

## Setup (Termux)

```bash
pkg install python
cd wbs-housing-bot
pip install -r requirements.txt
cp .env.example .env   # add BOT_TOKEN + CHAT_ID
nano config.json       # adjust filters
python main.py
```

## Layout

```
scraper/          # base_scraper.py, detail_page.py, pipeline.py, registry.py, <site>.py
bot/              # telegram_bot.py
utils/            # parser.py, filters.py, storage.py, soup.py, logger.py, config_loader.py
data/seen.json
main.py
config.json
```

## Commands

- `python main.py` — scheduler + Telegram polling
- `python main.py --test-scrape` — one cycle, log only (no Telegram)

## Note

Many portals change HTML or block bots (401/404). Failed sources are logged as **WARNING**; the bot keeps running.
