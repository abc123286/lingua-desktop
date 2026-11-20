@echo off
title LINGUA Desktop - Install
cd /d "%~dp0"
echo ============================================
echo   LINGUA Desktop - one-time install
echo ============================================
where py >nul 2>nul
if errorlevel 1 (
  echo.
  echo Python is not installed.
  echo 1. Go to https://www.python.org/downloads/  and install Python 3.12
  echo 2. On the first installer screen, TICK "Add python.exe to PATH"
  echo 3. Then double-click this file again.
  pause
  exit /b
)
echo Creating a private Python folder (.venv)...
py -3 -m venv .venv
if errorlevel 1 ( echo Could not create .venv & pause & exit /b )
echo Installing parts (this takes a few minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 ( echo. & echo Install failed. Check your internet and try again. & pause & exit /b )
echo.
echo Done! Now double-click "2_START_Windows.bat".
echo (Optional, for "Others hear me": install VB-Cable from https://vb-audio.com/Cable/ )
pause
