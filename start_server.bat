@echo off
setlocal EnableExtensions
chcp 65001 >nul

cd /d "%~dp0"
title Price Mixer - Start

set "ROOT_DIR=%~dp0"
set "VENV_DIR=%ROOT_DIR%.venv-win"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "ENV_FILE=%ROOT_DIR%.env"
set "PARSER_DIR=%ROOT_DIR%onliner-parser"

if defined PRICE_MIXER_RUNTIME_ROOT (
    set "RUNTIME_ROOT=%PRICE_MIXER_RUNTIME_ROOT%"
) else (
    for /d %%I in ("%ROOT_DIR%..\PriceMixer_next_runtime_*") do if not defined RUNTIME_ROOT set "RUNTIME_ROOT=%%~fI"
)

echo [1/8] Check project layout...
if not defined RUNTIME_ROOT goto no_runtime
if not exist "%RUNTIME_ROOT%\state\app_settings.json" goto no_runtime
if not exist "%ENV_FILE%" goto no_env
if not exist "%PARSER_DIR%\ui_server.py" goto no_parser

for %%D in (state data cache uploads logs backups) do if not exist "%RUNTIME_ROOT%\%%D" mkdir "%RUNTIME_ROOT%\%%D"

echo [2/8] Check Python 3.11 and Windows virtual environment...
py -3.11 --version >nul 2>&1
if errorlevel 1 goto no_python

if not exist "%PYTHON_EXE%" (
    echo Creating Windows virtual environment: .venv-win
    py -3.11 -m venv "%VENV_DIR%"
    if errorlevel 1 goto venv_failed
)

echo [3/8] Check dependencies...
"%PYTHON_EXE%" -c "import dotenv, flask, pandas, numpy, requests, openpyxl, xlrd, gspread, oauth2client" >nul 2>&1
if errorlevel 1 goto install_deps
goto check_running

:install_deps
echo Installing requirements from requirements.txt...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 goto deps_failed
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto deps_failed

:check_running
echo [4/8] Check existing services...
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5001/api/health -TimeoutSec 2; if($r.StatusCode -eq 200){ exit 0 } } catch {}; exit 1"
if errorlevel 1 goto start_parser
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5055/api/price-mixer/status -TimeoutSec 2; if($r.StatusCode -eq 200){ exit 0 } } catch {}; exit 1"
if not errorlevel 1 goto already_running
goto incomplete_running

:start_parser
echo [5/8] Start Onliner parser on port 5055...
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5055/api/price-mixer/status -TimeoutSec 2; if($r.StatusCode -eq 200){ exit 0 } } catch {}; exit 1"
if not errorlevel 1 goto parser_ready
start "Price Mixer Parser" /min /D "%ROOT_DIR%" "%PYTHON_EXE%" "%ROOT_DIR%scripts\run_parser_component.py" "%PARSER_DIR%" "%RUNTIME_ROOT%" "%PYTHON_EXE%" "%ENV_FILE%"
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(90); do { try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5055/api/price-mixer/status -TimeoutSec 2; if($r.StatusCode -eq 200){ exit 0 } } catch {}; Start-Sleep -Milliseconds 700 } while((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 goto parser_failed

:parser_ready
echo [6/8] Start background worker...
start "Price Mixer Worker" /min /D "%ROOT_DIR%" "%PYTHON_EXE%" "%ROOT_DIR%scripts\run_parallel_component.py" worker "%ROOT_DIR%" "%RUNTIME_ROOT%" 5001 "%ENV_FILE%" "%PYTHON_EXE%"
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(15); do { if(Test-Path '%RUNTIME_ROOT%\state\parallel-worker.pid'){ $p=[int](Get-Content '%RUNTIME_ROOT%\state\parallel-worker.pid' -ErrorAction SilentlyContinue); if(Get-Process -Id $p -ErrorAction SilentlyContinue){ exit 0 } }; Start-Sleep -Milliseconds 500 } while((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 goto worker_failed

echo [7/8] Start Price Mixer web server on port 5001...
start "Price Mixer Web" /min /D "%ROOT_DIR%" "%PYTHON_EXE%" "%ROOT_DIR%scripts\run_parallel_component.py" web "%ROOT_DIR%" "%RUNTIME_ROOT%" 5001 "%ENV_FILE%" "%PYTHON_EXE%"

echo [8/8] Wait for server and open browser...
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(90); do { try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5001/api/health -TimeoutSec 2; if($r.StatusCode -eq 200){ Start-Process 'http://127.0.0.1:5001'; exit 0 } } catch {}; Start-Sleep -Milliseconds 700 } while((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 goto start_failed

where ssh >nul 2>&1
if errorlevel 1 echo WARNING: Windows OpenSSH Client is not installed. IVEN_ZAKAZ reserve download may be unavailable.

echo.
echo Price Mixer, worker and parser are running.
echo Runtime: %RUNTIME_ROOT%
exit /b 0

:already_running
echo Price Mixer and parser are already running. Opening browser...
start "" "http://127.0.0.1:5001"
exit /b 0

:incomplete_running
echo.
echo An incomplete old Price Mixer process is running on port 5001.
echo Run stop_server.bat once, then run start_server.bat again.
echo.
pause
exit /b 1

:no_runtime
echo.
echo Runtime folder was not found.
echo Put these folders next to each other:
echo   PriceMixer_next_2026-07-24
echo   PriceMixer_next_runtime_2026-07-24
echo.
pause
exit /b 1

:no_env
echo.
echo Configuration file not found: %ENV_FILE%
echo.
pause
exit /b 1

:no_parser
echo.
echo Onliner parser not found: %PARSER_DIR%
echo.
pause
exit /b 1

:no_python
echo.
echo Python 3.11 was not found.
echo Install it from python.org with the Python Launcher, then run this file again.
echo.
pause
exit /b 1

:venv_failed
echo.
echo Failed to create .venv-win.
echo.
pause
exit /b 1

:deps_failed
echo.
echo Failed to install dependencies.
echo Run install_requirements.bat and check the errors.
echo.
pause
exit /b 1

:parser_failed
echo.
echo Parser did not respond on http://127.0.0.1:5055
echo Check: %RUNTIME_ROOT%\logs\parallel-parser.log
echo.
pause
exit /b 1

:worker_failed
echo.
echo Background worker did not start.
echo Check: %RUNTIME_ROOT%\logs\parallel-worker.log
echo.
pause
exit /b 1

:start_failed
echo.
echo Server did not respond on http://127.0.0.1:5001
echo Check: %RUNTIME_ROOT%\logs\parallel-web.log
echo.
pause
exit /b 1
