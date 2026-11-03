Set objShell = WScript.CreateObject("WScript.Shell")

Dim currentUxpPluginVer
Dim pluginName
pluginName = "UlanziDeck Plugin for Photoshop"
' list installed the plugin
Set objExec = objShell.Exec("C:\Program Files\Common Files\Adobe\Adobe Desktop Common\RemoteComponents\UPI\UnifiedPluginInstallerAgent\UnifiedPluginInstallerAgent.exe /list all")
output = objExec.StdOut.ReadAll()

' get the current version of the plugin
lines = Split(output, vbCrLf)
For Each line in lines
    If InStr(line, pluginName) > 0 Then
        words = Split(line)
        currentUxpPluginVer = words(UBound(words))
    End If

    If InStr(line, "Disabled") > 0 Then
        WScript.Echo "Disabled"
        WScript.Quit
        Exit For
    End If
Next

If currentUxpPluginVer = "" Then
    WScript.Echo "Disabled"
End If

