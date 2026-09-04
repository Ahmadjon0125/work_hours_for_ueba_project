'use strict';

const SVG_NS = 'http://www.w3.org/2000/svg';
const $ = (id) => document.getElementById(id);

// Statuslar — texnik nom o'rniga oddiy o'zbekcha
const STATUS = {
  severe:       { label: "Jiddiy chetlanish",   color: '#e74c3c', css: 'red',        mark: '🔴', rank: 4 },
  anomaly:      { label: "Sezilarli chetlanish", color: '#d99a06', css: 'darkyellow', mark: '🟠', rank: 3 },
  watch:        { label: "Kichik chetlanish",    color: '#f1c40f', css: 'yellow',     mark: '🟡', rank: 2 },
  normal:       { label: "Odatdagidek",          color: '#2ecc71', css: 'green',      mark: '🟢', rank: 1 },
  insufficient: { label: "Baholanmadi",          color: '#95a5a6', css: 'gray',       mark: '⚪', rank: 0 },
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

/** Ekranda ko'rsatiladigan nom: ism bo'lsa "Ism — hostname", bo'lmasa hostname */
function personName(row) {
  const host = row.hostname || row.clientId;
  // Eski natijalarda ism yo'q — ro'yxatdan qidiramiz
  const name = row.fullName
    || (clientList.find((c) => c.clientId === row.clientId) || {}).fullName;
  return name ? `${name} — ${host}` : host;
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
  const weeks = baselines[row.clientId];
  const w = weeks && weeks[row.dayOfWeek];
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

/** "1 soat 47 daqiqa erta keldi" ko'rinishidagi jumlalar (eng kattasi birinchi) */
function describe(row) {
  const c = compare(row);
  if (!c) return [];
  const out = [];
  if (Math.abs(row.zStart || 0) >= 0.5 && Math.abs(c.arriveDiff) >= 5) {
    out.push({
      text: `${humanMinutes(c.arriveDiff)} ${c.arriveDiff > 0 ? 'erta' : 'kech'} keldi`,
      detail: `Keldi ${row.start.slice(0, 5)} · Odatda ${WEEKDAY_UZ[row.dayOfWeek]}larda ${minutesToHHMM(c.usualStart)}`,
      z: Math.abs(row.zStart),
    });
  }
  if (Math.abs(row.zFinish || 0) >= 0.5 && Math.abs(c.leaveDiff) >= 5) {
    out.push({
      text: `${humanMinutes(c.leaveDiff)} ${c.leaveDiff > 0 ? 'kech' : 'erta'} ketdi`,
      detail: `Ketdi ${row.finish.slice(0, 5)} · Odatda ${WEEKDAY_UZ[row.dayOfWeek]}larda ${minutesToHHMM(c.usualFinish)}`,
      z: Math.abs(row.zFinish),
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

async function loadHealth() {
  try {
    const h = await (await fetch('/api/health')).json();
    const bad = [];
    if (h.mongo_main !== 'ok') bad.push('asosiy baza');
    if (h.mongo_local !== 'ok') bad.push('mahalliy baza');
    if (h.rabbitmq !== 'ok') bad.push('navbat');
    $('health').innerHTML = bad.length
      ? `<span class="bad">⚠ Ishlamayapti: ${bad.join(', ')}</span>`
      : `<span class="ok">●</span> Tizim ishlayapti`;
    return h;
  } catch (e) {
    $('health').innerHTML = '<span class="bad">⚠ Server bilan aloqa yo\'q</span>';
    return null;
  }
}

// ---------------------------------------------------------------- chizish
function render() {
  const visible = $('onlyIssues').checked
    ? rows.filter((r) => ['watch', 'anomaly', 'severe'].includes(r.status))
    : rows;
  renderSummary();
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

  const problems = c.severe + c.anomaly;
  const sel = $('client').value;
  const who = sel
    ? ((clientList.find((c) => c.clientId === sel) || {}).hostname || sel)
    : 'barcha xodimlar';
  let text = `<b>${who}</b> bo'yicha <b>${rows.length} ish kuni</b> tekshirildi. `;

  if (problems) {
    text += `Ulardan <b>${problems} kunda</b> jiddiy yoki sezilarli chetlanish bor`;
    text += c.watch ? `, yana ${c.watch} kunda kichik chetlanish.` : '.';
  } else if (c.watch) {
    text += `Jiddiy chetlanish yo'q, ${c.watch} kunda kichik chetlanish bor.`;
  } else if (c.normal) {
    text += `Hammasi odatdagidek — chetlanish topilmadi.`;
  } else {
    text += `Hali birortasi ham baholanmadi.`;
  }

  if (c.insufficient) {
    text += `<span class="note">${c.insufficient} kun baholanmadi: bu xodimning shu hafta kuni bo'yicha
      hali yetarli tarixi yo'q (baholash uchun kamida 5 ta shunday kun kerak).
      Vaqt o'tib ma'lumot to'plangach ular ham baholanadi.</span>`;
  }
  $('summary').innerHTML = text;
}

function renderIssues() {
  const issues = rows
    .filter((r) => ['watch', 'anomaly', 'severe'].includes(r.status))
    .sort((a, b) => STATUS[b.status].rank - STATUS[a.status].rank || b.date.localeCompare(a.date))
    .slice(0, 20);

  if (!issues.length) {
    $('issues').innerHTML = `<p class="ok-note">Bu oraliqda e'tibor talab qiladigan kun topilmadi.</p>`;
    return;
  }

  $('issues').innerHTML = issues.map((r) => {
    const parts = describe(r);
    const what = parts.length
      ? parts.map((p) => p.text).join(', ')
      : STATUS[r.status].label;
    const detail = parts.map((p) => p.detail).join('<br>');
    return `
      <div class="issue ${r.status}">
        <div class="mark">${STATUS[r.status].mark}</div>
        <div>
          <div class="who">${personName(r)}</div>
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
  clearSvg($('chart1'));
  clearSvg($('chart2'));

  if (!rows.length) {
    for (const id of ['chart1', 'chart2']) {
      const svg = $(id);
      svg.setAttribute('height', 56);
      svg.appendChild(el('text', { x: 12, y: 32 }, 'Ko\'rsatadigan ma\'lumot yo\'q'));
    }
    $('chart1Hint').textContent = $('chart2Hint').textContent = '';
    $('chart1Legend').innerHTML = $('chart2Legend').innerHTML = '';
    return;
  }

  const statusLegend = `
    <span><i style="background:#2ecc71"></i> odatdagidek</span>
    <span><i style="background:#f1c40f"></i> kichik chetlanish</span>
    <span><i style="background:#d99a06"></i> sezilarli</span>
    <span><i style="background:#e74c3c"></i> jiddiy</span>
    <span><i style="background:#95a5a6"></i> baholanmagan</span>`;

  // 1-grafik — ASOSIY: X o'qi kunlar, Y o'qi soatlar
  $('chart1Title').textContent = 'Kunlik ish vaqti';
  $('chart1Hint').textContent = oneClient
    ? 'X o\'qi — kunlar, Y o\'qi — sutka soatlari. Har ustun bitta kun: pastki uchi kelgan vaqti, '
      + 'yuqorigi uchi ketgan vaqti. Yashil yo\'lak — shu hafta kunidagi odatiy kelish/ketish oralig\'i.'
    : 'Yuqoridagi ro\'yxatdan bitta xodimni tanlang — uning kunlik ish vaqti shu yerda chiziladi.';
  $('chart1Legend').innerHTML = oneClient
    ? statusLegend + `<span><i style="background:#2ecc71;opacity:.28"></i> odatiy oraliq</span>`
    : '';

  if (oneClient) {
    drawDayChart($('chart1'), visible);
  } else {
    const svg = $('chart1');
    svg.setAttribute('height', 56);
    svg.appendChild(el('text', { x: 12, y: 32 }, 'Xodimni tanlang'));
  }

  // 2-grafik — qo'shimcha kesim
  if (oneClient) {
    $('chart2Title').textContent = 'Haftalik odatiy rejim';
    $('chart2Hint').textContent = 'X o\'qi — hafta kunlari, Y o\'qi — sutka soatlari. '
      + 'Yashil yo\'lak — o\'rganilgan odatiy oraliq, nuqtalar — haqiqiy kunlar '
      + '(ko\'k: kelish, sariq: ketish).';
    $('chart2Legend').innerHTML = `
      <span><i style="background:#2ecc71;opacity:.28"></i> odatiy kelish/ketish oralig'i</span>
      <span><i style="background:#7dd3fc;border-radius:50%"></i> kelgan vaqti</span>
      <span><i style="background:#fdba74;border-radius:50%"></i> ketgan vaqti</span>`;
    drawWeeklyProfile($('chart2'), visible);
  } else {
    $('chart2Title').textContent = 'Umumiy manzara';
    $('chart2Hint').textContent = 'Qatorlar — xodimlar, ustunlar — kunlar. '
      + 'Har katak rangi o\'sha kunning holati, bo\'sh katak — faollik qayd etilmagan.';
    $('chart2Legend').innerHTML = statusLegend;
    drawMatrix($('chart2'), visible);
  }
}

/** ASOSIY grafik: X o'qi kunlar, Y o'qi sutka soatlari (00:00 pastda, 24:00 tepada) */
function drawDayChart(svg, visible) {
  const days = [...visible].sort((a, b) => a.date.localeCompare(b.date));
  const colW = Math.max(18, Math.min(46, Math.floor(900 / Math.max(1, days.length))));
  const pad = { l: 54, r: 16, t: 12, b: 58 };
  const W = Math.max(560, pad.l + days.length * colW + pad.r);
  const H = 420;
  const plotH = H - pad.t - pad.b;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('height', H);

  const y = (mins) => pad.t + plotH - (mins / 1440) * plotH;
  const cx = (i) => pad.l + i * colW + colW / 2;

  // Soat to'ri va yorliqlari
  for (let hour = 0; hour <= 24; hour += 2) {
    const yy = y(hour * 60);
    svg.appendChild(el('line', {
      x1: pad.l, y1: yy, x2: W - pad.r, y2: yy, class: 'grid',
      opacity: hour % 6 === 0 ? 1 : 0.45,
    }));
    svg.appendChild(el('text', { x: pad.l - 8, y: yy + 4, 'text-anchor': 'end' },
      String(hour).padStart(2, '0') + ':00'));
  }

  const labelStep = Math.ceil(days.length / 26);

  days.forEach((r, i) => {
    const c = compare(r);
    const bw = Math.min(20, colW * 0.56);

    // Dam olish kunlari fonini ajratamiz
    if (r.dayOfWeek === 'Saturday' || r.dayOfWeek === 'Sunday') {
      svg.appendChild(el('rect', {
        x: pad.l + i * colW, y: pad.t, width: colW, height: plotH,
        fill: '#ffffff', opacity: 0.03,
      }));
    }

    // Odatiy kelish/ketish yo'laklari (mean ± std)
    if (c) {
      for (const [mean, std] of [[c.usualStart, c.stdStart], [c.usualFinish, c.stdFinish]]) {
        if (mean === null || !std) continue;
        const top = y(Math.min(1440, mean + std));
        const bot = y(Math.max(0, mean - std));
        svg.appendChild(el('rect', {
          x: cx(i) - bw / 2 - 4, y: top, width: bw + 8, height: Math.max(2, bot - top),
          fill: '#2ecc71', opacity: 0.22, rx: 2,
        }));
      }
    }

    // Kun ustuni: kelishdan ketishgacha
    const sy = y(hhmmssToMinutes(r.start));
    const fy = y(hhmmssToMinutes(r.finish));
    const bar = el('rect', {
      x: cx(i) - bw / 2, y: fy, width: bw, height: Math.max(3, sy - fy),
      fill: STATUS[r.status].color, opacity: 0.92, rx: 3,
    });
    bar.appendChild(el('title', {},
      `${humanDate(r.date, r.dayOfWeek)}\n` +
      `Keldi ${r.start.slice(0, 5)} · Ketdi ${r.finish.slice(0, 5)} (${humanMinutes(r.durationMin)})\n` +
      `${STATUS[r.status].label}` +
      (c ? `\nOdatda: ${minutesToHHMM(c.usualStart)} – ${minutesToHHMM(c.usualFinish)}` : '')));
    svg.appendChild(bar);

    // Sana yorlig'i (dam olish kunlari qizil)
    if (i % labelStep === 0) {
      const weekend = r.dayOfWeek === 'Saturday' || r.dayOfWeek === 'Sunday';
      const label = el('text', {
        x: cx(i), y: H - 18, 'text-anchor': 'end',
        transform: `rotate(-50 ${cx(i)} ${H - 18})`,
      }, r.date.slice(5));
      if (weekend) label.setAttribute('fill', '#e74c3c');
      svg.appendChild(label);
    }
  });
}

/** Barcha xodimlar: xodim x kun matritsasi (sanoat standarti "umumiy manzara") */
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
        fill: row ? STATUS[row.status].color : '#1e2632',
        opacity: row ? 0.9 : 1,
      });
      if (row) {
        rect.appendChild(el('title', {}, `${name}\n${humanDate(row.date, row.dayOfWeek)}\n` +
          `${row.start.slice(0, 5)} – ${row.finish.slice(0, 5)}\n${STATUS[row.status].label}`));
      }
      svg.appendChild(rect);
    });
  });
}

/** Bitta xodim: 7 hafta kuni bo'yicha odatiy rejim + haqiqiy kunlar */
function drawWeeklyProfile(svg, visible) {
  const ORDER = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
  const weeks = baselines[$('client').value] || {};
  const byDay = {};
  for (const r of visible) (byDay[r.dayOfWeek] = byDay[r.dayOfWeek] || []).push(r);

  const W = 780, H = 330;
  const pad = { l: 52, r: 14, t: 12, b: 44 };
  const plotW = W - pad.l - pad.r, plotH = H - pad.t - pad.b;
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('height', H);

  const y = (mins) => pad.t + plotH - (mins / 1440) * plotH;
  const colW = plotW / 7;
  const cx = (i) => pad.l + i * colW + colW / 2;

  for (let hour = 0; hour <= 24; hour += 3) {
    const yy = y(hour * 60);
    svg.appendChild(el('line', { x1: pad.l, y1: yy, x2: W - pad.r, y2: yy, class: 'grid' }));
    svg.appendChild(el('text', { x: pad.l - 8, y: yy + 4, 'text-anchor': 'end' },
      String(hour).padStart(2, '0') + ':00'));
  }

  ORDER.forEach((wd, i) => {
    const w = weeks[wd];
    const days = byDay[wd] || [];
    const bw = Math.min(52, colW * 0.62);

    svg.appendChild(el('text', { x: cx(i), y: H - 24, 'text-anchor': 'middle' },
      WEEKDAY_UZ[wd].slice(0, 3)));

    if (w && w.meanStart !== null && w.meanStart !== undefined) {
      // Odatiy ish oynasi: kelishdan ketishgacha
      svg.appendChild(el('rect', {
        x: cx(i) - bw / 2, y: y(w.meanFinish), width: bw,
        height: Math.max(2, y(w.meanStart) - y(w.meanFinish)),
        fill: '#2ecc71', opacity: 0.1, rx: 3,
      }));
      // mean ± std yo'laklari
      for (const [mean, std] of [[w.meanStart, w.stdStart], [w.meanFinish, w.stdFinish]]) {
        if (!std) continue;
        const top = y(Math.min(1440, mean + std)), bot = y(Math.max(0, mean - std));
        svg.appendChild(el('rect', {
          x: cx(i) - bw / 2, y: top, width: bw, height: Math.max(2, bot - top),
          fill: '#2ecc71', opacity: 0.3, rx: 3,
        })).appendChild(el('title', {}, `${WEEKDAY_UZ[wd]}: odatda ${minutesToHHMM(mean)} ` +
          `(±${humanMinutes(std)}), ${w.count} kun asosida`));
      }
      svg.appendChild(el('text', { x: cx(i), y: y(w.meanStart) + 14, 'text-anchor': 'middle' },
        minutesToHHMM(w.meanStart)));
      svg.appendChild(el('text', { x: cx(i), y: y(w.meanFinish) - 6, 'text-anchor': 'middle' },
        minutesToHHMM(w.meanFinish)));
    } else if (days.length) {
      svg.appendChild(el('text', { x: cx(i), y: pad.t + plotH / 2, 'text-anchor': 'middle' },
        'tarix kam'));
    }

    // Haqiqiy kunlar — nuqtalar
    days.forEach((r, k) => {
      const jitter = (k - (days.length - 1) / 2) * Math.min(7, bw / Math.max(1, days.length));
      for (const [val, color] of [[r.start, '#7dd3fc'], [r.finish, '#fdba74']]) {
        const dot = el('circle', {
          cx: cx(i) + jitter, cy: y(hhmmssToMinutes(val)), r: 3.4,
          fill: color, stroke: STATUS[r.status].color, 'stroke-width': 1.4,
        });
        dot.appendChild(el('title', {}, `${humanDate(r.date, r.dayOfWeek)}\n` +
          `${r.start.slice(0, 5)} – ${r.finish.slice(0, 5)}\n${STATUS[r.status].label}`));
        svg.appendChild(dot);
      }
    });
  });
}

function renderTable(visible) {
  const tbody = $('table').querySelector('tbody');
  $('tableInfo').textContent = `— ${visible.length} ta`;

  if (!visible.length) {
    tbody.innerHTML = '<tr><td colspan="9" class="empty">Ko\'rsatadigan kun yo\'q</td></tr>';
    return;
  }

  const diffCell = (diff, earlyWord, lateWord) => {
    if (diff === null) return '<td class="dim">—</td>';
    if (Math.abs(diff) < 5) return '<td class="dim">deyarli bir xil</td>';
    const early = diff > 0;
    return `<td class="${early ? 'diff-early' : 'diff-late'}">${humanMinutes(diff)} ${early ? earlyWord : lateWord}</td>`;
  };

  tbody.innerHTML = [...visible]
    .sort((a, b) => b.date.localeCompare(a.date) || (a.hostname || '').localeCompare(b.hostname || ''))
    .map((r) => {
      const c = compare(r);
      const s = STATUS[r.status];
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
        <td><span class="badge ${s.css}">${s.label}</span></td>
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
    $('retrainStatus').textContent = {
      collecting: "Ma'lumot yig'ilmoqda...",
      training: "Odatiy jadvallar hisoblanmoqda...",
      finished: 'Yangilandi ✓',
      error: 'Xato: ' + (r.error || '').slice(0, 60),
    }[r.stage] || '';

    if (r.status === 'finished' || r.status === 'error') {
      clearInterval(retrainTimer);
      $('retrain').disabled = false;
      if (r.status === 'finished') { loadBaselines().then(loadResults); loadClients(); }
    }
  }, 5000);
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
  $('from').value = iso(new Date(last.getTime() - 29 * 86400000));
}

async function init() {
  $('refresh').addEventListener('click', loadResults);
  $('retrain').addEventListener('click', startRetrain);
  for (const id of ['from', 'to', 'client']) $(id).addEventListener('change', loadResults);
  $('onlyIssues').addEventListener('change', render);

  await loadHealth();
  await setDefaultRange();
  await Promise.all([loadBaselines(), loadClients()]);
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

  setInterval(async () => { await loadHealth(); await loadResults(); }, 5 * 60 * 1000);
}

init();
