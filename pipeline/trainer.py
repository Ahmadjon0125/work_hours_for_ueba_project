"""
Bosqich 1 (o'qitish): raw_data.json -> baseline.json

Har bir user xar bir hafta kuni uchun alohida baseline yaratiladi:
  meanStart  - o'rtacha ish boshlash vaqti (00:00 dan daqiqa)
  stdStart   - boshlash vaqti og'ishi (sigma, alohida)
  meanFinish - o'rtacha ish tugash vaqti (00:00 dan daqiqa)
  stdFinish  - tugash vaqti og'ishi (sigma, alohida)
  meanDuration - o'rtacha ish vaqti (daqiqa)
  count      - shu hafta kuniga to'g'ri kelgan kunlar soni

Bu fayl FAQAT o'qitilgan modeldir — scorer uning ustiga yozmaydi.
"""
import json
from collections import defaultdict
from datetime import datetime

from .utils import (
    BASELINE_FILE,
    DAYS_MAP,
    DAYS_WINDOW,
    MIN_DOW_SAMPLES,
    RAW_DATA_FILE,
    build_user_day_ts,
    load_usernames,
    sample_std,
    to_minutes,
)

def train():
    print("Starting Stage 1 (Train): building per-weekday baselines...")

    if not RAW_DATA_FILE.exists():
        raise FileNotFoundError(
            f"Raw data file {RAW_DATA_FILE} not found. Run collection first."
        )

    with open(RAW_DATA_FILE, "r", encoding="utf-8") as f:
        raw_payload = json.load(f)

    user_day_ts, uids = build_user_day_ts(raw_payload)

    # Usernames ni bog'lash (clients collection orqali)
    print(f"Mapping usernames for {len(uids)} clients...")
    user_names = load_usernames(uids)

    # user -> dow -> [(start_min, finish_min, dur_min)]
    dow_samples = defaultdict(lambda: defaultdict(list))
    for uid, days in user_day_ts.items():
        for dk, tss in days.items():
            if not tss:
                continue
            start, finish = min(tss), max(tss)
            dur_min = (finish - start).total_seconds() / 60.0
            dow_samples[uid][dk.weekday()].append(
                (to_minutes(start), to_minutes(finish), dur_min)
            )

    baselines = {}
    for uid, dows in dow_samples.items():
        weeks = {}
        for dow, samples in sorted(dows.items()):
            n = len(samples)
            if n < MIN_DOW_SAMPLES:
                # Yetarli namunasi yo'q -> stat'lar null, z hisoblanmaydi
                weeks[DAYS_MAP[dow]] = {
                    "count": n,
                    "meanStart": None,
                    "stdStart": None,
                    "meanFinish": None,
                    "stdFinish": None,
                    "meanDuration": None,
                }
                continue

            starts = [s for s, _, _ in samples]
            finishes = [f for _, f, _ in samples]
            durs = [d for _, _, d in samples]

            std_start = sample_std(starts)
            std_finish = sample_std(finishes)

            weeks[DAYS_MAP[dow]] = {
                "count": n,
                "meanStart": round(sum(starts) / n, 2),
                "stdStart": round(std_start, 2) if std_start is not None else None,
                "meanFinish": round(sum(finishes) / n, 2),
                "stdFinish": round(std_finish, 2) if std_finish is not None else None,
                "meanDuration": round(sum(durs) / n, 2),
            }

        baselines[uid] = {
            "username": user_names.get(uid, uid),
            "weeks": weeks,
        }

    result = {
        "meta": {
            "windowDays": DAYS_WINDOW,
            "trainedAt": datetime.now().isoformat(),
            "minDowSamples": MIN_DOW_SAMPLES,
            "userCount": len(baselines),
        },
        "baselines": baselines,
    }

    with open(BASELINE_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"Stage 1 (Train) Complete. Baseline saved to: {BASELINE_FILE}")

if __name__ == "__main__":
    train()
