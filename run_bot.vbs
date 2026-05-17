Dim oShell
Set oShell = CreateObject("WScript.Shell")
oShell.Run "cmd.exe /c D:\Bot_Stavka\run_bot.bat", 0, False
Set oShell = Nothing
