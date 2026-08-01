@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
call .venv\Scripts\activate.bat
start "E2EProof demo server" /min cmd /c "call .venv\Scripts\activate.bat && python demo\server.py"
timeout /t 2 /nobreak >nul

echo Each contract below is intentionally broken and SHOULD FAIL.
for %%F in (fake-success duplicate fallback console-error accessibility) do (
  echo.
  echo ===== %%F =====
  e2eproof run examples\%%F.yaml
  if !errorlevel! EQU 0 (
    echo UNEXPECTED PASS: %%F
    set "BAD=1"
  ) else (
    echo Expected failure detected: %%F
  )
)
if defined BAD (
  echo.
  echo One or more broken fixtures passed unexpectedly.
  pause
  exit /b 1
)
echo.
echo All intentionally broken fixtures were rejected.
pause
exit /b 0
