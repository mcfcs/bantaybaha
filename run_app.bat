@echo off
rem Start the Bantay-Baha dashboard (needs a finished `python scripts\build.py`).
set PY=%USERPROFILE%\.venvs\bantay-baha\Scripts\python.exe
if not exist "%PY%" (
  echo Run download_data.bat first to create the environment.
  exit /b 1
)
"%PY%" -m streamlit run "%~dp0app\streamlit_app.py"
