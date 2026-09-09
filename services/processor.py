"""Processor: job dagi kunlarni detectorlar orqali baholaydi.

Sof funksiya — DB'ga tegmaydi. Baholash mantig'i `services/detectors/` da:
bu fayl faqat kontekst quradi va natija hujjatini yig'adi. Yangi detector
qo'shilganda BU FAYL O'ZGARMAYDI.
"""
from datetime import datetime

from services.detectors import registry
from services.detectors.base import DayContext
from utils.helpers import day_of_week, parse_to_datetime


def evaluate_job(job, baseline_doc, now=None):
    """job + baseline -> results document'lari ro'yxati.

    baseline_doc None bo'lsa ham kunlar yo'qolmaydi: ballar null, status
    `insufficient` bo'ladi.
    """
    now = now or datetime.now()
    baseline = baseline_doc or {}
    weeks = baseline.get("weeks") or {}
    hostname = job.get("hostname") or job["clientId"]
    full_name = job.get("fullName")

    docs = []
    for date_str, day in (job.get("days") or {}).items():
        start = parse_to_datetime(day.get("start"))
        finish = parse_to_datetime(day.get("finish"))
        if start is None or finish is None:
            continue

        weekday = day.get("dayOfWeek") or day_of_week(start)
        ctx = DayContext(
            client_id=job["clientId"],
            hostname=hostname,
            full_name=full_name,
            date=date_str,
            day_of_week=weekday,
            start=start,
            finish=finish,
            duration_min=day.get("durationMin"),
            active_min=day.get("activeMin"),
            event_count=day.get("eventCount"),
            day=day,
            baseline=baseline,
            week=weeks.get(weekday) or {},
            now=now,
        )
        out = registry.run(ctx)

        docs.append({
            "clientId": job["clientId"],
            "hostname": hostname,
            "fullName": full_name,
            "date": date_str,
            "dayOfWeek": weekday,
            "start": start.strftime("%H:%M:%S"),
            "finish": finish.strftime("%H:%M:%S"),
            # Kun uzunligi: birinchi hodisadan oxirgisigacha
            "durationMin": day.get("durationMin"),
            # Sof ish vaqti: tanaffuslar chiqarib tashlangan (services/workday.py)
            "activeMin": day.get("activeMin"),
            "eventCount": day.get("eventCount"),
            # Detectorlarning ustki darajaga chiqaradigan maydonlari:
            # zStart, zFinish, usualStart, usualFinish, stdStart, stdFinish.
            # Ular natijaning ichida saqlanadi — shunda natija o'zi-o'ziga
            # yetarli bo'ladi va dashboard "odatda qachon kelardi" ni joriy
            # baseline'dan izlamaydi (versiya nomuvofiqligi bo'lmaydi, ARCH-02).
            **out.fields,
            "isAnomaly": out.is_anomaly,
            # Eng kuchli detector bali (vaznsiz). Baholanmagan kunda None —
            # 0 emas, aks holda u dashboard'da "ideal kun" bo'lib ko'rinardi.
            "anomalyScore": out.anomaly_score,
            # Barcha detectorlarning vazn bilan birlashmasi (noisy-OR).
            "riskScore": out.risk_score,
            "status": out.status,            # anomaly | normal | insufficient
            "statusColor": out.status_color,
            # Tez tekshirish uchun: {"workingHours": true}
            "triggers": out.triggers,
            # Massiv — bitta multikey indeks barcha detectorlar bo'yicha
            # filtrni qoplaydi (map bo'lsa har nom uchun alohida indeks kerak).
            "triggeredDetectors": out.triggered_names,
            # Har detectorning bali, vazni va sababi
            "detectors": out.detectors,
            # Qaysi baseline versiyasi bilan baholangani (ARCH-02)
            "baselineId": baseline.get("baselineId"),
            "evaluatedAt": now.isoformat(timespec="seconds"),
        })
    return docs
