@echo off
REM ===========================================================================
REM  Put two shortcuts on the desktop.
REM
REM  Moved into scripts\ on 2026-08-21, so the two targets now live in
REM  different places: start.bat stayed at the project root (it is the one you
REM  double-click daily), start_public.bat came down here. ROOT and HERE below
REM  keep that straight - pointing both at %~dp0 would have produced two
REM  shortcuts to files that are not there.
REM ===========================================================================
chcp 65001 >nul
title Create desktop shortcuts
cd /d "%~dp0.."

set "ROOT=%CD%\"
set "HERE=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desktop = [System.Environment]::GetFolderPath('Desktop');" ^
  "$a = $ws.CreateShortcut($desktop + '\Smart_Extubation_Local.lnk');" ^
  "$a.TargetPath = '%ROOT%start.bat'; $a.WorkingDirectory = '%ROOT%';" ^
  "$a.Description = 'Smart Extubation dashboard - this machine only'; $a.Save();" ^
  "$b = $ws.CreateShortcut($desktop + '\Smart_Extubation_Public_Link.lnk');" ^
  "$b.TargetPath = '%HERE%start_public.bat'; $b.WorkingDirectory = '%ROOT%';" ^
  "$b.Description = 'Smart Extubation dashboard - temporary public URL with access key'; $b.Save()"

if %errorlevel% equ 0 (
    echo   [OK] Created: Smart_Extubation_Local.lnk and Smart_Extubation_Public_Link.lnk
) else (
    echo   [ERROR] Could not create the shortcuts.
)
pause
