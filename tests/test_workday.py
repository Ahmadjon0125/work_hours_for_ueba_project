"""Ish kuni manbasi sinovlari: session/activity tanlovi va sof ish vaqti.

Ishga tushirish:  python tests/test_workday.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import services.workday as workday_mod
from services.workday import active_minutes, collect_client_days
from utils.helpers import build_day_doc

CLIENT = {"_id": "oid-1", "clientId": "C1", "hostname": "PC-1"}


def _check(label, condition, detail=""):
    print(f"    {'✓' if condition else '✗'} {label}{'' if condition else '  <- ' + detail}")
    return condition


def _t(h, m=0):
    return datetime(2026, 9, 8, h, m)


def _fake_sessions(events):
    def gen(client, ws, we=None):
        yield "agentsessionstatuses", events
    return gen


def _fake_activity(stamps):
    def gen(client, ws, we=None):
        yield "keyloggers", stamps
    return gen


# --- sof ish vaqti ---------------------------------------------------

def test_active_minutes_oddiy():
    print("  Sof ish vaqti: oddiy kun")
    m = active_minutes([(_t(9), "LOGON"), (_t(17), "LOGOFF")])
    return _check("09:00 LOGON -> 17:00 LOGOFF = 480 daqiqa", m == 480.0, str(m))


def test_active_minutes_tanaffus():
    print("  Sof ish vaqti: tanaffus chiqarib tashlanadi")
    m = active_minutes([(_t(9), "LOGON"), (_t(12), "LOCK"),
                        (_t(13), "UNLOCK"), (_t(17), "LOGOFF")])
    return (_check("1 soatlik tanaffus ayrildi -> 420", m == 420.0, str(m))
            & _check("kun uzunligi 480 emas (tanaffus hisobga olingan)", m != 480.0))


def test_active_minutes_masofadan():
    print("  Sof ish vaqti: REMOTE_CONNECT ham sanaladi")
    m = active_minutes([(_t(9), "REMOTE_CONNECT"), (_t(11), "REMOTE_DISCONNECT")])
    return _check("2 soatlik masofaviy sessiya -> 120", m == 120.0, str(m))


def test_active_minutes_chala():
    print("  Sof ish vaqti: chala ma'lumot quyi chegara beradi")
    # Kun LOCK bilan boshlanadi — odam kechadan beri kirgan, o'sha oraliq
    # sanalmaydi (sun'iy cho'zishdan ko'ra kam ko'rsatgan yaxshi)
    a = active_minutes([(_t(10), "LOCK"), (_t(11), "UNLOCK"), (_t(15), "LOCK")])
    # Kun LOGOFF'siz tugaydi — ochiq oraliq oxirgi hodisagacha yopiladi
    b = active_minutes([(_t(9), "LOGON"), (_t(14), "UNLOCK")])
    c = active_minutes([])
    return (_check("juftsiz LOCK sanalmaydi -> 240", a == 240.0, str(a))
            & _check("ochiq oraliq oxirgi hodisada yopiladi -> 300", b == 300.0, str(b))
            & _check("bo'sh ro'yxat -> None", c is None, str(c)))


def test_active_minutes_tartibsiz():
    print("  Sof ish vaqti: hodisalar tartibsiz kelsa ham to'g'ri")
    m = active_minutes([(_t(17), "LOGOFF"), (_t(9), "LOGON"), (_t(12), "LOCK"),
                        (_t(13), "UNLOCK")])
    return _check("aralash tartibda ham 420", m == 420.0, str(m))


# --- manba tanlovi ---------------------------------------------------

def test_session_manbasi():
    print("  session manbasi: kunlar guruhlanadi, activeMin hisoblanadi")
    saqlangan = config.WORKDAY_SOURCE
    asl = workday_mod.iter_client_sessions
    try:
        config.WORKDAY_SOURCE = "session"
        workday_mod.iter_client_sessions = _fake_sessions([
            (_t(9), "LOGON"), (_t(12), "LOCK"), (_t(13), "UNLOCK"), (_t(17), "LOGOFF"),
            (datetime(2026, 9, 9, 10), "LOGON"), (datetime(2026, 9, 9, 11), "LOGOFF"),
        ])
        days, manbalar = collect_client_days(CLIENT, _t(0))
    finally:
        config.WORKDAY_SOURCE = saqlangan
        workday_mod.iter_client_sessions = asl

    return (_check("2 ta kun ajratildi", set(days) == {"2026-09-08", "2026-09-09"}, str(set(days)))
            & _check("1-kun 4 ta hodisa", len(days["2026-09-08"]["stamps"]) == 4)
            & _check("1-kun activeMin 420", days["2026-09-08"]["activeMin"] == 420.0,
                     str(days["2026-09-08"]["activeMin"]))
            & _check("2-kun activeMin 60", days["2026-09-09"]["activeMin"] == 60.0,
                     str(days["2026-09-09"]["activeMin"]))
            & _check("manba nomi qaytdi", manbalar[0][0] == "agentsessionstatuses"))


def test_activity_manbasi():
    print("  activity manbasi: activeMin hisoblanmaydi")
    saqlangan = config.WORKDAY_SOURCE
    asl = workday_mod.iter_client_timestamps
    try:
        config.WORKDAY_SOURCE = "activity"
        workday_mod.iter_client_timestamps = _fake_activity([_t(9), _t(13), _t(17)])
        days, manbalar = collect_client_days(CLIENT, _t(0))
    finally:
        config.WORKDAY_SOURCE = saqlangan
        workday_mod.iter_client_timestamps = asl

    return (_check("kun ajratildi", set(days) == {"2026-09-08"}, str(set(days)))
            & _check("3 ta timestamp", len(days["2026-09-08"]["stamps"]) == 3)
            & _check("activeMin None (sessiya ma'lumoti yo'q)",
                     days["2026-09-08"]["activeMin"] is None))


def test_kun_hujjatida_manba():
    print("  Kunlik hujjatda manba yozib qo'yiladi")
    doc = build_day_doc("C1", "PC-1", "2026-09-08", _t(9), _t(17), 4,
                        datetime(2026, 9, 8, 20), source="session", active_min=420.0)
    return (_check("source maydoni", doc["source"] == "session", str(doc.get("source")))
            & _check("activeMin maydoni", doc["activeMin"] == 420.0)
            & _check("durationMin baribir kun uzunligi", doc["durationMin"] == 480.0,
                     str(doc["durationMin"])))


def test_notogri_manba_defaultga_qaytadi():
    print("  .env da noto'g'ri qiymat berilsa activity ga qaytadi")
    return _check("hozirgi qiymat ruxsat etilganlardan",
                  config.WORKDAY_SOURCE in ("activity", "session"), config.WORKDAY_SOURCE)


if __name__ == "__main__":
    print("Ish kuni manbasi sinovlari\n")
    results = [
        test_active_minutes_oddiy(), test_active_minutes_tanaffus(),
        test_active_minutes_masofadan(), test_active_minutes_chala(),
        test_active_minutes_tartibsiz(),
        test_session_manbasi(), test_activity_manbasi(),
        test_kun_hujjatida_manba(), test_notogri_manba_defaultga_qaytadi(),
    ]
    print(f"\n{'HAMMASI O‘TDI ✓' if all(results) else 'SINOV YIQILDI ✗'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)
