"""Bir martalik: mavjud `results` yozuvlariga yangi ball maydonlarini qo'shadi.

Nima uchun kerak: `isAnomaly`, `anomalyScore`, `riskScore`, `triggers`,
`triggeredDetectors`, `detectors` maydonlari faqat yangi baholashlarda paydo
bo'ladi. Eski yozuvlarda ular yo'q va `status` hali ham eski 4 pog'onali
qiymatlarda (`watch`/`severe`) turadi.

Qayta hisoblash hujjatning O'ZIDAGI `usualStart`/`usualFinish`/`std` va
`start`/`finish` qiymatlari asosida bajariladi — baseline qaytadan o'qilmaydi
(ARCH-02: natija o'zi-o'ziga yetarli). Manba (alpha-demo) bazaga UMUMAN
tegilmaydi, faqat mahalliy `ueba_local.results`.

Eslatma: taqqoslash qiymatlari umuman yo'q eski yozuvlar uchun bu skript ham
hech narsa hisoblay olmaydi — ular `insufficient` bo'lib qoladi. Bunday
yozuvlarni to'g'ri tiklash uchun `scripts/rebuild_results.py` ishlatiladi.

    python scripts/backfill_scores.py            # quruq yurish — hech nima yozilmaydi
    python scripts/backfill_scores.py --apply    # yozadi
    python scripts/backfill_scores.py --all --apply   # allaqachon ballanganini ham
"""
import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import UpdateOne

import config
from services.detectors.base import DetectorResult
from services.detectors.scoring import combine_risk, status_for
from services.detectors.working_hours import evaluate_window
from services.mongo import local_db

DETECTOR = "workingHours"
BATCH = config.BULK_BATCH_SIZE


def _hhmmss_to_minutes(value):
    """"08:12:33" -> 492.55. Noto'g'ri qiymat -> None."""
    try:
        h, m, sec = (int(x) for x in str(value).split(":"))
        return h * 60 + m + sec / 60.0
    except Exception:
        return None


def rescore(doc, weight):
    """Bitta natija hujjati uchun yangi maydonlar dict'i."""
    start_min = _hhmmss_to_minutes(doc.get("start"))
    finish_min = _hhmmss_to_minutes(doc.get("finish"))

    is_anomaly = score = details = reason = None
    if start_min is not None and finish_min is not None:
        is_anomaly, score, details, reason = evaluate_window(
            doc.get("usualStart"), doc.get("usualFinish"),
            doc.get("stdStart"), doc.get("stdFinish"), start_min, finish_min)

    if score is None:
        result = DetectorResult(name=DETECTOR, weight=weight, evaluated=False, score=0,
                                reason="shu hafta kuni uchun baseline yo'q")
        window = {"windowStart": None, "windowFinish": None}
    else:
        # Bu yozuv jonli yo'l bilan emas, backfill bilan hisoblanganini
        # keyin ajratib olish uchun belgilab qo'yamiz.
        details["source"] = "backfill"
        result = DetectorResult(name=DETECTOR, weight=weight, is_anomaly=is_anomaly,
                                score=score, reason=reason, details=details)
        window = {"windowStart": details["windowStart"],
                  "windowFinish": details["windowFinish"]}

    risk = combine_risk([result])
    status, color = status_for(result.evaluated, result.triggered)
    return {
        **window,
        "isAnomaly": result.triggered,
        "anomalyScore": score,
        "riskScore": risk,
        "status": status,
        "statusColor": color,
        "triggers": {DETECTOR: result.triggered},
        "triggeredDetectors": [DETECTOR] if result.triggered else [],
        "detectors": {DETECTOR: result.as_doc()},
    }


def main():
    ap = argparse.ArgumentParser(description="results ga ball maydonlarini qo'shadi")
    ap.add_argument("--apply", action="store_true",
                    help="haqiqatan yozadi (busiz faqat hisobot chiqadi)")
    ap.add_argument("--all", action="store_true",
                    help="allaqachon ballangan yozuvlarni ham qayta hisoblaydi")
    ap.add_argument("--client-id", help="faqat shu xodim")
    ap.add_argument("--limit", type=int, help="ko'pi bilan shuncha yozuv")
    args = ap.parse_args()

    # Xavfsizlik darvozasi: mahalliy va manba baza nomi bir xil bo'lsa to'xtaymiz.
    if config.LOCAL_DB_NAME == config.DB_NAME:
        sys.exit(f"TO'XTATILDI: LOCAL_DB_NAME va DB_NAME bir xil ({config.DB_NAME}) — "
                 "manba bazaga yozib yuborish xavfi bor")

    query = {} if args.all else {"anomalyScore": {"$exists": False}}
    if args.client_id:
        query["clientId"] = args.client_id

    col = local_db()[config.COL_RESULTS]
    # DIQQAT: `stdStart`/`stdFinish` proyeksiyada BO'LISHI SHART — ular oynaning
    # kengligini beradi. Tushib qolsa oyna og'ishsiz, juda tor hisoblanadi va
    # deyarli har kun chetlanish bo'lib chiqadi.
    cursor = col.find(query, {"_id": 1, "status": 1, "start": 1, "finish": 1,
                              "usualStart": 1, "usualFinish": 1,
                              "stdStart": 1, "stdFinish": 1})
    if args.limit:
        cursor = cursor.limit(args.limit)

    weight = config.detector_weight(DETECTOR)
    print(f"Baza: {config.LOCAL_DB_NAME}.{config.COL_RESULTS}")
    print(f"Chegara: |z| > {config.ANOMALY_Z_THRESHOLD}   {DETECTOR} vazni: {weight}")
    print(f"Rejim: {'YOZISH' if args.apply else 'quruq yurish (hech nima yozilmaydi)'}\n")

    transitions = Counter()
    ops = []
    written = 0
    total = 0

    for doc in cursor:
        total += 1
        fields = rescore(doc, weight)
        transitions[f"{doc.get('status') or '—'} -> {fields['status']}"] += 1
        ops.append(UpdateOne({"_id": doc["_id"]}, {"$set": fields}))
        if args.apply and len(ops) >= BATCH:
            written += col.bulk_write(ops, ordered=False).modified_count
            ops = []

    if args.apply and ops:
        written += col.bulk_write(ops, ordered=False).modified_count

    print(f"Ko'rilgan yozuv: {total}")
    if not total:
        print("Qayta hisoblanadigan yozuv topilmadi.")
        return

    print("\nStatus o'tishlari:")
    for key, count in sorted(transitions.items(), key=lambda kv: -kv[1]):
        print(f"  {key:34s} {count:6d}")

    if args.apply:
        print(f"\nYozildi: {written} ta hujjat.")
    else:
        print("\nHech narsa yozilmadi. Yozish uchun:")
        print(f"  mongodump --db {config.LOCAL_DB_NAME} --collection {config.COL_RESULTS}")
        print("  python scripts/backfill_scores.py --apply")


if __name__ == "__main__":
    main()
