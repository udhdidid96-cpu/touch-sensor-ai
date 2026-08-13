@echo off
title ICU Extubation AI Early Warning System - National Competition Edition
echo =========================================================================
echo   ICU Extubation Early Warning System - Universal Launcher
echo =========================================================================
echo.

cd /d "%~dp0"

echo [1/3] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    echo Please install Python 3.9+ from https://www.python.org/
    pause
    exit /b 1
)

echo [2/3] Installing dependencies from requirements.txt...
python -m pip install -q -r requirements.txt

echo [3/3] Launching Clinical Warning Center Web Dashboard...
echo.
echo Dashboard URL: http://localhost:8081
echo Press Ctrl+C to stop the server.
echo.

python -u main.py

pause
