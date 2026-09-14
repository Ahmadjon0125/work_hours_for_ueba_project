"""Ikkita alohida MongoClient: asosiy (faqat o'qish) va mahalliy (o'qish/yozish).

Ajratish ataylab: asosiy bazaga yozma amal kod darajasida imkonsiz bo'lsin.
"""
import time
from datetime import datetime

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


def _group_names():
    """`groups` collectionidan {id: nom} xaritasi. Xatoda bo'sh xarita qaytadi.

    Xodim jadvalida ism ostida bo'lim ko'rsatiladi. Guruh nomi bo'lmasa jadval
    baribir chizilishi kerak, shuning uchun bu qidiruv hech qachon chaqiruvchini
    yiqitmaydi.
    """
    try:
        return {str(g["_id"]): (g.get("name") or "").strip()
                for g in main_db()["groups"].find({}, {"name": 1})}
    except Exception as e:
        log.warning("Guruh nomlarini o'qib bo'lmadi: %s", e)
        return {}


def active_clients():
    """Active client'lar: disabled=false yoki maydon umuman yo'q."""
    from utils.helpers import display_name

    guruhlar = _group_names()
    cursor = main_db()["clients"].find(
        {"$or": [{"disabled": False}, {"disabled": {"$exists": False}}]},
        {"_id": 1, "hostname": 1, "fullName": 1, "firstName": 1, "lastName": 1,
         "group": 1, "department": 1, "position": 1},
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
            # Ism ostidagi kichik yozuv: lavozim yoki bo'lim, bo'lmasa guruh nomi
            "unit": ((doc.get("position") or "").strip()
                     or (doc.get("department") or "").strip()
                     or guruhlar.get(str(doc.get("group")), "")),
            "_id": doc["_id"],
        })
    return clients


# `.env` dagi SESSION_COLLECTION bilan o'zgartiriladi
SESSION_COLLECTION = config.SESSION_COLLECTION


def iter_client_sessions(client, window_start, window_end=None):
    """Agent sessiyalari: (collection_nomi, [sessiya, ...]).

    Har sessiya — DLP dagi bitta hujjat: bitta (xodim, kompyuter, kun) uchun
    agent qachon serverga ulangan va qachon uzilgan.

        {"date": "2026-09-08", "connect": datetime, "disconnect": datetime|None,
         "reason": "ping timeout"|None}

    Kun DLP ning o'z maydonidan (`dateStr`) olinadi — `connect` dan hisoblab
    chiqarilmaydi. Sessiya yarim tundan o'tsa, u qaysi kunga tegishli ekanini
    manba tizimning o'zi hal qilgan.

    `disconnect` bo'sh bo'lishi mumkin: sessiya hali tugamagan yoki ertangi
    kunga o'tib ketgan. Bunday yozuv tashlanmaydi — `workday.py` uni kun
    boshlanishi uchun ishlatadi, tugashi uchun esa ishlatmaydi.

    Xato yuqoriga uzatiladi — "o'qib bo'lmadi" ni "hech narsa yo'q" deb qabul
    qilish mumkin emas (COL-04 bilan bir xil qoida).
    """
    db = main_db()
    # ObjectId ham, string ham bo'lishi mumkin — ikkalasini ham qidiramiz
    id_values = [client["_id"], client["clientId"]]

    con_f, dis_f = config.SESSION_CONNECT_FIELD, config.SESSION_DISCONNECT_FIELD
    date_f, reason_f = config.SESSION_DATE_FIELD, config.SESSION_REASON_FIELD

    bounds = {"$gte": window_start}
    if window_end is not None:
        bounds["$lt"] = window_end
    query = {"clientId": {"$in": id_values}, con_f: bounds}

    last_error = None
    for attempt in range(config.SOURCE_READ_RETRIES + 1):
        sessions = []
        try:
            cursor = (db[SESSION_COLLECTION]
                      .find(query, {"_id": 0, con_f: 1, dis_f: 1,
                                    date_f: 1, reason_f: 1})
                      .batch_size(config.BATCH_SIZE))
            for doc in cursor:
                con = parse_to_datetime(doc.get(con_f))
                if con is None or con < window_start:
                    continue
                if window_end is not None and con >= window_end:
                    continue
                dis = parse_to_datetime(doc.get(dis_f))
                # Nomuvofiq yozuv: uzilish ulanishdan oldin. Kunni buzmasin.
                if dis is not None and dis < con:
                    log.warning("%s | %s: %s < %s, uzilish e'tiborsiz qoldirildi",
                                client["clientId"], SESSION_COLLECTION, dis_f, con_f)
                    dis = None
                sessions.append({
                    "date": _session_date(doc.get(date_f), con),
                    "connect": con,
                    "disconnect": dis,
                    "reason": doc.get(reason_f),
                })
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

    yield SESSION_COLLECTION, sessions


def _session_date(xom, connect):
    """DLP ning kun maydonini "YYYY-MM-DD" ga o'giradi.

    Maydon yo'q yoki tanib bo'lmasa — `connect` ning kuniga qaytamiz, chunki
    kunsiz yozuv butunlay yaroqsiz bo'lib qolardi.
    """
    if isinstance(xom, str) and xom.strip():
        try:
            return datetime.strptime(xom.strip(), config.SESSION_DATE_FORMAT).strftime("%Y-%m-%d")
        except ValueError:
            log.warning("%s: '%s' sanasini %s formatida o'qib bo'lmadi",
                        SESSION_COLLECTION, xom, config.SESSION_DATE_FORMAT)
    xom_dt = parse_to_datetime(xom)
    if xom_dt is not None:
        return xom_dt.strftime("%Y-%m-%d")
    return connect.strftime("%Y-%m-%d")
