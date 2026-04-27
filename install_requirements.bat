@echo off
setlocal
chcp 65001 >nul

cd /d "%~dp0"
title Price Mixer - Install Requirements

py -3.11 --version >nul 2>&1
if errorlevel 1 goto no_python

py -3.11 -m pip install -r requirements.txt
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
