@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  Farm Bot - Kingdom Realms
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found! Install from https://python.org
    echo         Check "Add Python to PATH" during install.
    pause
    exit /b 1
)

if not exist "templates\tree.png" (
    echo [WARNING] templates\tree.png missing!
)
if not exist "templates\ore.png" (
    echo [WARNING] templates\ore.png missing!
)

if not exist ".deps_installed" (
    echo [SETUP] First run - installing dependencies...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies.
        pause
        exit /b 1
    )
    echo ok > .deps_installed
)

echo.
echo Starting bot... F8 = pause, F9 = quit
echo.
python -u farm_bot.py

echo.
echo Bot stopped.
pause
