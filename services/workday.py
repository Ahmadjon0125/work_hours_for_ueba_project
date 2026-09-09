"""Ish kunining boshi, oxiri va sof ish vaqti — `agentsessionstatuses` dan.

Manba bitta: agentning o'z hozirlik qaydlari. Ular faollikdan chiqarilgan
xulosa emas — agent tizimga kirish, chiqish, ekranni qulflash va ochish
hodisalarining o'zini yuboradi.

Olti xil status uch juftlik hosil qiladi:

    LOGON          <-> LOGOFF               tizimga kirish / chiqish
    UNLOCK         <-> LOCK                 ekranni ochish / qulflash
    REMOTE_CONNECT <-> REMOTE_DISCONNECT    masofadan ulanish / uzilish

Kun boshi — birinchi hodisa, oxiri — oxirgi hodisa. Bundan tashqari
`activeMin` hisoblanadi: ochilish va qulflanish oralig'idagi sof ish
daqiqalari (tanaffuslar chiqarib tashlangan).
"""
from collections import defaultdict

import config
from services.mongo import iter_client_sessions

# Hodisaning ma'nosi: ish boshlanishimi yoki tugashimi.
# Agent status nomlarini o'zgartirsa yoki yangisini qo'shsa — kodga emas,
# `.env` dagi SESSION_START_STATUSES / SESSION_END_STATUSES ga tegiladi.
SESSION_START = config.SESSION_START_STATUSES
SESSION_END = config.SESSION_END_STATUSES


def collect_client_days(client, window_start, window_end=None):
    """Bitta client uchun kunlik xom ma'lumot.

    Qaytaradi: {"2026-09-08": {"stamps": [datetime, ...], "activeMin": float}}

    Oyna: `[window_start, window_end)`. `window_end` berilmasa yuqori chegara
    yo'q — trigger shunday ishlatadi, bugungi tugallanmagan kun ham kerak.
    """
    days = defaultdict(lambda: {"stamps": [], "activeMin": None})
    hodisalar = defaultdict(list)          # sana -> [(dt, status), ...]

    for _, events in iter_client_sessions(client, window_start, window_end):
        for dt, status in events:
            kun = dt.strftime("%Y-%m-%d")
            days[kun]["stamps"].append(dt)
            hodisalar[kun].append((dt, status))

    for kun, evs in hodisalar.items():
        days[kun]["activeMin"] = active_minutes(evs)

    return dict(days)


def active_minutes(events):
    """Ochilishdan qulflanishgacha bo'lgan oraliqlar yig'indisi (daqiqa).

    Bu QUYI chegara: juftini topmagan hodisalar hisobga olinmaydi. Masalan kun
    LOCK bilan boshlansa (odam kechqurundan beri kirgan), o'sha ochiq oraliq
    sanalmaydi — sun'iy cho'zib yuborishdan ko'ra kam ko'rsatgan yaxshi.

    Oxirgi oraliq ochiq qolsa (kun LOGOFF'siz tugasa) u kunning oxirgi
    hodisasigacha yopiladi.

    Hodisalar tartibsiz kelsa ham to'g'ri ishlaydi — o'zi saralaydi.
    """
    if not events:
        return None

    evs = sorted(events)
    jami = 0.0
    ochiq = None
    for dt, status in evs:
        if status in SESSION_START:
            if ochiq is None:
                ochiq = dt
        elif status in SESSION_END:
            if ochiq is not None:
                jami += (dt - ochiq).total_seconds() / 60.0
                ochiq = None
    if ochiq is not None:
        jami += (evs[-1][0] - ochiq).total_seconds() / 60.0
    return round(jami, 2)
