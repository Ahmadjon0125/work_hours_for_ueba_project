# UEBA — Ish vaqti tahlili

Har bir xodim uchun **o'zining odatiy ish oynasini** o'rganadi, so'ng har kuni
shu oynadan **tashqarida** faollik bo'lganini tekshiradi. Ish vaqtidan
tashqaridagi faollik — DLP nuqtai nazaridan e'tibor talab qiladigan holat.

Ma'lumot manbai — DataGaze DLP tizimining MongoDB'sidagi
**`agentsessionstatuses`** collection'i: agent yuboradigan hozirlik qaydlari
(tizimga kirish/chiqish, ekranni ochish/qulflash, masofadan ulanish).

---

## Mundarija

- [Dashboard](#dashboard)
- [Umumiy manzara](#umumiy-manzara)
- [Bosqichma-bosqich](#bosqichma-bosqich) — collector, trainer, trigger, worker, dashboard
- [Matematika](#matematika-bitta-kun-qanday-baholanadi) — oyna, chetlanish, ball, risk
- [To'liq misol](#toliq-misol-bitta-kun-boshidan-oxirigacha)
- [Sof ish vaqti](#sof-ish-vaqti--activemin)
- [O'qitish jarayoni](#oqitish-jarayoni-train--retrain)
- [Ishga tushganda nima bo'ladi](#ishga-tushganda-nima-boladi)
- [Dashboard qanday ishlaydi](#dashboard-qanday-ishlaydi)
- [Yangi detector qo'shish](#yangi-detector-qoshish)
- [API](#api)
- [Ma'lumot tuzilmalari](#malumot-tuzilmalari)
- [Ishga tushirish](#ishga-tushirish)
- [Sozlamalar](#sozlamalar)
- [Loglar va kuzatuv](#loglar-va-kuzatuv)
- [Muammolarni bartaraf etish](#muammolarni-bartaraf-etish)
- [Testlar](#testlar)
- [Edge caselar](#edge-caselar)
- [Muhim qoidalar](#muhim-qoidalar)

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

Yuqoridagi tarmoq — **o'qitish**, faqat talab bo'yicha ishlaydi.
Pastdagisi — **baholash**, har 5 soatda avtomatik.

### Ikkita baza, aniq ajratilgan

| Baza | Rejim | Nima bor |
|---|---|---|
| `alpha-demo` (DLP) | **faqat o'qish** | `agentsessionstatuses`, `clients` |
| `ueba_local` | o'qish/yozish | `raw_data_for_train`, `baseline`, `baseline_runs`, `trigger_data`, `results`, `training_jobs` |

Ajratish kod darajasida: [services/mongo.py](services/mongo.py) da ikkita
alohida `MongoClient` bor. `main_db()` faqat `find()` uchun ishlatiladi,
`local_db()` esa barcha yozuvlar uchun. DLP bazasiga yozish jismonan
mumkin emas — bu tasodifiy emas, ataylab qo'yilgan to'siq.

### Manba collection

```json
{
  "clientId":   ObjectId("684d6e4c0614f7499b947d48"),   // clients._id ga bog'lanadi
  "computerId": ObjectId("684d6e4c0614f7499b947d41"),
  "status":     "UNLOCK",
  "dateTime":   ISODate("2026-08-25T17:40:53"),
  "info":       ""                                       // ba'zan RDP tafsilotlari
}
```

Olti xil status uch juftlik hosil qiladi:

```
LOGON          <-> LOGOFF               tizimga kirish / chiqish
UNLOCK         <-> LOCK                 ekranni ochish / qulflash
REMOTE_CONNECT <-> REMOTE_DISCONNECT    masofadan ulanish / uzilish
```

Status nomlari `.env` da (`SESSION_START_STATUSES`, `SESSION_END_STATUSES`) —
agent yangisini qo'shsa kodga tegilmaydi.

---

## Bosqichma-bosqich

### 1. Collector — tarixni yig'adi

**[services/collector.py](services/collector.py)** · faqat o'qitish paytida

Har bir active xodim uchun `agentsessionstatuses` dan **90 kunlik**
hodisalarni oladi. Har xodim uchun **bitta so'rov**.

**Active xodim kim:** `clients` da `disabled: false` yoki maydon umuman
yo'q. Ya'ni `disabled` qo'yilmagan xodim ham active hisoblanadi.

**Oyna ataylab to'liq tugagan kunlardan iborat:**

```
window_end   = bugungi 00:00        ← ishga tushirilgan kun KIRMAYDI
window_start = window_end − 90 kun  ← eng eski kun ham 00:00 dan boshlanadi
```

Nima uchun: agar oyna `now − 90 kun` bo'lganda, soat 15:20 da ishga
tushirilsa eng eski kun 15:20 dan boshlanardi (ertalabki qismi yo'q),
bugungi kun esa chala bo'lardi. Ikkalasi soxta kelish/ketish vaqti berib
normani buzardi. Endi oyna **soat nechada ishga tushirilganidan qat'i
nazar bir xil**.

**Har kun uchun uchta qiymat** ([services/workday.py](services/workday.py)):

```
start      = kunning birinchi hodisasi
finish     = kunning oxirgi hodisasi
activeMin  = LOGON/UNLOCK → LOCK/LOGOFF oraliqlari yig'indisi
```

**Arxiv oynaning aynan nusxasi bo'lib qoladi.** Collector uchta tozalash
qiladi:

1. Manbadan yo'qolgan kunlar o'chiriladi (DLP tomonda ma'lumot o'chirilgan
   bo'lsa, bizda ham qolmasin).
2. Oynadan chiqib ketgan kunlar o'chiriladi — **barcha xodimlar uchun**,
   sikldan tashqarida. Sikl ichida bo'lganda collector bormaydigan xodimning
   yozuvlari abadiy qolib ketardi.
3. Active ro'yxatda yo'q xodimlarning yozuvlari o'chiriladi — **faqat run
   to'liq muvaffaqiyatli bo'lsa**. Manba buzilib qisqa ro'yxat qaytarsa,
   butun arxiv qirilib ketmasin.

**Manba xatosida hech narsa yozilmaydi.** O'qish yozishdan oldin to'liq
bajariladi; xato bo'lsa o'sha xodim butunlay o'tkazib yuboriladi va uning
eski, to'g'ri ma'lumoti saqlanib qoladi. «O'qib bo'lmadi» ni «hech narsa
yo'q» deb qabul qilish mumkin emas — bu ikki xil holat.

Tarmoq uzilishlari ko'pincha o'tkinchi bo'lgani uchun
`SOURCE_READ_RETRIES` (2) marta qayta uriniladi.

### 2. Trainer — normani o'rganadi

**[services/trainer.py](services/trainer.py)**

Arxivdagi kunlarni **har hafta kuni alohida** guruhlaydi. Shanba faqat
shanbalar bilan solishtiriladi — odamlarning dam olish kunidagi rejimi
boshqacha bo'ladi va aralashtirilsa norma ma'nosini yo'qotadi.

Har guruh uchun o'rtacha va **sample** standart og'ish (`n−1` bo'luvchi):

```json
"Tuesday": { "count": 5, "meanStart": 817.7, "stdStart": 297.87,
                         "meanFinish": 1012.15, "stdFinish": 276.69,
                         "meanDuration": 194.44 }
```

Raqamlar — **kun boshidan daqiqa**. `817.7` = 13:37.

Namuna `MIN_DOW_SAMPLES` (3) dan kam bo'lsa statistika `null` bo'ladi va
o'sha hafta kuni baholanmaydi — faqat `count` yoziladi. Ikki kunlik
ma'lumotdan norma chiqarish yolg'on bo'lardi.

**Baseline versiyalanadi.** Har o'qitish yangi `baselineId` oladi, eskilari
(`BASELINE_KEEP_VERSIONS` = 5 tasi) saqlanadi. Almashtirish tartibi qat'iy:

```
1. yangi versiya yoziladi va DARROV current: true qilinadi
2. KEYIN eski versiyalar current: false ga o'tkaziladi
```

Shu tartibda «joriy versiya yo'q» oynasi umuman bo'lmaydi. Bir lahza
ikkitasi bo'lib qolsa, o'quvchi eng yangisini oladi.

### 3. Trigger — yangi ma'lumotni navbatga tashlaydi

**[services/trigger.py](services/trigger.py)** · har 5 soatda, **faqat
avtomatik** — API orqali ishga tushirish yo'li yo'q

`trigger_data` collection'i uchta savolga javob beradi va uning yagona
egasi trigger'dir:

| Savol | Qanday javob beradi |
|---|---|
| Qayerdan davom etish kerak? | xodimning eng oxirgi `finish` i = cursor |
| Nima yuborilgan? | ichida faqat MQ'ga **muvaffaqiyatli yetib borgan** kunlar |
| Takror yuborilmayaptimi? | `start`, `finish`, `eventCount` solishtiriladi |

**Cursor kun boshiga tushiriladi.** Oxirgi `finish` 2026-09-08T18:48 bo'lsa,
keyingi o'tish 2026-09-08T00:00 dan o'qiydi. Nima uchun: o'sha kun to'liq
qayta olinadi, shuning uchun chala kelgan ma'lumot keyingi o'tishda
**o'zini to'g'rilaydi**. Cursor umuman bo'lmasa (birinchi o'tish) —
`now − LOOKBACK_HOURS` (5 soat).

**Dedup:** kun `trigger_data` dagi yozuv bilan uchala maydon bo'yicha bir
xil bo'lsa, qayta yuborilmaydi. Ma'lumot o'zgargan bo'lsa — yuboriladi va
`results` yangilanadi.

**Tartib qat'iy: avval publish, keyin yozish.**

```python
publish(channel, job)                      # 1. RabbitMQ'ga
for doc in day_docs:
    trigger_col.update_one(..., upsert=True)   # 2. keyin trigger_data ga
```

Teskari bo'lsa, navbat yiqilganda kun «yuborilgan» deb belgilanib, hech
qachon baholanmay qolardi. Hozirgi tartibda esa eng yomon holat — cursor
orqada qoladi va keyingi o'tishda qayta yuboriladi. Hech narsa yo'qolmaydi.

**Tozalash:** har o'tishda `trigger_data` dan `DAYS_WINDOW` kundan eski
yozuvlar, `results` dan `RESULTS_RETENTION_DAYS` (365) kundan eskilari
o'chiriladi.

Bitta xodimda xato bo'lsa qolganlari davom etadi — xato o'sha xodim
doirasida ushlanadi.

### 4. Worker + Processor — baholaydi

**[mq/worker.py](mq/worker.py)** (`WORKER_COUNT` = 3 ta thread) →
**[services/processor.py](services/processor.py)**

**Navbat sozlamalari:**

| Parametr | Qiymat | Nima uchun |
|---|---|---|
| Queue | `ueba_jobs`, **durable** | RabbitMQ qayta ishga tushsa navbat yo'qolmaydi |
| Message | `delivery_mode=2` | xabar diskda saqlanadi |
| `prefetch_count` | **1** | bitta worker bir vaqtda bitta job — yuk teng taqsimlanadi |
| Auto-ack | **yo'q** | ack faqat ish tugagach, aks holda xato bo'lsa job yo'qolardi |

Har thread **o'z ulanishiga** ega — `pika` talabi: bir connection, bir thread.

**Job payload'i:**

```json
{
  "jobId": "8f3c...uuid4",
  "clientId": "6a68d16e4abd38577c6314fb",
  "hostname": "azam@azam-upc",
  "windowStart": "2026-09-08T00:00:00",
  "windowEnd": "2026-09-09T12:00:00",
  "days": {
    "2026-09-08": { "start": "2026-09-08T09:49:00", "finish": "2026-09-08T18:48:16",
                    "eventCount": 12, "dayOfWeek": "Tuesday",
                    "durationMin": 539.27, "activeMin": 384.6 }
  },
  "sentAt": "2026-09-09T12:00:00"
}
```

**Worker nima qiladi:**

1. JSON parse. Buzuq bo'lsa → darrov tashlanadi, qayta urinilmaydi
   (buzuq JSON qayta urinishdan tuzalmaydi).
2. `current_baseline_id()` → xodimning **joriy** baseline'ini topadi.
   Topilmasa ham kunlar yo'qolmaydi: natija baribir yoziladi,
   `status: insufficient` bo'ladi.
3. `evaluate_job(job, baseline)` → natija hujjatlari.
4. `results` ga upsert (`{clientId, date}` kaliti) → **idempotent**,
   takroriy job zarar qilmaydi.
5. `basic_ack`.

**Xato siyosati.** Message header'ida `x-retries` hisoblagichi bor:

```
xato + x-retries < MAX_RETRIES(3)  →  x-retries+1 bilan QAYTA PUBLISH
xato + x-retries >= 3              →  tashlanadi + ERROR log
```

Tashlangan job avtomatik qaytmaydi, chunki kunlar `trigger_data` da
«yuborilgan» deb turadi. Qo'lda qaytarish yo'li
[Muammolarni bartaraf etish](#muammolarni-bartaraf-etish) da.

**Processor o'zi hech narsa hisoblamaydi.** U har kun uchun `DayContext`
quradi va uni **detectorlar ro'yxatidan** o'tkazadi
([registry.py](services/detectors/registry.py)). Shuning uchun ikkinchi
detector qo'shilganda processor o'zgarmaydi.

Har detector alohida `try/except` ichida chaqiriladi. Bitta detector
yiqilsa `evaluated: false` yoziladi va kun yo'qolmaydi — aks holda job
3 marta qayta urinilib, keyin butunlay tashlanardi.

### 5. Dashboard — ko'rsatadi

Natijalar `results` ga yoziladi. Dashboard `/api/results` dan o'qiydi va
statistika tilida emas, **oddiy tilda** ko'rsatadi:

> «Ish oynasi boshlanishidan 1 soat 12 daqiqa oldin faollik ·
> Birinchi faollik 04:00 · Ish oynasi 05:12–22:41»

Tafsilotlar: [Dashboard qanday ishlaydi](#dashboard-qanday-ishlaydi).

---

## Matematika: bitta kun qanday baholanadi

### 1-qadam — ish oynasi quriladi

```
lo = meanStart  − T·σ(start)          T = ANOMALY_Z_THRESHOLD (1.0)
hi = meanFinish + T·σ(finish)
```

Misol: o'rtacha kelish 13:37 (±4s58d), ketish 16:52 (±4s37d) → oyna
**08:39 – 21:28**.

Oyna har hafta kuni uchun alohida — dushanbaniki dushanbanikidan,
jumaniki jumanikidan.

### 2-qadam — chetlanishmi?

```
start < lo   yoki   finish > hi   →   CHETLANISH
```

Bir daqiqa ham chetlanish. Va bu **aniq** ishlaydi: kunning barcha
hodisalari `start` va `finish` orasida yotadi, demak ikkala chekka oyna
ichida bo'lsa — o'sha kunning **hamma** faolligi oyna ichida. Alohida
hodisalarni tekshirish shart emas.

> **Kech kelish va erta ketish shubhali EMAS.** Odatda 09:00 da keladigan
> xodim 13:00 da kelsa — 13:00 oyna ichida, hech narsa chiqmaydi. Tizim
> intizomni emas, **ish vaqtidan tashqaridagi faollikni** kuzatadi. Bu
> ongli tanlov: kech kelish kadrlar masalasi, tunda ishlash esa DLP
> masalasi.

### 3-qadam — darajasi qanday?

```
zOut = max(zStart, zFinish)                     faqat oynadan CHIQARUVCHI tomon
ball = 100 · (zOut − T) / (ZFULL − T)           ZFULL = ANOMALY_Z_FULL_SCALE (3.0)
```

| zOut | 1.0 | 1.5 | 2.0 | 2.5 | ≥ 3.0 | σ = 0 |
|---|---|---|---|---|---|---|
| **ball** | 1 | 25 | 50 | 75 | **100** | **100** |

Daraja **daqiqada emas, xodimning o'z σ birligida** o'lchanadi. Bir xil
30 daqiqalik chiqish har kuni aniq 09:00 da keladigan xodim uchun
favqulodda holat, jadvali beqaror xodim uchun esa oddiy tebranish.
Daqiqa bu farqni ko'rmaydi, z ko'radi.

Chetlanish bo'lgan kun hech qachon 0 ball olmaydi (minimal 1) — aks holda
«chetlanish, lekin ball 0» degan ziddiyat chiqardi.

**Matematik ayniyat:** `lo = meanStart − T·σ` bo'lgani uchun «oynadan
tashqarida» aynan «`zOut > T`» degani. Bu 85 ta natijada tekshirilgan —
birorta istisno yo'q. Qaror **oyna bilan** qilinadi, chunki u `σ = 0`
bo'lganda ham ishlaydi (z esa nolga bo'linardi).

E'tibor bering — **modul emas, ishorali**:

| | z ishorasi | Oynaga nisbatan |
|---|---|---|
| `zStart > T` | erta kelish | tashqarida |
| `zStart < −T` | kech kelish | **ichida** |
| `zFinish > T` | kech ketish | tashqarida |
| `zFinish < −T` | erta ketish | **ichida** |

`abs()` ishlatilganda kech kelish va erta ketish ham chetlanish bo'lib
qolardi.

### 4-qadam — umumiy risk

```
riskScore = 100 · (1 − ∏(1 − ball_i/100 · vazn_i))
```

Har detector «toza qolish» ehtimolini kamaytiradi. Uchta qorovul deb
tasavvur qiling: birinchisi 50% shubhali desa o'tkazish ehtimoli 50%,
ikkinchisi 40% desa 60%, uchinchisi 30% desa 70%. Uchalasidan toza o'tib
ketish ehtimoli `0.5 × 0.6 × 0.7 = 21%`, demak xavf **79**.

Xossalari: bitta kuchli signal ham, ko'p kichik signal ham riskni
oshiradi; hech qachon 100 dan oshmaydi; yangi detector qo'shilsa formula
o'zgarmaydi.

**Vazn** = shu detector yakka o'zi berishi mumkin bo'lgan eng yuqori risk.

| Vazn | Ball 100 bo'lganda yakka o'zi beradigan risk |
|---|---|
| 1.0 | 100 — «bu yagona signalning o'zi yetarli» |
| 0.6 | 60 — «jiddiy, lekin yolg'iz o'zi hukm emas» |
| 0.3 | 30 — «shunchaki qo'shimcha dalil» |
| 0 | 0 — «soya rejim»: ishlaydi, yoziladi, riskka ta'sir qilmaydi |

Vaznni belgilash uchun o'zingizga savol bering: *«agar faqat shu detector
ishga tushsa va eng yuqori ball bersa, bu xodimni 100 ballik shkalada
necha ball xavfli deb bilaman?»* Javobni 100 ga bo'ling.

Hozir bitta detector va vazn 1.0 → `riskScore = anomalyScore`.

### Status

| Shart | `status` | Rang |
|---|---|---|
| oynadan tashqarida faollik bor | `anomaly` | qizil |
| hamma faollik oyna ichida | `normal` | yashil |
| baseline yo'q (namuna yetarli emas) | `insufficient` | kulrang |

`insufficient` ni yo'qotib bo'lmaydi: baseline yo'q kunni «normal» deyish
yolg'on bo'lardi. Bunday kunda `anomalyScore` va `riskScore` — `null`,
0 emas, aks holda u dashboardda «ideal kun» bo'lib ko'rinardi.

---

## To'liq misol: bitta kun boshidan oxirigacha

Real ma'lumot, `azam@azam-upc`, 2026-08-25 (seshanba).

**1. Manbada nima bor**

```
22:17:05   LOCK
```

Butun kunga bitta hodisa.

**2. Collector nima qiladi**

Bitta hodisa bo'lgani uchun `SINGLE_EVENT_STAY_HOURS` (1 soat) qoidasi
ishlaydi:

```
start     = 22:17:05
finish    = 23:17:05        (start + 1 soat, 23:59:59 bilan cheklangan)
activeMin = 0.0             (LOCK ning juftini topmadi -> sanalmaydi)
```

**3. Trainer nima o'rgangan**

```
Tuesday: meanStart 899.8 (14:59)  σ 760.26
         meanFinish 1337.19 (22:17)  σ 89.97
```

σ juda katta — bu xodim beqaror ishlaydi.

**4. Processor nima hisoblaydi**

```
lo = 899.8  − 1.0 · 760.26 = 139.5   →  02:20
hi = 1337.19 + 1.0 · 89.97 = 1427.2  →  23:47

start  22:17 >= 02:20   ✓ ichida
finish 23:17 <= 23:47   ✓ ichida
                        →  chetlanish YO'Q
```

**5. Natijada nima yoziladi**

```json
{ "isAnomaly": false, "anomalyScore": 0, "riskScore": 0, "status": "normal",
  "zStart": -0.575, "zFinish": 0.666,
  "detectors": { "workingHours": {
      "triggered": false, "score": 0, "evaluated": true,
      "reason": "faollik ish oynasi ichida (02:20–23:47)" } } }
```

E'tibor bering: `zFinish = 0.666` — ya'ni ketish vaqti o'rtachadan
farq qiladi, lekin bu **oyna ichida** qolgani uchun shubhali emas.
Eski qoidada (`|z| > 1.2`) bu kun ham boshqacha baholanardi.

**6. Dashboardda qanday ko'rinadi**

Kulrang fon 02:20 dan 23:47 gacha, ichida ikkita **yashil** nuqta —
22:17 va 23:17. Jadvalda «Odatdagidek», daraja ustuni bo'sh.

---

## Sof ish vaqti — `activeMin`

Kun uzunligidan tashqari **sof ish vaqti** ham hisoblanadi: ochilish va
qulflanish oralig'idagi daqiqalar, tanaffuslar chiqarib tashlangan holda.

```
10:30–22:17    kun uzunligi 707 daqiqa,  sof ish 512 daqiqa,  tanaffus 195 daqiqa
```

Algoritm ([workday.active_minutes](services/workday.py)):

```
LOGON/UNLOCK/REMOTE_CONNECT     →  oraliq ochiladi
LOGOFF/LOCK/REMOTE_DISCONNECT   →  oraliq yopiladi, davomiyligi qo'shiladi
```

Bu **quyi chegara** — ikkita ataylab qilingan yon berish bor:

- **Juftini topmagan yopuvchi hodisa sanalmaydi.** Kun `LOCK` bilan
  boshlansa (odam kechqurundan beri kirgan), o'sha ochiq oraliq hisobga
  olinmaydi. Sun'iy cho'zib yuborishdan ko'ra kam ko'rsatgan yaxshi.
- **Kun `LOGOFF` siz tugasa**, ochiq oraliq kunning oxirgi hodisasigacha
  yopiladi — undan nariga cho'zilmaydi.

Hodisalar tartibsiz kelsa ham to'g'ri ishlaydi — funksiya o'zi saralaydi.

Dashboard jadvalida «Sof ish» ustuni sifatida ko'rinadi, hover'da tanaffus
vaqti.

---

## O'qitish jarayoni (train / retrain)

Dashboarddagi **«Odatiy jadvallarni yangilash»** tugmasi yoki
`POST /api/retrain`.

```
POST /api/retrain
      │
      ├─ jobs.create("retrain")            training_jobs ga hujjat
      │      DuplicateKeyError bo'lsa  →  HTTP 409
      │
      └─ fon thread'ida:
             stage = "collecting"   →  collect()
             stage = "training"     →  train()
             status = "finished" yoki "partial"
```

**Bir vaqtda faqat bitta o'qitish.** Buni `threading.Lock` emas, MongoDB
dagi **unique partial indeks** kafolatlaydi:

```js
{ status: 1 }  unique,  partialFilterExpression: { status: "running" }
```

`status: "running"` hujjat faqat bitta bo'la oladi. Nima uchun bu muhim:
`Lock` faqat bitta protsess ichida ishlaydi, indeks esa bazada — bir necha
protsess bo'lsa ham ishlaydi. Ikkinchi so'rov `DuplicateKeyError` oladi va
409 qaytariladi.

**Job hujjati holatni saqlaydi**, shuning uchun dastur qayta ishga
tushirilsa ham tarix qoladi:

```json
{ "_id": "6aa1046f...", "type": "retrain", "status": "finished",
  "stage": "finished", "startedAt": "...", "finishedAt": "...",
  "stats": { "days": 34, "clients": 5, "clientsRead": 15, "failedClients": [] },
  "baselineId": "6aa12294c00c35a67bdbd5c8", "error": null }
```

**`partial` holati.** Ba'zi xodimlar manba xatosi tufayli o'tkazib
yuborilgan bo'lsa, o'qitish baribir bajariladi (qolganlarining ma'lumoti
to'liq), lekin natija `finished` emas **`partial`** deb belgilanadi va
`failedClients` ro'yxati yoziladi. «Hammasi joyida» deb ko'rsatilmaydi.

**Osilib qolgan job.** Protsess job o'rtasida to'xtasa, hujjat `running`
holicha qolib **keyingi barcha o'qitishlarni bloklardi**. Shuning uchun
har ishga tushishda `jobs.recover_stale()` chaqiriladi va bunday hujjatlar
tozalanadi.

**Retrain `results` va `trigger_data` ni tozalamaydi** — eski natijalar
tarix sifatida qoladi, yangi kunlar yangi baseline bilan baholanadi.

CLI muqobili: `python collector.py` + `python trainer.py`.

---

## Ishga tushganda nima bo'ladi

`python main.py` — hammasi **bitta protsessda**:

```
1. create_app()                    FastAPI ilovasi
2. startup hodisasi:
     ensure_indexes()              6 ta indeks (idempotent)
     jobs.recover_stale()          osilib qolgan joblarni tozalash
     start_workers(stop_event)     WORKER_COUNT (3) ta daemon thread
     BackgroundScheduler           trigger, har TRIGGER_INTERVAL_HOURS
                                   birinchi o'tish +10 soniyadan keyin
3. uvicorn                         API_HOST:API_PORT
```

**Mongo yotgan bo'lsa ham dastur ko'tariladi** — indekslar keyingi trigger
o'tishida yaratiladi, `/api/health` esa xatoni ko'rsatib turadi.

> ⚠️ **`uvicorn --workers N` ISHLATILMAYDI.** Aks holda scheduler va
> worker thread'lar N barobar ko'payadi: trigger bir vaqtda N marta
> ishlaydi, joblar takrorlanadi.

Yaratiladigan indekslar:

| Collection | Indeks | Nima uchun |
|---|---|---|
| `raw_data_for_train` | UNIQUE `{clientId, date}` | dublikat kun bo'lmasin |
| `trigger_data` | UNIQUE `{clientId, date}` | dublikat kun bo'lmasin |
| `results` | UNIQUE `{clientId, date}` | upsert kaliti |
| `results` | `{isAnomaly, date}` | «oxirgi chetlanishlar» so'rovi |
| `results` | `{triggeredDetectors}` | multikey — detector bo'yicha filtr |
| `baseline` | UNIQUE `{clientId, baselineId}` | versiyalash |
| `training_jobs` | UNIQUE `{status}` partial | bir vaqtda bitta o'qitish |

---

## Dashboard qanday ishlaydi

`dashboard/` — **vanilla JS + inline SVG**, tashqi kutubxona yo'q, CDN yo'q.
Grafiklar brauzerda `document.createElementNS` bilan chiziladi.

### To'rtta panel

**1. Xulosa** — bir jumla:

> `xodim-06@desktop-006` bo'yicha **23 ish kuni** tekshirildi. Ulardan
> **5 kunda** ish oynasidan tashqarida faollik qayd etildi.

Baholanmagan kunlar bo'lsa sababi ham yoziladi.

**2. E'tibor talab qiladigan kunlar** — chetlanishli kunlar kartalari,
**daraja bo'yicha saralangan** (eng xavflisi tepada), `DASHBOARD_MAX_ISSUES`
(20) tagacha. Har kartada daraja yorlig'i: `24 · past`, `56 · yuqori`.

**3. Grafik** — xodim tanlanganiga qarab ikki xil:

| Tanlangan | Grafik |
|---|---|
| bitta xodim | «Ish oynasi va faollik vaqtlari» |
| «Barcha xodimlar» | «Umumiy manzara» matritsasi |

**4. Jadval** — barcha kunlar, 11 ustun: sana, xodim, birinchi/oxirgi
faollik, odatdagi vaqtlar, farqlar, sof ish, xulosa, daraja.

### Asosiy grafik mexanikasi

```
X o'qi   kunlar (sana bo'yicha saralangan, har ustun bitta kun)
Y o'qi   sutka soatlari 00:00 (past) → 24:00 (tepa)
```

| Element | Ma'nosi |
|---|---|
| **kulrang fon** | o'sha kunning ish oynasi (`windowStart` – `windowFinish`) |
| **yashil nuqta** | faollik oyna **ichida** |
| **qizil nuqta** | faollik oynadan **tashqarida** |
| **kulrang nuqta** | baseline yo'q, baholab bo'lmadi |

Har kunda ikkita nuqta: birinchi va oxirgi faollik. Rang **har nuqta uchun
alohida** — bir kunda kelish yashil, ketish qizil bo'lishi mumkin.

Nuqta rangi kulrang fonga **to'g'ridan-to'g'ri mos keladi**: qizil nuqta
doim kulrang zonadan tashqarida turadi. Ziddiyat bo'lishi mumkin emas.

Hover'da har elementda `<title>` — brauzerning o'z tooltip'i, tashqi
kutubxona shart emas.

### Dashboard hech qanday qiymatni o'zida saqlamaydi

Chegaralar, daraja yorliqlari va sana oralig'i `/api/health` dan keladi:

```json
{ "anomalyZThreshold": 1.0, "minDowSamples": 3,
  "severity": { "high": 75, "medium": 50, "low": 25 },
  "dashboard": { "rangeDays": 30, "maxIssues": 20 } }
```

Ya'ni `.env` ni o'zgartirsangiz dashboard ham darrov moslashadi — JS
faylga tegish shart emas.

### Eski yozuvlar bilan ishlash

Natijada `isAnomaly` maydoni bo'lmasa (eski yozuv), dashboard qoidani
**o'zi qo'llaydi**: `windowOf(row)` bilan oynani hisoblab, nuqta ichidami
tashqaridami deb qaraydi. Shuning uchun ma'lumot ta'mirlanmasdan ham
to'g'ri ko'rsatadi.

---

## Yangi detector qo'shish

Karkas aynan shuning uchun qurilgan. Ikki qadam, `processor.py` ga
tegilmaydi.

### 1-qadam: fayl yozish

`services/detectors/usb_activity.py`:

```python
"""USB faolligi detectori: ish oynasidan tashqarida USB ga fayl ko'chirish."""
from services.detectors.base import Detector


class UsbActivityDetector(Detector):
    name = "usbActivity"        # lowerCamelCase — Mongo maydon nomi bo'ladi
    default_weight = 0.8        # .env dagi DETECTOR_WEIGHT_USB_ACTIVITY ustidan yozadi

    def evaluate(self, ctx):
        # ctx da kunning hamma ma'lumoti bor:
        #   ctx.start, ctx.finish        datetime
        #   ctx.active_min               sof ish vaqti
        #   ctx.event_count              hodisalar soni
        #   ctx.day                      job dagi xom kun hujjati
        #   ctx.baseline, ctx.week       butun baseline va shu hafta kuni
        #   ctx.date, ctx.day_of_week    "2026-09-08", "Tuesday"

        soni = (ctx.day.get("usbFiles") or 0)
        if soni == 0:
            # Ma'lumot yo'q — "toza" deyish yolg'on bo'lardi.
            # skipped() natija umumiy ballga ta'sir qilmaydi.
            return self.skipped("USB ma'lumoti yo'q")

        chetlanish = soni > 50
        ball = min(100, soni * 2)
        return self.result(
            chetlanish, ball,
            reason=f"{soni} ta fayl USB ga ko'chirildi",
            details={"fileCount": soni},
            # fields — natijaning USTKI darajasiga chiqadigan maydonlar
            fields={"usbFileCount": soni},
        )
```

### 2-qadam: ro'yxatga qo'shish

`services/detectors/registry.py` oxirida:

```python
from services.detectors.usb_activity import UsbActivityDetector
...
register(WorkingHoursDetector())
register(UsbActivityDetector())        # <- bitta qator
```

Tayyor. Natijada avtomatik paydo bo'ladi:

```json
"triggers": { "workingHours": false, "usbActivity": true },
"triggeredDetectors": ["usbActivity"],
"detectors": { "usbActivity": { "triggered": true, "score": 84, "weight": 0.8, ... } },
"riskScore": 67
```

### Qoidalar

- **Holatsiz bo'lishi shart** — 3 ta worker thread bir vaqtda `evaluate()`
  ni chaqiradi. `self` ga hech narsa yozilmasin.
- **Nomi `lowerCamelCase`** — Mongo maydon nomiga aylanadi, nuqta va `$`
  bo'lmasin. Registry buni tekshiradi va noto'g'ri nomni rad etadi.
- **Ma'lumot yo'q bo'lsa `skipped()`** — `evaluated: false` bo'ladi va
  umumiy natijaga xalaqit bermaydi.
- **`details` da faqat skalyar qiymatlar** — hujjat shishib ketmasin.
- **Xato tashlasa ham kun yo'qolmaydi** — registry uni ushlaydi va
  `error` maydoniga yozadi.

---

## API

Barcha endpointlar `/api/docs` da ham hujjatlashtirilgan (FastAPI avtomatik).

| Endpoint | Method | Vazifasi |
|---|---|---|
| `/api/health` | GET | Tizim holati + dashboard sozlamalari |
| `/api/train` | POST | Birinchi o'qitish (baseline mavjud bo'lsa **409**) |
| `/api/retrain` | POST | Baseline yangilash: collector → trainer (**202**) |
| `/api/jobs` | GET | O'qitish joblari tarixi |
| `/api/jobs/{job_id}` | GET | Bitta job (yo'q bo'lsa **404**) |
| `/api/clients` | GET | Xodimlar ro'yxati |
| `/api/baseline` | GET | Joriy baseline hujjatlari |
| `/api/baseline/versions` | GET | Baseline versiyalari ro'yxati |
| `/api/results` | GET | Natijalar (filtrlar quyida) |
| `/api/results/{client_id}` | GET | Bitta xodim natijalari (yo'q bo'lsa **404**) |
| `/` va `/api/dashboard` | GET | Dashboard sahifasi |

### `GET /api/results` — filtrlar

| Parametr | Misol | Ma'nosi |
|---|---|---|
| `from`, `to` | `2026-08-01` | sana oralig'i |
| `client_id` | `6a68d16e...` | bitta xodim |
| `status` | `anomaly,insufficient` | vergul bilan bir nechta |
| `is_anomaly` | `true` | faqat chetlanishlar |
| `min_risk` | `50` | `riskScore >= 50` |
| `trigger` | `workingHours` | shu detector ishga tushgan kunlar |
| `limit`, `offset` | `100`, `0` | sahifalash (`API_PAGE_SIZE`, `API_PAGE_MAX`) |

Javob konverti:

```json
{ "total": 34, "limit": 100, "offset": 0, "items": [ ... ] }
```

Saralash: `date` kamayish, `hostname` o'sish tartibida.

### `GET /api/health`

```json
{ "mongo_main": "ok", "mongo_local": "ok", "rabbitmq": "ok",
  "queue_depth": 0, "workers": 3,
  "anomalyZThreshold": 1.0, "minDowSamples": 3,
  "severity": { "high": 75, "medium": 50, "low": 25 },
  "dashboard": { "rangeDays": 30, "maxIssues": 20 },
  "lastTrigger": { "status": "finished", "sent": 1, "skipped": 9, ... },
  "lastRetrain": { "status": "finished", "days": 34, "clients": 5, ... } }
```

`mongo_main`, `mongo_local`, `rabbitmq` — `"ok"` yoki `"error"`.
`queue_depth` — navbatdagi xabarlar soni, ulanib bo'lmasa `null`.

### `GET /api/clients`

```json
[{ "clientId": "...", "hostname": "azam@azam-upc", "fullName": null,
   "label": "azam@azam-upc", "days": 13, "lastDate": "2026-09-08",
   "stale": false }]
```

`label` — dashboard dropdown'i uchun: bir xil hostname'li xodimlarga qisqa
id qo'shiladi, o'chirilganiga `" — o'chirilgan"` yoziladi.

---

## Ma'lumot tuzilmalari

Mahalliy bazadagi (`ueba_local`) collectionlar.

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
- `start` / `finish` — **naive lokal ISO datetime**.
- `durationMin` = `finish − start` daqiqada; `activeMin` = tanaffuslarsiz.
- **Indeks:** UNIQUE `{clientId, date}`. Yozish — replacement upsert, ya'ni
  qayta yozish har doim xavfsiz (idempotent).

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

- Vaqtlar — **kun boshidan daqiqa** (`899.8` = 14:59).
- `weeks` da faqat manbada uchragan hafta kunlari bo'ladi.
- Namuna `minDowSamples` dan kam bo'lsa faqat `count`, qolgani `null`.
- `keptDays` — mean'i chiqqan hafta kunlaridagi kunlar yig'indisi.
- **Indeks:** UNIQUE `{clientId, baselineId}`.

`baseline_runs` — versiyalar reyestri:

```json
{ "_id": "6aa12294c00c35a67bdbd5c8", "trainedAt": "...", "windowDays": 90,
  "minDowSamples": 3, "clientCount": 5, "dayCount": 34, "current": true }
```

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

- `start` / `finish` bu yerda **faqat vaqt** (`"HH:MM:SS"`), arxivda esa
  to'liq ISO — format ataylab boshqacha.
- **Natija o'zi-o'ziga yetarli:** `usualStart`, `windowStart` kabi
  taqqoslash qiymatlari ichida saqlanadi. Dashboard «odatda qachon
  kelardi» ni joriy baseline'dan izlamaydi — shuning uchun baseline
  yangilanganda eski natijalar yonida noto'g'ri farq ko'rinmaydi.
- `baselineId` — qaysi versiya bilan baholangani. Tarixiy natijalar qayta
  baholanmaydi.
- `triggeredDetectors` massiv: bitta multikey indeks barcha detectorlar
  bo'yicha filtrni qoplaydi. Map bo'lsa har nom uchun alohida indeks
  kerak bo'lardi.
- **Indeks:** UNIQUE `{clientId, date}`, plus `{isAnomaly, date}` va
  `{triggeredDetectors}`.

`training_jobs` — o'qitish joblari, tuzilishi
[O'qitish jarayoni](#oqitish-jarayoni-train--retrain) da.

---

## Manba bazadagi indeks

`agentsessionstatuses` da hozir faqat `{clientId: 1, computerId: 1}` indeksi
bor — `dateTime` indekslanmagan. Bizning so'rov `clientId` + vaqt oralig'i
bo'yicha ketadi, ya'ni `clientId` prefiksigacha indeksdan foydalanadi, keyin
o'sha xodimning butun tarixini xotirada filtrlaydi.

Hozirgi hajmda (~2400 hujjat) muammo yo'q. Ma'lumot o'sganda DLP jamoasidan
so'rash kerak:

```js
db.agentsessionstatuses.createIndex({ clientId: 1, dateTime: -1 })
```

Bizning kod DLP bazasiga yoza olmaydi, shuning uchun buni faqat ular qo'sha
oladi.

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
to'g'rilaydi, Mongo/RabbitMQ tayyor bo'lgunicha kutadi (healthcheck),
reboot'dan keyin o'zi ko'tariladi.

`dashboard/` papkasi konteynerga **volume** sifatida ulangan — statik
fayllar o'zgartirilsa brauzerni yangilash kifoya, obrazni qayta qurish
shart emas. Python kodi uchun esa `up -d --build` kerak.

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
[tests/test_config.py](tests/test_config.py) qo'riqlaydi: u `config.py` ni
AST bilan tekshiradi (har bir bosh harfli qiymat `os.getenv` orqali
olinishi shart) va keyin har bir sozlamani haqiqatan almashtirib ko'radi.
Kimdir kodga qattiq qiymat yozib qo'ysa test yiqiladi.

| Guruh | Sozlamalar |
|---|---|
| **Manba baza** | `MONGO_URI`, `DB_NAME`, `SESSION_COLLECTION`, `SESSION_START_STATUSES`, `SESSION_END_STATUSES` |
| **Mahalliy baza** | `LOCAL_MONGO_URI`, `LOCAL_DB_NAME`, `COL_*` (6 ta) |
| **RabbitMQ** | `RABBITMQ_HOST/PORT/USER/PASSWORD`, `QUEUE_NAME`, `WORKER_COUNT`, `MAX_RETRIES` |
| **API** | `API_HOST`, `API_PORT`, `API_PAGE_SIZE`, `API_PAGE_MAX` |
| **Pipeline** | `DAYS_WINDOW`, `TRIGGER_INTERVAL_HOURS`, `LOOKBACK_HOURS`, `BATCH_SIZE`, `SOURCE_READ_RETRIES`, `SOURCE_READ_RETRY_DELAY`, `SINGLE_EVENT_STAY_HOURS`, `RESULTS_RETENTION_DAYS`, `BASELINE_KEEP_VERSIONS`, `BULK_BATCH_SIZE` |
| **Anomaliya** | `MIN_DOW_SAMPLES`, `ANOMALY_Z_THRESHOLD`, `ANOMALY_Z_FULL_SCALE` |
| **Detectorlar** | `DETECTOR_WEIGHT_<NOM>` |
| **Dashboard** | `DASHBOARD_RANGE_DAYS`, `DASHBOARD_MAX_ISSUES`, `SEVERITY_HIGH`, `SEVERITY_MEDIUM`, `SEVERITY_LOW` |

### Eng ko'p sozlanadigan uchtasi

| Sozlama | Ta'siri |
|---|---|
| `MIN_DOW_SAMPLES` | Kamaytirilsa ko'proq kun baholanadi, lekin norma ishonchsizroq |
| `ANOMALY_Z_THRESHOLD` | Kattalashtirilsa oyna kengayadi, chetlanish kamayadi |
| `ANOMALY_Z_FULL_SCALE` | Kichraytirilsa ballar yuqoriroq chiqadi |

```bash
# .env ni tahrirlash, keyin:
docker compose up -d          # `restart` EMAS
```

> **Chegaralarni o'zgartirsangiz baseline qayta o'qitilishi kerak** —
> aks holda yangi kunlar eski normaga solishtiriladi.

Xavfsizlik: noto'g'ri qiymatlar jimgina ushlanadi. `ANOMALY_Z_THRESHOLD=0`
→ 1.0 ga qaytadi (nolga bo'linish bo'lardi); `ANOMALY_Z_FULL_SCALE`
chegaradan kichik berilsa → `T+2`; detector vazni `[0, 1]` ga siqiladi.

---

## Loglar va kuzatuv

Loglar `logs/ueba.log` ga va konsolga yoziladi:

```
2026-09-09 14:10:43 | INFO | ueba.collector | Collector boshlandi: 15 active client, oyna ...
2026-09-09 14:10:43 | INFO | ueba.collector | 6a68d16e... (azam@azam-upc): 13 kun yozildi
2026-09-09 14:11:23 | INFO | ueba.trigger   | trigger run: 15 client, 369 yangi event, 1 kun yuborildi, 9 kun skip
2026-09-09 14:11:23 | INFO | ueba.worker    | Worker 2: job bajarildi (1 kun)
```

Logger nomlari: `ueba.collector`, `ueba.trainer`, `ueba.trigger`,
`ueba.worker`, `ueba.mongo`, `ueba.detectors`, `ueba.jobs`, `ueba.main`.

```bash
docker compose logs -f app                    # jonli
docker compose logs app | grep ERROR          # faqat xatolar
tail -f logs/ueba.log
```

Tizim holatini bir qarashda ko'rish:

```bash
curl -s localhost:8000/api/health | python -m json.tool
```

---

## Muammolarni bartaraf etish

### Hamma kun «Baholanmadi»

Baseline yo'q yoki namuna yetarli emas.

```bash
curl -s localhost:8000/api/baseline | python -m json.tool | head -40
```

`weeks` ichida `meanStart: null` bo'lsa — o'sha hafta kuni uchun kun soni
`MIN_DOW_SAMPLES` dan kam. Yechim: ko'proq ma'lumot to'planishini kutish,
`DAYS_WINDOW` ni kattalashtirish, yoki `MIN_DOW_SAMPLES` ni kamaytirish
(keyin qayta o'qitish).

### Deyarli hamma kun «Chetlanish»

Ehtimol chegara juda tor yoki baseline eski manbada qurilgan.

```bash
# .env: ANOMALY_Z_THRESHOLD=1.5   (oyna kengayadi)
docker compose up -d
# keyin: dashboarddagi «Odatiy jadvallarni yangilash»
```

### Yangi kunlar paydo bo'lmayapti

```bash
curl -s localhost:8000/api/health | python -m json.tool | grep -A5 lastTrigger
```

- `queue_depth` katta bo'lsa — workerlar ishlamayapti, loglarni qarang.
- `rabbitmq: "error"` bo'lsa — navbat yotgan, trigger o'tishi bekor
  qilinadi (ma'lumot yo'qolmaydi, cursor orqada qoladi).
- Trigger har `TRIGGER_INTERVAL_HOURS` (5) soatda ishlaydi — hozircha
  vaqti kelmagan bo'lishi mumkin.

### Bitta kun baholanmay qolib ketdi

Worker 3 marta urinib job'ni tashlagan bo'lsa, kun `trigger_data` da
«yuborilgan» deb turadi va avtomatik qaytmaydi. Qo'lda qaytarish:

```js
// mongosh ueba_local
db.trigger_data.deleteOne({ clientId: "...", date: "2026-09-08" })
```

Keyingi trigger o'tishi o'sha kunni qayta yuboradi.

### Chegaralarni o'zgartirdim, eski natijalar eski qoidada qoldi

```bash
python scripts/rebuild_results.py            # quruq yurish, hisobot
python scripts/rebuild_results.py --apply    # yozish
```

Skript `raw_data_for_train` arxividagi kunlarni joriy baseline bilan qayta
baholaydi. Manba bazaga tegmaydi, yozishdan oldin zaxira collection
yaratadi, mahalliy va manba baza nomi bir xil bo'lsa to'xtaydi.

### O'qitish 409 qaytaryapti

Boshqa o'qitish ketmoqda. Agar u osilib qolgan bo'lsa:

```bash
curl -s localhost:8000/api/jobs | python -m json.tool | head -20
docker compose restart app     # startup'da recover_stale() tozalaydi
```

### `.env` o'zgartirdim, hech narsa o'zgarmadi

`docker compose restart` yetarli emas — `env_file` faqat konteyner
yaratilganda o'qiladi:

```bash
docker compose up -d
```

---

## Testlar

```bash
for t in tests/*.py; do venv/bin/python $t; done
```

`pytest` ishlatilmaydi — har test `bool` qaytaradi, `python tests/xxx.py`
bilan yurgiziladi va oxirida `HAMMASI O'TDI ✓ (n/n)` yozadi.

| Fayl | Nimani qo'riqlaydi | Soni |
|---|---|---|
| `test_config.py` | Har bir sozlama `.env` dan o'qiladimi; noto'g'ri qiymat tizimni buzmaydimi | 4 |
| `test_workday.py` | Sof ish vaqti (tanaffus, chala ma'lumot, tartibsiz hodisalar), kunlarga ajratish | 7 |
| `test_collector.py` | Oyna chegaralari (COL-01), manba xatosi (COL-04), arxiv tozalash (COL-02), qayta urinish | 9 |
| `test_detectors.py` | Ball jadvali, oyna qoidasi, `riskScore`, vazn, xato izolyatsiyasi, nom tekshiruvi | 13 |
| `test_baseline_versions.py` | Baseline versiyalash, natijaning o'zi-o'ziga yetarliligi | 4 |
| `test_jobs.py` | Bir vaqtda faqat bitta o'qitish, osilib qolgan job tiklanishi | 4 |
| | **Jami** | **41** |

Testlar jonli bazani talab qilmaydi — `test_collector.py` da mini-Mongo
emulyatori bor (`FakeCollection`, `FakeDB`), qolganlari sof funksiyalarni
tekshiradi.

Alohida e'tiborga loyiq ikkita tekshiruv:

- `test_detectors.test_anomaly_flag_independent_of_score` — 0 dan 400
  daqiqagacha 0.1 qadam bilan yurib, chetlanish bayrog'i va ball
  orasida ziddiyat yo'qligini tasdiqlaydi.
- `test_config.test_env_haqiqatan_ustidan_yozadi` — 42 ta sozlamaning
  **har birini** almashtirib, o'zgarganini tekshiradi.

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
  jobs.py                  o'qitish joblari holati (ARCH-01)
  detectors/
    scoring.py             ball, riskScore, status — chegaralar FAQAT shu yerda
    working_hours.py       ish oynasi qoidasi
    registry.py            ro'yxat + natijalarni birlashtirish
    base.py                DayContext, DetectorResult, Detector bazasi

mq/
  rabbitmq.py              ulanish, durable queue, publish
  worker.py                3 ta thread, retry siyosati

api/
  app.py                   FastAPI yig'ilishi, PyMongoError -> 503
  routes.py                barcha endpointlar

dashboard/
  index.html               4 ta panel
  static/script.js         vanilla JS + inline SVG
  static/style.css

scripts/
  rebuild_results.py       natijalarni arxivdan qayta qurish

tests/                     41 ta tekshiruv
utils/
  helpers.py               vaqt funksiyalari, kunlik agregat, ism tanlash
  logger.py                logging sozlamasi
```

---

## Edge caselar

Kodda ataylab hisobga olingan holatlar.

| Holat | Xatti-harakat |
|---|---|
| `clients` da `disabled` maydoni yo'q | `$or` so'rovi — xodim **active** hisoblanadi |
| `hostname` bo'sh yoki yo'q | o'rniga `str(_id)` ishlatiladi |
| Vaqt maydoni parse bo'lmadi | o'sha hodisa skip, xato tashlanmaydi (bu «ma'lumot yaroqsiz», «o'qib bo'lmadi» emas) |
| **Manbani o'qib bo'lmadi** (tarmoq uzildi) | 2 marta qayta urinish → baribir bo'lmasa `SourceReadError`; **shu xodim umuman yozilmaydi**, eski ma'lumoti saqlanadi, job `partial` bo'ladi |
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
| Worker 3 marta urinib tashladi | kunlar `trigger_data` da «yuborilgan» → avtomatik qaytmaydi (qo'lda qaytarish yuqorida) |
| Buzuq job JSON keldi | darrov tashlanadi, qayta urinilmaydi — buzuq JSON qayta urinishdan tuzalmaydi |
| Bitta detector xato tashladi | `registry.run` uni ushlaydi, `evaluated: false` yoziladi — kun yo'qolmaydi |
| Retrain davomida job keldi | eski baseline swap'gacha joyida — worker bo'sh baseline ko'rmaydi |
| Bir (clientId, date) qayta yozildi | replacement upsert → idempotent, dublikat yo'q |
| O'qitish o'rtasida protsess to'xtadi | job `running` holicha qolardi va keyingilarini bloklardi → startup'da `recover_stale()` tozalaydi |

---

## Muhim qoidalar

1. **DLP bazasi 100% read-only** — ikkita alohida MongoClient, asosiysiga
   faqat `find()`. Bu to'siq kod darajasida, sozlama emas.
2. **Baseline bir marta o'qitiladi** — har 5 soatlik tsiklda qayta
   qurilmaydi. Yangilash faqat tugma orqali.
3. **Baseline versiyalanadi** — retrain davomida eski versiya
   ishlayveradi, almashtirish atomik. Har natijada `baselineId` yoziladi.
4. **Natija o'zi-o'ziga yetarli** — `usualStart`, `stdStart`,
   `windowStart` kabi taqqoslash qiymatlari natijaning ichida saqlanadi.
   Dashboard «odatda qachon kelardi» ni joriy baseline'dan izlamaydi.
5. **Hech narsa yo'qolmaydi va takrorlanmaydi** — trigger cursor bilan
   ishlaydi, avval publish qiladi keyin yozadi, `results` upsert'i
   idempotent.
6. **Kunlik agregat qoidasi:** 0 hodisa → kun yo'q; 1 hodisa →
   `finish = start + SINGLE_EVENT_STAY_HOURS` (23:59:59 bilan cheklangan);
   2+ hodisa → `min/max`. 12 soatlik filtr yo'q.
7. **Xodim nomi:** asosiy identifikator `clientId`, ko'rsatish uchun
   `hostname`. DLP bazasidagi ism maydonlari to'liq emas va takrorlanadi,
   shuning uchun ism faqat haqiqiy bo'lganda ishlatiladi.
8. **Kech kelish va erta ketish chetlanish emas** — ular oyna ichida
   qoladi. Ongli qaror: tizim intizomni emas, ish vaqtidan tashqaridagi
   faollikni kuzatadi.
9. **Ball chetlanishni belgilamaydi** — bayroq (`isAnomaly`) va o'lchov
   (`anomalyScore`) ajratilgan. Aks holda eng kichik chetlanish ham
   majburan yuqori ball olardi.
10. **Kodda qattiq yozilgan sozlama yo'q** — 42 tasi ham `.env` da,
    `test_config.py` buni qo'riqlaydi.
