@echo off
REM ============================================================
REM  Bantay-Baha: one-click raw data download (Windows)
REM
REM  Usage:
REM    download_data.bat                      open sources only
REM    download_data.bat my-gee-project-id    open sources + Earth Engine
REM                                           (IMERG, MAP friction, GFD, Sentinel-1 inventory + flood masks)
REM
REM  Needs Python 3.10+ on PATH. Safe to re-run: finished files are skipped.
REM  The venv lives outside the repo (%USERPROFILE%\.venvs\bantay-baha)
REM  so OneDrive does not sync it.
REM ============================================================
setlocal
cd /d "%~dp0"

set "VENV=%USERPROFILE%\.venvs\bantay-baha"
set "PY=%VENV%\Scripts\python.exe"
set "EE_PROJECT=%~1"

where python >nul 2>nul || (echo [ERROR] Python not found on PATH. Install Python 3.10+ first. & exit /b 1)

if not exist "%PY%" (
    echo [1/4] Creating virtual environment at %VENV% ...
    python -m venv "%VENV%" || exit /b 1
) else (
    echo [1/4] Using existing virtual environment at %VENV%
)

echo [2/4] Installing Python packages ...
"%PY%" -m pip install -q --upgrade pip
"%PY%" -m pip install -q -r requirements.txt || exit /b 1
"%PY%" -m ipykernel install --user --name bantay-baha --display-name "Python (bantay-baha)" >nul

if not exist data mkdir data
echo [3/4] Downloading open datasets (about 7 GB, can take a while) ...
"%PY%" -u scripts\download_data.py
if errorlevel 1 (
    echo [WARN] Some sources failed. Re-run this file to retry; finished files are skipped.
)

if "%EE_PROJECT%"=="" (
    echo [4/4] Skipping Earth Engine sources. To include them:
    echo         1. Register a free non-commercial project: https://code.earthengine.google.com/register
    echo         2. "%VENV%\Scripts\earthengine.exe" authenticate
    echo         3. download_data.bat ^<your-project-id^>
) else (
    echo [4/4] Downloading Earth Engine sources with project %EE_PROJECT% ...
    "%PY%" -u scripts\download_gee.py --project %EE_PROJECT%
    if errorlevel 1 echo [WARN] Earth Engine download failed. Did you run "earthengine authenticate"?
)

echo.
echo ============================================================
echo  Done. Data is in data\raw\ and the file list is in data\raw\MANIFEST.csv
echo.
echo  Manual downloads (these sites block scripts):
echo    - PSA PSGC 2Q 2026 Excel  https://psa.gov.ph/classification/psgc
echo        save to data\raw\psgc\
echo    - DOH NHFR facility list   https://nhfr.doh.gov.ph/rfacilities2list.php
echo        save to data\raw\nhfr\
echo.
echo  Then open notebooks\00_data_eda.ipynb with the "Python (bantay-baha)" kernel.
echo ============================================================
endlocal
