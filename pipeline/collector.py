import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from pymongo import MongoClient
from dotenv import load_dotenv
import dateutil.parser

# Load environment variables
load_dotenv()

# Config
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "ueba_db")
DAYS_WINDOW = int(os.getenv("DAYS_WINDOW", 60))
RAW_DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "raw_data.json"

# Import config from utils
from .utils import COLLECTIONS

def parse_to_datetime(val):
    """Convert various input types to a datetime object."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val
    if isinstance(val, (int, float)):
        try:
            # Try as seconds or milliseconds
            return datetime.fromtimestamp(val if val < 1e11 else val / 1000.0)
        except:
            return None
    if isinstance(val, str):
        try:
            return dateutil.parser.parse(val)
        except:
            return None
    return None

def collect_data():
    print(f"Starting Stage 1: Data Collection (with Universal Parser)...")
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
    
    print(f"Stage 1 Complete. Raw data saved to: {RAW_DATA_FILE}")
    client.close()

if __name__ == "__main__":
    collect_data()
