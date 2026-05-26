@echo off
chcp 65001 >nul
cd /d D:\Ai电脑智能体\v5.9

echo ============================================
echo   TrueAgent Hyper v5.9
echo   正在后台启动...
echo ============================================

:: 启动服务器并立即关闭 CMD（不等待服务器退出）
start "" /B "D:\龙虾\QwenPaw\pythonw.exe" -u webui\server.py

echo [OK] TrueAgent 已启动，浏览器将自动打开
echo 如未自动打开，请访问 http://127.0.0.1:18765
echo.
timeout /t 3 >nul
exit
