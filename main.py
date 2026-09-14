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
from mq.worker import start_workers
from services import jobs, trigger
from services.mongo import check_time_alignment, ensure_indexes
from utils.helpers import now as hozir
from utils.logger import get_logger

log = get_logger("main")
app = create_app()

_stop_event = threading.Event()
_scheduler = None


def _trigger_job():
    """Rejalashtirilgan trigger o'tishi (faqat avtomatik — API orqali chaqirilmaydi).

    Holat `trigger_runs` collection'iga yoziladi: dastur qayta ishga tushsa ham
    tarix qoladi va tunda bo'lgan xato ertalab ko'rinadi.
    """
    try:
        run_id = jobs.trigger_start()
    except Exception as e:
        # Mongo yotgan bo'lsa ham trigger'ni urinib ko'ramiz — hisobotsiz
        log.error("Trigger o'tishini qayd qilib bo'lmadi: %s", e)
        run_id = None
    try:
        sent, skipped = trigger.run()
        if run_id:
            jobs.trigger_finish(run_id, "finished", sent=sent, skipped=skipped)
    except Exception as e:
        log.error("Trigger o'tishida xato: %s", e)
        if run_id:
            jobs.trigger_finish(run_id, "error", error=str(e),
                                errorKod=type(e).__name__)


@app.on_event("startup")
def _startup():
    global _scheduler
    try:
        ensure_indexes()
        # Protsess job o'rtasida to'xtagan bo'lsa, hujjat "running" holicha qolib
        # keyingi barcha o'qitishlarni bloklab qo'yardi (ARCH-01).
        jobs.recover_stale()
        jobs.trigger_recover_stale()
    except Exception as e:
        # Mongo hozir yotgan bo'lsa ham dastur ko'tariladi: /api/health xatoni ko'rsatadi,
        # indekslar keyingi trigger o'tishida yaratiladi.
        log.error("Indekslarni yaratib bo'lmadi (Mongo yotgan?): %s", e)
    # Vaqt mintaqasi mosligini ishga tushishdayoq tekshiramiz: noto'g'ri TZ
    # xato tashlamaydi, jimgina noto'g'ri natija beradi.
    try:
        holat, xabar = check_time_alignment()
        (log.error if holat == "xato" else
         log.warning if holat in ("ogohlantirish", "nomalum") else log.info)(
            "Vaqt tekshiruvi [%s]: %s", holat, xabar)
    except Exception as e:
        log.warning("Vaqt tekshiruvi bajarilmadi: %s", e)

    start_workers(_stop_event)

    # Scheduler ham AYNAN shu mintaqada ishlashi kerak: `next_run_time` ga
    # naive vaqt beriladi, APScheduler esa uni o'z mintaqasida talqin qiladi.
    # Mos bo'lmasa birinchi o'tish soatlab siljib ketardi.
    _scheduler = BackgroundScheduler(timezone=config.TIMEZONE) if config.TIMEZONE \
        else BackgroundScheduler()
    _scheduler.add_job(_trigger_job, "interval", hours=config.TRIGGER_INTERVAL_HOURS,
                       id="trigger", max_instances=1, coalesce=True,
                       next_run_time=hozir() + timedelta(seconds=10))
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
