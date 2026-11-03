' check PTS is opened
Set PTSProcessList = GetObject("winmgmts:").ExecQuery("select * from win32_process where name='Photoshop.EXE'")

If PTSProcessList.Count = 0 Then
    ' MsgBox "PTS Not Running"
    WScript.Echo "NotRunning"
End If