"""
utils/watchdog.py — Loop health monitoring and freeze detection.
Restarts stuck loops, sends admin alerts on critical failures.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Awaitable, Any

logger = logging.getLogger(__name__)

FREEZE_TIMEOUT_SECONDS = 300  # 5 minutes without heartbeat = frozen


class Watchdog:
    """
    Monitors an async loop via heartbeat.
    If no heartbeat received within FREEZE_TIMEOUT_SECONDS,
    fires the on_freeze callback (e.g. restart loop).
    """

    def __init__(
        self,
        on_freeze: Callable[[], Awaitable[None]],
        timeout: int = FREEZE_TIMEOUT_SECONDS,
    ):
        self._on_freeze = on_freeze
        self._timeout = timeout
        self._last_beat = time.monotonic()
        self._running = False
        self._task: asyncio.Task | None = None

    def beat(self) -> None:
        """Call this regularly from the monitored loop."""
        self._last_beat = time.monotonic()

    async def _monitor(self) -> None:
        logger.info("Watchdog monitoring started (timeout=%ds).", self._timeout)
        while self._running:
            await asyncio.sleep(30)
            elapsed = time.monotonic() - self._last_beat
            if elapsed > self._timeout:
                logger.error(
                    "Watchdog: loop frozen for %.0fs! Firing recovery.",
                    elapsed,
                )
                try:
                    await self._on_freeze()
                except Exception as e:
                    logger.error("Watchdog recovery callback failed: %s", e)
                self._last_beat = time.monotonic()  # Reset after recovery attempt

    def start(self) -> None:
        self._running = True
        self._last_beat = time.monotonic()
        self._task = asyncio.ensure_future(self._monitor())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Watchdog stopped.")


class DailySummaryScheduler:
    """Sends a daily summary report to admin via Telegram."""

    def __init__(
        self,
        send_summary: Callable[[dict[str, Any]], Awaitable[None]],
        hour: int = 8,
    ):
        self._send = send_summary
        self._hour = hour
        self._running = False
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        import datetime
        logger.info("Daily summary scheduler started.")
        while self._running:
            now = datetime.datetime.now()
            next_run = now.replace(hour=self._hour, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += datetime.timedelta(days=1)
            wait_secs = (next_run - now).total_seconds()
            await asyncio.sleep(wait_secs)
            if not self._running:
                break
            from database.db import get_daily_summary
            try:
                summary = get_daily_summary()
                await self._send(summary)
            except Exception as e:
                logger.error("Daily summary send failed: %s", e)

    def start(self) -> None:
        self._running = True
        self._task = asyncio.ensure_future(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
