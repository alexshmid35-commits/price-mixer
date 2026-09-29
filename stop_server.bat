@echo off
setlocal EnableExtensions
chcp 65001 >nul

cd /d "%~dp0"
title Price Mixer - Stop

set "ROOT_DIR=%~dp0"
if defined PRICE_MIXER_RUNTIME_ROOT (
    set "RUNTIME_ROOT=%PRICE_MIXER_RUNTIME_ROOT%"
) else (
    for /d %%I in ("%ROOT_DIR%..\PriceMixer_next_runtime_*") do if not defined RUNTIME_ROOT set "RUNTIME_ROOT=%%~fI"
)

echo Stopping Price Mixer web, worker and parser...
set "PRICE_MIXER_STOP_ROOT=%ROOT_DIR%"
powershell -NoProfile -Command "$root=$env:PRICE_MIXER_STOP_ROOT; $targets=Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(?:py|python|pythonw)(?:\.exe)?$' -and $_.CommandLine -like ('*' + $root + '*') -and ($_.CommandLine -match 'app\.py|run_parallel_component\.py|run_parser_component\.py|price_mixer\.workers\.durable_worker') }; $count=0; foreach($p in $targets){ Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue; $count++ }; Write-Host ('Stopped processes: ' + $count)"

if defined RUNTIME_ROOT (
    del /q "%RUNTIME_ROOT%\state\parallel-web.pid" 2>nul
    del /q "%RUNTIME_ROOT%\state\parallel-worker.pid" 2>nul
    del /q "%RUNTIME_ROOT%\state\parallel-parser.pid" 2>nul
)

echo Done.
echo.
pause
exit /b 0
