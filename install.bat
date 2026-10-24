@echo off
REM ============================================================
REM  Bantay-Baha: install only (Windows). Creates the Python environment and installs requirements.txt;
REM  downloads no data. Use it to open the dashboard on the pre-computed results (run_app.bat afterwards).
REM  To download the raw data and rebuild everything instead, use download_data.bat, then build.bat.
REM
REM  Needs Python 3.11+ on PATH (tested with 3.13). Safe to re-run.
REM  The venv lives outside this folder (%USERPROFILE%\.venvs\bantay-baha) so cloud-synced folders stay small.
REM ============================================================
setlocal
cd /d "%~dp0"

set "VENV=%USERPROFILE%\.venvs\bantay-baha"
set "PY=%VENV%\Scripts\python.exe"

where python >nul 2>nul || (echo [ERROR] Python not found on PATH. Install Python 3.11+ first. & exit /b 1)

if not exist "%PY%" (
    echo [1/2] Creating virtual environment at %VENV% ...
    python -m venv "%VENV%" || exit /b 1
) else (
    echo [1/2] Using existing virtual environment at %VENV%
)

echo [2/2] Installing Python packages (a few minutes the first time) ...
"%PY%" -m pip install -q --upgrade pip
"%PY%" -m pip install -q -r requirements.txt || exit /b 1

echo.
echo  Done. Start the dashboard with run_app.bat (it opens http://localhost:8501).
endlocal
