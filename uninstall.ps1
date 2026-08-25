<#
    Remove the per-user RebrandX install.

        powershell -ExecutionPolicy Bypass -File uninstall.ps1

    Leaves this folder alone -- delete it yourself afterwards if you want
    the source gone too. Pass -KeepSettings to keep the saved settings and
    recent folders without being asked.
#>
[CmdletBinding()]
param(
    [switch]$KeepSettings,
    [switch]$RemoveSettings
)

$ErrorActionPreference = "Stop"
$BinDir = Join-Path $env:LOCALAPPDATA "RebrandX\bin"
$ConfigDir = Join-Path $env:APPDATA "RebrandX"

function Say($msg) { Write-Host "  $msg" }

Write-Host "Removing RebrandX" -ForegroundColor Cyan

# --- shortcuts and shims ---------------------------------------------------
$targets = @(
    (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\RebrandX.lnk"),
    (Join-Path ([Environment]::GetFolderPath("Desktop")) "RebrandX.lnk"),
    (Join-Path $BinDir "rbx.cmd"),
    (Join-Path $BinDir "rebrandx.cmd")
)
foreach ($t in $targets) {
    if (Test-Path $t) {
        Remove-Item $t -Force
        Say "removed $t"
    }
}
if ((Test-Path $BinDir) -and -not (Get-ChildItem $BinDir -Force)) {
    Remove-Item $BinDir -Force
    $parent = Split-Path -Parent $BinDir
    if ((Test-Path $parent) -and -not (Get-ChildItem $parent -Force)) {
        Remove-Item $parent -Force
    }
}

# --- Explorer right-click --------------------------------------------------
foreach ($k in @("HKCU:\Software\Classes\Directory\shell\RebrandX",
                 "HKCU:\Software\Classes\Directory\Background\shell\RebrandX")) {
    if (Test-Path $k) {
        Remove-Item $k -Recurse -Force
        Say "removed $k"
    }
}

# --- PATH ------------------------------------------------------------------
$key = "HKCU:\Environment"
$current = (Get-ItemProperty -Path $key -Name Path -ErrorAction SilentlyContinue).Path
if ($current) {
    $parts = $current -split ";" | Where-Object { $_ -ne "" -and $_ -ne $BinDir }
    $new = $parts -join ";"
    if ($new -ne $current) {
        $kind = "String"
        if ($new -match "%") { $kind = "ExpandString" }
        Set-ItemProperty -Path $key -Name Path -Value $new -Type $kind
        Say "removed $BinDir from PATH"
    }
}

# --- settings --------------------------------------------------------------
if (Test-Path $ConfigDir) {
    $drop = $RemoveSettings
    if (-not $RemoveSettings -and -not $KeepSettings) {
        $answer = Read-Host "Also delete saved settings and recent folders? [y/N]"
        if ($answer -match '^[Yy]') { $drop = $true }
    }
    if ($drop) {
        Remove-Item $ConfigDir -Recurse -Force
        Say "removed $ConfigDir"
    } else {
        Say "kept $ConfigDir"
    }
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Open a new terminal for the PATH change to take effect."
