@echo off
title LINGUA Desktop
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run 1_INSTALL_Windows.bat first.
  pause
  exit /b
)
".venv\Scripts\python.exe" -m lingua
if errorlevel 1 pause
