"""Trainer: raw_data_for_train dan baseline quradi (versiyalab).

Faqat ueba_local bilan ishlaydi — asosiy bazaga bironta ham so'rov yubormaydi.

Har o'qitish run'i yangi `baselineId` oladi va eski versiya o'chirilmaydi
(ARCH-02): natijalarda qaysi baseline ishlatilgani yozilib qoladi, tarixiy
natijalar qayta baholanmaydi.
"""
from collections import defaultdict
from datetime import datetime

from bson import ObjectId

import config
from services.mongo import local_db
from utils.helpers import parse_to_datetime, sample_std, to_minutes
from utils.logger import get_logger

log = get_logger("trainer")


def _week_stats(days):
    """Bir hafta kunining kunlaridan statistika. Namuna kam bo'lsa statlar null."""
    n = len(days)
    if n < config.MIN_DOW_SAMPLES:
        return {"count": n, "meanStart": None, "stdStart": None,
                "meanFinish": None, "stdFinish": None, "meanDuration": None}

    starts = [d["startMin"] for d in days]
    finishes = [d["finishMin"] for d in days]
    durations = [d["durationMin"] for d in days]

    def r(v):
        return None if v is None else round(v, 2)

    return {
        "count": n,
        "meanStart": r(sum(starts) / n),
        "stdStart": r(sample_std(starts)),
        "meanFinish": r(sum(finishes) / n),
        "stdFinish": r(sample_std(finishes)),
        "meanDuration": r(sum(durations) / n),
    }


def train():
    """baseline ni qayta quradi. Qurilgan client'lar sonini qaytaradi."""
    db = local_db()
    now = datetime.now()

    # Har client uchun kunlarni hafta kuni bo'yicha yig'amiz
    per_client = defaultdict(lambda: {"hostname": None, "fullName": None,
                                      "weeks": defaultdict(list), "total": 0})
    for doc in db[config.COL_RAW_TRAIN].find(
            {}, {"_id": 0, "clientId": 1, "hostname": 1, "fullName": 1, "dayOfWeek": 1,
                 "start": 1, "finish": 1, "durationMin": 1}):
        start = parse_to_datetime(doc.get("start"))
        finish = parse_to_datetime(doc.get("finish"))
        if start is None or finish is None:
            continue
        entry = per_client[doc["clientId"]]
        entry["hostname"] = doc.get("hostname") or doc["clientId"]
        entry["fullName"] = doc.get("fullName")
        entry["total"] += 1
        entry["weeks"][doc["dayOfWeek"]].append({
            "startMin": to_minutes(start),
            "finishMin": to_minutes(finish),
            "durationMin": doc.get("durationMin") or 0.0,
        })

    if not per_client:
        log.warning("raw_data_for_train bo'sh — avval collector ishga tushirilsin")
        return 0

    # Yangi versiya: eski baseline o'chirilmaydi, workerlar swap'gacha undan foydalanadi.
    # Id string sifatida saqlanadi — natijalar JSON orqali uzatiladi, ObjectId
    # bo'lsa har joyda konvertatsiya kerak bo'lardi.
    baseline_id = str(ObjectId())
    trained_at = now.isoformat(timespec="seconds")

    docs = []
    for client_id, entry in per_client.items():
        weeks = {wd: _week_stats(days) for wd, days in entry["weeks"].items()}
        kept = sum(w["count"] for w in weeks.values() if w["meanStart"] is not None)
        docs.append({
            "baselineId": baseline_id,
            "clientId": client_id,
            "hostname": entry["hostname"],
            "fullName": entry["fullName"],
            "windowDays": config.DAYS_WINDOW,
            "minDowSamples": config.MIN_DOW_SAMPLES,
            "totalDays": entry["total"],
            "keptDays": kept,
            "trainedAt": trained_at,
            "weeks": weeks,
        })
    db[config.COL_BASELINE].insert_many(docs)

    total_days = sum(e["total"] for e in per_client.values())
    runs = db[config.COL_BASELINE_RUNS]
    runs.insert_one({
        "_id": baseline_id,
        "trainedAt": trained_at,
        "windowDays": config.DAYS_WINDOW,
        "minDowSamples": config.MIN_DOW_SAMPLES,
        "clientCount": len(docs),
        "dayCount": total_days,
        "current": True,
    })
    # Avval yangisi joriy qilinadi, keyin eskilari olib tashlanadi — shu tartibda
    # "joriy versiya yo'q" holati umuman bo'lmaydi (o'quvchi eng yangisini oladi).
    runs.update_many({"_id": {"$ne": baseline_id}, "current": True},
                     {"$set": {"current": False}})

    _prune_old_versions(db, baseline_id)

    log.info("Trainer tugadi: %d client, %d kun o'qitildi, yangi baseline versiyasi %s (%s)",
             len(docs), total_days, baseline_id, now.strftime("%Y-%m-%d %H:%M:%S"))
    return len(docs)


def _prune_old_versions(db, keep_current):
    """Eski baseline versiyalarini o'chiradi (oxirgi BASELINE_KEEP_VERSIONS qoladi)."""
    runs = db[config.COL_BASELINE_RUNS]
    baseline = db[config.COL_BASELINE]

    old = list(runs.find({}, {"_id": 1}).sort("trainedAt", -1)
               .skip(config.BASELINE_KEEP_VERSIONS))
    stale = [r["_id"] for r in old if r["_id"] != keep_current]
    if stale:
        baseline.delete_many({"baselineId": {"$in": stale}})
        runs.delete_many({"_id": {"$in": stale}})
        log.info("%d ta eski baseline versiyasi o'chirildi", len(stale))

    # Egasiz hujjatlar: versiyasiz (versiyalashdan oldingi) yoki ro'yxatdan
    # tushib qolgan versiyaga tegishli. Ular hech qachon ishlatilmaydi.
    known = [r["_id"] for r in runs.find({}, {"_id": 1})]
    orphans = baseline.delete_many(
        {"$or": [{"baselineId": {"$exists": False}},
                 {"baselineId": {"$nin": known}}]}).deleted_count
    if orphans:
        log.info("%d ta egasiz baseline hujjati o'chirildi", orphans)


def current_baseline_id(db=None):
    """Joriy (eng yangi) baseline versiyasining id'si. Baseline yo'q bo'lsa None."""
    # `db or local_db()` YOZIB BO'LMAYDI: pymongo Database obyekti bool() ni
    # qo'llab-quvvatlamaydi va NotImplementedError ko'taradi.
    if db is None:
        db = local_db()
    run = db[config.COL_BASELINE_RUNS].find_one({"current": True}, sort=[("trainedAt", -1)])
    return run["_id"] if run else None
