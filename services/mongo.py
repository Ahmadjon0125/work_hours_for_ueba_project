"""Ikkita alohida MongoClient: asosiy (faqat o'qish) va mahalliy (o'qish/yozish).

Ajratish ataylab: asosiy bazaga yozma amal kod darajasida imkonsiz bo'lsin.
"""
import time

from pymongo import ASCENDING, MongoClient

import config
from utils.helpers import COLLECTIONS
from utils.logger import get_logger

log = get_logger("mongo")


class SourceReadError(Exception):
    """Asosiy bazadan o'qib bo'lmadi.

    Bo'sh natijadan farqli: bo'sh natija — "bu yerda hech narsa yo'q", bu esa
    "ma'lumot noma'lum". Chaqiruvchi shu client'ni yozmasligi kerak.
    """

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
    from utils.helpers import display_name

    cursor = main_db()["clients"].find(
        {"$or": [{"disabled": False}, {"disabled": {"$exists": False}}]},
        {"_id": 1, "hostname": 1, "fullName": 1, "firstName": 1, "lastName": 1},
    )
    clients = []
    for doc in cursor:
        cid = str(doc["_id"])
        hostname = (doc.get("hostname") or "").strip() or cid
        clients.append({
            "clientId": cid,
            "hostname": hostname,
            "fullName": display_name(hostname, doc.get("fullName"),
                                     doc.get("firstName"), doc.get("lastName")),
            "_id": doc["_id"],
        })
    return clients


def iter_client_timestamps(client, window_start, window_end=None):
    """Bitta client uchun barcha collection'lardan oynadagi timestamp'larni oqim bilan o'qiydi.

    Oyna: `[window_start, window_end)`. `window_end` berilmasa yuqori chegara yo'q
    (trigger shunday ishlatadi — bugungi tugallanmagan kun ham baholanishi kerak).
    Collector esa `window_end` beradi: o'qitishga faqat to'liq kunlar kiradi (COL-01).

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

        bounds = {"$gte": window_start}
        if window_end is not None:
            bounds["$lt"] = window_end

        if len(time_fields) == 1:
            query = {id_field: {"$in": id_values}, time_fields[0]: dict(bounds)}
        else:
            query = {id_field: {"$in": id_values},
                     "$or": [{tf: dict(bounds)} for tf in time_fields]}

        # Qayta urinishlar: tarmoq uzilishlari ko'pincha o'tkinchi bo'ladi.
        # Baribir bo'lmasa xato YUQORIGA UZATILADI — "o'qib bo'lmadi" ni
        # "hech narsa yo'q" deb qabul qilish mumkin emas (COL-04).
        last_error = None
        for attempt in range(config.SOURCE_READ_RETRIES + 1):
            stamps = []  # qisman o'qilgani tashlanadi, yarim natija ishlatilmaydi
            try:
                cursor = db[coll_name].find(query, projection).batch_size(config.BATCH_SIZE)
                for doc in cursor:
                    for tf in time_fields:
                        dt = parse_to_datetime(doc.get(tf))
                        # rdps'da ikkita vaqt maydoni bor — biri oynada bo'lsa
                        # document keladi, shuning uchun har birini alohida tekshiramiz
                        if dt is None or dt < window_start:
                            continue
                        if window_end is not None and dt >= window_end:
                            continue
                        stamps.append(dt)
                break
            except Exception as e:
                last_error = e
                if attempt < config.SOURCE_READ_RETRIES:
                    log.warning("%s | %s o'qishda xato (%d/%d urinish), qayta urinaman: %s",
                                client["clientId"], coll_name, attempt + 1,
                                config.SOURCE_READ_RETRIES, e)
                    time.sleep(config.SOURCE_READ_RETRY_DELAY)
        else:
            raise SourceReadError(
                f"{coll_name} o'qib bo'lmadi ({config.SOURCE_READ_RETRIES + 1} urinish): "
                f"{type(last_error).__name__}: {last_error}") from last_error

        yield coll_name, stamps
