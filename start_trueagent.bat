@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting TrueAgent v5.9...
echo.
python -u webui\server.py
