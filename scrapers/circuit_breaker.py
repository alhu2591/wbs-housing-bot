"""
Per-scraper circuit breaker — prevents hammering failing sources.

States:
  CLOSED   → scraper runs normally
  OPEN     → scraper is skipped (too many recent failures)
  HALF     → one trial request allowed to test recovery
"""
import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Thresholds
FAILURE_THRESHOLD  = 5      # consecutive failures → OPEN
RECOVERY_TIMEOUT   = 300    # seconds before HALF_OPEN retry (5 min)
SUCCESS_THRESHOLD  = 2      # consecutive successes in HALF → CLOSED


class CircuitBreaker:
    def __init__(self, name: str):
        self.name               = name
        self._failures          = 0
        self._successes         = 0
        self._state             = "CLOSED"
        self._opened_at: datetime | None = None

    @property
    def state(self) -> str:
        if self._state == "OPEN":
            elapsed = (datetime.utcnow() - self._opened_at).total_seconds()
            if elapsed >= RECOVERY_TIMEOUT:
                self._state = "HALF"
                self._successes = 0
                logger.info("[CB] %s → HALF_OPEN (testing recovery)", self.name)
        return self._state

    def allow(self) -> bool:
        return self.state in ("CLOSED", "HALF")

    def record_success(self) -> None:
        self._failures = 0
        if self._state == "HALF":
            self._successes += 1
            if self._successes >= SUCCESS_THRESHOLD:
                self._state = "CLOSED"
                logger.info("[CB] %s → CLOSED (recovered)", self.name)
        elif self._state == "CLOSED":
            self._successes = min(self._successes + 1, SUCCESS_THRESHOLD)

    def record_failure(self) -> None:
        self._successes = 0
        self._failures += 1
        if self._state in ("CLOSED", "HALF") and self._failures >= FAILURE_THRESHOLD:
            self._state    = "OPEN"
            self._opened_at = datetime.utcnow()
            logger.warning(
                "[CB] %s → OPEN after %d failures (retry in %ds)",
                self.name, self._failures, RECOVERY_TIMEOUT,
            )

    def status(self) -> dict:
        return {
            "name":     self.name,
            "state":    self.state,
            "failures": self._failures,
            "opened_at": self._opened_at.isoformat() if self._opened_at else None,
        }


# ── Global registry ────────────────────────────────────────────────────────────
_breakers: dict[str, CircuitBreaker] = {}


def get_breaker(source: str) -> CircuitBreaker:
    if source not in _breakers:
        _breakers[source] = CircuitBreaker(source)
    return _breakers[source]


def all_statuses() -> list[dict]:
    return [cb.status() for cb in _breakers.values()]
