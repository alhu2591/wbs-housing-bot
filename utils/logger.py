import logging
import logging.handlers
import os

_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.getenv("LOG_DIR") or os.path.join(_ROOT_DIR, "logs")


def setup_logging() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    log_file = os.path.join(LOG_DIR, "bot.log")

    fmt     = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        handlers.append(
            logging.handlers.RotatingFileHandler(
                log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
            )
        )
    except OSError:
        pass   # read-only filesystem — stream only

    logging.basicConfig(level=logging.INFO, format=fmt, datefmt=datefmt, handlers=handlers)

    for noisy in ("httpx", "httpcore", "telegram", "apscheduler", "hpack"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
