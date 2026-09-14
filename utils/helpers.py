"""Umumiy yordamchilar: vaqt funksiyalari, kunlik agregat, ism tanlash.

Status va ball hisobi bu yerda EMAS — u siyosat, `services/detectors/scoring.py` da.
Ish kuni qaysi manbadan olinishi ham bu yerda emas — `services/workday.py` da.
"""
import re
from datetime import datetime, timedelta, timezone

from dateutil import parser as date_parser

import config

DAYS_MAP = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
            4: "Friday", 5: "Saturday", 6: "Sunday"}

def now():
    """Ilova vaqti — naive, `.env` dagi TZ mintaqasida.

    `datetime.now()` o'rniga SHU ishlatiladi. Farqi: `datetime.now()`
    operatsion tizimning mintaqasini o'qiydi, bu esa `config.TIMEZONE` ni.
    Server UTC da sozlangan bo'lsa ham ilova Toshkent vaqtida ishlaydi.

    Nima uchun naive: manbadagi vaqtlar ham naive (DLP mahalliy vaqtni
    saqlaydi, pymongo uni tzinfo'siz qaytaradi). Ikkalasi bir turda
    bo'lmasa Python taqqoslashda TypeError beradi.
    """
    if config.TIMEZONE is None:
        return datetime.now()
    return datetime.now(config.TIMEZONE).replace(tzinfo=None)


def utc_now():
    """Naive UTC — faqat server soatlarini taqqoslash uchun."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def parse_to_datetime(val):
    """Istalgan ko'rinishdagi vaqtni naive lokal datetime ga keltiradi. Xato -> None."""
    if val is None:
        return None
    try:
        if isinstance(val, datetime):
            if val.tzinfo is not None:
                return val.astimezone().replace(tzinfo=None)
            return val
        if isinstance(val, bool):
            return None
        if isinstance(val, (int, float)):
            # 1e11 dan kichik -> soniya, aks holda millisekunda
            return datetime.fromtimestamp(val if val < 1e11 else val / 1000.0)
        if isinstance(val, str):
            return date_parser.parse(val).replace(tzinfo=None)
    except Exception:
        return None
    return None


def to_minutes(dt):
    """datetime -> 00:00 dan boshlab daqiqa (float)."""
    return dt.hour * 60 + dt.minute + dt.second / 60.0


def sample_std(values):
    """Sample standart og'ish (n-1). n < 2 -> None."""
    n = len(values)
    if n < 2:
        return None
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / (n - 1)
    return var ** 0.5


def day_of_week(d):
    """date yoki datetime -> 'Monday'..'Sunday'."""
    return DAYS_MAP[d.weekday()]


def build_day_agg(tss):
    """Bir kunning timestamp'laridan (start, finish) chiqaradi.

    0 ta  -> None (kun mavjud emas)
    1 ta  -> start = ts, finish = min(ts + SINGLE_EVENT_STAY_HOURS, shu kun 23:59:59)
    2+ ta -> start = min(tss), finish = max(tss)
    """
    if not tss:
        return None
    if len(tss) == 1:
        start = tss[0]
        end_of_day = start.replace(hour=23, minute=59, second=59, microsecond=0)
        finish = min(start + timedelta(hours=config.SINGLE_EVENT_STAY_HOURS), end_of_day)
        return start, finish
    return min(tss), max(tss)


def duration_minutes(start, finish):
    return round((finish - start).total_seconds() / 60.0, 2)


_GENERIC_NAME = re.compile(r"^user[\s_-]*\d*$", re.IGNORECASE)


def display_name(hostname, full_name=None, first_name=None, last_name=None):
    """`clients` dagi ismdan ko'rsatishga yaroqlisini tanlaydi, bo'lmasa None.

    DLP bazasida ism maydonlari to'liq emas va ko'pincha login'ning takrori
    (login takrori) yoki umumiy o'rinbosar ("user_1", 5 ta clientda bir xil).
    Shunday hollarda ism ko'rsatilmaydi — hostname o'zi aniqroq.
    """
    name = (full_name or "").strip()
    if not name:
        name = " ".join(p for p in [(first_name or "").strip(), (last_name or "").strip()] if p)
    if not name:
        return None

    login = (hostname or "").split("@")[0].lstrip("@").strip().lower()
    if name.lower() == login or _GENERIC_NAME.match(name):
        return None
    return name


def build_day_doc(client_id, hostname, date_str, start, finish, event_count, now,
                  full_name=None, active_min=None):
    """raw_data_for_train va trigger_data uchun umumiy kunlik document.

    `active_min` — sof ish daqiqalari: ochilish va qulflanish oralig'idagi
    vaqt, tanaffuslar chiqarib tashlangan. `durationMin` esa kunning to'liq
    uzunligi (boshidan oxirigacha), tanaffuslar bilan birga.
    """
    return {
        "clientId": client_id,
        "hostname": hostname,
        "fullName": full_name,
        "date": date_str,
        "dayOfWeek": day_of_week(start),
        "start": start.isoformat(timespec="seconds"),
        "finish": finish.isoformat(timespec="seconds"),
        "durationMin": duration_minutes(start, finish),
        "eventCount": event_count,
        "activeMin": active_min,
        "updatedAt": now.isoformat(timespec="seconds"),
    }


def date_str_days_ago(now, days):
    """(now - days) sanasining 'YYYY-MM-DD' ko'rinishi — pruning filtrlari uchun."""
    return (now - timedelta(days=days)).strftime("%Y-%m-%d")
