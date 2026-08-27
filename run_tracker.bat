@echo off
setlocal
cd /d "%~dp0"

if not exist .venv\Scripts\python.exe call :createcompatible
if not exist .venv\Scripts\python.exe goto no_python

.venv\Scripts\python.exe -m pip install -r requirements.txt
if not errorlevel 1 goto run

rem Older tracker releases may have created a Windows venv with Python 3.13+.
rem eval7 0.1.11 currently has Windows binary wheels through CPython 3.12,
rem so rebuild with a compatible installed interpreter if dependency install fails.
echo.
echo Dependency install failed. Rebuilding the environment for exact poker equity...
rmdir /s /q .venv
call :createcompatible
if not exist .venv\Scripts\python.exe goto dependency_error
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto dependency_error

goto run

:createcompatible
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  py -3.12 -m venv .venv
  exit /b
)
py -3.11 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  py -3.11 -m venv .venv
  exit /b
)
py -3.10 -c "import sys" >nul 2>&1
if not errorlevel 1 (
  py -3.10 -m venv .venv
  exit /b
)
exit /b

:run
echo.
echo Starting CoinPoker Tracker...
.venv\Scripts\python.exe app.py
set "APP_EXIT=%ERRORLEVEL%"
if "%APP_EXIT%"=="0" exit /b 0
echo.
echo CoinPoker Tracker stopped with error code %APP_EXIT%.
echo The Python error is shown above. Please send a screenshot of this window if it happens again.
pause
exit /b %APP_EXIT%

:no_python
echo Python 3.10, 3.11, or 3.12 was not found.
echo Install 64-bit Python 3.12 from python.org, then run this file again.
pause
exit /b 1

:dependency_error
echo.
echo Could not install the exact equity engine.
echo For accurate preflop All-in Adj BB on Windows, install 64-bit Python 3.12,
echo delete the .venv folder, and run run_tracker.bat again.
pause
exit /b 1
