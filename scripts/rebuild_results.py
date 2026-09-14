"""Bir martalik: `raw_data_for_train` arxividan `results` ni qayta quradi.

Nima uchun kerak: ARCH-02 dan oldin yozilgan natijalarda taqqoslash qiymatlari
(`usualStart`, `usualFinish`, `stdStart`, `stdFinish`) saqlanmagan. Shuning uchun
ular `status: insufficient` bo'lib turadi, dashboard esa "odatda qachon kelardi"
ni joriy baseline'dan olib ko'rsatadi — jadvalda farq yozilgan, yonida esa
«Baholanmadi» turgan ziddiyat shundan.

Bu skript arxivdagi kunlik agregatlarni joriy baseline bilan `evaluate_job` dan
o'tkazadi va natijani upsert qiladi. Chiqadigan hujjatlar jonli pipeline
yozadiganidan farq qilmaydi — ayni funksiya chaqiriladi.

    python scripts/rebuild_results.py            # quruq yurish
    python scripts/rebuild_results.py --apply    # yozadi

Chegaralar:
  - manba (DLP) bazaga UMUMAN tegilmaydi — faqat mahalliy ueba_local;
  - arxivda yo'q kunlarga tegilmaydi (bugungi tugallanmagan kun, oynadan
    eski natijalar) — ular keyingi trigger o'tishida o'z-o'zidan yangilanadi;
  - hech narsa o'chirilmaydi, faqat upsert.

DIQQAT: tarixiy kunlar JORIY baseline bilan qayta baholanadi. Odatda bu qilinmaydi
(ARCH-02), lekin bu yozuvlarda baseline qiymatlari umuman yo'q — saqlanadigan
narsaning o'zi yo'q. Bir martalik ta'mirlash.
"""
import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo import UpdateOne

import config
from utils.helpers import now as hozir
from services.mongo import local_db
from services.processor import evaluate_job
from services.trainer import current_baseline_id

BATCH = config.BULK_BATCH_SIZE


def main():
    ap = argparse.ArgumentParser(description="results ni arxivdan qayta quradi")
    ap.add_argument("--apply", action="store_true", help="haqiqatan yozadi")
    ap.add_argument("--client-id", help="faqat shu xodim")
    ap.add_argument("--no-backup", action="store_true",
                    help="zaxira nusxa olinmasin (tavsiya etilmaydi)")
    args = ap.parse_args()

    if config.LOCAL_DB_NAME == config.DB_NAME:
        sys.exit(f"TO'XTATILDI: LOCAL_DB_NAME va DB_NAME bir xil ({config.DB_NAME})")

    db = local_db()
    baseline_id = current_baseline_id(db)
    if baseline_id is None:
        sys.exit("TO'XTATILDI: joriy baseline yo'q — avval o'qitish kerak")

    raw_query = {"clientId": args.client_id} if args.client_id else {}
    baselines = {b["clientId"]: b for b in
                 db[config.COL_BASELINE].find({"baselineId": baseline_id})}

    # Arxivni client bo'yicha guruhlaymiz — evaluate_job bitta client'ning
    # kunlarini birdaniga oladi.
    per_client = defaultdict(dict)
    meta = {}
    for doc in db[config.COL_RAW_TRAIN].find(raw_query):
        cid = doc["clientId"]
        per_client[cid][doc["date"]] = {
            "start": doc["start"], "finish": doc["finish"],
            "eventCount": doc.get("eventCount"), "dayOfWeek": doc.get("dayOfWeek"),
            "durationMin": doc.get("durationMin"), "activeMin": doc.get("activeMin"),
        }
        meta.setdefault(cid, {"hostname": doc.get("hostname"),
                              "fullName": doc.get("fullName")})

    results = db[config.COL_RESULTS]
    print(f"Baza: {config.LOCAL_DB_NAME}   baseline: {baseline_id}")
    print(f"Chegara: |z| > {config.ANOMALY_Z_THRESHOLD}")
    print(f"Arxiv: {len(per_client)} xodim, {sum(len(v) for v in per_client.values())} kun")
    print(f"Rejim: {'YOZISH' if args.apply else 'quruq yurish (hech nima yozilmaydi)'}\n")

    # Eski holatni o'tish matritsasi uchun eslab qolamiz
    eski = {(d["clientId"], d["date"]): d.get("status")
            for d in results.find({}, {"clientId": 1, "date": 1, "status": 1, "_id": 0})}

    if args.apply and not args.no_backup:
        backup = f"{config.COL_RESULTS}_backup_{hozir():%Y%m%d_%H%M%S}"
        results.aggregate([{"$out": backup}])
        print(f"Zaxira nusxa: {config.LOCAL_DB_NAME}.{backup}\n")

    transitions = Counter()
    baseline_yoq = []
    ops = []
    written = 0
    total = 0

    for cid, days in per_client.items():
        bl = baselines.get(cid)
        if bl is None:
            baseline_yoq.append(meta[cid]["hostname"] or cid)
        job = {"jobId": "rebuild", "clientId": cid,
               "hostname": meta[cid]["hostname"], "fullName": meta[cid]["fullName"],
               "days": days}
        for doc in evaluate_job(job, bl):
            total += 1
            oldst = eski.get((cid, doc["date"]))
            transitions[f"{oldst or '(yangi)'} -> {doc['status']}"] += 1
            ops.append(UpdateOne({"clientId": cid, "date": doc["date"]},
                                 {"$set": doc}, upsert=True))
            if args.apply and len(ops) >= BATCH:
                res = results.bulk_write(ops, ordered=False)
                written += res.modified_count + res.upserted_count
                ops = []

    if args.apply and ops:
        res = results.bulk_write(ops, ordered=False)
        written += res.modified_count + res.upserted_count

    print(f"Qayta baholangan kun: {total}")
    if baseline_yoq:
        print(f"Baseline topilmagan xodimlar ({len(baseline_yoq)}): {', '.join(baseline_yoq)}")
        print("  -> ularning kunlari `insufficient` bo'lib qoladi (to'g'ri xatti-harakat)")

    print("\nStatus o'tishlari:")
    for key, count in sorted(transitions.items(), key=lambda kv: -kv[1]):
        print(f"  {key:34s} {count:6d}")

    if args.apply:
        print(f"\nYozildi: {written} ta hujjat.")
        qolgan = results.count_documents({"anomalyScore": {"$exists": False}})
        if qolgan:
            print(f"\nArxivda yo'q {qolgan} ta yozuv qoldi (bugungi kun yoki oynadan eskisi).")
            print("Ular keyingi trigger o'tishida o'z-o'zidan yangilanadi.")
    else:
        print("\nHech narsa yozilmadi. Yozish uchun:")
        print("  python scripts/rebuild_results.py --apply")


if __name__ == "__main__":
    main()
