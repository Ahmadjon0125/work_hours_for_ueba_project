"""Ish vaqti detectori: odatiy ish oynasidan TASHQARIDAGI faollik.

Qoida:

    lo = usualStart  − T·stdStart          (oynaning quyi cheti)
    hi = usualFinish + T·stdFinish         (oynaning yuqori cheti)

    start  < lo   -> oynadan OLDIN faollik  -> shubhali
    finish > hi   -> oynadan KEYIN faollik  -> shubhali
    ikkalasi ham oyna ichida                -> shubha YO'Q

Nega bu aniq ishlaydi: kunning barcha eventlari `start` va `finish` orasida
yotadi. Demak `start >= lo` va `finish <= hi` bo'lsa, o'sha kunning HAMMA
faolligi oyna ichida bo'ladi — alohida eventlarni tekshirish shart emas.

Chetlanish DARAJASI z-score bilan o'lchanadi (`details.zOut`): chegaradan
qanchalik uzoqlashgani, xodimning o'z σ birligida.

Diqqat: kech kelish va erta ketish endi shubhali EMAS. Ular oyna ichida qoladi.
Tizim intizomni emas, ish vaqtidan tashqaridagi faollikni kuzatadi.

Matematik eslatma: `lo = mean − T·σ` bo'lgani uchun "oynadan tashqarida" degani
aynan "zOut > T" degani. Ikkalasi bir xil qoidaning ikki ko'rinishi; qaror oyna
bilan qilinadi, chunki u σ = 0 bo'lganda ham ishlaydi.
"""
import config
from services.detectors.base import Detector
from services.detectors.scoring import severity_score
from utils.helpers import to_minutes

# Natijaning ustki darajasiga chiqadigan maydonlar. Dashboard (`compare`,
# grafik, jadval) va mavjud testlar ularni aynan shu yerdan o'qiydi.
FIELD_NAMES = ("zStart", "zFinish", "usualStart", "usualFinish",
               "stdStart", "stdFinish", "windowStart", "windowFinish")


def window_bounds(usual_start, usual_finish, std_start, std_finish):
    """Ish oynasi chegaralari daqiqada, yoki baseline bo'lmasa (None, None).

    `std` mavjud bo'lmasa 0 deb olinadi — oyna aynan o'rtachalar orasida bo'ladi.
    """
    if usual_start is None or usual_finish is None:
        return None, None
    t = config.ANOMALY_Z_THRESHOLD
    return (usual_start - t * (std_start or 0.0),
            usual_finish + t * (std_finish or 0.0))


def outside_minutes(lo, hi, start_min, finish_min):
    """(oldin, keyin) — oynadan tashqarida qolgan daqiqalar (manfiy bo'lmaydi)."""
    return max(0.0, lo - start_min), max(0.0, finish_min - hi)


def z_scores(week, start, finish):
    """(zStart, zFinish) — endi baholashda ishlatilmaydi, faqat ko'rsatish uchun.

    Jadvaldagi «odatdagidan 3 soat erta keldi» kabi izohlar shundan chiqadi.
    std falsy (0 yoki None) bo'lsa tegishli z = None.
    """
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


def evaluate_window(usual_start, usual_finish, std_start, std_finish,
                    start_min, finish_min):
    """Oyna qoidasini qo'llaydi -> (chetlanishmi, ball, details, sabab).

    Baseline bo'lmasa (None, None, None, None). Backfill skripti ham SHU funksiyani
    chaqiradi, shuning uchun jonli yo'l bilan qayta hisoblash yo'li hech qachon
    bir-biridan uzoqlashmaydi.
    """
    lo, hi = window_bounds(usual_start, usual_finish, std_start, std_finish)
    if lo is None:
        return None, None, None, None

    before, after = outside_minutes(lo, hi, start_min, finish_min)
    outside = max(before, after)

    # 1-qadam — CHETLANISHMI: oynadan tashqarida bo'lgan har qanday faollik,
    # hatto bir daqiqa bo'lsa ham. Oyna chegarasi bilan tekshiriladi, chunki u
    # σ = 0 bo'lganda ham ishlaydi (z esa nolga bo'linib ketardi).
    is_anomaly = outside > 0

    # 2-qadam — DARAJASI: z-score bilan, xodimning o'z σ birligida.
    # Faqat oynadan CHIQARUVCHI tomon olinadi:
    #   zStart  > T  ->  erta kelish (oynadan oldin)
    #   zFinish > T  ->  kech ketish (oynadan keyin)
    # Kech kelish (zStart < 0) va erta ketish (zFinish < 0) oyna ichida qoladi.
    z_out = _z_out(usual_start, usual_finish, std_start, std_finish,
                   start_min, finish_min)
    score = severity_score(z_out) if is_anomaly else 0

    details = {
        "zOut": None if z_out is None else round(z_out, 3),
        "outsideMin": round(outside, 1),      # xom qiymat — ball 100 da ham saqlanadi
        "beforeMin": round(before, 1),
        "afterMin": round(after, 1),
        "windowStart": round(lo, 1),
        "windowFinish": round(hi, 1),
    }
    return is_anomaly, score, details, _reason(before, after, lo, hi, z_out)


def _z_out(usual_start, usual_finish, std_start, std_finish, start_min, finish_min):
    """Oynadan chiqaruvchi tomonning z qiymati (eng kattasi), yoki None.

    None qaytishi = σ hech qayerda hisoblanmadi (σ = 0). Bu holda har qanday
    chiqish cheksiz uzoq hisoblanadi — `severity_score` unga 100 beradi.
    """
    zs = ((usual_start - start_min) / std_start) if std_start else None
    zf = ((finish_min - usual_finish) / std_finish) if std_finish else None
    mavjud = [z for z in (zs, zf) if z is not None]
    return max(mavjud) if mavjud else None


def _reason(before, after, lo, hi, z_out=None):
    """«ish oynasidan (08:50–16:20) 1 soat 12 daqiqa oldin faollik (z=1.23)»."""
    if before <= 0 and after <= 0:
        return f"faollik ish oynasi ichida ({_hhmm(lo)}–{_hhmm(hi)})"
    qismlar = []
    if before > 0:
        qismlar.append(f"{_human_minutes(before)} oldin")
    if after > 0:
        qismlar.append(f"{_human_minutes(after)} keyin")
    daraja = "" if z_out is None else f" (z={round(z_out, 2)})"
    return (f"ish oynasidan ({_hhmm(lo)}–{_hhmm(hi)}) "
            f"{' va '.join(qismlar)} faollik{daraja}")


def _hhmm(mins):
    """555 -> "09:15". Sutkadan chiqib ketgan qiymatlar ham to'g'ri ko'rsatiladi."""
    m = int(round(mins)) % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def _human_minutes(m):
    """107.4 -> "1 soat 47 daqiqa"."""
    m = int(round(abs(m)))
    if m < 60:
        return f"{m} daqiqa"
    hours, minutes = divmod(m, 60)
    return f"{hours} soat {minutes} daqiqa" if minutes else f"{hours} soat"


class WorkingHoursDetector(Detector):
    """Odatiy ish oynasidan tashqaridagi faollik."""

    name = "workingHours"
    default_weight = 1.0

    def evaluate(self, ctx):
        week = ctx.week or {}
        start_min, finish_min = to_minutes(ctx.start), to_minutes(ctx.finish)
        z_start, z_finish = z_scores(week, ctx.start, ctx.finish)

        lo, hi = window_bounds(week.get("meanStart"), week.get("meanFinish"),
                               week.get("stdStart"), week.get("stdFinish"))

        # Taqqoslash qiymatlari HAR DOIM yoziladi (ARCH-02: natija o'zi-o'ziga
        # yetarli). Baseline yo'q bo'lsa ular null holida turadi.
        fields = {
            "zStart": z_start,
            "zFinish": z_finish,
            "usualStart": week.get("meanStart"),
            "usualFinish": week.get("meanFinish"),
            "stdStart": week.get("stdStart"),
            "stdFinish": week.get("stdFinish"),
            # Dashboard kulrang fonni va nuqta ranglarini shulardan chizadi —
            # chegarani brauzerda qayta hisoblash shart emas.
            "windowStart": None if lo is None else round(lo, 1),
            "windowFinish": None if hi is None else round(hi, 1),
        }

        is_anomaly, score, details, reason = evaluate_window(
            week.get("meanStart"), week.get("meanFinish"),
            week.get("stdStart"), week.get("stdFinish"), start_min, finish_min)

        if score is None:
            return self.skipped("shu hafta kuni uchun baseline yo'q", fields=fields)

        return self.result(is_anomaly, score, reason=reason,
                           details=details, fields=fields)
