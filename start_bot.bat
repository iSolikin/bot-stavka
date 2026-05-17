@echo off
title StatLine Bot
cd /d D:\Bot_Stavka

echo ========================================
echo  StatLine Bot + Web @statsline_bot
echo ========================================
echo  Запуск...

REM Запускаем веб-сервер в отдельном окне
echo [%date% %time%] Запуск веб-сервера на порту 8000...
start "StatLine Web" /min D:\Bot_Stavka\start_web.bat

REM Небольшая пауза чтобы веб успел запуститься
timeout /t 3 /nobreak >nul

:loop
echo [%date% %time%] Запуск бота...
D:\Bot_Stavka\.venv\Scripts\python.exe main.py
echo.
echo [%date% %time%] Бот упал (код: %errorlevel%). Перезапуск через 5 сек...
timeout /t 5 /nobreak
goto loop
