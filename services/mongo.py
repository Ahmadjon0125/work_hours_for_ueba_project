"""Ikkita alohida MongoClient: asosiy (faqat o'qish) va mahalliy (o'qish/yozish).

Ajratish ataylab: asosiy bazaga yozma amal kod darajasida imkonsiz bo'lsin.
"""
from pymongo import ASCENDING, MongoClient

import config
from utils.helpers import COLLECTIONS
from utils.logger import get_logger

log = get_logger("mongo")

_main_client = None
_local_client = None


def main_db():
    """alpha-demo — FAQAT find() uchun."""
    global _main_client
    if _main_client is None:
        _main_client = MongoClient(config.MONGO_URI, serverSelectionTimeoutMS=10000)
    return _main_client[config.DB_NAME]


def local_db():
    """ueba_local — barcha yozuvlar."""
    global _local_client
    if _local_client is None:
        _local_client = MongoClient(config.LOCAL_MONGO_URI, serverSelectionTimeoutMS=10000)
    return _local_client[config.LOCAL_DB_NAME]


def ensure_indexes():
    """4 ta unique indeks — idempotent."""
    db = local_db()
    db[config.COL_RAW_TRAIN].create_index([("clientId", ASCENDING), ("date", ASCENDING)], unique=True)
    db[config.COL_TRIGGER_DATA].create_index([("clientId", ASCENDING), ("date", ASCENDING)], unique=True)
    db[config.COL_BASELINE].create_index([("clientId", ASCENDING)], unique=True)
    db[config.COL_RESULTS].create_index([("clientId", ASCENDING), ("date", ASCENDING)], unique=True)
    log.info("Indekslar tekshirildi (4 ta unique)")


def active_clients():
    """Active client'lar: disabled=false yoki maydon umuman yo'q."""
    cursor = main_db()["clients"].find(
        {"$or": [{"disabled": False}, {"disabled": {"$exists": False}}]},
        {"_id": 1, "hostname": 1},
    )
    clients = []
    for doc in cursor:
        cid = str(doc["_id"])
        hostname = (doc.get("hostname") or "").strip() or cid
        clients.append({"clientId": cid, "hostname": hostname, "_id": doc["_id"]})
    return clients


def iter_client_timestamps(client, window_start):
    """Bitta client uchun 17 collection'dan window_start dan keyingi timestamp'larni oqim bilan o'qiydi.

    Har collection uchun (collection_nomi, [datetime, ...]) qaytaradi.
    O'qish BATCH_SIZE (100) documentlik partiyalarda — limit/paginatsiya emas, streaming cursor.
    """
    from utils.helpers import parse_to_datetime

    db = main_db()
    # ObjectId ham, string ham bo'lishi mumkin — ikkalasini ham qidiramiz
    id_values = [client["_id"], client["clientId"]]

    for coll_name, (id_field, time_fields) in COLLECTIONS.items():
        projection = {"_id": 0, id_field: 1}
        for tf in time_fields:
            projection[tf] = 1

        if len(time_fields) == 1:
            query = {id_field: {"$in": id_values}, time_fields[0]: {"$gte": window_start}}
        else:
            query = {id_field: {"$in": id_values},
                     "$or": [{tf: {"$gte": window_start}} for tf in time_fields]}

        stamps = []
        try:
            cursor = db[coll_name].find(query, projection).batch_size(config.BATCH_SIZE)
            for doc in cursor:
                for tf in time_fields:
                    dt = parse_to_datetime(doc.get(tf))
                    if dt is not None and dt >= window_start:
                        stamps.append(dt)
        except Exception as e:
            log.warning("%s | %s o'qishda xato: %s", client["clientId"], coll_name, e)
            continue

        yield coll_name, stamps
