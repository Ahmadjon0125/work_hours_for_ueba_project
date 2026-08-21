# DataGaze DLP — AI-Optimized Database Context & Best Practices

> **Audience:** LLM agents that read, query, and reason over the DataGaze DLP MongoDB cluster.
> **Engine:** MongoDB + Mongoose 8 (`mongoose-paginate-v2`). All `_id` fields are `ObjectId` unless noted.
> **Authoritative source:** `packages/common-models/src/*` — this document is derived directly from those schemas. If a schema and this doc disagree, the schema wins.

---

## 1. System Architecture & High-Level Overview

### 1.1 Domain & Purpose
This database backs a **Data Loss Prevention (DLP)** platform. Endpoint agents installed on employee workstations stream telemetry (web activity, USB transfers, file operations, clipboard, keystrokes, screenshots, messenger chats, email, print jobs) into MongoDB. A content-analysis pipeline evaluates this telemetry against DLP **policies** and raises **Incidents** on policy violations. The data model is therefore **activity-log-centric**: most collections are high-volume, append-heavy, time-series-like event logs keyed by `dateTime`.

### 1.2 Core Entity Model
Two **identity anchors** are referenced by nearly every event collection:

- **`Client`** (a.k.a. *Employee*) — the monitored person/agent identity (collection `clients`).
- **`Computer`** — the workstation the agent runs on (collection `computers`).

Every event document carries `clientId → clients._id` and `computerId → computers._id` as **referenced (foreign-key) relationships**. There is *no* embedding of identity into event docs; resolution happens via `$lookup` (see each model's `findByFields` static).

### 1.3 Collection Catalog

| Model | Collection | Domain group | Role |
|---|---|---|---|
| `Client` | `clients` | Identity | Employee/agent profile, AD attributes, online state |
| `Computer` | `computers` | Identity | Workstation hardware/agent metadata |
| `WebVisiting` | `webvisitings` | Web | Page-visit log (host, URL, title, duration) |
| `WebSearch` | `websearches` | Web | Search-engine query log |
| `WebSniff` | `websniffs` | Web | Intercepted HTTP(S) requests + uploaded/downloaded files |
| `UsbMonitor` | `usbmonitors` | Hardware | USB device connect/disconnect (+ block state) |
| `UsbSniff` | `usbsniffs` | Hardware | Files written to / copied from USB |
| `Minifilter` | `minifilter` ⚠️ | Hardware | Driver-level filesystem ops (create/move/delete) |
| `FileMonitor` | `filemonitors` | Hardware | File-change monitoring (path array, op type) |
| `FileWatcher` | `filewatchers` | Hardware | File-watch events with result/document text |
| `Activity` | `activities` | User activity | Daily productivity/active-time aggregates |
| `ActiveWindow` | `activewindows` | User activity | Foreground window/process time slices |
| `Clipboard` | `clipboards` | User activity | Clipboard text/file captures |
| `Print` | `prints` | User activity | Print-job metadata + spooled file |
| `Keylogger` | `keyloggers` | User activity | **Keystroke capture** (highly sensitive) |
| `Screenshot` | `screenshots` | User activity | Periodic screen captures |
| `Program` | `programs` | User activity | Installed program inventory |
| `Rdp` | `rdps` | User activity | RDP session records |
| `Telegram` | `telegrams` | Comms | Telegram messages + file exchange |
| `Whatsapp` | `whatsapps` | Comms | WhatsApp messages + file exchange |
| `Email` | `emails` | Comms | Intercepted email |
| `FTP` | `ftps` | Comms | FTP file-transfer sessions |
| `Incident` | `incidents` | Events | DLP policy-violation records |
| `Log` | `logs` | Events | Agent-state system logs |

> ⚠️ **`Minifilter`** overrides the default pluralization — its collection is literally **`minifilter`** (singular), set via `{ collection: 'minifilter' }`. Do not query `minifilters`.

### 1.4 Relationship Map (Referenced vs. Embedded)

**Referenced (`ObjectId`) edges:**
```
clients._id  ◄── clientId / employee ── (almost every event collection)
computers._id ◄── computerId / computer ── (almost every event collection)
clients.group        ──► groups._id        (Group)
clients.rule         ──► polytics._id       (Polytic = DLP policy)
clients.lastComputer ──► computers._id
computers.employees[] ──► clients._id       (array of references)
incidents.employee        ──► clients._id
incidents.computer        ──► computers._id
incidents.rule            ──► polytics._id
incidents.telegramMessageId ──► telegrams._id
incidents.comments[].author ──► users._id   (admin user)
telegrams.incidentId / whatsapps.incidentId ──► incidents._id
```

**Embedded sub-documents (no separate collection):**
- `files[]` — `fileEntrySchema` embedded in `WebSniff`, `UsbSniff`, `Minifilter`, `Clipboard`, `Print`, `Email`, `Telegram`, `Whatsapp`. Each entry may itself embed `archiveFiles[]`.
- `extractedText` — embedded OCR result object on all file-bearing comms/transfer collections.
- `transcript` — `transcriptSchema` embedded in `Telegram`, `Whatsapp` (speech-to-text result).
- `owner/receiver/sender/author/source/group` — embedded contact objects in `Telegram`/`Whatsapp` (`_id: false`).
- `incidents.comments[]`, `incidents.archiveFile`, `computers.missingFiles[]` — embedded.

> **Cross-collection note:** `FTP` is **not** linked to `Client`/`Computer` (the `clientId` ref is commented out). It only stores `clientIp`. Treat FTP records as orphaned w.r.t. identity.

---

## 2. Granular Collection Schemas (AI-Friendly Format)

> **Legend:** `R` = Required by business logic, `O` = Optional. Mongoose uses the misspelled `require` (not `required`) almost everywhere, so requiredness is **not enforced at the DB level** — treat `R` as *intended* required; defensively expect missing fields. `[ref]` = ObjectId reference. Default values shown where defined.

### 2.0 Shared Embedded Schemas

**`fileEntrySchema`** (embedded in `files[]`; `_id` disabled):

| Field | Type | Opt | Description |
|---|---|---|---|
| `name` | String | R | Original filename |
| `size` | Number | O | Bytes |
| `destination` | String | R | CAS storage path/URL of the stored copy |
| `hash` | String | O | SHA-256 content hash (CAS dedup key) |
| `removedBySaveFileOnlyOnIncident` | Boolean | O (def `false`) | File body purged because it wasn't an incident |
| `isArchive` | Boolean | O (def `false`) | Entry is an archive container |
| `isCorrupt` | Boolean | O (def `false`) | File could not be parsed |
| `isLoggedOnly` | Boolean | O (def `false`) | Metadata logged, body not stored |
| `archiveFiles[]` | Array<archiveFileSchema> | O | Extracted archive members (`name`, `size`, `destination`, `isCorrupt`) |
| `isDeleted` | Boolean | O (def `false`) | **Only present in `Clipboard.files`** (via `makeFileEntrySchema({isDeleted:true})`) |

**`extractedText`** (embedded object): `from` (String enum `['OCR']`), `content` (String — extracted text), `wasCropped` (Boolean def `false`).

**`transcriptSchema`** (embedded; `_id` disabled): `text`, `language`, `durationS` (Number), `chunkCount` (Number), `model` (String), `processingMs` (Number), `status` (enum `['pending','success','failed']` def `'pending'`), `error`, `transcribedAt` (Date).

---

### 2.1 `Client` (`clients`) — Identity

| Field | Type | Opt | Notes |
|---|---|---|---|
| `sid` | String | R, **unique** | Windows SID; primary natural identifier |
| `hostname` | String | R | indexed |
| `firstName`,`lastName`,`middleName` | String | O | AD name parts |
| `fullName` | String | O (auto) | Auto-built in `pre('save')` from name parts |
| `email` | String | O | |
| `position`,`department` | String | O | Org attributes |
| `phoneNumber` | String | O | |
| `image` | String | O | Avatar path |
| `tgAccount` | String | O | Linked Telegram account |
| `group` | ObjectId[ref `Group`] | O | indexed |
| `rule` | ObjectId[ref `Polytic`] | O | DLP policy assigned; indexed |
| `modules` | String | O | Agent module config (serialized) |
| `token` | String | O | 🔒 **Agent auth token — secret** |
| `isOnline` | Boolean | O (def `false`) | |
| `lastSeen` | Object | O | Free-form heartbeat object |
| `disabled` | Boolean | O (def `false`) | |
| `isAgentInstalled` | Boolean | O (def `true`) | |
| `lastComputer` | ObjectId[ref `Computer`] | O | indexed |
| `getNameFromAD` | Boolean | O (def `true`) | |
| `windowStatus` | String enum | O | `['blocked','unblocked']` (`WINDOW_STATUSES`) |

**Indexes:** `{group}`, `{rule}`, `{lastComputer}`, `{hostname}`, `{firstName, lastName}`, plus unique `{sid}`. **Virtual:** `id` (= hex `_id`).
**LLM use:** Filter employees by `group`/`rule`/`hostname` via the dedicated single-field indexes. Name search → use compound `{firstName,lastName}` (prefix order matters: filter `firstName` before `lastName`).

### 2.2 `Computer` (`computers`) — Identity

| Field | Type | Opt | Notes |
|---|---|---|---|
| `pcId` | String | R, **unique** | Hardware identifier (unique index) |
| `pcname` | String | R | indexed (compound w/ datetime) |
| `macAddress`,`ipAddress` | String | R | |
| `globalIp` | String | O (def `null`) | Public IP |
| `isOnline` | Boolean | O (def `false`) | |
| `isMonitored` | Boolean | O (def `true`) | |
| `isIgnoreMonitored` | Boolean | O (def `false`) | |
| `isAgentInstalled` | Boolean | O (def `false`) | |
| `isDeleted` | Boolean | O (def `false`) | **Soft-delete flag — always filter `isDeleted:false` for "active" sets** |
| `isNotLicense` | Boolean | O (def `false`) | |
| `lastSeen` | Object | O | |
| `os` | String | O (def `false`) ⚠️ | Boolean default on a String field — may be `false` |
| `agentVersion` | String | R | |
| `employees[]` | Array<ObjectId[ref `Client`]> | O | Users seen on this PC |
| `datetime`,`updatedAt` | Date | O | |
| `missingFiles[]` | Array<{name,description}> | O (def `null`) | Integrity check failures |

**Indexes:** unique `{pcId}`, compound `{pcname:1, datetime:-1}`. **Hook:** `post('remove')` cascades `deleteMany({computerId})` across ~19 event collections.

### 2.3 Web Activity

**`WebVisiting` (`webvisitings`):** `host`(R), `page`(R, URL), `protocol`(R), `title`(R), `dateTime`(R, Date), `duration`(Number, O), `isOnBlacklist`(Bool def`false`), `browser`(O), `clientId`(R ref), `computerId`(R ref).
Indexes: `{dateTime:-1, clientId:1}`, **text** `{host,page,title}`, single `{host}`,`{page}`,`{title}`.

**`WebSearch` (`websearches`):** `host`(R), `protocol`(R), `text`(R — query string), `dateTime`(R), `browser`(O), `clientId`/`computerId`(R refs).
Indexes: `{dateTime:-1, clientId:1}`, **text** `{host,text}`.

**`WebSniff` (`websniffs`):** `host`(R), `protocol`(R), `dateTime`(R), `message`(R — request body/summary), `browser`(O), `guid`(O — correlation id), `files[]` (fileEntrySchema), `isIncident`(def`false`), `isBlockedByExtension`(def`false`), `isPrompt`(def`false`), `extractedText`(OCR), `clientId`/`computerId`(R refs).
Indexes: `{dateTime:-1, clientId:1, guid:1}`, `{guid}`, **text** `{host,message,files.name}`, singles `{host}`,`{message}`,`{files.name}`.

### 2.4 Hardware / System Activity

**`UsbMonitor` (`usbmonitors`):** `title`,`label`,`model`,`capacity`,`imei`,`deviceId` (all String R), `dateTime`(R), `isBlocked`(Bool R), `clientId`/`computerId`(R). Indexes: `{dateTime:-1, clientId:1}`, **text** `{imei,model,title}`, singles `{imei}`,`{model}`,`{title}`.

**`UsbSniff` (`usbsniffs`):** `dateTime`(R), `guid`(O), `fileName`(R), `fileDestination`(R), `targetPath`(R), `deviceImei`(R), `isIncident`(def`false`), `isBlockedByExtension`(def`false`), `files[]`, `extractedText`, `clientId`/`computerId`(R). Indexes: `{dateTime:-1, clientId:1, guid:1}`, `{guid}`, **text** `{fileName,deviceImei}`, singles `{fileName}`,`{deviceImei}`.

**`Minifilter` (`minifilter`):** `dateTime`(R), `guid`(O), `channel`(O), `fileName`(R), `fileDestination`(R), `sourcePath`(R), `destinationPath`(R), `processName`(O), `deviceInfo`(O), `isIncident`/`isBlockedByExtension`(def`false`), `files[]`, `extractedText`, `clientId`/`computerId`(R). Indexes: `{dateTime:-1, clientId:1, guid:1}`, `{guid}`, **text** `{fileName,sourcePath}`, singles `{fileName}`,`{sourcePath}`.

**`FileMonitor` (`filemonitors`):** `dateTime`(R), `path`(Array R), `operationType`(String R), `isDirectory`(Bool R), `clientId`/`computerId`(R). Index: `{dateTime:-1, clientId:1, computerId:1}`. *No text index.*

**`FileWatcher` (`filewatchers`):** `dateTime`(R), `fileName`(R), `filePath`(R), `fileSize`(Number O), `fileDestination`(R), `document`(String R), `result`(String R), `employee`(ObjectId ref `Client` R — **note: field is `employee`, not `clientId`**), `computerId`(R). Index: `{dateTime:-1, employee:1}`.

### 2.5 User Activity Logs

**`Activity` (`activities`):** `allActiveTime`,`efficiencyProcTime`,`allWebTime`,`efficiencyWebTime` (Number O — seconds), `dateTime`(Date), `dateTimeStr`(String — day bucket), `employee`(ref `Client` R). Index: `{dateTime:-1, dateTimeStr:1, employee:1}`. *No `computerId`. Uses `employee` field name.*

**`ActiveWindow` (`activewindows`):** `datetime`(R — note lowercase `datetime`), `title`(R), `process`(R), `icon`(O), `time`(Number R — seconds focused), `isOnBlacklist`(def`false`), `clientId`/`computerId`(R). Indexes: `{datetime:-1, clientId:1, computerId:1}`, `{clientId:1, datetime:-1}`, **text** `{title,process}`, singles `{title}`,`{process}`.

**`Clipboard` (`clipboards`):** `type`(R — e.g. `TEXT`/`FILE`), `content`(O — clipboard text 🔒), `fileName`(O), `dateTime`(R), `source`(R — app/window), `dataUrl`(O), `guid`(O), `isIncident`(def`false`), `files[]` (with `isDeleted`), `extractedText`, `clientId`/`computerId`(R). Indexes: `{dateTime:-1, clientId:1, guid:1}`, `{guid}`, **text** `{content,source}`, singles `{content}`,`{source}`. `toClient()` truncates `content` to 20 chars for `TEXT`.

**`Print` (`prints`):** `printerName`(R), `fileName`(R), `fileDestination`(R), `pagesCount`(Number R), `copies`(Number R), `guid`(O), `dateTime`(Date, default = now UTC), `isIncident`(def`false`), `files[]`, `clientId`/`computerId`(R). Indexes: `{dateTime:-1, clientId:1}`, `{guid}`, **text** `{printerName,fileName}`, singles.

**`Keylogger` (`keyloggers`):** `activeWindowName`(R), `process`(R), `icon`(O), `text`(R — **raw keystrokes** 🔒🔒), `guid`(O), `dateTime`(R), `isIncident`(def`false`), `clientId`/`computerId`(R). Indexes: `{clientId:1, dateTime:-1}`, `{guid}`, **text** `{process,activeWindowName,text}`, singles. `toClient()` truncates `text` to 50 chars.

**`Screenshot` (`screenshots`):** `activeWindowName`(R), `imageUrl`(R — stored image path 🔒), `imageSize`(Number O), `dateTime`(R), `process`(R def `'unknown'`), `clientId`/`computerId`(R). Index: `{dateTime:-1, clientId:1, process:1}`.

**`Program` (`programs`):** `name`(R), `version`,`author`,`size`,`installLocation`,`uninstallPath`,`status`,`installingDate` (String O), `isupdate`(Bool O), `clientId`/`computerId`(R), `dateTime`(Date default now). Indexes: **unique** `{name:1, clientId:1}`, `{dateTime:-1, clientId:1}`, `{computerId}`.

**`Rdp` (`rdps`):** `sessionId`,`ipAddress`,`macAddress`,`pcName`(String O), `connectTime`/`disconnectTime`(Date O), `clientId`/`computerId`(R), `timestamps:true` (adds `createdAt`/`updatedAt`). Indexes: `{clientId:1, dateTime:-1}`, `{dateTime:-1}` ⚠️ — no `dateTime` field exists, so these indexes reference a missing field; **sort by `connectTime`/`createdAt` instead**.

### 2.6 Communications

**`Telegram` (`telegrams`):** `dateTime`(R), `direction`(R — in/out), embedded contacts `owner`/`receiver`/`sender`/`author`/`source` (`{id,username,name,phone}`) and `group` (`{id,username,name}`), `messageId`(R), `chatType`(R), `message`(R 🔒), `guid`(O), `isForwarding`/`isIncident`/`isBlockedByExtension`(def`false`), `incidentId`(ref), `clientId`/`computerId`(R), `file`(single `{name,destination}`), `files[]`, `extractedText`, `transcript`. `versionKey:false`. Indexes: compound `{clientId,chatType,owner.id,receiver.id,sender.id,group.id,messageId}`, **text** `{message,file.name}`, singles `{message}`,`{guid}`,`{file.name}`,`{dateTime:-1}`.

**`Whatsapp` (`whatsapps`):** Same shape as Telegram minus `author`/`source`/`isForwarding`; contacts omit `username`. Indexes: compound `{clientId,chatType,owner.id,receiver.id,sender.id,group.id}`, **text** `{message,file.name}`, singles `{message}`,`{guid}`,`{file.name}`.

**`Email` (`emails`):** `host`(R), `protocol`(R), `dateTime`(R), `from`(R 🔒), `to`(R 🔒), `subject`(R 🔒), `message`(R 🔒), `browser`(O), `guid`(O), `isIncident`/`isBlockedByExtension`(def`false`), `files[]`, `extractedText`, `clientId`/`computerId`(R). Indexes: `{clientId:1, dateTime:-1, guid:1}`, `{guid}`, **text** `{host,from,to,message,files.name}`, singles, `{dateTime:-1}`.

**`FTP` (`ftps`):** `ftpServer`(R), `dateTime`(Date default now), `fileName`(R), `dataContent`(R 🔒), `fileDestination`(R), `clientIp`(R), `status`(R). **No `clientId`/`computerId`.** Index: `{dateTime:-1}`.

### 2.7 Events

**`Incident` (`incidents`)** — central DLP violation record:

| Field | Type | Opt | Notes |
|---|---|---|---|
| `employee` | ObjectId[ref Client] | R | |
| `computer` | ObjectId[ref Computer] | R | |
| `rule` | ObjectId[ref Polytic] | R | Violated policy |
| `telegramMessageId` | ObjectId[ref Telegram] | O | |
| `channel` | String | R | One of `channelTypes` (see §2.8) |
| `documentType` | String | R | |
| `source`,`destination` | String | O | Data origin/target |
| `guid` | String | O, indexed | Correlation id |
| `fileName`,`fileUrl`,`filePathInArchive` | String | O | |
| `fileHash`,`contentHash` | String | O | SHA-256; `contentHash` indexed (sparse) for dedup |
| `fileSize` | Number | O | |
| `content` | String | O 🔒 | Matched content snapshot |
| `isShortenedContent` | Boolean | def`false` | |
| `time` | Date | R | Event time |
| `detectedAt` | Date | O | Analysis time |
| `matchingKeys` | Array | R | Matched policy keywords (exposed as `matchingWords`) |
| `severity` | Number | R | `1`=LOW, `2`=MEDIUM, `3`=HIGH |
| `action` | String | R | `'warn'` or `'block'` |
| `isViewed` | Boolean | def`false` | stripped in `toClient()` |
| `screenshotPath` | String | O | |
| `rate` | Number | def`0` | |
| `rateSource` | String enum | def`null` | `['user','ai']` |
| `contentFromOcr` | Boolean | def`false` | |
| `fileIsCorrupt` | Boolean | def`false` | |
| `isDestinationUnblockable` | Boolean | def`false` | |
| `details` | Object | def`{}` | Free-form |
| `comments[]` | Array | O | `{author→users._id, text(max 2000), createdAt}` |
| `archiveFile` | Object | O | `{destination,name,size}` |

Indexes: `{time:-1, employee:1, computer:1}`, `{detectedAt:-1, employee:1}`, sparse `{contentHash:1, time:-1}`, `{guid}`. **Note field naming:** Incident uses `employee`/`computer` (not `clientId`/`computerId`).

**`Log` (`logs`):** `employee`(ref Client R), `channelType`(String R), `content`(String R), `dataUrl`(O), `time`(Date default now). No extra indexes beyond `_id`. Virtual `id`.

### 2.8 Reference Enums
- **`channelTypes`:** `Activity, Clipboard, Print, Keylogger, Email, Search, WebVisiting, HTTP/S, Telegram, Whatsapp, USB, USBMONITOR, SMB, FTP, CDROM`.
- **`actionTypes`:** `warn`, `block`.
- **`severity`:** `LOW=1`, `MEDIUM=2`, `HIGH=3`.
- **`WINDOW_STATUSES`:** `blocked`, `unblocked`.
- **`textExtractMethod`:** `OCR`. `MAX_CONTENT_SIZE_BYTES = 12 MB`.
- **`transcript.status`:** `pending`, `success`, `failed`.

---

## 3. Sample Documents (Edge-Case Context)

**`clients`** (free-form `lastSeen` Object, secret `token`, auto `fullName`):
```json
{
  "_id": "6630a1f2c4a9b1e2d3f40011",
  "sid": "S-1-5-21-1004336348-1177238915-682003330-1013",
  "hostname": "FIN-WS-07", "firstName": "Aziz", "lastName": "Karimov",
  "middleName": "", "fullName": "Aziz Karimov", "email": "a.karimov@corp.uz",
  "position": "Accountant", "department": "Finance",
  "group": "6630a000c4a9b1e2d3f40001", "rule": "6630a100c4a9b1e2d3f40002",
  "token": "<REDACTED-AGENT-TOKEN>", "modules": "{...}",
  "isOnline": true, "lastSeen": { "ts": "2026-06-11T08:12:00Z", "ip": "10.2.4.7" },
  "disabled": false, "isAgentInstalled": true,
  "lastComputer": "6630a1f2c4a9b1e2d3f40090", "windowStatus": "unblocked"
}
```

**`computers`** (soft-deleted, `os:false` edge, empty `employees`, `missingFiles:null`):
```json
{
  "_id": "6630a1f2c4a9b1e2d3f40090",
  "pcId": "DESKTOP-9F3KQ2-MB#A77", "pcname": "FIN-WS-07",
  "macAddress": "00:1B:44:11:3A:B7", "ipAddress": "10.2.4.7", "globalIp": null,
  "isOnline": false, "isMonitored": true, "isDeleted": false,
  "os": false, "agentVersion": "3.4.1", "employees": [],
  "lastSeen": { "ts": "2026-06-11T08:10:00Z" }, "missingFiles": null
}
```

**`websniffs`** (file-bearing event with OCR + archive; `files` may be `[]`):
```json
{
  "_id": "6630b2a1c4a9b1e2d3f50001",
  "host": "files.example.com", "protocol": "https",
  "dateTime": "2026-06-11T09:30:12.000Z", "message": "POST /upload",
  "browser": "chrome", "guid": "a1b2-c3d4", "isIncident": true,
  "isBlockedByExtension": false, "isPrompt": false,
  "clientId": "6630a1f2c4a9b1e2d3f40011", "computerId": "6630a1f2c4a9b1e2d3f40090",
  "files": [{
    "name": "salary_2026.zip", "size": 482311,
    "destination": "/cas/ab/cd/abcdef...",
    "hash": "abcdef0123456789...", "isArchive": true, "isCorrupt": false,
    "archiveFiles": [
      { "name": "payroll.xlsx", "size": 22014, "destination": "/cas/...", "isCorrupt": false }
    ]
  }],
  "extractedText": { "from": "OCR", "content": "Net pay 12,400,000", "wasCropped": false }
}
```

**`telegrams`** (embedded contacts; `transcript` present only after STT, otherwise `undefined`):
```json
{
  "_id": "6630c000c4a9b1e2d3f60001",
  "dateTime": "2026-06-11T10:05:00.000Z", "direction": "outgoing",
  "owner":   { "id": "5512", "username": "aziz_k", "name": "Aziz", "phone": "+99890..." },
  "receiver":{ "id": "9001", "username": "ext_user", "name": "Ext", "phone": "+99891..." },
  "sender":  { "id": "5512", "username": "aziz_k", "name": "Aziz", "phone": "+99890..." },
  "group":   {},
  "messageId": "778", "chatType": "private", "message": "sending the report",
  "guid": "tg-778", "isForwarding": false, "isIncident": true,
  "incidentId": "6630d000c4a9b1e2d3f70001",
  "clientId": "6630a1f2c4a9b1e2d3f40011", "computerId": "6630a1f2c4a9b1e2d3f40090",
  "file": { "name": "report.pdf", "destination": "/cas/..." },
  "files": [{ "name": "report.pdf", "size": 91002, "destination": "/cas/..." }],
  "transcript": null
}
```
> **Edge cases:** `group` may be `{}` (private chats). `transcript` is `default: undefined` — absent on text/file messages; present only for voice/audio after STT (`status` may be `'pending'`/`'failed'`). The legacy single `file` object coexists with the newer `files[]` array — both can be set.

**`incidents`** (free-form `details`, `comments[]` may be empty, `rateSource` may be `null`):
```json
{
  "_id": "6630d000c4a9b1e2d3f70001",
  "employee": "6630a1f2c4a9b1e2d3f40011", "computer": "6630a1f2c4a9b1e2d3f40090",
  "rule": "6630a100c4a9b1e2d3f40002", "channel": "Telegram", "documentType": "pdf",
  "source": "telegram", "destination": "+99891...", "guid": "tg-778",
  "fileName": "report.pdf", "contentHash": "9f8e7d...", "fileSize": 91002,
  "content": "<REDACTED matched text>", "isShortenedContent": true,
  "time": "2026-06-11T10:05:00.000Z", "detectedAt": "2026-06-11T10:05:03.120Z",
  "matchingKeys": ["salary", "confidential"], "severity": 3, "action": "block",
  "isViewed": false, "rate": 0, "rateSource": null, "contentFromOcr": false,
  "details": {}, "comments": [],
  "archiveFile": { "destination": "/cas/...", "name": "report.pdf", "size": 91002 }
}
```

---

## 4. Query Rules & Guardrails (LLM Constraints)

### 4.1 Identity field naming — verify before filtering
Field names for the identity FKs are **not uniform**. Pick the right key per collection:
- Most event collections: `clientId` + `computerId`.
- `FileWatcher`, `Activity`: `employee` (no `clientId`); `Activity` has **no** `computerId`.
- `Incident`: `employee` + `computer`.
- `FTP`: **neither** — only `clientIp`.

### 4.2 Always anchor on the time + identity compound index
Most collections have a leading `{dateTime:-1, clientId:1, ...}` (or `{datetime:...}` / `{time:...}`) compound index. For employee timelines, always include both a `dateTime` range **and** `clientId`/`employee` in the match so the planner uses that index. Mind the per-collection date field name: `dateTime` (most), `datetime` (`ActiveWindow`), `time` (`Incident`,`Log`), `connectTime`/`createdAt` (`Rdp`), `dateTimeStr` (`Activity` day bucket).

### 4.3 Use the built-in `findByFields` static instead of hand-rolling joins
`WebVisiting/WebSearch/WebSniff/UsbMonitor/UsbSniff/Minifilter/ActiveWindow/Clipboard/Print/Keylogger/Email/Telegram/Whatsapp` expose `Model.findByFields({ search, dateTime: {$gte,$lte}, ...filters })`. It builds the `$match`, `$or` text search, file-array `$filter`, and projected `$lookup` to `clients`/`computers` for you. Prefer it over ad-hoc `$lookup` so projections (only `hostname/firstName/lastName`, `pcname`) and `preserveNullAndEmptyArrays` semantics stay consistent.
> ⚠️ When calling `findByFields` **without** `search`, the internal `$regexMatch` on file names receives `regex: undefined` and will error. Only use the `search` path when a search term is present, or query directly.

### 4.4 Text search vs. regex
- **Prefer `$text`** where a text index exists (`{host,page,title}`, `{message,...}`, `{title,process}`, etc.). One `$text` per query only.
- **Avoid unanchored `$regex`** (`/foo/i`) on large collections — it cannot use the b-tree and forces a COLLSCAN. The `findByFields` `$or` regex path is acceptable only because it runs *after* an indexed `$match` on `dateTime`+`clientId`.

### 4.5 Pagination & projection (mandatory)
- **Always paginate.** Every high-volume model has `mongoose-paginate-v2` (custom label `total` for `totalDocs`). Use `Model.paginate(filter, { page, limit, sort })`; never return unbounded `find()`. Cap `limit` (e.g. ≤ 100).
- **Always project.** Fetch only requested fields. Never `SELECT *` on collections holding `content`, `text`, `message`, `dataContent`, `extractedText.content`, `imageUrl`, `dataUrl`, or `token` unless explicitly required.
- **Always sort by an indexed date field descending** to leverage the leading index and keep pagination stable.

### 4.6 Aggregation performance
- Keep `$match` **first** and ensure it hits an index (date + identity).
- `$lookup` only into `clients`/`computers`, and **only with a projection sub-pipeline** (as `findByFields` does) — never pull whole identity docs.
- Avoid `$unwind` on `files[]`/`archiveFiles[]` across unbounded result sets; filter the array with `$filter`/`$addFields` instead (the established pattern).
- Be careful with `Computer.remove()` — its `post('remove')` hook cascade-deletes from ~19 collections. Never trigger document `remove()` casually; for cleanup prefer explicit, reviewed operations.

### 4.7 Requiredness is advisory
Because schemas use `require` (typo) not `required`, MongoDB does **not** reject missing "required" fields. Defensively handle `null`/absent values even on `R` fields, and use `preserveNullAndEmptyArrays` on lookups.

---

## 5. Security, Privacy & Data Masking (Critical Section)

This is a surveillance/DLP dataset: **most content fields are sensitive personal data**. Treat the whole store as confidential and minimize exposure.

### 5.1 NEVER read, surface, log, or echo these fields
| Collection | Field | Why |
|---|---|---|
| `clients` | `token` | 🔒 Agent authentication secret — credential. |
| `keyloggers` | `text` | 🔒🔒 Raw keystrokes (captures passwords, PII, anything typed). |
| `clipboards` | `content`, `dataUrl` | Arbitrary copied data, possibly credentials/PII. |
| `emails` | `from`, `to`, `subject`, `message` | Private correspondence + email addresses (PII). |
| `telegrams`/`whatsapps` | `message`, contact `phone`/`username`/`name`, `transcript.text` | Private messages, phone numbers, voice transcripts. |
| `ftps` | `dataContent` | Raw transferred file content. |
| `incidents` | `content` | Snapshot of the violating (often confidential) content. |
| `*` | `extractedText.content` | OCR text of documents — may contain financial/PII data. |
| `screenshots` | `imageUrl` | Pointer to a full screen capture. |
| `websearches` | `text`, `webvisitings`.`page`/`title` | Browsing/search history (PII-adjacent behavioral data). |

PII identifiers throughout: `clients.email`, `phoneNumber`, `firstName/lastName/fullName`, `sid`; `computers.macAddress`/`ipAddress`/`globalIp`; `ftps.clientIp`; messenger contact blocks.
