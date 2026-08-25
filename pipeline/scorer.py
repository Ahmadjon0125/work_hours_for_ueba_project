"""
Bosqich 2 (baholash): baseline.json + raw_data.json -> results.json

baseline.json FAQAT O'QILADI, yozilmaydi.
Har bir kun o'z hafta kunining baseline'iga nisbatan baholanadi:
  zStart  = (start  - meanStart)  / stdStart   (alohida)
  zFinish = (finish - meanFinish) / stdFinish  (alohida)
std=0 yoki baseline yo'q bo'lsa z = None (baholab bo'lmaydi).
"""
import json
from datetime import datetime

from .utils import (
    BASELINE_FILE,
    DAYS_MAP,
    MAX_DAILY_HOURS,
    MIN_DAILY_EVENTS,
    RAW_DATA_FILE,
    RESULTS_FILE,
    build_user_day_ts,
    filter_valid_days,
    to_minutes,
)

def _round3(x):
    return round(x, 3) if x is not None else None

def score():
    print("Starting Stage 2 (Score): computing Z-scores against trained baseline...")

    if not BASELINE_FILE.exists():
        raise FileNotFoundError(
            f"Baseline file {BASELINE_FILE} not found. Run 'train' first."
        )
    if not RAW_DATA_FILE.exists():
        raise FileNotFoundError(
            f"Raw data file {RAW_DATA_FILE} not found. Run collection first."
        )

    with open(BASELINE_FILE, "r", encoding="utf-8") as f:
        baseline = json.load(f)
    with open(RAW_DATA_FILE, "r", encoding="utf-8") as f:
        raw_payload = json.load(f)

    baselines = baseline.get("baselines", {})
    user_day_ts, _uids = build_user_day_ts(raw_payload)
    # Trainer bilan bir xil shovqin filtri (kam eventli / 12+ soatlik kunlar baholanmaydi)
    user_day_ts = {
        uid: filter_valid_days(days) for uid, days in user_day_ts.items()
    }
    print(
        f"Shovqin filtri qo'llandi: min {MIN_DAILY_EVENTS} event, "
        f"max {MAX_DAILY_HOURS:.0f} soat kunlik"
    )

    all_dates = set()
    for days in user_day_ts.values():
        all_dates.update(days.keys())
    if not all_dates:
        raise ValueError("No data to score in raw_data.json.")

    # Foydalanuvchilarni umumiy ish vaqti bo'yicha kamayish tartibida saralash
    user_totals = {}
    for uid, days in user_day_ts.items():
        for tss in days.values():
            user_totals[uid] = user_totals.get(uid, 0.0) + (
                (max(tss) - min(tss)).total_seconds() / 3600.0
            )

    users_out = []
    for uid in sorted(user_totals, key=lambda x: -user_totals[x]):
        days_out = []
        for dk in sorted(user_day_ts[uid].keys()):
            tss = user_day_ts[uid][dk]
            start, finish = min(tss), max(tss)
            dur_min = (finish - start).total_seconds() / 60.0

            # Aynan shu hafta kunining o'qitilgan baseline'iga nisbatan
            week = baselines.get(uid, {}).get("weeks", {}).get(
                DAYS_MAP[dk.weekday()]
            )
            z_start = None
            z_finish = None
            if week:
                mean_start, std_start = week.get("meanStart"), week.get("stdStart")
                mean_finish, std_finish = (
                    week.get("meanFinish"),
                    week.get("stdFinish"),
                )
                if mean_start is not None and std_start:
                    z_start = (to_minutes(start) - mean_start) / std_start
                if mean_finish is not None and std_finish:
                    z_finish = (to_minutes(finish) - mean_finish) / std_finish

            days_out.append({
                "date": dk.isoformat(),
                "dayOfWeek": DAYS_MAP[dk.weekday()],
                "start": start.strftime("%H:%M:%S"),
                "finish": finish.strftime("%H:%M:%S"),
                "durationMin": round(dur_min, 2),
                "zStart": _round3(z_start),
                "zFinish": _round3(z_finish),
            })

        users_out.append({
            "clientId": uid,
            "username": baselines.get(uid, {}).get("username", uid),
            "days": days_out,
        })

    result = {
        "meta": {
            "evalFrom": min(all_dates).isoformat(),
            "evalTo": max(all_dates).isoformat(),
            "generatedAt": datetime.now().isoformat(),
            "baselineTrainedAt": baseline.get("meta", {}).get("trainedAt"),
        },
        "users": users_out,
    }

    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Stage 2 (Score) Complete. Results saved to: {RESULTS_FILE}")

if __name__ == "__main__":
    score()
