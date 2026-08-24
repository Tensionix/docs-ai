@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Audion Docs AI v3 - Tools Launcher

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
cd /d "%BASE_DIR%"

set "CORE_DIR=%BASE_DIR%\system_core"
set "LICENSE_DIR=%CORE_DIR%\license"
set "FZF_EXE=%CORE_DIR%\fzf.exe"
set "RUNTIME_DIR=%BASE_DIR%\._runtime"
set "MENU_FILE=%RUNTIME_DIR%\tools_menu.txt"
set "RES_FILE=%RUNTIME_DIR%\tools_menu_res.txt"
set "TOOLS_PROMPT=audion@docs-v3 [TOOLS] > "

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%" >nul 2>nul
if /I "%~1"=="exit" exit /b 0
if "%AUDION_AUTO_EXIT%"=="1" exit /b 0

:MAIN
cls
echo ======================================================================
echo   AUDION DOCS AI v3 - TOOLS / SERVICE
echo ======================================================================
echo Root: %BASE_DIR%
echo.

if exist "%FZF_EXE%" goto FZF_MENU
goto FALLBACK_MENU

:FZF_MENU
> "%MENU_FILE%" echo [01] COLLECT LICENSES - PYTHON            ^| collect_py          ^| collect third-party license files
>>"%MENU_FILE%" echo [02] COLLECT AND DEDUP LICENSES           ^| collect_dedupe      ^| collect, then remove exact duplicates
>>"%MENU_FILE%" echo [03] PRUNE STALE LICENSE FOLDERS          ^| prune_stale         ^| remove uninstalled package leftovers
>>"%MENU_FILE%" echo [04] DEDUPLICATE COLLECTED LICENSES       ^| dedupe              ^| exact content duplicates only
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [05] PREPARE TREE FOR GITHUB              ^| cleanup_github      ^| remove runtime, deps, outputs, secrets
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [06] OPEN config                          ^| open_config         ^| explorer
>>"%MENU_FILE%" echo [07] OPEN logs                            ^| open_logs           ^| explorer
>>"%MENU_FILE%" echo [08] OPEN work                            ^| open_work           ^| explorer
>>"%MENU_FILE%" echo [09] OPEN output                          ^| open_output         ^| explorer
>>"%MENU_FILE%" echo [00] BACK                                 ^| back                ^| return

type "%MENU_FILE%" | "%FZF_EXE%" --prompt="%TOOLS_PROMPT%" --pointer=">" --header="Pick service action:" --layout=reverse --border="rounded" --info=hidden --margin=1,2 > "%RES_FILE%"

set "CHOICE="
set /p CHOICE=<"%RES_FILE%"
if not defined CHOICE goto MAIN

for /f "tokens=2 delims=|" %%a in ("%CHOICE%") do set "RAW=%%a"
call :TRIM RAW

if /I "%RAW%"=="collect_py" goto COLLECT_LICENSES_PY
if /I "%RAW%"=="collect_dedupe" goto COLLECT_AND_DEDUPE_LICENSES
if /I "%RAW%"=="prune_stale" goto PRUNE_STALE_LICENSES
if /I "%RAW%"=="dedupe" goto DEDUPE_LICENSES
if /I "%RAW%"=="cleanup_github" goto CLEANUP_GITHUB
if /I "%RAW%"=="open_config" goto OPEN_CONFIG
if /I "%RAW%"=="open_logs" goto OPEN_LOGS
if /I "%RAW%"=="open_work" goto OPEN_WORK
if /I "%RAW%"=="open_output" goto OPEN_OUTPUT
if /I "%RAW%"=="back" exit /b 0
goto MAIN

:FALLBACK_MENU
echo [01] Collect licenses - Python
echo [02] Collect and deduplicate licenses
echo [03] Prune stale license folders
echo [04] Deduplicate collected licenses
echo [05] Prepare tree for GitHub
echo [06] Open config
echo [07] Open logs
echo [08] Open work
echo [09] Open output
echo [00] Back
echo.
set "MENU_NUM="
set /p MENU_NUM=Select number: 
if "%MENU_NUM%"=="00" exit /b 0
if "%MENU_NUM%"=="0" exit /b 0
if "%MENU_NUM%"=="01" goto COLLECT_LICENSES_PY
if "%MENU_NUM%"=="1" goto COLLECT_LICENSES_PY
if "%MENU_NUM%"=="02" goto COLLECT_AND_DEDUPE_LICENSES
if "%MENU_NUM%"=="2" goto COLLECT_AND_DEDUPE_LICENSES
if "%MENU_NUM%"=="03" goto PRUNE_STALE_LICENSES
if "%MENU_NUM%"=="3" goto PRUNE_STALE_LICENSES
if "%MENU_NUM%"=="04" goto DEDUPE_LICENSES
if "%MENU_NUM%"=="4" goto DEDUPE_LICENSES
if "%MENU_NUM%"=="05" goto CLEANUP_GITHUB
if "%MENU_NUM%"=="5" goto CLEANUP_GITHUB
if "%MENU_NUM%"=="06" goto OPEN_CONFIG
if "%MENU_NUM%"=="6" goto OPEN_CONFIG
if "%MENU_NUM%"=="07" goto OPEN_LOGS
if "%MENU_NUM%"=="7" goto OPEN_LOGS
if "%MENU_NUM%"=="08" goto OPEN_WORK
if "%MENU_NUM%"=="8" goto OPEN_WORK
if "%MENU_NUM%"=="09" goto OPEN_OUTPUT
if "%MENU_NUM%"=="9" goto OPEN_OUTPUT
goto MAIN

:COLLECT_LICENSES_PY
call "%LICENSE_DIR%\Run-Collect-ThirdPartyLicenses-Python.cmd"
goto MAIN

:COLLECT_AND_DEDUPE_LICENSES
call "%LICENSE_DIR%\Run-Collect-And-Deduplicate-ThirdPartyLicenses.cmd"
goto MAIN

:PRUNE_STALE_LICENSES
call "%LICENSE_DIR%\Run-Prune-Stale-ThirdPartyLicenses.cmd"
goto MAIN

:DEDUPE_LICENSES
call "%LICENSE_DIR%\Run-Deduplicate-ThirdPartyLicenses.cmd"
goto MAIN

:CLEANUP_GITHUB
call "%BASE_DIR%\cleanup_audion_docs_ai.cmd"
goto MAIN

:OPEN_CONFIG
if not exist "%BASE_DIR%\config" mkdir "%BASE_DIR%\config" >nul 2>nul
start "" explorer "%BASE_DIR%\config"
goto MAIN

:OPEN_LOGS
if not exist "%BASE_DIR%\logs" mkdir "%BASE_DIR%\logs" >nul 2>nul
start "" explorer "%BASE_DIR%\logs"
goto MAIN

:OPEN_WORK
if not exist "%BASE_DIR%\work" mkdir "%BASE_DIR%\work" >nul 2>nul
start "" explorer "%BASE_DIR%\work"
goto MAIN

:OPEN_OUTPUT
if not exist "%BASE_DIR%\output" mkdir "%BASE_DIR%\output" >nul 2>nul
start "" explorer "%BASE_DIR%\output"
goto MAIN

:TRIM
set "_TMP=!%~1!"
for /f "tokens=* delims= " %%z in ("!_TMP!") do set "_TMP=%%z"
:TRIM_R
if not defined _TMP goto TRIM_DONE
if not "!_TMP:~-1!"==" " goto TRIM_DONE
set "_TMP=!_TMP:~0,-1!"
goto TRIM_R
:TRIM_DONE
set "%~1=!_TMP!"
goto :eof
