# UEBA PIPELINE - TO'LIQ ARXITEKTURA PLANI

## 📋 LAYIHANING MAQSADI
UEBA (User and Entity Behavior Analytics) tizimi – foydalanuvchilarning ish vaqti xatti-harakatlarini kuzatib, normaldan chetga chiqishlarni (anomaliyalarni) avtomatik aniqlaydigan tizim.

---

## 🏗️ TIZIM ARXITEKTURASI

```
ASOSIY MONGODB (Read Only)
├── clients
├── activewindows
├── activities
├── rdps
└── 15+ boshqa collection
        │
        ▼
STAGE 0: COLLECTOR (Bir marta - qo'lda)
├── 1. clients dan active client'lar ro'yxati
├── 2. Har bir client uchun 17 collection dan 60 kunlik ma'lumot
├── 3. Shovqin filtri: event>=5
└── 4. Mahalliy MongoDB ga saqlash (raw_data)
        │
        ▼
MAHALLIY MONGODB (Read/Write)
├── raw_data
├── baseline
└── scores
        │
        ▼
STAGE 1: TRAINER (Qo'lda - bir marta)
├── 1. raw_data dan o'qish
├── 2. Har bir client uchun hafta kunlari bo'yicha guruhlash
├── 3. meanStart, stdStart, meanFinish, stdFinish, count hisoblash
├── 4. count < 5 bo'lsa null qo'yish
└── 5. Mahalliy MongoDB ga saqlash (baseline)

QAYTA O'QITISH: POST /api/retrain
        │
        ▼
TRIGGER (Har 5 soat - avtomatik)
├── 1. APScheduler da har 5 soat ishga tushadi
├── 2. Active client'larni va oxirgi 5 soatlik ma'lumotlarni oladi
└── 3. RabbitMQ queue ga yuboradi (ueba_jobs)
        │
        ▼
RABBITMQ (Navbat)
├── ueba_jobs (queue)
├── Worker 1 (parallel)
├── Worker 2 (parallel)
└── Worker 3 (parallel)
        │
        ▼
STAGE 2: PROCESSOR (Worker)
├── 1. RabbitMQ dan ishni olish
├── 2. Baseline dan client ni topish
├── 3. zStart va zFinish hisoblash
├── 4. Status aniqlash (normal/watch/anomaly/severe)
├── 5. Mahalliy MongoDB ga saqlash (scores)
└── 6. Queue dan ishni o'chirish (ack)
        │
        ▼
STAGE 3: DASHBOARD
├── 1. scores dan o'qish
├── 2. HTML + CSS + JS vizualizatsiya
├── 3. Filter: vaqt, status, client
└── 4. Grafiklar va jadvallar
```

---

## 📊 KOMPONENTLAR VA VAZIFALARI

### 1. COLLECTOR (Stage 0)
| Nomi | Collector |
|------|-----------|
| Vazifasi | Asosiy MongoDB dan 60 kunlik ma'lumotlarni yig'ish |
| Ishga tushirish | Bir marta (qo'lda) |
| Natija | raw_data collection |

**Jarayon:**
1. clients collection'dan active client'larning _id larini olish
2. Har bir client uchun 17 ta collection'ni aylanib chiqish
3. Har bir collection'dan clientId bo'yicha so'rov
4. Vaqt filtri: datetime >= now - 60 kun
5. Har bir kun uchun: start (eng erta), finish (eng kech), duration, event_count
6. Shovqin filtri: event_count >= 5 (12 soatdan oshganlar ham saqlanadi)
7. Mahalliy MongoDB raw_data ga saqlash

---

### 2. TRAINER (Stage 1)
| Nomi | Trainer |
|------|---------|
| Vazifasi | Har bir client uchun baseline yaratish |
| Ishga tushirish | Qo'lda (bir marta yoki retrain) |
| Natija | baseline collection |

**Jarayon:**
1. raw_data dan o'qish
2. Har bir client uchun kunlarni hafta kunlari bo'yicha guruhlash
3. Har bir hafta kuni uchun:
   - count – necha kun
   - meanStart – o'rtacha boshlash vaqti (daqiqa)
   - stdStart – boshlash vaqti standart og'ishi
   - meanFinish – o'rtacha tugatish vaqti (daqiqa)
   - stdFinish – tugatish vaqti standart og'ishi
   - meanDuration – o'rtacha davomiylik (daqiqa)
4. Agar count < 5 bo'lsa, barcha qiymatlar null
5. Mahalliy MongoDB baseline ga saqlash

**Retrain:** POST /api/retrain - eski baseline o'chiriladi va yangisi yaratiladi

---

### 3. TRIGGER
| Nomi | Trigger |
|------|---------|
| Vazifasi | Har 5 soatda yangi ma'lumotlarni tekshirish |
| Ishga tushirish | Avtomatik (BackgroundScheduler) |
| Natija | RabbitMQ queue |

**Jarayon:**
1. Har 5 soatda avtomatik ishga tushadi
2. clients dan active client'larni olish
3. Har bir client uchun 17 collection dan so'nggi 5 soatlik ma'lumotlarni olish
4. RabbitMQ ueba_jobs queue'siga yuborish

---

### 4. PROCESSOR (Stage 2)
| Nomi | Processor |
|------|-----------|
| Vazifasi | Yangi ma'lumotlarni baseline bilan solishtirish |
| Ishga tushirish | RabbitMQ worker orqali |
| Natija | scores collection |

**Jarayon:**
1. RabbitMQ dan ishni olish
2. Har bir client uchun baseline dan o'qish
3. Har bir kun uchun:
   - weekday bo'yicha baseline ni topish
   - Agar baseline mavjud bo'lsa:
     - zStart = (observed_start - meanStart) / stdStart
     - zFinish = (observed_finish - meanFinish) / stdFinish
   - Agar baseline mavjud bo'lmasa yoki std=0: zStart = null, zFinish = null
4. Mahalliy MongoDB scores ga saqlash
5. Queue dan ishni o'chirish (ack)

---

### 5. DASHBOARD (Stage 3)
| Nomi | Dashboard |
|------|-----------|
| Vazifasi | Natijalarni vizualizatsiya qilish |
| Ishga tushirish | Brauzer orqali |
| Manba | scores collection |

---

## 📈 Z-SCORE BELGILARI

**Start (kelish) uchun:**
- Erta kelish → zStart > 0 (MUSBAT)
- Kech kelish → zStart < 0 (MANFIY)

**Finish (ketish) uchun:**
- Erta ketish → zFinish < 0 (MANFIY)
- Kech ketish → zFinish > 0 (MUSBAT)

**Status va ranglar:**
| Z-score | Status | Rang |
|---------|--------|------|
| `|Z| >= 1.8` | severe | Qizil |
| `1.2 <= |Z| < 1.8` | anomaly | To'q sariq |
| `0.5 <= |Z| < 1.2` | watch | Sariq |
| `|Z| < 0.5` | normal | Yashil |
| `Z = null` | insufficient | Kulrang |

---

## 🗄️ MONGODB COLLECTION'LAR

**Asosiy MongoDB (17 ta):**
clients, activewindows, activities, rdps, screenshots, keyloggers, webvisitings, telegrams, whatsapps, emails, websearches, websniffs, usbmonitors, usbsniffs, filemonitors, clipboards, prints, incidents

**Mahalliy MongoDB:**
| Collection | Maqsad | Indeks |
|------------|--------|--------|
| raw_data | 60 kunlik xom ma'lumot | clientId, date |
| baseline | O'qitilgan modellar | clientId |
| scores | Baholash natijalari | clientId, evaluatedAt |

---

## 📨 RABBITMQ KONFIGURATSIYASI

| Parametr | Qiymat |
|----------|--------|
| Host | localhost |
| Port | 5672 |
| Queue name | ueba_jobs |
| Durable | True |
| Prefetch count | 1 |
| Auto-ack | False |
| Worker'lar | 2-5 ta |

---

## 🔌 API ENDPOINTLAR

| Endpoint | Method | Vazifasi |
|----------|--------|----------|
| /api/train | POST | Baseline yaratish |
| /api/retrain | POST | Baseline'ni qayta o'qitish |
| /api/trigger | POST | Qo'lda trigger ishga tushirish |
| /api/scores | GET | Barcha natijalarni olish |
| /api/scores/{client_id} | GET | Bir client natijalarini olish |
| /api/dashboard | GET | Dashboard HTML |

---

## ⚙️ KONFIGURATSIYA PARAMETRLARI

| Parametr | Default | Izoh |
|----------|---------|------|
| DAYS_WINDOW | 60 | O'qitish uchun kunlar soni |
| TRIGGER_INTERVAL | 5 soat | Trigger oralig'i |
| LOOKBACK_HOURS | 5 soat | Har bir tekshiruvda olinadigan vaqt |
| Z_THRESHOLD | 1.2 | Anomaliya chegarasi |
| SEVERE_THRESHOLD | 1.8 | Jiddiy anomaliya chegarasi |
| MIN_DOW_SAMPLES | 5 | Baseline uchun minimal kunlar |
| MIN_DAILY_EVENTS | 5 | Kunlik minimal eventlar |
| MAX_DAILY_HOURS | 12 | Kunlik maksimal soat |
| RABBITMQ_HOST | localhost | RabbitMQ manzili |
| RABBITMQ_PORT | 5672 | RabbitMQ porti |
| MONGO_URI | mongodb://localhost:27017 | Asosiy MongoDB |
| LOCAL_MONGO_URI | mongodb://localhost:27017 | Mahalliy MongoDB |
| LOCAL_DB_NAME | ueba_local | Mahalliy database nomi |

---

## 🚀 ISHGA TUSHIRISH TARTIBI

```bash
# 1. Mahalliy MongoDB ni ishga tushirish
mongod --dbpath /data/ueba

# 2. RabbitMQ ni ishga tushirish
rabbitmq-server

# 3. Collector ni ishga tushirish (bir marta)
python collector.py

# 4. Trainer ni ishga tushirish (bir marta)
python trainer.py

# 5. Trigger va Worker'larni ishga tushirish
python main.py

# Qayta o'qitish:
curl -X POST http://localhost:8000/api/retrain
```

---

## 📁 KOD STRUKTURASI

```
project/
├── config.py
├── models/
│   ├── client.py
│   ├── raw_data.py
│   ├── baseline.py
│   └── score.py
├── services/
│   ├── collector.py
│   ├── trainer.py
│   ├── processor.py
│   └── trigger.py
├── queue/
│   ├── rabbitmq.py
│   └── worker.py
├── api/
│   ├── routes.py
│   └── dashboard.py
├── dashboard/
│   ├── index.html
│   └── static/
│       ├── style.css
│       └── script.js
├── utils/
│   ├── helpers.py
│   └── logger.py
├── main.py
└── requirements.txt
```

---

## 🎯 ASOSIY TAMOYILLAR

1. Baseline faqat bir marta o'qitiladi – har safar asosiy MongoDB ga murojaat qilmaydi
2. Qayta o'qitish qo'lda – retrain API orqali
3. RabbitMQ navbat – yuklama tushmasligi uchun
4. Worker'lar – parallel ishlov berish
5. Mahalliy MongoDB – barcha natijalar saqlanadi

---

---

## 📝 XULOSA JADVALI

| Bosqich | Komponent | Ishga tushirish | Manba | Natija |
|---------|-----------|-----------------|-------|--------|
| 0 | Collector | Bir marta | Asosiy MongoDB | raw_data |
| 1 | Trainer | Qo'lda | raw_data | baseline |
| 2 | Trigger | Har 5 soat | Asosiy MongoDB | RabbitMQ |
| 2 | Processor | Worker | baseline + yangi data | scores |
| 3 | Dashboard | Brauzer | scores | HTML |
