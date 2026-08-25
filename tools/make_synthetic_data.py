"""
Sintetik raw_data.json generatori — pipeline test uchun.

Format kollektor chiqarishi bilan BIR XIL:
    {collection: [{"uid": ..., "tss": ["ISO", ...]}, ...]}

Foydalanuvchilar (8 ta, 56 kunlik oyna):
  a1..a8 — dushanba-juma: har biri o'z navbatida ishlaydi (± jitter)
  a7     — "tunukchi": ayrim dushanba-juma kunlari 01:30-02:30 da boshlaydi
  a8     — "kech tugatuvidigan": ayrim dushanba-juma kunlari 21:30-23:00 da tugatadi
  HAMMASI — 6 ta shanba + 6 ta yakshanbada ham ishlaydi (2 tadan "dam kuni" tashlab).
            Har bir hafta kuni (shu jumla shanba/yakshanba) uchun baseline ALOHIDA
            hisoblanadi — boshqa kunlarga ta'siri yo'q.

Qo'llash:  python tools/make_synthetic_data.py
Natiq:     data/raw_data.json (ustidagi REAL faylni yozib yuboradi — oldin backup oling!)
Qayta tiklash: oddiy 'python main.py --retrain' (Stage 0 Mongo dan qayta olib keladi)
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
WINDOW_DAYS = 56
OUT = Path(__file__).resolve().parent.parent / "data" / "raw_data.json"

COLLECTIONS = [
    "activewindows", "filemonitors", "webvisitings",
    "emails", "screenshots", "telegrams",
]

# (uid, start_min, start_std, finish_min, finish_std,
#  wekStart, wekStart_std, wekFinish, wekFinish_std) — 00:00 dan daqiqa
USERS = [
    ("6a7f000000000000000000a1", 585, 20, 1080, 20,  660, 40,  990, 40),  # d-j 09:45->18:00 | sh/ya 11:00->16:30
    ("6a7f000000000000000000a2", 540, 25, 1050, 25,  660, 40,  990, 40),  # d-j 09:00->17:30 | sh/ya 11:00->16:30
    ("6a7f000000000000000000a3", 600, 20, 1110, 20,  690, 40, 1020, 40),  # d-j 10:00->18:30 | sh/ya 11:30->17:00
    ("6a7f000000000000000000a4", 510, 25, 1020, 20,  630, 40,  960, 40),  # d-j 08:30->17:00 | sh/ya 10:30->16:00
    ("6a7f000000000000000000a5", 555, 30, 1095, 25,  660, 40,  990, 40),  # d-j 09:15->18:15 | sh/ya 11:00->16:30
    ("6a7f000000000000000000a6", 630, 20, 1140, 20,  720, 40, 1050, 40),  # d-j 10:30->19:00 | sh/ya 12:00->17:30
    ("6a7f000000000000000000a7", 540, 20, 1050, 20,  600, 30,  960, 30),  # tunukchi        | sh/ya 10:00->16:00
    ("6a7f000000000000000000a8", 585, 15, 1080, 15,  660, 40,  990, 40),  # kech tugatadi    | sh/ya 11:00->16:30
]
NIGHT_UID = USERS[6][0]
LATE_UID = USERS[7][0]


def gen_day_events(day0, start_min, finish_min, n):
    """Bir kungacha event timestamp lari (00:00 dan)."""
    span = finish_min - start_min
    evs = []
    for _ in range(n):
        if random.random() < 0.7:
            # 70%: ish oynasi bo'ylab tekis
            t = start_min + random.random() * span
        else:
            # 30%: boshlanish/tugash yaqinida to'plangan
            edge = 0.08 if random.random() < 0.5 else 0.92
            t = random.gauss(start_min + span * edge, 12)
        t = min(max(t, start_min), finish_min)
        evs.append(day0 + timedelta(minutes=t, seconds=random.randint(0, 59)))
    return evs


def main():
    random.seed(SEED)
    now = datetime.now().replace(second=0, microsecond=0)
    acc = {}  # (col, uid) -> [datetime]
    summary = {}

    # Weekend: HAMMA user 6 ta shanba + 6 ta yakshanbada ishlaydi
    # (har biridan 2 tasi "dam kuni" — baseline uchun n=6 >= MIN_DOW_SAMPLES=5)
    sat_b = [b for b in range(WINDOW_DAYS, 0, -1) if (now - timedelta(days=b)).weekday() == 5]
    sun_b = [b for b in range(WINDOW_DAYS, 0, -1) if (now - timedelta(days=b)).weekday() == 6]
    sat_work = set(sat_b) - {sat_b[1], sat_b[5]}
    sun_work = set(sun_b) - {sun_b[1], sun_b[5]}

    for uid, s0, ss, f0, fs, ws, wss, wf, wfs in USERS:
        work_idx = 0   # ish kuni tartibi (dushanba-juma) — anomaliya naqshi uchun
        for back in range(WINDOW_DAYS, 0, -1):
            day0 = (now - timedelta(days=back)).replace(hour=0, minute=0, second=0)
            dow = day0.weekday()
            is_weekend = dow >= 5
            # Weekend: hamma user 6 shanba + 6 yakshanbada ishlaydi
            if is_weekend and back not in (sat_work if dow == 5 else sun_work):
                continue
            if not is_weekend:
                work_idx += 1

            if is_weekend:
                # Weekend navbati (apart dushanba-jumadan, alohida baseline)
                start = max(300.0, random.gauss(ws, wss))
                finish = min(1380.0, random.gauss(wf, wfs))
            else:
                start, finish = (
                    max(300.0, random.gauss(s0, ss)),
                    min(1380.0, random.gauss(f0, fs)),
                )
            note = ""
            # anomaliyalar faqat dushanba-juma kunlariga joylanadi
            if uid == NIGHT_UID and dow < 5 and work_idx > 15 and work_idx % 9 in (3, 8):
                start = random.uniform(90.0, 150.0)          # 01:30-02:30
                finish = start + random.uniform(480.0, 540.0)
                note = "  <== TUN: ish 01:30-02:30 da boshlandi"
            elif uid == LATE_UID and dow < 5 and work_idx > 12 and work_idx % 8 == 5:
                finish = random.uniform(1290.0, 1380.0)      # 21:30-23:00
                note = "  <== KEC: ish 21:30-23:00 da tugadi"

            for dt in gen_day_events(day0, start, finish, random.randint(60, 150)):
                col = random.choice(COLLECTIONS)
                acc.setdefault((col, uid), []).append(dt)
            if note:
                summary.setdefault(uid, []).append(f"{day0.date()}{note}")

    # Payload: har bir kolleksiya -> [{uid, tss}, ...]
    payload = {col: [] for col in COLLECTIONS}
    by_key = {}
    for (col, uid), tss in acc.items():
        by_key.setdefault((col, uid), []).extend(tss)
    for (col, uid), tss in sorted(by_key.items()):
        payload[col].append({
            "uid": uid,
            "tss": [t.isoformat() for t in sorted(tss)],
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    print(f"Sintetik ma'lumot yozildi: {OUT} ({len(USERS)} user, {WINDOW_DAYS} kun)")
    for uid, notes in sorted(summary.items()):
        print(f"  {uid} — joylangan anomaliya kunlari:")
        for n in notes:
            print(f"      {n}")
    print(f"  Weekend: hamma user {len(sat_work)} ta shanba + {len(sun_work)} ta yakshanbada ishlaydi (alohida baseline'lar)")


if __name__ == "__main__":
    main()
