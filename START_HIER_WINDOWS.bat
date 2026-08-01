@echo off
setlocal
cd /d "%~dp0"
title E2EProof Start
if not exist .venv\Scripts\python.exe (
  echo First-time setup will now start.
  call setup_windows.bat
  if errorlevel 1 exit /b 1
)
call run_demo_windows.bat
exit /b %errorlevel%
