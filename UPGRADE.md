# 🚀 WBS Housing Bot v2.0 — Upgrade Guide

## What's New

| Feature | v1 | v2 |
|---------|----|----|
| Scraping loop | Interval-only (10–60 min) | Real-time (30–120s continuous) |
| AI filtering | Keyword-based | NLP classifier + 0–100 scoring |
| Jobcenter rules | Manual config | Automatic filtering + badge |
| Database | JSON files | SQLite (indexed, fast) |
| Telegram UI | German labels | Full Arabic inline menu |
| Dashboard | None | FastAPI web UI |
| Source health | None | Auto-disable + auto-recover |
| Watchdog | None | Freeze detection + restart |
| Admin alerts | None | Error + daily summary |

---

## 📁 New Files to Add to Your Repo

Copy these new directories/files into your existing project root:

```
ai/
  __init__.py
  scorer.py              ← NLP classifier + 0–100 scorer

database/
  __init__.py
  db.py                  ← SQLite layer (replaces seen.json)

dashboard/
  __init__.py
  app.py                 ← FastAPI monitoring dashboard

bot/
  arabic_ui.py           ← Full Arabic notification builder
  callback_handler.py    ← Inline button handler (new)

scraper/
  realtime_engine.py     ← Continuous async loop (new core)
  registry_adapter.py    ← Bridges existing scrapers to new engine

utils/
  watchdog.py            ← Loop health monitor

main.py                  ← REPLACE existing main.py with this
config.json              ← MERGE new fields into your existing config
requirements.txt         ← REPLACE (adds fastapi, uvicorn)
```

---

## ⚡ Installation Steps

### 1. Back up existing data
```bash
cp data/seen.json data/seen.json.bak
cp config.json config.json.bak
```

### 2. Copy new files
```bash
# Copy all new files from this upgrade package into your wbs-housing-bot/ directory
cp -r ai/ bot/arabic_ui.py bot/callback_handler.py database/ dashboard/ \
       scraper/realtime_engine.py scraper/registry_adapter.py utils/watchdog.py \
       main.py requirements.txt /path/to/wbs-housing-bot/
```

### 3. Install new dependencies
```bash
pip install fastapi uvicorn python-dotenv --break-system-packages
# Or on desktop:
pip install fastapi uvicorn python-dotenv
```

### 4. Merge config.json
Add these fields to your existing `config.json`:
```json
{
  "interval_seconds": 60,
  "min_score": 0,
  "jobcenter_rules": {
    "max_rent": 700,
    "max_size": 50,
    "rooms": 1
  },
  "dashboard_enabled": true,
  "dashboard_port": 8080,
  "notify_admin_on_error": true,
  "daily_summary_hour": 8
}
```

### 5. Optional: Add ADMIN_CHAT_ID
```bash
echo "ADMIN_CHAT_ID=your_telegram_id" >> .env
```

### 6. Run
```bash
python main.py
# With dashboard disabled:
python main.py --no-dashboard
# Test scrape only:
python main.py --test-scrape
```

---

## 🎛 New Telegram Commands

| Command | Action |
|---------|--------|
| `/start` | Start + show Arabic menu |
| `/settings` | Open control panel |
| `/status` | System status + stats |
| `/scan` | Trigger immediate scan |

---

## 📊 Dashboard

Open in browser: `http://localhost:8080`

Shows:
- Live source health (success rate, response time)
- Recent listings with scores
- System event log
- Auto-refreshes every 30s

---

## 🧠 AI Scoring

Each listing is scored 0–100:

| Factor | Weight |
|--------|--------|
| Price vs Jobcenter limit | 30 pts |
| WBS compatibility | 25 pts |
| Size fit | 20 pts |
| Room count | 15 pts |
| Location relevance | 10 pts |

Listings classified as WG, Senioren, commercial, or temporary are **automatically rejected**.

---

## ⚙️ Jobcenter Rules

Configure in `config.json`:
```json
"jobcenter_rules": {
  "max_rent": 700,
  "max_size": 50,
  "rooms": 1
}
```

Each listing will show: ✅ مناسب للجوبسنتر or ❌ غير مناسب للجوبسنتر

---

## 🔄 Backward Compatibility

- All existing scrapers work unchanged
- `seen.json` is automatically migrated to SQLite on first run
- `data/config.json` (Telegram runtime config) still works
- `--test-scrape` flag still works

---

## 🐛 Troubleshooting

**Dashboard not starting:**
```bash
pip install fastapi uvicorn
```

**Database errors:**
```bash
rm data/housing.db  # Reset DB (loses history, not configs)
```

**Bot not responding:**
Check that `BOT_TOKEN` and `CHAT_ID` are set in `.env`

**Sources auto-disabled:**
They recover automatically after 30 minutes, or restart the bot.
