"""
Bosqich 3 (vizualizatsiya): results.json + baseline.json -> dashboard.html

Ustunli (bar) diagramma:
  - Userlar tanlanadi (dropdown) — tanlangan user grafigi chiqadi
  - X o'q: BARCHA kalendar kunlar ketma-ket. Harakat yo'q kunlar bo'sh turadi,
    lekin o'z o'rnini bosib turadi (grid chizig'i + sana belgisi).
    Dam olish kunlari (sh+ya) alohida fonda belgilanadi.
  - Y o'q: kun soatlari (00:00 - 24:00)
  - Har bir kun uchun:
      * Oq bar = shu kun ish vaqti (start -> finish)
      * YASHIL = baseline o'rtacha vaqti (kelish/ketish bandi)
      * Sariq->yashil o'rgash = real vaqt bilan baseline O'RТАЧASI orasidagi CHETLANISH:
          - yashil uchi = o'rtacha (meanStart/meanFinish), sariq uchi = real vaqt
          - o'gish kattaligi = o'rgashning uzunligi (ertaga va kechgaga bir xil)
      * Kelish/ketish nuqtalarida alohida belgilar — rangi |z| ga bog'liq
      * Baseline yetarli bo'lmasa: kulrang ustun
"""
import html
import json
from datetime import datetime, timedelta

from .utils import BASE_DIR, BASELINE_FILE, RESULTS_FILE, minutes_to_hhmm

# --- Diagramma geometriyasi ---
BASE_PLOT_W = 1180
MIN_SLOT_W = 22          # kun sloti kengligi (px) — hamma sanalar ko'rinadigan qilib
PLOT_H = 520
M_LEFT = 56
M_RIGHT = 16
M_TOP = 24
M_BOT = 78
DAY_MIN = 24 * 60

YELLOW = (255, 193, 7)         # #ffc107 — real vaqt (chetlanish)
GREEN = (56, 142, 60)          # #388e3c — baseline o'rtacha
GRAY_BAR = "#cfd8dc"
WHITE_BAR = "#ffffff"
BAND_START_FILL = "#e8f5e9"
BAND_START_STROKE = "#81c784"
BAND_FINISH_FILL = "#c8e6c9"
BAND_FINISH_STROKE = "#66bb6a"
WEEKEND_FILL = "#f5f7f9"
WEEKEND_LABEL = "#c0392b"
GRID_LINE = "#e4e9ee"

CSS = """
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 20px; }
h1 { color: #333; text-align: center; }
.meta { text-align: center; margin-bottom: 15px; color: #666; font-size: 0.9em; }
.controls { text-align: center; margin-bottom: 15px; font-size: 14px; color: #333; }
.controls select { padding: 6px 14px; font-size: 14px; border-radius: 6px; border: 1px solid #b8c4cc; background: white; min-width: 300px; }
.legend { display: flex; justify-content: center; gap: 18px; margin-bottom: 15px; flex-wrap: wrap; font-size: 0.8em; color: #445; }
.legend-item { display: flex; align-items: center; gap: 6px; }
.swatch { width: 16px; height: 16px; border-radius: 3px; border: 1px solid #99a5b1; }
.swatch.white { background: #ffffff; border-color: #8a97a5; }
.swatch.dev { background: linear-gradient(to bottom, #ffc107, #388e3c); border-color: #f9a825; }
.swatch.gray { background: #cfd8dc; }
.swatch.band-start { background: #e8f5e9; border: 1px dashed #81c784; }
.swatch.band-finish { background: #c8e6c9; border: 1px dashed #66bb6a; }
.swatch.marker { background: #ffc107; border-color: #f9a825; }
.swatch.weekend { background: #f5f7f9; border-color: #cfd8dc; }
.charts { background: white; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); padding: 16px; overflow-x: auto; }
.user-title { font-weight: bold; color: #333; padding: 4px 8px; }
.chart svg { display: block; margin: 0 auto; }
"""


def _parse_hms(s):
    """'HH:MM:SS' -> daqiqa (float)."""
    try:
        h, m, sec = s.split(":")
        return int(h) * 60 + int(m) + int(sec) / 60.0
    except Exception:
        return None


def _y(minutes):
    """daqiqa -> SVG y koordinata (00:00 pastda, 24:00 yuqorida)."""
    return M_TOP + PLOT_H * (1.0 - minutes / DAY_MIN)


def _mix(t):
    """Rang aralashuvi: t=0 -> sariq (real vaqt), t=1 -> yashil (baseline)."""
    t = min(max(t, 0.0), 1.0)
    r = int(round(YELLOW[0] + (GREEN[0] - YELLOW[0]) * t))
    g = int(round(YELLOW[1] + (GREEN[1] - YELLOW[1]) * t))
    b = int(round(YELLOW[2] + (GREEN[2] - YELLOW[2]) * t))
    return f"rgb({r},{g},{b})"


def _marker_color(z):
    """Kelish/ketish belgisi rangi: |z| katta bo'lsa sariq (chetlanish),
    |z| kichik bo'lsa yashil (baseline yaqin)."""
    if z is None:
        return "#b0bec5"
    return _mix(1.0 - min(abs(z) / 2.0, 1.0))


def _build_user_svg(ui, user, weeks, dates):
    days = {d["date"]: d for d in user.get("days", [])}
    n = len(dates)
    plot_w = max(BASE_PLOT_W, n * MIN_SLOT_W)
    slot = plot_w / n
    bar_w = max(slot * 0.55, 3.0)
    band_w = slot * 0.85
    svg_w = M_LEFT + plot_w + M_RIGHT
    svg_h = M_TOP + PLOT_H + M_BOT

    defs = []
    body = []

    # Dam olish kunlari foni + har bir kun uchun grid chizig'i (bo'sh kunlar ham ko'rinadi)
    for i, d in enumerate(dates):
        dt = datetime.fromisoformat(d)
        x0 = M_LEFT + slot * i
        if dt.weekday() >= 5:
            body.append(
                f'<rect x="{x0:.1f}" y="{M_TOP}" width="{slot:.1f}" height="{PLOT_H}" fill="{WEEKEND_FILL}"/>'
            )
        body.append(
            f'<line x1="{x0:.1f}" y1="{M_TOP}" x2="{x0:.1f}" y2="{M_TOP + PLOT_H}" '
            f'stroke="{GRID_LINE}" stroke-width="0.6"/>'
        )
    body.append(
        f'<line x1="{M_LEFT + plot_w:.1f}" y1="{M_TOP}" x2="{M_LEFT + plot_w:.1f}" '
        f'y2="{M_TOP + PLOT_H}" stroke="{GRID_LINE}" stroke-width="0.6"/>'
    )

    # Y o'q: soatlar bo'yicha grid (3 soatdan-bir)
    for h in range(0, 25, 3):
        y = _y(h * 60)
        body.append(f'<line x1="{M_LEFT}" y1="{y:.1f}" x2="{M_LEFT + plot_w:.1f}" y2="{y:.1f}" stroke="#e3e8ec"/>')
        body.append(f'<text x="{M_LEFT - 8}" y="{y + 3:.1f}" text-anchor="end" font-size="10" fill="#667">{h:02d}:00</text>')

    for i, d in enumerate(dates):
        dt = datetime.fromisoformat(d)
        xc = M_LEFT + slot * i + slot / 2

        # Sana belgisi: HAR BIR kun uchun (dam olish kunlari qizil)
        ylab = M_TOP + PLOT_H + 10
        lfill = WEEKEND_LABEL if dt.weekday() >= 5 else "#556"
        body.append(
            f'<text x="{xc:.1f}" y="{ylab:.1f}" '
            f'transform="rotate(90 {xc:.1f} {ylab:.1f})" font-size="8" fill="{lfill}">'
            f'{dt.strftime("%d.%m")}</text>'
        )

        day = days.get(d)
        if not day:
            continue  # bo'sh kun: o'rni bosib turgan, lekin bar yo'q

        start = _parse_hms(day["start"])
        finish = _parse_hms(day["finish"])
        if start is None or finish is None or finish < start:
            continue

        x = xc - bar_w / 2
        band = weeks.get(day["dayOfWeek"])
        if band and band.get("meanStart") is not None and band.get("meanFinish") is not None:
            ms, mf = band["meanStart"], band["meanFinish"]
            ss = band.get("stdStart") or 0.0
            sf = band.get("stdFinish") or 0.0
            band_s_lo = max(0.0, ms - ss)
            band_s_hi = min(float(DAY_MIN), ms + ss)
            band_f_lo = max(0.0, mf - sf)
            band_f_hi = min(float(DAY_MIN), mf + sf)
            band_txt = f"Kelish {minutes_to_hhmm(ms)} ±{ss:.0f}m | Ketish {minutes_to_hhmm(mf)} ±{sf:.0f}m"
            has_band = True
        else:
            band_s_lo = band_s_hi = band_f_lo = band_f_hi = None
            band_txt = "baseline yetarli emas"
            has_band = False

        zs = f"{day['zStart']:+.3f}" if day.get("zStart") is not None else "n/a"
        zf = f"{day['zFinish']:+.3f}" if day.get("zFinish") is not None else "n/a"
        title = html.escape(
            f"{dt.strftime('%d.%m')} {day['dayOfWeek']}\n"
            f"Start {day['start']} | Finish {day['finish']} | {day['durationMin']} min\n"
            f"zStart {zs} | zFinish {zf}\n"
            f"Baseline: {band_txt}"
        )

        parts = [f'<g><title>{title}</title>']

        if has_band:
            # Kelish bandi (apelsin) va ketish bandi (yashil) — alohida, alohida
            bx = xc - band_w / 2
            parts.append(
                f'<rect x="{bx:.1f}" y="{_y(band_s_hi):.1f}" width="{band_w:.1f}" '
                f'height="{max(_y(band_s_lo) - _y(band_s_hi), 1):.1f}" fill="{BAND_START_FILL}" '
                f'stroke="{BAND_START_STROKE}" stroke-width="0.6" stroke-dasharray="3 2"/>'
            )
            parts.append(
                f'<rect x="{bx:.1f}" y="{_y(band_f_hi):.1f}" width="{band_w:.1f}" '
                f'height="{max(_y(band_f_lo) - _y(band_f_hi), 1):.1f}" fill="{BAND_FINISH_FILL}" '
                f'stroke="{BAND_FINISH_STROKE}" stroke-width="0.6" stroke-dasharray="3 2"/>'
            )

        if not has_band:
            # Baseline yetarli emas -> kulrang ustun
            parts.append(
                f'<rect x="{x:.1f}" y="{_y(finish):.1f}" width="{bar_w:.1f}" '
                f'height="{max(_y(start) - _y(finish), 1):.1f}" fill="{GRAY_BAR}" '
                f'stroke="#9aa7b0" stroke-width="0.6" stroke-dasharray="3 2"/>'
            )
        else:
            # 1) Ish vaqti oraliqi — OQ bar (rangsiz)
            parts.append(
                f'<rect x="{x:.1f}" y="{_y(finish):.1f}" width="{bar_w:.1f}" '
                f'height="{max(_y(start) - _y(finish), 1):.1f}" fill="{WHITE_BAR}" '
                f'stroke="#b0bec5" stroke-width="0.6"/>'
            )

            # 2) Chetlanish barlari: baseline O'RТАЧА (yashil) <-> REAL VAQТ (sariq)
            #    Sariq uchi = real vaqt, yashil uchi = o'rtacha; oraliq o'rgash.
            #    O'gish kattaligi = o'rgashning uzunligi.
            dw = max(bar_w * 0.7, 3.0)
            dx = xc - dw / 2
            k = 0
            for real, mean in ((start, ms), (finish, mf)):
                if abs(real - mean) < 1.0:
                    continue  # chetlanish deyarli yo'q
                k += 1
                gid = f"g{ui}_{i}_{k}"
                lo, hi = min(real, mean), max(real, mean)
                top_green = (hi == mean)  # yashil uchi = baseline o'rtacha
                c_top = _mix(1.0 if top_green else 0.0)
                c_bot = _mix(0.0 if top_green else 1.0)
                defs.append(
                    f'<linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
                    f'<stop offset="0" stop-color="{c_top}"/>'
                    f'<stop offset="1" stop-color="{c_bot}"/>'
                    f'</linearGradient>'
                )
                parts.append(
                    f'<rect x="{dx:.1f}" y="{_y(hi):.1f}" width="{dw:.1f}" '
                    f'height="{max(_y(lo) - _y(hi), 1):.1f}" fill="url(#{gid})" '
                    f'stroke="#f9a825" stroke-width="0.5"/>'
                )

            # 3) Kelish va ketish belgilari — rangi |z| ga bog'liq
            mw = bar_w + 6
            mx = x - 3
            parts.append(
                f'<rect x="{mx:.1f}" y="{_y(start) - 2:.1f}" width="{mw:.1f}" height="4" rx="1.5" '
                f'fill="{_marker_color(day.get("zStart"))}" stroke="#ffffff" stroke-width="0.6"/>'
            )
            parts.append(
                f'<rect x="{mx:.1f}" y="{_y(finish) - 2:.1f}" width="{mw:.1f}" height="4" rx="1.5" '
                f'fill="{_marker_color(day.get("zFinish"))}" stroke="#ffffff" stroke-width="0.6"/>'
            )
        parts.append("</g>")
        body.extend(parts)

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{svg_w:.0f}" height="{svg_h:.0f}" style="background:#fff">']
    if defs:
        svg.append(f'<defs>{"".join(defs)}</defs>')
    svg.append("".join(body))
    svg.append(
        f'<line x1="{M_LEFT}" y1="{M_TOP + PLOT_H}" x2="{M_LEFT + plot_w:.1f}" y2="{M_TOP + PLOT_H}" stroke="#90a0ae"/>'
        f'<line x1="{M_LEFT}" y1="{M_TOP}" x2="{M_LEFT}" y2="{M_TOP + PLOT_H}" stroke="#90a0ae"/>'
    )
    svg.append(f'<text x="{M_LEFT + plot_w / 2:.0f}" y="{svg_h - 4:.0f}" text-anchor="middle" font-size="11" fill="#556">Kunlar (barcha kalendar kunlari)</text>')
    svg.append(f'<text transform="rotate(-90 14 {M_TOP + PLOT_H / 2:.0f})" x="14" y="{M_TOP + PLOT_H / 2:.0f}" text-anchor="middle" font-size="11" fill="#556">Soat</text>')
    svg.append("</svg>")
    return "".join(svg)


def generate_dashboard(html_path=None):
    print("Starting Stage 3 (Dashboard): generating bar-chart dashboard...")

    if html_path is None:
        html_path = BASE_DIR / "dashboard.html"
    if not RESULTS_FILE.exists():
        raise FileNotFoundError(
            f"Results file {RESULTS_FILE} not found. Run 'score' first."
        )

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    users = data.get("users", [])
    if not users:
        raise ValueError("No user data found in results.json.")

    # Baseline band'lar faqat O'QILADI
    baselines = {}
    if BASELINE_FILE.exists():
        with open(BASELINE_FILE, "r", encoding="utf-8") as f:
            baselines = json.load(f).get("baselines", {})

    meta = data.get("meta", {})
    eval_from = datetime.fromisoformat(meta["evalFrom"]).date()
    eval_to = datetime.fromisoformat(meta["evalTo"]).date()
    dates = [
        (eval_from + timedelta(days=i)).isoformat()
        for i in range((eval_to - eval_from).days + 1)
    ]

    parts = []
    parts.append("<!DOCTYPE html><html lang='en'><head>")
    parts.append("<meta charset='UTF-8'><title>UEBA Working Hours Dashboard</title>")
    parts.append(f"<style>{CSS}</style></head><body>")

    parts.append("<h1>UEBA Working Hours Dashboard</h1>")
    meta_text = (
        f"Generated: {meta.get('generatedAt', 'N/A')} | "
        f"Eval window: {meta.get('evalFrom', 'N/A')} &rarr; {meta.get('evalTo', 'N/A')} | "
        f"Baseline trained: {meta.get('baselineTrainedAt', 'N/A')}"
    )
    parts.append(f"<div class='meta'>{meta_text}</div>")

    # User tanlash
    parts.append("<div class='controls'>")
    parts.append("<label for='userSelect'>User tanlang: </label>")
    parts.append("<select id='userSelect' onchange='showUser(this.value)'>")
    for u in users:
        parts.append(
            f"<option value='{html.escape(u['clientId'], quote=True)}'>"
            f"{html.escape(u['username'])}</option>"
        )
    parts.append("</select>")
    parts.append("</div>")

    # Legend
    parts.append("<div class='legend'>")
    parts.append("<div class='legend-item'><span class='swatch white'></span> Ish vaqti oraliqi (oq, rangsiz)</div>")
    parts.append("<div class='legend-item'><span style='width:16px;height:16px;border-radius:3px;background:#ffc107;border:1px solid #f9a825'></span> Real kelish/ketish vaqti (sariq)</div>")
    parts.append("<div class='legend-item'><span style='width:16px;height:16px;border-radius:3px;background:#388e3c;border:1px solid #2e7d32'></span> Baseline o'rtacha vaqti (yashil)</div>")
    parts.append("<div class='legend-item'><span class='swatch dev'></span> Chetlanish — sariqdan yashilga o'rgash (uzoqlashgan sari o'rgash kengayadi)</div>")
    parts.append("<div class='legend-item'><span class='swatch marker'></span> Kelish/ketish belgisi (rangi |z| ga qarab: sariq&harr;yashil)</div>")
    parts.append("<div class='legend-item'><span class='swatch gray'></span> Baseline yetarli emas</div>")
    parts.append("<div class='legend-item'><span class='swatch weekend'></span> Dam olish kuni (sh/ya)</div>")
    parts.append("</div>")

    # Har user uchun alohida grafik (bir vaqtda bittasi ko'rinadi)
    parts.append("<div class='charts'>")
    for idx, u in enumerate(users):
        uid = u["clientId"]
        weeks = baselines.get(uid, {}).get("weeks", {})
        svg = _build_user_svg(idx, u, weeks, dates)
        display = "block" if idx == 0 else "none"
        active = len(u.get("days", []))
        parts.append(
            f"<div class='chart' data-uid='{html.escape(uid, quote=True)}' style='display:{display}'>"
            f"<div class='user-title'>{html.escape(u['username'])} — faol kunlar: {active}/{len(dates)}</div>"
            f"{svg}</div>"
        )
    parts.append("</div>")

    parts.append(
        "<script>"
        "function showUser(uid) {"
        "  document.querySelectorAll('.chart').forEach(function (el) {"
        "    el.style.display = (el.getAttribute('data-uid') === uid) ? 'block' : 'none';"
        "  });"
        "}"
        "</script>"
    )
    parts.append("</body></html>")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))

    print(f"Stage 3 (Dashboard) Complete. Dashboard generated at: {html_path}")


if __name__ == "__main__":
    generate_dashboard()
