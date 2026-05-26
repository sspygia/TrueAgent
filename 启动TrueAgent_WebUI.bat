@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   TrueAgent v5.9
echo   Launching WebUI...
echo ============================================

:: Start server with pythonw (no console window)
start "" /B pythonw -u webui\server.py

echo [OK] TrueAgent started. Opening browser...
echo If browser doesn't open, visit http://127.0.0.1:18765
echo.
timeout /t 3 >nul
exit
