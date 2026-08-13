import sys
import os

with open(r"C:\Users\denpo\OneDrive\Desktop\Project2\main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"Total lines in main.py: {len(lines)}")

print("\n--- Searching for @app decorators ---")
for i, line in enumerate(lines):
    if "@app." in line:
        print(f"Line {i+1}: {line.strip()}")

print("\n--- Searching for predict, pdf, tele-nursing, bed in endpoint URLs ---")
for i, line in enumerate(lines):
    if any(k in line.lower() for k in ["predict", "pdf", "tele-nursing", "bed", "audit-report"]):
        if "@app" in line or "def " in line or 'path' in line:
            print(f"Line {i+1}: {line.strip()}")
