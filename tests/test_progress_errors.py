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
from api.routes import build_error_log, _bosqich_foizi


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


# --- Bosqichlar bo'ylab umumiy foiz --------------------------------------

def test_bosqich_foizi_bir_yonalishda_osadi():
    print("  Umumiy foiz collector -> trainer bo'ylab faqat oldinga yuradi")
    yozilgan = []
    asl = jobs_mod.set_progress
    try:
        jobs_mod.set_progress = lambda job_id, foiz, matn=None: yozilgan.append(foiz)
        ulush = config.RETRAIN_COLLECT_SHARE
        collect_cb = _bosqich_foizi("job-1", 0, ulush)
        train_cb = _bosqich_foizi("job-1", ulush, 100)
        for f in (0, 50, 100):
            collect_cb(f, "yig'ilmoqda")
        for f in (0, 50, 100):
            train_cb(f, "o'qitilmoqda")
    finally:
        jobs_mod.set_progress = asl
    return (_check("collector 0 dan boshlaydi", yozilgan[0] == 0, str(yozilgan))
            & _check(f"collector {ulush} da tugaydi", yozilgan[2] == ulush, str(yozilgan))
            & _check("trainer o'sha nuqtadan davom etadi", yozilgan[3] == ulush, str(yozilgan))
            & _check("oxiri 100", yozilgan[-1] == 100, str(yozilgan))
            & _check("kamaymaydi", all(a <= b for a, b in zip(yozilgan, yozilgan[1:])),
                     str(yozilgan)))


def test_bosqich_foizi_chegaradan_chiqmaydi():
    print("  Bosqich noto'g'ri foiz bersa ham umumiy shkala buzilmaydi")
    yozilgan = []
    asl = jobs_mod.set_progress
    try:
        jobs_mod.set_progress = lambda job_id, foiz, matn=None: yozilgan.append(foiz)
        cb = _bosqich_foizi("job-1", 40, 90)
        cb(-20, "x")
        cb(300, "x")
    finally:
        jobs_mod.set_progress = asl
    return (_check("pastdan chiqmaydi", yozilgan[0] == 40, str(yozilgan))
            & _check("yuqoridan chiqmaydi", yozilgan[1] == 90, str(yozilgan)))


def test_set_stage_foizni_saqlay_oladi():
    print("  set_stage berilgan foizni saqlaydi (chiziq nolga sakramaydi)")
    tutilgan = {}

    class _Coll:
        def update_one(self, filtr, update):
            tutilgan.update(update["$set"])

    asl = jobs_mod.local_db
    try:
        jobs_mod.local_db = lambda: {config.COL_TRAINING_JOBS: _Coll()}
        jobs_mod.set_stage("job-1", "training", progress=50, progressText="x")
    finally:
        jobs_mod.local_db = asl
    return (_check("bosqich yozildi", tutilgan.get("stage") == "training", str(tutilgan))
            & _check("foiz 50 qoldi", tutilgan.get("progress") == 50, str(tutilgan)))


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
        test_bosqich_foizi_bir_yonalishda_osadi(), test_bosqich_foizi_chegaradan_chiqmaydi(),
        test_set_stage_foizni_saqlay_oladi(),
    ]
    print(f"\n{'HAMMASI O‘TDI ✓' if all(results) else 'SINOV YIQILDI ✗'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)
