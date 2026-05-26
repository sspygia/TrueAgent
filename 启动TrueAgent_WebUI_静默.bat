@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   TrueAgent v5.9
echo   Silent launch (no console)...
echo ============================================

:: Launch with VBS hidden window
set VBS=%TEMP%\trueagent_launch.vbs
echo Set WshShell = CreateObject("WScript.Shell") > "%VBS%"
echo WshShell.Run """python"" -u webui\server.py", 0, False >> "%VBS%"
cscript //nologo "%VBS%"
del "%VBS%"

echo.
echo [OK] TrueAgent running in background
echo Visit http://127.0.0.1:18765
echo.
timeout /t 3 >nul
