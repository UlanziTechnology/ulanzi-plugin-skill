Set objShell = WScript.CreateObject("WScript.Shell")

pluginFilePath = WScript.Arguments(0)
uxpPluginVer = WScript.Arguments(1)

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
        Exit For
    End If
Next

' check if this is the first install or update
If currentUxpPluginVer = "" Then
    ' Install the plugin
    ' If vbYes = MsgBox("This plugin requires Photoshop UXP Plugin for Streamdeck to function properly, Click yes to install.", vbYesNo, "Photoshop UXP Plugin Check") Then
        objShell.Run """C:\Program Files\Common Files\Adobe\Adobe Desktop Common\RemoteComponents\UPI\UnifiedPluginInstallerAgent\UnifiedPluginInstallerAgent.exe"" /install """ & pluginFilePath & """", 0, True
    ' End If
Else
    ' Update the plugin
    If CompareVersions(currentUxpPluginVer, uxpPluginVer) < 0 Then
        ' If vbYes = MsgBox("This plugin requires new version of Photoshop UXP Plugin for Streamdeck to function properly, Click yes to update.", vbYesNo, "Photoshop UXP Plugin Check") Then
        ' Remove the plugin
        objShell.Run """C:\Program Files\Common Files\Adobe\Adobe Desktop Common\RemoteComponents\UPI\UnifiedPluginInstallerAgent\UnifiedPluginInstallerAgent.exe"" /remove """ & pluginName & """", 0, True
        ' Wait for 3 seconds
        WScript.Sleep 3000
        ' Install the plugin
        objShell.Run """C:\Program Files\Common Files\Adobe\Adobe Desktop Common\RemoteComponents\UPI\UnifiedPluginInstallerAgent\UnifiedPluginInstallerAgent.exe"" /install """ & pluginFilePath & """", 0, True
        ' End If
    End If
End If

Function CompareVersions(version1, version2)
    Dim parts1, parts2, i

    parts1 = Split(version1, ".")
    parts2 = Split(version2, ".")

    For i = 0 To UBound(parts1)
        If CInt(parts1(i)) < CInt(parts2(i)) Then
            CompareVersions = -1
            Exit Function
        ElseIf CInt(parts1(i)) > CInt(parts2(i)) Then
            CompareVersions = 1
            Exit Function
        End If
    Next

    CompareVersions = 0
End Function