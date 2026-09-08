"""Collector regressiya sinovlari — jonli baza ishlatilmaydi.

Ishga tushirish:  python tests/test_collector.py

COL-04 (tashqi tekshiruv, 2026-09-06): manbadan o'qishda xato bo'lsa, chala
ma'lumot eski to'g'ri yozuvni almashtirib yubormasligi kerak.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import services.collector as collector_mod  # noqa: E402
import services.mongo as mongo_mod  # noqa: E402
from services.mongo import SourceReadError  # noqa: E402


# --- Soxta mahalliy baza -------------------------------------------------
class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.writes = 0

    def update_one(self, flt, update, upsert=False):
        self.writes += 1
        doc = {**flt, **update["$set"]}
        for i, d in enumerate(self.docs):
            if all(d.get(k) == v for k, v in flt.items()):
                self.docs[i] = doc
                return
        if upsert:
            self.docs.append(doc)

    def delete_many(self, flt):
        pass

    def find_one(self, flt):
        return next((d for d in self.docs
                     if all(d.get(k) == v for k, v in flt.items())), None)


class FakeDB:
    def __init__(self, coll):
        self.coll = coll

    def __getitem__(self, name):
        return self.coll


def _check(label, condition, detail=""):
    print(f"    {'✓' if condition else '✗'} {label}{'' if condition else '  <- ' + detail}")
    return condition


# --- COL-04: manba xatosi eski yozuvni buzmasligi kerak ------------------
def test_source_failure_keeps_existing_day():
    """Bitta collection xato bersa, o'sha client umuman yozilmasligi kerak."""
    day = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    base = datetime.strptime(day, "%Y-%m-%d")

    # Arxivda turgan to'g'ri yozuv
    raw = FakeCollection([{
        "clientId": "C1", "hostname": "PC-1", "date": day,
        "start": f"{day}T08:00:00", "finish": f"{day}T18:00:00", "eventCount": 42,
    }])

    def failing_source(client, window_start):
        # 1-collection ishladi: kun o'rtasidagi ikkita event
        yield "telegrams", [base.replace(hour=12), base.replace(hour=13)]
        # 2-collection xato: aynan 08:00 va 18:00 shu yerda edi
        raise SourceReadError("activewindows o'qib bo'lmadi: Network is unreachable")

    collector_mod.ensure_indexes = lambda: None
    collector_mod.active_clients = lambda: [
        {"clientId": "C1", "hostname": "PC-1", "fullName": None, "_id": "C1"}]
    collector_mod.iter_client_timestamps = failing_source
    collector_mod.local_db = lambda: FakeDB(raw)

    result = collector_mod.collect()
    stored = raw.find_one({"clientId": "C1", "date": day})
    span = (stored["start"][11:16], stored["finish"][11:16])

    print("  COL-04: manba xatosida eski kun saqlanadi")
    return all([
        _check("hech narsa yozilmadi", raw.writes == 0, f"{raw.writes} marta yozildi"),
        _check("eski kun buzilmadi (08:00-18:00)", span == ("08:00", "18:00"), f"{span}"),
        _check("eventCount o'zgarmadi (42)", stored["eventCount"] == 42),
        _check("client failed ro'yxatida", len(result["failed"]) == 1),
        _check("days = 0", result["days"] == 0),
    ])


def test_all_sources_ok_writes_day():
    """Barcha manbalar o'qilganda kun normal yoziladi."""
    day = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    base = datetime.strptime(day, "%Y-%m-%d")
    raw = FakeCollection()

    def good_source(client, window_start):
        yield "telegrams", [base.replace(hour=12), base.replace(hour=13)]
        yield "activewindows", [base.replace(hour=8), base.replace(hour=18)]

    collector_mod.ensure_indexes = lambda: None
    collector_mod.active_clients = lambda: [
        {"clientId": "C1", "hostname": "PC-1", "fullName": None, "_id": "C1"}]
    collector_mod.iter_client_timestamps = good_source
    collector_mod.local_db = lambda: FakeDB(raw)

    result = collector_mod.collect()
    stored = raw.find_one({"clientId": "C1", "date": day})
    span = (stored["start"][11:16], stored["finish"][11:16])

    print("  Normal holat: barcha manbalar o'qildi")
    return all([
        _check("kun yozildi (08:00-18:00)", span == ("08:00", "18:00"), f"{span}"),
        _check("4 ta event sanaldi", stored["eventCount"] == 4),
        _check("failed bo'sh", not result["failed"]),
    ])


# --- Qayta urinish mexanizmi --------------------------------------------
class _RetryColl:
    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.attempts = 0

    def find(self, query, projection):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise ConnectionError("Network is unreachable")
        return _RetryCursor([{"dateTime": datetime(2026, 1, 5, 9, 0)}])


class _RetryCursor:
    def __init__(self, docs):
        self.docs = docs

    def batch_size(self, n):
        return self.docs


def _read_with_failures(fail_times):
    coll = _RetryColl(fail_times)
    mongo_mod.main_db = lambda: FakeDB(coll)
    mongo_mod.COLLECTIONS = {"telegrams": ("clientId", ["dateTime"])}
    client = {"clientId": "C1", "_id": "C1"}
    try:
        out = list(mongo_mod.iter_client_timestamps(client, datetime(2026, 1, 1)))
        return True, coll.attempts, out
    except SourceReadError:
        return False, coll.attempts, None


def test_retry():
    """O'tkinchi xato qayta urinish bilan yengiladi, doimiysi uzatiladi."""
    config.SOURCE_READ_RETRY_DELAY = 0.01  # sinov tez o'tsin
    total = config.SOURCE_READ_RETRIES + 1

    ok_transient, attempts_t, out = _read_with_failures(1)
    ok_permanent, attempts_p, _ = _read_with_failures(99)

    print("  Qayta urinish mexanizmi")
    return all([
        _check("o'tkinchi xato yengildi", ok_transient and out and len(out[0][1]) == 1),
        _check("2-urinishda muvaffaqiyat", attempts_t == 2, f"{attempts_t} urinish"),
        _check("doimiy xato yutilmadi", not ok_permanent),
        _check(f"jami {total} urinish bo'ldi", attempts_p == total, f"{attempts_p} urinish"),
    ])


if __name__ == "__main__":
    print("Collector sinovlari\n")
    results = [
        test_all_sources_ok_writes_day(),
        test_source_failure_keeps_existing_day(),
        test_retry(),
    ]
    print(f"\n{'HAMMASI O‘TDI ✓' if all(results) else 'SINOV YIQILDI ✗'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)
