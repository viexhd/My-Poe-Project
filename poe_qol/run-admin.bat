@echo off
rem Launches run.bat elevated so in-game hotkeys reach Path of Exile.
rem Double-click this; accept the UAC prompt.

setlocal
cd /d "%~dp0"

rem Already elevated?  Just run.
net session >nul 2>&1
if %ERRORLEVEL% equ 0 (
    call "%~dp0run.bat"
    exit /b %ERRORLEVEL%
)

rem Re-launch ourselves elevated via PowerShell's Start-Process.
powershell -NoProfile -Command ^
    "Start-Process -FilePath '%~dp0run.bat' -Verb RunAs -WorkingDirectory '%~dp0'"
exit /b 0
