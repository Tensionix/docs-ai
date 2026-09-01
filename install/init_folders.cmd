@echo off
chcp 65001 >nul
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

for %%A in ("%SCRIPT_DIR%") do set "HERE=%%~nxA"

set "ROOT=%SCRIPT_DIR%"
if /I "%HERE%"=="install" for %%A in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fA"

set "FAILED=0"

call :MK "%ROOT%\input"
call :MK "%ROOT%\output"
call :MK "%ROOT%\report"
call :MK "%ROOT%\workspace"
call :MK "%ROOT%\work"
call :MK "%ROOT%\work\rendered_pdf"
call :MK "%ROOT%\work\marked_ooxml"
call :MK "%ROOT%\work\extracted_pdf_text"
call :MK "%ROOT%\cache"
call :MK "%ROOT%\runtime"
call :MK "%ROOT%\wheelhouse"
call :MK "%ROOT%\release"
call :MK "%ROOT%\logs"
call :MK "%ROOT%\licenses"
call :MK "%ROOT%\config"
call :MK "%ROOT%\config\audit_rules"
call :MK "%ROOT%\config\doc_tasks"
call :MK "%ROOT%\data"
call :MK "%ROOT%\docs"
call :MK "%ROOT%\._runtime"
call :MK "%ROOT%\system_core"
call :MK "%ROOT%\system_core\core"
call :MK "%ROOT%\system_core\providers"
call :MK "%ROOT%\system_core\render"
call :MK "%ROOT%\system_core\services"
call :MK "%ROOT%\system_core\ui_nicegui"
call :MK "%ROOT%\system_core\powershell"
call :MK "%ROOT%\system_core\license"
call :MK "%ROOT%\system_core\license\files"
call :MK "%ROOT%\system_core\license\fallbacks"
call :MK "%ROOT%\install"
call :MK "%ROOT%\install\download"


if "%FAILED%"=="1" (
  echo [ERROR] init_folders.cmd failed.
  exit /b 1
)

exit /b 0

:MK
if exist "%~1\" goto :eof
mkdir "%~1" >nul 2>nul
if not exist "%~1\" (
  echo [ERROR] Cannot create directory: %~1
  set "FAILED=1"
)
goto :eof
