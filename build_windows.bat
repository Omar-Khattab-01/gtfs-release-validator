@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  python merge_gtfs.py %*
) else (
  py -3 merge_gtfs.py %*
)
exit /b %errorlevel%
