from collections import defaultdict
import numpy as np
from pymongo import MongoClient

# 1. MongoDB ulanishi
client = MongoClient("mongodb://192.168.100.8:27017/")
db = client["alpha-demo"]

stats_col = db["agentstats "]
session_col = db["agentsessionstatuses"]

print("1. Ma'lumotlarni yuklash...")

# agentstats kolleksiyasidan vaqtlarni olish
stats_cursor = stats_col.find(
    {"dataSniffTime": {"$ne": None}}, {"computer": 1, "dataSniffTime": 1}
)

# agentsessionstatuses kolleksiyasidan LOCK / UNLOCK holatlarini olish
session_cursor = session_col.find(
    {"dataSniffTime": {"$ne": None}, "status": {"$ne": None}},
    {"computer": 1, "dataSniffTime": 1, "status": 1},
)

comp_daily_sniffs = defaultdict(lambda: defaultdict(list))
comp_daily_sessions = defaultdict(lambda: defaultdict(list))

for rec in stats_cursor:
    comp_id = str(rec.get("computer"))
    sniff_time = rec.get("dataSniffTime")
    if comp_id and sniff_time:
        date_key = sniff_time.strftime("%Y-%m-%d")
        comp_daily_sniffs[comp_id][date_key].append(sniff_time)

for rec in session_cursor:
    comp_id = str(rec.get("computer"))
    sniff_time = rec.get("dataSniffTime")
    status = str(rec.get("status")).upper()
    if comp_id and sniff_time:
        date_key = sniff_time.strftime("%Y-%m-%d")
        comp_daily_sessions[comp_id][date_key].append((sniff_time, status))

# 2. Kompyuter yoniq bo'lgan vaqtni hisoblash (Span - Lock Duration)
user_daily_hours = defaultdict(dict)

for comp_id, dates_dict in comp_daily_sniffs.items():
    for date_key, timestamps in dates_dict.items():
        if len(timestamps) < 2:
            continue

        # Kompyuter yonish (birinchi paket) va o'chish (oxirgi paket) vaqti
        t_first = min(timestamps)
        t_last = max(timestamps)

        # Kompyuter yoniq turgan umumiy vaqt (soatda)
        total_span_seconds = (t_last - t_first).total_seconds()

        # Ekran qulflangan (LOCK) vaqtni hisoblash
        sessions = sorted(
            comp_daily_sessions[comp_id].get(date_key, []), key=lambda x: x[0]
        )
        lock_seconds = 0.0
        lock_start = None

        for event_time, status in sessions:
            if status in ["LOCK", "LOGOFF"]:
                lock_start = event_time
            elif status in ["UNLOCK", "LOGON"] and lock_start is not None:
                duration = (event_time - lock_start).total_seconds()
                if duration > 0:
                    lock_seconds += duration
                lock_start = None

        # Yoniq vaqtdan faqat ekran qulflangan vaqt ayiriladi
        net_active_seconds = max(0.0, total_span_seconds - lock_seconds)
        active_hours = net_active_seconds / 3600.0

        if active_hours > 0.001:
            user_daily_hours[comp_id][date_key] = {
                "hours": active_hours,
                "day_of_week": t_first.weekday(),
            }

# 3. UEBA Anomaliya Tahlili (Z-Score)
days_map = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}

print("\n--- HAQIQIY YONIQ VAQT BO'YICHA UEBA NATIJALARI ---")

for comp_id, dates_data in user_daily_hours.items():
    dow_hours = defaultdict(list)

    for date_key, info in dates_data.items():
        dow_hours[info["day_of_week"]].append((date_key, info["hours"]))

    # Dushanbadan Cumagacha (0..4)
    for dow in range(5):
        records_list = dow_hours.get(dow, [])
        hours_list = [h for _, h in records_list]

        if len(hours_list) < 2:
            continue

        mean = np.mean(hours_list)
        std = np.std(hours_list)

        if std == 0:
            continue

        for date_key, work_hours in records_list:
            z_score = (work_hours - mean) / std

            # Z-Score 0.5 dan katta chetlashishlarni chiqaradi
            if abs(z_score) > 1.2:
                day_name = days_map[dow]
                status_desc = (
                    "Overwork Anomaly" if z_score > 0 else "Underwork Anomaly"
                )
                print(
                    f"Computer: {comp_id} | Date: {date_key} ({day_name}) | "
                    f"Yoniq vaqt: {work_hours:.2f}h | O'rtacha: {mean:.2f}h | "
                    f"Z-Score: {z_score:.2f} | Status: {status_desc}"
                )

    # Dam olish kunlari (Shanba / Yakshanba)
    for dow in [5, 6]:
        for date_key, work_hours in dow_hours.get(dow, []):
            day_name = days_map[dow]
            print(
                f"Computer: {comp_id} | Date: {date_key} ({day_name}) | "
                f"Yoniq vaqt: {work_hours:.2f}h | Status: Weekend Work Anomaly"
            )