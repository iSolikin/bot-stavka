@echo off
chcp 65001 >nul
echo.
echo  ╔══════════════════════════════════════╗
echo  ║    Установка зависимостей проекта   ║
echo  ╚══════════════════════════════════════╝
echo.

cd /d "%~dp0"

REM Проверяем Python
python --version 2>nul
if errorlevel 1 (
    echo  [ОШИБКА] Python не найден. Установи Python 3.11+
    pause
    exit /b 1
)

REM Создаём venv если нет
if not exist ".venv" (
    echo  [1/4] Создаю виртуальное окружение...
    python -m venv .venv
)

REM Активируем
echo  [2/4] Активирую окружение...
call .venv\Scripts\activate.bat

REM Устанавливаем зависимости
echo  [3/4] Устанавливаю пакеты (может занять 1-3 минуты)...
pip install -r requirements.txt --quiet

REM Устанавливаем playwright браузер
echo  [4/4] Устанавливаю Playwright Chromium...
playwright install chromium

echo.
echo  ✅ Всё установлено!
echo.
echo  Для запуска бота:       start_bot.bat
echo  Для запуска сайта:      start_web.bat
echo.
pause
