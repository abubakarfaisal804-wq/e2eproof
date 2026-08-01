@echo off
setlocal
cd /d "%~dp0"
if not exist .venv\Scripts\e2eproof.exe (
  echo E2EProof is not set up yet. Run setup_windows.bat first.
  pause
  exit /b 2
)
call .venv\Scripts\activate.bat
call e2eproof demo --browser chromium
set "CODE=%ERRORLEVEL%"
echo.
if "%CODE%"=="0" (
  echo PASS: the real browser-to-backend proof completed.
) else (
  echo FAIL: inspect the report and error above.
)
pause
exit /b %CODE%
