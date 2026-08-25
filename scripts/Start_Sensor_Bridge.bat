@echo off
REM ===========================================================================
REM  Bridge an Arduino touch-sensor board to the dashboard.
REM  Moved into scripts\ on 2026-08-21; "cd /d %~dp0.." keeps the working
REM  directory at the project root, where stream_to_cloud.py lives.
REM ===========================================================================
chcp 65001 >nul
title Arduino touch sensor -^> cloud bridge
cd /d "%~dp0.."

python -u stream_to_cloud.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   [ERROR] Could not start / เริ่มโปรแกรมไม่ได้ - ตรวจสอบว่ามี python และ pyserial
    pause
)
