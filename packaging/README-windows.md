# RebrandX on Windows

The engine, the rules and every behaviour are shared with the Linux build.
Only the window differs: Linux uses GTK, Windows uses a **native tkinter
window**.

There is nothing to install. tkinter is part of the Python standard
library, so the app runs on a stock python.org install, offline, with no
third-party packages and no browser engine involved.

## Option A — install it (recommended)

Needs [Python 3.8+](https://www.python.org/downloads/).

```
powershell -ExecutionPolicy Bypass -File install.ps1
```

Registers RebrandX with Windows: Start menu entry, desktop shortcut, `rbx`
and `rebrandx` on the PATH, and a **Rebrand with RebrandX** item on the
right-click menu of any folder.

Everything is per-user — no admin rights, nothing outside `HKCU` and
`%LOCALAPPDATA%`. See what it would do first with `-DryRun`, and undo it
all with `uninstall.ps1`.

## Option B — run from source

```
python rebrandx\app_tk.py
```

Or double-click `bin\rebrandx.bat`. For the command line, `bin\rbx.bat`:

```
bin\rbx.bat Taskly Flowdesk C:\dev\taskly -n
```

## Option C — build a standalone .exe

```
powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1
```

Produces `dist\RebrandX.exe` (the window) and `dist\rbx.exe` (the command
line), each self-contained, plus a portable zip of both. Neither needs
Python on the machine you copy it to.

The build stamps a version resource and an application manifest, so the
files show a proper name and version in Explorer, declare `longPathAware`,
ask for `PerMonitorV2` DPI, and run `asInvoker` — no UAC prompt.

PyInstaller does not cross-compile, so this script must run on Windows.
That is not the only route from a Linux box:

- **CI** — every push builds both `.exe`s on a `windows-latest` runner.
  Fetch them with `gh run download` or from the run's artifacts page.
- **Wine** — install Windows Python into a Wine prefix and run PyInstaller
  under it. See `packaging/build-windows-wine.sh`.

## Windows-specific behaviour

All of this lives in `rebrandx/win.py` and is exercised by
`tests/test_windows.py`:

- **Case-only renames.** NTFS treats `taskly.js` and `Taskly.js` as the same
  file. A naive rename sees the target "already existing" and invents
  `Taskly-2.js`. `safe_rename()` goes via a temporary name instead.
- **Illegal names.** A rebrand that would produce `CON.txt`, `api:v2.js` or
  a name ending in a space or dot is flagged in the scan (`winWarn`), and
  on Windows the rename lands on a corrected name rather than failing
  part-way through the run.
- **Read-only files.** Git leaves everything in `.git/objects` read-only,
  and Windows refuses to delete or overwrite such a file. RebrandX clears
  the attribute rather than aborting — this affects rewrites, the backup
  wipe, `--clean` and Revert.
- **Junctions.** `os.path.islink()` is False for a directory junction, so a
  naive walk follows one out of the project or straight into a loop.
  RebrandX checks the reparse-point attribute and skips them.
- **Long paths.** Paths past 260 characters are opened through the `\\?\`
  prefix, so a deep tree works even where `LongPathsEnabled` was never
  turned on. The frozen build also declares `longPathAware`.
- **Encodings.** UTF-8, UTF-8 with BOM, UTF-16 LE/BE and cp1252 are all
  detected and written back byte-for-byte in the same encoding, with the
  same BOM. PowerShell 5's `>` redirect writes UTF-16LE, and Notepad still
  writes a UTF-8 BOM, so a scanner that only understands plain UTF-8 would
  call half a Windows project binary.
- **Line endings** are preserved as found, and a file that is mostly LF is
  not converted to CRLF because it contains one stray CRLF.
- **Dangerous roots.** Drive roots, `C:\Windows`, `C:\Program Files`,
  `C:\Users`, your profile and its shell folders, and bare UNC shares are
  all refused.
- **Console.** ANSI colour is enabled only once the console actually
  accepts VT processing, `NO_COLOR` is honoured, and the tick and arrow
  glyphs fall back to ASCII when the stream cannot encode them — so
  `rbx ... > build.log` on a cp1252 machine works instead of raising
  `UnicodeEncodeError`.
- **Config** lives in `%APPDATA%\RebrandX\config.json`, written atomically
  as UTF-8.
- **Backups** are marked hidden, since a leading dot means nothing to
  Explorer.

## Verifying a build

```
python tests\test_engine.py
python tests\test_windows.py
```

35 engine checks and 89 Windows checks. Both are pure stdlib. The Windows
suite builds the real window and drives it, so it needs a display.

To look at the window and have it report what it painted:

```
python tests\gui_probe_tk.py
python tests\gui_probe_tk.py --shot window.png
```
