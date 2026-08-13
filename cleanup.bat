@echo off
REM ===========================================================================
REM  Project2 - one-time tidy up
REM
REM  Everything below has been MERGED INTO README.md or SUPERSEDED. This script
REM  MOVES it into _archive\ - nothing is deleted, so if you find something
REM  missing it is still there. Once you are happy, delete _archive\ by hand.
REM
REM  Run once by double-clicking, then delete this file too.
REM ===========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo.
echo   Project2 cleanup - moving superseded files into _archive\
echo   ---------------------------------------------------------------------
echo.

if not exist "_archive"      mkdir "_archive"
if not exist "_archive\docs" mkdir "_archive\docs"

set MOVED=0

REM --- documentation now merged into README.md ------------------------------
for %%F in (
    "ACTION_PLAN.md"
    "CLAUDE_LOOPING_ENGINEERING_PROMPT.md"
    "CLAUDE_LOOPING_ENGINEERING_V2.md"
    "CLAUDE_WHITE_PAPER_DOCUMENTATION.md"
    "COMPLETE_SYSTEM_DOCUMENTATION.md"
    "DATA_COLLECTION_SOP_v2.md"
    "NEW_DATASET_EVALUATION_REPORT.md"
    "ORIGINAL_REQUEST.md"
    "CODE_REVIEW_v6.2.md"
) do (
    if exist %%F (
        move /y %%F "_archive\docs\" >nul 2>&1
        if !errorlevel! equ 0 ( echo     merged into README.md   %%~F & set /a MOVED+=1 )
    )
)

REM --- superseded by tests\test_regressions.py ------------------------------
if exist "test_normal_mix.py" (
    move /y "test_normal_mix.py" "_archive\" >nul 2>&1
    if !errorlevel! equ 0 ( echo     moved to tests\         test_normal_mix.py & set /a MOVED+=1 )
)

REM --- AI agent scratch directories from earlier sessions -------------------
if exist ".agents" (
    move /y ".agents" "_archive\" >nul 2>&1
    if !errorlevel! equ 0 ( echo     agent scratch           .agents\ & set /a MOVED+=1 )
)

REM --- the old standalone web launcher: it opened a file:// page that could
REM     never reach the API. main.py serves the dashboard now. ---------------
if exist "web\run_webapp.bat" (
    move /y "web\run_webapp.bat" "_archive\" >nul 2>&1
    if !errorlevel! equ 0 ( echo     superseded              web\run_webapp.bat & set /a MOVED+=1 )
)

REM --- stale plots, replaced by Data\research_plots\ ------------------------
for %%F in (
    "Data\multiclass_confusion_matrix.png"
    "Data\new_dataset_confusion_matrix.png"
    "Data\evaluation_summary_results.csv"
) do (
    if exist %%F (
        move /y %%F "_archive\" >nul 2>&1
        if !errorlevel! equ 0 ( echo     stale output            %%~F & set /a MOVED+=1 )
    )
)

REM --- regenerable caches: safe to delete outright --------------------------
if exist "__pycache__"       rd /s /q "__pycache__"       2>nul
if exist "tests\__pycache__" rd /s /q "tests\__pycache__" 2>nul
if exist ".pytest_cache"     rd /s /q ".pytest_cache"     2>nul
echo     deleted caches          __pycache__\, .pytest_cache\

echo.
echo   ---------------------------------------------------------------------
echo   !MOVED! item(s) moved into _archive\  (nothing was deleted)
echo.
echo   What is left at the top level:
echo.
echo     main.py            the engine
echo     web\               the dashboard (served by main.py)
echo     README.md          the whole documentation
echo     requirements.txt   dependencies
echo     start.bat          double-click to run
echo     share_public.py    public tunnel for remote judges
echo     Data\              recordings + generated metrics
echo     tests\             the test suite
echo.
echo   Delete _archive\ once you are sure nothing is missing,
echo   and delete this cleanup.bat too - it only needs to run once.
echo.
pause
