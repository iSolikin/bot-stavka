@echo off
chcp 65001 >nul
echo.
echo  ╔══════════════════════════════════════╗
echo  ║     Esports Analytics — Website     ║
echo  ╚══════════════════════════════════════╝
echo.
echo  Сайт будет доступен по адресу:
echo  http://localhost:8000
echo.
echo  Для остановки нажми Ctrl+C
echo.

cd /d "%~dp0"

REM Активируем venv если есть
if exist ".venv\Scripts\activate.bat" (
    echo  [OK] Активирую виртуальное окружение...
    call .venv\Scripts\activate.bat
) else (
    echo  [!] venv не найден, используем системный Python
)

REM Проверяем что uvicorn установлен
python -c "import uvicorn" 2>nul
if errorlevel 1 (
    echo.
    echo  [!] uvicorn не найден. Устанавливаю зависимости...
    pip install fastapi "uvicorn[standard]" aiosqlite --quiet
)

echo.
echo  Запуск сервера...
echo.

:loop
D:\Bot_Stavka\.venv\Scripts\python.exe -m uvicorn web_app:app --host 0.0.0.0 --port 8000
echo.
echo  [!] Сервер упал, перезапуск через 5 сек...
timeout /t 5 /nobreak >nul
goto loop
