"""
Track scraper failures / timeouts; skip sources after repeated failures until cooldown expires.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(_ROOT, "data", "source_health.json")

_STATE: dict[str, dict[str, Any]] = {}
_COOLDOWN_SEC = 900.0
_FAIL_THRESHOLD = 2


def _load() -> None:
    global _STATE
    try:
        if os.path.exists(_PATH) and os.path.getsize(_PATH) > 2:
            with open(_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                _STATE = {k: dict(v) for k, v in raw.items() if isinstance(v, dict)}
    except Exception as e:
        logger.debug("source_health load: %s", e)


def _save() -> None:
    try:
        os.makedirs(os.path.dirname(_PATH), exist_ok=True)
        tmp = f"{_PATH}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_STATE, f)
        os.replace(tmp, _PATH)
    except Exception as e:
        logger.debug("source_health save: %s", e)


_load()


def is_in_cooldown(source_id: str) -> bool:
    st = _STATE.get(source_id)
    if not st:
        return False
    fails = int(st.get("fails") or 0)
    last_fail = float(st.get("last_fail") or 0)
    if fails < _FAIL_THRESHOLD:
        return False
    if time.time() - last_fail >= _COOLDOWN_SEC:
        logger.info(
            "event=source_cooldown_reset source=%s fails_was=%d",
            source_id,
            fails,
        )
        _STATE[source_id] = {
            "fails": 0,
            "last_ok": float(st.get("last_ok") or 0),
            "last_fail": 0.0,
        }
        _save()
        return False
    logger.warning(
        "event=source_skipped_cooldown source=%s failures=%d",
        source_id,
        fails,
    )
    return True


def record_ok(source_id: str) -> None:
    _STATE[source_id] = {"fails": 0, "last_ok": time.time(), "last_fail": 0.0}
    _save()


def record_fail(source_id: str, reason: str) -> None:
    st = _STATE.get(source_id, {})
    fails = int(st.get("fails") or 0) + 1
    _STATE[source_id] = {
        "fails": fails,
        "last_fail": time.time(),
        "last_ok": float(st.get("last_ok") or 0),
        "reason": reason[:200],
    }
    logger.warning(
        "event=source_fail source=%s reason=%s fail_count=%d",
        source_id,
        reason[:80],
        fails,
    )
    _save()
