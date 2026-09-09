"""Ball, xavf va status matematikasi — chegaralar FAQAT shu faylda.

`utils/helpers.get_status` va `STATUS_COLORS` shu yerga ko'chdi: helpers umumiy
yordamchilar uchun, siyosat (chegara/status) esa detector paketiga tegishli.
"""
import math

import config

# Eski 4 pog'ona (severe/anomaly/watch/normal) bekor qilindi — 3 holat qoldi.
STATUS_COLORS = {
    "anomaly": "red",
    "normal": "green",
    "insufficient": "gray",
}


def round_half_up(x):
    """0.5 ni doim yuqoriga yaxlitlaydi.

    Python'ning o'z round() i "bankir yaxlitlashi" qiladi: round(24.5) -> 24,
    round(25.5) -> 26. Ball jadvalida bu jim xatolar berardi.
    """
    return int(math.floor(x + 0.5))


def severity_score(z_out):
    """Chetlanish darajasi: zOut -> 1..100 butun ball.

        ball = 100 · (zOut − T) / (ZFULL − T)          T = ANOMALY_Z_THRESHOLD

    Ya'ni chegaradan (zOut = T) qanchalik uzoqlashgani o'lchanadi, xodimning
    O'Z og'ishi (σ) birligida. Beqaror ishlaydigan xodimda bir soatlik chiqish
    kam ball oladi, har kuni bir xil keladigan xodimda esa ko'p — chunki
    ikkinchisi uchun bu haqiqatan g'ayrioddiy.

    `ANOMALY_Z_FULL_SCALE` (default 3.0) da 100 ga yetadi va o'sha joyda qoladi.

    `z_out is None` — σ = 0 bo'lgan holat: xodim shu hafta kuni sekundma-sekund
    bir xil kelgan, demak har qanday chiqish cheksiz uzoq. Bunda 100 beriladi.

    Chetlanish bo'lgan kun hech qachon 0 ball olmaydi (minimal 1), aks holda
    "chetlanish, lekin ball 0" degan ziddiyat chiqardi.
    """
    if z_out is None:
        return 100
    t, full = config.ANOMALY_Z_THRESHOLD, config.ANOMALY_Z_FULL_SCALE
    return max(1, round_half_up(100.0 * min(1.0, (z_out - t) / (full - t))))


def combine_risk(results):
    """Bir nechta detector balidan bitta riskScore (noisy-OR, vazn bilan).

        toza_qolish = KO'PAYTMA(1 - ball_i/100 * vazn_i)
        riskScore   = 100 * (1 - toza_qolish)

    Ma'nosi: har bir detector "toza qolish" ehtimolini kamaytiradi. Bitta kuchli
    signal ham, ko'p kichik signal ham riskni oshiradi, lekin 100 dan oshmaydi.

    Bitta detector va vazn 1.0 bo'lganda riskScore aynan uning baliga teng.
    Baholanmagan detectorlar hisobga olinmaydi; bittasi ham qolmasa -> None.
    """
    clean = 1.0
    used = 0
    for r in results:
        if not r.evaluated:
            continue
        clean *= 1.0 - (r.score / 100.0) * r.weight
        used += 1
    if used == 0:
        return None
    return round_half_up(100.0 * (1.0 - clean))


def status_for(evaluated_any, is_anomaly):
    """(status, statusColor). Uch holat: anomaly / normal / insufficient.

    `evaluated_any` — hech bo'lmasa bitta detector kunni baholay oldimi.
    Baholay olmagan bo'lsa `insufficient`: "toza" deb aytish yolg'on bo'lardi.
    """
    if not evaluated_any:
        return "insufficient", STATUS_COLORS["insufficient"]
    if is_anomaly:
        return "anomaly", STATUS_COLORS["anomaly"]
    return "normal", STATUS_COLORS["normal"]
