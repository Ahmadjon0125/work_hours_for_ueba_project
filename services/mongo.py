"""Ikkita alohida MongoClient: asosiy (faqat o'qish) va mahalliy (o'qish/yozish).

Ajratish ataylab: asosiy bazaga yozma amal kod darajasida imkonsiz bo'lsin.
"""
import time

from pymongo import ASCENDING, MongoClient

import config
from utils.helpers import parse_to_datetime
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
    """Indekslar — idempotent."""
    db = local_db()
    db[config.COL_RAW_TRAIN].create_index([("clientId", ASCENDING), ("date", ASCENDING)], unique=True)
    db[config.COL_TRIGGER_DATA].create_index([("clientId", ASCENDING), ("date", ASCENDING)], unique=True)
    db[config.COL_RESULTS].create_index([("clientId", ASCENDING), ("date", ASCENDING)], unique=True)

    # Baseline endi versiyalanadi: bitta client uchun bir nechta versiya bo'ladi,
    # shuning uchun eski `{clientId}` unique indeksi to'g'ri kelmaydi (ARCH-02).
    baseline = db[config.COL_BASELINE]
    try:
        for name, spec in baseline.index_information().items():
            if spec.get("key") == [("clientId", 1)] and spec.get("unique"):
                baseline.drop_index(name)
                log.info("Eski baseline indeksi (%s) olib tashlandi — versiyalash yoqildi", name)
    except Exception as e:
        log.warning("Baseline indekslarini tekshirib bo'lmadi: %s", e)

    baseline.create_index([("clientId", ASCENDING), ("baselineId", ASCENDING)], unique=True)
    baseline.create_index([("baselineId", ASCENDING)])
    db[config.COL_BASELINE_RUNS].create_index([("trainedAt", -1)])

    # Bir vaqtda faqat BITTA o'qitish ketishi kerak (ARCH-01). Buni unique
    # partial indeks kafolatlaydi: `status: "running"` hujjat faqat bitta
    # bo'la oladi. threading.Lock dan farqli — ko'p protsessda ham ishlaydi.
    jobs = db[config.COL_TRAINING_JOBS]
    jobs.create_index([("status", ASCENDING)], unique=True,
                      partialFilterExpression={"status": "running"},
                      name="one_running_job")
    jobs.create_index([("startedAt", -1)])

    # Dashboard va API eng ko'p so'raydigan kesimlar (unique emas — tezlik uchun).
    results = db[config.COL_RESULTS]
    results.create_index([("isAnomaly", ASCENDING), ("date", -1)])
    # Multikey: `triggeredDetectors` massiv, shuning uchun bitta indeks barcha
    # detectorlar bo'yicha filtrni qoplaydi.
    results.create_index([("triggeredDetectors", ASCENDING)])
    log.info("Indekslar tekshirildi (4 ta unique + 2 ta qidiruv)")


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


# `.env` dagi SESSION_COLLECTION bilan o'zgartiriladi
SESSION_COLLECTION = config.SESSION_COLLECTION


def iter_client_sessions(client, window_start, window_end=None):
    """Agent hozirlik hodisalari: (collection_nomi, [(datetime, status), ...]).

    `services/workday.py` undan kun boshi/oxiri va sof ish daqiqalarini
    hisoblaydi.

    Xato yuqoriga uzatiladi — "o'qib bo'lmadi" ni "hech narsa yo'q" deb qabul
    qilish mumkin emas (COL-04 bilan bir xil qoida).
    """
    db = main_db()
    # ObjectId ham, string ham bo'lishi mumkin — ikkalasini ham qidiramiz
    id_values = [client["_id"], client["clientId"]]

    bounds = {"$gte": window_start}
    if window_end is not None:
        bounds["$lt"] = window_end
    query = {"clientId": {"$in": id_values}, "dateTime": bounds}

    last_error = None
    for attempt in range(config.SOURCE_READ_RETRIES + 1):
        events = []
        try:
            cursor = (db[SESSION_COLLECTION]
                      .find(query, {"_id": 0, "dateTime": 1, "status": 1})
                      .batch_size(config.BATCH_SIZE))
            for doc in cursor:
                dt = parse_to_datetime(doc.get("dateTime"))
                if dt is None or dt < window_start:
                    continue
                if window_end is not None and dt >= window_end:
                    continue
                events.append((dt, doc.get("status") or ""))
            break
        except Exception as e:
            last_error = e
            if attempt < config.SOURCE_READ_RETRIES:
                log.warning("%s | %s o'qishda xato (%d/%d urinish), qayta urinaman: %s",
                            client["clientId"], SESSION_COLLECTION, attempt + 1,
                            config.SOURCE_READ_RETRIES, e)
                time.sleep(config.SOURCE_READ_RETRY_DELAY)
    else:
        raise SourceReadError(
            f"{SESSION_COLLECTION} o'qib bo'lmadi ({config.SOURCE_READ_RETRIES + 1} urinish): "
            f"{type(last_error).__name__}: {last_error}") from last_error

    yield SESSION_COLLECTION, events
