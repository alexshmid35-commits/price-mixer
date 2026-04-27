@echo off
setlocal
chcp 65001 >nul

title Price Mixer - Stop
echo Stopping Python processes with app.py...
powershell -NoProfile -Command "$killed=0; Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^py(?:thon)?(?:\.exe)?$' -and $_.CommandLine -match 'app\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $killed++ }; Write-Host ('Stopped processes: ' + $killed)"
echo.
pause
exit /b 0
