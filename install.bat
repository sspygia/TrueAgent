@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   TrueAgent v5.9 一键安装
echo ============================================
echo.

:: 1. 检查 Python
echo [1/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python not found. Please install Python 3.10+
    echo        https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version
echo.

:: 2. 安装依赖 (using python -m pip for reliability)
echo [2/4] Installing dependencies...
python -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo [FAIL] Dependency installation failed. Check your network.
    echo        Try: python -m pip install -r requirements.txt
    pause
    exit /b 1
)
echo [OK] Dependencies installed
echo.

:: 3. 初始化数据目录
echo [3/4] Initializing data directories...
if not exist "data" mkdir data
if not exist "data\cache" mkdir data\cache
if not exist "data\outputs" mkdir data\outputs
if not exist "data\backups" mkdir data\backups
echo [OK] Data directories ready
echo.

:: 4. 提示下一步
echo [4/4] Ready to start!
echo.
echo   To launch: double-click 启动TrueAgent_WebUI.bat
echo   First launch: enter your DeepSeek API Key (get one at https://platform.deepseek.com)
echo   Browser will open at: http://127.0.0.1:18765
echo ============================================
echo.
pause
exit /b 0
