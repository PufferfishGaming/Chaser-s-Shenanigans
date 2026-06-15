@echo off
REM Generate desktop/folder shortcuts with proper icons.
REM (A .bat file can't carry an icon itself; a shortcut can - this makes them.)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0create_shortcuts.ps1"
echo.
pause
