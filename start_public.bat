@echo off
REM ===========================================================================
REM  Project2 - expose the dashboard on a temporary public HTTPS URL.
REM
REM  This file REPLACES Start_Public_Web_App.bat (same script, Thai messages).
REM
REM  share_public.py generates an access key by default and prints the link with
REM  the key already in it. Do not remove that: the API serves every recording
REM  under Data\, accepts uploads, accepts writes to the audit trail, and can
REM  open a serial port on THIS machine.
REM ===========================================================================
chcp 65001 >nul
title Smart Extubation Early Warning - public link
cd /d "%~dp0"

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo   [ERROR] Python not found on PATH / ไม่พบ Python ในระบบ
    echo.
    pause
    exit /b 1
)

python -u share_public.py
pause
