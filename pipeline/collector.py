import json
from datetime import datetime, timedelta

from dateutil import parser as dateutil_parser
from dotenv import load_dotenv
from pymongo import MongoClient

from .utils import COLLECTIONS, DAYS_WINDOW, DB_NAME, MONGO_URI, RAW_DATA_FILE

# Load environment variables
load_dotenv()

def parse_to_datetime(val):
    """Convert various input types to a naive local datetime."""
    if val is None:
        return None
    if isinstance(val, datetime):
        dt = val
    elif isinstance(val, (int, float)):
        try:
            # Try as seconds or milliseconds
            dt = datetime.fromtimestamp(val if val < 1e11 else val / 1000.0)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(val, str):
        try:
            dt = dateutil_parser.parse(val)
        except (ValueError, OverflowError):
            return None
    else:
        return None

    # BSON Date (UTC-aware) ni naive lokal vaqtga keltiramiz —
    # shunda win_start bilan solishtirish TypeError bermaydi
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt

def collect_data():
    print("Starting Stage 0: Data Collection (with Universal Parser)...")
    now = datetime.now()
    win_start = now - timedelta(days=DAYS_WINDOW)

    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
    db = client[DB_NAME]

    raw_payload = {}

    for colname, (idf, tf) in COLLECTIONS.items():
        proj = {idf: 1}
        for t in tf:
            proj[t] = 1

        time_field = tf[0]
        # Fetch documents that have the time field
        query = {time_field: {"$exists": True}}
        cur = db[colname].find(query, proj)

        col_data = []
        n = 0
        for rec in cur:
            uid = rec.get(idf)
            if uid is None:
                continue
            uid_str = str(uid).strip()

            tss = []
            for t in tf:
                val = rec.get(t)
                dt = parse_to_datetime(val)
                if dt and dt >= win_start:
                    tss.append(dt.isoformat())

            if tss:
                col_data.append({
                    "uid": uid_str,
                    "tss": tss
                })
                n += 1

        raw_payload[colname] = col_data
        print(f"   {colname:<14} o'qildi: {n} foydali yozuv")

    RAW_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(RAW_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(raw_payload, f, ensure_ascii=False, indent=2)

    print(f"Stage 0 Complete. Raw data saved to: {RAW_DATA_FILE}")
    client.close()

if __name__ == "__main__":
    collect_data()
