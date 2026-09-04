"""Collector: alpha-demo dan 60 kunlik tarixni yig'ib raw_data_for_train ga yozadi.

Faqat train/retrain paytida ishlaydi (CLI yoki /api/train, /api/retrain zanjiri).
"""
from collections import defaultdict
from datetime import datetime, timedelta

import config
from services.mongo import active_clients, ensure_indexes, iter_client_timestamps, local_db
from utils.helpers import build_day_agg, build_day_doc, date_str_days_ago, day_of_week
from utils.logger import get_logger

log = get_logger("collector")


def _log_weekday_report(client_id, coll_name, stamps):
    """Tekshiruv uchun: har hafta kuni bo'yicha birinchi/oxirgi document va soni."""
    by_weekday = defaultdict(list)
    for ts in stamps:
        by_weekday[day_of_week(ts)].append(ts)
    for weekday, tss in by_weekday.items():
        log.info("%s | %-14s | %-9s | firstDoc=%s | lastDoc=%s | docs=%d",
                 client_id, coll_name, weekday,
                 min(tss).strftime("%Y-%m-%d %H:%M:%S"),
                 max(tss).strftime("%Y-%m-%d %H:%M:%S"), len(tss))


def collect():
    """60 kunlik tarixni yig'ib raw_data_for_train ni to'ldiradi. Yozilgan kunlar sonini qaytaradi."""
    ensure_indexes()
    now = datetime.now()
    window_start = now - timedelta(days=config.DAYS_WINDOW)
    db = local_db()
    raw = db[config.COL_RAW_TRAIN]

    clients = active_clients()
    if not clients:
        log.warning("Active client topilmadi — collector bo'sh tugadi")
        return 0

    log.info("Collector boshlandi: %d active client, oyna %s dan",
             len(clients), window_start.strftime("%Y-%m-%d"))

    total_days = 0
    for client in clients:
        cid, hostname = client["clientId"], client["hostname"]
        full_name = client.get("fullName")
        try:
            day_stamps = defaultdict(list)
            for coll_name, stamps in iter_client_timestamps(client, window_start):
                if not stamps:
                    continue
                _log_weekday_report(cid, coll_name, stamps)
                for ts in stamps:
                    day_stamps[ts.strftime("%Y-%m-%d")].append(ts)

            for date_str, tss in day_stamps.items():
                agg = build_day_agg(tss)
                if agg is None:
                    continue
                start, finish = agg
                doc = build_day_doc(cid, hostname, date_str, start, finish, len(tss), now,
                                    full_name=full_name)
                raw.update_one({"clientId": cid, "date": date_str}, {"$set": doc}, upsert=True)
                total_days += 1

            # Pruning: oynadan tashqaridagi eski kunlar
            raw.delete_many({"clientId": cid,
                             "date": {"$lt": date_str_days_ago(now, config.DAYS_WINDOW)}})
            log.info("%s (%s): %d kun yozildi", cid, hostname, len(day_stamps))
        except Exception as e:
            log.error("%s client'ida xato (qolganlari davom etadi): %s", cid, e)

    log.info("Collector tugadi: %d client, %d kun yozildi", len(clients), total_days)
    return total_days
