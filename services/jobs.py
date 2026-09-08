"""O'qitish job'lari — holat MongoDB'da saqlanadi (ARCH-01).

Avval holat API protsessining xotirasida (oddiy dict) turardi: dastur qayta
ishga tushsa yo'qolardi, tarix qolmasdi va parallel ishga tushirish qulfi
(`threading.Lock`) faqat bitta protsess ichida ishlardi.

Endi har o'qitish `training_jobs` da hujjat: bosqichlari yozib boriladi,
tarix qoladi, parallel ishga tushirishni esa **unique indeks** to'xtatadi
(bir vaqtda faqat bitta `status: "running"` hujjat bo'la oladi).
"""
from datetime import datetime

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

import config
from services.mongo import local_db
from utils.logger import get_logger

log = get_logger("jobs")


class JobAlreadyRunning(Exception):
    """Boshqa o'qitish allaqachon ketmoqda."""


def _now():
    return datetime.now().isoformat(timespec="seconds")


def create(mode):
    """Yangi job ochadi va id'sini qaytaradi. Band bo'lsa JobAlreadyRunning."""
    doc = {
        "_id": str(ObjectId()),
        "type": mode,                # train | retrain
        "status": "running",
        "stage": "queued",
        "startedAt": _now(),
        "finishedAt": None,
        "stats": {},
        "baselineId": None,
        "error": None,
    }
    try:
        local_db()[config.COL_TRAINING_JOBS].insert_one(doc)
    except DuplicateKeyError:
        raise JobAlreadyRunning()
    log.info("Job ochildi: %s (%s)", doc["_id"], mode)
    return doc["_id"]


def set_stage(job_id, stage, **fields):
    """Bosqichni (va qo'shimcha maydonlarni) yangilaydi."""
    update = {"stage": stage}
    for key, value in fields.items():
        update[key] = value
    local_db()[config.COL_TRAINING_JOBS].update_one({"_id": job_id}, {"$set": update})


def finish(job_id, status, **fields):
    """Job'ni yakunlaydi: status finished | partial | error."""
    update = {"status": status, "stage": status, "finishedAt": _now(), **fields}
    local_db()[config.COL_TRAINING_JOBS].update_one({"_id": job_id}, {"$set": update})
    log.info("Job yakunlandi: %s -> %s", job_id, status)


def latest(mode=None):
    """Eng oxirgi job hujjati (yoki None)."""
    query = {"type": mode} if mode else {}
    return local_db()[config.COL_TRAINING_JOBS].find_one(query, sort=[("startedAt", -1)])


def recent(limit=20):
    """Oxirgi job'lar, yangisi birinchi."""
    return list(local_db()[config.COL_TRAINING_JOBS]
                .find({}).sort("startedAt", -1).limit(limit))


def recover_stale():
    """Dastur ishga tushganda uzilib qolgan job'larni yopadi.

    Protsess job o'rtasida to'xtasa, hujjat `running` holicha qolib, unique
    indeks tufayli keyingi barcha o'qitishlarni bloklab qo'yardi.
    """
    result = local_db()[config.COL_TRAINING_JOBS].update_many(
        {"status": "running"},
        {"$set": {"status": "error", "stage": "error", "finishedAt": _now(),
                  "error": "dastur qayta ishga tushdi, job uzilib qoldi"}})
    if result.modified_count:
        log.warning("%d ta uzilib qolgan job yopildi", result.modified_count)
    return result.modified_count
