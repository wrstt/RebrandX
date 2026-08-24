# Running RebrandX on Windows

The engine, the interface and every behaviour are shared with the Linux
build. Only the window differs: Linux uses GTK + WebKitGTK, Windows uses
**WebView2**, which ships with Windows 10 and 11 — so there is no runtime to
install.

## Option A — run from source (quickest)

Needs [Python 3.10+](https://www.python.org/downloads/) with *"Add Python to
PATH"* ticked during install.

```
pip install pywebview
python rebrandx\app_win.py
```

Or double-click `bin\rebrandx.bat`. For the command line use `bin\rbx.bat`:

```
bin\rbx.bat Taskly Flowdesk C:\dev\taskly -n
```

## Option B — build a standalone .exe

```
powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1
```

Produces `dist\RebrandX.exe` — one self-contained file, no Python needed on
the machine you copy it to.

PyInstaller does not cross-compile, so this script itself must run on
Windows. That is not the only way to get an `.exe` from a Linux box, though:

- **CI** — every push builds `RebrandX.exe` on a `windows-latest` runner.
  Fetch it with `gh run download` or from the run's artifacts page. This is
  the most faithful build, since it is a real Windows machine.
- **Wine** — install Windows Python into a Wine prefix and run PyInstaller
  under it. See `packaging/build-windows-wine.sh`.

## Windows-specific behaviour

These are handled in `engine.py` and are worth knowing about:

- **Case-only renames.** NTFS treats `taskly.js` and `Taskly.js` as the same
  file. A naive rename sees the target "already existing" and invents
  `Taskly-2.js`. `safe_rename()` goes via a temporary name so a case-only
  rebrand works properly.
- **Illegal names.** If a replacement would produce `CON.txt`, `a:b.js` or a
  name ending in a space or dot, the scan flags it (`winWarn`) rather than
  failing at write time.
- **Line endings** are preserved as found — a CRLF file stays CRLF.
- **Config** lives in `%APPDATA%\RebrandX\config.json`.
- **Long paths.** Windows caps paths at 260 characters unless long-path
  support is enabled. Deeply nested trees may need
  `Computer\HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`.

## Verifying a build

```
python tests\test_engine.py
```

35 checks covering the rules, scanning, both apply modes, revert, project-file
removal, nested renames and the Windows name rules. It is pure stdlib and
runs identically on both platforms.
