'use strict';

const SVG_NS = 'http://www.w3.org/2000/svg';
const $ = (id) => document.getElementById(id);

// Statuslar — texnik nom o'rniga oddiy o'zbekcha
const STATUS = {
  anomaly:      { label: "Chetlanish",  color: '#e74c3c', css: 'red',   mark: '🔴', rank: 3 },
  normal:       { label: "Odatdagidek", color: '#2ecc71', css: 'green', mark: '🟢', rank: 1 },
  insufficient: { label: "Baholanmadi", color: '#95a5a6', css: 'gray',  mark: '⚪', rank: 0 },
};
/** Kun chetlanish sanaladimi.
 *
 *  Eski (backfill qilinmagan) yozuvlarda `isAnomaly` maydoni yo'q. Ularda eski
 *  status nomiga QARAMAYMIZ — u boshqa chegara bilan hisoblangan va `watch`
 *  (0.5–1.2) yangi qoidada normal ham, chetlanish ham bo'lishi mumkin.
 *  O'rniga z'dan qaytadan hisoblaymiz: bu backfill qiladigan ishning aynan o'zi,
 *  shuning uchun dashboard backfilldan oldin ham to'g'ri ko'rsatadi.
 */
const isAnomalyRow = (row) => {
  if (typeof row.isAnomaly === 'boolean') return row.isAnomaly;
  const o = outsideOf(row);              // eski yozuv — oyna qoidasini o'zimiz qo'llaymiz
  return !!o && (o.before > 0 || o.after > 0);
};

/** Qator rangi/yorlig'i. Eski yozuvlarda ham z'dan hisoblanadi. */
const statusOf = (row) => {
  if (row.status === 'insufficient') return STATUS.insufficient;
  if (row.status === 'anomaly' || row.status === 'normal') return STATUS[row.status];
  // Eski 4 pog'onali yozuv (watch/severe) — yangi qoida bo'yicha qayta baholaymiz
  if (!windowOf(row)) return STATUS.insufficient;
  return isAnomalyRow(row) ? STATUS.anomaly : STATUS.normal;
};
const WEEKDAY_UZ = {
  Monday: 'dushanba', Tuesday: 'seshanba', Wednesday: 'chorshanba', Thursday: 'payshanba',
  Friday: 'juma', Saturday: 'shanba', Sunday: 'yakshanba',
};
const MONTH_UZ = ['yanvar', 'fevral', 'mart', 'aprel', 'may', 'iyun',
  'iyul', 'avgust', 'sentabr', 'oktabr', 'noyabr', 'dekabr'];

let rows = [];          // joriy filtrdagi natijalar
let baselines = {};     // clientId -> weeks
let clientList = [];    // [{clientId, hostname, fullName, label}]
let riskRows = [];      // /api/risk-summary natijasi
let zThreshold = 1.0;   // /api/health dan keladi (.env: ANOMALY_Z_THRESHOLD)
let minDowSamples = 3;  // /api/health dan keladi (.env: MIN_DOW_SAMPLES)
// Qolgan sozlamalar ham serverdan keladi — bu yerda faqat zaxira qiymatlar.
// Server javob bermasa sahifa baribir chiziladi.
let sozlama = { severity: { high: 75, medium: 50, low: 25 },
                dashboard: { rangeDays: 30, maxIssues: 20 } };

/** Ekranda ko'rsatiladigan nom: ism bo'lsa "Ism — hostname", bo'lmasa hostname */
function personName(row) {
  // Ism bo'lsa ism, bo'lmasa hostname.
  // Eski natijalarda ism maydoni yo'q — xodimlar ro'yxatidan qidiramiz.
  const name = row.fullName
    || (clientList.find((c) => c.clientId === row.clientId) || {}).fullName;
  return name || row.hostname || row.clientId;
}

// ---------------------------------------------------------------- formatlash
const iso = (d) => d.toISOString().slice(0, 10);

/** "2026-08-25" -> "25-avgust, seshanba" */
function humanDate(dateStr, weekday) {
  const [, m, d] = dateStr.split('-');
  const wd = WEEKDAY_UZ[weekday] || '';
  return `${+d}-${MONTH_UZ[+m - 1]}${wd ? ', ' + wd : ''}`;
}

/** 107.4 -> "1 soat 47 daqiqa";  45 -> "45 daqiqa" */
function humanMinutes(mins) {
  const total = Math.round(Math.abs(mins));
  const h = Math.floor(total / 60), m = total % 60;
  if (h && m) return `${h} soat ${m} daqiqa`;
  if (h) return `${h} soat`;
  return `${m} daqiqa`;
}

/** 555 -> "09:15" */
function minutesToHHMM(mins) {
  const m = Math.round(mins) % 1440;
  return String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
}

/** "09:15:32" -> 555.5 */
function hhmmssToMinutes(s) {
  const [h, m, sec] = s.split(':').map(Number);
  return h * 60 + m + (sec || 0) / 60;
}

// -------------------------------------------------------- baseline bilan taqqoslash
/** Bir kun uchun: odatdagi jadval va undan farq. Baseline yo'q bo'lsa null. */
function compare(row) {
  // Natija o'zi-o'ziga yetarli: qaysi normaga qarab baholangani uning ichida
  // saqlanadi. Shunda "baholanmadi" deb yozilgan kun yonida joriy baseline'dan
  // olingan farq ko'rinib qolmaydi (versiya nomuvofiqligi bo'lmaydi).
  let w = (row.usualStart !== null && row.usualStart !== undefined)
    ? { meanStart: row.usualStart, meanFinish: row.usualFinish,
        stdStart: row.stdStart, stdFinish: row.stdFinish }
    : null;

  // Eski natijalarda bu maydonlar yo'q — joriy baseline'dan qidiramiz
  if (!w) {
    const weeks = baselines[row.clientId];
    w = weeks && weeks[row.dayOfWeek];
  }
  if (!w || w.meanStart === null || w.meanStart === undefined) return null;

  const startMin = hhmmssToMinutes(row.start);
  const finishMin = hhmmssToMinutes(row.finish);
  return {
    usualStart: w.meanStart,
    usualFinish: w.meanFinish,
    stdStart: w.stdStart,
    stdFinish: w.stdFinish,
    // musbat = erta keldi;  manfiy = kech keldi
    arriveDiff: w.meanStart - startMin,
    // musbat = kech ketdi;  manfiy = erta ketdi
    leaveDiff: finishMin - w.meanFinish,
  };
}

/** Kunning ish oynasi (daqiqada) yoki null.
 *
 *  Qoida backend bilan bir xil:  lo = usualStart − T·σ,  hi = usualFinish + T·σ.
 *  Yangi natijalarda tayyor `windowStart`/`windowFinish` bo'ladi — o'shani olamiz;
 *  eski yozuvlarda `compare()` dan hisoblaymiz.
 */
function windowOf(row) {
  if (row.windowStart !== null && row.windowStart !== undefined
      && row.windowFinish !== null && row.windowFinish !== undefined) {
    return { lo: row.windowStart, hi: row.windowFinish };
  }
  const c = compare(row);
  if (!c) return null;
  return {
    lo: c.usualStart - zThreshold * (c.stdStart || 0),
    hi: c.usualFinish + zThreshold * (c.stdFinish || 0),
  };
}

/** Oynadan tashqarida qolgan daqiqalar: {before, after, lo, hi} yoki null. */
function outsideOf(row) {
  const w = windowOf(row);
  if (!w) return null;
  return {
    before: Math.max(0, w.lo - hhmmssToMinutes(row.start)),
    after: Math.max(0, hhmmssToMinutes(row.finish) - w.hi),
    lo: w.lo,
    hi: w.hi,
  };
}

/** «Ish oynasidan 1 soat 12 daqiqa oldin faollik» ko'rinishidagi jumlalar.
 *
 *  Kech kelish va erta ketish bu yerda ATAYLAB yo'q — ular oyna ichida qoladi
 *  va shubhali sanalmaydi.
 */
function describe(row) {
  const o = outsideOf(row);
  if (!o) return [];
  const oyna = `Ish oynasi ${minutesToHHMM(o.lo)}–${minutesToHHMM(o.hi)}`;
  const out = [];
  if (o.before >= 1) {
    out.push({
      text: `Ish oynasi boshlanishidan ${humanMinutes(o.before)} oldin faollik`,
      detail: `Birinchi faollik ${row.start.slice(0, 5)} · ${oyna}`,
      z: o.before,
    });
  }
  if (o.after >= 1) {
    out.push({
      text: `Ish oynasi tugaganidan ${humanMinutes(o.after)} keyin faollik`,
      detail: `Oxirgi faollik ${row.finish.slice(0, 5)} · ${oyna}`,
      z: o.after,
    });
  }
  return out.sort((a, b) => b.z - a.z);
}

// ---------------------------------------------------------------- ma'lumot olish
async function loadBaselines() {
  try {
    const list = await (await fetch('/api/baseline')).json();
    baselines = Object.fromEntries(list.map((b) => [b.clientId, b.weeks]));
  } catch (e) { baselines = {}; }
}

async function loadClients() {
  try {
    const list = await (await fetch('/api/clients')).json();
    clientList = list;
    const sel = $('client'), keep = sel.value;
    sel.innerHTML = '<option value="">Barcha xodimlar</option>';
    for (const c of list) {
      const o = document.createElement('option');
      o.value = c.clientId; o.textContent = c.label || c.hostname;
      sel.appendChild(o);
    }
    sel.value = keep;
  } catch (e) { /* bo'sh qoladi */ }
}

async function loadResults() {
  const params = new URLSearchParams({ from: $('from').value, to: $('to').value, limit: '5000' });
  if ($('client').value) params.set('client_id', $('client').value);
  try {
    const data = await (await fetch('/api/results?' + params)).json();
    rows = data.items || [];
  } catch (e) {
    rows = [];
  }
  render();
}

/** Kuzatuvdagi xodimlar jadvali uchun ma'lumot.
 *
 *  Alohida so'rov: `/api/results` bitta xodim tanlanganda faqat o'shaning
 *  kunlarini beradi, bu jadval esa HAR DOIM hammasini talab qiladi.
 */
async function loadRiskSummary() {
  const q = new URLSearchParams();
  if ($('from').value) q.set('from', $('from').value);
  if ($('to').value) q.set('to', $('to').value);
  try {
    riskRows = await (await fetch('/api/risk-summary?' + q)).json();
  } catch (e) {
    riskRows = [];
  }
  renderRiskTable();
}

/** Kumulyativ xavf chizig'i — inline SVG matni sifatida.
 *
 *  DIQQAT: bu yerda `el()` ISHLATILMAYDI. U `createElementNS` bilan SVG
 *  namespace'da element yasaydi — grafiklar uchun to'g'ri, lekin `<tr>`/`<td>`
 *  uchun emas: ular DOM'da paydo bo'ladi-yu, jadval sifatida chizilmaydi.
 *  Shuning uchun jadval HTML matn sifatida quriladi.
 */
function sparklineSvg(trend, w = 88, h = 26) {
  if (!trend || trend.length < 2) return `<svg width="${w}" height="${h}" class="risk-spark"></svg>`;
  const max = Math.max(...trend) || 1;
  const dx = w / (trend.length - 1);
  const pts = trend
    .map((v, i) => `${(i * dx).toFixed(1)},${(h - 3 - (v / max) * (h - 6)).toFixed(1)}`)
    .join(' ');
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" class="risk-spark">
    <polyline points="${pts}" fill="none" stroke="#4dd0e1" stroke-width="1.6"
              stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}

function renderRiskTable() {
  const tbody = $('riskTable').querySelector('tbody');
  const tanlangan = $('client').value;
  $('riskInfo').textContent = riskRows.length ? `— ${riskRows.length} ta` : '';

  if (!riskRows.length) {
    tbody.innerHTML = '<tr><td colspan="4" class="empty">Bu oraliqda baholangan kun yo\'q</td></tr>';
    return;
  }

  tbody.innerHTML = riskRows.map((r) => `
    <tr data-client="${r.clientId}"${r.clientId === tanlangan ? ' class="active"' : ''}>
      <td>
        <i class="risk-mark ${r.level}" title="Oxirgi xavf: ${r.recentRisk}"></i>
        <span class="risk-name">${r.fullName || r.hostname}</span>
      </td>
      <td class="num">${r.recentRisk}</td>
      <td title="${r.evaluatedDays} ta baholangan kun">
        ${sparklineSvg(r.trend)}<span class="risk-total">${r.overallRisk}</span>
      </td>
      <td class="num">
        <span class="risk-cases${r.anomalyDays ? ' hit' : ''}">${r.anomalyDays}</span>
      </td>
    </tr>`).join('');

  // Qatorni bosish — o'sha xodimga o'tish (qayta bosilsa tanlov bekor qilinadi)
  for (const tr of tbody.querySelectorAll('tr[data-client]')) {
    tr.addEventListener('click', () => {
      const cid = tr.getAttribute('data-client');
      $('client').value = (cid === $('client').value) ? '' : cid;
      loadResults();
    });
  }
}

async function loadHealth() {
  try {
    const h = await (await fetch('/api/health')).json();
    if (typeof h.anomalyZThreshold === 'number') zThreshold = h.anomalyZThreshold;
    if (typeof h.minDowSamples === 'number') minDowSamples = h.minDowSamples;
    if (h.severity) sozlama.severity = h.severity;
    if (h.dashboard) sozlama.dashboard = h.dashboard;
    const bad = [];
    if (h.mongo_main !== 'ok') bad.push('asosiy baza');
    if (h.mongo_local !== 'ok') bad.push('mahalliy baza');
    if (h.rabbitmq !== 'ok') bad.push('navbat');
    $('health').innerHTML = bad.length
      ? `<span class="bad">⚠ Ishlamayapti: ${bad.join(', ')}</span>`
      : `<span class="ok">●</span> Tizim ishlayapti`;
    renderRunbar(h);
    return h;
  } catch (e) {
    $('health').innerHTML = '<span class="bad">⚠ Server bilan aloqa yo\'q</span>';
    return null;
  }
}

/** Sana-vaqtni qisqa ko'rinishda: "09-09 14:10". Bo'sh bo'lsa "—". */
function qisqaVaqt(iso) {
  if (!iso) return '—';
  return iso.slice(5, 16).replace('T', ' ');
}

/** Fon jarayonlari qatori: oxirgi retrain, oxirgi trigger va jarayon chizig'i.
 *
 *  Har `loadHealth()` da yangilanadi, shuning uchun sahifa qayta ochilsa ham
 *  ko'rinadi — ilgari holat faqat tugma bosilgandan keyingi polling paytida
 *  ko'rinardi va tunda bo'lgan xato bilinmay qolardi.
 */
function renderRunbar(h) {
  const r = (h && h.lastRetrain) || {};
  const t = (h && h.lastTrigger) || {};

  // Jarayon chizig'i — faqat ish ketayotganda
  const ketmoqda = r.status === 'running';
  $('runProgress').hidden = !ketmoqda;
  if (ketmoqda) {
    const foiz = Math.max(0, Math.min(100, r.progress || 0));
    $('runProgressFill').style.width = foiz + '%';
    $('runProgressPct').textContent = foiz + '%';
    $('runProgressText').textContent = r.progressText
      || { collecting: "Ma'lumot yig'ilmoqda", training: 'Odatiy jadvallar hisoblanmoqda' }[r.stage]
      || 'Bajarilmoqda';
  }

  const belgi = { finished: ['ok', '✓'], partial: ['warn', '⚠'], error: ['bad', '✕'],
                  running: ['', '…'], idle: ['', '—'] };

  const [rk, ri] = belgi[r.status] || ['', ''];
  $('runRetrain').innerHTML = `Oxirgi yangilash: <b>${qisqaVaqt(r.finishedAt || r.startedAt)}</b>`
    + ` <span class="${rk}">${ri}</span>`
    + (r.status === 'partial' ? ` <span class="warn">(${(r.failedClients || []).length} xodim tushib qoldi)</span>` : '')
    + (r.status === 'error' ? ` <span class="bad">xato</span>` : '');

  const [tk, ti] = belgi[t.status] || ['', ''];
  $('runTrigger').innerHTML = `Oxirgi tekshiruv: <b>${qisqaVaqt(t.finishedAt || t.startedAt)}</b>`
    + ` <span class="${tk}">${ti}</span>`
    + (t.status === 'finished' ? ` <span class="muted">(${t.sent || 0} kun yuborildi)</span>` : '')
    + (t.status === 'error' ? ` <span class="bad">xato</span>` : '');

  // "Xatolar" tugmasi faqat xato bo'lsa ko'rinadi
  const xatoBor = r.status === 'error' || t.status === 'error'
    || (r.errorCount || 0) > 0 || r.status === 'partial';
  const btn = $('errorsBtn');
  btn.hidden = !xatoBor;
  btn.className = xatoBor ? 'ghost has-errors' : 'ghost';
}

async function loadErrors() {
  const tbody = $('errorsTable').querySelector('tbody');
  let rows = [];
  try {
    rows = await (await fetch('/api/errors?limit=100')).json();
  } catch (e) { rows = []; }

  $('errorsInfo').textContent = rows.length ? `— ${rows.length} ta` : '';
  tbody.innerHTML = rows.length
    ? rows.map((x) => `<tr>
        <td class="time dim">${qisqaVaqt(x.at)}</td>
        <td>${x.manba || ''}</td>
        <td class="dim">${x.kontekst || ''}</td>
        <td class="xato">${(x.xato || '').replace(/</g, '&lt;')}</td>
      </tr>`).join('')
    : '<tr><td colspan="4" class="empty">Xato qayd etilmagan</td></tr>';
}

// ---------------------------------------------------------------- chizish
function render() {
  const visible = $('onlyIssues').checked
    ? rows.filter(isAnomalyRow)
    : rows;
  renderSummary();
  renderRiskTable();
  renderIssues();
  renderChart(visible);
  renderTable(visible);
}

function renderSummary() {
  const c = { severe: 0, anomaly: 0, watch: 0, normal: 0, insufficient: 0 };
  for (const r of rows) if (c[r.status] !== undefined) c[r.status]++;

  if (!rows.length) {
    $('summary').innerHTML = `Tanlangan sanalar oralig'ida ma'lumot topilmadi.
      <span class="note">Sana oralig'ini kengaytiring yoki boshqa xodimni tanlang.</span>`;
    return;
  }

  const problems = c.anomaly + (c.severe || 0) + (c.watch || 0);
  const sel = $('client').value;
  const who = sel
    ? ((clientList.find((c) => c.clientId === sel) || {}).hostname || sel)
    : 'barcha xodimlar';
  let text = `<b>${who}</b> bo'yicha <b>${rows.length} ish kuni</b> tekshirildi. `;

  if (problems) {
    text += `Ulardan <b>${problems} kunda</b> ish oynasidan tashqarida faollik qayd etildi.`;
  } else if (c.normal) {
    text += `Hammasi odatdagidek — chetlanish topilmadi.`;
  } else {
    text += `Hali birortasi ham baholanmadi.`;
  }

  if (c.insufficient) {
    text += `<span class="note">${c.insufficient} kun baholanmadi: bu xodimning shu hafta kuni bo'yicha
      hali yetarli tarixi yo'q (baholash uchun kamida ${minDowSamples} ta shunday kun kerak).
      Vaqt o'tib ma'lumot to'plangach ular ham baholanadi.</span>`;
  }
  $('summary').innerHTML = text;
}

/** Kunning chetlanish darajasi (0-100) yoki null.
 *  Yangi natijalarda tayyor, eskilarida ko'rsatilmaydi. */
const severityOf = (row) =>
  (typeof row.riskScore === 'number') ? row.riskScore
    : (typeof row.anomalyScore === 'number') ? row.anomalyScore : null;

/** Daraja uchun qisqa yorliq: 100 ballik shkala odamga tushunarli tilda. */
function severityLabel(score) {
  if (score === null) return '';
  if (score >= sozlama.severity.high) return 'juda yuqori';
  if (score >= sozlama.severity.medium) return 'yuqori';
  if (score >= sozlama.severity.low) return "o'rtacha";
  return 'past';
}

function renderIssues() {
  const issues = rows
    .filter(isAnomalyRow)
    // Eng xavflisi tepada: daraja bo'yicha, teng bo'lsa yangi sana bo'yicha
    .sort((a, b) => (severityOf(b) || 0) - (severityOf(a) || 0)
      || b.date.localeCompare(a.date))
    .slice(0, sozlama.dashboard.maxIssues);

  if (!issues.length) {
    $('issues').innerHTML = `<p class="ok-note">Bu oraliqda e'tibor talab qiladigan kun topilmadi.</p>`;
    return;
  }

  $('issues').innerHTML = issues.map((r) => {
    const parts = describe(r);
    const what = parts.length
      ? parts.map((p) => p.text).join(', ')
      : statusOf(r).label;
    const detail = parts.map((p) => p.detail).join('<br>');
    const sev = severityOf(r);
    const badge = sev === null ? ''
      : `<span class="sev sev-${severityLabel(sev).replace(/[^a-z]/g, '')}"
              title="Chetlanish darajasi: xodimning o'z og'ishiga nisbatan">
           ${sev} · ${severityLabel(sev)}</span>`;
    return `
      <div class="issue ${r.status}">
        <div class="mark">${statusOf(r).mark}</div>
        <div>
          <div class="who">${personName(r)} ${badge}</div>
          <div class="when">${humanDate(r.date, r.dayOfWeek)}</div>
          <div class="what">${what}</div>
          <div class="detail">${detail}</div>
        </div>
      </div>`;
  }).join('');
}

// --- SVG yordamchisi
function el(tag, attrs, text) {
  const n = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
}
function clearSvg(svg) { while (svg.firstChild) svg.removeChild(svg.firstChild); }

function renderChart(visible) {
  const oneClient = !!$('client').value;
  const svg = $('chart');
  clearSvg(svg);

  if (!rows.length) {
    svg.setAttribute('height', 56);
    svg.appendChild(el('text', { x: 12, y: 32 }, 'Ko\'rsatadigan ma\'lumot yo\'q'));
    $('chartHint').textContent = '';
    $('chartLegend').innerHTML = '';
    return;
  }

  if (oneClient) {
    $('chartTitle').textContent = 'Ish oynasi va faollik vaqtlari';
    $('chartHint').textContent = 'X o\'qi — kunlar, Y o\'qi — sutka soatlari. '
      + 'Kulrang fon — shu kunning ish oynasi. Ikkita nuqta — birinchi va oxirgi '
      + 'faollik: oynadan tashqarida bo\'lsa qizil, ichida bo\'lsa yashil. '
      + 'Bo\'sh ustun — o\'sha kuni manbada faollik umuman qayd etilmagan.';
    $('chartLegend').innerHTML = `
      <span><i style="background:#8a97ab;opacity:.5"></i> ish oynasi</span>
      <span><i style="background:#2ecc71;border-radius:50%"></i> oyna ichida</span>
      <span><i style="background:#e74c3c;border-radius:50%"></i> oynadan tashqarida</span>
      <span><i style="background:#95a5a6;border-radius:50%"></i> baholanmadi</span>
      <span><i style="background:#3a4657"></i> faollik qayd etilmagan</span>`;
    drawBaselineChart(svg, visible);
  } else {
    $('chartTitle').textContent = 'Umumiy manzara';
    $('chartHint').textContent = 'Qatorlar — xodimlar, ustunlar — kunlar. '
      + 'Har katak rangi o\'sha kunning holati, bo\'sh katak — faollik qayd etilmagan. '
      + 'Bitta xodimni tanlasangiz uning odatiy oralig\'i chiziladi.';
    $('chartLegend').innerHTML = `
      <span><i style="background:#2ecc71"></i> odatdagidek</span>
      <span><i style="background:#e74c3c"></i> chetlanish</span>
      <span><i style="background:#95a5a6"></i> baholanmagan</span>`;
    drawMatrix(svg, visible);
  }
}

function drawMatrix(svg, visible) {
  const dates = [...new Set(visible.map((r) => r.date))].sort();
  const names = [...new Set(visible.map((r) => r.hostname || r.clientId))].sort();
  const cell = new Map();
  for (const r of visible) cell.set((r.hostname || r.clientId) + '|' + r.date, r);

  const cw = Math.max(9, Math.min(20, Math.floor(760 / Math.max(1, dates.length))));
  const rh = 22;
  const pad = { l: 200, r: 16, t: 26, b: 40 };
  const W = pad.l + dates.length * cw + pad.r;
  const H = pad.t + names.length * rh + pad.b;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('height', H);

  // Sana yorliqlari (oralab)
  const step = Math.max(1, Math.ceil(dates.length / 20));
  dates.forEach((d, i) => {
    if (i % step) return;
    const x = pad.l + i * cw + cw / 2;
    svg.appendChild(el('text', {
      x, y: H - pad.b + 26, 'text-anchor': 'end',
      transform: `rotate(-50 ${x} ${H - pad.b + 26})`,
    }, d.slice(5)));
  });

  names.forEach((name, r) => {
    const y = pad.t + r * rh;
    const short = name.length > 26 ? name.slice(0, 25) + '…' : name;
    svg.appendChild(el('text', { x: pad.l - 10, y: y + 15, 'text-anchor': 'end' }, short));

    dates.forEach((d, i) => {
      const row = cell.get(name + '|' + d);
      const rect = el('rect', {
        x: pad.l + i * cw + 1, y: y + 3, width: cw - 2, height: rh - 6, rx: 2,
        fill: row ? statusOf(row).color : '#1e2632',
        opacity: row ? 0.9 : 1,
      });
      if (row) {
        rect.appendChild(el('title', {}, `${name}\n${humanDate(row.date, row.dayOfWeek)}\n` +
          `${row.start.slice(0, 5)} – ${row.finish.slice(0, 5)}\n${statusOf(row).label}`));
      }
      svg.appendChild(rect);
    });
  });
}

/** Baseline grafigi: X o'qi kunlar, Y o'qi sutka soatlari.
 *
 *  Kulrang fon — shu kunning odatiy oralig'i: kelish normasining quyi chetidan
 *  ketish normasining yuqori chetigacha (masalan 08:50 – 18:20).
 *  Nuqtalar — haqiqiy kelish va ketish vaqti. Har nuqta O'Z o'qi bo'yicha rang
 *  oladi: normadan chiqsa qizil, chiqmasa yashil. Shuning uchun bir kunda
 *  kelish yashil, ketish qizil bo'lishi mumkin.
 *
 *  `|z| <= chegara` aynan "mean ± chegara·std oralig'ida" degani, shuning uchun
 *  nuqta rangi kulrang zonaga to'liq mos keladi — ziddiyat bo'lishi mumkin emas.
 */
/** Chizish uchun kunlar ro'yxati: tanlangan oraliqdagi HAR BIR kalendar kuni.
 *
 *  Qaytaradi `[{date, row}]` — `row` null bo'lsa o'sha kuni ma'lumot yo'q.
 *  Oraliq filtrlardan olinadi; ular bo'sh bo'lsa ma'lumotning o'z chegarasi.
 */
function kalendarKunlari(bor) {
  const sanalar = [...bor.keys()].sort();
  const boshi = $('from').value || sanalar[0];
  const oxiri = $('to').value || sanalar[sanalar.length - 1];
  if (!boshi || !oxiri) return [];

  const MAX = 400;   // undan ortig'i grafikda o'qilmay qoladi
  const out = [];
  const d = new Date(boshi + 'T12:00:00');
  const son = new Date(oxiri + 'T12:00:00');
  while (d <= son) {
    const sana = d.toISOString().slice(0, 10);
    out.push({ date: sana, row: bor.get(sana) || null });
    d.setDate(d.getDate() + 1);
  }
  // Cheklov OXIRIDAN olinadi: uzoq oraliqda eng yangi kunlar kerak.
  // Boshidan kessak, 2 yillik oraliqda bugungi ma'lumot tushib qolardi.
  return out.length > MAX ? out.slice(-MAX) : out;
}

function drawBaselineChart(svg, visible) {
  // X o'qi — TO'LIQ kalendar, faqat ma'lumot bor kunlar emas.
  //
  // Ilgari bu yerda `visible` ning o'zi ishlatilardi va o'q "ma'lumot bor
  // kunlar ketma-ketligi" bo'lib qolardi: 08-15 va 08-20 yonma-yon turib,
  // orada 4 kun borligi ko'rinmasdi. Endi har kalendar kuni o'z ustuniga
  // ega — ma'lumotsiz kun bo'sh joy sifatida ko'rinadi. Bo'shliqning o'zi
  // ma'lumot: agent hech narsa yubormagan (ta'til, o'chirilgan kompyuter,
  // agent ishlamayapti).
  const bor = new Map([...visible].map((r) => [r.date, r]));
  const days = kalendarKunlari(bor);

  // Eng kichik ustun kengligi 14px: vertikal sana yorlig'i shundan tor
  // bo'lsa qo'shnisiga kirib ketadi. Grafik siqilmaydi — kengroq bo'lsa
  // `.chart-wrap` scroll beradi.
  const colW = Math.max(14, Math.min(46, Math.floor(900 / Math.max(1, days.length))));
  const pad = { l: 54, r: 16, t: 12, b: 58 };
  const W = Math.max(560, pad.l + pad.r + colW * days.length);
  const H = 420;
  const plotH = H - pad.t - pad.b;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('height', H);
  // Tabiiy kenglik — konteynerdan kengroq bo'lsa .chart-wrap scroll beradi
  svg.style.width = `${W}px`;

  const y = (mins) => pad.t + plotH - (mins / 1440) * plotH;
  const cx = (i) => pad.l + i * colW + colW / 2;

  for (let hour = 0; hour <= 24; hour += 2) {
    const yy = y(hour * 60);
    svg.appendChild(el('line', {
      x1: pad.l, y1: yy, x2: W - pad.r, y2: yy, class: 'grid',
      opacity: hour % 6 === 0 ? 1 : 0.45,
    }));
    svg.appendChild(el('text', { x: pad.l - 8, y: yy + 4, 'text-anchor': 'end' },
      String(hour).padStart(2, '0') + ':00'));
  }

  const bw = Math.min(28, colW * 0.72);

  // Yorliq faqat MA'LUMOT BOR kunlarga qo'yiladi — bo'sh kunlarda pastdagi
  // belgi yetarli. Ustunlar tor bo'lsa yorliqlar bir-biriga kirib ketmasligi
  // uchun ular orasida kamida 13px masofa qoldiriladi.
  const belgilanadi = new Set();
  let oxirgiX = -Infinity;
  days.forEach((kun, i) => {
    if (!kun.row) return;
    if (cx(i) - oxirgiX >= 13) {
      belgilanadi.add(i);
      oxirgiX = cx(i);
    }
  });

  days.forEach((kun, i) => {
    if (belgilanadi.has(i)) {
      const ly = H - pad.b + 10;
      svg.appendChild(el('text', {
        x: cx(i), y: ly, 'text-anchor': 'end',
        transform: `rotate(-90 ${cx(i)} ${ly})`,
      }, kun.date.slice(5)));
    }

    const r = kun.row;
    if (!r) {
      // Ma'lumotsiz kun: manbada bitta ham hodisa bo'lmagan. Ustun bo'sh
      // qoladi, faqat pastda ingichka belgi — bo'shliq ko'rinib tursin.
      const tick = el('rect', {
        x: cx(i) - 1, y: pad.t + plotH - 3, width: 2, height: 3,
        fill: '#3a4657',
      });
      tick.appendChild(el('title', {}, `${kun.date}\nFaollik qayd etilmagan`));
      svg.appendChild(tick);
      return;
    }

    const w = windowOf(r);          // {lo, hi} yoki null

    // Kulrang fon — ish oynasi. Faqat baseline bor kunlarda chiziladi.
    if (w) {
      const band = el('rect', {
        x: cx(i) - bw / 2, y: y(Math.min(1440, w.hi)), width: bw,
        height: Math.max(2, y(Math.max(0, w.lo)) - y(Math.min(1440, w.hi))),
        fill: '#8a97ab', opacity: 0.22, rx: 3,
      });
      band.appendChild(el('title', {},
        `${humanDate(r.date, r.dayOfWeek)}\nIsh oynasi: ${minutesToHHMM(w.lo)} – ${minutesToHHMM(w.hi)}`));
      svg.appendChild(band);
    }

    // Kelish va ketish nuqtalari.
    // Rang QOIDASI: nuqta oynadan tashqarida bo'lsa qizil, ichida bo'lsa yashil.
    // Ya'ni rang kulrang fonga to'g'ridan-to'g'ri mos keladi — kech kelish yoki
    // erta ketish (oyna ICHIDA qolgani uchun) qizil bo'lmaydi.
    const marks = [
      { time: r.start, word: 'Birinchi faollik' },
      { time: r.finish, word: 'Oxirgi faollik' },
    ];
    for (const m of marks) {
      if (!m.time) continue;
      const mins = hhmmssToMinutes(m.time);
      const outside = w && (mins < w.lo || mins > w.hi);
      const dot = el('circle', {
        cx: cx(i), cy: y(mins), r: Math.max(2.5, Math.min(4, colW * 0.22)),
        fill: !w ? '#95a5a6' : (outside ? '#e74c3c' : '#2ecc71'),
        stroke: '#0f1419', 'stroke-width': 1,
      });
      const izoh = w
        ? `Ish oynasi ${minutesToHHMM(w.lo)}–${minutesToHHMM(w.hi)}`
          + (outside ? ' — TASHQARIDA' : ' — ichida')
        : 'Baholanmadi — bu hafta kuni uchun tarix yetarli emas';
      dot.appendChild(el('title', {}, `${humanDate(r.date, r.dayOfWeek)}\n`
        + `${m.word} ${m.time.slice(0, 5)}\n${izoh}`));
      svg.appendChild(dot);
    }
  });
}

function renderTable(visible) {
  const tbody = $('table').querySelector('tbody');
  $('tableInfo').textContent = `— ${visible.length} ta`;

  if (!visible.length) {
    tbody.innerHTML = '<tr><td colspan="11" class="empty">Ko\'rsatadigan kun yo\'q</td></tr>';
    return;
  }

  // Farq ustunlari o'rtachadan chetlanishni ko'rsatadi. Bu ENDI shubha belgisi
  // emas — xulosani ish oynasi qoidasi beradi (kech kelish oyna ichida qolsa
  // shubhali sanalmaydi). Shuning uchun rang berilmaydi, faqat ma'lumot.
  const diffCell = (diff, earlyWord, lateWord) => {
    if (diff === null) return '<td class="dim">—</td>';
    if (Math.abs(diff) < 5) return '<td class="dim">deyarli bir xil</td>';
    return `<td class="dim">${humanMinutes(diff)} ${diff > 0 ? earlyWord : lateWord}</td>`;
  };

  // Sof ish vaqti: tanaffuslar chiqarib tashlangan (agent hodisalaridan).
  // Kun uzunligi bilan farqi — tanaffusda o'tgan vaqt.
  const aktivCell = (r) => {
    if (typeof r.activeMin !== 'number') return '—';
    const tanaffus = (r.durationMin || 0) - r.activeMin;
    return `<span title="Kun uzunligi ${humanMinutes(r.durationMin || 0)}, `
      + `tanaffus ${humanMinutes(tanaffus)}">${humanMinutes(r.activeMin)}</span>`;
  };

  // Daraja ustuni: faqat chetlanish bo'lgan kunlarda ko'rsatiladi
  const sevCell = (r) => {
    const sev = severityOf(r);
    if (!isAnomalyRow(r) || sev === null) return '<span class="dim">—</span>';
    const w = Math.max(3, sev);
    return `<span class="sev-bar" title="${sev} / 100 — ${severityLabel(sev)}">
              <i style="width:${w}%"></i></span><span class="sev-num">${sev}</span>`;
  };

  tbody.innerHTML = [...visible]
    .sort((a, b) => b.date.localeCompare(a.date) || (a.hostname || '').localeCompare(b.hostname || ''))
    .map((r) => {
      const c = compare(r);
      const s = statusOf(r);
      return `
      <tr>
        <td>${humanDate(r.date, r.dayOfWeek)}</td>
        <td>${personName(r)}</td>
        <td class="time">${r.start.slice(0, 5)}</td>
        <td class="time dim">${c ? minutesToHHMM(c.usualStart) : '—'}</td>
        ${diffCell(c ? c.arriveDiff : null, 'erta', 'kech')}
        <td class="time">${r.finish.slice(0, 5)}</td>
        <td class="time dim">${c ? minutesToHHMM(c.usualFinish) : '—'}</td>
        ${diffCell(c ? -c.leaveDiff : null, 'erta', 'kech')}
        <td class="time dim">${aktivCell(r)}</td>
        <td><span class="badge ${s.css}">${s.label}</span></td>
        <td class="sev-cell">${sevCell(r)}</td>
      </tr>`;
    }).join('');
}

// ---------------------------------------------------------------- retrain
let retrainTimer = null;

async function startRetrain() {
  $('retrain').disabled = true;
  $('retrainStatus').textContent = 'boshlanmoqda...';
  try {
    const res = await fetch('/api/retrain', { method: 'POST' });
    if (res.status === 409) $('retrainStatus').textContent = 'allaqachon bajarilmoqda';
    pollRetrain();
  } catch (e) {
    $('retrainStatus').textContent = 'xato: ' + e.message;
    $('retrain').disabled = false;
  }
}

function pollRetrain() {
  clearInterval(retrainTimer);
  retrainTimer = setInterval(async () => {
    const h = await loadHealth();
    const r = (h && h.lastRetrain) || {};
    const skipped = (r.failedClients || []).length;
    $('retrainStatus').textContent = {
      collecting: "Ma'lumot yig'ilmoqda...",
      training: "Odatiy jadvallar hisoblanmoqda...",
      finished: 'Yangilandi ✓',
      // Ba'zi xodimlarning ma'lumoti olinmadi — ularniki eski holicha qoldi
      partial: `Yangilandi, lekin ${skipped} ta xodim ma'lumoti olinmadi (eskisi saqlandi)`,
      error: 'Xato: ' + (r.error || '').slice(0, 60),
    }[r.stage] || '';
    $('retrainStatus').style.color = r.stage === 'partial' ? 'var(--yellow)'
      : (r.stage === 'error' ? 'var(--red)' : '');

    if (!$('errorsPanel').hidden) loadErrors();

    if (['finished', 'partial', 'error'].includes(r.status)) {
      clearInterval(retrainTimer);
      $('retrain').disabled = false;
      if (r.status !== 'error') { loadBaselines().then(loadResults); loadClients(); }
    }
  }, 2000);
}

// ---------------------------------------------------------------- boshlanish
/** Default oraliq — ma'lumotdagi eng oxirgi kundan 30 kun orqaga */
async function setDefaultRange() {
  let last = new Date();
  try {
    const d = await (await fetch('/api/results?limit=1')).json();
    if (d.items && d.items.length) last = new Date(d.items[0].date + 'T12:00:00');
  } catch (e) { /* bugundan boshlaymiz */ }
  $('to').value = iso(last);
  const kun = Math.max(1, sozlama.dashboard.rangeDays) - 1;
  $('from').value = iso(new Date(last.getTime() - kun * 86400000));
}

async function init() {
  $('refresh').addEventListener('click', async () => {
    await loadRiskSummary();
    await loadResults();
  });
  $('retrain').addEventListener('click', startRetrain);
  for (const id of ['from', 'to']) {
    $(id).addEventListener('change', async () => {
      await loadRiskSummary();     // oraliq o'zgardi -> xavf jadvali ham
      await loadResults();
    });
  }
  $('client').addEventListener('change', loadResults);
  $('onlyIssues').addEventListener('change', render);
  $('errorsBtn').addEventListener('click', async () => {
    $('errorsPanel').hidden = false;
    await loadErrors();
    $('errorsPanel').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  });
  $('errorsClose').addEventListener('click', () => { $('errorsPanel').hidden = true; });

  await loadHealth();
  await setDefaultRange();
  await Promise.all([loadBaselines(), loadClients(), loadRiskSummary()]);
  await loadResults();
  // Ochilishida eng ko'p ma'lumotli xodim tanlanadi — grafik darrov to'la ko'rinsin
  if (!$('client').value && rows.length) {
    const count = {};
    for (const r of rows) count[r.clientId] = (count[r.clientId] || 0) + 1;
    const top = Object.entries(count).sort((a, b) => b[1] - a[1])[0];
    if (top && clientList.some((c) => c.clientId === top[0])) {
      $('client').value = top[0];
      await loadResults();
    }
  }

  setInterval(async () => {
    await loadHealth();
    await loadRiskSummary();
    await loadResults();
  }, 5 * 60 * 1000);
}

init();
