"""Logging: konsol (INFO) + logs/ueba.log (5MB x 3)."""
import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
_configured = False


def _configure():
    global _configured
    if _configured:
        return
    os.makedirs(LOG_DIR, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)-12s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    file_handler = RotatingFileHandler(os.path.join(LOG_DIR, "ueba.log"),
                                       maxBytes=5 * 1024 * 1024, backupCount=3,
                                       encoding="utf-8")
    file_handler.setFormatter(fmt)

    root = logging.getLogger("ueba")
    root.setLevel(logging.INFO)
    root.addHandler(console)
    root.addHandler(file_handler)
    root.propagate = False

    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    _configured = True


def get_logger(name):
    _configure()
    return logging.getLogger(f"ueba.{name}")
