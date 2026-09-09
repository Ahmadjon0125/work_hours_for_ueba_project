"""Ish kunining boshi va oxiri qaysi manbadan olinishini hal qiladi.

Ikkita manba bor (`config.WORKDAY_SOURCE`):

  activity — 16 ta faollik collection'i. Kunning birinchi va oxirgi eventi
             ish vaqti deb olinadi. Agent hodisalariga bog'liq emas, lekin
             faollikdan XULOSA chiqaradi: fon jarayoni ham event bergani uchun
             kun sun'iy cho'zilishi mumkin. Har client uchun 16 ta so'rov.

  session  — `agentsessionstatuses`. Agentning o'zi yuboradigan hozirlik
             qaydlari: LOGON/UNLOCK ish boshlanishi, LOGOFF/LOCK tugashi,
             REMOTE_CONNECT/DISCONNECT masofadan ulanish. Bitta so'rov, va
             faollikdan xulosa emas — haqiqiy hozirlik.

Ikkala manba bitta shaklda qaytaradi, shuning uchun collector va trigger
kodida farq yo'q.
"""
from collections import defaultdict

import config
from services.mongo import iter_client_sessions, iter_client_timestamps

# Sessiya hodisalarining ma'nosi
SESSION_START = ("LOGON", "UNLOCK", "REMOTE_CONNECT")
SESSION_END = ("LOGOFF", "LOCK", "REMOTE_DISCONNECT")


def collect_client_days(client, window_start, window_end=None):
    """Bitta client uchun kunlik xom ma'lumot.

    Qaytaradi `(days, manbalar)`:
      days     = {"2026-09-08": {"stamps": [datetime, ...], "activeMin": float|None}}
      manbalar = [(manba_nomi, [datetime, ...]), ...]   — collector logi uchun

    `activeMin` faqat session rejimida hisoblanadi: LOCK/UNLOCK oralig'idagi
    tanaffuslarni chiqarib tashlagan sof ish daqiqalari.
    """
    days = defaultdict(lambda: {"stamps": [], "activeMin": None})
    manbalar = []

    if config.WORKDAY_SOURCE == "session":
        hodisalar = defaultdict(list)   # sana -> [(dt, status), ...]
        for nom, events in iter_client_sessions(client, window_start, window_end):
            manbalar.append((nom, [dt for dt, _ in events]))
            for dt, status in events:
                kun = dt.strftime("%Y-%m-%d")
                days[kun]["stamps"].append(dt)
                hodisalar[kun].append((dt, status))
        for kun, evs in hodisalar.items():
            days[kun]["activeMin"] = active_minutes(evs)
    else:
        for nom, stamps in iter_client_timestamps(client, window_start, window_end):
            manbalar.append((nom, stamps))
            for dt in stamps:
                days[dt.strftime("%Y-%m-%d")]["stamps"].append(dt)

    return dict(days), manbalar


def active_minutes(events):
    """LOGON/UNLOCK dan LOGOFF/LOCK gacha bo'lgan oraliqlar yig'indisi (daqiqa).

    Bu QUYI chegara: juftini topmagan hodisalar hisobga olinmaydi. Masalan kun
    LOCK bilan boshlansa (odam kechqurundan beri kirgan), o'sha ochiq oraliq
    sanalmaydi — sun'iy cho'zib yuborishdan ko'ra kam ko'rsatgan yaxshi.

    Oxirgi oraliq ochiq qolsa (kun LOGOFF'siz tugasa) u kunning oxirgi
    hodisasigacha yopiladi.
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
