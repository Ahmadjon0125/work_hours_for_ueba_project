"""Ish kunining boshi, oxiri va sof ish vaqti — `agentsessions` dan.

Manba bitta: agentning server bilan ulanish sessiyalari. DLP har bir
(xodim, kompyuter, kun) uchun bitta yozuv yuritadi:

    connectTime     — agent o'sha kuni birinchi marta qachon ulandi
    disconnectTime  — oxirgi marta qachon uzildi
    dateStr         — yozuv qaysi kunga tegishli

Kun ichida qayta ulanilsa DLP faqat `disconnectTime` ni yangilaydi,
`connectTime` esa tegilmaydi. Shuning uchun ular to'g'ridan-to'g'ri kunning
boshi va oxiri bo'lib xizmat qiladi — qo'shimcha hisob-kitob kerak emas.

Bir xodimda ikkita kompyuter bo'lsa, o'sha kunga ikkita yozuv tushadi.
Kun chegaralari ular bo'ylab birlashtiriladi: eng erta ulanish va eng kech
uzilish.

`disconnectTime` bo'sh bo'lishi mumkin — sessiya hali tugamagan yoki ertangi
kunga o'tib ketgan. Bunday yozuv kun BOSHLANISHI uchun ishlatiladi, lekin
TUGASHI uchun ishlatilmaydi: bo'sh uzilishni "yarim tungacha ishladi" deb
talqin qilish xato bo'lardi.
"""
from collections import defaultdict

from services.mongo import iter_client_sessions


def collect_client_days(client, window_start, window_end=None):
    """Bitta client uchun kunlik xom ma'lumot.

    Qaytaradi: {"2026-09-08": {"stamps": [datetime, ...], "activeMin": float}}

    `stamps` — o'sha kunning barcha ulanish va uzilish vaqtlari. Chaqiruvchi
    undan `min()`/`max()` bilan kun chegaralarini oladi (`build_day_agg`),
    shuning uchun bir nechta kompyuter avtomatik birlashadi.

    Oyna: `[window_start, window_end)`. `window_end` berilmasa yuqori chegara
    yo'q — trigger shunday ishlatadi, bugungi tugallanmagan kun ham kerak.
    """
    days = defaultdict(lambda: {"stamps": [], "activeMin": None})
    sessiyalar = defaultdict(list)          # sana -> [sessiya, ...]

    for _, sessions in iter_client_sessions(client, window_start, window_end):
        for ses in sessions:
            kun = ses["date"]
            days[kun]["stamps"].append(ses["connect"])
            if ses["disconnect"] is not None:
                days[kun]["stamps"].append(ses["disconnect"])
            sessiyalar[kun].append(ses)

    for kun, arr in sessiyalar.items():
        days[kun]["activeMin"] = active_minutes(arr)

    return dict(days)


def active_minutes(sessions):
    """Tarmoqda o'tkazilgan sof daqiqalar: sessiyalar davomiyligi yig'indisi.

    Bu QUYI chegara: uzilishi yozilmagan sessiya hisobga olinmaydi. Uni kun
    oxirigacha cho'zish mumkin edi, lekin bo'sh `disconnectTime` ko'pincha
    "sessiya ertangi kunga o'tdi" degani — sun'iy cho'zishdan ko'ra kam
    ko'rsatgan yaxshi.

    `durationMin` dan farqi: u kunning birinchi ulanishidan oxirgi uzilishigacha
    bo'lgan to'liq oraliq (tanaffuslar ichida), bu esa faqat tarmoqda
    turilgan vaqt.
    """
    if not sessions:
        return None

    jami = 0.0
    topildi = False
    for ses in sessions:
        if ses["disconnect"] is None:
            continue
        jami += (ses["disconnect"] - ses["connect"]).total_seconds() / 60.0
        topildi = True
    return round(jami, 2) if topildi else None
