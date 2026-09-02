"""Umumiy yordamchilar: 17 collection mapping, vaqt funksiyalari, kunlik agregat, status."""
from datetime import datetime, timedelta

from dateutil import parser as date_parser

import config

# Aktivlik collectionlari: nom -> (ID maydoni, [vaqt maydonlari])
#
# `activities` ATAYLAB YO'Q. U event jurnali emas — kunlik agregat jadvali:
# dateTime doim 00:00:00 (tekshirilgan: 155/155 yozuv), ichida allActiveTime,
# efficiencyWebTime kabi kunlik yig'indilar. Uni qo'shsak har kunning `start` i
# soxta 00:00 ga tushib, "ishga kelish vaqti" signali butunlay yo'qoladi.
COLLECTIONS = {
    "activewindows": ("clientId", ["datetime"]),
    "rdps":          ("clientId", ["connectTime", "disconnectTime"]),
    "screenshots":   ("clientId", ["dateTime"]),
    "keyloggers":    ("clientId", ["dateTime"]),
    "webvisitings":  ("clientId", ["dateTime"]),
    "telegrams":     ("clientId", ["dateTime"]),
    "whatsapps":     ("clientId", ["dateTime"]),
    "emails":        ("clientId", ["dateTime"]),
    "websearches":   ("clientId", ["dateTime"]),
    "websniffs":     ("clientId", ["dateTime"]),
    "usbmonitors":   ("clientId", ["dateTime"]),
    "usbsniffs":     ("clientId", ["dateTime"]),
    "filemonitors":  ("clientId", ["dateTime"]),
    "clipboards":    ("clientId", ["dateTime"]),
    "prints":        ("clientId", ["dateTime"]),
    "incidents":     ("employee", ["time"]),
}

DAYS_MAP = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
            4: "Friday", 5: "Saturday", 6: "Sunday"}

STATUS_COLORS = {
    "severe": "red",
    "anomaly": "darkyellow",
    "watch": "yellow",
    "normal": "green",
    "insufficient": "gray",
}


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


def get_status(z_start, z_finish):
    """z'lardan (status, statusColor) qaytaradi."""
    if z_start is None and z_finish is None:
        return "insufficient", STATUS_COLORS["insufficient"]
    z = max(abs(z_start or 0.0), abs(z_finish or 0.0))
    if z >= config.SEVERE_THRESHOLD:
        status = "severe"
    elif z >= config.Z_THRESHOLD:
        status = "anomaly"
    elif z >= config.WATCH_THRESHOLD:
        status = "watch"
    else:
        status = "normal"
    return status, STATUS_COLORS[status]


def build_day_doc(client_id, hostname, date_str, start, finish, event_count, now):
    """raw_data_for_train va trigger_data uchun umumiy kunlik document."""
    return {
        "clientId": client_id,
        "hostname": hostname,
        "date": date_str,
        "dayOfWeek": day_of_week(start),
        "start": start.isoformat(timespec="seconds"),
        "finish": finish.isoformat(timespec="seconds"),
        "durationMin": duration_minutes(start, finish),
        "eventCount": event_count,
        "updatedAt": now.isoformat(timespec="seconds"),
    }


def date_str_days_ago(now, days):
    """(now - days) sanasining 'YYYY-MM-DD' ko'rinishi — pruning filtrlari uchun."""
    return (now - timedelta(days=days)).strftime("%Y-%m-%d")
