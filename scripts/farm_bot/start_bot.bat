@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo  Farm Bot - Kingdom Realms
echo ============================================

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python не найден! Установи с https://python.org
    echo         При установке поставь галочку "Add Python to PATH"
    pause
    exit /b 1
)

if not exist "templates\tree.png" (
    echo [WARNING] Нет файла templates\tree.png !
    echo           Вырежи дерево из игры через Win+Shift+S и сохрани туда.
)
if not exist "templates\ore.png" (
    echo [WARNING] Нет файла templates\ore.png !
    echo           Вырежи руду из игры через Win+Shift+S и сохрани туда.
)

if not exist ".deps_installed" (
    echo [SETUP] Первый запуск - ставлю зависимости...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Не удалось установить зависимости.
        pause
        exit /b 1
    )
    echo ok > .deps_installed
)

echo.
echo Запускаю бота... F8 - пауза, F9 - выход
echo.
python farm_bot.py

echo.
echo Бот завершил работу.
pause
