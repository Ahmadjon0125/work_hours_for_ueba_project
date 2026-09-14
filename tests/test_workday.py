"""Ish kuni sinovlari: agent sessiyalaridan kun va sof ish vaqti.

Ishga tushirish:  python tests/test_workday.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import services.workday as workday_mod
from services.workday import active_minutes, collect_client_days
from utils.helpers import build_day_agg, build_day_doc

CLIENT = {"_id": "oid-1", "clientId": "C1", "hostname": "PC-1"}


def _check(label, condition, detail=""):
    print(f"    {'✓' if condition else '✗'} {label}{'' if condition else '  <- ' + detail}")
    return condition


def _t(h, m=0, kun=8):
    return datetime(2026, 9, kun, h, m)


def _ses(con, dis, kun="2026-09-08", reason="transport close"):
    return {"date": kun, "connect": con, "disconnect": dis, "reason": reason}


def _fake_sessions(sessions):
    def gen(client, ws, we=None):
        yield "agentsessions", sessions
    return gen


# --- sof ish vaqti (tarmoqda turilgan vaqt) --------------------------

def test_active_minutes_oddiy():
    print("  Sof ish vaqti: bitta sessiya")
    m = active_minutes([_ses(_t(9), _t(17))])
    return _check("09:00 -> 17:00 = 480 daqiqa", m == 480.0, str(m))


def test_active_minutes_bir_nechta_sessiya():
    print("  Sof ish vaqti: kun ichidagi uzilish ayriladi")
    # Kompyuter 12:00 da uzilib, 13:00 da qayta ulangan — o'sha soat sanalmaydi
    m = active_minutes([_ses(_t(9), _t(12)), _ses(_t(13), _t(17))])
    return (_check("3 soat + 4 soat = 420", m == 420.0, str(m))
            & _check("kun uzunligi 480 emas", m != 480.0))


def test_active_minutes_uzilishsiz_sessiya():
    print("  Sof ish vaqti: uzilishi yozilmagan sessiya sanalmaydi")
    # Bo'sh disconnectTime = sessiya ertangi kunga o'tgan bo'lishi mumkin.
    # Uni kun oxirigacha cho'zish xato bo'lardi.
    a = active_minutes([_ses(_t(9), None)])
    b = active_minutes([_ses(_t(9), _t(12)), _ses(_t(13), None)])
    c = active_minutes([])
    return (_check("yolg'iz ochiq sessiya -> None", a is None, str(a))
            & _check("yopilgani sanaladi, ochig'i yo'q -> 180", b == 180.0, str(b))
            & _check("bo'sh ro'yxat -> None", c is None, str(c)))


def test_active_minutes_ikki_kompyuter():
    print("  Sof ish vaqti: ikki kompyuter vaqti qo'shiladi")
    m = active_minutes([_ses(_t(9), _t(12)), _ses(_t(10), _t(13))])
    return _check("3 soat + 3 soat = 360", m == 360.0, str(m))


# --- kun chegaralari -------------------------------------------------

def test_kunlarga_ajratish():
    print("  Sessiyalar kunlarga ajratiladi, activeMin hisoblanadi")
    asl = workday_mod.iter_client_sessions
    try:
        workday_mod.iter_client_sessions = _fake_sessions([
            _ses(_t(9), _t(12)), _ses(_t(13), _t(17)),
            _ses(_t(10, kun=9), _t(11, kun=9), kun="2026-09-09"),
        ])
        days = collect_client_days(CLIENT, _t(0))
    finally:
        workday_mod.iter_client_sessions = asl

    return (_check("2 ta kun", set(days) == {"2026-09-08", "2026-09-09"}, str(set(days)))
            & _check("1-kun 4 ta vaqt belgisi", len(days["2026-09-08"]["stamps"]) == 4,
                     str(len(days["2026-09-08"]["stamps"])))
            & _check("1-kun activeMin 420", days["2026-09-08"]["activeMin"] == 420.0,
                     str(days["2026-09-08"]["activeMin"]))
            & _check("2-kun activeMin 60", days["2026-09-09"]["activeMin"] == 60.0,
                     str(days["2026-09-09"]["activeMin"])))


def test_kun_chegarasi_birlashadi():
    print("  Ikki kompyuter: eng erta ulanish va eng kech uzilish olinadi")
    asl = workday_mod.iter_client_sessions
    try:
        # PC-1: 10:00-15:00,  PC-2: 09:00-18:00 -> kun 09:00-18:00 bo'lishi kerak
        workday_mod.iter_client_sessions = _fake_sessions([
            _ses(_t(10), _t(15)), _ses(_t(9), _t(18)),
        ])
        days = collect_client_days(CLIENT, _t(0))
    finally:
        workday_mod.iter_client_sessions = asl
    start, finish = build_day_agg(days["2026-09-08"]["stamps"])
    return (_check("kun boshi 09:00", start == _t(9), str(start))
            & _check("kun oxiri 18:00", finish == _t(18), str(finish)))


def test_ochiq_sessiya_kun_boshini_beradi():
    print("  Uzilishi yo'q sessiya kun boshlanishini baribir beradi")
    asl = workday_mod.iter_client_sessions
    try:
        workday_mod.iter_client_sessions = _fake_sessions([
            _ses(_t(9), _t(12)), _ses(_t(14), None),
        ])
        days = collect_client_days(CLIENT, _t(0))
    finally:
        workday_mod.iter_client_sessions = asl
    kun = days["2026-09-08"]
    start, finish = build_day_agg(kun["stamps"])
    return (_check("3 ta vaqt belgisi (ochiq sessiyada 1 ta)", len(kun["stamps"]) == 3,
                   str(len(kun["stamps"])))
            & _check("kun boshi 09:00", start == _t(9), str(start))
            & _check("kun oxiri 14:00 dan oldin ketmaydi", finish >= _t(12), str(finish))
            & _check("activeMin faqat yopilganidan 180", kun["activeMin"] == 180.0,
                     str(kun["activeMin"])))


def test_kun_hujjatida_sof_ish():
    print("  Kunlik hujjatda sof ish vaqti saqlanadi")
    doc = build_day_doc("C1", "PC-1", "2026-09-08", _t(9), _t(17), 4,
                        datetime(2026, 9, 8, 20), active_min=420.0)
    return (_check("activeMin maydoni", doc["activeMin"] == 420.0)
            & _check("durationMin baribir kun uzunligi", doc["durationMin"] == 480.0,
                     str(doc["durationMin"])))


if __name__ == "__main__":
    print("Ish kuni manbasi sinovlari\n")
    results = [
        test_active_minutes_oddiy(), test_active_minutes_bir_nechta_sessiya(),
        test_active_minutes_uzilishsiz_sessiya(), test_active_minutes_ikki_kompyuter(),
        test_kunlarga_ajratish(), test_kun_chegarasi_birlashadi(),
        test_ochiq_sessiya_kun_boshini_beradi(), test_kun_hujjatida_sof_ish(),
    ]
    print(f"\n{'HAMMASI O‘TDI ✓' if all(results) else 'SINOV YIQILDI ✗'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)
