@echo off
REM ============================================================================
REM  MSFS 2024 Companion - Controls Setup App
REM  Double-click this file to launch the controls/bindings app.
REM  On first run it creates a local .venv and installs the requirements;
REM  later runs just start the app.
REM ============================================================================
setlocal
cd /d "%~dp0"

REM ---------------------------------------------------------------- LLM config
REM The AI provider, model, and API key are read from msfs-companion.conf.
REM On first run we create it from the example so you can edit it.
if not exist "msfs-companion.conf" (
    echo Creating msfs-companion.conf - edit it to set your AI provider and key.
    copy /y "msfs-companion.conf.example" "msfs-companion.conf" >nul
)

REM ------------------------------------------------------- 1) ensure a .venv
if not exist ".venv\Scripts\python.exe" (
    echo No virtual environment found - creating .venv ...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo ERROR: could not create a virtual environment. Is Python 3.10+ installed?
        echo Download it from https://www.python.org/downloads/ and re-run this file.
        pause
        exit /b 1
    )
)

call ".venv\Scripts\activate.bat"

REM -------------------------------------------- 2) ensure requirements installed
REM The marker file is written only after a successful install, so a half-finished
REM or failed first install is retried on the next run instead of being skipped.
if not exist ".venv\.deps-installed" (
    echo Installing the controls app and its requirements ^(first run only^)...
    python -m pip install --upgrade pip
    pip install -e ".[controls,openai]"
    if errorlevel 1 (
        echo.
        echo ERROR: installing requirements failed. Check your internet connection
        echo and re-run this file to try again.
        pause
        exit /b 1
    )
    echo installed > ".venv\.deps-installed"
)

REM -------------------------------------------------------------------- Launch
echo Starting the controls setup app...
python -m controls_app
set "EXITCODE=%ERRORLEVEL%"

if not "%EXITCODE%"=="0" (
    echo.
    echo The app exited with code %EXITCODE%.
    pause
)
endlocal
