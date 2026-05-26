@echo off
chcp 65001 >nul
cd /d D:\Ai电脑智能体\v5.9

echo ============================================
echo   TrueAgent Hyper v6.0
echo   正在后台启动...
echo ============================================

:: 用 VBS 隐藏 CMD 窗口
set VBS=%TEMP%\trueagent_launch.vbs
echo Set WshShell = CreateObject("WScript.Shell") > "%VBS%"
echo WshShell.Run """D:\龙虾\QwenPaw\pythonw.exe"" -u webui\server.py", 0, False >> "%VBS%"
cscript //nologo "%VBS%"
del "%VBS%"

echo.
echo [OK] TrueAgent 已在后台启动
echo 浏览器应自动打开，如未打开请手动访问 http://127.0.0.1:18765
echo.
timeout /t 3 >nul
