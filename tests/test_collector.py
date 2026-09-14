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
import services.workday as workday_mod  # noqa: E402
from services.mongo import SourceReadError  # noqa: E402


# --- Soxta mahalliy baza -------------------------------------------------
def _match_value(value, cond):
    """Bitta maydonni shartga solishtirish (oddiy qiymat yoki $-operatorlar)."""
    if not isinstance(cond, dict):
        return value == cond
    for op, arg in cond.items():
        if op == "$lt" and not (value is not None and value < arg):
            return False
        if op == "$gte" and not (value is not None and value >= arg):
            return False
        if op == "$nin" and value in arg:
            return False
        if op == "$in" and value not in arg:
            return False
    return True


def _matches(doc, flt):
    """Soxta Mongo filtri: $or va maydon shartlari yetarli."""
    for key, cond in flt.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in cond):
                return False
        elif not _match_value(doc.get(key), cond):
            return False
    return True


class DeleteResult:
    def __init__(self, n):
        self.deleted_count = n


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.writes = 0

    def update_one(self, flt, update, upsert=False):
        self.writes += 1
        doc = {**flt, **update["$set"]}
        for i, d in enumerate(self.docs):
            if _matches(d, flt):
                self.docs[i] = doc
                return
        if upsert:
            self.docs.append(doc)

    def delete_many(self, flt):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _matches(d, flt)]
        return DeleteResult(before - len(self.docs))

    def find_one(self, flt):
        return next((d for d in self.docs if _matches(d, flt)), None)


class FakeDB:
    def __init__(self, coll):
        self.coll = coll

    def __getitem__(self, name):
        return self.coll


def _ses(connect, disconnect, day=None):
    """Manba `agentsessions` dagi bitta yozuv shakli."""
    return {"date": day or connect.strftime("%Y-%m-%d"),
            "connect": connect, "disconnect": disconnect,
            "reason": "transport close"}


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

    def failing_source(client, window_start, window_end=None):
        # Yarim o'qildi: kun o'rtasidagi bitta sessiya keldi...
        yield "agentsessions", [_ses(base.replace(hour=12), base.replace(hour=13), day)]
        # ...keyin uzildi. 08:00-18:00 sessiyasi hali kelmagan edi.
        raise SourceReadError("agentsessions o'qib bo'lmadi: Network is unreachable")

    collector_mod.ensure_indexes = lambda: None
    collector_mod.active_clients = lambda: [
        {"clientId": "C1", "hostname": "PC-1", "fullName": None, "_id": "C1"}]
    workday_mod.iter_client_sessions = failing_source
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

    def good_source(client, window_start, window_end=None):
        # Kun ichida uzilib qayta ulangan: ikkita sessiya, kun 08:00-18:00
        yield "agentsessions", [_ses(base.replace(hour=8), base.replace(hour=12), day),
                                _ses(base.replace(hour=13), base.replace(hour=18), day)]

    collector_mod.ensure_indexes = lambda: None
    collector_mod.active_clients = lambda: [
        {"clientId": "C1", "hostname": "PC-1", "fullName": None, "_id": "C1"}]
    workday_mod.iter_client_sessions = good_source
    collector_mod.local_db = lambda: FakeDB(raw)

    result = collector_mod.collect()
    stored = raw.find_one({"clientId": "C1", "date": day})
    span = (stored["start"][11:16], stored["finish"][11:16])

    print("  Normal holat: barcha manbalar o'qildi")
    return all([
        _check("kun yozildi (08:00-18:00)", span == ("08:00", "18:00"), f"{span}"),
        _check("4 ta vaqt belgisi sanaldi", stored["eventCount"] == 4),
        _check("failed bo'sh", not result["failed"]),
    ])


# --- COL-01: o'qitishga faqat to'liq kunlar kirsin -----------------------
def test_window_covers_only_complete_days():
    """Ishga tushirilgan kun kirmaydi; oyna soatga bog'liq emas."""
    raw = FakeCollection()
    seen = {}

    def source(client, window_start, window_end=None):
        seen["start"], seen["end"] = window_start, window_end
        # Chegaralarni iter_client_sessions qo'llaydi (alohida sinov bor),
        # bu yerda collect() to'g'ri oyna uzatishini tekshiramiz
        con = window_start + timedelta(hours=7)
        yield "agentsessions", [_ses(con, con + timedelta(hours=8))]

    collector_mod.ensure_indexes = lambda: None
    collector_mod.active_clients = lambda: [
        {"clientId": "C1", "hostname": "PC-1", "fullName": None, "_id": "C1"}]
    workday_mod.iter_client_sessions = source
    collector_mod.local_db = lambda: FakeDB(raw)
    collector_mod.collect()

    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    expected_start = midnight - timedelta(days=config.DAYS_WINDOW)
    oldest = raw.find_one({"date": expected_start.strftime("%Y-%m-%d")})

    print("  COL-01: collect() to'liq kunlar oynasini uzatadi")
    return all([
        _check("oyna 00:00 dan boshlanadi", seen["start"] == expected_start,
               f"{seen['start']}"),
        _check(f"oyna {config.DAYS_WINDOW} kunlik",
               (seen["end"] - seen["start"]).days == config.DAYS_WINDOW),
        _check("yuqori chegara = bugungi 00:00 (ishga tushirilgan kun kirmaydi)",
               seen["end"] == midnight, f"{seen['end']}"),
        _check("eng eski kun ertalabdan boshlandi",
               oldest is not None and oldest["start"][11:16] == "07:00",
               f"{oldest['start'][11:16] if oldest else 'yo‘q'}"),
    ])


def test_source_respects_window_bounds():
    """iter_client_sessions ikkala chegarani ham qo'llaydi."""
    start = datetime(2026, 7, 10, 0, 0)
    end = datetime(2026, 9, 8, 0, 0)
    def _doc(dt):
        return {"connectTime": dt, "disconnectTime": dt + timedelta(hours=1),
                "dateStr": dt.strftime("%d.%m.%Y")}
    docs = [
        _doc(datetime(2026, 7, 9, 23, 59)),   # oynadan oldin
        _doc(datetime(2026, 7, 10, 0, 0)),    # chegarada — kiradi
        _doc(datetime(2026, 8, 1, 12, 0)),    # o'rtada
        _doc(datetime(2026, 9, 7, 23, 59)),   # oxirgi to'liq kun
        _doc(datetime(2026, 9, 8, 0, 0)),     # bugungi kun — chiqadi
    ]

    class Coll:
        def find(self, q, p):
            return _RetryCursor(docs)   # so'rov filtri emas, kod filtri sinaladi

    mongo_mod.main_db = lambda: FakeDB(Coll())
    out = list(mongo_mod.iter_client_sessions(
        {"clientId": "C1", "_id": "C1"}, start, end))
    got = sorted(ses["connect"] for ses in out[0][1])

    print("  COL-01: manba o'qishda oyna chegaralari")
    return all([
        _check("3 ta sessiya qoldi", len(got) == 3, f"{len(got)} ta"),
        _check("oynadan oldingisi chiqarildi", datetime(2026, 7, 9, 23, 59) not in got),
        _check("chegaradagi 00:00 kiritildi", datetime(2026, 7, 10, 0, 0) in got),
        _check("ishga tushirilgan kun chiqarildi", datetime(2026, 9, 8, 0, 0) not in got),
    ])


# --- COL-02: arxiv oynaning nusxasi bo'lsin ------------------------------
def _setup(raw, source, clients):
    collector_mod.ensure_indexes = lambda: None
    collector_mod.active_clients = lambda: clients
    workday_mod.iter_client_sessions = source
    collector_mod.local_db = lambda: FakeDB(raw)


def _day(days_ago):
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _row(cid, host, date):
    return {"clientId": cid, "hostname": host, "date": date,
            "start": f"{date}T09:00:00", "finish": f"{date}T17:00:00", "eventCount": 10}


ACTIVE = [{"clientId": "C1", "hostname": "PC-1", "fullName": None, "_id": "C1"}]


def test_inactive_client_rows_removed():
    """Active ro'yxatda yo'q client (ishdan bo'shagan) arxivdan chiqariladi."""
    raw = FakeCollection([
        _row("C1", "PC-1", _day(5)),
        _row("GONE", "eski-xodim", _day(5)),      # active ro'yxatda yo'q
        _row("GONE", "eski-xodim", _day(6)),
    ])

    def source(client, window_start, window_end=None):
        base = datetime.strptime(_day(5), "%Y-%m-%d")
        yield "agentsessions", [_ses(base.replace(hour=9), base.replace(hour=17), _day(5))]

    _setup(raw, source, ACTIVE)
    collector_mod.collect()

    print("  COL-02: active bo'lmagan client arxivdan chiqadi")
    return all([
        _check("ishdan bo'shagan xodim yozuvlari o'chdi",
               raw.find_one({"clientId": "GONE"}) is None),
        _check("active client yozuvi joyida", raw.find_one({"clientId": "C1"}) is not None),
    ])


def test_inactive_cleanup_skipped_when_run_failed():
    """Run to'liq bajarilmasa, o'chirish qilinmaydi (manba buzilgan bo'lishi mumkin)."""
    raw = FakeCollection([_row("GONE", "eski-xodim", _day(5))])

    def failing(client, window_start, window_end=None):
        raise SourceReadError("manba yotdi")
        yield  # pragma: no cover

    _setup(raw, failing, ACTIVE)
    result = collector_mod.collect()

    print("  COL-02: xatoli run'da tozalash qilinmaydi (himoya)")
    return all([
        _check("client failed ro'yxatida", len(result["failed"]) == 1),
        _check("arxiv qirilmadi", raw.find_one({"clientId": "GONE"}) is not None),
    ])


def test_stale_day_removed():
    """Oynada bor, lekin manbadan kelmagan kun arxivdan o'chiriladi."""
    raw = FakeCollection([
        _row("C1", "PC-1", _day(5)),    # manbada bor
        _row("C1", "PC-1", _day(6)),    # manbadan yo'qolgan
    ])

    def source(client, window_start, window_end=None):
        base = datetime.strptime(_day(5), "%Y-%m-%d")
        yield "agentsessions", [_ses(base.replace(hour=9), base.replace(hour=17), _day(5))]

    _setup(raw, source, ACTIVE)
    collector_mod.collect()

    print("  COL-02: manbadan yo'qolgan kun o'chadi")
    return all([
        _check("manbadagi kun qoldi", raw.find_one({"date": _day(5)}) is not None),
        _check("yo'qolgan kun o'chdi", raw.find_one({"date": _day(6)}) is None),
    ])


def test_old_rows_age_out_even_for_unvisited_clients():
    """Collector bormaydigan client yozuvlari ham sana bo'yicha eskiradi."""
    old = (datetime.now() - timedelta(days=config.DAYS_WINDOW + 10)).strftime("%Y-%m-%d")
    raw = FakeCollection([
        _row("C1", "PC-1", old),
        _row("GONE", "eski-xodim", old),
        _row("C1", "PC-1", datetime.now().strftime("%Y-%m-%d")),  # bugungi chala kun
    ])

    def source(client, window_start, window_end=None):
        yield "telegrams", []

    _setup(raw, source, ACTIVE)
    collector_mod.collect()

    print("  COL-02: eski yozuvlar hammaga birdek eskiradi")
    return all([
        _check("oynadan eski yozuvlar o'chdi", raw.find_one({"date": old}) is None),
        _check("bugungi chala kun o'chdi",
               raw.find_one({"date": datetime.now().strftime("%Y-%m-%d")}) is None),
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
        return _RetryCursor([{"connectTime": datetime(2026, 1, 5, 9, 0),
                              "disconnectTime": datetime(2026, 1, 5, 17, 0),
                              "dateStr": "05.01.2026"}])


class _RetryCursor:
    def __init__(self, docs):
        self.docs = docs

    def batch_size(self, n):
        return self.docs


def _read_with_failures(fail_times):
    coll = _RetryColl(fail_times)
    mongo_mod.main_db = lambda: FakeDB(coll)
    client = {"clientId": "C1", "_id": "C1"}
    try:
        out = list(mongo_mod.iter_client_sessions(client, datetime(2026, 1, 1)))
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
        test_window_covers_only_complete_days(),
        test_source_respects_window_bounds(),
        test_inactive_client_rows_removed(),
        test_inactive_cleanup_skipped_when_run_failed(),
        test_stale_day_removed(),
        test_old_rows_age_out_even_for_unvisited_clients(),
        test_retry(),
    ]
    print(f"\n{'HAMMASI O‘TDI ✓' if all(results) else 'SINOV YIQILDI ✗'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)
