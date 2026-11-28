@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto setup_error
)

".venv\Scripts\python.exe" -c "import intentaware, PySide6" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -e .
    if errorlevel 1 goto setup_error
)

".venv\Scripts\python.exe" -m intentaware %*
if errorlevel 1 pause
exit /b

:setup_error
echo Setup failed. Install Python 3.11 or newer and follow README.md.
pause
exit /b 1
