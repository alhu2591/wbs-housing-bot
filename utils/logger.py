"""utils/logger.py — Upgraded logging with DB event handler."""
from __future__ import annotations
import logging
import logging.handlers
import os


class _DBHandler(logging.Handler):
    """Writes WARNING+ logs to the SQLite system_events table."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.WARNING:
            return
        try:
            from database.db import log_event
            log_event(record.levelname, self.format(record)[:2000])
        except Exception:
            pass


def setup_logging(level: int = logging.INFO) -> None:
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        root.addHandler(ch)

    # File handler
    try:
        log_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs"
        )
        os.makedirs(log_dir, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            os.path.join(log_dir, "bot.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:
        pass

    # DB handler for WARNING+
    db_handler = _DBHandler()
    db_handler.setLevel(logging.WARNING)
    db_handler.setFormatter(fmt)
    root.addHandler(db_handler)

    # Quiet noisy libraries
    for lib in ("httpx", "telegram", "apscheduler", "uvicorn", "fastapi"):
        logging.getLogger(lib).setLevel(logging.WARNING)
