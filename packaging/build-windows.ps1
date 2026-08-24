# Build RebrandX.exe on Windows.
#
#   powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1
#
# Produces dist\RebrandX.exe -- a single self-contained file. Must run ON
# Windows: PyInstaller cannot cross-compile from Linux.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "Building RebrandX for Windows" -ForegroundColor Cyan

# --- checks ---------------------------------------------------------------
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { throw "Python 3.10+ not found on PATH. Install it from python.org." }
$ver = (python -c "import sys;print('%d.%d' % sys.version_info[:2])")
Write-Host "  python $ver"

Write-Host "  installing build dependencies..."
python -m pip install --quiet --upgrade pip pyinstaller pywebview

# --- icon -----------------------------------------------------------------
$icon = "share\rebrandx.ico"
if (-not (Test-Path $icon)) {
    Write-Host "  no .ico found, building without a custom icon" -ForegroundColor Yellow
    $iconArg = @()
} else {
    $iconArg = @("--icon", $icon)
}

# --- build ----------------------------------------------------------------
$args = @(
    "--name", "RebrandX",
    "--onefile",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--add-data", "rebrandx\ui;rebrandx/ui",
    "--hidden-import", "webview.platforms.edgechromium",
    "--collect-all", "webview",
    "rebrandx\app_win.py"
) + $iconArg

python -m PyInstaller @args

Write-Host ""
Write-Host "Done: dist\RebrandX.exe" -ForegroundColor Green
Write-Host ""
Write-Host "  Double-click it, or put it anywhere on your PATH."
Write-Host "  For the command line, use bin\rbx.bat (needs Python installed)."
