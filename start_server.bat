@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"
title Price Mixer - Start

set "VENV_DIR=%~dp0.venv-win"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

echo [1/5] Check Python 3.11 and Windows virtual environment...
py -3.11 --version >nul 2>&1
if errorlevel 1 goto no_python

if not exist "%PYTHON_EXE%" (
    echo Creating Windows virtual environment: .venv-win
    py -3.11 -m venv "%VENV_DIR%"
    if errorlevel 1 goto venv_failed
)

echo [2/5] Check if server is already running...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5001/api/health -TimeoutSec 2; if($r.StatusCode -eq 200){ exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 goto already_running

echo [3/5] Check dependencies...
"%PYTHON_EXE%" -c "import dotenv, flask, pandas, numpy, requests, openpyxl, xlrd, gspread, oauth2client" >nul 2>&1
if errorlevel 1 goto install_deps
goto start_server

:install_deps
echo Installing requirements from requirements.txt...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 goto deps_failed
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto deps_failed

:start_server
echo [4/5] Start server...
start "Price Mixer Server" /D "%~dp0" cmd /k ""%PYTHON_EXE%" app.py"

echo [5/5] Wait for server and open browser...
powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(60); do { try { $r=Invoke-WebRequest -UseBasicParsing http://127.0.0.1:5001/api/health -TimeoutSec 2; if($r.StatusCode -eq 200){ Start-Process 'http://127.0.0.1:5001'; exit 0 } } catch {}; Start-Sleep -Milliseconds 700 } while((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 goto start_failed

echo Done.
exit /b 0

:already_running
echo Server is already running. Opening browser...
start "" "http://127.0.0.1:5001"
exit /b 0

:no_python
echo.
echo Python 3.11 was not found.
echo Install it with:
echo     py install 3.11
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

:start_failed
echo.
echo Server did not respond on http://127.0.0.1:5001
echo Check the "Price Mixer Server" window.
echo.
pause
exit /b 1
