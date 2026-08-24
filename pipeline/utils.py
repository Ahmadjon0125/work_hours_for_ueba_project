# Yordamchi funksiyalar va umumiy sozlamalar
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

# Config
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "ueba_db")
DAYS_WINDOW = int(os.getenv("DAYS_WINDOW", 60))
Z_THRESHOLD = float(os.getenv("Z_THRESHOLD", 1.2))
SEVERE_THRESHOLD = float(os.getenv("SEVERE_THRESHOLD", 1.8))
MIN_DOW_SAMPLES = int(os.getenv("MIN_DOW_SAMPLES", 2))

# Fayl yo'llari
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_FILE = DATA_DIR / "raw_data.json"
RESULTS_FILE = DATA_DIR / "results.json"
BASELINE_FILE = DATA_DIR / "baseline.json"

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
    if z is None:
        return "insufficient", "gray"
    if abs(z) >= SEVERE_THRESHOLD: return "severe", "red"
    if abs(z) >= Z_THRESHOLD: return "anomaly", "orange"
    if abs(z) >= 0.5: return "watch", "yellow"
    return "normal", "green"

def to_minutes(dt):
    """datetime -> 00:00 dan daqiqa (float)."""
    return dt.hour * 60 + dt.minute + dt.second / 60.0

def minutes_to_hhmm(minutes):
    """daqiqa -> 'HH:MM' formatida qaytaradi."""
    m = round(minutes) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"

def sample_std(values):
    """Sample standart og'ish (n-1). n < 2 bo'lsa None."""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    return var ** 0.5

def build_user_day_ts(raw_payload):
    """raw payload -> (user -> date -> [datetime], unique uid set).

    Kunlik start/finish logikasi shu yerda: start = min(ts), finish = max(ts)
    (qo'llashchilar tomonidan min/max bilan ishlanadi).
    """
    user_day_ts = defaultdict(lambda: defaultdict(list))
    uids = set()
    for entries in raw_payload.values():
        for entry in entries:
            uid = entry["uid"]
            uids.add(uid)
            for ts_str in entry["tss"]:
                dt = datetime.fromisoformat(ts_str)
                user_day_ts[uid][dt.date()].append(dt)
    return user_day_ts, uids

def load_usernames(uids):
    """clients kolleksiyasi orqali username mapping.

    Har bir uid ni alohida konversiya qilamiz: valid ObjectId bo'lmaganlar
    raw string qilib alohida so'rovda qidiriladi (barcha yoki hech
    bo'lmagan eski xato tuzatildi).
    """
    user_names = {}
    if not uids:
        return user_names

    from bson import ObjectId
    oids, raws = [], []
    for uid in uids:
        try:
            oids.append(ObjectId(uid))
        except Exception:
            raws.append(uid)

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    try:
        db = client[DB_NAME]
        for ids in (oids, raws):
            if not ids:
                continue
            for doc in db["clients"].find(
                {"_id": {"$in": ids}},
                {"_id": 1, "firstName": 1, "lastName": 1,
                 "fullName": 1, "hostname": 1, "username": 1},
            ):
                # Priority: firstName+lastName -> fullName -> hostname -> username -> oid
                fname = doc.get("firstName")
                lname = doc.get("lastName")
                f_name = doc.get("fullName")
                hname = doc.get("hostname")
                uname = doc.get("username")

                if fname or lname:
                    final_name = f"{fname or ''} {lname or ''}".strip()
                elif f_name:
                    final_name = str(f_name).strip()
                elif hname:
                    final_name = str(hname).strip()
                elif uname:
                    final_name = str(uname).strip()
                else:
                    final_name = str(doc.get("_id"))

                key = str(doc.get("_id"))
                user_names[key] = final_name if final_name else key
    except Exception as e:
        print(f"Warning: Error mapping usernames: {e}")
    finally:
        client.close()

    return user_names
