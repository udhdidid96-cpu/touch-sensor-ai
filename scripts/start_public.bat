@echo off
REM ===========================================================================
REM  Serve the dashboard through a temporary public HTTPS tunnel.
REM
REM  share_public.py generates an access key and prints a link containing it.
REM  main.py refuses a non-loopback host without that key, on purpose.
REM
REM  Moved into scripts\ on 2026-08-21. The only change is the ".." below:
REM  %~dp0 is this file's own folder, which is now one level down, and main.py
REM  and share_public.py still live at the project root.
REM ===========================================================================
chcp 65001 >nul
title Smart Extubation Early Warning - public link
cd /d "%~dp0.."

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
