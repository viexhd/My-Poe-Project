@echo off
rem Double-click to launch Twice Corrupted.
rem Right-click -> "Run as administrator" if you want in-game hotkeys
rem (PoE runs elevated and won't accept input from unelevated processes).

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [Twice Corrupted] No venv found. Creating one and installing deps...
    py -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install --upgrade pip          || goto :fail
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt    || goto :fail
)

rem Ensure the poe_qol package itself is installed (editable) so
rem `python -m poe_qol` resolves. This is a no-op on subsequent runs.
".venv\Scripts\python.exe" -c "import poe_qol" 2>nul
if errorlevel 1 (
    echo [Twice Corrupted] Installing package in editable mode...
    ".venv\Scripts\python.exe" -m pip install -e . || goto :fail
)

".venv\Scripts\python.exe" -m poe_qol
set EXITCODE=%ERRORLEVEL%

if %EXITCODE% neq 0 (
    echo.
    echo [Twice Corrupted] exited with code %EXITCODE%
    pause
)
exit /b %EXITCODE%

:fail
echo [Twice Corrupted] setup failed.
pause
exit /b 1
