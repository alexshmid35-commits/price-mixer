@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"
title Price Mixer - Install Requirements

set "VENV_DIR=%~dp0.venv-win"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"

py -3.11 --version >nul 2>&1
if errorlevel 1 goto no_python

if not exist "%PYTHON_EXE%" (
    echo Creating Windows virtual environment: .venv-win
    py -3.11 -m venv "%VENV_DIR%"
    if errorlevel 1 goto venv_failed
)

"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 goto deps_failed
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 goto deps_failed
echo.
pause
exit /b 0

:no_python
echo Python 3.11 was not found.
echo Run:
echo     py install 3.11
echo.
pause
exit /b 1

:venv_failed
echo Failed to create .venv-win.
echo.
pause
exit /b 1

:deps_failed
echo Failed to install dependencies.
echo.
pause
exit /b 1
