"""
dashboard/app.py — Lightweight FastAPI monitoring dashboard.
Shows system status, listings, source health, and logs.
Mobile-friendly. No heavy deps beyond fastapi + uvicorn.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

try:
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False
    logger.warning("fastapi not installed — dashboard disabled. pip install fastapi uvicorn")

if HAS_FASTAPI:
    app = FastAPI(title="WBS Housing Bot Dashboard", docs_url=None, redoc_url=None)

    _start_time = time.time()

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> str:
        """Main dashboard page."""
        return _render_dashboard()

    @app.get("/api/stats")
    async def api_stats() -> dict:
        from database.db import get_daily_summary, get_source_stats, get_listings_count, get_seen_count
        summary = get_daily_summary()
        sources = get_source_stats()
        uptime = int(time.time() - _start_time)
        return {
            "uptime_seconds": uptime,
            "uptime_human": _format_uptime(uptime),
            "summary": summary,
            "sources": sources,
        }

    @app.get("/api/listings")
    async def api_listings(limit: int = 20) -> list:
        from database.db import get_recent_listings
        listings = get_recent_listings(limit=min(limit, 100))
        # Strip heavy data_json for API response
        for l in listings:
            l.pop("data_json", None)
        return listings

    @app.get("/api/logs")
    async def api_logs(limit: int = 50) -> list:
        from database.db import get_recent_events
        return get_recent_events(limit=min(limit, 200))

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "uptime": int(time.time() - _start_time)}


def _format_uptime(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}س {m}د"
    return f"{m}د {s}ث"


def _render_dashboard() -> str:
    """Render the full HTML dashboard."""
    return """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>بوت السكن — لوحة التحكم</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
    background: #0f0f1a;
    color: #e0e0e0;
    direction: rtl;
  }
  header {
    background: linear-gradient(135deg, #1a1a2e, #16213e);
    padding: 16px 24px;
    display: flex;
    align-items: center;
    gap: 12px;
    border-bottom: 1px solid #2a2a4a;
  }
  header h1 { font-size: 1.4rem; color: #7c9eff; }
  header span { font-size: 0.85rem; color: #888; }
  .status-dot { width: 10px; height: 10px; border-radius: 50%; background: #22c55e; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 16px;
    padding: 20px;
  }
  .card {
    background: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 20px;
    text-align: center;
  }
  .card .value { font-size: 2rem; font-weight: bold; color: #7c9eff; }
  .card .label { font-size: 0.85rem; color: #888; margin-top: 4px; }

  .section { padding: 0 20px 20px; }
  .section h2 { font-size: 1.1rem; color: #7c9eff; margin-bottom: 12px; padding-bottom: 6px; border-bottom: 1px solid #2a2a4a; }

  table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
  th { background: #16213e; padding: 8px 12px; text-align: right; color: #aaa; }
  td { padding: 8px 12px; border-bottom: 1px solid #1e1e30; }
  tr:hover td { background: #1a1a2e; }

  .badge { display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 0.75rem; }
  .badge-ok { background: #14532d; color: #22c55e; }
  .badge-fail { background: #450a0a; color: #f87171; }
  .badge-warn { background: #451a03; color: #fb923c; }

  .log-entry { padding: 6px 12px; border-bottom: 1px solid #1e1e30; font-size: 0.8rem; font-family: monospace; }
  .log-INFO { color: #86efac; }
  .log-WARNING { color: #fcd34d; }
  .log-ERROR { color: #f87171; }
  .time-col { color: #666; font-size: 0.75rem; }

  #refresh-btn {
    background: #3b3bff;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 8px 16px;
    cursor: pointer;
    font-size: 0.9rem;
    margin: 0 20px 20px;
  }
  #refresh-btn:hover { background: #5555ff; }
  #last-update { color: #666; font-size: 0.8rem; margin: 0 20px 10px; }
</style>
</head>
<body>
<header>
  <div class="status-dot" id="status-dot"></div>
  <h1>🏠 بوت السكن — لوحة التحكم</h1>
  <span id="uptime-label">جاري التحميل...</span>
</header>

<div class="grid" id="stats-grid">
  <div class="card"><div class="value" id="stat-today">—</div><div class="label">إعلانات اليوم</div></div>
  <div class="card"><div class="value" id="stat-total">—</div><div class="label">إجمالي الإعلانات</div></div>
  <div class="card"><div class="value" id="stat-seen">—</div><div class="label">إجمالي المشاهدات</div></div>
  <div class="card"><div class="value" id="stat-errors">—</div><div class="label">أخطاء اليوم</div></div>
  <div class="card"><div class="value" id="stat-sources">—</div><div class="label">مصادر نشطة</div></div>
</div>

<button id="refresh-btn" onclick="loadAll()">🔄 تحديث</button>
<div id="last-update"></div>

<div class="section">
  <h2>📊 حالة المصادر</h2>
  <table id="sources-table">
    <thead><tr>
      <th>المصدر</th><th>الطلبات</th><th>نجاح</th><th>فشل</th><th>آخر استجابة</th><th>الحالة</th>
    </tr></thead>
    <tbody id="sources-body"></tbody>
  </table>
</div>

<div class="section">
  <h2>🏠 آخر الإعلانات</h2>
  <table id="listings-table">
    <thead><tr>
      <th>العنوان</th><th>السعر</th><th>الموقع</th><th>التقييم</th><th>الجوبسنتر</th>
    </tr></thead>
    <tbody id="listings-body"></tbody>
  </table>
</div>

<div class="section">
  <h2>📋 سجل الأحداث</h2>
  <div id="logs-container"></div>
</div>

<script>
async function loadStats() {
  const r = await fetch('/api/stats');
  const d = await r.json();
  document.getElementById('stat-today').textContent = d.summary.listings_found_24h;
  document.getElementById('stat-total').textContent = d.summary.total_listings;
  document.getElementById('stat-seen').textContent = d.summary.total_seen;
  document.getElementById('stat-errors').textContent = d.summary.errors_24h;
  const active = d.sources.filter(s => !s.disabled).length;
  document.getElementById('stat-sources').textContent = active + '/' + d.sources.length;
  document.getElementById('uptime-label').textContent = 'وقت التشغيل: ' + d.uptime_human;

  const tbody = document.getElementById('sources-body');
  tbody.innerHTML = '';
  for (const s of d.sources) {
    const rate = s.total_requests ? Math.round(s.success_count/s.total_requests*100) : 0;
    const badge = s.disabled ? '<span class="badge badge-fail">معطل</span>'
      : rate >= 80 ? '<span class="badge badge-ok">نشط</span>'
      : '<span class="badge badge-warn">بطيء</span>';
    tbody.innerHTML += `<tr>
      <td>${s.source}</td>
      <td>${s.total_requests}</td>
      <td>${s.success_count}</td>
      <td>${s.fail_count}</td>
      <td>${Math.round(s.last_response_ms)}ms</td>
      <td>${badge}</td>
    </tr>`;
  }
}

async function loadListings() {
  const r = await fetch('/api/listings?limit=10');
  const listings = await r.json();
  const tbody = document.getElementById('listings-body');
  tbody.innerHTML = '';
  for (const l of listings) {
    const jc = l.jobcenter_ok ? '<span class="badge badge-ok">✅</span>' : '<span class="badge badge-fail">❌</span>';
    tbody.innerHTML += `<tr>
      <td>${(l.title||'').substring(0,40)}</td>
      <td>${l.price ? l.price + ' €' : '—'}</td>
      <td>${(l.location||'').substring(0,30)}</td>
      <td>${l.score}/100</td>
      <td>${jc}</td>
    </tr>`;
  }
}

async function loadLogs() {
  const r = await fetch('/api/logs?limit=30');
  const logs = await r.json();
  const container = document.getElementById('logs-container');
  container.innerHTML = '';
  for (const e of logs) {
    const t = new Date(e.created_at * 1000).toLocaleTimeString('ar-SA');
    container.innerHTML += `<div class="log-entry log-${e.level}">
      <span class="time-col">${t}</span> [${e.level}] ${e.message}
    </div>`;
  }
}

async function loadAll() {
  await Promise.all([loadStats(), loadListings(), loadLogs()]);
  document.getElementById('last-update').textContent = 'آخر تحديث: ' + new Date().toLocaleTimeString('ar-SA');
}

loadAll();
setInterval(loadAll, 30000); // Auto-refresh every 30s
</script>
</body>
</html>"""


async def start_dashboard(host: str = "0.0.0.0", port: int = 8080) -> None:
    """Start the dashboard server in the background."""
    if not HAS_FASTAPI:
        logger.warning("Dashboard not started: fastapi/uvicorn not installed.")
        return
    try:
        import uvicorn
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        logger.info("Dashboard starting at http://%s:%d", host, port)
        import asyncio
        asyncio.create_task(server.serve())
    except ImportError:
        logger.warning("uvicorn not installed — dashboard disabled. pip install uvicorn")
    except Exception as e:
        logger.error("Dashboard start failed: %s", e)
