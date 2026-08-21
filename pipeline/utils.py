# Yordamchi funksiyalar va umumiy sozlamalar
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# Config
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "ueba_db")
DAYS_WINDOW = int(os.getenv("DAYS_WINDOW", 60))
Z_THRESHOLD = float(os.getenv("Z_THRESHOLD", 1.2))
MIN_DOW_SAMPLES = int(os.getenv("MIN_DOW_SAMPLES", 2))

# Fayl yo'llari
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_FILE = DATA_DIR / "raw_data.json"
RESULTS_FILE = DATA_DIR / "results.json"
BASELINES_FILE = DATA_DIR / "baselines.json"

# 17 ta kolleksiya konfiguratsiyasi
COLLECTIONS = {
    "activewindows":  ("clientId",   ["datetime"]),
    "activities":     ("employee",   ["dateTime"]),
    "rdps":           ("clientId",   ["connectTime", "disconnectTime"]),
    "screenshots":    ("clientId",   ["dateTime"]),
    "keyloggers":     ("clientId",   ["dateTime"]),
    "webvisitings":   ("clientId",   ["dateTime"]),
    "telegrams":      ("clientId",   ["dateTime"]),
    "whatsapps":      ("clientId",   ["dateTime"]),
    "emails":         ("clientId",   ["dateTime"]),
    "websearches":    ("clientId",   ["dateTime"]),
    "websniffs":      ("clientId",   ["dateTime"]),
    "usbmonitors":    ("clientId",   ["dateTime"]),
    "usbsniffs":      ("clientId",   ["dateTime"]),
    "filemonitors":   ("clientId",   ["dateTime"]),
    "clipboards":     ("clientId",   ["dateTime"]),
    "prints":         ("clientId",   ["dateTime"]),
    "incidents":      ("employee",   ["time"]),
}

DAYS_MAP = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
            4: "Friday", 5: "Saturday", 6: "Sunday"}

def get_status_color(z):
    if z is not None and abs(z) >= 1.8: return "severe", "red"
    if z is not None and abs(z) >= Z_THRESHOLD: return "anomaly", "orange"
    if z is not None and abs(z) >= 0.5: return "watch", "yellow"
    return "normal", "green"
