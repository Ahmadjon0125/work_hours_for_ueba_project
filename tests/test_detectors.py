"""Detector karkasi sinovlari: ball, riskScore, vazn, xato izolyatsiyasi.

Ishga tushirish:  python tests/test_detectors.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from services.detectors import registry
from services.detectors.base import DayContext, Detector, DetectorResult
from services.detectors.scoring import combine_risk, round_half_up, severity_score
from services.detectors.working_hours import evaluate_window, window_bounds
from services.processor import evaluate_job

BASELINE = {
    "baselineId": "v1-abc",
    "clientId": "C1",
    "weeks": {"Tuesday": {"count": 9, "meanStart": 540.0, "stdStart": 30.0,
                          "meanFinish": 1020.0, "stdFinish": 45.0}},
}


def _check(label, condition, detail=""):
    print(f"    {'✓' if condition else '✗'} {label}{'' if condition else '  <- ' + detail}")
    return condition


def _job(date, start, finish, weekday="Tuesday"):
    return {"jobId": "j1", "clientId": "C1", "hostname": "PC-1",
            "days": {date: {"start": f"{date}T{start}", "finish": f"{date}T{finish}",
                            "eventCount": 10, "dayOfWeek": weekday, "durationMin": 600}}}


def _ctx(week=None):
    """Sinovlar uchun eng sodda DayContext."""
    return DayContext(client_id="C1", hostname="PC-1", full_name=None,
                      date="2026-08-25", day_of_week="Tuesday",
                      start=datetime(2026, 8, 25, 8, 0), finish=datetime(2026, 8, 25, 18, 0),
                      duration_min=600, event_count=10, day={},
                      baseline=BASELINE, week=week if week is not None else BASELINE["weeks"]["Tuesday"],
                      now=datetime(2026, 8, 25, 20, 0))


def _fake(name, weight=1.0, score=0, raises=False, fields=None):
    """Ro'yxatga qo'shilmaydigan soxta detector."""
    class Fake(Detector):
        def __init__(self):
            self.name = name
            self.weight = weight

        def evaluate(self, ctx):
            if raises:
                raise RuntimeError("sinov xatosi")
            return DetectorResult(name=name, weight=weight, is_anomaly=score > 0,
                                  score=score, fields=fields or {})
    return Fake()


# --- Ball ---------------------------------------------------------------

def test_score_table():
    print("  Daraja jadvali — z bilan (chegara 1.0, to'liq shkala 3.0)")
    cases = [(1.0, 1), (1.02, 1), (1.5, 25), (2.0, 50), (2.5, 75), (3.0, 100), (9.0, 100)]
    ok = True
    for z, expected in cases:
        got = severity_score(z)
        ok &= _check(f"zOut={z} -> {expected}", got == expected, f"chiqdi {got}")
    ok &= _check("sigma=0 (zOut None) -> 100", severity_score(None) == 100)
    ok &= _check("chetlanish hech qachon 0 ball olmaydi", severity_score(1.0) >= 1)
    return ok


def test_score_rounding():
    print("  0.5 yuqoriga yaxlitlanadi (Python round() bankir yaxlitlashi qiladi)")
    return (_check("round_half_up(24.5) = 25", round_half_up(24.5) == 25)
            & _check("round_half_up(25.5) = 26", round_half_up(25.5) == 26)
            & _check("Python round(24.5) haqiqatan 24", round(24.5) == 24))


def test_anomaly_flag_independent_of_score():
    print("  Chetlanish bayrog'i balldan MUSTAQIL: tashqarida > 0 bo'lsa true")
    ok = True
    bad = []
    for i in range(0, 4001):
        tashqarida = i / 10.0
        # oyna 08:30–17:45, kelishni tashqariga chiqaramiz
        an, score, d, _ = evaluate_window(540.0, 1020.0, 30.0, 45.0,
                                          510.0 - tashqarida, 1020.0)
        if an != (tashqarida > 0):
            bad.append((tashqarida, an))
        if an and score < 1:
            bad.append(("ball 0 bo'lgan chetlanish", tashqarida, score))
    ok &= _check(f"0..400 daqiqa oralig'ida ziddiyat yo'q ({len(bad)} ta)",
                 not bad, str(bad[:5]))
    ok &= _check("1 daqiqa ham chetlanish",
                 evaluate_window(540.0, 1020.0, 30.0, 45.0, 509.0, 1020.0)[0] is True)
    ok &= _check("chetlanish bo'lsa ball hech qachon 0 emas",
                 evaluate_window(540.0, 1020.0, 30.0, 45.0, 509.9, 1020.0)[1] >= 1)
    ok &= _check("sigma=0 bo'lsa har qanday chiqish -> 100",
                 evaluate_window(540.0, 1020.0, 0.0, 0.0, 539.0, 1020.0)[1] == 100,
                 str(evaluate_window(540.0, 1020.0, 0.0, 0.0, 539.0, 1020.0)))
    return ok


def test_window_rule():
    print("  Oyna qoidasi (oyna 08:30–17:45)")
    lo, hi = window_bounds(540.0, 1020.0, 30.0, 45.0)
    ok = _check("oyna chegarasi 510–1065", (lo, hi) == (510.0, 1065.0), f"{lo}-{hi}")

    def ball(st, fi):
        return evaluate_window(540.0, 1020.0, 30.0, 45.0, st, fi)[1]

    def anom(st, fi):
        return evaluate_window(540.0, 1020.0, 30.0, 45.0, st, fi)[0]

    ok &= _check("oyna ichida (09:15–17:00) -> 0", ball(555, 1020) == 0)
    ok &= _check("KECH kelish (13:00–17:00) -> 0 — endi shubhali emas",
                 ball(780, 1020) == 0, str(ball(780, 1020)))
    ok &= _check("ERTA ketish (09:00–10:00) -> 0 — endi shubhali emas",
                 ball(540, 600) == 0, str(ball(540, 600)))
    ok &= _check("oynadan oldin (08:00, zOut=2.0) -> 50", ball(480, 1020) == 50,
                 str(ball(480, 1020)))
    ok &= _check("oynadan keyin (19:00, zOut=2.67) -> 83", ball(555, 1140) == 83,
                 str(ball(555, 1140)))
    ok &= _check("ikki tomondan (03:00–23:00) -> 100", ball(180, 1380) == 100)

    # Chegaradagi aniq holat: bir daqiqa tashqarida ham anomaliya
    ok &= _check("chegarada aynan (08:30) -> ball 0, chetlanish YO'Q",
                 ball(510, 1020) == 0 and anom(510, 1020) is False)
    ok &= _check("chegaradan 1 daqiqa (08:29) -> ball 2, chetlanish HA",
                 ball(509, 1020) == 2 and anom(509, 1020) is True,
                 f"{ball(509, 1020)} {anom(509, 1020)}")

    _, _, details, _ = evaluate_window(540.0, 1020.0, 30.0, 45.0, 180, 1380)
    ok &= _check("xom daqiqa saqlanadi (ball 100 bo'lsa ham)",
                 details["outsideMin"] == 330.0, str(details))
    ok &= _check("zOut ham saqlanadi", details["zOut"] == 12.0, str(details["zOut"]))
    ok &= _check("baseline yo'q -> (None, None, None, None)",
                 evaluate_window(None, None, None, None, 500, 1000) == (None, None, None, None))
    return ok


def test_risk_equals_score_single_detector():
    print("  Bitta detector + vazn 1.0 -> riskScore = anomalyScore")
    bad = [s for s in range(101)
           if combine_risk([DetectorResult(name="x", weight=1.0, score=s)]) != s]
    return _check(f"0..100 ballarning hammasi mos ({len(bad)} ta farq)", not bad, str(bad[:5]))


def test_weight_scales_risk():
    print("  Vazn riskni miqyoslaydi")
    one = combine_risk([DetectorResult(name="x", weight=0.4, score=100)])
    two = combine_risk([DetectorResult(name="a", weight=1.0, score=50),
                        DetectorResult(name="b", weight=1.0, score=50)])
    three = combine_risk([DetectorResult(name="a", weight=1.0, score=50),
                          DetectorResult(name="b", weight=0.8, score=50),
                          DetectorResult(name="c", weight=0.6, score=50)])
    none = combine_risk([DetectorResult(name="x", weight=1.0, evaluated=False)])
    return (_check("vazn 0.4 + ball 100 -> 40", one == 40, f"chiqdi {one}")
            & _check("ikkita 50/1.0 -> 75", two == 75, f"chiqdi {two}")
            & _check("50/1.0 + 50/0.8 + 50/0.6 -> 79", three == 79, f"chiqdi {three}")
            & _check("baholanmagan detector -> None", none is None, f"chiqdi {none}"))


# --- Natija hujjati -----------------------------------------------------

def test_result_shape():
    print("  Natija hujjatining yangi maydonlari")
    doc = evaluate_job(_job("2026-08-25", "08:00:00", "18:00:00"), BASELINE)[0]
    det = (doc.get("detectors") or {}).get("workingHours") or {}
    return (_check("isAnomaly True (oynadan tashqarida)", doc["isAnomaly"] is True)
            & _check("anomalyScore 50 (zOut=2.0)", doc["anomalyScore"] == 50,
                     str(doc.get("anomalyScore")))
            & _check("riskScore = anomalyScore", doc["riskScore"] == doc["anomalyScore"])
            & _check("status anomaly", doc["status"] == "anomaly", doc["status"])
            & _check("triggers.workingHours True", doc["triggers"] == {"workingHours": True})
            & _check("triggeredDetectors ro'yxati", doc["triggeredDetectors"] == ["workingHours"])
            & _check("detectors.workingHours.score", det.get("score") == 50)
            & _check("windowStart/windowFinish yozildi",
                     doc.get("windowStart") == 510.0 and doc.get("windowFinish") == 1065.0,
                     f"{doc.get('windowStart')}-{doc.get('windowFinish')}")
            & _check("detectors.workingHours.weight", det.get("weight") == 1.0)
            & _check("sabab matni bor", bool(det.get("reason")), str(det.get("reason"))))


def test_insufficient_day():
    print("  Baseline yo'q kun: ball null, isAnomaly false")
    doc = evaluate_job(_job("2026-08-24", "08:00:00", "18:00:00", weekday="Monday"), BASELINE)[0]
    return (_check("status insufficient", doc["status"] == "insufficient", doc["status"])
            & _check("anomalyScore None", doc["anomalyScore"] is None, str(doc["anomalyScore"]))
            & _check("riskScore None", doc["riskScore"] is None, str(doc["riskScore"]))
            & _check("isAnomaly False", doc["isAnomaly"] is False)
            & _check("triggers false bo'lib turadi", doc["triggers"] == {"workingHours": False})
            & _check("triggeredDetectors bo'sh", doc["triggeredDetectors"] == []))


def test_normal_day():
    print("  Chegaradan pastdagi kun: normal")
    # 09:15–17:00 — oyna (08:30–17:45) ichida, demak shubha yo'q
    doc = evaluate_job(_job("2026-08-25", "09:15:00", "17:00:00"), BASELINE)[0]
    return (_check("status normal", doc["status"] == "normal", doc["status"])
            & _check("isAnomaly False", doc["isAnomaly"] is False)
            & _check("anomalyScore 0", doc["anomalyScore"] == 0, str(doc["anomalyScore"]))
            & _check("zStart ko'rsatish uchun saqlanadi", doc["zStart"] == -0.5,
                     str(doc["zStart"])))


# --- Registry xatti-harakati -------------------------------------------

def test_broken_detector_isolated():
    print("  Xato tashlagan detector kunni yo'qotmaydi")
    out = registry.run(_ctx(), detectors=[_fake("yomon", raises=True),
                                          _fake("yaxshi", score=60)])
    yomon = out.detectors["yomon"]
    return (_check("yomon detector evaluated=False", yomon["evaluated"] is False)
            & _check("xato yozildi", "RuntimeError" in (yomon.get("error") or ""),
                     str(yomon.get("error")))
            & _check("yaxshi detector baribir ishladi", out.detectors["yaxshi"]["score"] == 60)
            & _check("riskScore faqat ishlaganidan", out.risk_score == 60, str(out.risk_score)))


def test_field_collision():
    print("  Ikki detector bir xil maydon bersa birinchisi qoladi")
    out = registry.run(_ctx(), detectors=[_fake("bir", score=10, fields={"zStart": 1}),
                                          _fake("ikki", score=10, fields={"zStart": 2})])
    return _check("birinchi qiymat saqlandi", out.fields["zStart"] == 1, str(out.fields))


def test_registry_rejects_bad_name():
    print("  Ro'yxatga olishda nom tekshiriladi")
    ok = True
    for bad in ["Working.Hours", "$usb", "WorkingHours", ""]:
        try:
            registry.register(_fake(bad))
            ok &= _check(f"{bad!r} rad etildi", False, "qabul qilindi")
        except ValueError:
            ok &= _check(f"{bad!r} rad etildi", True)
    try:
        registry.register(_fake("workingHours"))
        ok &= _check("takroriy nom rad etildi", False, "qabul qilindi")
    except ValueError:
        ok &= _check("takroriy nom rad etildi", True)
    return ok


# --- Vazn sozlamasi -----------------------------------------------------

def test_env_key_name():
    print("  .env kaliti va vaznning [0,1] ga siqilishi")
    key = "DETECTOR_WEIGHT_WORKING_HOURS"
    saved = os.environ.get(key)
    try:
        os.environ[key] = "0.4"
        a = config.detector_weight("workingHours")
        os.environ[key] = "5"
        b = config.detector_weight("workingHours")
        os.environ[key] = "-1"
        c = config.detector_weight("workingHours")
        os.environ[key] = "abc"
        d = config.detector_weight("workingHours", 0.7)
        os.environ.pop(key)
        e = config.detector_weight("workingHours", 0.9)
    finally:
        os.environ.pop(key, None)
        if saved is not None:
            os.environ[key] = saved
    return (_check("workingHours -> DETECTOR_WEIGHT_WORKING_HOURS = 0.4", a == 0.4, str(a))
            & _check("5 -> 1.0 ga siqildi", b == 1.0, str(b))
            & _check("-1 -> 0.0 ga siqildi", c == 0.0, str(c))
            & _check("son bo'lmasa default", d == 0.7, str(d))
            & _check("kalit yo'q bo'lsa default", e == 0.9, str(e)))


if __name__ == "__main__":
    print("Detector karkasi sinovlari\n")
    results = [
        test_score_table(), test_score_rounding(), test_anomaly_flag_independent_of_score(),
        test_window_rule(),
        test_risk_equals_score_single_detector(), test_weight_scales_risk(),
        test_result_shape(), test_insufficient_day(), test_normal_day(),
        test_broken_detector_isolated(), test_field_collision(),
        test_registry_rejects_bad_name(), test_env_key_name(),
    ]
    print(f"\n{'HAMMASI O‘TDI ✓' if all(results) else 'SINOV YIQILDI ✗'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)
