@echo off
cd /d "%~dp0"
REM Build a standalone Windows .exe of Chaser's Shenanigans (launcher + 3 tools).
REM Uses the project's .venv if present (run install.bat first), else system python.

set "VPY=.venv\Scripts\python.exe"
if not exist "%VPY%" set "VPY=python"

echo Ensuring PyInstaller is installed ...
"%VPY%" -m pip install --upgrade pyinstaller

REM IMPORTANT: the --name has NO apostrophe. PyInstaller writes this value
REM verbatim into a generated .spec (a Python file) as name='...'; an apostrophe
REM there terminates the string and breaks the build with a SyntaxError. The
REM running app still shows "Chaser's Shenanigans" in its title bar and on the
REM taskbar (that comes from the code, not the filename), so only the .exe file
REM name differs: "Chasers Shenanigans.exe".
REM
REM  - launcher.py is the entry point; it imports all three tool windows.
REM  - fonts/ and icon.ico are bundled; icon.ico is also the exe's file icon.
REM  - --collect-all pillow_heif bundles libheif so HEIF works in the package.
REM  - --clean discards any stale build cache / old .spec.
"%VPY%" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name "Chasers Shenanigans" ^
  --icon "icon.ico" ^
  --add-data "fonts;fonts" ^
  --add-data "icon.ico;." ^
  --collect-all pillow_heif ^
  launcher.py

if errorlevel 1 (
  echo.
  echo [ERROR] Build FAILED - see the messages above. No .exe was produced.
) else (
  echo.
  echo Built "dist\Chasers Shenanigans.exe"
)
pause
