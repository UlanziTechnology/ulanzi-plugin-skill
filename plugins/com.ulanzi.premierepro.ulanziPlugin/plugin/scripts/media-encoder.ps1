# Read-only installation detection; does not launch or change Adobe applications.
$ErrorActionPreference = 'Stop'
$candidates = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
function Add-EncoderCandidate([string]$candidate) {
    if (-not [string]::IsNullOrWhiteSpace($candidate)) { [void]$candidates.Add($candidate.Trim().Trim('"')) }
}

# A running application also covers installations in a custom location.
Get-Process -Name 'Adobe Media Encoder' -ErrorAction SilentlyContinue | ForEach-Object { Add-EncoderCandidate $_.Path }

$appPathRoots = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Adobe Media Encoder.exe',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\Adobe Media Encoder.exe',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Adobe Media Encoder.exe'
)
foreach ($registryPath in $appPathRoots) {
    if (Test-Path -LiteralPath $registryPath) { Add-EncoderCandidate (Get-Item -LiteralPath $registryPath).GetValue('') }
}

# Validate actual executable files so stale uninstall entries are not accepted.
$uninstallRoots = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
)
foreach ($registryRoot in $uninstallRoots) {
    if (-not (Test-Path -LiteralPath $registryRoot)) { continue }
    foreach ($key in Get-ChildItem -LiteralPath $registryRoot) {
        $entry = Get-ItemProperty -LiteralPath $key.PSPath
        if ($entry.DisplayName -notmatch '^Adobe Media Encoder(?:\s|$)') { continue }
        if ($entry.InstallLocation) { Add-EncoderCandidate (Join-Path $entry.InstallLocation 'Adobe Media Encoder.exe') }
        if ($entry.DisplayIcon) { Add-EncoderCandidate ($entry.DisplayIcon -replace ',\s*-?\d+\s*$', '') }
    }
}

# Search only immediate Adobe install folders, never whole drives.
$adobeRoots = @($env:ProgramW6432, $env:ProgramFiles, ${env:ProgramFiles(x86)}, (Join-Path $env:LOCALAPPDATA 'Programs')) |
    Where-Object { $_ } | Select-Object -Unique | ForEach-Object { Join-Path $_ 'Adobe' }
foreach ($adobeRoot in $adobeRoots) {
    if (-not (Test-Path -LiteralPath $adobeRoot -PathType Container)) { continue }
    foreach ($directory in Get-ChildItem -LiteralPath $adobeRoot -Directory -Filter 'Adobe Media Encoder*') {
        Add-EncoderCandidate (Join-Path $directory.FullName 'Adobe Media Encoder.exe')
    }
}
foreach ($candidate in $candidates) {
    if ([System.IO.Path]::GetFileName($candidate) -ieq 'Adobe Media Encoder.exe' -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        @{ installed = $true } | ConvertTo-Json -Compress
        exit 0
    }
}
@{ installed = $false } | ConvertTo-Json -Compress
