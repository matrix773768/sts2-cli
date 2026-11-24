@echo off
setlocal
cd /d "%~dp0..\.."
if not defined INF1_PYTHON set "INF1_PYTHON=python.exe"
"%INF1_PYTHON%" -X utf8 -m tools.training_manager.dashboard %*
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
