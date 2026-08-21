import json
from datetime import datetime
from collections import defaultdict
from pymongo import MongoClient
from .utils import MONGO_URI, DB_NAME, DAYS_WINDOW, RESULTS_FILE, BASELINES_FILE, DAYS_MAP, get_status_color, RAW_DATA_FILE, MIN_DOW_SAMPLES

def process_data():
    print(f"Starting Stage 2: Data Processing...")
    
    if not RAW_DATA_FILE.exists():
        print(f"Error: Raw data file {RAW_DATA_FILE} not found. Run collector first.")
        return

    with open(RAW_DATA_FILE, "r", encoding="utf-8") as f:
        raw_payload = json.load(f)

    # 1. Yig'ish: user -> date -> timestamps
    user_day_ts = defaultdict(lambda: defaultdict(list))
    user_day_cols = defaultdict(lambda: defaultdict(set))
    unique_client_ids = set()

    for colname, entries in raw_payload.items():
        for entry in entries:
            uid = entry["uid"]
            unique_client_ids.add(uid)
            for ts_str in entry["tss"]:
                dt = datetime.fromisoformat(ts_str)
                dk = dt.date()
                user_day_ts[uid][dk].append(dt)
                user_day_cols[uid][dk].add(colname)

    # 2. Usernames ni bog'lash (clients collection orqali)
    print(f"Mapping usernames for {len(unique_client_ids)} clients...")
    user_names = {}
    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000)
        db = client[DB_NAME]
        from bson import ObjectId
        try:
            oids = [ObjectId(uid) for uid in unique_client_ids]
        except:
            oids = list(unique_client_ids)
        for user_doc in db["clients"].find({"_id": {"$in": oids}}, {"_id": 1, "firstName": 1, "lastName": 1, "fullName": 1, "hostname": 1, "username": 1}):
            oid = str(user_doc.get("_id"))
            fname = user_doc.get("firstName")
            lname = user_doc.get("lastName")
            f_name = user_doc.get("fullName")
            hname = user_doc.get("hostname")
            uname = user_doc.get("username")
            
            # Priority mapping:
            # 1. firstName + lastName
            # 2. fullName
            # 3. hostname
            # 4. username
            # 5. fallback to oid
            
            final_name = ""
            if fname or lname:
                final_name = f"{fname or ''} {lname or ''}".strip()
            elif f_name:
                final_name = str(f_name).strip()
            elif hname:
                final_name = str(hname).strip()
            elif uname:
                final_name = str(uname).strip()
            else:
                final_name = oid
                
            user_names[oid] = final_name if final_name else oid
    except Exception as e:
        print(f"Warning: Error mapping usernames: {e}")

    # 3. Kunlik hisob-kitoblar (span)
    daily = {}
    for uid, days in user_day_ts.items():
        for dk, tss in days.items():
            if not tss: continue
            start, finish = min(tss), max(tss)
            hours = (finish - start).total_seconds() / 3600.0
            daily[(uid, dk)] = {
                "hours": hours,
                "start": start,
                "finish": finish,
                "dayOfWeek": dk.weekday(),
            }

    # 4. Baseline-lar va Z-scores hisoblash
    zmap = {}
    baselines = {} # user -> {dow: {mean, std, count}}
    
    by_user_dow = defaultdict(lambda: defaultdict(list))
    for (uid, dk), d in daily.items():
        by_user_dow[uid][d["dayOfWeek"]].append((dk, d["hours"]))

    for uid, dow_dict in by_user_dow.items():
        baselines[uid] = {}
        for dow, recs in dow_dict.items():
            hs = [h for _, h in recs]
            count = len(hs)
            if count < MIN_DOW_SAMPLES:
                baselines[uid][dow] = {"mean": None, "std": None, "count": count}
                continue
            
            mean = sum(hs) / count
            var = sum((h - mean) ** 2 for h in hs) / count
            std = var ** 0.5
            
            baselines[uid][dow] = {"mean": round(mean, 3), "std": round(std, 3), "count": count}
            
            if std > 0:
                for dk, h in recs:
                    zmap[(uid, dk)] = ((h - mean) / std, mean)
            else:
                # std=0 bo'lsa hamma kunlar bir xil, z=0
                for dk, h in recs:
                    zmap[(uid, dk)] = (0.0, mean)

    # Baseline-larni saqlash
    with open(BASELINES_FILE, "w", encoding="utf-8") as f:
        json.dump(baselines, f, ensure_ascii=False, indent=2)
    print(f"Baselines saved to: {BASELINES_FILE}")

    # 5. Yakuniy tuzilmani yaratish
    user_totals = {}
    for (uid, dk), d in daily.items():
        user_totals[uid] = user_totals.get(uid, 0.0) + d["hours"]
    
    ordered_uids = sorted(user_totals, key=lambda x: -user_totals[x])
    users_out = []
    for uid in ordered_uids:
        username = user_names.get(uid, uid)
        daily_out = []
        user_days = sorted([(dk, d) for (u, dk), d in daily.items() if u == uid], key=lambda x: x[0])
        
        for dk, d in user_days:
            z_info = zmap.get((uid, dk))
            z = z_info[0] if z_info else None
            status, color = get_status_color(z)
            daily_out.append({
                "date": dk.isoformat(),
                "dayOfWeek": DAYS_MAP[d["dayOfWeek"]],
                "start": d["start"].strftime("%Y-%m-%d %H:%M:%S"),
                "finish": d["finish"].strftime("%Y-%m-%d %H:%M:%S"),
                "hours": round(d["hours"], 4),
                "contributing": sorted(list(user_day_cols[uid][dk])),
                "contribCount": len(user_day_cols[uid][dk]),
                "zScore": round(z, 3) if z is not None else None,
                "status": status,
                "color": color,
            })
        
        total = sum(x["hours"] for x in daily_out)
        active = len(daily_out)
        users_out.append({
            "clientId": uid,
            "username": username,
            "daily": daily_out,
            "summary": {
                "activeDays": active,
                "totalHours": round(total, 2),
                "avgDailyHours": round(total / active, 2) if active else 0,
            },
        })

    result = {
        "meta": {
            "windowDays": DAYS_WINDOW,
            "generatedAt": datetime.now().isoformat(),
        },
        "users": users_out,
    }

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    print(f"Stage 2 Complete. Results saved to: {RESULTS_FILE}")

if __name__ == "__main__":
    process_data()
