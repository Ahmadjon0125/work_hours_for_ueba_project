"""UEBA kirish nuqtasi: FastAPI + APScheduler (trigger) + worker thread'lar.

DIQQAT: faqat BITTA protsess sifatida ishga tushiriladi (`python main.py`).
uvicorn --workers rejimi ishlatilmaydi — aks holda scheduler va workerlar ko'payadi.
"""
import threading
from datetime import datetime, timedelta

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler

import config
from api.app import create_app
from api.routes import set_trigger_state
from mq.worker import start_workers
from services import trigger
from services.mongo import ensure_indexes
from utils.logger import get_logger

log = get_logger("main")
app = create_app()

_stop_event = threading.Event()
_scheduler = None


def _trigger_job():
    """Rejalashtirilgan trigger o'tishi (faqat avtomatik — API orqali chaqirilmaydi)."""
    started = datetime.now()
    set_trigger_state(status="running", startedAt=started.isoformat(timespec="seconds"))
    try:
        sent, skipped = trigger.run()
        set_trigger_state(status="finished", sent=sent, skipped=skipped,
                          startedAt=started.isoformat(timespec="seconds"),
                          finishedAt=datetime.now().isoformat(timespec="seconds"))
    except Exception as e:
        log.error("Trigger o'tishida xato: %s", e)
        set_trigger_state(status="error", error=str(e),
                          startedAt=started.isoformat(timespec="seconds"),
                          finishedAt=datetime.now().isoformat(timespec="seconds"))


@app.on_event("startup")
def _startup():
    global _scheduler
    try:
        ensure_indexes()
    except Exception as e:
        # Mongo hozir yotgan bo'lsa ham dastur ko'tariladi: /api/health xatoni ko'rsatadi,
        # indekslar keyingi trigger o'tishida yaratiladi.
        log.error("Indekslarni yaratib bo'lmadi (Mongo yotgan?): %s", e)
    start_workers(_stop_event)

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(_trigger_job, "interval", hours=config.TRIGGER_INTERVAL_HOURS,
                       id="trigger", max_instances=1, coalesce=True,
                       next_run_time=datetime.now() + timedelta(seconds=10))
    _scheduler.start()
    log.info("Scheduler ishga tushdi: har %g soatda trigger (birinchi o'tish 10s dan keyin)",
             config.TRIGGER_INTERVAL_HOURS)


@app.on_event("shutdown")
def _shutdown():
    _stop_event.set()
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
    log.info("To'xtatildi")


if __name__ == "__main__":
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, log_level="warning")
