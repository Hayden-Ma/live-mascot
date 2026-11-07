' 隐藏窗口启动网易云点歌服务（登录 Windows 后自动运行）
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

projectDir = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
logDir = projectDir & "\logs"
If Not fso.FolderExists(logDir) Then
  fso.CreateFolder(logDir)
End If

cmd = "cmd /c cd /d """ & projectDir & """ && node scripts\start_netease.cjs >> """ & logDir & "\netease-api.log"" 2>&1"
shell.Run cmd, 0, False
