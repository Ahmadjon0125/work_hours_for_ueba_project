# DLP backend jamoasiga: 2 ta indeks qo'shish so'rovi

**Kimdan:** UEBA (xodim xatti-harakati tahlili) pipeline jamoasi
**Baza:** `alpha-demo` (MongoDB 8.0.4) — ulanish manzili alohida uzatiladi
**Sana:** 2026-09-08

---

## 1. Kontekst: biz kimmiz va bazangizga nima qilamiz

UEBA pipeline — DLP agentlari yig'gan event'lar asosida har bir xodimning
"ishga kelish / ishdan ketish" vaqtini o'rganib, undan chetga chiqishni
(anomaliya) aniqlaydigan tizim.

Bazangizga munosabatimiz:

| | |
|---|---|
| Ulanish rejimi | **Faqat o'qish.** Kodimizda `alpha-demo` ga yozish jismonan mumkin emas — alohida, yozuvsiz MongoClient ishlatiladi. Barcha natijalar bizning alohida bazamizga (`ueba_local`) yoziladi. |
| Nechta collection | 16 ta event collection'i + `clients` |
| Query shakli | Har doim bitta xodim + vaqt oralig'i: `{ clientId: <ObjectId>, dateTime: { $gte: A, $lt: B } }` |
| Projection | Faqat 2 ta maydon: `{ _id: 0, clientId: 1, dateTime: 1 }`. **Hujjat mazmunini (matn, fayl nomi, skrinshot yo'li) umuman o'qimaymiz** — bizga faqat event'ning *sodir bo'lgan vaqti* kerak. |
| Qanchalik tez-tez | Har 5 soatda bir marta oshirmali (faqat yangi ma'lumot). To'liq 60 kunlik qayta o'qish — faqat model qayta o'qitilganda, kuniga ko'pi bilan bir marta. |

## 2. Hozirgi holat: shikoyat emas, profilaktika

Bazangizdagi indekslarni `explain` bilan tekshirdik. **Hozir hammasi joyida** —
16 ta collection'dan 16 tasi ham indeksdan foydalanyapti, birorta COLLSCAN yo'q.
Bitta to'liq o'tish server vaqtidan atigi **0.9 sekund** oladi.

Ya'ni bu so'rov hozirgi muammoni hal qilish uchun emas — ma'lumot hajmi
o'sganda paydo bo'ladigan ikkita muammoni **oldindan** yopish uchun.

## 3. So'rov: 2 ta indeks

### 3.1 `filemonitors` — `{ clientId: 1, dateTime: -1 }`

**Hozirgi yagona indeks:** `{ dateTime: -1, clientId: 1, computerId: 1 }`

Maydon tartibi bizning query uchun teskari: `dateTime` birinchi turgani uchun
Mongo avval **vaqt oralig'idagi hamma xodimning** kalitlarini oladi, keyin
ular orasidan kerakli `clientId` ni ajratadi. 60 kunlik oyna esa bu
collection'ning deyarli hammasini qamrab oladi (171 413 hujjatdan 170 344 tasi).

Hozir Mongo buni skip-scan bilan eplayapti va sekinlik bilinmaydi. Ammo bu
collection bazangizdagi eng kattasi va eng tez o'sadiganidir — millionlarga
chiqqanda har bir xodim uchun butun oyna bo'ylab yurish kerak bo'ladi.

`clientId` ni birinchi o'ringa qo'yish Mongo'ga to'g'ridan-to'g'ri kerakli
xodimning bo'lagiga sakrash imkonini beradi.

```js
db.filemonitors.createIndex(
  { clientId: 1, dateTime: -1 },
  { name: "clientId_1_dateTime_-1" }
)
```

**Narxi:** mavjud 3 maydonli indeks atigi 904 KB joy egallaydi, demak bu
2 maydonli indeks undan ham kichik — **1 MB dan kam**. 171 ming hujjatda
qurilishi bir necha sekund. MongoDB 8.0 da indeks qurilishi onlayn kechadi,
o'qish/yozishni bloklamaydi.

**Mavjud indeksni o'chirish shart emas** — u boshqa querylaringizga (sana
bo'yicha umumiy hisobotlar) kerak bo'lishi mumkin.

---

### 3.2 `rdps` — `{ clientId: 1, connectTime: -1 }`

Bu yerda alohida holat bor. `rdps` da hozir 2 ta indeks turibdi:

- `{ dateTime: -1 }`
- `{ clientId: 1, dateTime: -1 }`

Lekin `Rdp` sxemasida **`dateTime` degan maydon umuman yo'q**. Hujjatlarda
`connectTime`, `disconnectTime`, `createdAt`, `updatedAt` bor — `dateTime` yo'q.
Ya'ni bu ikkala indeks mavjud bo'lmagan maydonga ishora qiladi va faqat
`null` kalitlardan iborat — hech qanday queryni tezlashtirmaydi.

Biz `connectTime` va `disconnectTime` bo'yicha qidiramiz, ularda esa indeks yo'q.
Natijada Mongo `clientId` gacha indeksdan boradi, keyin o'sha xodimning
**butun RDP tarixini** diskdan o'qib, vaqtni xotirada filtrlaydi.

```js
db.rdps.createIndex(
  { clientId: 1, connectTime: -1 },
  { name: "clientId_1_connectTime_-1" }
)
```

**Narxi:** hozir collection'da 55 ta hujjat — indeks bir zumda quriladi,
hajmi ~36 KB.

> **Eslatma (bizning so'rovimizga kirmaydi):** yuqoridagi ikkita "o'lik"
> `dateTime` indeksi ham e'tiboringizga loyiq — ular bo'sh va har bir yangi RDP
> yozuvida bekorga yangilanadi. Lekin **biz ularni o'chirishni so'ramayapmiz** —
> bizning ishimizga ta'sir qilmaydi. Bu butunlay sizning qaroringiz va bu
> so'rovdan mustaqil ravishda ko'rib chiqilishi mumkin.

---

## 4. Bu sizning ishingizga qanday ta'sir qiladi

Bu bo'lim ataylab yozildi — indeks qo'shishdan oldin beriladigan odatiy
savollarga oldindan javob bo'lsin.

### Indeks qurilishi bazani bloklaydimi?

Yo'q. MongoDB 4.2 dan boshlab indeks qurilishi onlayn kechadi: o'qish ham,
yozish ham davom etaveradi. Sizda MongoDB **8.0.4** — bu rejim standart.

`alpha-demo` dagi 171 413 hujjatda qurilish bir necha sekund oladi.

> ⚠️ **Muhim ogohlantirish:** bu yerdagi barcha raqamlar **`alpha-demo`**
> bazasidan olingan (799 MB, 15 ta client, `filemonitors` da 171 ming hujjat).
> Agar siz bu indeksni kattaroq muhitga (masalan yuzlab clientli, o'n
> millionlab hujjatli baza) qo'llasangiz, qurilish vaqti va RAM/disk yuki
> shunga mutanosib ortadi — sekundlar emas, daqiqalar bo'lishi mumkin.
> Bunday holatda gavjum bo'lmagan vaqtni tanlashni tavsiya qilamiz.

### Yozish tezligiga ta'sir qiladimi?

Har bir yangi hujjat endi bitta qo'shimcha indeksni yangilaydi. Bu qancha
turishini bilish uchun `filemonitors` ga yozish tezligini o'lchadik:

| Davr | Yozuvlar soni | O'rtacha |
|---|---|---|
| 2026-08 (eng gavjum oy) | 120 826 | kuniga ~3 900, **daqiqasiga ~3 ta** |
| 2026-09 (oxirgi 8 kun) | 2 097 | kuniga ~260 |

Daqiqasiga ~3 ta yozuv — MongoDB uchun ahamiyatsiz yuk (u sekundiga minglab
yozuvni ko'taradi). Bitta qo'shimcha B-tree yangilanishi mikrosekundlar oladi.

### Disk joyi

`filemonitors` dagi mavjud 3 maydonli indeks — 904 KB. Yangi indeks 2 maydonli,
demak undan ham kichik: **1 MB dan kam**. `rdps` da ~36 KB.

### Yagona haqiqiy e'tibor talab qiladigan nuqta: query plan kesh

Yangi indeks qo'shilganda MongoDB o'sha collection uchun **query plan keshini
tozalaydi**. Ya'ni sizning mavjud querylaringiz keyingi ishga tushganda
qaytadan rejalashtiriladi.

Deyarli har doim bu sezilmaydi (rejalashtiruvchi o'sha eski indeksni qayta
tanlaydi). Ammo nazariy jihatdan biror queryingiz uchun yangi indeks noto'g'ri
tanlanib qolishi mumkin. Shuning uchun:

- Mavjud indekslarni **o'chirishni so'ramayapmiz** — eski rejalar mavjud bo'lib
  qolaveradi.
- Indeks qo'shilgandan keyin bir necha soat davomida `filemonitors` bilan
  ishlaydigan endpointlaringizning javob vaqtiga qarab turishni tavsiya qilamiz.

### Orqaga qaytarish

Bir buyruq, bir zumda, ma'lumotga hech qanday ta'sirsiz:

```js
db.filemonitors.dropIndex("clientId_1_dateTime_-1")
db.rdps.dropIndex("clientId_1_connectTime_-1")
```

Indeks — hosila ma'lumot. Uni o'chirish hech qanday hujjatni yo'qotmaydi.

### Shoshilinchmi?

**Yo'q.** Hozir hech qanday muammo yo'q (§2). Bu so'rov kelajakdagi o'sishga
tayyorgarlik. Sizga qulay bo'lgan istalgan vaqtda, odatiy jarayoningiz
doirasida bajarilishi mumkin — biz tomonda hech narsa kutib turmaydi.

## 5. Muhim: Mongoose sxemasiga ham qo'shish kerak

Bazadagi collection'lar Mongoose model'lari orqali boshqarilganini ko'rdik
(`versionKey`, `timestamps`, virtual `id`, `post('remove')` hook'lari).

Agar indeks faqat `mongosh` dan qo'lda qo'shilsa, u model faylida qolmaydi:
yangi stend ko'tarilganda yoki boshqa muhitga deploy qilinganda indeks
bo'lmaydi. Shuning uchun model fayllariga ham qo'shishni so'raymiz:

```js
// models/FileMonitor.js
fileMonitorSchema.index({ clientId: 1, dateTime: -1 });

// models/Rdp.js
rdpSchema.index({ clientId: 1, connectTime: -1 });
```

## 6. Qanday tekshirish mumkin

Indeks qo'shilgandan keyin (`<ID>` — istalgan mavjud client `_id` si):

```js
db.filemonitors.find(
  { clientId: ObjectId("<ID>"), dateTime: { $gte: ISODate("2026-07-10"), $lt: ISODate("2026-09-08") } },
  { _id: 0, clientId: 1, dateTime: 1 }
).explain("executionStats")
```

Kutilayotgan natija:
- `winningPlan.inputStage.indexName` = `"clientId_1_dateTime_-1"`
- `executionStats.totalDocsExamined` = **0** (indeksning o'zi yetarli, hujjat diskdan olinmaydi)
- `totalKeysExamined` ≈ `nReturned` (ortiqcha kalit o'qilmaydi)

## 7. Xulosa

| Collection | Qo'shiladigan indeks | Hajm | Shoshilinchmi |
|---|---|---|---|
| `filemonitors` | `{ clientId: 1, dateTime: -1 }` | < 1 MB | Yo'q, lekin tavsiya etiladi |
| `rdps` | `{ clientId: 1, connectTime: -1 }` | ~36 KB | Yo'q |

Ikkalasi ham qo'shimcha, mavjud hech narsani buzmaydi va istalgan payt
`dropIndex` bilan orqaga qaytariladi.

Savollar bo'lsa — bemalol murojaat qiling.
