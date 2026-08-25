@echo off
REM ===========================================================================
REM  Bridge a USB sensor board on this machine to a cloud instance.
REM  Frames go up as {"raw_frame": [...]}; the server classifies and sends the
REM  result back. Nothing is classified here.
REM
REM  For a LOCAL terminal readout instead, use:  python main.py --monitor COM5
REM  (that replaced live_monitor.py).
REM ===========================================================================
chcp 65001 >nul
title Arduino touch sensor -> cloud bridge
cd /d "%~dp0"
python -u stream_to_cloud.py %*
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   [ERROR] Could not start / เริ่มโปรแกรมไม่ได้ - ตรวจสอบว่ามี python และ pyserial
    pause
)
