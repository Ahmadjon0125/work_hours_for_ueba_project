"""Xavf jadvali sinovlari: to'plangan xavf, oxirgi davr, tendensiya, daraja.

Ishga tushirish:  python tests/test_risk_summary.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from api.routes import build_risk_summary


def _check(label, condition, detail=""):
    print(f"    {'✓' if condition else '✗'} {label}{'' if condition else '  <- ' + detail}")
    return condition


def _r(cid, sana, risk, anomaly=False, host=None):
    return {"clientId": cid, "hostname": host or f"pc-{cid}", "fullName": None,
            "date": sana, "riskScore": risk, "isAnomaly": anomaly}


def test_yigindi_va_tendensiya():
    print("  Umumiy xavf = yig'indi, tendensiya = kumulyativ")
    rows = [_r("A", "2026-09-01", 10), _r("A", "2026-09-02", 5), _r("A", "2026-09-03", 20)]
    out = build_risk_summary(rows, date_to="2026-09-03")
    x = out[0]
    return (_check("overallRisk 35", x["overallRisk"] == 35, str(x["overallRisk"]))
            & _check("trend kumulyativ [10,15,35]", x["trend"] == [10, 15, 35], str(x["trend"]))
            & _check("baholangan kun 3", x["evaluatedDays"] == 3))


def test_baholanmagan_kun_hisobga_olinmaydi():
    print("  riskScore null bo'lgan kun xavfga qo'shilmaydi")
    rows = [_r("A", "2026-09-01", 10), _r("A", "2026-09-02", None), _r("A", "2026-09-03", 5)]
    x = build_risk_summary(rows, date_to="2026-09-03")[0]
    return (_check("overallRisk 15 (null qo'shilmadi)", x["overallRisk"] == 15, str(x["overallRisk"]))
            & _check("baholangan kun 2", x["evaluatedDays"] == 2, str(x["evaluatedDays"]))
            & _check("trend 2 nuqta", len(x["trend"]) == 2, str(x["trend"])))


def test_oxirgi_davr():
    print(f"  Oxirgi xavf — so'nggi {config.RISK_RECENT_DAYS} kun")
    # 2026-09-30 dan orqaga: eskisi oynadan tashqarida qolishi kerak
    rows = [_r("A", "2026-09-01", 100), _r("A", "2026-09-29", 7), _r("A", "2026-09-30", 3)]
    x = build_risk_summary(rows, date_to="2026-09-30")[0]
    return (_check("overallRisk hammasi (110)", x["overallRisk"] == 110, str(x["overallRisk"]))
            & _check("recentRisk faqat oxirgi kunlar (10)", x["recentRisk"] == 10,
                     str(x["recentRisk"])))


def test_kesim_hamma_uchun_bitta():
    print("  Oxirgi davr chegarasi hamma xodim uchun bir xil")
    # B ning oxirgi kuni ancha eski — u "oxirgi davr" ga tushmasligi kerak
    rows = [_r("A", "2026-09-29", 5), _r("A", "2026-09-30", 5),
            _r("B", "2026-09-01", 50)]
    out = {x["clientId"]: x for x in build_risk_summary(rows, date_to="2026-09-30")}
    return (_check("A recent 10", out["A"]["recentRisk"] == 10, str(out["A"]["recentRisk"]))
            & _check("B recent 0 (kunlari eski)", out["B"]["recentRisk"] == 0,
                     str(out["B"]["recentRisk"]))
            & _check("B overall baribir 50", out["B"]["overallRisk"] == 50))


def test_saralash():
    print("  Umumiy xavf bo'yicha kamayish tartibida")
    rows = [_r("kichik", "2026-09-01", 5), _r("katta", "2026-09-01", 90),
            _r("orta", "2026-09-01", 40)]
    out = build_risk_summary(rows, date_to="2026-09-01")
    return _check("tartib: katta, orta, kichik",
                  [x["clientId"] for x in out] == ["katta", "orta", "kichik"],
                  str([x["clientId"] for x in out]))


def test_daraja_chegaralari():
    print("  Belgi rangi RISK_LEVEL_* chegaralari bo'yicha")
    H, M = config.RISK_LEVEL_HIGH, config.RISK_LEVEL_MEDIUM
    holatlar = [(H, "high"), (H - 1, "medium" if H - 1 >= M else "low"),
                (M, "medium"), (M - 1, "low"), (0, "low")]
    ok = True
    for risk, kutilgan in holatlar:
        x = build_risk_summary([_r("A", "2026-09-01", risk)], date_to="2026-09-01")[0]
        ok &= _check(f"recent {risk} -> {kutilgan}", x["level"] == kutilgan, x["level"])
    return ok


def test_anomaly_kunlar():
    print("  Chetlanishli kunlar sanaladi")
    rows = [_r("A", "2026-09-01", 60, anomaly=True), _r("A", "2026-09-02", 0),
            _r("A", "2026-09-03", 30, anomaly=True)]
    x = build_risk_summary(rows, date_to="2026-09-03")[0]
    return _check("anomalyDays 2", x["anomalyDays"] == 2, str(x["anomalyDays"]))


def test_trend_cheklanadi():
    print(f"  Tendensiya oxirgi {config.RISK_TREND_POINTS} nuqta bilan cheklanadi")
    n = config.RISK_TREND_POINTS + 15
    rows = [_r("A", f"2026-09-{i % 28 + 1:02d}", 1) for i in range(n)]
    x = build_risk_summary(rows, date_to="2026-09-28")[0]
    return (_check(f"nuqtalar {config.RISK_TREND_POINTS} ta",
                   len(x["trend"]) == config.RISK_TREND_POINTS, str(len(x["trend"])))
            & _check("oxirgi nuqta to'liq yig'indi", x["trend"][-1] == n, str(x["trend"][-1])))


def test_bosh_royxat():
    print("  Bo'sh kirish xato bermaydi")
    return (_check("[] -> []", build_risk_summary([]) == [])
            & _check("faqat null risk -> []",
                     build_risk_summary([_r("A", "2026-09-01", None)],
                                        date_to="2026-09-01") == []))


if __name__ == "__main__":
    print("Xavf jadvali sinovlari\n")
    results = [
        test_yigindi_va_tendensiya(), test_baholanmagan_kun_hisobga_olinmaydi(),
        test_oxirgi_davr(), test_kesim_hamma_uchun_bitta(), test_saralash(),
        test_daraja_chegaralari(), test_anomaly_kunlar(), test_trend_cheklanadi(),
        test_bosh_royxat(),
    ]
    print(f"\n{'HAMMASI O‘TDI ✓' if all(results) else 'SINOV YIQILDI ✗'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)
