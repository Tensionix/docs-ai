@echo off
chcp 65001 >nul
setlocal EnableExtensions

title Audion Docs AI v3 - Project Cleanup

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
cd /d "%BASE_DIR%" || exit /b 1

set "DRY_RUN=0"
set "YES=0"

:PARSE_ARGS
if "%~1"=="" goto ARGS_DONE
if /I "%~1"=="help" goto HELP
if /I "%~1"=="--help" goto HELP
if /I "%~1"=="/?" goto HELP
if /I "%~1"=="--dry-run" (
  set "DRY_RUN=1"
  shift
  goto PARSE_ARGS
)
if /I "%~1"=="/dry-run" (
  set "DRY_RUN=1"
  shift
  goto PARSE_ARGS
)
if /I "%~1"=="--yes" (
  set "YES=1"
  shift
  goto PARSE_ARGS
)
if /I "%~1"=="/y" (
  set "YES=1"
  shift
  goto PARSE_ARGS
)
echo [ERROR] Unknown argument: %~1
echo.
goto HELP

:ARGS_DONE
call :GUARD_ROOT || exit /b 1

echo ======================================================================
echo   AUDION DOCS AI v3 - CLEAN GENERATED LOCAL ARTIFACTS
echo ======================================================================
echo Root: %BASE_DIR%
echo.
echo This cleanup keeps source code, install scripts, documentation, tests,
echo GitHub metadata, rules, TASK instructions, prompts, and project configs.
echo.
echo It cleans local/generated contents:
echo   runtime\*
echo   wheelhouse\*
echo   ._runtime\*
echo   install\download\*
echo   system_core\powershell\*
echo   system_core\**\__pycache__\
echo   system_core\fzf.exe
echo   system_core\_fzf_tmp\*, system_core\_pwsh_tmp\*, system_core\_powershell_tmp\*
echo   logs\*
echo   input\*, output\*, report\*, work\*, workspace\*
echo   - root licenses\ is preserved unchanged
echo.
echo API key files in config are preserved.
echo.
if "%DRY_RUN%"=="1" (
  echo [MODE] Dry run only. Nothing will be deleted.
) else (
  echo [MODE] Real cleanup.
)
echo.

if "%DRY_RUN%"=="1" goto CLEAN
if "%YES%"=="1" goto CLEAN

choice /C YNQ /N /M "Proceed with project cleanup? [Y/N/Q]: "
if errorlevel 2 goto CANCEL
if errorlevel 1 goto CLEAN
goto CANCEL

:CLEAN
echo.
echo [1/8] Cleaning portable runtimes and dependency caches...
call :EMPTY_DIR "runtime"
call :EMPTY_DIR "wheelhouse"
call :EMPTY_DIR "._runtime"

echo.
echo [2/8] Cleaning install download cache and portable PowerShell...
call :EMPTY_DIR "install\download"
call :EMPTY_DIR "system_core\powershell"

echo.
echo [3/8] Removing system_core Python caches and local helper binaries...
call :REMOVE_SYSTEM_CORE_PYCACHE
call :DEL_FILE "system_core\fzf.exe"
call :EMPTY_DIR "system_core\_fzf_tmp"
call :EMPTY_DIR "system_core\_pwsh_tmp"
call :EMPTY_DIR "system_core\_powershell_tmp"

echo.
echo [4/8] Cleaning logs, user documents, reports, and working artifacts...
call :EMPTY_DIR "logs"
call :EMPTY_DIR "input"
call :EMPTY_DIR "output"
call :EMPTY_DIR "report"
call :EMPTY_DIR "workspace"
call :EMPTY_DIR "work"
call :EMPTY_DIR "cache"
call :EMPTY_DIR "release"
rem licenses\ is intentionally preserved by release cleanup.
echo.
echo [5/8] Cleaning generated license payload folders...
call :EMPTY_DIR "system_core\license\files"
call :EMPTY_DIR "system_core\license\fallbacks"

echo.
echo [6/8] Removing developer-only virtualenvs and legacy leftovers...
call :RM_DIR ".venv"
call :RM_DIR ".venv_latest"
call :RM_DIR ".venv_build"
call :RM_DIR ".venv_latest_build"
call :RM_DIR "audit_docs"
call :DEL_FILE "api_key.txt"
call :DEL_FILE "api_key_openai.txt"
call :DEL_FILE "api_key_gemini.txt"
call :DEL_FILE "api_key_xai.txt"
call :DEL_FILE "launcher_audit.cmd"
call :DEL_FILE "launcher_audit_genai.cmd"
call :DEL_FILE "install\launcher_audit.cmd"

echo.
echo [7/8] Recreating required managed folder structure...
call :KEEP_DIR "config"
call :KEEP_DIR "config\audit_rules"
call :KEEP_DIR "config\doc_tasks"
call :KEEP_DIR "docs"
call :KEEP_DIR "GitHub"
call :KEEP_DIR "install"
call :KEEP_DIR "install\download"
call :KEEP_DIR "system_core"
call :KEEP_DIR "system_core\core"
call :KEEP_DIR "system_core\providers"
call :KEEP_DIR "system_core\render"
call :KEEP_DIR "system_core\services"
call :KEEP_DIR "system_core\ui_nicegui"
call :KEEP_DIR "system_core\powershell"
call :KEEP_DIR "system_core\license"
call :KEEP_DIR "system_core\license\files"
call :KEEP_DIR "system_core\license\fallbacks"
call :KEEP_DIR "tests"
call :KEEP_DIR "data"
call :KEEP_DIR "input"
call :KEEP_DIR "output"
call :KEEP_DIR "logs"
call :KEEP_DIR "report"
call :KEEP_DIR "workspace"
call :KEEP_DIR "work"
call :KEEP_DIR "work\rendered_pdf"
call :KEEP_DIR "work\marked_ooxml"
call :KEEP_DIR "work\extracted_pdf_text"
call :KEEP_DIR "cache"
call :KEEP_DIR "runtime"
call :KEEP_DIR "wheelhouse"
call :KEEP_DIR "release"
call :KEEP_DIR "licenses"
call :KEEP_DIR "._runtime"

echo.
echo [8/8] Preserving local API key placeholders...
call :KEEP_FILE "config\api_key_gemini.txt"
call :KEEP_FILE "config\api_key_openai.txt"
call :KEEP_FILE "config\api_key_xai.txt"
rem .gitkeep markers are not recreated here: every folder above is held by its
rem own :KEEP_DIR call, and install\init_folders.cmd is what builds the empty
rem structure. Recreating markers on each cleanup is how 18 of them came back.

echo.
if "%DRY_RUN%"=="1" goto DRY_RUN_DONE
echo [OK] Cleanup finished.
echo      Source code, scripts, docs, configs, rules, and TASK instructions were kept.
echo      Generated runtimes, caches, logs, user outputs, and local binaries were cleaned.
echo      Existing config API key files were left unchanged.
goto CLEANUP_DONE

:DRY_RUN_DONE
echo [OK] Dry run finished. No files were deleted.

:CLEANUP_DONE
echo.
if not "%YES%"=="1" call :WAIT_KEY
exit /b 0

:HELP
echo Audion Docs AI v3 project cleanup
echo.
echo Usage:
echo   cleanup_project.cmd
echo   cleanup_project.cmd --dry-run
echo   cleanup_project.cmd --yes
echo.
echo Default mode asks for confirmation. Use --dry-run to preview the plan.
echo Use --yes only for scripted cleanup.
exit /b 0

:CANCEL
echo.
echo [INFO] Cancelled.
call :WAIT_KEY
exit /b 0

:GUARD_ROOT
if not exist "%BASE_DIR%\system_core\doctor.py" goto BAD_ROOT
if not exist "%BASE_DIR%\config\tool_manifest.yaml" goto BAD_ROOT
if not exist "%BASE_DIR%\install\init_folders.cmd" goto BAD_ROOT
exit /b 0

:BAD_ROOT
echo [ERROR] This does not look like the Audion Docs AI project root:
echo         %BASE_DIR%
echo.
echo Expected files:
echo   system_core\doctor.py
echo   config\tool_manifest.yaml
echo   install\init_folders.cmd
call :WAIT_KEY
exit /b 1

:EMPTY_DIR
set "REL=%~1"
set "TARGET=%BASE_DIR%\%REL%"
if "%DRY_RUN%"=="1" (
  echo    [clean] %REL%\*
  goto :eof
)
if not exist "%TARGET%\" mkdir "%TARGET%" >nul 2>nul
del /f /q "%TARGET%\*" >nul 2>nul
for /d %%D in ("%TARGET%\*") do rd /s /q "%%D" >nul 2>nul
echo    [clean] %REL%\*
goto :eof

:CLEAN_LICENSES
rem Safety guard: release cleanup must never touch licenses\.
echo   keep  licenses\  ^(preserved unchanged^)
goto :eof

:RM_DIR
set "REL=%~1"
set "TARGET=%BASE_DIR%\%REL%"
if "%DRY_RUN%"=="1" (
  echo    [remove dir] %REL%\
  goto :eof
)
if exist "%TARGET%\" (
  rd /s /q "%TARGET%" >nul 2>nul
  echo    [remove dir] %REL%\
)
goto :eof

:DEL_FILE
set "REL=%~1"
set "TARGET=%BASE_DIR%\%REL%"
if "%DRY_RUN%"=="1" (
  echo    [remove file] %REL%
  goto :eof
)
if exist "%TARGET%" (
  del /f /q "%TARGET%" >nul 2>nul
  echo    [remove file] %REL%
)
goto :eof

:KEEP_DIR
if "%DRY_RUN%"=="1" (
  echo    [keep dir] %~1\
  goto :eof
)
if not exist "%BASE_DIR%\%~1\" mkdir "%BASE_DIR%\%~1" >nul 2>nul
goto :eof

:KEEP_FILE
if "%DRY_RUN%"=="1" (
  echo    [keep file] %~1
  goto :eof
)
set "TARGET=%BASE_DIR%\%~1"
for %%P in ("%TARGET%") do if not exist "%%~dpP" mkdir "%%~dpP" >nul 2>nul
if not exist "%TARGET%" type nul > "%TARGET%"
goto :eof

:KEEP_FILE_OPTIONAL
if "%DRY_RUN%"=="1" (
  echo    [keep optional file] %~1
  goto :eof
)
set "TARGET=%BASE_DIR%\%~1"
for %%P in ("%TARGET%") do set "PARENT=%%~dpP"
if not exist "%PARENT%" mkdir "%PARENT%" >nul 2>nul
if exist "%TARGET%" goto :eof
set "OPTIONAL_HAS_CONTENT=0"
for /f %%C in ('dir /a /b "%PARENT%" 2^>nul ^| find /c /v ""') do set "OPTIONAL_HAS_CONTENT=%%C"
if not "%OPTIONAL_HAS_CONTENT%"=="0" goto :eof
type nul > "%TARGET%" 2>nul
if exist "%TARGET%" echo    [keep optional file] %~1
goto :eof

:EMPTY_FILE
if "%DRY_RUN%"=="1" (
  echo    [empty file] %~1
  goto :eof
)
set "TARGET=%BASE_DIR%\%~1"
for %%P in ("%TARGET%") do if not exist "%%~dpP" mkdir "%%~dpP" >nul 2>nul
type nul > "%TARGET%"
echo    [empty file] %~1
goto :eof

:REMOVE_SYSTEM_CORE_PYCACHE
if "%DRY_RUN%"=="1" (
  echo    [remove dirs] system_core\**\__pycache__\
  echo    [remove files] system_core\*.pyc, system_core\*.pyo
  goto :eof
)
for /d /r "%BASE_DIR%\system_core" %%D in (__pycache__) do if exist "%%D\" rd /s /q "%%D" >nul 2>nul
del /s /q "%BASE_DIR%\system_core\*.pyc" "%BASE_DIR%\system_core\*.pyo" >nul 2>nul
echo    [remove dirs] system_core\**\__pycache__\
echo    [remove files] system_core\*.pyc, system_core\*.pyo
goto :eof
:WAIT_KEY
echo Press any key to continue . . .
if not defined AUDION_NO_PAUSE pause >nul
goto :eof
