# RebrandX on Windows

The engine, the rules and every behaviour are shared with the Linux build.
Only the window differs: Linux uses GTK, Windows uses a **native tkinter
window**.

It is a **portable app**. There is no installer and nothing to uninstall:
the `.exe` is the whole program, it runs from wherever you put it, and
deleting the file removes it. Nothing goes into Program Files, nothing is
written to the registry, and no shortcut appears behind your back.

Running from source needs nothing either. tkinter is part of the Python
standard library, so the app runs on a stock python.org install, offline,
with no third-party packages and no browser engine involved.

## Option A — the .exe (recommended)

```
powershell -ExecutionPolicy Bypass -File windows\build.ps1
```

Produces `dist\windows\RebrandX.exe` (the window) and `dist\windows\rbx.exe`
(the command line), each self-contained, plus a portable zip of both.
Neither needs Python on the machine you copy it to. The Linux build writes
to `dist/linux/`, so the two never tread on each other.

Both carry the whole app, `rbx.exe` included — `rbx` with no arguments
opens the window, and that is what a double-click is, so a CLI build with
the toolkit stripped out of it is a build that crashes on its most likely
first use. It stays a **console** binary, because that is what makes
`rbx Old New .` behave in a shell: the prompt waits for it, output arrives
in order, and the confirmation can be answered. Windows hands such a binary
a terminal of its own when it is double-clicked, so the build passes
`--hide-console hide-early` and the bootloader puts that window away before
Python starts. Double-clicked, dropped on, or run bare, `rbx.exe` shows a
window and nothing else; anything that goes wrong on that path is reported
in a dialog rather than printed to a console nobody can see.

Ask a built copy what it is made of:

```
dist\windows\rbx.exe --self-test
```

It reports the Python it was frozen with, whether tkinter and the window
survived the build, and runs the engine over a small throwaway project.
The build script and CI both run it, so a binary missing a piece fails the
build instead of a user's double-click.

The build stamps a version resource and an application manifest, so the
files show a proper name and version in Explorer, declare `longPathAware`,
ask for `PerMonitorV2` DPI, and run `asInvoker` — no UAC prompt.

PyInstaller does not cross-compile, so this script must run on Windows.
That is not the only route from a Linux box:

- **CI** — every push builds both `.exe`s on a `windows-latest` runner.
  Fetch them with `gh run download` or from the run's artifacts page.
- **Wine** — install Windows Python into a Wine prefix and run PyInstaller
  under it. See `windows/build-under-wine.sh`.

## Option B — run from source

```
python rebrandx\app_tk.py
```

Or double-click `windows\bin\rebrandx.bat`. For the command line,
`windows\bin\rbx.bat`:

```
windows\bin\rbx.bat Taskly Flowdesk C:\dev\taskly -n
```

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
- **Whose console it is.** A double-clicked `.exe` is handed a console of
  its own; one started from a shell is only lent the shell's. RebrandX
  tells them apart by asking which processes are attached to it, and only
  ever hides — or reports a crash in a dialog instead of printing to — the
  one that belongs to it. Getting that backwards would take a shell's
  window away, or put a modal dialog in front of a CI runner.
- **Config** lives in `%APPDATA%\RebrandX\config.json`, written atomically
  as UTF-8.
- **Backups** are marked hidden, since a leading dot means nothing to
  Explorer.

## Verifying a build

```
python tests\test_engine.py
python tests\test_windows.py
```

35 engine checks and 99 Windows checks. Both are pure stdlib. The Windows
suite builds the real window and drives it, so it needs a display.

To look at the window and have it report what it painted:

```
python tests\gui_probe_tk.py
python tests\gui_probe_tk.py --shot window.png
```
