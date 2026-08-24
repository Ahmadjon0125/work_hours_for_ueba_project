"""
Bosqich 3 (vizualizatsiya): results.json -> dashboard.html

Har bir katakda ikki nuqta: yuqori = start Z-score, past = finish Z-score.
Ranglar Z-score'ga qo'llanadi (get_status_color). z=None -> kulrang (insufficient).
"""
import html
import json
from datetime import datetime, timedelta

from .utils import BASE_DIR, RESULTS_FILE, get_status_color

CSS = """
body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 20px; }
h1 { color: #333; text-align: center; }
.meta { text-align: center; margin-bottom: 15px; color: #666; font-size: 0.9em; }
.table-container { overflow-x: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
table { border-collapse: collapse; width: 100%; min-width: 1000px; }
th, td { border: 1px solid #ddd; padding: 6px; text-align: center; font-size: 12px; }
th { background-color: #f2f2f2; position: sticky; top: 0; }
.user-col { text-align: left; font-weight: bold; position: sticky; left: 0; background: white; z-index: 1; min-width: 180px; }
td.cell { vertical-align: middle; background: white; cursor: help; }
.dot { width: 9px; height: 9px; border-radius: 50%; margin: 2px auto; }
.red { background-color: #ff4d4d; }
.orange { background-color: #ffa500; }
.yellow { background-color: #ffe14d; }
.green { background-color: #4caf50; }
.gray { background-color: #d0d0d0; }
.empty { background-color: #f9f9f9; color: #ccc; }
.legend { display: flex; justify-content: center; gap: 20px; margin-bottom: 10px; flex-wrap: wrap; }
.legend-item { display: flex; align-items: center; gap: 5px; font-size: 0.9em; }
.box { width: 15px; height: 15px; border: 1px solid #999; border-radius: 3px; }
"""

def generate_dashboard(html_path=None):
    print("Starting Stage 3 (Dashboard): generating dashboard...")

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

    parts.append("<div class='legend'>")
    for color, label in [
        ("red", "Severe"), ("orange", "Anomaly"), ("yellow", "Watch"),
        ("green", "Normal"), ("gray", "Insufficient"),
    ]:
        parts.append(
            f"<div class='legend-item'><div class='box {color}'></div> {label}</div>"
        )
    parts.append("</div>")
    parts.append("<div class='meta'>Yuqori nuqta: start Z-score | Past nuqta: finish Z-score</div>")

    parts.append("<div class='table-container'><table><thead><tr>")
    parts.append("<th class='user-col'>User (Username)</th>")
    for d in dates:
        parts.append(f"<th>{d}</th>")
    parts.append("</tr></thead><tbody>")

    for u in users:
        day_map = {day["date"]: day for day in u.get("days", [])}
        parts.append(
            f"<tr><td class='user-col'>{html.escape(u['username'])}</td>"
        )
        for d in dates:
            day = day_map.get(d)
            if not day:
                parts.append("<td class='empty'>-</td>")
                continue

            _, color_start = get_status_color(day["zStart"])
            _, color_finish = get_status_color(day["zFinish"])
            zs = (
                f"{day['zStart']:+.3f}" if day["zStart"] is not None else "n/a"
            )
            zf = (
                f"{day['zFinish']:+.3f}" if day["zFinish"] is not None else "n/a"
            )
            tooltip = html.escape(f"Start {day['start']} (z={zs}) | Finish {day['finish']} (z={zf}) | Duration {day['durationMin']} min")
            parts.append(
                f"<td class='cell' title=\"{tooltip}\">"
                f"<div class='dot {color_start}'></div>"
                f"<div class='dot {color_finish}'></div></td>"
            )
        parts.append("</tr>")

    parts.append("</tbody></table></div></body></html>")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write("".join(parts))

    print(f"Stage 3 (Dashboard) Complete. Dashboard generated at: {html_path}")

if __name__ == "__main__":
    generate_dashboard()
