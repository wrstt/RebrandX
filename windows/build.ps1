<#
    Build RebrandX for Windows.

        powershell -ExecutionPolicy Bypass -File windows\build.ps1

    Produces, in dist\windows\:

        RebrandX.exe        the app window, self-contained, no console
        rbx.exe             the command line, self-contained -- and the app
                            when it is double-clicked or run with no arguments
        RebrandX-windows.zip  both of the above, ready to hand to someone

    Must run ON Windows -- PyInstaller cannot cross-compile. See
    windows\README.md for the CI and Wine routes from Linux.

    Options:
        -NoZip        skip the portable archive
        -CliOnly      build rbx.exe only, skipping the window
        -Version X    stamp this version into the file properties
#>
[CmdletBinding()]
param(
    [switch]$NoZip,
    [switch]$CliOnly,
    [string]$Version = "1.1.0"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments)
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments 2>&1 | ForEach-Object { Write-Host "    $_" }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $old
    }
}

Write-Host "Building RebrandX $Version for Windows" -ForegroundColor Cyan

# Windows locks a running executable, so a build over the top of one fails
# deep inside PyInstaller with a bare "Access is denied". Say what is
# actually wrong instead.
# No prompt: this also runs in CI, where a Read-Host would simply hang.
$running = @(Get-Process -Name RebrandX, rbx -ErrorAction SilentlyContinue)
if ($running.Count) {
    Write-Host "  closing a running RebrandX first:" -ForegroundColor Yellow
    $running | ForEach-Object { Write-Host ("    pid {0}  {1}" -f $_.Id, $_.ProcessName) }
    $running | Stop-Process -Force
    Start-Sleep -Milliseconds 700
}

# --- checks ---------------------------------------------------------------
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) { throw "Python 3.8+ not found on PATH. Install it from python.org." }
$PyExe = $py.Source

$old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
$ver = (& $PyExe -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>&1 | Out-String).Trim()
$ErrorActionPreference = $old
Write-Host "  python $ver ($PyExe)"

Write-Host "  installing build dependencies..."
# PyInstaller is the only build dependency. The app itself has none:
# the window is tkinter, which is part of the standard library.
# 6.0+ for --hide-console, which is what keeps a double-clicked rbx.exe
# from opening a terminal it does not need.
$deps = @("-m", "pip", "install", "--quiet", "--upgrade", "pip", "pyinstaller>=6.0")
if ((Invoke-Native $PyExe $deps) -ne 0) { throw "Could not install build dependencies." }

# --- version resource -----------------------------------------------------
# Without this the .exe shows up in Explorer's Details tab and in Task
# Manager with no name, company or version at all -- which is what makes a
# PyInstaller build look like something you should not run.
$v = $Version.Split(".")
while ($v.Count -lt 4) { $v += "0" }
$vTuple = ($v[0..3]) -join ", "

# Each binary gets its own resource: Explorer shows OriginalFilename in the
# Details tab, and stamping both of them "RebrandX.exe" makes rbx.exe look
# like a copy of something else.
function New-VersionFile {
    param([string]$FileName, [string]$Description)
    $path = Join-Path $env:TEMP ("rebrandx-version-{0}.txt" -f $FileName)
    @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($vTuple), prodvers=($vTuple),
    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'RebrandX'),
        StringStruct('FileDescription', '$Description'),
        StringStruct('FileVersion', '$Version'),
        StringStruct('InternalName', 'RebrandX'),
        StringStruct('OriginalFilename', '$FileName'),
        StringStruct('ProductName', 'RebrandX'),
        StringStruct('ProductVersion', '$Version')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"@ | Set-Content -Path $path -Encoding ASCII
    return $path
}

$verGui = New-VersionFile "RebrandX.exe" "Rename a project across its files, names and contents"
$verCli = New-VersionFile "rbx.exe" "RebrandX on the command line"

# --- application manifest -------------------------------------------------
# longPathAware lets the frozen build open paths past 260 characters even on
# a machine where the registry switch was never turned on. asInvoker keeps
# it out of the UAC prompt: rebranding your own project is not admin work.
$manifest = Join-Path $env:TEMP "rebrandx.manifest"
@"
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <assemblyIdentity type="win32" name="dev.rebrandx.RebrandX"
                    version="$($v[0]).$($v[1]).$($v[2]).$($v[3])"/>
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
      </requestedPrivileges>
    </security>
  </trustInfo>
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <longPathAware xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">true</longPathAware>
      <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
      <activeCodePage xmlns="http://schemas.microsoft.com/SMI/2019/WindowsSettings">UTF-8</activeCodePage>
    </windowsSettings>
  </application>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
    <application>
      <!-- Windows 10 and 11. -->
      <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
      <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}"/>
    </application>
  </compatibility>
</assembly>
"@ | Set-Content -Path $manifest -Encoding UTF8

# --- icon -----------------------------------------------------------------
$icon = "share\rebrandx.ico"
$iconArg = @()
if (Test-Path $icon) {
    $iconArg = @("--icon", $icon)
} else {
    Write-Host "  no .ico found, building without a custom icon" -ForegroundColor Yellow
}

# --- build ----------------------------------------------------------------
# The window icon is the only asset that has to travel with the binary --
# every control is drawn at runtime, so there is no stylesheet or bitmap
# theme to bundle.
$common = @(
    "--onefile", "--noconfirm", "--clean",
    # Each platform builds into its own half of dist\ and build\, so a Linux
    # .deb and a Windows .exe can sit side by side. The generated .spec files
    # are swept up at the end -- --specpath would move them, but it also
    # re-roots every relative --add-data path against wherever they land.
    "--distpath", "dist\windows", "--workpath", "build\windows",
    "--manifest", $manifest,
    "--add-data", "share\rebrandx.ico;share",
    "--add-data", "share\rebrandx.png;share"
) + $iconArg

if (-not $CliOnly) {
    Write-Host "  building RebrandX.exe (window)..."
    # A one-file build has to unpack itself before Python starts, which is a
    # second of nothing happening. --splash covers that gap; the app closes
    # it the moment its own window is ready.
    $splashArg = @()
    if (Test-Path "share\rebrandx-splash.png") {
        $splashArg = @("--splash", "share\rebrandx-splash.png")
    }
    $guiArgs = @("-m", "PyInstaller", "--name", "RebrandX", "--windowed",
                 "--version-file", $verGui) + $splashArg + $common + @("rebrandx\app_tk.py")
    if ((Invoke-Native $PyExe $guiArgs) -ne 0) { throw "PyInstaller failed building RebrandX.exe" }
}

Write-Host "  building rbx.exe (command line and window)..."
# rbx.exe carries tkinter too. `rbx` with no arguments opens the app -- that
# is documented, and it is what a double-click does -- so leaving the toolkit
# out to save four megabytes bought a binary that crashed on its most likely
# first use.
#
# It stays a console binary, because that is what makes `rbx Old New .`
# behave in a shell: the prompt waits for it, output lands in order, and the
# confirmation can be answered. Windows hands a console-subsystem .exe a
# terminal of its own when it is double-clicked, and --hide-console puts that
# window away in the bootloader, before Python starts -- so the app comes up
# on its own rather than in front of a black rectangle.
$cliArgs = @("-m", "PyInstaller", "--name", "rbx", "--console",
             "--hide-console", "hide-early",
             "--version-file", $verCli) + $common + @("rebrandx\cli.py")
if ((Invoke-Native $PyExe $cliArgs) -ne 0) { throw "PyInstaller failed building rbx.exe" }

# --- verify ---------------------------------------------------------------
$built = @()
if (-not $CliOnly) { $built += "dist\windows\RebrandX.exe" }
$built += "dist\windows\rbx.exe"
foreach ($exe in $built) {
    if (-not (Test-Path $exe)) { throw "$exe was not produced" }
    $size = (Get-Item $exe).Length
    if ($size -lt 3MB) { throw "$exe looks too small to be complete ($size bytes)" }
    Write-Host ("  {0}  {1:N1} MB" -f $exe, ($size / 1MB)) -ForegroundColor Green
}

# rbx.exe is self-contained, so it can prove itself right here. --self-test
# reports what the binary is made of and fails if the toolkit, the window or
# the engine did not make it in -- which is how a build that only ever ran
# `--help` shipped a CLI that crashed the moment somebody double-clicked it.
Write-Host "  smoke test..."
if ((Invoke-Native "dist\windows\rbx.exe" @("--help")) -ne 0) { throw "rbx.exe --help failed" }
if ((Invoke-Native "dist\windows\rbx.exe" @("--self-test")) -ne 0) { throw "rbx.exe --self-test failed" }

# --- portable archive -----------------------------------------------------
if (-not $NoZip) {
    $zip = "dist\windows\RebrandX-windows.zip"
    Remove-Item $zip -ErrorAction SilentlyContinue
    Compress-Archive -Path $built -DestinationPath $zip
    Write-Host ("  {0}  {1:N1} MB" -f $zip, ((Get-Item $zip).Length / 1MB)) -ForegroundColor Green
}

Remove-Item $verGui, $verCli, $manifest -ErrorAction SilentlyContinue
Remove-Item "RebrandX.spec", "rbx.spec" -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host ""
Write-Host "  RebrandX.exe  double-click it, or put it anywhere on your PATH"
Write-Host "  rbx.exe       rbx OldName NewName C:\path\to\folder"
Write-Host "                double-click it, or run it with no arguments, and"
Write-Host "                it opens the same window -- no terminal in sight"
Write-Host ""
Write-Host "  Portable: keep the file wherever suits you, delete it when done."
Write-Host "  Nothing was registered, and there is nothing to uninstall."
