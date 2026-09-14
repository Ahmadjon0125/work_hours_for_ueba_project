"""Logging: konsol (INFO) + fayl (aylanma).

Fayl yo'li va hajmi `.env` dan: `LOG_DIR`, `LOG_MAX_MB`, `LOG_BACKUPS`.
Serverda Docker'siz ishlaganda loglar odatda `/var/log/ueba` ga yoziladi,
loyiha papkasiga emas.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

import config

LOG_DIR = config.LOG_DIR
_configured = False


def _configure():
    global _configured
    if _configured:
        return
    # Papka yaratib bo'lmasa (huquq yo'q, faqat o'qiladigan fayl tizimi) —
    # dastur to'xtamasin, konsol logi bilan davom etsin. Systemd/Docker
    # baribir stdout'ni o'zi yig'adi.
    fayl_yozish = True
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
    except OSError as e:
        fayl_yozish = False
        print(f"OGOHLANTIRISH: log papkasi ochilmadi ({LOG_DIR}): {e}. "
              f"Faqat konsolga yoziladi.")
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)-12s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")

    console = logging.StreamHandler()
    console.setFormatter(fmt)

    root = logging.getLogger("ueba")
    root.setLevel(logging.INFO)
    root.addHandler(console)

    if fayl_yozish:
        try:
            file_handler = RotatingFileHandler(
                os.path.join(LOG_DIR, config.LOG_FILE),
                maxBytes=config.LOG_MAX_MB * 1024 * 1024,
                backupCount=config.LOG_BACKUPS, encoding="utf-8")
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)
        except OSError as e:
            print(f"OGOHLANTIRISH: log fayli ochilmadi: {e}. Faqat konsolga yoziladi.")

    root.propagate = False

    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    _configured = True


def get_logger(name):
    _configure()
    return logging.getLogger(f"ueba.{name}")
