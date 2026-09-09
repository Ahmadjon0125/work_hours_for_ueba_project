"""Detector ro'yxati va natijalarni bitta xulosaga birlashtirish.

Yangi detector qo'shish: import qiling va fayl oxiridagi `register(...)` ga
qo'shing. Avtomatik topish (pkgutil) ATAYLAB ishlatilmadi — u import tartibi va
jim yutilgan xatolar bilan bog'liq muammolar keltiradi; bu ro'yxat esa grep
bilan bir zumda topiladi.
"""
import re
from dataclasses import dataclass

from services.detectors.base import DetectorResult
from services.detectors.scoring import combine_risk, status_for
from services.detectors.working_hours import WorkingHoursDetector
from utils.logger import get_logger

log = get_logger("detectors")

# Detector nomi Mongo maydon nomiga aylanadi (`triggers.workingHours`) —
# nuqta, $ va bo'sh joy bo'lmasligi kerak.
_NAME_RE = re.compile(r"^[a-z][A-Za-z0-9]*$")

_REGISTRY = []


@dataclass(frozen=True)
class RunOutcome:
    """Bir kun bo'yicha barcha detectorlarning umumiy xulosasi."""
    status: str
    status_color: str
    is_anomaly: bool
    anomaly_score: int | None
    risk_score: int | None
    triggers: dict            # {"workingHours": True}
    triggered_names: list     # ["workingHours"]
    detectors: dict           # {"workingHours": {...}}
    fields: dict              # natijaning ustki darajasiga qo'shiladiganlar


def register(detector):
    """Detectorni ro'yxatga qo'shadi. Nomi noto'g'ri yoki takroriy bo'lsa — xato."""
    if not _NAME_RE.match(detector.name or ""):
        raise ValueError(f"Detector nomi noto'g'ri: {detector.name!r} "
                         "(lowerCamelCase, harf va raqamlardan iborat bo'lsin)")
    if any(d.name == detector.name for d in _REGISTRY):
        raise ValueError(f"Detector nomi takrorlandi: {detector.name}")
    _REGISTRY.append(detector)
    return detector


def all_detectors():
    return list(_REGISTRY)


def run(ctx, detectors=None):
    """Barcha detectorlarni ishlatib bitta RunOutcome quradi.

    `detectors` — testlar uchun ro'yxatni almashtirish imkoni.
    """
    results = []
    for det in (all_detectors() if detectors is None else detectors):
        try:
            results.append(det.evaluate(ctx))
        except Exception as e:
            # Bitta detectorning xatosi butun kunni yo'qotmasin: aks holda worker
            # job'ni 3 marta qayta urinib, keyin BUTUNLAY tashlab yuborardi
            # (mq/worker.py) va o'sha kunlar hech qachon baholanmasdi.
            log.error("Detector %s xato berdi (%s %s): %s: %s",
                      det.name, ctx.client_id, ctx.date, type(e).__name__, e)
            results.append(DetectorResult(name=det.name, weight=det.weight,
                                          evaluated=False,
                                          error=f"{type(e).__name__}: {e}"))
    return combine(results)


def combine(results):
    """DetectorResult ro'yxati -> RunOutcome."""
    fields = {}
    for r in results:
        for key, value in r.fields.items():
            if key in fields:
                log.warning("Detector maydoni takrorlandi: %s (%s) — e'tiborsiz qoldirildi",
                            key, r.name)
                continue
            fields[key] = value

    evaluated = [r for r in results if r.evaluated]
    # anomalyScore = eng kuchli signal (vaznsiz), riskScore = vazn bilan
    # birlashmasi. Chetlanish bor-yo'qligini esa ball emas, detectorlarning
    # o'z bayroqlari hal qiladi.
    score = max((r.score for r in evaluated), default=None)
    risk = combine_risk(evaluated)
    is_anomaly = any(r.triggered for r in results)
    status, color = status_for(bool(evaluated), is_anomaly)

    return RunOutcome(
        status=status,
        status_color=color,
        is_anomaly=is_anomaly,
        anomaly_score=score,
        risk_score=risk,
        triggers={r.name: r.triggered for r in results},
        triggered_names=[r.name for r in results if r.triggered],
        detectors={r.name: r.as_doc() for r in results},
        fields=fields,
    )


# --- Ro'yxat: yangi detector shu yerga qo'shiladi ---
register(WorkingHoursDetector())
