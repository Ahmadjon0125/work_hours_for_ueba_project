"""Collector: manbadan 60 kunlik tarixni yig'ib raw_data_for_train ga yozadi.

Faqat train/retrain paytida ishlaydi (CLI yoki /api/train, /api/retrain zanjiri).
"""
from collections import defaultdict
from datetime import datetime, timedelta

import config
from services.mongo import SESSION_COLLECTION, active_clients, ensure_indexes, local_db
from services.workday import collect_client_days
from utils.helpers import build_day_agg, build_day_doc, day_of_week, now as hozir
from utils.logger import get_logger

log = get_logger("collector")


def _log_weekday_report(client_id, coll_name, stamps):
    """Tekshiruv uchun: har hafta kuni bo'yicha birinchi/oxirgi document va soni."""
    by_weekday = defaultdict(list)
    for ts in stamps:
        by_weekday[day_of_week(ts)].append(ts)
    for weekday, tss in by_weekday.items():
        log.info("%s | %-14s | %-9s | firstDoc=%s | lastDoc=%s | docs=%d",
                 client_id, coll_name, weekday,
                 min(tss).strftime("%Y-%m-%d %H:%M:%S"),
                 max(tss).strftime("%Y-%m-%d %H:%M:%S"), len(tss))


def collect(on_progress=None):
    """90 kunlik tarixni yig'ib raw_data_for_train ni to'ldiradi.

    `on_progress(foiz, matn)` — ixtiyoriy. Har client'dan keyin chaqiriladi,
    shuning uchun uzoq ishlaydigan jarayon frontda ko'rinib turadi. CLI
    rejimida (`python collector.py`) berilmaydi va e'tiborsiz qoladi.

    Natija: {"clients": N, "days": N, "failed": [{clientId, hostname, error}, ...]}

    Manbadan o'qishda xato bo'lsa, o'sha client BUTUNLAY o'tkazib yuboriladi —
    uning eski (to'g'ri) yozuvlari saqlanib qoladi. Chala ma'lumot bilan
    yozish qilinmaydi (COL-04).
    """
    ensure_indexes()
    now = hozir()
    # Oyna faqat TO'LIQ tugagan kunlardan iborat (COL-04 emas, COL-01):
    # yuqori chegara — bugungi 00:00, ya'ni ishga tushirilgan kun kirmaydi;
    # quyi chegara — undan 60 kun oldingi 00:00. Soat nechada ishga
    # tushirilganidan qat'i nazar oyna bir xil bo'ladi.
    window_end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    window_start = window_end - timedelta(days=config.DAYS_WINDOW)
    first_date = window_start.strftime("%Y-%m-%d")
    today_str = window_end.strftime("%Y-%m-%d")   # oynaga kirmaydigan birinchi kun
    db = local_db()
    raw = db[config.COL_RAW_TRAIN]

    clients = active_clients()
    if not clients:
        log.warning("Active client topilmadi — collector bo'sh tugadi")
        return {"clients": 0, "days": 0, "failed": []}

    log.info("Collector boshlandi: %d active client, oyna %s — %s (%d to'liq kun)",
             len(clients), first_date,
             (window_end - timedelta(days=1)).strftime("%Y-%m-%d"), config.DAYS_WINDOW)

    total_days = 0
    failed = []
    for nomer, client in enumerate(clients, start=1):
        cid, hostname = client["clientId"], client["hostname"]
        if on_progress:
            on_progress(round(nomer / len(clients) * 100),
                        f"Ma'lumot yig'ilmoqda: {nomer}/{len(clients)} xodim")
        full_name = client.get("fullName")
        try:
            day_stamps = collect_client_days(client, window_start, window_end)
            barcha = [ts for kun in day_stamps.values() for ts in kun["stamps"]]
            if barcha:
                _log_weekday_report(cid, SESSION_COLLECTION, barcha)

            for date_str, kun in day_stamps.items():
                tss = kun["stamps"]
                agg = build_day_agg(tss)
                if agg is None:
                    continue
                start, finish = agg
                doc = build_day_doc(cid, hostname, date_str, start, finish, len(tss), now,
                                    full_name=full_name, active_min=kun["activeMin"])
                raw.update_one({"clientId": cid, "date": date_str}, {"$set": doc}, upsert=True)
                total_days += 1

            # Bu client uchun oyna ichidagi arxiv endi manbaning aynan nusxasi
            # bo'lishi kerak: manbadan kelmagan kunlar o'chiriladi (COL-02).
            stale = raw.delete_many({
                "clientId": cid,
                "date": {"$gte": first_date, "$lt": today_str, "$nin": list(day_stamps)},
            }).deleted_count
            if stale:
                log.info("%s (%s): manbadan yo'qolgan %d kun arxivdan o'chirildi",
                         cid, hostname, stale)
            log.info("%s (%s): %d kun yozildi", cid, hostname, len(day_stamps))
        except Exception as e:
            # Hech narsa yozilmadi: o'qish yozishdan oldin to'liq bajariladi,
            # shuning uchun bu client'ning eski ma'lumoti o'z holicha qoladi.
            failed.append({"clientId": cid, "hostname": hostname, "error": str(e)})
            log.error("%s (%s): ma'lumoti YANGILANMADI, eskisi saqlanib qoldi — %s",
                      cid, hostname, e)

    # --- Arxivni oynaning nusxasiga keltirish (COL-02) --------------------
    # 1) Sana bo'yicha — BARCHA clientlar uchun, sikldan tashqarida.
    #    Sikl ichida bo'lganda collector bormaydigan client (o'chirilgan yoki
    #    disabled) hech qachon eskirmasdi — yozuvlari abadiy qolib ketardi.
    aged = raw.delete_many({"$or": [{"date": {"$lt": first_date}},
                                    {"date": {"$gte": today_str}}]}).deleted_count
    if aged:
        log.info("Oynadan tashqaridagi %d yozuv o'chirildi", aged)

    # 2) Active ro'yxatda yo'q clientlar — ular yangi baseline'ga kirmasligi kerak.
    #    Ikkita himoya: run to'liq muvaffaqiyatli bo'lsagina va ro'yxat bo'sh
    #    bo'lmasagina o'chiramiz — manba buzilib qisqa ro'yxat qaytarsa,
    #    butun arxiv qirilib ketmasin. Arxiv hosila ma'lumot: kerak bo'lsa
    #    keyingi run manbadan qayta olib keladi.
    if not failed:
        active_ids = [c["clientId"] for c in clients]
        gone = raw.delete_many({"clientId": {"$nin": active_ids}}).deleted_count
        if gone:
            log.info("Active bo'lmagan clientlarning %d yozuvi o'chirildi "
                     "(dashboard'ga ta'sir qilmaydi — natijalar `results` da qoladi)", gone)
    else:
        log.warning("Active bo'lmagan clientlar tozalanmadi: run to'liq bajarilmadi "
                    "(%d client o'tkazib yuborilgan)", len(failed))

    if failed:
        log.error("Collector tugadi: %d client, %d kun yozildi, %d client O'TKAZIB YUBORILDI: %s",
                  len(clients), total_days, len(failed),
                  ", ".join(f["hostname"] for f in failed))
    else:
        log.info("Collector tugadi: %d client, %d kun yozildi", len(clients), total_days)
    return {"clients": len(clients), "days": total_days, "failed": failed}
