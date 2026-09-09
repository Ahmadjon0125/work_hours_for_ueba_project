"""Barcha sozlamalar shu yerda o'qiladi (.env > default)."""
import os
import re

from dotenv import load_dotenv

load_dotenv()

# --- Asosiy MongoDB (alpha-demo) — FAQAT O'QISH ---
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "alpha-demo")

# --- Mahalliy MongoDB — barcha yozuvlar ---
LOCAL_MONGO_URI = os.getenv("LOCAL_MONGO_URI", "mongodb://localhost:27017")
LOCAL_DB_NAME = os.getenv("LOCAL_DB_NAME", "ueba_local")

# --- RabbitMQ ---
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", 5672))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASSWORD = os.getenv("RABBITMQ_PASSWORD", "guest")
QUEUE_NAME = os.getenv("QUEUE_NAME", "ueba_jobs")
WORKER_COUNT = int(os.getenv("WORKER_COUNT", 3))
# Job xato bersa necha marta qayta urinish (mq/worker.py)
MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))

# --- API ---
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", 8000))

# --- Pipeline ---
DAYS_WINDOW = int(os.getenv("DAYS_WINDOW", 90))
TRIGGER_INTERVAL_HOURS = float(os.getenv("TRIGGER_INTERVAL_HOURS", 5))
LOOKBACK_HOURS = float(os.getenv("LOOKBACK_HOURS", 5))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 100))
# Manbadan o'qishda necha marta qayta urinish (o'tkinchi tarmoq uzilishlari uchun)
SOURCE_READ_RETRIES = int(os.getenv("SOURCE_READ_RETRIES", 2))
SOURCE_READ_RETRY_DELAY = float(os.getenv("SOURCE_READ_RETRY_DELAY", 2))
SINGLE_EVENT_STAY_HOURS = float(os.getenv("SINGLE_EVENT_STAY_HOURS", 1))
RESULTS_RETENTION_DAYS = int(os.getenv("RESULTS_RETENTION_DAYS", 365))

# --- Ish kuni manbasi ---
# Agent hozirlik qaydlari saqlanadigan collection (asosiy bazada).
SESSION_COLLECTION = os.getenv("SESSION_COLLECTION", "agentsessionstatuses")


def _statuslar(kalit, default):
    """Vergul bilan ajratilgan status ro'yxatini o'qiydi."""
    xom = os.getenv(kalit, default)
    return tuple(x.strip().upper() for x in xom.split(",") if x.strip())


# Qaysi status ish boshlanishi, qaysisi tugashi. Agent yangi status qo'shsa
# yoki nomlarini o'zgartirsa — bu yerda emas, `.env` da tuzatiladi.
SESSION_START_STATUSES = _statuslar("SESSION_START_STATUSES",
                                    "LOGON,UNLOCK,REMOTE_CONNECT")
SESSION_END_STATUSES = _statuslar("SESSION_END_STATUSES",
                                  "LOGOFF,LOCK,REMOTE_DISCONNECT")

# --- Anomaliya chegarasi ---
MIN_DOW_SAMPLES = int(os.getenv("MIN_DOW_SAMPLES", 3))
# |z| shu chegaradan oshsa — anomaliya. Eski 4 pog'onali sxema (watch/anomaly/
# severe) bekor qilindi: bitta chegara + 0-100 ball tushunarliroq va sozlash
# osonroq. Chegara ball shkalasida aynan 50 ga to'g'ri keladi (detectors/scoring).
ANOMALY_Z_THRESHOLD = float(os.getenv("ANOMALY_Z_THRESHOLD", 1.0))
if ANOMALY_Z_THRESHOLD <= 0:
    # 0 yoki manfiy bo'lsa ball formulasida nolga bo'linish bo'lardi
    ANOMALY_Z_THRESHOLD = 1.0

# Chetlanish darajasi z-score bilan o'lchanadi: zOut shu qiymatga yetganda ball
# 100 bo'ladi. Chegara (ANOMALY_Z_THRESHOLD) da ball minimal, bu yerda maksimal.
# Bundan oshig'i ham 100 bo'lib qolaveradi — xom qiymatlar
# `detectors.workingHours.details` da (zOut, outsideMin) saqlanadi.
ANOMALY_Z_FULL_SCALE = float(os.getenv("ANOMALY_Z_FULL_SCALE", 3.0))
if ANOMALY_Z_FULL_SCALE <= ANOMALY_Z_THRESHOLD:
    ANOMALY_Z_FULL_SCALE = ANOMALY_Z_THRESHOLD + 2.0

# Detector nomidan .env kalitini quradi: workingHours -> WORKING_HOURS
_CAMEL_SPLIT = re.compile(r"(?<!^)(?=[A-Z])")


def detector_weight(name, default=1.0):
    """Detector vazni: DETECTOR_WEIGHT_<UPPER_SNAKE> bo'lsa o'sha, aks holda default.

    Vaznni o'zgartirish uchun kodga tegilmaydi:
        DETECTOR_WEIGHT_WORKING_HOURS=0.4

    Qiymat [0, 1] oralig'iga siqiladi — riskScore formulasi (noisy-OR) faqat shu
    oraliqda ma'noli. Vazn 0 = "soya rejim": detector ishlaydi va natijaga
    yoziladi, lekin umumiy riskka ta'sir qilmaydi (yangi detectorni jonli
    ma'lumotda sinash uchun).
    """
    key = "DETECTOR_WEIGHT_" + _CAMEL_SPLIT.sub("_", name).upper()
    raw = os.getenv(key)
    weight = default
    if raw is not None:
        try:
            weight = float(raw)
        except ValueError:
            # Kechiktirilgan import: config hech qanday loyiha moduliga bog'liq bo'lmasin
            from utils.logger import get_logger
            get_logger("config").warning(
                "%s qiymati son emas (%r) — default %s ishlatildi", key, raw, default)
    return min(1.0, max(0.0, weight))


# --- Xavf jadvali (kuzatuvdagi xodimlar) ---
# "Recent risk" ustuni necha kunlik yig'indi. Bitta kun juda beqaror
# bo'lgani uchun default 7 — hafta davomidagi manzarani ko'rsatadi.
RISK_RECENT_DAYS = int(os.getenv("RISK_RECENT_DAYS", 7))
# Sparkline'da nechta nuqta chiziladi (oxirgi shuncha kun)
RISK_TREND_POINTS = int(os.getenv("RISK_TREND_POINTS", 30))
# Recent risk shu chegaralardan oshsa xodim belgisi rangi o'zgaradi
RISK_LEVEL_HIGH = int(os.getenv("RISK_LEVEL_HIGH", 50))     # qizil uchburchak
RISK_LEVEL_MEDIUM = int(os.getenv("RISK_LEVEL_MEDIUM", 20))  # sariq kvadrat

# --- Daraja yorliqlari (dashboard uchun) ---
# 0-100 ballik shkalani odam tiliga o'giradigan chegaralar.
SEVERITY_HIGH = int(os.getenv("SEVERITY_HIGH", 75))       # bundan yuqori: "juda yuqori"
SEVERITY_MEDIUM = int(os.getenv("SEVERITY_MEDIUM", 50))   # "yuqori"
SEVERITY_LOW = int(os.getenv("SEVERITY_LOW", 25))         # "o'rtacha"; pastrog'i "past"

# --- Dashboard va API ---
# Dashboard ochilganda ko'rsatiladigan sana oralig'i (kun)
DASHBOARD_RANGE_DAYS = int(os.getenv("DASHBOARD_RANGE_DAYS", 30))
# "E'tibor talab qiladigan kunlar" ro'yxatida nechta karta
DASHBOARD_MAX_ISSUES = int(os.getenv("DASHBOARD_MAX_ISSUES", 20))
# /api/results sahifasi: default va eng katta ruxsat etilgan hajm
API_PAGE_SIZE = int(os.getenv("API_PAGE_SIZE", 100))
API_PAGE_MAX = int(os.getenv("API_PAGE_MAX", 5000))
# Bir martalik skriptlar bir partiyada nechta hujjat yozadi
BULK_BATCH_SIZE = int(os.getenv("BULK_BATCH_SIZE", 500))

# --- Collection nomlari (mahalliy DB) ---
COL_RAW_TRAIN = os.getenv("COL_RAW_TRAIN", "raw_data_for_train")
COL_TRIGGER_DATA = os.getenv("COL_TRIGGER_DATA", "trigger_data")
COL_BASELINE = os.getenv("COL_BASELINE", "baseline")
COL_BASELINE_RUNS = os.getenv("COL_BASELINE_RUNS", "baseline_runs")
COL_RESULTS = os.getenv("COL_RESULTS", "results")
COL_TRAINING_JOBS = os.getenv("COL_TRAINING_JOBS", "training_jobs")

# Nechta baseline versiyasi saqlanadi (eskilari o'chiriladi)
BASELINE_KEEP_VERSIONS = int(os.getenv("BASELINE_KEEP_VERSIONS", 5))
