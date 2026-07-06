@echo off
REM ============================================================================
REM  MSFS 2024 Companion - Controls Setup App
REM  Double-click this file to launch the controls/bindings app.
REM  First run creates a local Python virtual environment and installs deps;
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

REM ------------------------------------------------------------ Python + deps
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment ^(first run only^)...
    py -3 -m venv .venv 2>nul || python -m venv .venv
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo ERROR: could not create a virtual environment. Is Python 3.10+ installed?
        echo Download it from https://www.python.org/downloads/ and re-run this file.
        pause
        exit /b 1
    )
    call ".venv\Scripts\activate.bat"
    python -m pip install --upgrade pip
    echo Installing the controls app and its dependencies...
    pip install -e ".[controls,openai]"
) else (
    call ".venv\Scripts\activate.bat"
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
