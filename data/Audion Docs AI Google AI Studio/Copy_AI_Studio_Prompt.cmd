@echo off
setlocal EnableExtensions

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
set "PROMPT_FILE=%BASE_DIR%\prompts\prompt_google_ai_studio.md"

if not exist "%PROMPT_FILE%" (
  echo [ERROR] Prompt file not found:
  echo %PROMPT_FILE%
  if not defined AUDION_NO_PAUSE pause
  exit /b 1
)

type "%PROMPT_FILE%" | clip
echo [OK] Prompt copied to clipboard.
echo File:
echo   %PROMPT_FILE%
if not defined AUDION_NO_PAUSE pause
