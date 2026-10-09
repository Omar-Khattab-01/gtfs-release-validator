@echo off
setlocal
cd /d "%~dp0"
java -version
if errorlevel 1 (
  echo Install Java 17 or newer first, then run this file again.
  pause
  exit /b 1
)
py -3 -m gtfs_validator.setup_mobilitydata
if errorlevel 1 pause
