@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if errorlevel 1 (
  echo Python 3 was not found. Install Python from https://www.python.org/downloads/windows/
  echo During installation, select "Add Python to PATH" and install the Python launcher.
  pause
  exit /b 1
)

py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
  echo GTFS Validator requires Python 3.10 or newer.
  pause
  exit /b 1
)

echo Starting the local GTFS Validator...
py -3 -m gtfs_validator serve --open
if errorlevel 1 pause
