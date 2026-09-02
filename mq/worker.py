"""Worker thread: navbatdan job olib, processor orqali baholab results ga yozadi."""
import json
import threading
import time

import config
from mq.rabbitmq import connect, declare_queue, publish
from services.mongo import local_db
from services.processor import evaluate_job
from utils.logger import get_logger

log = get_logger("worker")


def _handle_job(body):
    """Bitta job'ni qayta ishlaydi: baseline -> z-score -> results upsert."""
    job = json.loads(body.decode("utf-8"))
    db = local_db()

    baseline_doc = db[config.COL_BASELINE].find_one({"clientId": job["clientId"]})
    if baseline_doc is None:
        log.warning("%s uchun baseline yo'q — kunlar 'insufficient' sifatida yoziladi",
                    job["clientId"])

    results = db[config.COL_RESULTS]
    for doc in evaluate_job(job, baseline_doc):
        results.update_one({"clientId": doc["clientId"], "date": doc["date"]},
                           {"$set": doc}, upsert=True)
    return len(job.get("days") or {})


def _consume_forever(worker_id, stop_event):
    """Bitta worker thread'ining asosiy sikli (uzilsa qayta ulanadi)."""
    while not stop_event.is_set():
        conn = None
        try:
            conn = connect()
            channel = conn.channel()
            declare_queue(channel)
            channel.basic_qos(prefetch_count=1)
            log.info("Worker %d navbatga ulandi", worker_id)

            for method, properties, body in channel.consume(config.QUEUE_NAME, inactivity_timeout=1):
                if stop_event.is_set():
                    break
                if method is None:
                    continue  # bo'sh navbat — stop_event ni tekshirib davom etamiz

                headers = (properties.headers or {}) if properties else {}
                retries = int(headers.get("x-retries", 0))
                try:
                    days = _handle_job(body)
                    channel.basic_ack(method.delivery_tag)
                    log.info("Worker %d: job bajarildi (%d kun)", worker_id, days)
                except json.JSONDecodeError as e:
                    log.error("Worker %d: buzuq job JSON, tashlandi: %s", worker_id, e)
                    channel.basic_nack(method.delivery_tag, requeue=False)
                except Exception as e:
                    if retries < config.MAX_RETRIES:
                        log.warning("Worker %d: xato (%s), qayta urinish %d/%d",
                                    worker_id, e, retries + 1, config.MAX_RETRIES)
                        try:
                            publish(channel, json.loads(body.decode("utf-8")), retries=retries + 1)
                        except Exception as re:
                            log.error("Worker %d: qayta publish xatosi: %s", worker_id, re)
                    else:
                        log.error("Worker %d: %d marta urinildi, job tashlandi: %s. "
                                  "Kerak bo'lsa trigger_data dagi yozuvni o'chirib qayta yuboring.",
                                  worker_id, retries, e)
                    channel.basic_reject(method.delivery_tag, requeue=False)
        except Exception as e:
            if not stop_event.is_set():
                log.error("Worker %d ulanish xatosi, 5s dan keyin qayta: %s: %s",
                          worker_id, type(e).__name__, e)
                time.sleep(5)
        finally:
            try:
                if conn is not None and conn.is_open:
                    conn.close()
            except Exception:
                pass


def start_workers(stop_event):
    """WORKER_COUNT ta daemon thread ishga tushiradi (har biri o'z connection'i bilan)."""
    threads = []
    for i in range(1, config.WORKER_COUNT + 1):
        t = threading.Thread(target=_consume_forever, args=(i, stop_event),
                             name=f"worker-{i}", daemon=True)
        t.start()
        threads.append(t)
    log.info("%d ta worker ishga tushdi", len(threads))
    return threads
