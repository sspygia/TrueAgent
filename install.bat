@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   TrueAgent v5.9 一键安装
echo ============================================
echo.

:: 1. 检查 Python
echo [1/4] 检查 Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] 未找到 Python，请先安装 Python 3.10+
    echo         下载: https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version
echo.

:: 2. 安装依赖
echo [2/4] 安装依赖...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo [FAIL] 依赖安装失败，请检查网络连接
    pause
    exit /b 1
)
echo [OK] 依赖安装完成
echo.

:: 3. 初始化数据目录
echo [3/4] 初始化数据目录...
if not exist "data" mkdir data
if not exist "data\cache" mkdir data\cache
if not exist "data\outputs" mkdir data\outputs
if not exist "data\backups" mkdir data\backups
echo [OK] 数据目录就绪
echo.

:: 4. 启动
echo [4/4] 启动 TrueAgent...
echo.
echo   首次启动会自动引导你输入 API Key
echo   浏览器将自动打开: http://127.0.0.1:18765
echo.
echo   按 Ctrl+C 停止
echo ============================================
echo.

start "" pythonw.exe -u webui\server.py
timeout /t 3 >nul
exit /b 0
