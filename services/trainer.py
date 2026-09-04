"""Trainer: raw_data_for_train dan baseline quradi (tmp + atomik swap).

Faqat ueba_local bilan ishlaydi — asosiy bazaga bironta ham so'rov yubormaydi.
"""
from collections import defaultdict
from datetime import datetime

from pymongo import ASCENDING

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

    # Yangi baseline'ni vaqtinchalik collection'da quramiz
    tmp = db[config.COL_BASELINE_TMP]
    tmp.drop()
    tmp.create_index([("clientId", ASCENDING)], unique=True)

    docs = []
    for client_id, entry in per_client.items():
        weeks = {wd: _week_stats(days) for wd, days in entry["weeks"].items()}
        kept = sum(w["count"] for w in weeks.values() if w["meanStart"] is not None)
        docs.append({
            "clientId": client_id,
            "hostname": entry["hostname"],
            "fullName": entry["fullName"],
            "windowDays": config.DAYS_WINDOW,
            "minDowSamples": config.MIN_DOW_SAMPLES,
            "totalDays": entry["total"],
            "keptDays": kept,
            "trainedAt": now.isoformat(timespec="seconds"),
            "weeks": weeks,
        })
    tmp.insert_many(docs)

    # Atomik swap: shu paytgacha eski baseline joyida turadi, workerlar undan foydalanadi
    tmp.rename(config.COL_BASELINE, dropTarget=True)

    total_days = sum(e["total"] for e in per_client.values())
    log.info("Trainer tugadi: %d client, %d kun o'qitildi, baseline almashtirildi (%s)",
             len(docs), total_days, now.strftime("%Y-%m-%d %H:%M:%S"))
    return len(docs)
