@echo off
REM ===========================================================================
REM  Creates BOTH desktop shortcuts - local dashboard and public link.
REM  Replaces Create_Public_Desktop_Shortcut.bat, which differed only in which
REM  one of the two it made.
REM ===========================================================================
chcp 65001 >nul
title Create desktop shortcuts
cd /d "%~dp0"
set "SCRIPT_DIR=%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ws = New-Object -ComObject WScript.Shell;" ^
  "$desktop = [System.Environment]::GetFolderPath('Desktop');" ^
  "$a = $ws.CreateShortcut($desktop + '\Smart_Extubation_Local.lnk');" ^
  "$a.TargetPath = '%SCRIPT_DIR%start.bat'; $a.WorkingDirectory = '%SCRIPT_DIR%';" ^
  "$a.Description = 'Smart Extubation dashboard - this machine only'; $a.Save();" ^
  "$b = $ws.CreateShortcut($desktop + '\Smart_Extubation_Public_Link.lnk');" ^
  "$b.TargetPath = '%SCRIPT_DIR%start_public.bat'; $b.WorkingDirectory = '%SCRIPT_DIR%';" ^
  "$b.Description = 'Smart Extubation dashboard - temporary public URL with access key'; $b.Save()"

if %errorlevel% equ 0 (
    echo   [OK] Created: Smart_Extubation_Local.lnk and Smart_Extubation_Public_Link.lnk
) else (
    echo   [ERROR] Could not create the shortcuts.
)
pause
