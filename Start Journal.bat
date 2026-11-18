@echo off
setlocal
cd /d "%~dp0"
title LiAInne Journal

if exist ".venv-windows\Scripts\python.exe" goto run

echo Preparing LiAInne for Windows. This is only needed once.
echo Python and an internet connection are required for initial setup.
echo.
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 (
    py -3.12 -m venv .venv-windows
    goto created
)
py -3 -c "import sys; assert sys.version_info[:2] in [(3, 10), (3, 11), (3, 12), (3, 13)]" >nul 2>&1
if not errorlevel 1 (
    py -3 -m venv .venv-windows
    goto created
)
python -c "import sys; assert sys.version_info[:2] in [(3, 10), (3, 11), (3, 12), (3, 13)]" >nul 2>&1
if not errorlevel 1 (
    python -m venv .venv-windows
    goto created
)
echo Python 3.10 to 3.13 was not found. Install Python from https://www.python.org/downloads/windows/
echo During installation, select "Add Python to PATH", then launch this file again.
goto failed

:created
if errorlevel 1 (
    echo Could not create the Windows Python environment.
    goto failed
)

:run
".venv-windows\Scripts\python.exe" -c "import fastapi, uvicorn, dotenv, httpx, supabase, groq" >nul 2>&1
if errorlevel 1 (
    echo Installing the app dependencies. This may take a few minutes...
    ".venv-windows\Scripts\python.exe" -m pip install -r requirements-windows.txt
    if errorlevel 1 (
        echo Dependency installation failed. Check your internet connection and try again.
        goto failed
    )
)
echo Starting your journal. Keep this window open while using it.
echo Close this window or press Ctrl+C to stop the journal.
".venv-windows\Scripts\python.exe" scripts\launch_windows.py
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
pause
exit /b 1
