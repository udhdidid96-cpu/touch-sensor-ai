@echo off
REM ===========================================================================
REM  Deploy to Google Cloud Run. Double-click this.
REM
REM  All it does is run scripts\deploy_google.ps1 - one implementation, not two.
REM  This stub stays at the project root because it is a thing you double-click;
REM  the logic moved down into scripts\ with everything else on 2026-08-21.
REM ===========================================================================
chcp 65001 >nul
title Deploy to Google Cloud Run
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\deploy_google.ps1"
echo.
pause
