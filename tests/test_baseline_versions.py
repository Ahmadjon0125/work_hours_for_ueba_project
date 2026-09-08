"""ARCH-02 sinovlari: baseline versiyalash va natijaning o'zi-o'ziga yetarliligi.

Ishga tushirish:  python tests/test_baseline_versions.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.processor import evaluate_job  # noqa: E402


def _check(label, condition, detail=""):
    print(f"    {'✓' if condition else '✗'} {label}{'' if condition else '  <- ' + detail}")
    return condition


BASELINE = {
    "baselineId": "v1-abc",
    "clientId": "C1",
    "weeks": {"Tuesday": {"count": 9, "meanStart": 540.0, "stdStart": 30.0,
                          "meanFinish": 1020.0, "stdFinish": 45.0}},
}


def _job(date, start, finish, weekday="Tuesday"):
    return {"clientId": "C1", "hostname": "PC-1", "days": {date: {
        "start": f"{date}T{start}", "finish": f"{date}T{finish}",
        "eventCount": 10, "dayOfWeek": weekday, "durationMin": 600}}}


def test_result_records_baseline_version():
    """Natijada qaysi baseline versiyasi ishlatilgani yoziladi."""
    doc = evaluate_job(_job("2026-08-25", "08:00:00", "18:00:00"), BASELINE)[0]

    print("  ARCH-02: natijada baselineId bo'ladi")
    return all([
        _check("baselineId yozildi", doc["baselineId"] == "v1-abc", f"{doc['baselineId']}"),
        _check("z-score to'g'ri (erta kelish -> musbat)", doc["zStart"] == 2.0),
    ])


def test_result_is_self_contained():
    """Taqqoslash qiymatlari natijaning ichida saqlanadi."""
    doc = evaluate_job(_job("2026-08-25", "08:00:00", "18:00:00"), BASELINE)[0]

    print("  ARCH-02: natija o'zi-o'ziga yetarli")
    return all([
        _check("usualStart saqlandi (09:00 = 540)", doc["usualStart"] == 540.0),
        _check("usualFinish saqlandi (17:00 = 1020)", doc["usualFinish"] == 1020.0),
        _check("stdStart saqlandi", doc["stdStart"] == 30.0),
        _check("stdFinish saqlandi", doc["stdFinish"] == 45.0),
    ])


def test_unevaluated_day_has_no_comparison():
    """Baseline'i yo'q hafta kunida taqqoslash qiymatlari ham bo'lmaydi.

    Skrinshotdagi ziddiyatning oldini oladi: "Baholanmadi" deb yozilgan kun
    yonida farq ko'rsatilmasligi kerak.
    """
    # Dushanba uchun baseline yo'q (weeks da faqat Tuesday bor)
    doc = evaluate_job(_job("2026-08-24", "10:20:00", "22:15:00", "Monday"), BASELINE)[0]

    print("  ARCH-02: baholanmagan kunda taqqoslash qiymati yo'q")
    return all([
        _check("status insufficient", doc["status"] == "insufficient", doc["status"]),
        _check("zStart null", doc["zStart"] is None),
        _check("usualStart null", doc["usualStart"] is None,
               f"{doc['usualStart']}"),
        _check("usualFinish null", doc["usualFinish"] is None),
    ])


def test_no_baseline_at_all():
    """Client uchun baseline umuman bo'lmasa ham kun yo'qolmaydi (edge #8)."""
    doc = evaluate_job(_job("2026-08-25", "09:00:00", "17:00:00"), None)[0]

    print("  Baseline umuman yo'q bo'lganda")
    return all([
        _check("kun yozildi", doc["date"] == "2026-08-25"),
        _check("status insufficient", doc["status"] == "insufficient"),
        _check("baselineId null", doc["baselineId"] is None),
        _check("taqqoslash qiymatlari null", doc["usualStart"] is None),
    ])


if __name__ == "__main__":
    print("Baseline versiyalash sinovlari\n")
    results = [
        test_result_records_baseline_version(),
        test_result_is_self_contained(),
        test_unevaluated_day_has_no_comparison(),
        test_no_baseline_at_all(),
    ]
    print(f"\n{'HAMMASI O‘TDI ✓' if all(results) else 'SINOV YIQILDI ✗'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)
