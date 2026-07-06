@echo off
REM ============================================================================
REM  MSFS 2024 Companion - Controls Setup App
REM  Double-click this file to launch the controls/bindings app.
REM  On first run it creates a local .venv and installs the requirements;
REM  later runs just start the app.
REM ============================================================================
setlocal
cd /d "%~dp0"

REM ---------------------------------------------------------------- LLM provider
REM Use OpenAI for the "Ask AI" binding advisor.
set "MSFS_COMPANION_LLM=openai"
REM Optional: pick a specific model (default is gpt-4o).
REM set "MSFS_COMPANION_MODEL=gpt-4o"

REM Provide your OpenAI key. If it's already set in your Windows environment
REM this keeps it; otherwise it asks once (not stored to disk).
if "%OPENAI_API_KEY%"=="" set /p "OPENAI_API_KEY=Enter your OpenAI API key (or press Enter to skip): "

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
