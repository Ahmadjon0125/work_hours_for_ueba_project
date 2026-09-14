"""Sozlamalar sinovi: har bir qiymat `.env` dan o'zgarishi SHART.

Bu qo'riqchi test. Kimdir kelajakda `config.py` ga qattiq qiymat yozib qo'ysa
(masalan `LIMIT = 100`), shu test yiqiladi va buni darrov ko'rsatadi.

Ishga tushirish:  python tests/test_config.py
"""
import ast
import importlib
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

LOYIHA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FAYLI = os.path.join(LOYIHA, "config.py")
ENV_NAMUNA = os.path.join(LOYIHA, ".env.example")

# Turiga qarab sinov qiymati
NAMUNA = {int: "77", float: "7.5", str: "sinov-qiymati", tuple: "AAA,BBB,CCC"}


def _check(label, condition, detail=""):
    print(f"    {'✓' if condition else '✗'} {label}{'' if condition else '  <- ' + detail}")
    return condition


def _env_kalitlari(yol):
    """`.env` shaklidagi fayldan kalitlarni o'qiydi (izohlar hisobga olinmaydi)."""
    out = set()
    with open(yol, encoding="utf-8") as f:
        for qator in f:
            q = qator.strip()
            if q and not q.startswith("#") and "=" in q:
                out.add(q.split("=", 1)[0].strip())
    return out


def _kod_kalitlari():
    """config.py da `os.getenv(...)` bilan o'qiladigan barcha kalitlar."""
    src = open(CONFIG_FAYLI, encoding="utf-8").read()
    kalitlar = set(re.findall(r'os\.getenv\(\s*"([A-Z0-9_]+)"', src))
    # `_statuslar("X", ...)` kabi yordamchilar ham `.env` dan o'qiydi
    kalitlar |= set(re.findall(r'_statuslar\(\s*"([A-Z0-9_]+)"', src))
    return kalitlar


def test_env_namuna_toliq():
    """`.env.example` barcha sozlamani qamrab olishi SHART.

    Yangi sozlama qo'shilib, namunaga yozilmasa — serverga o'rnatgan odam
    uni umuman bilmay qoladi. Shu test buni oldini oladi.
    """
    print("  .env.example barcha sozlamani qamraydi")
    if not os.path.exists(ENV_NAMUNA):
        return _check(".env.example mavjud", False, "fayl yo'q")
    kod = _kod_kalitlari()
    namuna = _env_kalitlari(ENV_NAMUNA)
    yoq = sorted(kod - namuna)
    ortiqcha = sorted(namuna - kod)
    return (_check(".env.example mavjud", True)
            & _check(f"{len(kod)} ta sozlama qamralgan", not yoq, "yo'q: " + ", ".join(yoq))
            & _check("ortiqcha kalit yo'q", not ortiqcha, "ortiqcha: " + ", ".join(ortiqcha)))


def _sozlamalar():
    """config.py dagi modul darajasidagi BOSH HARFLI qiymatlar."""
    return sorted(k for k in dir(config)
                  if k.isupper() and not k.startswith("_")
                  and isinstance(getattr(config, k), (int, float, str, tuple)))


def test_hammasi_env_dan_oqiladi():
    """Har bir sozlama manba kodda os.getenv orqali olinishi kerak."""
    print("  Har bir sozlama manba kodda .env ga bog'langanmi")
    daraxt = ast.parse(open(CONFIG_FAYLI).read())
    manba = open(CONFIG_FAYLI).read().split("\n")

    qattiq = []
    for tugun in daraxt.body:
        if not isinstance(tugun, ast.Assign):
            continue
        for nishon in tugun.targets:
            if not (isinstance(nishon, ast.Name) and nishon.id.isupper()
                    and not nishon.id.startswith("_")):
                continue
            kod = "\n".join(manba[tugun.lineno - 1:tugun.end_lineno])
            # os.getenv to'g'ridan-to'g'ri yoki uni o'raydigan yordamchi orqali
            if "os.getenv" not in kod and "_statuslar(" not in kod:
                qattiq.append(nishon.id)

    return _check(f"qattiq yozilgan sozlama yo'q ({len(qattiq)} ta topildi)",
                  not qattiq, ", ".join(qattiq))


def test_env_haqiqatan_ustidan_yozadi():
    """Har bir sozlamani .env kaliti bilan almashtirib ko'ramiz."""
    print("  Har bir sozlama haqiqatan .env dan o'zgaradimi")
    nomlar = _sozlamalar()
    yiqilgan = []

    for nom in nomlar:
        eski = getattr(config, nom)
        namuna = NAMUNA.get(type(eski))
        if namuna is None:
            continue
        saqlangan = os.environ.get(nom)
        try:
            os.environ[nom] = namuna
            yangi_config = importlib.reload(config)
            yangi = getattr(yangi_config, nom)
            kutilgan = {int: 77, float: 7.5, str: "sinov-qiymati",
                        tuple: ("AAA", "BBB", "CCC")}[type(eski)]
            if yangi != kutilgan:
                yiqilgan.append(f"{nom} ({eski!r} -> {yangi!r}, kutilgan {kutilgan!r})")
        finally:
            if saqlangan is None:
                os.environ.pop(nom, None)
            else:
                os.environ[nom] = saqlangan
            importlib.reload(config)

    return (_check(f"{len(nomlar)} ta sozlama tekshirildi", len(nomlar) > 30, str(len(nomlar)))
            & _check(f"hammasi .env dan o'zgardi ({len(yiqilgan)} ta yiqildi)",
                     not yiqilgan, "; ".join(yiqilgan[:4])))


def test_notogri_qiymat_tizimni_buzmaydi():
    """Noto'g'ri qiymat berilsa xavfsiz defaultga qaytadi, xato tashlamaydi."""
    print("  Noto'g'ri qiymatlar xavfsiz ushlanadi")
    ok = True
    tekshiruv = [
        ("ANOMALY_Z_THRESHOLD", "0", lambda c: c.ANOMALY_Z_THRESHOLD > 0),
        ("ANOMALY_Z_THRESHOLD", "-5", lambda c: c.ANOMALY_Z_THRESHOLD > 0),
        ("ANOMALY_Z_FULL_SCALE", "0.5", lambda c: c.ANOMALY_Z_FULL_SCALE > c.ANOMALY_Z_THRESHOLD),
    ]
    for kalit, qiymat, shart in tekshiruv:
        saqlangan = os.environ.get(kalit)
        try:
            os.environ[kalit] = qiymat
            c = importlib.reload(config)
            ok &= _check(f"{kalit}={qiymat} -> xavfsiz qiymat ({getattr(c, kalit)})", shart(c))
        finally:
            if saqlangan is None:
                os.environ.pop(kalit, None)
            else:
                os.environ[kalit] = saqlangan
            importlib.reload(config)
    return ok


def test_vazn_oraligi():
    """Detector vazni [0, 1] dan tashqarida berilsa siqiladi."""
    print("  Detector vazni chegaralanadi")
    saqlangan = os.environ.get("DETECTOR_WEIGHT_WORKING_HOURS")
    try:
        os.environ["DETECTOR_WEIGHT_WORKING_HOURS"] = "9"
        a = config.detector_weight("workingHours")
        os.environ["DETECTOR_WEIGHT_WORKING_HOURS"] = "-3"
        b = config.detector_weight("workingHours")
    finally:
        if saqlangan is None:
            os.environ.pop("DETECTOR_WEIGHT_WORKING_HOURS", None)
        else:
            os.environ["DETECTOR_WEIGHT_WORKING_HOURS"] = saqlangan
    return (_check("9 -> 1.0", a == 1.0, str(a)) & _check("-3 -> 0.0", b == 0.0, str(b)))


if __name__ == "__main__":
    print("Sozlamalar sinovi\n")
    results = [
        test_hammasi_env_dan_oqiladi(),
        test_env_haqiqatan_ustidan_yozadi(),
        test_notogri_qiymat_tizimni_buzmaydi(),
        test_vazn_oraligi(),
        test_env_namuna_toliq(),
    ]
    print(f"\n{'HAMMASI O‘TDI ✓' if all(results) else 'SINOV YIQILDI ✗'} "
          f"({sum(results)}/{len(results)})")
    sys.exit(0 if all(results) else 1)
