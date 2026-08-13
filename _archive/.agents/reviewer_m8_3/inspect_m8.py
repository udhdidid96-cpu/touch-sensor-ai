import re
import sys
import os

main_path = r"C:\Users\denpo\OneDrive\Desktop\Project2\main.py"
with open(main_path, "r", encoding="utf-8") as f:
    code = f.read()

checks = {
    "Torii Red (#D7000F)": "#D7000F" in code or "#d7000f" in code,
    "Imperial Gold (#FFD700)": "#FFD700" in code or "#ffd700" in code,
    "Indigo Navy (#0F172A)": "#0F172A" in code or "#0f172a" in code,
    "Indigo Navy (#1E293B)": "#1E293B" in code or "#1e293b" in code,
    "English text lang='en'": 'lang="en"' in code or "lang='en'" in code,
    "25-Node 90x120mm Patch Visualizer": "25-Node" in code or "90x120" in code or "90 x 120" in code,
    "RBF Thin-Plate Interpolator": "RBF" in code or "thin-plate" in code.lower() or "thin_plate" in code.lower() or "thinplate" in code.lower(),
    "CPRI Gauge": "CPRI" in code,
    "Real-Time Chart.js Graph": "Chart" in code or "chart.js" in code.lower(),
    "8-Bed ICU Grid View": "8-Bed" in code or "Bed 1" in code or "8 Bed" in code or "icu" in code.lower(),
    "1-Click Printable PDF Audit Chart": "Printable" in code or "PDF" in code or "window.print" in code,
    "Tele-Nursing LINE/Telegram Panel": "LINE" in code and "Telegram" in code,
    "USB Serial Controller": "Serial" in code or "COM" in code,
    "Interactive Competition Demo Toolbar": "Demo" in code or "Scenario" in code,
    "Scenario: Normal": "Normal" in code,
    "Scenario: Touch": "Touch" in code,
    "Scenario: Peel": "Peel" in code,
    "Scenario: Extubation Alarm": "Extubation" in code,
    "Audio Siren 960Hz": "960" in code,
    "Audio Siren 770Hz": "770" in code,
}

print("=== CHECK RESULTS ===")
for key, val in checks.items():
    print(f"[{'PASS' if val else 'FAIL'}] {key}")
