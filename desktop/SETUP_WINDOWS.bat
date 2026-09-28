@echo off
setlocal
cd /d "%~tp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ not found. Install Python and rerun.
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~tp0bootstrap_tools.ps1"
echo.
echo Setup complete.
pause
