
import json
from datetime import datetime
from pathlib import Path
from pymongo import MongoClient
from dotenv import load_dotenv
import dateutil.parser
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

def parse_to_date(val):
    if val is None: return None
    if isinstance(val, datetime): return val.date()
    if isinstance(val, (int, float)):
        try:
            return datetime.fromtimestamp(val if val < 1e11 else val / 1000.0).date()
        except: return None
    if isinstance(val, str):
        try:
            return dateutil.parser.parse(val).date()
        except: return None
    return None

def audit_user_fixed(db, uid):
    print(f"\\n--- Fixed Audit for User: {uid} ---")
    all_active_dates = set()
    
    print(f"{'Collection':<18} | {'Unique Days':<12}")
    print('-' * 32)
    
    from bson import ObjectId
    try:
        oid = ObjectId(uid)
    except:
        oid = uid

    for col in COLLECTIONS:
        try:
            # Fetch all documents for this user to avoid field type issues
            cursor = db[col].find({"$or": [{"clientId": oid}, {"employee": oid}]})
            
            col_dates = set()
            for doc in cursor:
                # Check all fields in the document for anything that looks like a date
                for k, v in doc.items():
                    # We only check fields that are typically timestamps or start with common prefixes
                    if any(x in k.lower() for x in ['time', 'date', 'ts', 'created']):
                        d = parse_to_date(v)
                        if d:
                            col_dates.add(d)
                            all_active_dates.add(d)
            
            print(f"{col:<18} | {len(col_dates):<12}")
                
        except Exception as e:
            print(f"{col:<18} | ERROR: {e}")
    
    print('-' * 32)
    print(f"TOTAL UNIQUE ACTIVE DAYS: {len(all_active_dates)}")
    if all_active_dates:
        print(f"Date Range: {min(all_active_dates)} to {max(all_active_dates)}")

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
        audit_user_fixed(db, uid)
    else:
        print(f"User {target_name} not found")
    client.close()
