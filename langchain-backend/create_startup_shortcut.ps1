$startupPath = [Environment]::GetFolderPath('Startup')
$WshShell = New-Object -ComObject WScript.Shell
$shortcut = $WshShell.CreateShortcut("$startupPath\LottoAI_Server.lnk")
$shortcut.TargetPath = "C:\Users\psdet\Desktop\로또개발\langchain-backend\start_server_silent.vbs"
$shortcut.WorkingDirectory = "C:\Users\psdet\Desktop\로또개발\langchain-backend"
$shortcut.Description = "Lotto AI Python Backend Server"
$shortcut.Save()
Write-Host "Startup shortcut created at: $startupPath\LottoAI_Server.lnk"
