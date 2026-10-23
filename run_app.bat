@echo off
rem Start the Bantay-Baha dashboard (needs a finished `python scripts\build.py`).
rem Runs from the repo folder so Streamlit picks up .streamlit\config.toml (theme, no developer menu).
set PY=%USERPROFILE%\.venvs\bantay-baha\Scripts\python.exe
if not exist "%PY%" (
  echo Run download_data.bat first to create the environment.
  exit /b 1
)
cd /d "%~dp0"
"%PY%" -m streamlit run "app\streamlit_app.py" %*
