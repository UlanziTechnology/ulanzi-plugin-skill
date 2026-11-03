[CmdletBinding()]
param([switch]$EnableDebug)
$ErrorActionPreference = 'Stop'
$extensionId = 'com.ulanzi.premierepro.bridge'
$sourcePath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "../cep/$extensionId"))
if (-not (Test-Path -LiteralPath (Join-Path $sourcePath 'CSXS/manifest.xml') -PathType Leaf)) { throw 'CEP extension source is missing.' }
if ([string]::IsNullOrWhiteSpace($env:APPDATA)) { throw 'APPDATA is unavailable.' }
$extensionRoot = [IO.Path]::GetFullPath((Join-Path $env:APPDATA 'Adobe/CEP/extensions'))
$backupRoot = [IO.Path]::GetFullPath((Join-Path $env:APPDATA 'Adobe/CEP/UlanziBackups'))
$targetPath = [IO.Path]::GetFullPath((Join-Path $extensionRoot $extensionId))
if ([IO.Path]::GetDirectoryName($targetPath) -ne $extensionRoot -or [IO.Path]::GetFileName($targetPath) -ne $extensionId) { throw 'Unsafe installation target.' }
New-Item -ItemType Directory -Force -Path $extensionRoot, $backupRoot | Out-Null
foreach ($checkPath in @($extensionRoot, $backupRoot)) {
  if ((Get-Item -LiteralPath $checkPath).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Refusing a linked installation directory: $checkPath" }
}
$backupPath = Join-Path $backupRoot ($extensionId + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8))
if (Test-Path -LiteralPath $targetPath) {
  if ((Get-Item -LiteralPath $targetPath).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing to replace a linked extension directory.' }
  Move-Item -LiteralPath $targetPath -Destination $backupPath
}
try {
  Copy-Item -LiteralPath $sourcePath -Destination $targetPath -Recurse
  if (-not (Test-Path -LiteralPath (Join-Path $targetPath 'CSXS/manifest.xml'))) { throw 'Installed extension manifest was not found.' }
} catch {
  if (Test-Path -LiteralPath $targetPath) { Move-Item -LiteralPath $targetPath -Destination ($backupPath + '-failed') }
  if (Test-Path -LiteralPath $backupPath) { Move-Item -LiteralPath $backupPath -Destination $targetPath }
  throw
}
if ($EnableDebug) {
  foreach ($csxsVersion in @('11', '12')) {
    $registryPath = "HKCU:\Software\Adobe\CSXS.$csxsVersion"
    New-Item -Path $registryPath -Force | Out-Null
    New-ItemProperty -Path $registryPath -Name PlayerDebugMode -Value '1' -PropertyType String -Force | Out-Null
  }
  Write-Output 'Unsigned CEP development extensions enabled for CSXS 11 and 12. This affects all CEP extensions for this user.'
}
Write-Output "CEP extension installed: $targetPath"
if (Test-Path -LiteralPath $backupPath) { Write-Output "Previous extension preserved: $backupPath" }
Write-Output 'Save your project and restart Premiere Pro. The background bridge connects automatically; no panel needs to stay open.'
Write-Output 'For troubleshooting only: Window > Extensions > Ulanzi Premiere Bridge Diagnostics.'
Write-Output 'The Ulanzi plugin itself has not been installed or synchronized by this script.'
