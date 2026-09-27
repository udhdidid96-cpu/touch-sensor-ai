"""The repository root, put on sys.path for scripts run from scripts/.

``python scripts/<name>.py`` puts only scripts/ on sys.path. A script that imports main.py and
also needs the root's path imports ROOT from here, above ``import main``.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
