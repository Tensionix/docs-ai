@echo off
setlocal EnableDelayedExpansion
rem Run a docs-ai script with the Python that ships with Audion Docs AI.
rem
rem No system-wide installation is needed: the portable runtime already carries
rem python-docx, openpyxl, PyMuPDF and python-pptx. Where that program lives is
rem not guessed - it is written down in docs-ai-home.txt next to SKILL.md.
rem
rem Usage:  run.cmd prepare.py --source "D:\docs\Записка.docx" --preset standard

set "SCRIPT_DIR=%~dp0"
set "SKILL_DIR=%SCRIPT_DIR%.."
set "TARGET=%~1"
if "%TARGET%"=="" (
  echo Usage: run.cmd ^<script.py^> [args...]
  exit /b 2
)
shift

set "FOUND="
set "HOME_PATH="

rem 1. The environment wins, if someone set it deliberately.
if defined DOCS_AI_PYTHON call :try "%DOCS_AI_PYTHON%"
if not defined FOUND if defined AUDION_DOCS_AI_HOME call :fromhome "%AUDION_DOCS_AI_HOME%"

rem 2. The skill living inside Audion Docs AI (data\skills\<name>) needs no setup.
if not defined FOUND call :try "%SKILL_DIR%\..\..\..\runtime\python.exe"

rem 3. Otherwise read the path written next to SKILL.md.
if not defined FOUND if exist "%SKILL_DIR%\docs-ai-home.txt" (
  for /f "usebackq delims=" %%L in ("%SKILL_DIR%\docs-ai-home.txt") do (
    if not defined FOUND (
      set "LINE=%%L"
      if not "!LINE!"=="" if not "!LINE:~0,1!"=="#" call :fromhome "!LINE!"
    )
  )
)

rem 4. Last resort: a system Python that happens to have the libraries.
if not defined FOUND for %%C in (py python3 python) do (
  if not defined FOUND call :try "%%C"
)

if not defined FOUND (
  echo [ERROR] Не найден Python с библиотеками python-docx и openpyxl.
  echo.
  echo Впишите путь к портативной Audion Docs AI в файл:
  echo     %SKILL_DIR%\docs-ai-home.txt
  echo Например одной строкой:
  echo     E:\TOOLS\Audion Docs AI
  echo.
  echo Образец с пояснениями лежит рядом: docs-ai-home.example.txt
  echo Проверить интерпретатор:  ^<python^> "%SCRIPT_DIR%check_env.py"
  if defined HOME_PATH echo.
  if defined HOME_PATH echo Прочитано из файла: "!HOME_PATH!" — там Python не найден или без библиотек.
  exit /b 1
)

"%FOUND%" "%SCRIPT_DIR%%TARGET%" %*
exit /b %ERRORLEVEL%

rem Accept either the program folder or a direct path to an interpreter.
:fromhome
if defined FOUND exit /b 0
set "HOME_PATH=%~1"
call :try "%~1\runtime\python.exe"
if not defined FOUND call :try "%~1"
exit /b 0

:try
if defined FOUND exit /b 0
if "%~1"=="" exit /b 1
"%~1" -c "import docx, openpyxl" >nul 2>&1
if errorlevel 1 exit /b 1
set "FOUND=%~1"
exit /b 0
