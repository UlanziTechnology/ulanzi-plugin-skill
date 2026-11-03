Set objShell = WScript.CreateObject("WScript.Shell")

pluginFilePath = WScript.Arguments(0)
Dim pluginName
pluginName = "UlanziDeck Plugin for Photoshop"

objShell.Run """C:\Program Files\Common Files\Adobe\Adobe Desktop Common\RemoteComponents\UPI\UnifiedPluginInstallerAgent\UnifiedPluginInstallerAgent.exe"" /remove """ & pluginName & """", 0, True
' Wait for 1 seconds
WScript.Sleep 1000
' Install the plugin
objShell.Run """C:\Program Files\Common Files\Adobe\Adobe Desktop Common\RemoteComponents\UPI\UnifiedPluginInstallerAgent\UnifiedPluginInstallerAgent.exe"" /install """ & pluginFilePath & """", 0, True
' End If
