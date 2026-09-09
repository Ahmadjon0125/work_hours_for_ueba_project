"""Detector interfeysi va umumiy ma'lumot tuzilmalari.

MUHIM: detectorlar HOLATSIZ bo'lishi shart. Registry ularni bir marta yaratadi,
`WORKER_COUNT` (3) ta thread esa bir vaqtda `evaluate()` ni chaqiradi —
`self` ga hech narsa yozilmasin.
"""
from dataclasses import dataclass, field
from datetime import datetime

import config


@dataclass(frozen=True)
class DayContext:
    """Bitta kunni baholash uchun kerak bo'ladigan hamma narsa.

    Yangi detectorlar ko'pincha yangi maydon talab qiladi, shuning uchun xom
    `day` hujjati va butun `baseline` ham uzatiladi — faqat qisqartma emas.
    """
    client_id: str
    hostname: str
    full_name: str | None
    date: str                 # "YYYY-MM-DD"
    day_of_week: str          # "Monday".."Sunday"
    start: datetime
    finish: datetime
    duration_min: float | None     # kun uzunligi (birinchi hodisadan oxirgisigacha)
    active_min: float | None       # sof ish vaqti (tanaffuslarsiz), bo'lmasa None
    event_count: int | None
    day: dict                 # job dagi xom kun hujjati
    baseline: dict            # butun baseline hujjati (bo'sh bo'lishi mumkin)
    week: dict                # baseline["weeks"][day_of_week] (bo'sh bo'lishi mumkin)
    now: datetime


@dataclass(frozen=True)
class DetectorResult:
    """Bitta detectorning bitta kun bo'yicha xulosasi.

    score     — 0..100. Har detector o'z signalini SHU shkalaga o'girishi shart.
    evaluated — False bo'lsa "baholab bo'lmadi" (baseline yo'q yoki xato);
                bu "baholandi, toza" dan farq qiladi va riskScore ga kirmaydi.
    fields    — natija hujjatining USTKI darajasiga qo'shiladigan maydonlar
                (masalan zStart/usualStart — dashboard ularni shu yerdan o'qiydi).
                Shu mexanizm tufayli processor bironta detectorning maydonini
                bilmaydi va yangi detector qo'shilganda o'zgarmaydi.
    details   — faqat shu detectorga tegishli qo'shimcha qiymatlar; natijada
                `detectors.<nom>.details` ichida saqlanadi. Hujjat shishib
                ketmasligi uchun faqat skalyar qiymatlar bo'lsin.
    """
    name: str
    weight: float
    evaluated: bool = True
    # Chetlanish bor-yo'qligi. Ball EMAS, shu bayroq hal qiladi — detector o'z
    # qoidasiga ko'ra belgilaydi (workingHours: oynadan tashqarida bo'lsa true,
    # hatto 1 daqiqa bo'lsa ham). Ball faqat "qanchalik" ni o'lchaydi.
    is_anomaly: bool = False
    score: int = 0
    reason: str | None = None         # o'zbekcha qisqa izoh (log va API uchun)
    details: dict = field(default_factory=dict)
    fields: dict = field(default_factory=dict)
    error: str | None = None

    @property
    def triggered(self):
        """Baholanmagan detector hech qachon chetlanish bermaydi."""
        return self.evaluated and self.is_anomaly

    def as_doc(self):
        """Natija hujjatiga yoziladigan ko'rinish."""
        doc = {
            "triggered": self.triggered,
            "score": self.score if self.evaluated else None,
            "weight": self.weight,
            "evaluated": self.evaluated,
            "reason": self.reason,
        }
        if self.details:
            doc["details"] = self.details
        if self.error:
            doc["error"] = self.error
        return doc


class Detector:
    """Barcha detectorlarning bazasi."""

    name = ""             # lowerCamelCase — Mongo maydon nomi bo'ladi
    default_weight = 1.0  # .env dagi DETECTOR_WEIGHT_* buni ustidan yozadi

    def __init__(self):
        self.weight = config.detector_weight(self.name, self.default_weight)

    def evaluate(self, ctx):
        """DayContext -> DetectorResult."""
        raise NotImplementedError

    # --- qulaylik konstruktorlari ---

    def result(self, is_anomaly, score, reason=None, details=None, fields=None):
        return DetectorResult(name=self.name, weight=self.weight,
                              is_anomaly=bool(is_anomaly), score=int(score),
                              reason=reason, details=details or {}, fields=fields or {})

    def skipped(self, reason, fields=None):
        """Baholab bo'lmadi: baseline yo'q yoki ma'lumot yetarli emas.

        `fields` ni baribir uzatish kerak — natija o'zi-o'ziga yetarli bo'lishi
        uchun taqqoslash maydonlari (null holida ham) o'rnida turishi shart.
        """
        return DetectorResult(name=self.name, weight=self.weight, evaluated=False,
                              score=0, reason=reason, fields=fields or {})
