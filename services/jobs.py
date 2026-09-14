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
from utils.helpers import now as hozir
from utils.logger import get_logger

log = get_logger("jobs")


class JobAlreadyRunning(Exception):
    """Boshqa o'qitish allaqachon ketmoqda."""


def _now():
    return hozir().isoformat(timespec="seconds")


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
        # Bosqich ichidagi jarayon: 0..100 va odam o'qiydigan matn
        "progress": 0,
        "progressText": "Navbatda",
        # Har bosqichning o'z foizi: dashboard ikkita alohida chiziq chizadi
        "stageProgress": {},
        # Bosqichlar davomida to'plangan xatolar (client darajasidagilar ham)
        "errors": [],
        "error": None,
    }
    try:
        local_db()[config.COL_TRAINING_JOBS].insert_one(doc)
    except DuplicateKeyError:
        raise JobAlreadyRunning()
    log.info("Job ochildi: %s (%s)", doc["_id"], mode)
    return doc["_id"]


def set_progress(job_id, percent, text=None, stage=None):
    """Bosqich ichidagi jarayonni yangilaydi (0..100).

    Tez-tez chaqiriladi (har client uchun), shuning uchun faqat kerakli
    maydonlarni yozadi — butun hujjat qayta yozilmaydi.

    `stage` berilsa foiz `stageProgress.<stage>` ga ham yoziladi. Dashboard
    har bosqich uchun ALOHIDA chiziq chizadi, shuning uchun collector va
    trainer foizlari bir-birining ustiga yozilmasligi kerak: bitta umumiy
    `progress` bilan ikkinchi bosqich birinchisining natijasini o'chirardi.
    """
    p = max(0, min(100, int(percent)))
    update = {"progress": p}
    if text is not None:
        update["progressText"] = text
    if stage:
        update[f"stageProgress.{stage}.percent"] = p
        update[f"stageProgress.{stage}.status"] = "running"
        if text is not None:
            update[f"stageProgress.{stage}.text"] = text
    local_db()[config.COL_TRAINING_JOBS].update_one({"_id": job_id}, {"$set": update})


def finish_stage(job_id, stage, status="done", text=None):
    """Bosqichni yakunlaydi: `done` bo'lsa foizi 100 ga to'ldiriladi.

    Xodim topilmasa collector bironta `on_progress` chaqirmaydi va chiziq
    0% da qotib qolardi — shuning uchun yakun alohida belgilanadi.
    """
    update = {f"stageProgress.{stage}.status": status}
    if status == "done":
        update[f"stageProgress.{stage}.percent"] = 100
    if text is not None:
        update[f"stageProgress.{stage}.text"] = text
    local_db()[config.COL_TRAINING_JOBS].update_one({"_id": job_id}, {"$set": update})


def add_error(job_id, xato, kontekst=None):
    """Job davomida yuz bergan xatoni ro'yxatga qo'shadi (jarayon to'xtamaydi).

    Butun job yiqilmasa ham xodim darajasidagi xatolar shu yerda qoladi va
    keyin dashboardda ko'rinadi.
    """
    yozuv = {"at": _now(), "error": str(xato)[:400]}
    # Istisno turini alohida saqlaymiz: matndan ajratib olishdan ko'ra
    # ishonchli, va xatoni tasniflashda aynan shu ishlatiladi.
    if isinstance(xato, BaseException):
        yozuv["kod"] = type(xato).__name__
    if kontekst:
        yozuv["context"] = kontekst
    local_db()[config.COL_TRAINING_JOBS].update_one(
        {"_id": job_id}, {"$push": {"errors": {"$each": [yozuv], "$slice": -50}}})


def set_stage(job_id, stage, **fields):
    """Bosqichni (va qo'shimcha maydonlarni) yangilaydi.

    Yangi bosqich o'z chizig'ini 0 dan boshlaydi — oldingi bosqichning
    `stageProgress` yozuvi tegilmaydi, u ekranda «bajarildi» bo'lib qoladi.
    """
    update = {"stage": stage, "progress": 0,
              f"stageProgress.{stage}.percent": 0,
              f"stageProgress.{stage}.status": "running"}
    for key, value in fields.items():
        update[key] = value
    if "progressText" in fields:
        update[f"stageProgress.{stage}.text"] = fields["progressText"]
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


# ---------------------------------------------------------------------------
# Trigger o'tishlari
#
# Ilgari holat API protsessining xotirasida (`_state` dict) turardi: dastur
# qayta ishga tushsa yo'qolardi va tunda bo'lgan xato ertalab bilinmasdi.
# Endi har o'tish `trigger_runs` da hujjat — tarix qoladi.
# ---------------------------------------------------------------------------

def trigger_start():
    """Yangi trigger o'tishini ochadi, id qaytaradi."""
    doc = {"_id": str(ObjectId()), "status": "running", "startedAt": _now(),
           "finishedAt": None, "sent": 0, "skipped": 0, "clients": 0,
           "events": 0, "error": None}
    local_db()[config.COL_TRIGGER_RUNS].insert_one(doc)
    return doc["_id"]


def trigger_finish(run_id, status, **fields):
    """O'tishni yopadi va eski yozuvlarni tozalaydi."""
    local_db()[config.COL_TRIGGER_RUNS].update_one(
        {"_id": run_id},
        {"$set": {"status": status, "finishedAt": _now(), **fields}})
    _prune_trigger_runs()


def _prune_trigger_runs():
    """Oxirgi TRIGGER_KEEP_RUNS o'tishini qoldiradi."""
    col = local_db()[config.COL_TRIGGER_RUNS]
    eskilar = list(col.find({}, {"_id": 1}).sort("startedAt", -1)
                   .skip(config.TRIGGER_KEEP_RUNS))
    if eskilar:
        col.delete_many({"_id": {"$in": [d["_id"] for d in eskilar]}})


def trigger_latest():
    """Oxirgi o'tish, yoki hech qachon ishlamagan bo'lsa {'status': 'idle'}."""
    doc = local_db()[config.COL_TRIGGER_RUNS].find_one({}, sort=[("startedAt", -1)])
    return doc or {"status": "idle"}


def trigger_recent(limit=20):
    return list(local_db()[config.COL_TRIGGER_RUNS]
                .find({}).sort("startedAt", -1).limit(limit))


def trigger_recover_stale():
    """Uzilib qolgan o'tishlarni yopadi (dastur qayta ishga tushganda)."""
    result = local_db()[config.COL_TRIGGER_RUNS].update_many(
        {"status": "running"},
        {"$set": {"status": "error", "finishedAt": _now(),
                  "error": "dastur qayta ishga tushdi, o'tish uzilib qoldi"}})
    if result.modified_count:
        log.warning("%d ta uzilib qolgan trigger o'tishi yopildi", result.modified_count)
    return result.modified_count
