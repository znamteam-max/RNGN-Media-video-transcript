@echo off
cd /d "%~tp0"
if not exist .venv\Scripts\python.exe (
  echo Run SETUP_WINDOWS.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
python app.py
