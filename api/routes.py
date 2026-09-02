"""FastAPI endpoint'lari."""
import os
import threading
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

import config
from mq.rabbitmq import queue_depth
from services.collector import collect
from services.mongo import local_db, main_db
from services.trainer import train
from utils.logger import get_logger

log = get_logger("api")
router = APIRouter()

DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard")

# Fon amallarining holati (/api/health da ko'rinadi)
_state = {
    "lastTrigger": {"status": "idle"},
    "lastRetrain": {"status": "idle"},
}
_retrain_lock = threading.Lock()


def set_trigger_state(**kwargs):
    _state["lastTrigger"] = {**kwargs}


def get_state():
    return _state


def _retrain_chain(mode):
    """collector -> trainer zanjiri (fon thread'ida). Baseline swap'gacha eskisi ishlaydi."""
    try:
        _state["lastRetrain"] = {"status": "running", "stage": "collecting", "mode": mode,
                                 "startedAt": datetime.now().isoformat(timespec="seconds")}
        days = collect()

        _state["lastRetrain"] = {**_state["lastRetrain"], "stage": "training", "days": days}
        clients = train()

        _state["lastRetrain"] = {**_state["lastRetrain"], "status": "finished",
                                 "stage": "finished", "clients": clients,
                                 "finishedAt": datetime.now().isoformat(timespec="seconds")}
        log.info("%s zanjiri tugadi: %d kun, %d client", mode, days, clients)
    except Exception as e:
        log.error("%s zanjirida xato: %s", mode, e)
        _state["lastRetrain"] = {**_state["lastRetrain"], "status": "error",
                                 "stage": "error", "error": str(e),
                                 "finishedAt": datetime.now().isoformat(timespec="seconds")}
    finally:
        _retrain_lock.release()


def _start_chain(mode):
    if not _retrain_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="retrain davom etmoqda")
    threading.Thread(target=_retrain_chain, args=(mode,), daemon=True).start()


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
        "lastTrigger": _state["lastTrigger"],
        "lastRetrain": _state["lastRetrain"],
    }


@router.post("/api/train", status_code=202)
def train_endpoint():
    """Birinchi o'qitish: collector -> trainer."""
    if local_db()[config.COL_BASELINE].count_documents({}, limit=1):
        raise HTTPException(status_code=409, detail="baseline mavjud, /api/retrain ishlatiling")
    _start_chain("train")
    return {"status": "training"}


@router.post("/api/retrain", status_code=202)
def retrain_endpoint():
    """Baseline yangilash: collector (yangi 60 kun) -> trainer (tmp + atomik swap)."""
    _start_chain("retrain")
    return {"status": "retraining"}


@router.get("/api/clients")
def clients():
    """Dashboard dropdown'i uchun: results dagi client'lar (hostname bilan)."""
    pipeline = [
        {"$group": {"_id": "$clientId", "hostname": {"$last": "$hostname"}}},
        {"$sort": {"hostname": 1}},
    ]
    return [{"clientId": doc["_id"], "hostname": doc.get("hostname") or doc["_id"]}
            for doc in local_db()[config.COL_RESULTS].aggregate(pipeline)]


@router.get("/api/baseline")
def baseline():
    """Har client uchun o'rganilgan jadval — dashboard "odatda qachon keladi" ni shundan oladi."""
    return list(local_db()[config.COL_BASELINE].find(
        {}, {"_id": 0, "clientId": 1, "hostname": 1, "weeks": 1, "trainedAt": 1}))


def _query_results(date_from, date_to, client_id, status, limit, offset):
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
            limit: int = Query(100, ge=1, le=5000),
            offset: int = Query(0, ge=0)):
    return _query_results(date_from, date_to, client_id, status, limit, offset)


@router.get("/api/results/{client_id}")
def results_for_client(client_id: str,
                       date_from: str = Query(None, alias="from"),
                       date_to: str = Query(None, alias="to"),
                       status: str = None,
                       limit: int = Query(100, ge=1, le=5000),
                       offset: int = Query(0, ge=0)):
    if not local_db()[config.COL_RESULTS].count_documents({"clientId": client_id}, limit=1):
        raise HTTPException(status_code=404, detail="client topilmadi")
    return _query_results(date_from, date_to, client_id, status, limit, offset)


@router.get("/api/dashboard", include_in_schema=False)
@router.get("/", include_in_schema=False)
def dashboard():
    return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))
