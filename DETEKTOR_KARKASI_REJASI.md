# Detector karkasi + yangi baseline grafigi

## Context

Hozir pipeline faqat bitta narsani biladi — ish vaqti — va natijani 4 pog'onali
`status` (normal/watch/anomaly/severe) bilan qaytaradi. Ikkita muammo bor:

1. **Kengaymaydi.** Kelajakda USB faolligi, ma'lumot hajmi kabi yangi detectorlar
   qo'shilganda `processor.py` ni har safar qayta yozish kerak bo'ladi va har
   detector natijasini bitta umumiy xavf raqamiga aylantirish yo'li yo'q.
2. **Dashboarddagi haftalik grafik o'qilmaydi.** Undagi nuqtalar (ko'k = kelish,
   sariq = ketish, har hafta kunida o'nlab nuqta ustma-ust) nimani anglatishini
   tushunib bo'lmaydi.

Natijada: har kun uchun `isAnomaly` (bor/yo'q), `anomalyScore` (0–100), va
detectorlar birlashmasidan `riskScore` chiqadigan karkas quriladi; haftalik
grafik o'rniga har kunning kelish/ketish vaqti baseline oralig'i ustida
yashil/qizil nuqta bilan ko'rsatiladigan grafik chiziladi.

---

## Qabul qilingan qarorlar

| # | Qaror |
|---|---|
| 1 | 4 pog'ona bekor. 3 holat: `anomaly` (\|z\| > 1.0), `normal`, `insufficient` (baseline yo'q) |
| 2 | `WATCH/Z/SEVERE_THRESHOLD` o'rniga bitta `ANOMALY_Z_THRESHOLD` (default 1.0) |
| 3 | `anomalyScore` — butun son 0–100, **50 = chegara**, ya'ni `isAnomaly == (anomalyScore >= 50)` |
| 4 | `riskScore` — vaznli noisy-OR (to'ldiruvchi ko'paytma) |
| 5 | Vazn kodda default, `.env` dagi `DETECTOR_WEIGHT_*` ustidan yozadi |
| 6 | To'liq `services/detectors/` registry paketi, hozircha bitta detector |
| 7 | Mavjud natijalar bir martalik skript bilan qayta hisoblanadi |
| 8 | Haftalik grafik (`drawWeeklyProfile`) yangisiga almashtiriladi; kunlik grafik tegilmaydi |

### Ball formulasi (T = `ANOMALY_Z_THRESHOLD` = 1.0)

```
|z| = max(|zStart|, |zFinish|)

|z| <  T :  ball = min(49, round_half_up(50 · |z| / T))            →  0..49
|z| >= T :  ball = round_half_up(50 + 50 · min(1, (|z|−T) / 2T))   → 50..100
```

z=0→0, 0.5→25, 1→50, 2→75, 3 va yuqori→100.

### riskScore

```
toza_qolish = ∏(1 − ball_i/100 · vazn_i)
riskScore   = round_half_up(100 · (1 − toza_qolish))
```

Bitta detector + vazn 1.0 → `riskScore == anomalyScore` (test bilan qulflanadi).

---

## A qism — Backend: detector karkasi

### Yangi paket `services/detectors/`

| Fayl | Mazmuni |
|---|---|
| `scoring.py` | `_round_half_up`, `anomaly_score(z_abs)`, `combine_risk(results)`, `status_from_score()`, `TRIGGER_SCORE = 50`, `STATUS_COLORS` (3 ta) |
| `base.py` | `DayContext` (dataclass), `DetectorResult` (dataclass), `Detector` bazasi |
| `working_hours.py` | `z_scores()`, `score_from_zs()`, `WorkingHoursDetector` |
| `registry.py` | `register()`, `run(ctx)`, `combine(results)`, `RunOutcome` |

**`DetectorResult` maydonlari:** `name, weight, evaluated, score, reason, details,
fields, error` + hisoblanadigan `triggered` xossasi (`evaluated and score >= 50`).

**`fields` mexanizmi — eng muhim dizayn qarori.** Dashboard (`compare()`,
`describe()`, `renderTable()`) va `tests/test_baseline_versions.py` `zStart`,
`zFinish`, `usualStart`, `usualFinish`, `stdStart`, `stdFinish` ni natijaning
**ustki darajasidan** o'qiydi. Bu 6 maydon `workingHours` detectoriga tegishli,
lekin ustki darajada qolishi shart. Yechim: detector ularni `fields` da
qaytaradi, registry birlashtiradi, `processor.py` esa `**out.fields` bilan
yoyadi — processor bironta detectorning maydonini bilmaydi.

> `skipped()` ham `fields` bilan qaytarilishi shart, aks holda
> `test_unevaluated_day_has_no_comparison` yiqiladi.

### `services/processor.py` — qayta yoziladi (~55 qator)

`evaluate_job(job, baseline_doc, now=None)` **imzosi o'zgarmaydi** →
`mq/worker.py` ga tegilmaydi. Yangi vazifasi faqat: `DayContext` qurish →
`registry.run(ctx)` → hujjat yig'ish. Yangi detector qo'shilganda bu fayl
o'zgarmaydi.

### `utils/helpers.py`

`get_status()` (108-121) va `STATUS_COLORS` (37-43) **o'chiriladi** — ular butun
repoda faqat `processor.py` dan chaqiriladi (tekshirilgan). Mantiq
`scoring.status_from_score()` ga ko'chadi.

### `config.py`

O'chadi: `WATCH_THRESHOLD`, `Z_THRESHOLD`, `SEVERE_THRESHOLD`.
Qo'shiladi: `ANOMALY_Z_THRESHOLD` (≤0 bo'lsa 1.0 ga qaytadi) va

```python
def detector_weight(name, default=1.0):
    """DETECTOR_WEIGHT_<UPPER_SNAKE> bo'lsa o'sha, bo'lmasa default. [0,1] ga siqiladi.
    Vazn 0 = "soya rejim": detector ishlaydi, natijaga yoziladi, riskScore ga ta'sir qilmaydi."""
```

`.env` dan uchala eski chegara **o'chirilsin** (aks holda jimgina e'tiborsiz qoladi).

### Natija hujjatiga qo'shiladigan maydonlar

```jsonc
"isAnomaly": true,
"anomalyScore": 75,              // eng kuchli detector bali; insufficient bo'lsa null
"riskScore": 75,                 // noisy-OR, vazn bilan; insufficient bo'lsa null
"status": "anomaly",             // anomaly | normal | insufficient
"triggers": { "workingHours": true },              // so'ralgan "nom: true/false"
"triggeredDetectors": ["workingHours"],            // massiv → bitta multikey indeks
"detectors": {
  "workingHours": { "triggered": true, "score": 75, "weight": 1.0,
                    "evaluated": true, "reason": "...", "details": {"z": 2.0, "axis": "start"} }
}
```

`insufficient` da `anomalyScore`/`riskScore` = **`null`**, `0` emas — aks holda
baholanmagan kun dashboardda "ideal kun" bo'lib ko'rinadi va risk bo'yicha
saralashda aralashadi.

### `services/mongo.py`, `api/routes.py`

- `results` ga 2 ta indeks: `{isAnomaly:1, date:-1}`, `{triggeredDetectors:1}`
- `_query_results()` ga 3 ta filtr: `is_anomaly`, `min_risk`, `trigger`
- `status` filtri o'zgarmaydi, faqat qiymatlari 3 taga qisqaradi

### `scripts/backfill_scores.py` (yangi papka)

Mavjud `results` yozuvlarini **o'z ichidagi** `zStart`/`zFinish` asosida qayta
baholaydi (baseline qayta o'qilmaydi — natija o'zi-o'ziga yetarli, ARCH-02).
Manba bazaga tegmaydi.

- Jonli kod bilan bir xil funksiyalarni chaqiradi (`score_from_zs`, `combine_risk`)
- **Default quruq yurish**, yozish uchun `--apply` shart
- Hisobot: `severe→anomaly: N`, `watch→anomaly: N`, `watch→normal: N` o'tish matritsasi
- Darvoza: `LOCAL_DB_NAME == DB_NAME` bo'lsa to'xtaydi; ekranda `mongodump` tavsiyasi
- Idempotent (`$set`), `bulk_write(ordered=False)` 500 talik partiyalarda
- `evaluatedAt` ga tegilmaydi; backfill belgisi `detectors.workingHours.details.source = "backfill"`

---

## B qism — Dashboard: yangi grafik

`drawWeeklyProfile()` (`dashboard/static/script.js:444-516`) **butunlay
o'chiriladi**, o'rniga `drawBaselineChart()` yoziladi. `renderChart()`
dispetcheri (257-316) shu yangi funksiyani chaqiradi. Kunlik grafik
(`drawDayChart`) va matritsa (`drawMatrix`) tegilmaydi.

### Spetsifikatsiya

- **X o'qi** — sanalar, har ustun bitta kun (o'sish tartibida)
- **Y o'qi** — sutka soatlari 00:00 → 24:00 (mavjud `y(mins)` formulasi)
- **Gray fon** — har ustunda bitta uzluksiz to'rtburchak:
  `(usualStart − stdStart)` dan `(usualFinish + stdFinish)` gacha.
  Misol: 9:00±10daq / 18:00±20daq → **08:50 – 18:20**. Boshqa yo'lak yo'q.
- **Kelish nuqtasi** `y(start)` da:
  - `[usualStart − stdStart, usualStart + stdStart]` ichida → **yashil**
  - tashqarisida → **qizil**
- **Ketish nuqtasi** `y(finish)` da: xuddi shunday, `usualFinish ± stdFinish` bo'yicha
- Baseline yo'q kun (`insufficient`) → gray fon chizilmaydi, nuqtalar kulrang
- Boshqa hech narsa yo'q: ustun ham, chiziq ham, matn yorlig'i ham

### Rang qoidasi — muhim nuqta

Rang **har nuqta uchun alohida**, kunning umumiy statusi bo'yicha emas:

```
kelish yashil  ⟺  |zStart|  <= 1.0
ketish yashil  ⟺  |zFinish| <= 1.0
```

Ya'ni bir kunda kelish yashil, ketish qizil bo'lishi mumkin. Bu to'g'ri va
foydali — `|z| <= 1` aynan "mean ± 1·std oralig'ida" degani, shuning uchun
**nuqta rangi gray fondagi o'z zonasiga to'liq mos keladi**, ziddiyat bo'lmaydi.

`zStart`/`zFinish` natijaning ustki darajasida turibdi (`fields` mexanizmi buni
kafolatlaydi), qo'shimcha API chaqiruvi kerak emas.

### Qayta ishlatiladigan mavjud kod

`el()`, `clearSvg()` (249-255), `hhmmssToMinutes()` (60-63), `minutesToHHMM()`
(54-57), `humanDate()` (38-42), `compare()` (67-95) — o'zgarishsiz. Har nuqtaga
`<title>` bolasi (mavjud uslub, tashqi tooltip kutubxonasi yo'q).

### Kosmetik tozalash (backfilldan **keyin**)

- `STATUS` xaritasidan (script.js:7-13) `severe`/`watch` olib tashlanadi
- `statusLegend` (273-278) 5 tadan 3 taga; yangi grafik uchun o'z legendasi
- `['watch','anomaly','severe'].includes(r.status)` (174, 220) → `r.isAnomaly`
- `style.css:123-125` dagi `.issue.severe` / `.issue.watch` qoidalari

---

## O'zgaradigan fayllar

**Yangi:** `services/detectors/{__init__,base,scoring,working_hours,registry}.py`,
`scripts/backfill_scores.py`, `tests/test_detectors.py`

**O'zgaradi:** `services/processor.py` (qayta yoziladi), `utils/helpers.py`
(`get_status` + `STATUS_COLORS` o'chadi), `config.py`, `.env`,
`services/mongo.py`, `api/routes.py`, `dashboard/static/script.js`,
`dashboard/static/style.css`, `README.md`, `UEBA_PIPELINE_ARCHITECTURE_V2.md`

**Tegilmaydi:** `mq/worker.py`, `services/trainer.py`, `services/collector.py`,
`services/trigger.py`, `tests/test_collector.py`, `tests/test_jobs.py`

---

## Bajarish tartibi

1. `config.py` — yangi chegara + `detector_weight()`, eskilarini o'chirish
2. `detectors/scoring.py` → `base.py` → `working_hours.py` → `registry.py`
3. `processor.py` qayta yozish + `helpers.py` dan `get_status`/`STATUS_COLORS` o'chirish
   *(1–3 bitta commit: oraliqda kod ishlamaydi)*
4. **Darvoza:** `python tests/test_baseline_versions.py` → 4/4 **o'zgarishsiz** o'tsin
5. `tests/test_detectors.py` yozish va o'tkazish
6. `services/mongo.py` indekslari + `api/routes.py` filtrlari
7. `.env` tozalash; pipeline'ni qayta ishga tushirib bitta trigger o'tishini kuzatish
8. `mongodump` → `backfill_scores.py` (quruq) → hisobotni ko'rish → `--apply`
9. Dashboard: `drawBaselineChart()` yozish, `drawWeeklyProfile()` o'chirish
10. Dashboard kosmetik tozalash + hujjatlar

---

## Tekshirish

**Testlar** (mavjud uslubda — `pytest` yo'q, har test `bool` qaytaradi, `sys.exit`):

```bash
python tests/test_baseline_versions.py   # 4/4 — mavjud xatti-harakat buzilmagani
python tests/test_detectors.py           # yangi
python tests/test_collector.py           # regressiya
python tests/test_jobs.py                # regressiya
```

`tests/test_detectors.py` da qulflanadigan xossalar:

| Test | Nimani ushlaydi |
|---|---|
| `test_score_table` | z=0→0, 0.5→25, 1→50, 2→75, 3→100 |
| `test_score_matches_flag` | z=0.00..4.00 (0.01 qadam) bo'ylab `isAnomaly == (score >= 50)` |
| `test_score_rounding` | `round()` bankir yaxlitlashi tuzog'i (`round(24.5)` → 24) |
| `test_risk_equals_score_single_detector` | ball 0..100: vazn 1.0 da `riskScore == anomalyScore` |
| `test_weight_scales_risk` | vazn 0.4 + ball 100 → 40; ikkita 50/1.0 → 75 |
| `test_insufficient_day` | baseline yo'q → `anomalyScore is None`, `riskScore is None`, `isAnomaly False` |
| `test_broken_detector_isolated` | xato tashlaydigan detector kunni yo'qotmaydi, `detectors.<nom>.error` yoziladi |
| `test_env_key_name` | `workingHours` → `DETECTOR_WEIGHT_WORKING_HOURS` |

**Uchdan uchigacha:**

```bash
venv/bin/python main.py          # trigger o'tishini kuting (yoki TRIGGER_INTERVAL_HOURS ni kichraytiring)
curl -s localhost:8000/api/results?limit=1 | python -m json.tool   # yangi maydonlar bormi
curl -s "localhost:8000/api/results?is_anomaly=true&limit=5"
```

Dashboard (http://localhost:8000): xodim tanlanganda ikkinchi grafik yangi
ko'rinishda bo'lsin — gray fon, ustida yashil/qizil nuqtalar. Tekshirish:
jadvalda "1 soat 40 daqiqa erta keldi" deb yozilgan kun grafikda **qizil**
kelish nuqtasi bo'lishi kerak.

---

## Ogohlantirishlar

1. **Anomaliyalar ulushi keskin oshadi.** Mavjud `results` da o'lchadim: hozirgi
   1.2 chegarasida baholangan 7 kundan 3 tasi chetlanish; **1.0 chegarasida
   4 tasi (57%)**. Namuna kichik, lekin yo'nalish aniq. Ma'lumot ko'paygach
   `ANOMALY_Z_THRESHOLD` ni `.env` dan sozlash kerak bo'lishi mumkin — aynan
   shuning uchun u bitta kalitga chiqarilyapti.

2. **Kunlarning aksariyati baholanmaydi.** Hozirgi 71 natijadan **64 tasi**
   `insufficient` — baseline hali yupqa (`MIN_DOW_SAMPLES=5`). Yangi grafikda
   ular gray fonsiz, kulrang nuqtalar bo'lib ko'rinadi. Bu mavjud holat,
   bu ish uni o'zgartirmaydi.

3. **Backfill qaytarib bo'lmaydi** — `status` qiymatlari ustiga yoziladi
   (`severe`/`watch` yo'qoladi). `mongodump` majburiy.

4. **`is_anomaly` filtri backfilldan oldingi hujjatlarni ko'rmaydi** (maydon
   umuman yo'q). Shuning uchun 8-qadam 6-qadamdan keyin turadi.

5. **Detector istisnosi ushlanmasa kunlar yo'qoladi:** `mq/worker.py:72-76`
   job'ni 3 marta qayta urinib, keyin butunlay tashlab yuboradi. Shuning uchun
   registry da har detector `try/except` ichida chaqiriladi.

6. **Detectorlar holatsiz bo'lishi shart** — 3 ta worker thread bir vaqtda
   `evaluate()` ni chaqiradi, `self` ga hech narsa yozilmasin.

7. **`.env` import paytida o'qiladi** — vazn o'zgartirilsa protsess qayta
   ishga tushirilishi kerak.

8. **`workingHours` vazni bugun 1.0 bo'lishi shart** (`riskScore == anomalyScore`
   bo'lishi uchun). Ikkinchi detector qo'shilganda uni 0.3–0.5 ga tushirish
   kerak bo'ladi — ish vaqtidan chetlanish ma'lumot o'g'irligi emas.
