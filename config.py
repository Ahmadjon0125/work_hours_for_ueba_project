"""Barcha sozlamalar shu yerda o'qiladi (.env > default)."""
import os

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
SINGLE_EVENT_STAY_HOURS = float(os.getenv("SINGLE_EVENT_STAY_HOURS", 1))
RESULTS_RETENTION_DAYS = int(os.getenv("RESULTS_RETENTION_DAYS", 365))

# --- Z-score chegaralari ---
MIN_DOW_SAMPLES = int(os.getenv("MIN_DOW_SAMPLES", 5))
WATCH_THRESHOLD = float(os.getenv("WATCH_THRESHOLD", 0.5))
Z_THRESHOLD = float(os.getenv("Z_THRESHOLD", 1.2))
SEVERE_THRESHOLD = float(os.getenv("SEVERE_THRESHOLD", 1.8))

# --- Collection nomlari (mahalliy DB) ---
COL_RAW_TRAIN = "raw_data_for_train"
COL_TRIGGER_DATA = "trigger_data"
COL_BASELINE = "baseline"
COL_BASELINE_TMP = "baseline_tmp"
COL_RESULTS = "results"
