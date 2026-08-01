@echo off
setlocal
cd /d "%~dp0"
title E2EProof Setup

echo [1/5] Checking Python...
where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if not %errorlevel%==0 (
    echo Python 3.11 or newer is required.
    echo Install it from python.org and enable Add Python to PATH.
    pause
    exit /b 1
  )
  set "PY=python"
)

%PY% -c "import sys; assert sys.version_info >= (3,11), 'Python 3.11+ required'" || goto :failed

echo [2/5] Creating isolated environment...
if not exist .venv %PY% -m venv .venv || goto :failed
call .venv\Scripts\activate.bat || goto :failed

echo [3/5] Installing E2EProof...
python -m pip install --upgrade pip setuptools wheel || goto :failed
python -m pip install --no-build-isolation -e . || goto :failed

echo [4/5] Installing Chromium...
e2eproof install-browser chromium || goto :failed

echo [5/5] Checking the environment...
e2eproof doctor --browser chromium || goto :failed

echo.
echo Setup complete. Double-click run_demo_windows.bat.
pause
exit /b 0

:failed
echo.
echo Setup failed. Copy the complete error above when asking for help.
pause
exit /b 1
