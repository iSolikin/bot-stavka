@echo off
:loop
cd /d D:\Bot_Stavka
echo %date% %time% - Bot starting... >> D:\Bot_Stavka\bot.log
"D:\Bot_Stavka\.venv\Scripts\python.exe" main.py >> D:\Bot_Stavka\bot.log 2>> D:\Bot_Stavka\bot_err.log
echo %date% %time% - Bot stopped, restarting in 5s... >> D:\Bot_Stavka\bot.log
timeout /t 5 /nobreak >nul
goto loop
