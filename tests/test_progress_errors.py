"""Jarayon ko'rsatkichi va xatolar tarixi sinovlari.

Ishga tushirish:  python tests/test_progress_errors.py
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import services.collector as collector_mod
import services.jobs as jobs_mod
import services.workday as workday_mod
import api.routes as routes_mod
from api.routes import build_error_log


def _check(label, condition, detail=""):
    print(f"    {'✓' if condition else '✗'} {label}{'' if condition else '  <- ' + detail}")
    return condition


# --- Xatolar tarixi ---------------------------------------------------

def test_zanjir_xatosi():
    print("  Butun zanjir yiqilsa xato ro'yxatga tushadi")
    joblar = [{"type": "retrain", "startedAt": "2026-09-09T10:00:00",
               "finishedAt": "2026-09-09T10:00:05", "error": "Mongo javob bermadi"}]
    out = build_error_log(joblar, [])
    return (_check("1 ta yozuv", len(out) == 1, str(len(out)))
            & _check("manba retrain", out[0]["manba"] == "retrain")
            & _check("kontekst ko'rsatilgan", out[0]["kontekst"] == "zanjir to'xtadi")
            & _check("xato matni", out[0]["xato"] == "Mongo javob bermadi"))


def test_xodim_darajasidagi_xato():
    print("  Zanjir tugagan bo'lsa ham xodim xatolari saqlanadi")
    joblar = [{"type": "retrain", "status": "partial", "error": None,
               "startedAt": "2026-09-09T10:00:00",
               "errors": [{"at": "2026-09-09T10:00:02", "context": "collector · pc-1",
                           "error": "tarmoq uzildi"},
                          {"at": "2026-09-09T10:00:03", "context": "collector · pc-2",
                           "error": "timeout"}]}]
    out = build_error_log(joblar, [])
    return (_check("2 ta yozuv", len(out) == 2, str(len(out)))
            & _check("kontekstda xodim nomi", "pc-" in out[0]["kontekst"], out[0]["kontekst"]))


def test_takroriy_xato_bir_marta():
    """Zanjir xatosi `error` va `errors[]` da ikkalasida ham bo'ladi."""
    print("  Bitta xato ikki qator bo'lib chiqmaydi")
    joblar = [{"type": "retrain", "startedAt": "2026-09-09T10:00:00",
               "finishedAt": "2026-09-09T10:00:05",
               "error": "Mongo javob bermadi: timeout 10s",
               "errors": [{"at": "2026-09-09T10:00:04", "context": "retrain zanjiri",
                           "error": "Mongo javob bermadi: timeout 10s"}]}]
    out = build_error_log(joblar, [])
    return (_check("1 ta yozuv (2 emas)", len(out) == 1, str(len(out)))
            & _check("kontekstli varianti qoldi", out[0]["kontekst"] == "retrain zanjiri",
                     out[0]["kontekst"]))


def test_uzun_xato_qisqartiriladi():
    print("  Juda uzun xato matni qisqartiriladi")
    uzun = "x" * 900
    out = build_error_log([{"type": "retrain", "finishedAt": "2026-09-09T10:00:00",
                            "error": uzun}], [])
    return _check("300 belgidan uzun emas", len(out[0]["xato"]) <= 300, str(len(out[0]["xato"])))


def test_trigger_xatosi():
    print("  Trigger o'tishidagi xato ham ro'yxatga tushadi")
    o_tishlar = [{"startedAt": "2026-09-09T12:00:00", "finishedAt": "2026-09-09T12:00:01",
                  "error": "RabbitMQ ulanmadi"}]
    out = build_error_log([], o_tishlar)
    return (_check("1 ta yozuv", len(out) == 1)
            & _check("manba trigger", out[0]["manba"] == "trigger", out[0]["manba"]))


def test_ikkala_manba_vaqt_boyicha():
    print("  Ikkala manba birlashadi va vaqt bo'yicha saralanadi")
    joblar = [{"type": "retrain", "finishedAt": "2026-09-09T10:00:00", "error": "eski"}]
    o_tishlar = [{"finishedAt": "2026-09-09T15:00:00", "error": "yangi"}]
    out = build_error_log(joblar, o_tishlar)
    return (_check("2 ta yozuv", len(out) == 2)
            & _check("yangisi birinchi", out[0]["xato"] == "yangi", out[0]["xato"])
            & _check("eskisi ikkinchi", out[1]["xato"] == "eski"))


def test_xatosiz_holat():
    print("  Xato bo'lmasa ro'yxat bo'sh")
    joblar = [{"type": "retrain", "status": "finished", "error": None, "errors": []}]
    o_tishlar = [{"status": "finished", "error": None}]
    return _check("bo'sh ro'yxat", build_error_log(joblar, o_tishlar) == [])


def test_limit():
    print("  Limit qo'llanadi")
    joblar = [{"type": "retrain", "finishedAt": f"2026-09-{i:02d}T10:00:00",
               "error": f"xato-{i}"} for i in range(1, 21)]
    out = build_error_log(joblar, [], limit=5)
    return (_check("5 ta yozuv", len(out) == 5, str(len(out)))
            & _check("eng yangisi birinchi", out[0]["xato"] == "xato-20", out[0]["xato"]))


# --- Jarayon ko'rsatkichi ---------------------------------------------

class _FakeColl:
    def __init__(self):
        self.docs = []

    def update_one(self, flt, update, upsert=False):
        self.docs.append({**flt, **update.get("$set", {})})

    def delete_many(self, flt):
        class R:
            deleted_count = 0
        return R()

    def find_one(self, flt):
        return None


class _FakeDB:
    def __init__(self, coll):
        self.coll = coll

    def __getitem__(self, name):
        return self.coll


def test_collector_jarayonni_xabar_qiladi():
    print("  Collector har xodimdan keyin jarayonni xabar qiladi")
    xodimlar = [{"clientId": f"C{i}", "hostname": f"pc-{i}", "fullName": None, "_id": f"C{i}"}
                for i in range(1, 5)]
    base = datetime.now() - timedelta(days=3)

    def manba(client, ws, we=None):
        yield "agentsessionstatuses", [(base.replace(hour=9), "LOGON"),
                                      (base.replace(hour=17), "LOGOFF")]

    qadamlar = []
    asl_source = workday_mod.iter_client_sessions
    asl_idx, asl_cl, asl_db = (collector_mod.ensure_indexes,
                               collector_mod.active_clients, collector_mod.local_db)
    try:
        workday_mod.iter_client_sessions = manba
        collector_mod.ensure_indexes = lambda: None
        collector_mod.active_clients = lambda: xodimlar
        collector_mod.local_db = lambda: _FakeDB(_FakeColl())
        collector_mod.collect(on_progress=lambda foiz, matn: qadamlar.append((foiz, matn)))
    finally:
        workday_mod.iter_client_sessions = asl_source
        collector_mod.ensure_indexes, collector_mod.active_clients, collector_mod.local_db = (
            asl_idx, asl_cl, asl_db)

    foizlar = [q[0] for q in qadamlar]
    return (_check("har xodim uchun bitta xabar", len(qadamlar) == 4, str(len(qadamlar)))
            & _check("foiz o'sib boradi", foizlar == sorted(foizlar), str(foizlar))
            & _check("oxirgisi 100", foizlar[-1] == 100, str(foizlar))
            & _check("matnda xodim soni bor", "4" in qadamlar[-1][1], qadamlar[-1][1]))


# --- Har bosqichning alohida foizi ---------------------------------------
#
# Dashboard collector va trainer uchun IKKITA alohida chiziq chizadi, shuning
# uchun ularning foizlari bir-birining ustiga yozilmasligi shart.

class _YozuvchiColl:
    """update_one'ni yig'ib boradigan soxta collection."""

    def __init__(self):
        self.yozuvlar = []

    def update_one(self, filtr, update):
        self.yozuvlar.append(update["$set"])


def _soxta_baza(coll):
    return lambda: {config.COL_TRAINING_JOBS: coll}


def test_har_bosqich_oz_foizini_yozadi():
    print("  collector va trainer foizlari alohida saqlanadi")
    coll = _YozuvchiColl()
    asl = jobs_mod.local_db
    try:
        jobs_mod.local_db = _soxta_baza(coll)
        jobs_mod.set_progress("job-1", 40, "4/10 xodim", stage="collecting")
        jobs_mod.set_progress("job-1", 20, "1/5 xodim", stage="training")
    finally:
        jobs_mod.local_db = asl
    c, t = coll.yozuvlar
    return (_check("collector o'z kalitiga yozdi",
                   c.get("stageProgress.collecting.percent") == 40, str(c))
            & _check("trainer boshqa kalitga yozdi",
                     t.get("stageProgress.training.percent") == 20, str(t))
            & _check("trainer collector foizini o'chirmadi",
                     "stageProgress.collecting.percent" not in t, str(t))
            & _check("matn ham bosqich ostida", c.get("stageProgress.collecting.text")
                     == "4/10 xodim", str(c)))


def test_set_stage_faqat_oz_bosqichini_nollaydi():
    print("  Yangi bosqich boshlansa oldingisining chizig'i tegilmaydi")
    coll = _YozuvchiColl()
    asl = jobs_mod.local_db
    try:
        jobs_mod.local_db = _soxta_baza(coll)
        jobs_mod.set_stage("job-1", "training", progressText="o'qitilmoqda")
    finally:
        jobs_mod.local_db = asl
    u = coll.yozuvlar[0]
    return (_check("yangi bosqich 0 dan boshlaydi",
                   u.get("stageProgress.training.percent") == 0, str(u))
            & _check("holati running", u.get("stageProgress.training.status") == "running",
                     str(u))
            & _check("matni ko'chirildi",
                     u.get("stageProgress.training.text") == "o'qitilmoqda", str(u))
            & _check("collector yozuviga tegilmadi",
                     not any(k.startswith("stageProgress.collecting") for k in u), str(u)))


def test_finish_stage_100_ga_toldiradi():
    print("  Bosqich yakunlansa chizig'i 100% da yashil bo'lib qoladi")
    coll = _YozuvchiColl()
    asl = jobs_mod.local_db
    try:
        jobs_mod.local_db = _soxta_baza(coll)
        jobs_mod.finish_stage("job-1", "collecting", text="4 xodim, 12 kun yig'ildi")
        jobs_mod.finish_stage("job-1", "training", status="error", text="Mongo yiqildi")
    finally:
        jobs_mod.local_db = asl
    ok, xato = coll.yozuvlar
    return (_check("bajarilgani 100%", ok.get("stageProgress.collecting.percent") == 100,
                   str(ok))
            & _check("holati done", ok.get("stageProgress.collecting.status") == "done",
                     str(ok))
            & _check("xatoda 100% ga sudralmaydi",
                     "stageProgress.training.percent" not in xato, str(xato))
            & _check("holati error", xato.get("stageProgress.training.status") == "error",
                     str(xato)))


def test_zanjir_ikkala_bosqichni_belgilaydi():
    print("  Zanjir collector va trainer bosqichlarini ketma-ket yakunlaydi")
    tartib = []
    asl_stage, asl_finish, asl_prog = (jobs_mod.set_stage, jobs_mod.finish_stage,
                                       jobs_mod.set_progress)
    asl_collect, asl_train = routes_mod.collect, routes_mod.train
    asl_job_finish, asl_baseline = jobs_mod.finish, routes_mod.current_baseline_id
    try:
        jobs_mod.set_stage = lambda job_id, stage, **kw: tartib.append(("boshladi", stage))
        jobs_mod.finish_stage = lambda job_id, stage, **kw: tartib.append(("tugadi", stage))
        jobs_mod.set_progress = lambda *a, **kw: None
        jobs_mod.finish = lambda *a, **kw: None
        routes_mod.current_baseline_id = lambda: "b1"
        routes_mod.collect = lambda on_progress=None: {"days": 3, "failed": [], "clients": 2}
        routes_mod.train = lambda on_progress=None: 2
        routes_mod._retrain_chain("retrain", "job-1")
    finally:
        (jobs_mod.set_stage, jobs_mod.finish_stage, jobs_mod.set_progress,
         jobs_mod.finish, routes_mod.collect, routes_mod.train,
         routes_mod.current_baseline_id) = (asl_stage, asl_finish, asl_prog,
                                            asl_job_finish, asl_collect, asl_train,
                                            asl_baseline)
    kutilgan = [("boshladi", "collecting"), ("tugadi", "collecting"),
                ("boshladi", "training"), ("tugadi", "training")]
    return _check("tartib to'g'ri", tartib == kutilgan, str(tartib))


def test_xato_qaysi_bosqichda_bolgani_belgilanadi():
    print("  Trainer yiqilsa aynan trainer bosqichi xato deb belgilanadi")
    xatolar = []
    asl_stage, asl_finish, asl_prog = (jobs_mod.set_stage, jobs_mod.finish_stage,
                                       jobs_mod.set_progress)
    asl_collect, asl_train = routes_mod.collect, routes_mod.train
    asl_job_finish, asl_add = jobs_mod.finish, jobs_mod.add_error
    try:
        jobs_mod.set_stage = lambda *a, **kw: None
        jobs_mod.set_progress = lambda *a, **kw: None
        jobs_mod.add_error = lambda *a, **kw: None
        jobs_mod.finish = lambda *a, **kw: None
        jobs_mod.finish_stage = lambda job_id, stage, status="done", **kw: (
            xatolar.append(stage) if status == "error" else None)
        routes_mod.collect = lambda on_progress=None: {"days": 3, "failed": [], "clients": 2}

        def _yiqiladi(on_progress=None):
            raise RuntimeError("Mongo javob bermadi")
        routes_mod.train = _yiqiladi
        routes_mod._retrain_chain("retrain", "job-1")
    finally:
        (jobs_mod.set_stage, jobs_mod.finish_stage, jobs_mod.set_progress,
         jobs_mod.finish, jobs_mod.add_error, routes_mod.collect,
         routes_mod.train) = (asl_stage, asl_finish, asl_prog, asl_job_finish,
                              asl_add, asl_collect, asl_train)
    return _check("xato trainer bosqichida belgilandi", xatolar == ["training"],
                  str(xatolar))


def test_jarayonsiz_ham_ishlaydi():
    print("  on_progress berilmasa collector baribir ishlaydi (CLI rejimi)")
    asl_idx, asl_cl, asl_db = (collector_mod.ensure_indexes,
                               collector_mod.active_clients, collector_mod.local_db)
    try:
        collector_mod.ensure_indexes = lambda: None
        collector_mod.active_clients = lambda: []
        collector_mod.local_db = lambda: _FakeDB(_FakeColl())
        natija = collector_mod.collect()
    finally:
        collector_mod.ensure_indexes, collector_mod.active_clients, collector_mod.local_db = (
            asl_idx, asl_cl, asl_db)
    return _check("xatosiz tugadi", natija["clients"] == 0, str(natija))


if __name__ == "__main__":
    print("Jarayon va xatolar sinovlari\n")
    results = [
        test_zanjir_xatosi(), test_xodim_darajasidagi_xato(), test_trigger_xatosi(),
        test_ikkala_manba_vaqt_boyicha(), test_xatosiz_holat(), test_limit(),
        test_takroriy_xato_bir_marta(), test_uzun_xato_qisqartiriladi(),
        test_collector_jarayonni_xabar_qiladi(), test_jarayonsiz_ham_ishlaydi(),
        test_har_bosqich_oz_foizini_yozadi(), test_set_stage_faqat_oz_bosqichini_nollaydi(),
        test_finish_stage_100_ga_toldiradi(), test_zanjir_ikkala_bosqichni_belgilaydi(),
        test_xato_qaysi_bosqichda_bolgani_belgilanadi(),
    ]
    print(f"\n{'HAMMASI O‘TDI ✓' if all(results) else 'SINOV YIQILDI ✗'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)
