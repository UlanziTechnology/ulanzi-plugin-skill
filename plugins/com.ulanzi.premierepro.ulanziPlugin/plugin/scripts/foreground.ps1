# Read-only foreground check. Does not activate windows or inject keys.
param([switch]$Persistent)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class UlanziPremiereForeground {
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  [DllImport("kernel32.dll", SetLastError = true)] static extern IntPtr OpenProcess(uint access, bool inherit, uint processId);
  [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)] static extern bool QueryFullProcessImageName(IntPtr process, uint flags, StringBuilder name, ref uint size);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
  public static string ReadProcessName() {
    uint processId;
    GetWindowThreadProcessId(GetForegroundWindow(), out processId);
    if (processId == 0) throw new InvalidOperationException("No foreground process");
    IntPtr process = OpenProcess(0x1000, false, processId);
    if (process == IntPtr.Zero) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
    try {
      uint size = 32768;
      var name = new StringBuilder((int)size);
      if (!QueryFullProcessImageName(process, 0, name, ref size)) throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());
      return System.IO.Path.GetFileNameWithoutExtension(name.ToString());
    } finally { CloseHandle(process); }
  }
}
'@
function Read-ForegroundProcessName {
  [UlanziPremiereForeground]::ReadProcessName()
}
if ($Persistent) {
  [Console]::Out.WriteLine('READY')
  [Console]::Out.Flush()
  while ($null -ne ($requestLine = [Console]::ReadLine())) {
    if ($requestLine -ne 'CHECK') { break }
    try { [Console]::Out.WriteLine((Read-ForegroundProcessName)) }
    catch { [Console]::Out.WriteLine('CHECK_ERROR') }
    [Console]::Out.Flush()
  }
} else { Read-ForegroundProcessName }
