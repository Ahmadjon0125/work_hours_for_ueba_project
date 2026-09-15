"""UEBA kirish nuqtasi: FastAPI + APScheduler (trigger) + worker thread'lar.

DIQQAT: faqat BITTA protsess sifatida ishga tushiriladi (`python main.py`).
uvicorn --workers rejimi ishlatilmaydi — aks holda scheduler va workerlar ko'payadi.
"""
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import uvicorn
from apscheduler.schedulers.background import BackgroundScheduler

import config
from api.app import create_app
from api.routes import _retrain_chain
from mq.worker import start_workers
from services import jobs, trigger
from services.mongo import check_time_alignment, ensure_indexes
from services.trainer import current_baseline_id
from utils.helpers import now as hozir
from utils.logger import get_logger

log = get_logger("main")

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
    except trigger.BaselineMissing as e:
        # Bu XATO emas: birinchi o'qitish hali tugamagan. "error" deb yozsak
        # dashboardda qizil ✕ va "Xatolar" tugmasi chiqib, birinchi daqiqalarda
        # bekorga vahima ko'tarardi.
        log.warning("Trigger o'tkazib yuborildi: %s", e)
        if run_id:
            jobs.trigger_finish(run_id, "skipped", error=str(e),
                                errorKod=type(e).__name__)
    except Exception as e:
        log.error("Trigger o'tishida xato: %s", e)
        if run_id:
            jobs.trigger_finish(run_id, "error", error=str(e),
                                errorKod=type(e).__name__)


def _bootstrap():
    """Birinchi ishga tushish: collector -> trainer -> trigger, SHU TARTIBDA.

    Nima uchun kerak: baseline yo'q bo'lsa trigger har kunni `insufficient`
    deb yozadi, va ular QAYTA BAHOLANMAYDI — `trigger_data` ga "yuborildi"
    deb belgilangani uchun keyingi o'tishlar ularni `skipped` qiladi. Ya'ni
    birinchi kunlar butunlay yo'qoladi.

    Ilgari buni odam qo'lda qilishi kerak edi (`collector.py`, keyin
    `trainer.py`). Qilmasa tizim ishlayotgandek ko'rinardi, lekin natijalar
    bo'sh bo'lardi — aynan shunday holat yuz berdi.

    Baseline allaqachon bo'lsa hech narsa qilmaydi.
    """
    try:
        if current_baseline_id() is not None:
            return
    except Exception as e:
        log.warning("Baseline bor-yo'qligini tekshirib bo'lmadi: %s", e)
        return

    log.info("Baseline topilmadi — birinchi o'qitish boshlanmoqda "
             "(collector -> trainer). Bu bir necha daqiqa olishi mumkin.")
    try:
        job_id = jobs.create("train")
    except jobs.JobAlreadyRunning:
        log.info("O'qitish allaqachon ketmoqda — bootstrap o'tkazib yuborildi")
        return
    except Exception as e:
        log.error("Birinchi o'qitishni boshlab bo'lmadi: %s", e)
        return

    _retrain_chain("train", job_id)          # xatolarni o'zi job'ga yozadi

    if current_baseline_id() is None:
        log.error("Birinchi o'qitish baseline bermadi — trigger kutadi. "
                  "Xatolar tarixiga qarang.")
        return
    log.info("Birinchi o'qitish tugadi — trigger ishga tushirilmoqda")
    _trigger_job()


def _ishga_tushirish():
    """Ishga tushish ilgagi: indekslar, tiklash, workerlar, bootstrap, scheduler."""
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

    # Birinchi ishga tushish zanjiri fon thread'ida: HTTP server kutmasin.
    threading.Thread(target=_bootstrap, name="bootstrap", daemon=True).start()

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


def _toxtatish():
    """To'xtash ilgagi: workerlarga signal, scheduler'ni yopish.

    `_stop_event` bo'lmasa worker thread'lar navbatdan o'qishda davom etadi
    va protsess `docker compose down` / `systemctl stop` da osilib qoladi.
    """
    _stop_event.set()
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
    log.info("To'xtatildi")


@asynccontextmanager
async def _lifespan(app):
    """Dastur hayotining boshi va oxiri — bitta joyda.

    `yield` dan OLDINGISI ishga tushganda, KEYINGISI to'xtaganda bajariladi.
    Ilgari bu ikkita alohida `@app.on_event(...)` edi; u FastAPI'da eskirgan.
    """
    _ishga_tushirish()
    try:
        yield
    finally:
        _toxtatish()


app = create_app(lifespan=_lifespan)


if __name__ == "__main__":
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT, log_level="warning")
