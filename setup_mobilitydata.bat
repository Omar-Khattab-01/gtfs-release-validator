@echo off
setlocal
cd /d "%~dp0"
py -3 -m gtfs_validator.setup_mobilitydata
if errorlevel 1 pause
