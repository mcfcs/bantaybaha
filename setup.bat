@echo off
REM ============================================================
REM  Bantay-Baha: one-click team setup (Windows)
REM
REM  Usage:
REM    setup.bat                        everything in the team bucket (~7 GB)
REM    setup.bat dengue_hdx cchain      selected sources only (folder names in data\raw)
REM
REM  1. creates the venv at %USERPROFILE%\.venvs\bantay-baha (outside OneDrive)
REM  2. installs requirements.txt and the Jupyter kernel "Python (bantay-baha)"
REM  3. signs you in to Google once (browser), if not signed in yet
REM  4. pulls data\raw from gs://bantay-baha-raw-hackathonproper, checked against MANIFEST.csv
REM
REM  Sign in with the account that was given bucket access (your @student.ateneo.edu).
REM  Safe to re-run: finished steps and files are skipped.
REM  To rebuild from the original sources instead, use download_data.bat.
REM ============================================================
setlocal
cd /d "%~dp0"

set "VENV=%USERPROFILE%\.venvs\bantay-baha"
set "PY=%VENV%\Scripts\python.exe"
set "EE_CRED=%USERPROFILE%\.config\earthengine\credentials"

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

if exist "%EE_CRED%" (
    echo [3/4] Already signed in to Google ^(%EE_CRED%^)
) else (
    echo [3/4] Signing in to Google: a browser window will open. Use your @student.ateneo.edu account.
    "%VENV%\Scripts\earthengine.exe" authenticate --auth_mode=localhost || (echo [ERROR] Sign-in failed. Re-run setup.bat. & exit /b 1)
)

if not exist data\raw mkdir data\raw
echo [4/4] Pulling data from the team bucket (only missing files; ~7 GB the first time) ...
"%PY%" -u scripts\sync_data.py pull %*
if errorlevel 1 (
    echo [ERROR] Pull failed. If it says 403 / permission denied, you are signed in with an account that has no
    echo         bucket access: delete "%EE_CRED%" and re-run setup.bat to sign in with the right one.
    exit /b 1
)

echo.
echo ============================================================
echo  Done. Data is in data\raw\ ^(file list: data\raw\MANIFEST.csv^)
echo  Open notebooks\00_data_eda.ipynb in VS Code and pick the "Python (bantay-baha)" kernel.
echo ============================================================
endlocal
