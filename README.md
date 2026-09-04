# UEBA — Ish vaqti tahlili

Xodimlarning **ishga kelish** va **ketish** vaqtlarini kuzatib, har birining o'z odatiy jadvalidan chetlanishini **z-score** bilan aniqlaydigan tizim.

Ma'lumot manbai — DataGaze DLP tizimining MongoDB'si: xodim kompyuterlaridan keladigan aktivlik yozuvlari (email, Telegram, fayl operatsiyalari, sayt tashriflari va h.k.). Har kundagi **eng birinchi event = kelish vaqti**, **eng oxirgi event = ketish vaqti**.

> To'liq arxitektura spetsifikatsiyasi: [UEBA_PIPELINE_ARCHITECTURE_V2.md](UEBA_PIPELINE_ARCHITECTURE_V2.md)

---

## Qanday ishlaydi

```
alpha-demo (DLP bazasi, faqat o'qish)
        │
        ├─── COLLECTOR ──► raw_data_for_train    (60 kunlik arxiv, train uchun)
        │                        │
        │                   TRAINER ──► baseline  (client × hafta kuni statistikasi)
        │                                  │
        └─── TRIGGER ──► RabbitMQ ──► WORKER ──► results  (z-score natijalar)
             (har 5 soat)              (x3)         │
                                                DASHBOARD
```

1. **Collector** — 60 kunlik tarixni yig'ib kunlik agregatlarga aylantiradi (faqat train paytida ishlaydi).
2. **Trainer** — har xodim uchun **har hafta kuni alohida** o'rtacha kelish/ketish vaqti va standart og'ishni hisoblaydi. Shanba faqat shanbalar bilan solishtiriladi.
3. **Trigger** — har 5 soatda faqat **yangi** ma'lumotni oladi (qayerda to'xtaganini `trigger_data` cursor'idan biladi) va navbatga yuboradi.
4. **Worker** (3 ta) — kunlarni baseline bilan solishtirib z-score hisoblaydi.
5. **Dashboard** — natijalarni **oddiy tilda** ko'rsatadi: «5 soat 18 daqiqa kech keldi — keldi 18:00, odatda payshanbalarda 12:43». Z-score ichkarida qoladi, ekranda ko'rinmaydi.

### Z-score va statuslar

```
zStart  = (meanStart − start)   / stdStart      erta kelish  → musbat
zFinish = (finish − meanFinish) / stdFinish     kech ketish  → musbat
```

| \|z\| | Status | Rang |
|---|---|---|
| < 0.5 | normal | yashil |
| 0.5 – 1.2 | watch | sariq |
| 1.2 – 1.8 | anomaly | to'q sariq |
| ≥ 1.8 | severe | qizil |
| baseline yo'q | insufficient | kulrang |

---

## Ishga tushirish (Docker Compose — tavsiya etilgan)

`.env` da `MONGO_URI` va `DB_NAME` asosiy DLP bazasiga ko'rsatib turgan bo'lsin (faqat o'qiladi). Qolgan sozlamalar default qiymatlari bilan ishlaydi.

```bash
docker compose up -d --build          # mongo + rabbitmq + app
docker compose exec app python collector.py    # 60 kunlik tarixni yig'ish
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
| `/api/results` | GET | Natijalar: `from`, `to`, `client_id`, `status`, `limit`, `offset` |
| `/api/results/{client_id}` | GET | Bitta xodim natijalari |
| `/api/baseline` | GET | Xodimlarning o'rganilgan odatiy jadvallari |
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
  collector.py       60 kunlik tarixni yig'ish
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
3. **Retrain davomida eski baseline ishlayveradi** — yangisi `baseline_tmp` da qurilib, tayyor bo'lgach atomik almashtiriladi.
4. **Hech narsa yo'qolmaydi va takrorlanmaydi** — trigger cursor bilan ishlaydi, yuborilganini `trigger_data` ga yozib boradi.
5. **Kunlik agregat qoidasi:** 0 event → kun yo'q; 1 event → `finish = start + 1 soat` (23:59:59 bilan cheklangan); 2+ event → `min/max`. 12 soatlik filtr yo'q.
6. **Xodim nomi:** asosiy identifikator — `clientId`, ko'rsatish uchun `hostname` (100% to'la va noyob). DLP bazasidagi ism maydonlari to'liq emas (`fullName` 65%, unda 5 ta takroriy «user_1»), shuning uchun ism faqat **haqiqiy bo'lganda** ishlatiladi. Ekranda: ism bo'lsa ism («Azamat Muqumjonov»), bo'lmasa hostname («sanja@desktop-q46u2et»).
7. **`activities` collection'i ishlatilmaydi** — u event jurnali emas, kunlik agregat jadvali (`dateTime` doim 00:00). Pipeline 16 ta real event collection'idan foydalanadi.
