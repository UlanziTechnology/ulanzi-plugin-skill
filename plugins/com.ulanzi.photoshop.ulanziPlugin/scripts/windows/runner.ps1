Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class FastInput {
    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll")]
    public static extern void mouse_event(int dwFlags, int dx, int dy, int dwData, int dwExtraInfo);

    public static void Scroll(int delta) {
        mouse_event(0x0800, 0, 0, delta, 0);
    }
}
"@

$wsh = New-Object -ComObject WScript.Shell

function MoveToFocus {
    try {
        $f = [System.Windows.Automation.AutomationElement]::FocusedElement
        if ($f) {
            $r = $f.Current.BoundingRectangle
            if ($r.Width -gt 0 -and $r.Height -gt 0) {
                $tx = [int]($r.X + $r.Width / 2)
                $ty = [int]($r.Y + $r.Height / 2)
                [FastInput]::SetCursorPos($tx, $ty) | Out-Null
            }
        }
    } catch {}
}

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Write-Output "READY"

while ($true) {
    $line = [Console]::ReadLine()
    if ($null -eq $line -or $line -eq "exit") { break }
    if ($line.Trim() -eq "") { continue }

    $parts = $line.Split(" ")
    $action = $parts[0]

    switch ($action) {
        "shortcut" {
            $menu = $parts[1]
            $wsh.AppActivate("Photoshop") | Out-Null
            Start-Sleep -Milliseconds 60
            if ($menu -eq "hue-saturation") { $wsh.SendKeys("^u") }
            elseif ($menu -eq "curves") { $wsh.SendKeys("^m") }
            elseif ($menu -eq "levels") { $wsh.SendKeys("^l") }
        }
        "adjust" {
            $dir = $parts[1]
            $step = 1
            if ($parts.Length -gt 2) { $step = [int]$parts[2] }
            if ($step -le 0) { $step = 1 }
            if ($step -gt 100) { $step = 100 }
            $delta = if ($dir -eq "up") { 120 * $step } else { -120 * $step }

            MoveToFocus
            [FastInput]::Scroll($delta)
        }
        "tab" {
            $isReverse = ($parts.Length -gt 1 -and $parts[1] -eq "true")
            if ($isReverse) { $wsh.SendKeys("+{TAB}") }
            else { $wsh.SendKeys("{TAB}") }
            Start-Sleep -Milliseconds 30
            MoveToFocus
        }
        "enter" {
            $wsh.SendKeys("{ENTER}")
        }
        "escape" {
            $wsh.SendKeys("{ESC}")
        }
    }
    Write-Output "OK"
}
