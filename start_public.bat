@echo off
title International Competition - Public Cloud Web Launcher
echo =========================================================================
echo   ICU Extubation Early Warning System - Public Cloud HTTPS Launcher
echo =========================================================================
echo.

cd /d "%~dp0"

echo [1/2] Checking Python installation...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    pause
    exit /b 1
)

echo [2/2] Launching Public Tunnel & Web Application...
python -u share_public.py

pause
