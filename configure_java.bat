@echo off
setlocal
cd /d "%~dp0"
py -3 -m gtfs_validator.java_runtime
pause
