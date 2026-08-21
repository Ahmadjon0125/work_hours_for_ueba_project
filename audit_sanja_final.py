
import json
from datetime import datetime
from pathlib import Path
from pymongo import MongoClient
from dotenv import load_dotenv
import os

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "ueba_db")
RESULTS_FILE = Path('/home/ahmadjon/Desktop/ueba/data/results.json')

COLLECTIONS = [
    "activewindows", "activities", "rdps", "screenshots", "keyloggers",
    "webvisitings", "telegrams", "whatsapps", "emails", "websearches",
    "websniffs", "usbmonitors", "usbsniffs", "filemonitors", "clipboards",
    "prints", "incidents"
]

def audit_user_fast(db, uid):
    print(f"\\n--- Fast Audit for User: {uid} ---")
    active_days = set()
    
    print(f"{'Collection':<18} | {'Unique Days':<12}")
    print('-' * 32)
    
    from bson import ObjectId
    try:
        oid = ObjectId(uid)
    except:
        oid = uid

    for col in COLLECTIONS:
        try:
            # Find a sample document to identify the date field
            sample = db[col].find_one({"$or": [{"clientId": oid}, {"employee": oid}]})
            if not sample:
                print(f"{col:<18} | 0")
                continue
                
            date_field = None
            for k, v in sample.items():
                if isinstance(v, datetime):
                    date_field = k
                    break
            
            if date_field:
                # Use distinct to get all unique dates for this field - much faster
                distinct_dates = db[col].distinct(date_field, {"$or": [{"clientId": oid}, {"employee": oid}]})
                count_days = 0
                for dt in distinct_dates:
                    if isinstance(dt, datetime):
                        active_days.add(dt.date())
                        count_days += 1
                print(f"{col:<18} | {count_days:<12}")
            else:
                print(f"{col:<18} | No Date Field")
                
        except Exception as e:
            print(f"{col:<18} | ERROR")
    
    print('-' * 32)
    print(f"TOTAL UNIQUE ACTIVE DAYS (across all cols): {len(active_days)}")

if __name__ == '__main__':
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    if not RESULTS_FILE.exists():
        print("Results file not found!")
        exit(1)
        
    with open(RESULTS_FILE, 'r') as f:
        data = json.load(f)
    
    target_name = "sanja@desktop-q46u2et"
    uid = next((u['clientId'] for u in data.get('users', []) if u.get('username') == target_name), None)
    
    if uid:
        audit_user_fast(db, uid)
    else:
        print(f"User {target_name} not found")
    client.close()
