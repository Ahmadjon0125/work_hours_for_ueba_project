"""Processor: job dagi kunlarni baseline bilan taqqoslab z-score hisoblaydi.

Sof funksiya — DB'ga tegmaydi, faqat job + baseline dan results document'lar quradi.
"""
from datetime import datetime

from utils.helpers import day_of_week, get_status, parse_to_datetime, to_minutes


def _z_scores(week, start, finish):
    """(zStart, zFinish). Erta kelish -> +, kech ketish -> +."""
    if not week:
        return None, None

    z_start = z_finish = None
    mean_start, std_start = week.get("meanStart"), week.get("stdStart")
    if mean_start is not None and std_start:
        z_start = round((mean_start - to_minutes(start)) / std_start, 3)

    mean_finish, std_finish = week.get("meanFinish"), week.get("stdFinish")
    if mean_finish is not None and std_finish:
        z_finish = round((to_minutes(finish) - mean_finish) / std_finish, 3)

    return z_start, z_finish


def evaluate_job(job, baseline_doc, now=None):
    """job + baseline -> results document'lari ro'yxati.

    baseline_doc None bo'lsa ham kunlar yo'qolmaydi: z'lar null, status insufficient.
    """
    now = now or datetime.now()
    weeks = (baseline_doc or {}).get("weeks") or {}
    hostname = job.get("hostname") or job["clientId"]
    full_name = job.get("fullName")

    docs = []
    for date_str, day in (job.get("days") or {}).items():
        start = parse_to_datetime(day.get("start"))
        finish = parse_to_datetime(day.get("finish"))
        if start is None or finish is None:
            continue

        weekday = day.get("dayOfWeek") or day_of_week(start)
        z_start, z_finish = _z_scores(weeks.get(weekday), start, finish)
        status, color = get_status(z_start, z_finish)

        docs.append({
            "clientId": job["clientId"],
            "hostname": hostname,
            "fullName": full_name,
            "date": date_str,
            "dayOfWeek": weekday,
            "start": start.strftime("%H:%M:%S"),
            "finish": finish.strftime("%H:%M:%S"),
            "durationMin": day.get("durationMin"),
            "eventCount": day.get("eventCount"),
            "zStart": z_start,
            "zFinish": z_finish,
            "status": status,
            "statusColor": color,
            "evaluatedAt": now.isoformat(timespec="seconds"),
        })
    return docs
