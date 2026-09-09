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
MAX_RETRIES = 3

# --- API ---
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", 8000))

# --- Pipeline ---
DAYS_WINDOW = int(os.getenv("DAYS_WINDOW", 60))
TRIGGER_INTERVAL_HOURS = float(os.getenv("TRIGGER_INTERVAL_HOURS", 5))
LOOKBACK_HOURS = float(os.getenv("LOOKBACK_HOURS", 5))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", 100))
# Manbadan o'qishda necha marta qayta urinish (o'tkinchi tarmoq uzilishlari uchun)
SOURCE_READ_RETRIES = int(os.getenv("SOURCE_READ_RETRIES", 2))
SOURCE_READ_RETRY_DELAY = float(os.getenv("SOURCE_READ_RETRY_DELAY", 2))
SINGLE_EVENT_STAY_HOURS = float(os.getenv("SINGLE_EVENT_STAY_HOURS", 1))
RESULTS_RETENTION_DAYS = int(os.getenv("RESULTS_RETENTION_DAYS", 365))

# --- Ish kuni manbasi ---
# activity : 16 ta faollik collection'idan xulosa chiqariladi (eski usul)
# session  : `agentsessionstatuses` dagi LOGON/UNLOCK/LOCK/LOGOFF hodisalari —
#            agentning haqiqiy hozirlik qaydlari. Ancha arzon va aniqroq, lekin
#            agent hodisalarni to'liq yuborayotgan bo'lishi shart.
# DIQQAT: ikkala manba tizimli farq qiladi (session qisqaroq kun beradi).
# Manbani almashtirgandan keyin baseline QAYTA O'QITILISHI shart, aks holda
# yangi kunlar eski manbadagi normaga solishtiriladi.
WORKDAY_SOURCE = os.getenv("WORKDAY_SOURCE", "activity").strip().lower()
if WORKDAY_SOURCE not in ("activity", "session"):
    WORKDAY_SOURCE = "activity"

# --- Anomaliya chegarasi ---
MIN_DOW_SAMPLES = int(os.getenv("MIN_DOW_SAMPLES", 5))
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


# --- Collection nomlari (mahalliy DB) ---
COL_RAW_TRAIN = "raw_data_for_train"
COL_TRIGGER_DATA = "trigger_data"
COL_BASELINE = "baseline"
COL_BASELINE_RUNS = "baseline_runs"
COL_RESULTS = "results"
COL_TRAINING_JOBS = "training_jobs"

# Nechta baseline versiyasi saqlanadi (eskilari o'chiriladi)
BASELINE_KEEP_VERSIONS = int(os.getenv("BASELINE_KEEP_VERSIONS", 5))
