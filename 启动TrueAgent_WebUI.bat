@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   TrueAgent v5.9
echo   Launching...
echo ============================================

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python not found. Please install Python 3.10+
    echo        https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Start server (server auto-opens browser when ready)
start "" python -u webui\server.py

echo [OK] Browser will open automatically when ready.
echo If not, visit http://127.0.0.1:18765
timeout /t 3 >nul
exit
