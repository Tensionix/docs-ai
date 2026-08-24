@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Audion Docs AI v3 - Project launcher

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
cd /d "%BASE_DIR%"

set "CORE_DIR=%BASE_DIR%\system_core"
set "FZF_EXE=%CORE_DIR%\fzf.exe"
set "RUNTIME_DIR=%BASE_DIR%\._runtime"
set "AUDION_REPORT_LANG=en"

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%" >nul 2>nul
set "SESSION_ID=%RANDOM%_%RANDOM%_%RANDOM%"
set "MENU_FILE=%RUNTIME_DIR%\project_menu_en_%SESSION_ID%.txt"
set "RES_FILE=%RUNTIME_DIR%\project_menu_en_res_%SESSION_ID%.txt"
set "LLM_ENV_FILE=%RUNTIME_DIR%\llm_settings_en_%SESSION_ID%.cmd"

call :RESOLVE_PYTHON
if errorlevel 1 goto NO_PYTHON
if /I "%~1"=="exit" exit /b 0
call :LOAD_LLM_SETTINGS
if errorlevel 1 goto CONFIG_ERROR
if "%AUDION_AUTO_EXIT%"=="1" exit /b 0
if not "%~1"=="" goto RUN_DIRECT

:MAIN
cls
echo ======================================================================
echo   Audion Docs AI v3 - Project launcher
echo ======================================================================
echo Root:   %BASE_DIR%
echo Python: %PYTHON_EXE% %PYTHON_ARGS%
echo Config: config\llm_settings.yaml
echo.

if "%AUDION_DISABLE_FZF%"=="1" goto FALLBACK_MENU
if exist "%FZF_EXE%" goto FZF_MENU
goto FALLBACK_MENU

:FZF_MENU
> "%MENU_FILE%" echo [01] Scan input                             ^| pipeline_scan              ^| recursive DOCX/PPTX scan
>>"%MENU_FILE%" echo [02] COM PDF export / render-map            ^| pipeline_render            ^| marked OOXML to PDF via Office COM
>>"%MENU_FILE%" echo [03] Audit step: OpenAI low                 ^| pipeline_audit_openai_low  ^| DOCX/PPTX + OpenAI / low
>>"%MENU_FILE%" echo [04] Audit step: OpenAI med                 ^| pipeline_audit_openai_med  ^| DOCX/PPTX + OpenAI / medium
>>"%MENU_FILE%" echo [05] Audit step: OpenAI high                ^| pipeline_audit_openai_high ^| DOCX/PPTX + OpenAI / high
>>"%MENU_FILE%" echo [06] Audit step: Gemini fast                ^| pipeline_audit_gemini_fast ^| DOCX/PPTX + Gemini / fast
>>"%MENU_FILE%" echo [07] Audit step: Gemini pro                 ^| pipeline_audit_gemini_pro  ^| DOCX/PPTX + Gemini / pro
>>"%MENU_FILE%" echo [08] Report + annotate from logs            ^| pipeline_report_annotate   ^| rebuild reports and annotated docs
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [11] OpenAI audit low                       ^| pipeline_all_openai_low    ^| full DOCX/PPTX pipeline
>>"%MENU_FILE%" echo [12] OpenAI audit med                       ^| pipeline_all_openai_med    ^| full DOCX/PPTX pipeline
>>"%MENU_FILE%" echo [13] OpenAI audit high                      ^| pipeline_all_openai_high   ^| full DOCX/PPTX pipeline
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [21] Gemini audit fast                      ^| pipeline_all_gemini_fast   ^| full DOCX/PPTX pipeline
>>"%MENU_FILE%" echo [22] Gemini audit pro                       ^| pipeline_all_gemini_pro    ^| full DOCX/PPTX pipeline
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [41] Open input                             ^| open_input                 ^| explorer
>>"%MENU_FILE%" echo [42] Open output                            ^| open_output                ^| explorer
>>"%MENU_FILE%" echo [43] Open logs                              ^| open_logs                  ^| explorer
>>"%MENU_FILE%" echo [44] Open work                              ^| open_work                  ^| explorer
>>"%MENU_FILE%" echo [45] Open config                            ^| open_config                ^| explorer
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [00] Exit                                   ^| exit                       ^| close

type "%MENU_FILE%" | "%FZF_EXE%" --prompt="audion@docs-v3 [project] > " --pointer=">" --header="Pick step:" --layout=reverse --border="rounded" --info=hidden --margin=1,2 > "%RES_FILE%"

set "CHOICE="
set /p CHOICE=<"%RES_FILE%"
if not defined CHOICE goto MAIN

for /f "tokens=2 delims=|" %%a in ("%CHOICE%") do set "RAW=%%a"
call :TRIM RAW
if /I "%RAW%"=="exit" exit /b 0
call :DISPATCH "%RAW%"
goto MAIN

:FALLBACK_MENU
echo [01] Scan input
echo [02] COM PDF export / render-map
echo [03] Audit step: OpenAI low
echo [04] Audit step: OpenAI med
echo [05] Audit step: OpenAI high
echo [06] Audit step: Gemini fast
echo [07] Audit step: Gemini pro
echo [08] Report + annotate from logs
echo [11] OpenAI audit low
echo [12] OpenAI audit med
echo [13] OpenAI audit high
echo [21] Gemini audit fast
echo [22] Gemini audit pro
echo [41] Open input
echo [42] Open output
echo [43] Open logs
echo [44] Open work
echo [45] Open config
echo [00] Exit
echo.
set "MENU_NUM="
set /p MENU_NUM=Select number: 
if "%MENU_NUM%"=="00" exit /b 0
if "%MENU_NUM%"=="0" exit /b 0
if "%MENU_NUM%"=="01" goto PIPELINE_SCAN
if "%MENU_NUM%"=="1" goto PIPELINE_SCAN
if "%MENU_NUM%"=="02" goto PIPELINE_RENDER
if "%MENU_NUM%"=="2" goto PIPELINE_RENDER
if "%MENU_NUM%"=="03" goto PIPELINE_AUDIT_OPENAI_LOW
if "%MENU_NUM%"=="3" goto PIPELINE_AUDIT_OPENAI_LOW
if "%MENU_NUM%"=="04" goto PIPELINE_AUDIT_OPENAI_MED
if "%MENU_NUM%"=="4" goto PIPELINE_AUDIT_OPENAI_MED
if "%MENU_NUM%"=="05" goto PIPELINE_AUDIT_OPENAI_HIGH
if "%MENU_NUM%"=="5" goto PIPELINE_AUDIT_OPENAI_HIGH
if "%MENU_NUM%"=="06" goto PIPELINE_AUDIT_GEMINI_FAST
if "%MENU_NUM%"=="6" goto PIPELINE_AUDIT_GEMINI_FAST
if "%MENU_NUM%"=="07" goto PIPELINE_AUDIT_GEMINI_PRO
if "%MENU_NUM%"=="7" goto PIPELINE_AUDIT_GEMINI_PRO
if "%MENU_NUM%"=="08" goto PIPELINE_REPORT_ANNOTATE
if "%MENU_NUM%"=="8" goto PIPELINE_REPORT_ANNOTATE
if "%MENU_NUM%"=="11" goto PIPELINE_ALL_OPENAI_LOW
if "%MENU_NUM%"=="12" goto PIPELINE_ALL_OPENAI_MED
if "%MENU_NUM%"=="13" goto PIPELINE_ALL_OPENAI_HIGH
if "%MENU_NUM%"=="21" goto PIPELINE_ALL_GEMINI_FAST
if "%MENU_NUM%"=="22" goto PIPELINE_ALL_GEMINI_PRO
if "%MENU_NUM%"=="41" goto OPEN_INPUT
if "%MENU_NUM%"=="42" goto OPEN_OUTPUT
if "%MENU_NUM%"=="43" goto OPEN_LOGS
if "%MENU_NUM%"=="44" goto OPEN_WORK
if "%MENU_NUM%"=="45" goto OPEN_CONFIG
goto MAIN

:DISPATCH
set "ACTION=%~1"
if /I "%ACTION%"=="audit_openai_low_p" goto PIPELINE_ALL_OPENAI_LOW
if /I "%ACTION%"=="audit_openai_med_p" goto PIPELINE_ALL_OPENAI_MED
if /I "%ACTION%"=="audit_openai_high_p" goto PIPELINE_ALL_OPENAI_HIGH
if /I "%ACTION%"=="audit_flash_p" goto PIPELINE_ALL_GEMINI_FAST
if /I "%ACTION%"=="audit_pro_p" goto PIPELINE_ALL_GEMINI_PRO
if /I "%ACTION%"=="pipeline_scan" goto PIPELINE_SCAN
if /I "%ACTION%"=="pipeline_render" goto PIPELINE_RENDER
if /I "%ACTION%"=="pipeline_audit_openai_low" goto PIPELINE_AUDIT_OPENAI_LOW
if /I "%ACTION%"=="pipeline_audit_openai_med" goto PIPELINE_AUDIT_OPENAI_MED
if /I "%ACTION%"=="pipeline_audit_openai_high" goto PIPELINE_AUDIT_OPENAI_HIGH
if /I "%ACTION%"=="pipeline_audit_gemini_fast" goto PIPELINE_AUDIT_GEMINI_FAST
if /I "%ACTION%"=="pipeline_audit_gemini_pro" goto PIPELINE_AUDIT_GEMINI_PRO
if /I "%ACTION%"=="pipeline_report_annotate" goto PIPELINE_REPORT_ANNOTATE
if /I "%ACTION%"=="pipeline_all_openai_low" goto PIPELINE_ALL_OPENAI_LOW
if /I "%ACTION%"=="pipeline_all_openai_med" goto PIPELINE_ALL_OPENAI_MED
if /I "%ACTION%"=="pipeline_all_openai_high" goto PIPELINE_ALL_OPENAI_HIGH
if /I "%ACTION%"=="pipeline_all_gemini_fast" goto PIPELINE_ALL_GEMINI_FAST
if /I "%ACTION%"=="pipeline_all_gemini_pro" goto PIPELINE_ALL_GEMINI_PRO
if /I "%ACTION%"=="pipeline_audit" goto PIPELINE_AUDIT_OPENAI_LOW
if /I "%ACTION%"=="pipeline_audit_strict" goto PIPELINE_AUDIT_OPENAI_LOW
if /I "%ACTION%"=="pipeline_report" goto PIPELINE_REPORT
if /I "%ACTION%"=="pipeline_annotate" goto PIPELINE_ANNOTATE
if /I "%ACTION%"=="pipeline_all" goto PIPELINE_ALL_OPENAI_LOW
if /I "%ACTION%"=="pipeline_all_strict" goto PIPELINE_ALL_OPENAI_LOW
if /I "%ACTION%"=="open_input" goto OPEN_INPUT
if /I "%ACTION%"=="open_output" goto OPEN_OUTPUT
if /I "%ACTION%"=="open_logs" goto OPEN_LOGS
if /I "%ACTION%"=="open_work" goto OPEN_WORK
if /I "%ACTION%"=="open_config" goto OPEN_CONFIG

rem Backward-compatible direct ids from previous project/audit launchers.
if /I "%ACTION%"=="audit_critical_low_p" goto PIPELINE_ALL_OPENAI_LOW
if /I "%ACTION%"=="audit_critical_med_p" goto PIPELINE_ALL_OPENAI_MED
if /I "%ACTION%"=="audit_critical_high_p" goto PIPELINE_ALL_OPENAI_HIGH
if /I "%ACTION%"=="audit_huge_low_p" goto PIPELINE_ALL_OPENAI_LOW
if /I "%ACTION%"=="audit_huge_med_p" goto PIPELINE_ALL_OPENAI_MED
if /I "%ACTION%"=="audit_huge_high_p" goto PIPELINE_ALL_OPENAI_HIGH
if /I "%ACTION%"=="openai_menu" goto MAIN
if /I "%ACTION%"=="gemini_menu" goto MAIN

echo [ERROR] Unknown action: %ACTION%
if defined DIRECT_MODE exit /b 2
if not defined AUDION_NO_PAUSE pause
goto MAIN

:RUNPY
set "TARGET=%~1"
shift /1
if not exist "%TARGET%" (
  echo [ERROR] Script not found:
  echo %TARGET%
  exit /b 1
)
set "RUN_ARGS="
:RUNPY_ARGS
if "%~1"=="" goto RUNPY_EXEC
set "RUN_ARGS=%RUN_ARGS% "%~1""
shift /1
goto RUNPY_ARGS
:RUNPY_EXEC
"%PYTHON_EXE%" %PYTHON_ARGS% "%TARGET%"%RUN_ARGS%
exit /b %errorlevel%

:PIPELINE_SCAN
call :RUNPY "%CORE_DIR%\pipeline.py" scan
goto AFTER_ACTION

:PIPELINE_RENDER
call :RUNPY "%CORE_DIR%\pipeline.py" render --recursive --renderer com
goto AFTER_ACTION

:PIPELINE_AUDIT
goto PIPELINE_AUDIT_OPENAI_LOW

:PIPELINE_AUDIT_OPENAI_LOW
set "PIPE_AUDIT_LABEL=OpenAI audit low"
set "PIPE_PROVIDER=openai"
set "PIPE_MODEL=%OPENAI_MODEL_AUDIT%"
set "PIPE_REASONING=%OPENAI_REASONING_LOW%"
set "PIPE_TIMEOUT=%OPENAI_TIMEOUT_MEDIUM%"
set "PIPE_RETRIES=%OPENAI_MAX_RETRIES%"
set "PIPE_CHUNK=%OPENAI_CHUNK_NORMAL%"
set "PIPE_OVERLAP=%OPENAI_OVERLAP_NORMAL%"
set "PIPE_MAX_OUT=%OPENAI_MAX_OUT%"
set "PIPE_TIER=%OPENAI_TIER%"
call :RUN_PIPELINE_AUDIT_SELECTED
goto AFTER_ACTION

:PIPELINE_AUDIT_OPENAI_MED
set "PIPE_AUDIT_LABEL=OpenAI audit med"
set "PIPE_PROVIDER=openai"
set "PIPE_MODEL=%OPENAI_MODEL_AUDIT%"
set "PIPE_REASONING=%OPENAI_REASONING_MEDIUM%"
set "PIPE_TIMEOUT=%OPENAI_TIMEOUT_MEDIUM%"
set "PIPE_RETRIES=%OPENAI_MAX_RETRIES%"
set "PIPE_CHUNK=%OPENAI_CHUNK_NORMAL%"
set "PIPE_OVERLAP=%OPENAI_OVERLAP_NORMAL%"
set "PIPE_MAX_OUT=%OPENAI_MAX_OUT%"
set "PIPE_TIER=%OPENAI_TIER%"
call :RUN_PIPELINE_AUDIT_SELECTED
goto AFTER_ACTION

:PIPELINE_AUDIT_OPENAI_HIGH
set "PIPE_AUDIT_LABEL=OpenAI audit high"
set "PIPE_PROVIDER=openai"
set "PIPE_MODEL=%OPENAI_MODEL_AUDIT%"
set "PIPE_REASONING=%OPENAI_REASONING_HIGH%"
set "PIPE_TIMEOUT=%OPENAI_TIMEOUT_HIGH%"
set "PIPE_RETRIES=%OPENAI_MAX_RETRIES%"
set "PIPE_CHUNK=%OPENAI_CHUNK_NORMAL%"
set "PIPE_OVERLAP=%OPENAI_OVERLAP_NORMAL%"
set "PIPE_MAX_OUT=%OPENAI_MAX_OUT%"
set "PIPE_TIER=%OPENAI_TIER%"
call :RUN_PIPELINE_AUDIT_SELECTED
goto AFTER_ACTION

:PIPELINE_AUDIT_GEMINI_FAST
set "PIPE_AUDIT_LABEL=Gemini audit fast"
set "PIPE_PROVIDER=gemini"
set "PIPE_MODEL=%GEMINI_MODEL_FAST%"
set "PIPE_REASONING=fast"
set "PIPE_TIMEOUT=%OPENAI_TIMEOUT_MEDIUM%"
set "PIPE_RETRIES=%GEMINI_MAX_RETRIES%"
set "PIPE_CHUNK=%GEMINI_CHUNK_NORMAL%"
set "PIPE_OVERLAP=%GEMINI_OVERLAP_NORMAL%"
set "PIPE_MAX_OUT=%OPENAI_MAX_OUT%"
set "PIPE_TIER=default"
call :RUN_PIPELINE_AUDIT_SELECTED
goto AFTER_ACTION

:PIPELINE_AUDIT_GEMINI_PRO
set "PIPE_AUDIT_LABEL=Gemini audit pro"
set "PIPE_PROVIDER=gemini"
set "PIPE_MODEL=%GEMINI_MODEL_PRO%"
set "PIPE_REASONING=pro"
set "PIPE_TIMEOUT=%OPENAI_TIMEOUT_HIGH%"
set "PIPE_RETRIES=%GEMINI_MAX_RETRIES%"
set "PIPE_CHUNK=%GEMINI_CHUNK_NORMAL%"
set "PIPE_OVERLAP=%GEMINI_OVERLAP_NORMAL%"
set "PIPE_MAX_OUT=%OPENAI_MAX_OUT%"
set "PIPE_TIER=default"
call :RUN_PIPELINE_AUDIT_SELECTED
goto AFTER_ACTION

:PIPELINE_AUDIT_STRICT
goto PIPELINE_AUDIT_OPENAI_LOW

:PIPELINE_REPORT
call :RUNPY "%CORE_DIR%\pipeline.py" report --from-logs logs --report-lang en
goto AFTER_ACTION

:PIPELINE_ANNOTATE
call :RUNPY "%CORE_DIR%\pipeline.py" annotate --from-logs logs
goto AFTER_ACTION

:PIPELINE_REPORT_ANNOTATE
call :RUNPY "%CORE_DIR%\pipeline.py" report --from-logs logs --report-lang en
if errorlevel 1 goto AFTER_ACTION
call :RUNPY "%CORE_DIR%\pipeline.py" annotate --from-logs logs
goto AFTER_ACTION

:PIPELINE_ALL
goto PIPELINE_ALL_OPENAI_LOW

:PIPELINE_ALL_STRICT
goto PIPELINE_ALL_OPENAI_LOW

:PIPELINE_ALL_OPENAI_LOW
set "PIPE_AUDIT_LABEL=OpenAI audit low"
set "PIPE_PROVIDER=openai"
set "PIPE_MODEL=%OPENAI_MODEL_AUDIT%"
set "PIPE_REASONING=%OPENAI_REASONING_LOW%"
set "PIPE_TIMEOUT=%OPENAI_TIMEOUT_MEDIUM%"
set "PIPE_RETRIES=%OPENAI_MAX_RETRIES%"
set "PIPE_CHUNK=%OPENAI_CHUNK_NORMAL%"
set "PIPE_OVERLAP=%OPENAI_OVERLAP_NORMAL%"
set "PIPE_MAX_OUT=%OPENAI_MAX_OUT%"
set "PIPE_TIER=%OPENAI_TIER%"
call :RUN_PIPELINE_ALL_SELECTED
goto AFTER_ACTION

:PIPELINE_ALL_OPENAI_MED
set "PIPE_AUDIT_LABEL=OpenAI audit med"
set "PIPE_PROVIDER=openai"
set "PIPE_MODEL=%OPENAI_MODEL_AUDIT%"
set "PIPE_REASONING=%OPENAI_REASONING_MEDIUM%"
set "PIPE_TIMEOUT=%OPENAI_TIMEOUT_MEDIUM%"
set "PIPE_RETRIES=%OPENAI_MAX_RETRIES%"
set "PIPE_CHUNK=%OPENAI_CHUNK_NORMAL%"
set "PIPE_OVERLAP=%OPENAI_OVERLAP_NORMAL%"
set "PIPE_MAX_OUT=%OPENAI_MAX_OUT%"
set "PIPE_TIER=%OPENAI_TIER%"
call :RUN_PIPELINE_ALL_SELECTED
goto AFTER_ACTION

:PIPELINE_ALL_OPENAI_HIGH
set "PIPE_AUDIT_LABEL=OpenAI audit high"
set "PIPE_PROVIDER=openai"
set "PIPE_MODEL=%OPENAI_MODEL_AUDIT%"
set "PIPE_REASONING=%OPENAI_REASONING_HIGH%"
set "PIPE_TIMEOUT=%OPENAI_TIMEOUT_HIGH%"
set "PIPE_RETRIES=%OPENAI_MAX_RETRIES%"
set "PIPE_CHUNK=%OPENAI_CHUNK_NORMAL%"
set "PIPE_OVERLAP=%OPENAI_OVERLAP_NORMAL%"
set "PIPE_MAX_OUT=%OPENAI_MAX_OUT%"
set "PIPE_TIER=%OPENAI_TIER%"
call :RUN_PIPELINE_ALL_SELECTED
goto AFTER_ACTION

:PIPELINE_ALL_GEMINI_FAST
set "PIPE_AUDIT_LABEL=Gemini audit fast"
set "PIPE_PROVIDER=gemini"
set "PIPE_MODEL=%GEMINI_MODEL_FAST%"
set "PIPE_REASONING=fast"
set "PIPE_TIMEOUT=%OPENAI_TIMEOUT_MEDIUM%"
set "PIPE_RETRIES=%GEMINI_MAX_RETRIES%"
set "PIPE_CHUNK=%GEMINI_CHUNK_NORMAL%"
set "PIPE_OVERLAP=%GEMINI_OVERLAP_NORMAL%"
set "PIPE_MAX_OUT=%OPENAI_MAX_OUT%"
set "PIPE_TIER=default"
call :RUN_PIPELINE_ALL_SELECTED
goto AFTER_ACTION

:PIPELINE_ALL_GEMINI_PRO
set "PIPE_AUDIT_LABEL=Gemini audit pro"
set "PIPE_PROVIDER=gemini"
set "PIPE_MODEL=%GEMINI_MODEL_PRO%"
set "PIPE_REASONING=pro"
set "PIPE_TIMEOUT=%OPENAI_TIMEOUT_HIGH%"
set "PIPE_RETRIES=%GEMINI_MAX_RETRIES%"
set "PIPE_CHUNK=%GEMINI_CHUNK_NORMAL%"
set "PIPE_OVERLAP=%GEMINI_OVERLAP_NORMAL%"
set "PIPE_MAX_OUT=%OPENAI_MAX_OUT%"
set "PIPE_TIER=default"
call :RUN_PIPELINE_ALL_SELECTED
goto AFTER_ACTION

:RUN_PIPELINE_AUDIT_SELECTED
call :RUNPY "%CORE_DIR%\pipeline.py" audit --recursive --renderer com --provider "%PIPE_PROVIDER%" --model "%PIPE_MODEL%" --reasoning "%PIPE_REASONING%" --timeout-sec "%PIPE_TIMEOUT%" --max-retries "%PIPE_RETRIES%" --chunk-tokens "%PIPE_CHUNK%" --overlap-tokens "%PIPE_OVERLAP%" --max-output-tokens "%PIPE_MAX_OUT%" --service-tier "%PIPE_TIER%" --resume --report-lang en
exit /b %errorlevel%

:RUN_PIPELINE_ALL_SELECTED
echo.
echo [1/5] [####----------------] Scan input
echo ----------------------------------------------------------------------
call :RUNPY "%CORE_DIR%\pipeline.py" scan
if errorlevel 1 exit /b %errorlevel%
echo.
echo [2/5] [########------------] COM PDF export / render-map
echo ----------------------------------------------------------------------
call :RUNPY "%CORE_DIR%\pipeline.py" render --recursive --renderer com
if errorlevel 1 exit /b %errorlevel%
echo.
echo [3/5] [############--------] %PIPE_AUDIT_LABEL%
echo ----------------------------------------------------------------------
call :RUN_PIPELINE_AUDIT_SELECTED
if errorlevel 1 exit /b %errorlevel%
echo.
echo [4/5] [################----] Report from logs
echo ----------------------------------------------------------------------
call :RUNPY "%CORE_DIR%\pipeline.py" report --from-logs logs --report-lang en
if errorlevel 1 exit /b %errorlevel%
echo.
echo [5/5] [####################] Annotate from logs
echo ----------------------------------------------------------------------
call :RUNPY "%CORE_DIR%\pipeline.py" annotate --from-logs logs
exit /b %errorlevel%

:OPEN_INPUT
call :OPEN_DIR "%BASE_DIR%\input"
if defined DIRECT_MODE exit /b %errorlevel%
goto MAIN

:OPEN_OUTPUT
call :OPEN_DIR "%BASE_DIR%\output"
if defined DIRECT_MODE exit /b %errorlevel%
goto MAIN

:OPEN_LOGS
call :OPEN_DIR "%BASE_DIR%\logs"
if defined DIRECT_MODE exit /b %errorlevel%
goto MAIN

:OPEN_WORK
call :OPEN_DIR "%BASE_DIR%\work"
if defined DIRECT_MODE exit /b %errorlevel%
goto MAIN

:OPEN_CONFIG
call :OPEN_DIR "%BASE_DIR%\config"
if defined DIRECT_MODE exit /b %errorlevel%
goto MAIN

:OPEN_DIR
if not exist "%~1\" mkdir "%~1" >nul 2>nul
start "" explorer "%~1"
goto :eof

:RUN_DIRECT
set "DIRECT_MODE=1"
set "RAW=%~1"
call :TRIM RAW
if /I "%RAW%"=="exit" exit /b 0
call :DISPATCH "%RAW%"
set "RC=%errorlevel%"
exit /b %RC%

:AFTER_ACTION
set "RC=%errorlevel%"
if defined DIRECT_MODE exit /b %RC%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:RESOLVE_PYTHON
set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist "%BASE_DIR%\runtime\python.exe" (
  set "PYTHON_EXE=%BASE_DIR%\runtime\python.exe"
  exit /b 0
)
if exist "%BASE_DIR%\runtime\python\python.exe" (
  set "PYTHON_EXE=%BASE_DIR%\runtime\python\python.exe"
  exit /b 0
)
exit /b 1

:LOAD_LLM_SETTINGS
"%PYTHON_EXE%" "%CORE_DIR%\config_resolver.py" --cmd-env > "%LLM_ENV_FILE%"
if errorlevel 1 exit /b 1
call "%LLM_ENV_FILE%"
exit /b %errorlevel%

:NO_PYTHON
cls
echo [ERROR] Python runtime was not resolved.
echo.
echo Supported locations:
echo   runtime\python.exe
echo   runtime\python\python.exe
if not defined AUDION_NO_PAUSE pause
exit /b 1

:CONFIG_ERROR
cls
echo [ERROR] Failed to load config\llm_settings.yaml.
echo Check config files and rerun the launcher.
if not defined AUDION_NO_PAUSE pause
exit /b 1

:TRIM
for /f "tokens=* delims= " %%z in ("!%~1!") do set "%~1=%%z"
:TRIM_R
if "!%~1:~-1!"==" " set "%~1=!%~1:~0,-1!" & goto TRIM_R
goto :eof
