@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Chaser's Shenanigans - installer
echo ============================================
echo.

REM Find Python: prefer the 'py' launcher, fall back to 'python'.
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo [ERROR] Python was not found on PATH.
  echo Install Python 3.10+ from https://www.python.org/downloads/
  echo Tick "Add python.exe to PATH" in the installer, then re-run this.
  pause
  exit /b 1
)
echo Using Python: %PY%
%PY% --version
echo.

REM Create an isolated virtual environment in .venv (keeps your global
REM Python clean - important since HEIF wheels differ between your x64 and
REM ARM64 machines, so each gets its own correct install).
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment in .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo [ERROR] Could not create the virtual environment.
    pause
    exit /b 1
  )
)
set "VPY=.venv\Scripts\python.exe"

echo Upgrading pip ...
"%VPY%" -m pip install --upgrade pip
echo.
echo Installing dependencies (this can take a few minutes - PySide6 is large)...
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [WARNING] An install step reported an error.
  echo If the ONLY thing that failed was 'pillow-heif', the app still works -
  echo HEIF/HEIC/HIF conversion is simply disabled. Everything else runs.
)

echo.
echo Checking optional HEIF support ...
"%VPY%" -c "import pillow_heif; print('  HEIF support: OK')" 2>nul || echo   HEIF support: NOT available (pillow-heif missing - the rest works fine)

echo.
echo ============================================
echo   Done. Double-click run.bat to start.
echo ============================================
pause
