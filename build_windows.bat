@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  py -3.12 -c "import sys" >nul 2>&1
  if errorlevel 1 (
    echo Python 3.12 is recommended for the Windows build because eval7 has a prebuilt wheel for it.
    pause
    exit /b 1
  )
  py -3.12 -m venv .venv
)
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b 1
.venv\Scripts\pyinstaller.exe --noconfirm --clean --windowed --name CoinPokerTracker --icon "%~dp0assets\coinpoker_tracker.ico" --add-data "%~dp0assets\coinpoker_tracker.png;assets" app.py 
echo Built executable is under dist\CoinPokerTracker\
