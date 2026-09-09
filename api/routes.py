"""FastAPI endpoint'lari."""
import os
import threading
from collections import Counter, defaultdict
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

import config
from mq.rabbitmq import queue_depth
from services import jobs
from services.collector import collect
from services.mongo import active_clients, local_db, main_db
from services.trainer import current_baseline_id, train
from utils.helpers import date_str_days_ago
from utils.logger import get_logger

log = get_logger("api")
router = APIRouter()

DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard")

# Trigger holati — hozircha xotirada (u job emas, har 5 soatlik avtomatik o'tish)
_state = {"lastTrigger": {"status": "idle"}}


def set_trigger_state(**kwargs):
    _state["lastTrigger"] = {**kwargs}


def get_state():
    return _state


def _retrain_chain(mode, job_id):
    """collector -> trainer zanjiri (fon thread'ida). Bosqichlar job hujjatiga yoziladi."""
    try:
        jobs.set_stage(job_id, "collecting")
        collected = collect()
        days, failed = collected["days"], collected["failed"]

        jobs.set_stage(job_id, "training",
                       **{"stats.days": days, "stats.clientsRead": collected["clients"]})
        # Muvaffaqiyatsiz clientlar bo'lsa ham o'qitamiz: qolganlarining ma'lumoti
        # to'liq, o'tkazib yuborilganlarniki esa eski (to'g'ri) holicha turibdi.
        clients = train()

        # Bironta client tushib qolgan bo'lsa "hammasi joyida" deb ko'rsatilmaydi
        status = "partial" if failed else "finished"
        jobs.finish(job_id, status,
                    baselineId=current_baseline_id(),
                    **{"stats.clients": clients,
                       "stats.failedClients": [{"hostname": f["hostname"],
                                                "error": f["error"]} for f in failed]})
        if failed:
            log.error("%s zanjiri qisman bajarildi: %d kun, %d client o'qitildi, "
                      "%d client o'tkazib yuborildi", mode, days, clients, len(failed))
        else:
            log.info("%s zanjiri tugadi: %d kun, %d client", mode, days, clients)
    except Exception as e:
        log.error("%s zanjirida xato: %s", mode, e)
        jobs.finish(job_id, "error", error=str(e))


def _start_chain(mode):
    """Job ochib fon thread'ini yuboradi. Band bo'lsa 409."""
    try:
        job_id = jobs.create(mode)
    except jobs.JobAlreadyRunning:
        raise HTTPException(status_code=409, detail="retrain davom etmoqda")
    threading.Thread(target=_retrain_chain, args=(mode, job_id), daemon=True).start()
    return job_id


@router.get("/api/health")
def health():
    def ping(fn):
        try:
            fn()
            return "ok"
        except Exception:
            return "error"

    depth = queue_depth()
    return {
        "mongo_main": ping(lambda: main_db().command("ping")),
        "mongo_local": ping(lambda: local_db().command("ping")),
        "rabbitmq": "ok" if depth is not None else "error",
        "queue_depth": depth,
        "workers": config.WORKER_COUNT,
        # Dashboard grafigi shu chegara bo'yicha yo'lak chizadi va nuqtalarni
        # bo'yaydi — kodda qattiq yozilmasin, aks holda .env bilan uzilib qoladi.
        "anomalyZThreshold": config.ANOMALY_Z_THRESHOLD,
        # Dashboard qattiq yozilgan raqam ishlatmasin — hammasi shu yerdan
        "minDowSamples": config.MIN_DOW_SAMPLES,
        "severity": {"high": config.SEVERITY_HIGH,
                     "medium": config.SEVERITY_MEDIUM,
                     "low": config.SEVERITY_LOW},
        "dashboard": {"rangeDays": config.DASHBOARD_RANGE_DAYS,
                      "maxIssues": config.DASHBOARD_MAX_ISSUES},
        "lastTrigger": _state["lastTrigger"],
        # Eski shakl saqlanadi — hozirgi dashboard shundan o'qiydi
        "lastRetrain": _job_as_state(jobs.latest()),
    }


def _job_as_state(job):
    """Job hujjatini eski `lastRetrain` shakliga keltiradi (dashboard buzilmasin)."""
    if not job:
        return {"status": "idle"}
    stats = job.get("stats") or {}
    return {
        "jobId": job["_id"],
        "mode": job.get("type"),
        "status": job.get("status"),
        "stage": job.get("stage"),
        "startedAt": job.get("startedAt"),
        "finishedAt": job.get("finishedAt"),
        "days": stats.get("days"),
        "clients": stats.get("clients"),
        "failedClients": stats.get("failedClients", []),
        "baselineId": job.get("baselineId"),
        "error": job.get("error"),
    }


@router.post("/api/train", status_code=202)
def train_endpoint():
    """Birinchi o'qitish: collector -> trainer."""
    if local_db()[config.COL_BASELINE].count_documents({}, limit=1):
        raise HTTPException(status_code=409, detail="baseline mavjud, /api/retrain ishlatiling")
    return {"status": "training", "jobId": _start_chain("train")}


@router.post("/api/retrain", status_code=202)
def retrain_endpoint():
    """Baseline yangilash: collector (yangi 60 kun) -> trainer (yangi versiya)."""
    return {"status": "retraining", "jobId": _start_chain("retrain")}


@router.get("/api/jobs")
def list_jobs(limit: int = Query(20, ge=1, le=config.API_PAGE_MAX)):
    """O'qitish job'lari tarixi — yangisi birinchi."""
    return jobs.recent(limit)


@router.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    """Bitta job'ning holati — UI bosqichni shundan kuzatadi."""
    job = local_db()[config.COL_TRAINING_JOBS].find_one({"_id": job_id})
    if job is None:
        raise HTTPException(status_code=404, detail="job topilmadi")
    return job


@router.get("/api/clients")
def clients():
    """Dashboard dropdown'i uchun xodimlar ro'yxati.

    Ro'yxat `results` dan quriladi (tarix), shuning uchun unda asosiy DLP tizimidan
    keyinchalik o'chirilgan client'lar ham uchraydi. Ikkita holat alohida belgilanadi:
      - bir nechta clientId bir xil hostname bilan  -> nomga qisqa id qo'shiladi;
      - client asosiy `clients` da endi yo'q        -> "o'chirilgan" deb belgilanadi.
    """
    rows = list(local_db()[config.COL_RESULTS].aggregate([
        {"$group": {"_id": "$clientId",
                    "hostname": {"$last": "$hostname"},
                    "fullName": {"$last": "$fullName"},
                    "days": {"$sum": 1},
                    "lastDate": {"$max": "$date"}}},
    ]))

    # Asosiy bazadagi tirik client'lar: ism va hostname shu yerdan olinadi (eng yangi manba).
    # Baza yotgan bo'lsa belgilamaymiz va results dagi qiymatlar bilan cheklanamiz.
    try:
        live = {}
        for c in active_clients():
            live[c["clientId"]] = c
    except Exception:
        live = None

    # Ko'rsatiladigan nom: ism bo'lsa ism, bo'lmasa hostname
    def shown(cid, r):
        cur = (live or {}).get(cid) or {}
        host = cur.get("hostname") or r.get("hostname") or cid
        name = cur.get("fullName") or r.get("fullName")
        return host, name, (name or host)

    seen = Counter(shown(r["_id"], r)[2] for r in rows)

    out = []
    for r in rows:
        cid = r["_id"]
        hostname, full_name, label = shown(cid, r)
        # Bir xil nomli bir nechta yozuv bo'lsa — ajratib ko'rsatamiz
        if seen[label] > 1:
            label += f" ({cid[-7:]})"
        stale = live is not None and cid not in live
        if stale:
            label += " — o'chirilgan"
        out.append({"clientId": cid, "hostname": hostname, "fullName": full_name,
                    "label": label,
                    "days": r["days"], "lastDate": r.get("lastDate"), "stale": stale})

    # Mavjudlari birinchi, keyin hostname bo'yicha
    out.sort(key=lambda c: (c["stale"], c["label"].lower()))
    return out


def build_risk_summary(rows, date_to=None):
    """`results` qatorlaridan xodimlar kesimini quradi. DB'ga tegmaydi — sinash oson.

    `rows` sana bo'yicha O'SISH tartibida bo'lishi kutiladi (kumulyativ chiziq
    uchun muhim).
    """
    if not rows:
        return []

    # Oxirgi davr chegarasi HAMMA xodim uchun bitta bo'lishi kerak, aks holda
    # kimningdir "oxirgi 7 kuni" boshqasinikidan boshqa oraliqqa tushib qolardi.
    oxirgi_sana = date_to or max(r["date"] for r in rows)
    kesim = date_str_days_ago(datetime.strptime(oxirgi_sana, "%Y-%m-%d"),
                              config.RISK_RECENT_DAYS)

    per = defaultdict(lambda: {"hostname": None, "fullName": None, "kunlar": [],
                               "overall": 0, "recent": 0, "anomaly": 0})
    for r in rows:
        p = per[r["clientId"]]
        p["hostname"] = r.get("hostname") or p["hostname"]
        p["fullName"] = r.get("fullName") or p["fullName"]
        risk = r.get("riskScore")
        if risk is None:          # baholanmagan kun — xavfga qo'shilmaydi
            continue
        p["kunlar"].append(risk)
        p["overall"] += risk
        if r["date"] > kesim:
            p["recent"] += risk
        if r.get("isAnomaly"):
            p["anomaly"] += 1

    def daraja(recent):
        if recent >= config.RISK_LEVEL_HIGH:
            return "high"
        if recent >= config.RISK_LEVEL_MEDIUM:
            return "medium"
        return "low"

    out = []
    for cid, p in per.items():
        if not p["kunlar"]:
            continue
        # Sparkline — kumulyativ yig'indi, oxirgi RISK_TREND_POINTS nuqta
        trend, yigindi = [], 0
        for risk in p["kunlar"]:
            yigindi += risk
            trend.append(yigindi)
        out.append({
            "clientId": cid,
            "hostname": p["hostname"] or cid,
            "fullName": p["fullName"],
            "overallRisk": p["overall"],
            "recentRisk": p["recent"],
            "evaluatedDays": len(p["kunlar"]),
            "anomalyDays": p["anomaly"],
            "trend": trend[-config.RISK_TREND_POINTS:],
            "level": daraja(p["recent"]),
        })

    out.sort(key=lambda x: (-x["overallRisk"], -x["recentRisk"]))
    return out


@router.get("/api/risk-summary")
def risk_summary(date_from: str = Query(None, alias="from"),
                 date_to: str = Query(None, alias="to")):
    """Kuzatuvdagi xodimlar: to'plangan xavf, oxirgi davr xavfi va tendensiya.

    Nima uchun alohida endpoint: `/api/results` bitta xodim tanlanganda faqat
    o'shaning kunlarini qaytaradi, bu jadval esa HAR DOIM barcha xodimlarni
    talab qiladi.

    Ustunlar:
      overallRisk  — oraliqdagi `riskScore` yig'indisi (to'plangan xavf)
      recentRisk   — oxirgi RISK_RECENT_DAYS kunlik yig'indi
      trend        — kumulyativ yig'indi nuqtalari (sparkline uchun)
      level        — belgi rangi: high | medium | low

    Baholanmagan kunlar (`riskScore: null`) hisobga olinmaydi.
    """
    query = {}
    if date_from or date_to:
        query["date"] = {}
        if date_from:
            query["date"]["$gte"] = date_from
        if date_to:
            query["date"]["$lte"] = date_to

    rows = list(local_db()[config.COL_RESULTS]
                .find(query, {"_id": 0, "clientId": 1, "hostname": 1, "fullName": 1,
                              "date": 1, "riskScore": 1, "isAnomaly": 1})
                .sort("date", 1))
    return build_risk_summary(rows, date_to)


@router.get("/api/baseline")
def baseline():
    """JORIY baseline versiyasi — dashboard haftalik rejim grafigini shundan chizadi."""
    db = local_db()
    bid = current_baseline_id(db)
    if bid is None:
        return []
    return list(db[config.COL_BASELINE].find(
        {"baselineId": bid},
        {"_id": 0, "baselineId": 0}))


@router.get("/api/baseline/versions")
def baseline_versions():
    """Saqlangan baseline versiyalari (eng yangisi birinchi)."""
    return [{**r, "baselineId": r.pop("_id")}
            for r in local_db()[config.COL_BASELINE_RUNS]
            .find({}).sort("trainedAt", -1)]


def _query_results(date_from, date_to, client_id, status, limit, offset,
                   is_anomaly=None, min_risk=None, trigger=None):
    query = {}
    if date_from or date_to:
        query["date"] = {}
        if date_from:
            query["date"]["$gte"] = date_from
        if date_to:
            query["date"]["$lte"] = date_to
    if client_id:
        query["clientId"] = client_id
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if statuses:
            query["status"] = {"$in": statuses}
    if is_anomaly is not None:
        # Diqqat: eski (backfill qilinmagan) hujjatlarda `isAnomaly` maydoni
        # umuman yo'q — ular bu filtrga tushmaydi.
        query["isAnomaly"] = is_anomaly
    if min_risk is not None:
        query["riskScore"] = {"$gte": min_risk}
    if trigger:
        names = [t.strip() for t in trigger.split(",") if t.strip()]
        if names:
            query["triggeredDetectors"] = {"$in": names}

    col = local_db()[config.COL_RESULTS]
    total = col.count_documents(query)
    items = list(col.find(query, {"_id": 0})
                 .sort([("date", -1), ("hostname", 1)])
                 .skip(offset).limit(limit))
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/api/results")
def results(date_from: str = Query(None, alias="from"),
            date_to: str = Query(None, alias="to"),
            client_id: str = None,
            status: str = None,
            is_anomaly: bool = None,
            min_risk: int = Query(None, ge=0, le=100),
            trigger: str = None,
            limit: int = Query(config.API_PAGE_SIZE, ge=1, le=config.API_PAGE_MAX),
            offset: int = Query(0, ge=0)):
    return _query_results(date_from, date_to, client_id, status, limit, offset,
                          is_anomaly, min_risk, trigger)


@router.get("/api/results/{client_id}")
def results_for_client(client_id: str,
                       date_from: str = Query(None, alias="from"),
                       date_to: str = Query(None, alias="to"),
                       status: str = None,
                       is_anomaly: bool = None,
                       min_risk: int = Query(None, ge=0, le=100),
                       trigger: str = None,
                       limit: int = Query(config.API_PAGE_SIZE, ge=1, le=config.API_PAGE_MAX),
                       offset: int = Query(0, ge=0)):
    if not local_db()[config.COL_RESULTS].count_documents({"clientId": client_id}, limit=1):
        raise HTTPException(status_code=404, detail="client topilmadi")
    return _query_results(date_from, date_to, client_id, status, limit, offset,
                          is_anomaly, min_risk, trigger)


@router.get("/api/dashboard", include_in_schema=False)
@router.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))
