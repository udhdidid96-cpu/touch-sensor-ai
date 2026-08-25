@echo off
REM ===========================================================================
REM  Project2 - start the dashboard on this machine (loopback only).
REM
REM  This file REPLACES Start_Web_App.bat, which was the same script with Thai
REM  error messages. Four launchers were doing two jobs; run cleanup.bat to move
REM  the duplicates into _archive\.
REM
REM  Loopback means 127.0.0.1 only. To hand the link to someone else use
REM  start_public.bat, which generates an access key - main.py refuses to serve
REM  a non-loopback address without one, on purpose.
REM ===========================================================================
chcp 65001 >nul
title Smart Extubation Early Warning - local dashboard
cd /d "%~dp0"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   [ERROR] Python not found on PATH / ไม่พบ Python ในระบบ
    echo           Install Python 3.9+ from https://www.python.org/
    echo.
    pause
    exit /b 1
)

echo.
echo   Installing/checking dependencies ...
python -m pip install -q -r requirements.txt

echo.
echo   Starting. First run trains the model (~30 s); after that it loads the
echo   cached one from Data\trained_model.joblib.
echo.
python -u main.py
pause
