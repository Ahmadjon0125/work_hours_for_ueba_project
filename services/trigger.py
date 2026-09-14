"""Trigger: cursor asosida yangi ma'lumotni olib, har client uchun job yuboradi.

FAQAT avtomatik ishlaydi (APScheduler) — API orqali ishga tushirish yo'li yo'q.
trigger_data ning yagona egasi: cursor + dedup + "nima yuborilgan" yozuvi.
"""
import uuid
from collections import defaultdict
from datetime import datetime, timedelta

import config
from mq.rabbitmq import connect, declare_queue, publish
from services.mongo import active_clients, ensure_indexes, local_db
from services.workday import collect_client_days
from utils.helpers import build_day_agg, build_day_doc, date_str_days_ago
from utils.logger import get_logger

log = get_logger("trigger")


class NoActiveClients(Exception):
    """Manba bazada active xodim topilmadi — kutilmagan holat."""


class QueueUnavailable(Exception):
    """Navbatga ulanib bo'lmadi — o'tish umuman boshlanmadi.

    Alohida tur: "hech narsa yuborilmadi, chunki navbat yo'q" bilan
    "hech narsa yuborilmadi, chunki yangi kun yo'q" ni ajratish uchun.
    """


def _window_start(trigger_col, client_id, now):
    """Cursor: oxirgi yuborilgan finish ning kun boshi. Cursor yo'q bo'lsa — oxirgi LOOKBACK_HOURS."""
    last = trigger_col.find_one({"clientId": client_id}, {"finish": 1},
                                sort=[("finish", -1)])
    if last and last.get("finish"):
        try:
            cursor_dt = datetime.fromisoformat(last["finish"])
            # Kun boshiga tushiramiz: o'sha kun to'liq qayta olinadi (self-correct)
            return cursor_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            pass
    return now - timedelta(hours=config.LOOKBACK_HOURS)


def run():
    """Bitta trigger o'tishi. (yuborilgan_kunlar, skip_kunlar) qaytaradi."""
    now = datetime.now()
    ensure_indexes()  # idempotent — boot'da Mongo yotgan bo'lsa shu yerda yaratiladi
    db = local_db()
    trigger_col = db[config.COL_TRIGGER_DATA]

    clients = active_clients()
    if not clients:
        # Bu ham jimgina "muvaffaqiyat" bo'lib ketmasin: manba baza bo'sh
        # ro'yxat qaytarishi sozlama xatosi yoki nosozlik belgisi bo'lishi
        # mumkin, va u holda kunlar jimgina to'planmay qoladi.
        raise NoActiveClients("Active xodim topilmadi — o'tish bo'sh tugadi")

    conn = None
    try:
        conn = connect()
        channel = conn.channel()
        declare_queue(channel)
    except Exception as e:
        # Ilgari bu yerda (0, 0) qaytarilardi va o'tish `finished` deb
        # yozilardi — dashboardda yashil ✓ ko'rinib, aslida hech narsa
        # yuborilmagan bo'lardi. Nosozlik faqat konteyner logida qolardi.
        # Ma'lumot baribir yo'qolmaydi (hech narsa yozilmadi, cursor orqada
        # qoldi), lekin bu MUVAFFAQIYAT emas — yuqoriga uzatamiz.
        if conn is not None and conn.is_open:
            conn.close()
        raise QueueUnavailable(
            f"RabbitMQ ulanmadi, o'tish bekor qilindi (ma'lumot yo'qolmadi, "
            f"cursor orqada qoldi): {type(e).__name__}: {e}") from e

    sent_days = skipped_days = 0
    total_events = 0
    try:
        for client in clients:
            cid, hostname = client["clientId"], client["hostname"]
            full_name = client.get("fullName")
            try:
                window_start = _window_start(trigger_col, cid, now)

                day_stamps = collect_client_days(client, window_start)
                total_events += sum(len(v["stamps"]) for v in day_stamps.values())

                days_payload, day_docs = {}, []
                for date_str, kun in sorted(day_stamps.items()):
                    tss = kun["stamps"]
                    agg = build_day_agg(tss)
                    if agg is None:
                        continue
                    start, finish = agg
                    doc = build_day_doc(cid, hostname, date_str, start, finish, len(tss), now,
                                        full_name=full_name, active_min=kun["activeMin"])

                    # Dedup: allaqachon yuborilgan va o'zgarmagan kun qayta yuborilmaydi
                    existing = trigger_col.find_one(
                        {"clientId": cid, "date": date_str},
                        {"start": 1, "finish": 1, "eventCount": 1})
                    if existing and (existing.get("start") == doc["start"]
                                     and existing.get("finish") == doc["finish"]
                                     and existing.get("eventCount") == doc["eventCount"]):
                        skipped_days += 1
                        continue

                    days_payload[date_str] = {
                        "start": doc["start"],
                        "finish": doc["finish"],
                        "eventCount": doc["eventCount"],
                        "dayOfWeek": doc["dayOfWeek"],
                        "durationMin": doc["durationMin"],
                        "activeMin": doc["activeMin"],
                    }
                    day_docs.append(doc)

                if not days_payload:
                    continue

                job = {
                    "jobId": str(uuid.uuid4()),
                    "clientId": cid,
                    "hostname": hostname,
                    "fullName": full_name,
                    "windowStart": window_start.isoformat(timespec="seconds"),
                    "windowEnd": now.isoformat(timespec="seconds"),
                    "days": days_payload,
                    "sentAt": now.isoformat(timespec="seconds"),
                }

                # Avval publish — muvaffaqiyatli bo'lsagina trigger_data ga yozamiz
                publish(channel, job)
                for doc in day_docs:
                    trigger_col.update_one({"clientId": cid, "date": doc["date"]},
                                           {"$set": doc}, upsert=True)
                sent_days += len(day_docs)

                # Pruning: eski yuborilganlik yozuvlari
                trigger_col.delete_many(
                    {"clientId": cid,
                     "date": {"$lt": date_str_days_ago(now, config.DAYS_WINDOW)}})
            except Exception as e:
                log.error("%s client'ida xato (qolganlari davom etadi): %s", cid, e)
    finally:
        if conn is not None and conn.is_open:
            conn.close()

    # results retention: bir yildan eski natijalar saqlanmaydi
    db[config.COL_RESULTS].delete_many(
        {"date": {"$lt": date_str_days_ago(now, config.RESULTS_RETENTION_DAYS)}})

    log.info("trigger run: %d client, %d yangi event, %d kun yuborildi, %d kun skip (bir xil)",
             len(clients), total_events, sent_days, skipped_days)
    return sent_days, skipped_days
