# UEBA — Ish vaqti tahlili

Xodimlarning **ishga kelish** va **ketish** vaqtlarini kuzatib, har birining o'z odatiy jadvalidan chetlanishini **z-score** bilan aniqlaydigan tizim.

Ma'lumot manbai — DataGaze DLP tizimining MongoDB'sidagi **`agentsessionstatuses`** collection'i: agent yuboradigan hozirlik qaydlari (tizimga kirish/chiqish, ekranni ochish/qulflash, masofadan ulanish). Har kundagi **eng birinchi hodisa = kelish vaqti**, **eng oxirgi hodisa = ketish vaqti**.

> To'liq arxitektura spetsifikatsiyasi: [UEBA_PIPELINE_ARCHITECTURE_V2.md](UEBA_PIPELINE_ARCHITECTURE_V2.md)

---

## Dashboard

Natijalar statistika tilida emas, oddiy tilda ko'rsatiladi — «5 soat 18 daqiqa kech keldi, keldi 18:00, odatda payshanbalarda 12:43».

![Dashboard: bitta xodim — xulosa, chetlanishli kunlar, odatiy oraliq grafigi va jadval](image.png)

*Yuqorida: bitta xodim tanlangan holat. Grafikda X — kunlar, Y — sutka soatlari; kulrang fon — o'sha kunning ish oynasi; ikkita nuqta — birinchi va oxirgi faollik (oyna ichida yashil, tashqarida qizil, baseline yo'q bo'lsa kulrang).*

![Barcha xodimlar: umumiy manzara matritsasi](image-1.png)

*Yuqorida: xodim tanlanmagan holat — qatorlar xodimlar, ustunlar kunlar. Har katak rangi o'sha kunning holati.*

---

## Qanday ishlaydi

```
alpha-demo (DLP bazasi, faqat o'qish)
        │
        ├─── COLLECTOR ──► raw_data_for_train    (90 kunlik arxiv, train uchun)
        │                        │
        │                   TRAINER ──► baseline  (client × hafta kuni statistikasi)
        │                                  │
        └─── TRIGGER ──► RabbitMQ ──► WORKER ──► results  (z-score natijalar)
             (har 5 soat)              (x3)         │
                                                DASHBOARD
```

1. **Collector** — 90 kunlik tarixni yig'ib kunlik agregatlarga aylantiradi (faqat train paytida ishlaydi).
2. **Trainer** — har xodim uchun **har hafta kuni alohida** o'rtacha kelish/ketish vaqti va standart og'ishni hisoblaydi. Shanba faqat shanbalar bilan solishtiriladi.
3. **Trigger** — har 5 soatda faqat **yangi** ma'lumotni oladi (qayerda to'xtaganini `trigger_data` cursor'idan biladi) va navbatga yuboradi.
4. **Worker** (3 ta) — kunlarni detectorlardan o'tkazib ball va `riskScore` hisoblaydi.
5. **Dashboard** — natijalarni **oddiy tilda** ko'rsatadi: «5 soat 18 daqiqa kech keldi — keldi 18:00, odatda payshanbalarda 12:43». Z-score ichkarida qoladi, ekranda ko'rinmaydi.

### Ish kuni qayerdan olinadi

Yagona manba — **`agentsessionstatuses`**: agentning o'z hozirlik qaydlari.
Olti xil status uch juftlik hosil qiladi:

```
LOGON          <-> LOGOFF               tizimga kirish / chiqish
UNLOCK         <-> LOCK                 ekranni ochish / qulflash
REMOTE_CONNECT <-> REMOTE_DISCONNECT    masofadan ulanish / uzilish
```

`clientId` bevosita `clients._id` ga bog'lanadi. Kun boshi — birinchi hodisa,
oxiri — oxirgi hodisa.

**`activeMin` — sof ish vaqti.** Ochilish va qulflanish oralig'idagi
daqiqalar yig'indisi, tanaffuslar chiqarib tashlangan holda:

```
10:30–22:17   kun uzunligi 707 daqiqa,  sof ish 512 daqiqa,  tanaffus 195 daqiqa
```

Bu quyi chegara — juftini topmagan hodisalar sanalmaydi (kun `LOCK` bilan
boshlansa, ya'ni odam kechqurundan beri kirgan bo'lsa, o'sha ochiq oraliq
hisobga olinmaydi). Sun'iy cho'zib yuborishdan ko'ra kam ko'rsatgan yaxshi.

> Ilgari ish vaqti 16 ta faollik collection'idan (`activewindows`,
> `webvisitings`, `keyloggers` va h.k.) chiqarilardi: kunning birinchi va
> oxirgi eventi ish vaqti deb olinardi. Bu **xulosa** edi — fon jarayoni ham
> event bergani uchun kun sun'iy cho'zilardi, tanaffusni esa umuman ko'rib
> bo'lmasdi. Endi agentning o'z qaydlari ishlatiladi: har client uchun
> 16 ta emas, **bitta so'rov**, va faollikdan taxmin emas — haqiqiy hozirlik.

### Anomaliya qoidasi: ish oynasidan tashqaridagi faollik

Baseline har hafta kuni uchun bitta **ish oynasini** beradi:

```
lo = usualStart  − T·σ(start)        oynaning quyi cheti
hi = usualFinish + T·σ(finish)       oynaning yuqori cheti      T = ANOMALY_Z_THRESHOLD (1.0)
```

Masalan `usualStart 09:00 (σ=10 daq)`, `usualFinish 16:00 (σ=20 daq)` → oyna **08:50 – 16:20**.

```
start  < lo   ->  oynadan OLDIN faollik   ->  shubhali
finish > hi   ->  oynadan KEYIN faollik   ->  shubhali
ikkalasi ham oyna ichida                  ->  shubha YO'Q
```

Bu **aniq** ishlaydi: kunning barcha eventlari `start` va `finish` orasida yotadi,
shuning uchun `start ≥ lo` va `finish ≤ hi` bo'lsa o'sha kunning **hamma** faolligi
oyna ichida bo'ladi — alohida eventlarni tekshirish shart emas.

> **Kech kelish va erta ketish shubhali EMAS.** Odatda 09:00 da keladigan xodim
> 13:00 da kelsa — 13:00 oyna ichida, hech narsa chiqmaydi. Tizim intizomni emas,
> **ish vaqtidan tashqaridagi faollikni** kuzatadi.

**1-qadam — chetlanishmi?** Ikkilik qaror: oynadan tashqarida bo'lgan **har qanday**
faollik chetlanish, hatto 1 daqiqa bo'lsa ham.

```
isAnomaly = tashqarida > 0
```

**2-qadam — darajasi qanday?** `anomalyScore` ni z-score beradi: chetlanish
xodimning **o'z og'ishi (σ)** birligida qanchalik katta ekanini o'lchaydi.

```
zOut = max(zStart, zFinish)          faqat oynadan CHIQARUVCHI tomon
ball = 100 · min(1, (zOut − T) / (ANOMALY_Z_FULL_SCALE − T))        T = 1.0
```

| zOut | 1.0 | 1.5 | 2.0 | 2.5 | ≥ 3.0 |
|---|---|---|---|---|---|
| **ball** | 1 | 25 | 50 | 75 | **100** |

Chetlanish bo'lgan kun hech qachon 0 ball olmaydi (minimal 1). σ = 0 bo'lsa
(xodim sekundma-sekund bir xil keladi) har qanday chiqish 100 ball oladi.

> **Nega z, daqiqa emas.** Bir xil 30 daqiqalik chiqish har kuni aniq 09:00 da
> keladigan xodim uchun favqulodda holat, jadvali beqaror xodim uchun esa oddiy
> tebranish. z-score ayni shu farqni hisobga oladi — daqiqa hisobga olmaydi.

**Muhim matematik ayniyat:** oyna `mean ± T·σ` bo'lgani uchun «oynadan tashqarida»
degani aynan «`zOut > T`» degani. Ikkalasi bir xil qoidaning ikki ko'rinishi.
Qaror oyna bilan qilinadi, chunki u `σ = 0` bo'lganda ham ishlaydi.

E'tibor bering: bu **modul emas, ishorali** taqqoslash. `zStart > 1` — erta kelish
(oynadan tashqarida), `zStart < −1` esa kech kelish (oyna **ichida**, shubhali emas).

| Shart | `status` | Rang |
|---|---|---|
| oynadan tashqarida faollik bor | `anomaly` | qizil |
| hamma faollik oyna ichida | `normal` | yashil |
| baseline yo'q | `insufficient` | kulrang |

`zStart`/`zFinish` hisoblanishda davom etadi, lekin **baholashda ishlatilmaydi** —
ular faqat jadvaldagi «odatdagidan 3 soat erta keldi» kabi izohlar uchun.

### Detectorlar va `riskScore`

Har bir detector bitta signalni **bir xil 0–100 shkalaga** o'giradi. Hozir bitta
detector bor — `workingHours` (ish vaqti). Yangi detector qo'shish:
`services/detectors/` ga bitta fayl yozib, `registry.py` ro'yxatiga qo'shish
kifoya — `processor.py` o'zgarmaydi.

Umumiy xavf barcha detectorlar balidan **vazn** bilan yig'iladi:

```
toza_qolish = ∏(1 − ball_i/100 · vazn_i)
riskScore   = 100 · (1 − toza_qolish)
```

Ma'nosi: har bir detector "toza qolish" ehtimolini kamaytiradi. Bitta kuchli
signal ham, ko'p kichik signal ham riskni oshiradi, lekin 100 dan oshmaydi.

**Vazn** = shu detector yakka o'zi berishi mumkin bo'lgan eng yuqori risk.
Vazn 1.0 → bali to'liq o'tadi; 0.4 → yakka o'zi 40 dan yuqori risk bera olmaydi;
0 → "soya rejim" (ishlaydi, natijaga yoziladi, riskka ta'sir qilmaydi).
`.env` dan sozlanadi, kodga tegilmaydi:

```
DETECTOR_WEIGHT_WORKING_HOURS=0.4
```

Bitta detector va vazn 1.0 bo'lganda `riskScore == anomalyScore`.

---

## Ishga tushirish (Docker Compose — tavsiya etilgan)

`.env` da `MONGO_URI` va `DB_NAME` asosiy DLP bazasiga ko'rsatib turgan bo'lsin (faqat o'qiladi). Qolgan sozlamalar default qiymatlari bilan ishlaydi.

```bash
docker compose up -d --build          # mongo + rabbitmq + app
docker compose exec app python collector.py    # 90 kunlik tarixni yig'ish
docker compose exec app python trainer.py      # baseline qurish
```

Dashboard: **http://localhost:8000**

| Buyruq | Vazifasi |
|---|---|
| `docker compose ps` | servislar holati |
| `docker compose logs -f app` | jonli loglar |
| `docker compose restart app` | dasturni qayta ishga tushirish |
| `docker compose down` | to'xtatish (data volume'da qoladi) |

Compose timezone'ni (`TZ=Asia/Tashkent`) va servis manzillarini o'zi to'g'rilaydi, Mongo/RabbitMQ tayyor bo'lgunicha kutadi va reboot'dan keyin o'zi ko'tariladi.

### Docker'siz (lokal ishlab chiqish)

```bash
docker run -d --name ueba-mongo -p 27017:27017 -v ueba_mongo_data:/data/db mongo:8.0.4
docker run -d --name ueba-rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3.13-management

python -m venv venv && venv/bin/pip install -r requirements.txt
venv/bin/python collector.py
venv/bin/python trainer.py
venv/bin/python main.py
```

> ⚠️ Bu usulda ikkita narsaga e'tibor bering (Compose'da ular avtomatik hal qilingan):
> **1)** `main.py` faqat **bitta protsess** sifatida ishlaydi — uvicorn'ning `--workers N` rejimi ishlatilmaydi, aks holda scheduler va workerlar N barobar ko'payadi.
> **2)** Server timezone'i xodimlar timezone'i bilan bir xil bo'lishi kerak (`Asia/Tashkent`) va keyin o'zgartirilmasligi lozim.

---

## Kundalik foydalanish

| Amal | Qanday |
|---|---|
| Natijalarni ko'rish | http://localhost:8000 |
| Baseline yangilash | dashboard'dagi **«Baseline yangilash»** tugmasi (collector + trainer avtomatik ketadi) |
| Tizim holati | `curl localhost:8000/api/health` |
| Loglar | `logs/ueba.log` yoki `docker compose logs -f app` |

Trigger **faqat avtomatik** ishlaydi — qo'lda ishga tushirish yo'li yo'q. Oraliq `.env` dagi `TRIGGER_INTERVAL_HOURS` bilan o'zgartiriladi.

### API

| Endpoint | Method | Vazifasi |
|---|---|---|
| `/api/health` | GET | Mongo, RabbitMQ, navbat, oxirgi trigger/retrain holati |
| `/api/train` | POST | Birinchi o'qitish (baseline mavjud bo'lsa 409) |
| `/api/retrain` | POST | Baseline yangilash: collector → trainer |
| `/api/results` | GET | Natijalar (`durationMin` — kun uzunligi, `activeMin` — sof ish vaqti): `from`, `to`, `client_id`, `status`, `is_anomaly`, `min_risk`, `trigger`, `limit`, `offset` |
| `/api/results/{client_id}` | GET | Bitta xodim natijalari |
| `/api/baseline` | GET | Joriy versiyadagi odatiy jadvallar |
| `/api/baseline/versions` | GET | Baseline versiyalari tarixi |
| `/api/jobs` | GET | O'qitish job'lari tarixi va holati |
| `/api/clients` | GET | Dashboard dropdown'i: xodimlar (ism bo'lsa qo'shiladi; o'chirilganlari va bir xil nomlilari belgilanadi) |
| `/api/docs` | GET | Swagger |

---

## Loyiha tuzilishi

```
docker-compose.yml   mongo + rabbitmq + app
Dockerfile           app obrazi
config.py            barcha sozlamalar (.env dan)
main.py              FastAPI + APScheduler + worker thread'lar
collector.py         CLI: tarix yig'ish
trainer.py           CLI: baseline qurish

services/
  mongo.py           2 ta alohida ulanish: asosiy (RO) + mahalliy (RW)
  collector.py       90 kunlik tarixni yig'ish
  trainer.py         baseline qurish (tmp + atomik swap)
  trigger.py         cursor + dedup + navbatga yuborish
  processor.py       z-score hisoblash (sof funksiya)

mq/
  rabbitmq.py        ulanish, publish, navbat
  worker.py          worker thread'lari (consume → processor → results)

api/
  app.py, routes.py  FastAPI endpointlari

dashboard/
  index.html, static/  vanilla JS + inline SVG (tashqi kutubxonasiz)

utils/
  helpers.py         collection mapping, vaqt funksiyalari, kunlik agregat, status
  logger.py          konsol + logs/ueba.log
```

---

## Muhim qoidalar

1. **Asosiy baza 100% read-only** — kodda ikkita alohida MongoClient bor, asosiysiga faqat `find()` chaqiriladi.
2. **Baseline bir marta o'qitiladi** — har 5 soatlik tsiklda qayta qurilmaydi. Yangilash faqat tugma orqali.
3. **Baseline versiyalanadi** — har o'qitish yangi versiya yaratadi, eskilari saqlanadi (oxirgi 5 tasi). Retrain davomida eski versiya ishlayveradi. Har natijada qaysi versiya bilan baholangani (`baselineId`) yoziladi; tarixiy natijalar qayta baholanmaydi.
4. **Hech narsa yo'qolmaydi va takrorlanmaydi** — trigger cursor bilan ishlaydi, yuborilganini `trigger_data` ga yozib boradi.
5. **Kunlik agregat qoidasi:** 0 event → kun yo'q; 1 event → `finish = start + 1 soat` (23:59:59 bilan cheklangan); 2+ event → `min/max`. 12 soatlik filtr yo'q.
6. **Xodim nomi:** asosiy identifikator — `clientId`, ko'rsatish uchun `hostname` (100% to'la va noyob). DLP bazasidagi ism maydonlari to'liq emas (`fullName` 65%, unda 5 ta takroriy «user_1»), shuning uchun ism faqat **haqiqiy bo'lganda** ishlatiladi. Ekranda: ism bo'lsa ism («Familiya Ism»), bo'lmasa hostname («user@desktop-a1b2c3»).
7. **`activities` collection'i ishlatilmaydi** — u event jurnali emas, kunlik agregat jadvali (`dateTime` doim 00:00). Pipeline 16 ta real event collection'idan foydalanadi.
