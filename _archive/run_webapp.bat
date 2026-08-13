@echo off
REM ---------------------------------------------------------------------------
REM  The dashboard is served BY main.py, not opened as a file.
REM
REM  This script used to do `start index.html` (a file:// page) and then run
REM  `python -m http.server 3000`. Neither can talk to the API: a file:// page
REM  resolves /api/... against the filesystem, and a page on :3000 is blocked
REM  by the same-origin policy against the API on :8081. The dashboard silently
REM  showed nothing real either way.
REM ---------------------------------------------------------------------------
echo.
echo   The dashboard is served by main.py. Run start.bat instead, or:
echo.
echo       cd ..
echo       python main.py
echo.
echo   then open http://127.0.0.1:8081
echo.
pause
