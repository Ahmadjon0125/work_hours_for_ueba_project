import json
from datetime import datetime, timedelta
from pathlib import Path
from pipeline.utils import RESULTS_FILE

def generate_dashboard(html_path="dashboard.html"):
    print(f"Starting Stage 3: Visualization...")
    
    if not RESULTS_FILE.exists():
        print(f"Error: Results file {RESULTS_FILE} not found. Run processor first.")
        return

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    users = data.get("users", [])
    if not users:
        print("No user data found in JSON.")
        return
    # Get all dates in the 60-day window (Calendar approach)
    # We get the window from the meta data
    window_days = data['meta'].get('windowDays', 60)
    generated_at = datetime.fromisoformat(data['meta'].get('generatedAt', datetime.now().isoformat())).date()
    
    sorted_dates = []
    for i in range(window_days, -1, -1):
        date_val = generated_at - timedelta(days=i)
        sorted_dates.append(date_val.isoformat())

    html_parts = []
    html_parts.append("<!DOCTYPE html><html lang='en'><head>")
    html_parts.append("<meta charset='UTF-8'><title>UEBA Working Hours Dashboard</title>")
    html_parts.append("<style>")
    html_parts.append("body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #f4f7f6; margin: 20px; }")
    html_parts.append("h1 { color: #333; text-align: center; }")
    html_parts.append(".meta { text-align: center; margin-bottom: 20px; color: #666; font-size: 0.9em; }")
    html_parts.append(".table-container { overflow-x: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }")
    html_parts.append("table { border-collapse: collapse; width: 100%; min-width: 1000px; }")
    html_parts.append("th, td { border: 1px solid #ddd; padding: 8px; text-align: center; font-size: 12px; }")
    html_parts.append("th { background-color: #f2f2f2; position: sticky; top: 0; }")
    html_parts.append(".user-col { text-align: left; font-weight: bold; position: sticky; left: 0; background: white; z-index: 1; min-width: 180px; }")
    html_parts.append(".red { background-color: #ff4d4d; color: white; cursor: help; }")
    html_parts.append(".orange { background-color: #ffa500; color: white; cursor: help; }")
    html_parts.append(".yellow { background-color: #ffff99; color: #333; cursor: help; }")
    html_parts.append(".green { background-color: #90ee90; color: #333; cursor: help; }")
    html_parts.append(".empty { background-color: #f9f9f9; color: #ccc; }")
    html_parts.append(".legend { display: flex; justify-content: center; gap: 20px; margin-bottom: 20px; }")
    html_parts.append(".legend-item { display: flex; align-items: center; gap: 5px; font-size: 0.9em; }")
    html_parts.append(".box { width: 15px; height: 15px; border: 1px solid #999; border-radius: 3px; }")
    html_parts.append("</style></head><body>")
    
    html_parts.append("<h1>UEBA Working Hours Heatmap</h1>")
    meta_text = f"Generated: {data['meta'].get('generatedAt', 'N/A')} | Window: {data['meta'].get('windowDays', 'N/A')} days"
    html_parts.append(f"<div class='meta'>{meta_text}</div>")
    
    html_parts.append("<div class='legend'>")
    html_parts.append("<div class='legend-item'><div class='box red'></div> Severe</div>")
    html_parts.append("<div class='legend-item'><div class='box orange'></div> Anomaly</div>")
    html_parts.append("<div class='legend-item'><div class='box yellow'></div> Watch</div>")
    html_parts.append("<div class='legend-item'><div class='box green'></div> Normal</div>")
    html_parts.append("<div class='legend-item'><div class='box empty'></div> No Activity</div>")
    html_parts.append("</div>")
    
    html_parts.append("<div class='table-container'><table><thead><tr>")
    html_parts.append("<th class='user-col'>User (Username)</th>")
    for d in sorted_dates:
        html_parts.append(f"<th>{d}</th>")
    html_parts.append("</tr></thead><tbody>")
    
    for u in users:
        display_name = u['username']
        day_map = {day["date"]: day for day in u.get("daily", [])}
        html_parts.append(f"<tr><td class='user-col'>{display_name}</td>")
        for d in sorted_dates:
            day_data = day_map.get(d)
            if day_data:
                color = day_data["color"]
                tooltip = f"Hours: {day_data['hours']}h | Start: {day_data['start']} | Finish: {day_data['finish']} | Status: {day_data['status']}"
                html_parts.append(f"<td class='{color}' title='{tooltip}'>●</td>")
            else:
                html_parts.append("<td class='empty'>-</td>")
        html_parts.append("</tr>")
        
    html_parts.append("</tbody></table></div></body></html>")
    
    final_html = "".join(html_parts)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(final_html)
    
    print(f"Stage 3 Complete. Dashboard generated at: {html_path}")

if __name__ == "__main__":
    generate_dashboard()
