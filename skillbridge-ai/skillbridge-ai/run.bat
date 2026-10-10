@echo off
setlocal
cd /d "%~dp0"
title SkillBridge AI

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (where python >nul 2>nul && set "PY=python")
if not defined PY (
  echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
  echo and tick "Add python.exe to PATH" during setup. Then run this file again.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo Creating a private Python environment, first run only...
  %PY% -m venv .venv
  if errorlevel 1 ( echo Could not create the environment. & pause & exit /b 1 )
)

echo Installing requirements, first run takes about a minute...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 ( echo Install failed. Check your internet connection and run again. & pause & exit /b 1 )

if not exist ".env" copy ".env.example" ".env" >nul

if not defined PORT set "PORT=8000"
echo.
echo  SkillBridge AI is running at  http://127.0.0.1:%PORT%
echo  Keep this window open. Press Ctrl+C to stop.
echo.
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:%PORT%"
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
pause
