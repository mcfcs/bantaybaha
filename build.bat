@echo off
rem One-command rebuild: everything the dashboard reads, from data\raw\ to data\processed\.
rem Usage: build.bat            (all stages)      build.bat panel forecast   (selected stages)
rem Missing inputs (GEE, PSGC, NHFR, unfinished downloads) are skipped with a warning; re-run when they arrive.
set PY=%USERPROFILE%\.venvs\bantay-baha\Scripts\python.exe
if not exist "%PY%" (
  echo Run download_data.bat first to create the environment.
  exit /b 1
)
cd /d "%~dp0"
"%PY%" -u scripts\build.py %*
