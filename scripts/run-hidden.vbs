' Starts the background service with no window. Used by the Startup-folder shortcut
' that install-background.bat creates.
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
cmd = "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & here & "\background-windows.ps1"""
CreateObject("WScript.Shell").Run cmd, 0, False
