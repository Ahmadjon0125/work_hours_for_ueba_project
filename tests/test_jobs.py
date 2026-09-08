"""ARCH-01 sinovlari: o'qitish job holati MongoDB'da.

Ishga tushirish:  python tests/test_jobs.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pymongo.errors import DuplicateKeyError  # noqa: E402

import services.jobs as jobs_mod  # noqa: E402


def _check(label, condition, detail=""):
    print(f"    {'✓' if condition else '✗'} {label}{'' if condition else '  <- ' + detail}")
    return condition


class FakeJobs:
    """Unique partial indeksni taqlid qiladi: bitta 'running' hujjat."""

    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        if doc.get("status") == "running" and any(d["status"] == "running" for d in self.docs):
            raise DuplicateKeyError("one_running_job")
        self.docs.append(doc)

    def update_one(self, flt, update):
        for d in self.docs:
            if d["_id"] == flt["_id"]:
                d.update(update["$set"])

    def update_many(self, flt, update):
        n = 0
        for d in self.docs:
            if all(d.get(k) == v for k, v in flt.items()):
                d.update(update["$set"])
                n += 1
        return type("R", (), {"modified_count": n})()

    def find_one(self, flt, sort=None):
        rows = [d for d in self.docs if all(d.get(k) == v for k, v in flt.items())]
        rows.sort(key=lambda d: d.get("startedAt", ""), reverse=True)
        return rows[0] if rows else None


class FakeDB:
    def __init__(self, coll):
        self.coll = coll

    def __getitem__(self, name):
        return self.coll


def _setup():
    coll = FakeJobs()
    jobs_mod.local_db = lambda: FakeDB(coll)
    return coll


def test_only_one_job_at_a_time():
    """Bir vaqtda faqat bitta o'qitish ketishi kerak."""
    coll = _setup()
    first = jobs_mod.create("retrain")
    try:
        jobs_mod.create("retrain")
        blocked = False
    except jobs_mod.JobAlreadyRunning:
        blocked = True

    print("  ARCH-01: parallel o'qitish to'xtatiladi")
    return all([
        _check("birinchi job ochildi", first is not None),
        _check("ikkinchisi bloklandi", blocked),
        _check("bitta hujjat bor", len(coll.docs) == 1, f"{len(coll.docs)}"),
    ])


def test_job_finishes_and_frees_the_slot():
    """Job tugagach, keyingisini ochish mumkin bo'lishi kerak."""
    coll = _setup()
    first = jobs_mod.create("retrain")
    jobs_mod.set_stage(first, "collecting")
    jobs_mod.finish(first, "finished", baselineId="v1")

    second = jobs_mod.create("retrain")
    done = coll.find_one({"_id": first})

    print("  ARCH-01: tugagan job keyingisini bloklamaydi")
    return all([
        _check("ikkinchi job ochildi", second is not None),
        _check("birinchisi finished", done["status"] == "finished"),
        _check("tugash vaqti yozildi", done["finishedAt"] is not None),
        _check("baselineId yozildi", done["baselineId"] == "v1"),
    ])


def test_stale_job_recovery():
    """Protsess uzilsa, 'running' qolgan job keyingi startda yopiladi."""
    coll = _setup()
    jobs_mod.create("retrain")          # go'yo protsess shu yerda to'xtadi
    recovered = jobs_mod.recover_stale()
    after = jobs_mod.create("retrain")   # endi ochilishi kerak

    stuck = coll.docs[0]
    print("  ARCH-01: uzilib qolgan job tiklanadi")
    return all([
        _check("1 ta job tiklandi", recovered == 1, f"{recovered}"),
        _check("eskisi error deb yopildi", stuck["status"] == "error"),
        _check("sabab yozildi", "uzilib" in (stuck["error"] or "")),
        _check("yangi job ochildi", after is not None),
    ])


def test_stage_progression():
    """Bosqichlar hujjatga yozib boriladi."""
    coll = _setup()
    job_id = jobs_mod.create("retrain")
    stages = []
    for stage in ("collecting", "training"):
        jobs_mod.set_stage(job_id, stage)
        stages.append(coll.find_one({"_id": job_id})["stage"])
    jobs_mod.finish(job_id, "partial")

    print("  ARCH-01: bosqichlar kuzatiladi")
    return all([
        _check("collecting -> training", stages == ["collecting", "training"], f"{stages}"),
        _check("yakuniy holat partial", coll.find_one({"_id": job_id})["status"] == "partial"),
    ])


if __name__ == "__main__":
    print("O'qitish job'lari sinovlari\n")
    results = [
        test_only_one_job_at_a_time(),
        test_job_finishes_and_frees_the_slot(),
        test_stale_job_recovery(),
        test_stage_progression(),
    ]
    print(f"\n{'HAMMASI O‘TDI ✓' if all(results) else 'SINOV YIQILDI ✗'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)
