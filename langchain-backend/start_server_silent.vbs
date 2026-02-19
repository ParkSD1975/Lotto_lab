Set WshShell = CreateObject("WScript.Shell")
Dim scriptPath
scriptPath = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\"))
WshShell.Run chr(34) & scriptPath & "start_server.bat" & chr(34), 0
Set WshShell = Nothing
