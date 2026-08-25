@echo off
REM ===========================================================================
REM  Project2 - remove the files nothing uses. 2026-08-21 edition.
REM
REM  Replaces the previous cleanup.bat AND cleanup_bloat.bat (two scripts doing
REM  the same job on different lists).
REM
REM    cleanup.bat          DELETES everything on the list below
REM    cleanup.bat /keep    moves it into _to_delete\ instead, deletes nothing
REM    cleanup.bat /all     also does group [7/9], the one judgement call -
REM                         the 54 MB tunnel binary. Combine freely:
REM                         cleanup.bat /keep /all
REM
REM  Every file removed is either generated, a duplicate of another file in this
REM  same folder, or superseded by something in main.py - the reason for each one
REM  is in the comment above its group, and in README.md section 10. If the repo
REM  is committed, `git checkout -- <file>` brings any of them back.
REM
REM  Nothing under Data\<class>\ is touched. The only thing removed from Data\
REM  is the pytest fixtures in Custom_Uploads\, which are not recordings.
REM
REM  2026-08-21: added groups [5/9] retired scratch folders, [6/9] dead
REM  automation and regenerable figures, [7/9] the judgement call behind /all,
REM  and [8/9] the root tidy-up that finishes the move into scripts\.
REM  Three things are
REM  kept rather than removed:
REM    - _archive\docs\ACTION_PLAN.md, because main.py cites it by name at line
REM      4164, which prints on every boot
REM    - .agents\rules\, which is NOT scratch: it is where Antigravity reads
REM      this project's rules from. Same folder name, opposite meaning. The
REM      per-worker scratch subfolders go; rules\ stays.
REM    - start.bat and cleanup.bat stay at the root. One is the daily entry
REM      point; the other is this file, and a .bat that deletes itself while
REM      running behaves badly.
REM ===========================================================================
chcp 65001 >nul
setlocal EnableDelayedExpansion
title Project2 cleanup
cd /d "%~dp0"

set "MODE=delete"
set "SWEEP=safe"
for %%A in (%*) do (
    if /i "%%~A"=="/keep" set "MODE=keep"
    if /i "%%~A"=="/all"  set "SWEEP=all"
)

if "%MODE%"=="keep" (
    if not exist "_to_delete"            mkdir "_to_delete"
    if not exist "_to_delete\superseded" mkdir "_to_delete\superseded"
    if not exist "_to_delete\bin"        mkdir "_to_delete\bin"
    if not exist "_to_delete\uploads"    mkdir "_to_delete\uploads"
    if not exist "_to_delete\video"      mkdir "_to_delete\video"
    if not exist "_to_delete\docs"       mkdir "_to_delete\docs"
    if not exist "_to_delete\scratch"    mkdir "_to_delete\scratch"
)

set REMOVED=0
echo.
if "%MODE%"=="keep" (
    echo   Project2 cleanup - MOVING unused files into _to_delete\
) else (
    echo   Project2 cleanup - DELETING unused files
    echo   ^(run "cleanup.bat /keep" instead if you would rather move them^)
)
echo   =====================================================================

REM --- code superseded by something in main.py, or duplicated ---------------
REM  live_monitor.py          -> python main.py --monitor COM5
REM                              It drew a fictitious 5x5 pad lattice (defect
REM                              F5), applied PAD_ORDER when the sockets do not,
REM                              and printed a predicted_label key LivePipeline
REM                              has never returned - so every line read
REM                              "(NORMAL)", including LEVEL 3 CRITICAL ones.
REM  benchmark_fast.py        -> duplicate of benchmark_ml_architectures.py,
REM                              same duplicated-feature bug, same wrong captions
REM  inspect_peel.py          -> one-off scratch script
REM  diagnose_baseline.py     -> one-off scratch script, hardcoded relative path
REM  test_*.py at the root    -> docstring-only stubs; pytest.ini sets
REM                              testpaths=tests, so they never ran
REM  cleanup_bloat.bat        -> merged into this file
REM  Start_Web_App.bat        -> merged into start.bat (now bilingual)
REM  Start_Public_Web_App.bat -> merged into start_public.bat
REM  Create_Public_Desktop_Shortcut.bat -> merged into Create_Desktop_Shortcut.bat
echo.
echo   [1/9] superseded code and duplicate launchers
call :remove_group "superseded" "live_monitor.py" "benchmark_fast.py" "inspect_peel.py" "diagnose_baseline.py" "test_events.py" "test_gated_pipeline.py" "test_robust_pipeline.py" "cleanup_bloat.bat" "Start_Web_App.bat" "Start_Public_Web_App.bat" "Create_Public_Desktop_Shortcut.bat"

REM --- documents whose content is in README.md ------------------------------
echo.
echo   [2/9] documents merged into README.md
call :remove_group "docs" "ACTION_PLAN.md" "CLAUDE_LOOPING_ENGINEERING_PROMPT.md" "CLAUDE_LOOPING_ENGINEERING_V2.md" "CLAUDE_WHITE_PAPER_DOCUMENTATION.md" "COMPLETE_SYSTEM_DOCUMENTATION.md" "DATA_COLLECTION_SOP_v2.md" "NEW_DATASET_EVALUATION_REPORT.md" "ORIGINAL_REQUEST.md" "CODE_REVIEW_v6.2.md" "test_normal_mix.py"

REM --- binaries and recordings that do not belong in a source tree ----------
REM  cf.exe and cloudflared.exe are the same 54 MB tunnel binary under two
REM  names. share_public.py looks for cloudflared, so that is the one kept.
echo.
echo   [3/9] duplicate binary and screen recordings
call :remove_group "bin" "cf.exe"
REM  Wildcards go to del/move directly. Routing them through `for %%F in (...)`
REM  and a :remove_one subroutine silently did nothing - the pattern matched, the
REM  subroutine ran, and the files were still there afterwards. del and move
REM  expand wildcards themselves; there is no reason to loop.
if "%MODE%"=="keep" (
    move /y "*.mp4" "_to_delete\video\" >nul 2>&1
    move /y "*.mkv" "_to_delete\video\" >nul 2>&1
    move /y "*.avi" "_to_delete\video\" >nul 2>&1
) else (
    del /f /q "*.mp4" >nul 2>&1
    del /f /q "*.mkv" >nul 2>&1
    del /f /q "*.avi" >nul 2>&1
)
if not exist "*.mp4" echo         screen recordings ^(*.mp4^)

REM --- pytest fixtures sitting in the real corpus ---------------------------
REM  Written into Data\Custom_Uploads\ by the test suite before it was isolated
REM  from the real Data\ directory on 2026-08-17. They are not recordings, and
REM  they sit against the 50-file upload quota - so the next genuine upload
REM  evicts a real one to make room.
echo.
echo   [4/9] pytest fixtures left in Data\Custom_Uploads\
if "%MODE%"=="keep" (
    move /y "Data\Custom_Uploads\dup_*.csv"              "_to_delete\uploads\" >nul 2>&1
    move /y "Data\Custom_Uploads\unit_test_sample*.csv"  "_to_delete\uploads\" >nul 2>&1
) else (
    del /f /q "Data\Custom_Uploads\dup_*.csv"             >nul 2>&1
    del /f /q "Data\Custom_Uploads\unit_test_sample*.csv" >nul 2>&1
)
if not exist "Data\Custom_Uploads\dup_*.csv" (
    if not exist "Data\Custom_Uploads\unit_test_sample*.csv" echo         pytest fixtures ^(dup_*.csv, unit_test_sample*.csv^)
)

REM --- retired folders ------------------------------------------------------
REM  _archive\  finished work parked here by earlier cleanups: superseded docs,
REM             two confusion-matrix PNGs regenerated by --plots, the old
REM             run_webapp.bat launcher, test_normal_mix.py, and a copy of
REM             .agents\. Nothing imports any of it and no test reads it.
REM  .agents\   scratch space from the agent runs that built this project -
REM             BRIEFING.md / handoff.md / progress.md per worker, plus their
REM             one-off analysis scripts. Finished work, not inputs.
REM
REM             EXCEPT .agents\rules\ - Antigravity's workspace rules live
REM             there and are a live input, not a leftover. This script removes
REM             the scratch subfolders one level down instead of the whole
REM             .agents\ tree, so the rules survive a cleanup.
REM
REM  ACTION_PLAN.md is the one file rescued rather than binned: main.py prints
REM  "see ACTION_PLAN.md P0-3" on every boot, and a boot message that names a
REM  file nobody can find is worse than the clutter it saves.
echo.
echo   [5/9] retired folders
if exist "_archive\docs\ACTION_PLAN.md" (
    if not exist "docs" mkdir "docs"
    if not exist "docs\ACTION_PLAN.md" (
        move /y "_archive\docs\ACTION_PLAN.md" "docs\" >nul 2>&1
        if exist "docs\ACTION_PLAN.md" echo         kept  docs\ACTION_PLAN.md ^(cited by main.py^)
    )
)
call :remove_dir "_archive"

REM  .agents\ is emptied of scratch rather than removed outright: every child
REM  except rules\ goes, then the folder itself only if nothing is left in it.
if exist ".agents\" (
    for /d %%D in (".agents\*") do (
        if /i not "%%~nxD"=="rules" call :remove_dir "%%~fD"
    )
    for %%F in (".agents\*.md") do call :remove_one "scratch" "%%~fF"
    if exist ".agents\rules\" (
        echo         kept  .agents\rules\ ^(Antigravity workspace rules^)
    ) else (
        call :remove_dir ".agents"
    )
)

REM --- dead automation and regenerable output -------------------------------
REM  .github\workflows\keep_alive.yml
REM      Pings https://touch-sensor-ai.onrender.com every 10 minutes to stop a
REM      Render free instance sleeping. That endpoint has answered 401 since the
REM      access key went in, and the step ends in `|| true`, so it has been
REM      firing 144 times a day and reporting success while doing nothing. CI
REM      minutes for a no-op. ci.yml is the real workflow and stays.
REM
REM  Data\research_plots\
REM      Figures written by `python main.py --plots`. Regenerated in seconds.
REM      Roughly 3.3 MB of PNG and SVG that no code reads.
REM
REM  Data\model_comparison_100x.json is NOT in this list on purpose: it is also
REM  "regenerable", but regenerating it means re-running the 100x benchmark.
echo.
echo   [6/9] dead automation and regenerable figures
call :remove_one "superseded" ".github\workflows\keep_alive.yml"
call :remove_dir "Data\research_plots"

REM --- judgement calls: only with /all --------------------------------------
REM  cloudflared.exe  54.9 MB, the single largest file in the tree and about
REM      85%% of everything outside Data\. share_public.py DOES use it - but it
REM      checks PATH first (`shutil.which`) and falls back to npx localtunnel,
REM      so removing it degrades rather than breaks: install cloudflared
REM      properly, or let the fallback handle it. Your own .dockerignore and
REM      .gcloudignore already exclude it, which is the same judgement.
REM
REM  The two loose reports are MOVED into docs\, not deleted. They are finished
REM  work worth keeping; they just do not need to sit in the root where you read
REM  the file list every day.
echo.
if /i "%SWEEP%"=="all" (
    echo   [7/9] judgement calls ^(/all^)
    call :remove_one "bin" "cloudflared.exe"
) else (
    echo   [7/9] judgement calls - skipped ^(pass /all to include them^)
    echo         cloudflared.exe ^(54.9 MB^) stays
)

REM --- root tidy-up: originals whose copy now lives in scripts\ -------------
REM  The root had five .bat plus a .ps1 sitting next to main.py, and the file
REM  you actually double-click every day was lost among them. The three
REM  secondary launchers and the deploy script now live in scripts\, each with
REM  "cd /d %%~dp0.." so the working directory is still the project root.
REM
REM  This group deletes the ORIGINALS at the root. It only fires once the copy
REM  is confirmed present, so an interrupted move cannot leave you with neither.
REM
REM  start.bat and cleanup.bat deliberately stay at the root: one is the daily
REM  entry point, the other is this file, and a batch script that deletes itself
REM  mid-run behaves badly - cmd reads it line by line as it executes.
REM
REM  Procfile goes too: it is Render's entry point, render.yaml is already gone,
REM  and the deploy target is Cloud Run, which reads the Dockerfile.
echo.
echo   [8/9] root tidy-up ^(moved into scripts\^)
call :drop_if_copied "start_public.bat"          "scripts\start_public.bat"
call :drop_if_copied "Start_Sensor_Bridge.bat"   "scripts\Start_Sensor_Bridge.bat"
call :drop_if_copied "Create_Desktop_Shortcut.bat" "scripts\Create_Desktop_Shortcut.bat"
call :drop_if_copied "deploy_google.ps1"         "scripts\deploy_google.ps1"
call :remove_one "superseded" "Procfile"
call :tuck_doc "DEPLOY_GOOGLE.md"
call :tuck_doc "CODE_REVIEW_2026-08-19.md"
call :tuck_doc "RELATED_RESEARCH_PAPER_SUMMARY.md"

REM --- generated caches: always deleted, they rebuild themselves ------------
echo.
echo   [9/9] generated caches
if exist "__pycache__"       ( rd /s /q "__pycache__"       2>nul & echo         __pycache__ )
if exist "tests\__pycache__" ( rd /s /q "tests\__pycache__" 2>nul & echo         tests\__pycache__ )
if exist ".pytest_cache"     ( rd /s /q ".pytest_cache"     2>nul & echo         .pytest_cache )

echo.
echo   =====================================================================
REM  !REMOVED!, not %REMOVED%: inside a parenthesised block a %var% is expanded
REM  once when the block is parsed, so this summary reported 0 every run no
REM  matter how many files had just moved.
if "%MODE%"=="keep" (
    echo   !REMOVED! file^(s^) moved into _to_delete\ - nothing was deleted.
) else (
    echo   !REMOVED! file^(s^) deleted.
)
echo.
if /i not "%SWEEP%"=="all" echo   Run "cleanup.bat /all" to also clear the 54.9 MB tunnel binary.
echo.
echo   Check it still works:
echo       python -m pytest tests\ -q
echo       python main.py --verify-metrics
echo       start.bat
echo   =====================================================================
echo.
pause
exit /b 0

REM ---------------------------------------------------------------------------
:remove_group
set "BUCKET=%~1"
shift
:remove_group_loop
if "%~1"=="" goto :eof
call :remove_one "%BUCKET%" "%~1"
shift
goto :remove_group_loop

:drop_if_copied
REM  %~1 is the original at the root, %~2 the copy that replaced it. Refuse to
REM  delete unless the copy is really there - "move" done as two steps must
REM  never be able to lose the only version.
if not exist "%~1" goto :eof
if not exist "%~2" (
    echo         SKIPPED %~1 - no copy at %~2 yet
    goto :eof
)
if "%MODE%"=="keep" (
    move /y "%~1" "_to_delete\superseded\" >nul 2>&1
) else (
    del /f /q "%~1" >nul 2>&1
)
if not exist "%~1" (
    echo         %~1 -^> %~2
    set /a REMOVED+=1
)
goto :eof

:tuck_doc
REM  Documents are moved into docs\, not destroyed - finished work that simply
REM  does not need to sit in the root where you read the file list every day.
if not exist "%~1" goto :eof
if not exist "docs" mkdir "docs"
move /y "%~1" "docs\" >nul 2>&1
if not exist "%~1" (
    echo         moved %~1 -^> docs\
    set /a REMOVED+=1
)
goto :eof

:remove_dir
REM  Directories need rd, not del: `del /f /q "_archive"` deletes the files
REM  inside it and leaves the tree of empty folders standing, which looks like
REM  the script did nothing.
if not exist "%~1\" goto :eof
if "%MODE%"=="keep" (
    if not exist "_to_delete\folders" mkdir "_to_delete\folders"
    move /y "%~1" "_to_delete\folders\" >nul 2>&1
) else (
    rd /s /q "%~1" 2>nul
)
if not exist "%~1\" (
    echo         %~1\
    set /a REMOVED+=1
)
goto :eof

:remove_one
if not exist "%~2" goto :eof
if "%MODE%"=="keep" (
    move /y "%~2" "_to_delete\%~1\" >nul 2>&1
) else (
    del /f /q "%~2" >nul 2>&1
)
if not exist "%~2" (
    echo         %~nx2
    set /a REMOVED+=1
)
goto :eof
