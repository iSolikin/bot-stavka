@echo off
title StatLine Bot
cd /d D:\Bot_Stavka

echo ========================================
echo  StatLine Bot @statsline_bot
echo ========================================
echo  Запуск...

:loop
echo [%date% %time%] Запуск бота...
python main.py
echo.
echo [%date% %time%] Бот упал (код: %errorlevel%). Перезапуск через 5 сек...
timeout /t 5 /nobreak
goto loop
