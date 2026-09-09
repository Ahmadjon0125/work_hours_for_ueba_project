# UEBA — Ish vaqti tahlili

Har bir xodim uchun **o'zining odatiy ish oynasini** o'rganadi, so'ng har kuni
shu oynadan **tashqarida** faollik bo'lganini tekshiradi. Ish vaqtidan
tashqaridagi faollik — DLP nuqtai nazaridan e'tibor talab qiladigan holat.

Ma'lumot manbai — DataGaze DLP tizimining MongoDB'sidagi
**`agentsessionstatuses`** collection'i: agent yuboradigan hozirlik qaydlari
(tizimga kirish/chiqish, ekranni ochish/qulflash, masofadan ulanish).

---

## Dashboard

![Dashboard: bitta xodim — xulosa, chetlanishli kunlar, ish oynasi grafigi va jadval](image.png)

*Bitta xodim tanlangan holat. Grafikda X — kunlar, Y — sutka soatlari;
kulrang fon — o'sha kunning ish oynasi; ikkita nuqta — birinchi va oxirgi
faollik (oyna ichida yashil, tashqarida qizil, baseline yo'q bo'lsa kulrang).*

![Barcha xodimlar: umumiy manzara matritsasi](image-1.png)

*Xodim tanlanmagan holat — qatorlar xodimlar, ustunlar kunlar.*

---

## Umumiy manzara

```
alpha-demo.agentsessionstatuses          (DLP bazasi — FAQAT O'QILADI)
        │
        ├── COLLECTOR ──► raw_data_for_train ──► TRAINER ──► baseline
        │   (90 kunlik tarix)                                (o'rganilgan norma)
        │
        └── TRIGGER ──► RabbitMQ ──► WORKER ──► PROCESSOR ──► results
            (har 5 soatda)             (×3)     (detectorlar)      │
                                                              DASHBOARD
```

### Ikkita baza, aniq ajratilgan

| Baza | Rejim | Nima bor |
|---|---|---|
| `alpha-demo` (DLP) | **faqat o'qish** | `agentsessionstatuses`, `clients` |
| `ueba_local` | o'qish/yozish | `raw_data_for_train`, `baseline`, `trigger_data`, `results`, `training_jobs` |

Ajratish kod darajasida: [services/mongo.py](services/mongo.py) da ikkita
alohida `MongoClient` bor, `main_db()` faqat `find()` uchun ishlatiladi.
DLP bazasiga yozish jismonan mumkin emas.

---

## Bosqichma-bosqich

### 1. Collector — tarixni yig'adi

**[services/collector.py](services/collector.py)** · faqat o'qitish paytida ishlaydi

Har bir active xodim uchun `agentsessionstatuses` dan **90 kunlik** hodisalarni
oladi. Har xodim uchun **bitta so'rov**.

Oyna ataylab **to'liq tugagan kunlardan** iborat:

```
window_end   = bugungi 00:00        ← ishga tushirilgan kun KIRMAYDI
window_start = window_end − 90 kun  ← eng eski kun ham 00:00 dan boshlanadi
```

Nima uchun: agar oyna `now − 90 kun` bo'lganda, soat 15:20 da ishga
tushirilsa eng eski kun 15:20 dan boshlanardi (ertalabki qismi yo'q), bugungi
kun esa chala bo'lardi — ikkalasi soxta kelish/ketish vaqti berib, normani
buzardi.

Har kun uchun uchta qiymat hisoblanadi ([services/workday.py](services/workday.py)):

```
start      = kunning birinchi hodisasi
finish     = kunning oxirgi hodisasi
activeMin  = LOGON/UNLOCK → LOCK/LOGOFF oraliqlari yig'indisi
```

Natija `raw_data_for_train` ga yoziladi. Arxiv oynaning **aynan nusxasi**
bo'lib qoladi: manbadan yo'qolgan kunlar va oynadan chiqib ketgan kunlar
o'chiriladi.

**Manba xatosida hech narsa yozilmaydi.** O'qish yozishdan oldin to'liq
bajariladi; xato bo'lsa o'sha xodim butunlay o'tkazib yuboriladi va uning
eski, to'g'ri ma'lumoti saqlanib qoladi. «O'qib bo'lmadi» ni «hech narsa
yo'q» deb qabul qilish mumkin emas.

### 2. Trainer — normani o'rganadi

**[services/trainer.py](services/trainer.py)**

Arxivdagi kunlarni **har hafta kuni alohida** guruhlaydi. Shanba faqat
shanbalar bilan solishtiriladi — odamlarning dam olish kunidagi rejimi
boshqacha bo'ladi.

Har guruh uchun o'rtacha va standart og'ish:

```json
"Tuesday": { "count": 5, "meanStart": 817.7, "stdStart": 297.87,
                         "meanFinish": 1012.15, "stdFinish": 276.69 }
```

Raqamlar — **kun boshidan daqiqa**. `817.7` = 13:37.

Namuna `MIN_DOW_SAMPLES` (3) dan kam bo'lsa statistika `null` bo'ladi va o'sha
hafta kuni baholanmaydi. Ikki kunlik ma'lumotdan norma chiqarish yolg'on
bo'lardi.

**Baseline versiyalanadi:** har o'qitish yangi `baselineId` oladi, eskilari
(oxirgi 5 tasi) saqlanadi. Yangi versiya tayyor bo'lgach `current: true`
qilinadi, keyin eskilari `false` ga o'tkaziladi — shu tartibda «joriy versiya
yo'q» oynasi umuman bo'lmaydi.

### 3. Trigger — yangi ma'lumotni navbatga tashlaydi

**[services/trigger.py](services/trigger.py)** · har 5 soatda, faqat avtomatik

Cursor bilan ishlaydi: `trigger_data` dagi oxirgi `finish` ning **kun
boshidan** o'qiydi. Kun boshiga tushirish ataylab — o'sha kun to'liq qayta
olinadi, shuning uchun chala kelgan ma'lumot keyingi o'tishda o'zini
to'g'rilaydi.

**Dedup:** `start`, `finish`, `eventCount` o'zgarmagan kun qayta yuborilmaydi.

**Tartib muhim:** avval RabbitMQ'ga publish qilinadi, **keyin** `trigger_data`
ga yoziladi. Teskari bo'lsa, navbat yiqilganda kun «yuborilgan» deb
belgilanib, hech qachon baholanmay qolardi.

### 4. Worker + Processor — baholaydi

**[mq/worker.py](mq/worker.py)** (3 ta thread) → **[services/processor.py](services/processor.py)**

Worker navbatdan job oladi, xodimning **joriy** baseline'ini topadi va
processor'ga uzatadi.

Processor o'zi hech narsa hisoblamaydi. U har kun uchun `DayContext` quradi va
uni **detectorlar ro'yxatidan** o'tkazadi
([services/detectors/registry.py](services/detectors/registry.py)). Shuning
uchun ikkinchi detector qo'shilganda processor o'zgarmaydi.

Baseline topilmasa ham kunlar yo'qolmaydi: natija baribir yoziladi, `status`
`insufficient` bo'ladi.

**Xato siyosati:** job xato bersa `MAX_RETRIES` (3) marta qayta urinib
ko'riladi, keyin tashlanadi. Har detector alohida `try/except` ichida
chaqiriladi — bitta detector yiqilsa ham kun yo'qolmaydi.

### 5. Dashboard — ko'rsatadi

Natijalar `results` ga yoziladi. Dashboard `/api/results` dan o'qiydi va
statistika tilida emas, **oddiy tilda** ko'rsatadi:

> «Ish oynasi boshlanishidan 1 soat 12 daqiqa oldin faollik ·
> Birinchi faollik 04:00 · Ish oynasi 05:12–22:41»

---

## Matematika: bitta kun qanday baholanadi

### 1-qadam — ish oynasi quriladi

```
lo = meanStart  − T·σ(start)          T = ANOMALY_Z_THRESHOLD (1.0)
hi = meanFinish + T·σ(finish)
```

Misol: o'rtacha kelish 13:37 (±4s58d), ketish 16:52 (±4s37d) → oyna
**08:39 – 21:28**.

### 2-qadam — chetlanishmi?

```
start < lo   yoki   finish > hi   →   CHETLANISH
```

Bir daqiqa ham chetlanish. Va bu **aniq** ishlaydi: kunning barcha hodisalari
`start` va `finish` orasida yotadi, demak ikkala chekka oyna ichida bo'lsa —
o'sha kunning hamma faolligi oyna ichida.

> **Kech kelish va erta ketish shubhali EMAS.** Odatda 09:00 da keladigan
> xodim 13:00 da kelsa — 13:00 oyna ichida, hech narsa chiqmaydi. Tizim
> intizomni emas, **ish vaqtidan tashqaridagi faollikni** kuzatadi.

### 3-qadam — darajasi qanday?

```
zOut = max(zStart, zFinish)                     faqat oynadan CHIQARUVCHI tomon
ball = 100 · (zOut − T) / (ZFULL − T)           ZFULL = ANOMALY_Z_FULL_SCALE (3.0)
```

| zOut | 1.0 | 1.5 | 2.0 | 2.5 | ≥ 3.0 | σ = 0 |
|---|---|---|---|---|---|---|
| **ball** | 1 | 25 | 50 | 75 | **100** | **100** |

Daraja **daqiqada emas, xodimning o'z σ birligida** o'lchanadi. Bir xil 30
daqiqalik chiqish har kuni aniq 09:00 da keladigan xodim uchun favqulodda
holat, jadvali beqaror xodim uchun esa oddiy tebranish.

Chetlanish bo'lgan kun hech qachon 0 ball olmaydi (minimal 1).

**Matematik ayniyat:** `lo = meanStart − T·σ` bo'lgani uchun «oynadan
tashqarida» aynan «`zOut > T`» degani. Qaror oyna bilan qilinadi, chunki u
`σ = 0` bo'lganda ham ishlaydi (z esa nolga bo'linardi).

E'tibor bering — **modul emas, ishorali**: `zStart > T` erta kelish
(tashqarida), `zStart < −T` esa kech kelish (oyna **ichida**).

### 4-qadam — umumiy risk

```
riskScore = 100 · (1 − ∏(1 − ball_i/100 · vazn_i))
```

Har detector «toza qolish» ehtimolini kamaytiradi. Bitta kuchli signal ham,
ko'p kichik signal ham riskni oshiradi, lekin 100 dan oshmaydi.

**Vazn** = shu detector yakka o'zi berishi mumkin bo'lgan eng yuqori risk.
Vazn 1.0 → bali to'liq o'tadi; 0.4 → yakka o'zi 40 dan yuqori risk bera
olmaydi; 0 → «soya rejim» (ishlaydi, natijaga yoziladi, riskka ta'sir
qilmaydi).

Hozir bitta detector va vazn 1.0 → `riskScore = anomalyScore`.

### Status

| Shart | `status` | Rang |
|---|---|---|
| oynadan tashqarida faollik bor | `anomaly` | qizil |
| hamma faollik oyna ichida | `normal` | yashil |
| baseline yo'q (namuna yetarli emas) | `insufficient` | kulrang |

---

## Sof ish vaqti — `activeMin`

Kun uzunligidan tashqari **sof ish vaqti** ham hisoblanadi: ochilish va
qulflanish oralig'idagi daqiqalar, tanaffuslar chiqarib tashlangan holda.

```
10:30–22:17    kun uzunligi 707 daqiqa,  sof ish 512 daqiqa,  tanaffus 195 daqiqa
```

Bu **quyi chegara** — juftini topmagan hodisalar sanalmaydi. Kun `LOCK` bilan
boshlansa (odam kechqurundan beri kirgan), o'sha ochiq oraliq hisobga
olinmaydi: sun'iy cho'zib yuborishdan ko'ra kam ko'rsatgan yaxshi.

Dashboard jadvalida «Sof ish» ustuni sifatida ko'rinadi (hover'da tanaffus).

Olti xil status uch juftlik hosil qiladi:

```
LOGON          <-> LOGOFF               tizimga kirish / chiqish
UNLOCK         <-> LOCK                 ekranni ochish / qulflash
REMOTE_CONNECT <-> REMOTE_DISCONNECT    masofadan ulanish / uzilish
```

---

## Qachon nima ishga tushadi

| Bosqich | Qachon | Kim ishga tushiradi |
|---|---|---|
| Collector + Trainer | talab bo'yicha | dashboard tugmasi yoki `POST /api/retrain` |
| Trigger | **har 5 soatda** | APScheduler, avtomatik |
| Worker | doim tinglaydi | 3 ta thread |

[main.py](main.py) hammasini **bitta protsessda** ko'taradi. `uvicorn --workers`
ishlatilmaydi — aks holda scheduler va workerlar N barobar ko'payardi.

---

## Ishga tushirish

`.env` da `MONGO_URI` va `DB_NAME` DLP bazasiga ko'rsatib turgan bo'lsin.

```bash
docker compose up -d --build                    # mongo + rabbitmq + app
docker compose exec app python collector.py     # 90 kunlik tarixni yig'ish
docker compose exec app python trainer.py       # baseline qurish
```

Dashboard: **http://localhost:8000**

| Buyruq | Vazifasi |
|---|---|
| `docker compose ps` | servislar holati |
| `docker compose logs -f app` | jonli loglar |
| `docker compose up -d` | **`.env` o'zgarishini qo'llash** (konteyner qayta yaratiladi) |
| `docker compose restart app` | qayta ishga tushirish (`.env` o'zgarishi **o'qilmaydi**) |
| `docker compose down` | to'xtatish (ma'lumot volume'da qoladi) |

Compose timezone'ni (`TZ=Asia/Tashkent`) va servis manzillarini o'zi
to'g'rilaydi, Mongo/RabbitMQ tayyor bo'lgunicha kutadi, reboot'dan keyin o'zi
ko'tariladi.

### Docker'siz

```bash
docker run -d --name ueba-mongo -p 27017:27017 -v ueba_mongo_data:/data/db mongo:8.0.4
docker run -d --name ueba-rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3.13-management

python -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python collector.py
venv/bin/python trainer.py
venv/bin/python main.py
```

> ⚠️ Ikkita narsa (Compose'da avtomatik hal qilingan):
> **1)** `main.py` faqat bitta protsess sifatida ishlaydi.
> **2)** Server timezone'i xodimlar timezone'i bilan bir xil bo'lishi kerak
> (`Asia/Tashkent`) va keyin o'zgartirilmasligi lozim — aks holda barcha
> vaqtlar suriladi va baseline buziladi.

---

## Sozlamalar

**Kodda qattiq yozilgan qiymat yo'q — 42 tasi ham `.env` da.** Buni
[tests/test_config.py](tests/test_config.py) qo'riqlaydi: u `config.py` ni AST
bilan tekshiradi va har bir sozlamani haqiqatan almashtirib ko'radi. Kimdir
kodga qattiq qiymat yozib qo'ysa test yiqiladi.

| Guruh | Sozlamalar |
|---|---|
| **Manba baza** | `MONGO_URI`, `DB_NAME`, `SESSION_COLLECTION`, `SESSION_START_STATUSES`, `SESSION_END_STATUSES` |
| **Mahalliy baza** | `LOCAL_MONGO_URI`, `LOCAL_DB_NAME`, `COL_*` (6 ta) |
| **RabbitMQ** | `RABBITMQ_*`, `QUEUE_NAME`, `WORKER_COUNT`, `MAX_RETRIES` |
| **API** | `API_HOST`, `API_PORT`, `API_PAGE_SIZE`, `API_PAGE_MAX` |
| **Pipeline** | `DAYS_WINDOW`, `TRIGGER_INTERVAL_HOURS`, `LOOKBACK_HOURS`, `BATCH_SIZE`, `SOURCE_READ_RETRIES`, `SOURCE_READ_RETRY_DELAY`, `SINGLE_EVENT_STAY_HOURS`, `RESULTS_RETENTION_DAYS`, `BASELINE_KEEP_VERSIONS`, `BULK_BATCH_SIZE` |
| **Anomaliya** | `MIN_DOW_SAMPLES`, `ANOMALY_Z_THRESHOLD`, `ANOMALY_Z_FULL_SCALE` |
| **Detectorlar** | `DETECTOR_WEIGHT_<NOM>` |
| **Dashboard** | `DASHBOARD_RANGE_DAYS`, `DASHBOARD_MAX_ISSUES`, `SEVERITY_HIGH`, `SEVERITY_MEDIUM`, `SEVERITY_LOW` |

Dashboard hech narsani o'zida saqlamaydi — chegaralarni, daraja yorliqlarini
va sana oralig'ini `/api/health` dan oladi.

```bash
# .env ni tahrirlash, keyin:
docker compose up -d          # `restart` EMAS
```

Chegaralarni (`MIN_DOW_SAMPLES`, `DAYS_WINDOW`, `ANOMALY_Z_*`) o'zgartirsangiz
**baseline qayta o'qitilishi** kerak — aks holda yangi kunlar eski normaga
solishtiriladi.

---

## Yangi detector qo'shish

Karkas aynan shuning uchun qurilgan. Ikki qadam:

1. `services/detectors/` ga bitta fayl — `base.Detector` dan meros olib,
   `evaluate(ctx)` ni yozasiz. `ctx` da kunning barcha ma'lumoti bor:
   `start`, `finish`, `active_min`, `event_count`, `baseline`, `week`.
2. `registry.py` oxiridagi ro'yxatga bitta qator qo'shasiz.

`processor.py` ga tegilmaydi. Detector `evaluated=False` qaytarsa (ma'lumot
yetarli emas), u umumiy natijaga xalaqit bermaydi.

Detectorlar **holatsiz** bo'lishi shart — 3 ta worker thread bir vaqtda
chaqiradi.

---

## API

| Endpoint | Method | Vazifasi |
|---|---|---|
| `/api/health` | GET | Mongo, RabbitMQ, navbat, oxirgi trigger/retrain + dashboard sozlamalari |
| `/api/train` | POST | Birinchi o'qitish (baseline mavjud bo'lsa 409) |
| `/api/retrain` | POST | Baseline yangilash: collector → trainer |
| `/api/jobs` | GET | O'qitish joblari ro'yxati |
| `/api/clients` | GET | Xodimlar ro'yxati |
| `/api/baseline` | GET | Joriy baseline |
| `/api/baseline/versions` | GET | Baseline versiyalari |
| `/api/results` | GET | Natijalar: `from`, `to`, `client_id`, `status`, `is_anomaly`, `min_risk`, `trigger`, `limit`, `offset` |
| `/api/results/{client_id}` | GET | Bitta xodim natijalari |

---

## Ma'lumot tuzilmalari

Mahalliy bazadagi (`ueba_local`) to'rtta collection.

### `raw_data_for_train` — o'qitish arxivi

Har xodim × har kun = 1 hujjat. `trigger_data` ham **aynan shu shaklda**.

```json
{
  "clientId": "6a68d16e4abd38577c6314fb",
  "hostname": "azam@azam-upc",
  "fullName": null,
  "date": "2026-08-25",
  "dayOfWeek": "Tuesday",
  "start": "2026-08-25T22:17:05",
  "finish": "2026-08-25T23:17:05",
  "durationMin": 60.0,
  "activeMin": 0.0,
  "eventCount": 1,
  "updatedAt": "2026-09-09T14:10:43"
}
```

- `date` — **string**, `"YYYY-MM-DD"`. Ataylab: ISO string'lar alifbo
  tartibida solishtirilganda xronologik tartib bilan mos tushadi, shuning
  uchun `$lt` / `$gte` filtrlar string ustida ham to'g'ri ishlaydi.
- **Indeks:** UNIQUE `{clientId, date}`. Yozish — replacement upsert, ya'ni
  qayta yozish har doim xavfsiz.

`trigger_data` ning farqi vazifasida — u uchta savolga javob beradi:
**nima yuborilgan**, **qayerdan davom etish kerak** (cursor), **takror
yuborilmayaptimi** (dedup).

### `baseline` — o'rganilgan norma

```json
{
  "baselineId": "6aa12294c00c35a67bdbd5c8",
  "clientId": "6a68d16e4abd38577c6314fb",
  "hostname": "azam@azam-upc",
  "windowDays": 90,
  "minDowSamples": 3,
  "totalDays": 13,
  "keptDays": 9,
  "trainedAt": "2026-09-09T14:10:44",
  "weeks": {
    "Tuesday": { "count": 3, "meanStart": 899.8, "stdStart": 760.26,
                 "meanFinish": 1337.19, "stdFinish": 89.97, "meanDuration": 437.4 }
  }
}
```

Vaqtlar — **kun boshidan daqiqa** (`899.8` = 14:59). Namuna
`minDowSamples` dan kam bo'lsa faqat `count` yoziladi, qolgan statlar `null`.

`baseline_runs` — versiyalar reyestri, joriysi `current: true` bilan.

### `results` — har (xodim × kun) uchun baholash

```json
{
  "clientId": "...", "hostname": "azam@azam-upc", "fullName": null,
  "date": "2026-08-25", "dayOfWeek": "Tuesday",
  "start": "22:17:05", "finish": "23:17:05",
  "durationMin": 60.0, "activeMin": 0.0, "eventCount": 1,

  "usualStart": 899.8,   "usualFinish": 1337.19,
  "stdStart": 760.26,    "stdFinish": 89.97,
  "windowStart": 139.5,  "windowFinish": 1427.2,
  "zStart": -0.575,      "zFinish": 0.666,

  "isAnomaly": false, "anomalyScore": 0, "riskScore": 0,
  "status": "normal", "statusColor": "green",

  "triggers": { "workingHours": false },
  "triggeredDetectors": [],
  "detectors": {
    "workingHours": {
      "triggered": false, "score": 0, "weight": 1.0, "evaluated": true,
      "reason": "faollik ish oynasi ichida (02:20–23:47)",
      "details": { "zOut": 0.666, "outsideMin": 0.0, "beforeMin": 0.0,
                   "afterMin": 0.0, "windowStart": 139.5, "windowFinish": 1427.2 }
    }
  },

  "baselineId": "6aa12294c00c35a67bdbd5c8",
  "evaluatedAt": "2026-09-09T14:11:23"
}
```

- `start` / `finish` bu yerda **faqat vaqt** (`"HH:MM:SS"`), arxivda esa to'liq ISO.
- **Natija o'zi-o'ziga yetarli:** `usualStart`, `windowStart` kabi taqqoslash
  qiymatlari ichida saqlanadi. Dashboard «odatda qachon kelardi» ni joriy
  baseline'dan izlamaydi — shuning uchun versiya nomuvofiqligi bo'lmaydi.
- `triggeredDetectors` massiv: bitta multikey indeks barcha detectorlar
  bo'yicha filtrni qoplaydi.
- **Indeks:** UNIQUE `{clientId, date}`, plus `{isAnomaly, date}` va
  `{triggeredDetectors}`.

---

## Manba bazadagi indeks

`agentsessionstatuses` da hozir faqat `{clientId: 1, computerId: 1}` indeksi
bor — `dateTime` indekslanmagan. Bizning so'rov `clientId` + vaqt oralig'i
bo'yicha ketadi.

Hozirgi hajmda (2400 hujjat) muammo yo'q. Ma'lumot o'sganda DLP jamoasidan
so'rash kerak:

```js
db.agentsessionstatuses.createIndex({ clientId: 1, dateTime: -1 })
```

Bizning kod DLP bazasiga yoza olmaydi, shuning uchun buni faqat ular qo'sha
oladi.

---

## Loyiha tuzilishi

```
main.py                    FastAPI + scheduler + workerlar (bitta protsess)
config.py                  42 ta sozlama, hammasi .env dan
collector.py / trainer.py  CLI qobiqlari

services/
  workday.py               kun boshi/oxiri + sof ish vaqti
  collector.py             90 kunlik tarix -> raw_data_for_train
  trainer.py               norma quradi -> baseline (versiyalangan)
  trigger.py               cursor + dedup -> RabbitMQ
  processor.py             kontekst quradi, detectorlarga uzatadi
  mongo.py                 2 ta MongoClient (DLP read-only + mahalliy)
  jobs.py                  o'qitish joblari holati
  detectors/
    scoring.py             ball, riskScore, status — chegaralar FAQAT shu yerda
    working_hours.py       ish oynasi qoidasi
    registry.py            ro'yxat + natijalarni birlashtirish
    base.py                DayContext, DetectorResult, Detector bazasi

mq/                        RabbitMQ ulanishi va worker thread'lar
api/                       FastAPI endpointlari
dashboard/                 vanilla JS + inline SVG (tashqi kutubxonasiz)
scripts/                   bir martalik ta'mirlash skriptlari
tests/                     41 ta tekshiruv
```

---

## Testlar

```bash
for t in tests/*.py; do venv/bin/python $t; done
```

| Fayl | Nimani qo'riqlaydi |
|---|---|
| `test_config.py` | Har bir sozlama `.env` dan o'qiladimi (qattiq qiymat yo'qmi) |
| `test_workday.py` | Sof ish vaqti, kunlarga ajratish, chala ma'lumot |
| `test_collector.py` | Oyna chegaralari, manba xatosi, arxiv tozalash |
| `test_detectors.py` | Ball jadvali, oyna qoidasi, riskScore, xato izolyatsiyasi |
| `test_baseline_versions.py` | Baseline versiyalash, natijaning o'zi-o'ziga yetarliligi |
| `test_jobs.py` | Bir vaqtda faqat bitta o'qitish |

`pytest` ishlatilmaydi — har test `bool` qaytaradi, `python tests/xxx.py`
bilan yurgiziladi.

---

## Edge caselar

Kodda ataylab hisobga olingan holatlar.

| Holat | Xatti-harakat |
|---|---|
| `clients` da `disabled` maydoni yo'q | `$or` so'rovi — xodim **active** hisoblanadi |
| `hostname` bo'sh yoki yo'q | o'rniga `str(_id)` ishlatiladi |
| Vaqt maydoni parse bo'lmadi | o'sha hodisa skip, xato tashlanmaydi (bu «ma'lumot yaroqsiz», «o'qib bo'lmadi» emas) |
| **Manbani o'qib bo'lmadi** (tarmoq uzildi) | 2 marta qayta urinish → baribir bo'lmasa `SourceReadError`; **shu xodim umuman yozilmaydi**, eski ma'lumoti saqlanadi |
| Xodim ishdan bo'shadi | active ro'yxatga tushmaydi → arxiv yozuvlari o'chiriladi → keyingi baseline'ga kirmaydi. `results` dagi tarixi qoladi |
| Kun to'liq tugamagan (bugungi) | o'qitish oynasiga **kirmaydi**, baholanishda esa qatnashadi |
| Shu hafta kuni uchun baseline yo'q | `status: insufficient` — kun dashboardda ko'rinadi, ma'lumot yo'qolmaydi |
| Yangi xodim, baseline umuman yo'q | natija **baribir yoziladi**, `insufficient` bo'ladi |
| σ = 0 (xodim har kuni aynan bir xil vaqtda) | z hisoblanmaydi; oyna `[mean, mean]` bo'ladi va har qanday chiqish 100 ball oladi |
| Kunda faqat 1 ta hodisa | `finish = start + SINGLE_EVENT_STAY_HOURS`; keyin hodisa qo'shilsa o'zi to'g'rilanadi |
| Yagona hodisa 23:00 dan keyin | `finish` 23:59:59 bilan cheklanadi — soxta «erta ketish» bo'lmaydi |
| Sessiya yarim tunni kesib o'tdi | har hodisa o'z sanasi bilan guruhlanadi — kun 2 ga bo'linadi |
| Kun 12 soatdan uzun | filtrlanmaydi, normal saqlanadi — chetlanish bo'lishi mumkin |
| Dastur 2 kun o'chiq turdi | keyingi trigger cursor'dan hozirgacha hammasini oladi |
| Publish paytida RabbitMQ yotdi | `trigger_data` yozilmaydi → cursor orqada → keyingi o'tishda qayta yuboriladi |
| Worker 3 marta urinib tashladi | kunlar `trigger_data` da «yuborilgan» → avtomatik qaytmaydi. Kerak bo'lsa: `db.trigger_data.deleteOne({clientId, date})` |
| Bitta detector xato tashladi | `registry.run` uni ushlaydi, `evaluated: false` yoziladi — kun yo'qolmaydi |
| Retrain davomida job keldi | eski baseline swap'gacha joyida — worker bo'sh baseline ko'rmaydi |
| Bir (clientId, date) qayta yozildi | replacement upsert → idempotent, dublikat yo'q |

---

## Muhim qoidalar

1. **DLP bazasi 100% read-only** — ikkita alohida MongoClient, asosiysiga
   faqat `find()`.
2. **Baseline bir marta o'qitiladi** — har 5 soatlik tsiklda qayta
   qurilmaydi. Yangilash faqat tugma orqali.
3. **Baseline versiyalanadi** — retrain davomida eski versiya ishlayveradi.
   Har natijada `baselineId` yoziladi.
4. **Natija o'zi-o'ziga yetarli** — `usualStart`, `stdStart`, `windowStart`
   kabi taqqoslash qiymatlari natijaning ichida saqlanadi. Dashboard «odatda
   qachon kelardi» ni joriy baseline'dan izlamaydi.
5. **Hech narsa yo'qolmaydi va takrorlanmaydi** — trigger cursor bilan
   ishlaydi, yuborilganini `trigger_data` ga yozib boradi.
6. **Kunlik agregat qoidasi:** 0 hodisa → kun yo'q; 1 hodisa →
   `finish = start + SINGLE_EVENT_STAY_HOURS` (23:59:59 bilan cheklangan);
   2+ hodisa → `min/max`.
7. **Xodim nomi:** asosiy identifikator `clientId`, ko'rsatish uchun
   `hostname`. DLP bazasidagi ism maydonlari to'liq emas, shuning uchun ism
   faqat haqiqiy bo'lganda ishlatiladi.
8. **Kech kelish va erta ketish chetlanish emas** — ular oyna ichida qoladi.
   Bu ongli qaror: tizim intizomni emas, ish vaqtidan tashqaridagi faollikni
   kuzatadi.
