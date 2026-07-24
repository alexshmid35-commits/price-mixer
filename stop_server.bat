@echo off
setlocal
chcp 65001 >nul

title Price Mixer - Stop
echo Stopping Price Mixer server processes...
powershell -NoProfile -Command "$killed=0; Get-CimInstance Win32_Process | Where-Object { ($_.Name -match '^(?:py|python|cmd)(?:\.exe)?$') -and $_.CommandLine -match 'app\.py' -and $_.CommandLine -match 'PriceMixer_v4_REFACTORED|\.venv-win' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $killed++ }; Write-Host ('Stopped processes: ' + $killed)"
echo.
pause
exit /b 0
