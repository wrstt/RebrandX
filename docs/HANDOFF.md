# RebrandX — handoff

Written 2026-08-25, at commit `c6d07d9`. Read this before changing the
Windows build or moving anything around; most of it is the reasoning behind
decisions that look arbitrary from the outside.

## What this is

One rename engine, two desktop shells, one CLI. RebrandX replaces a project
name across a folder's file contents, file names and folder names, previews
every change as a diff, and either rewrites in place with a backup or writes
a rebranded copy elsewhere.

No third-party packages anywhere. The Linux window is GTK + WebKit through
the system `gi` bindings; the Windows window is tkinter, which ships with
Python. CI asserts this by importing the app and checking `sys.modules`
against `sys.stdlib_module_names` — if a PyPI import ever creeps in, the
build fails.

## Layout

```text
rebrandx/            the app — shared by both platforms
├── engine.py        the rebrand engine: scan(), apply(), revert()
├── core.py          shared application logic and config
├── cli.py           the rbx command line, and the entry point of rbx.exe
├── win.py           Windows filesystem + console primitives
├── app_gtk.py       the GTK window          ─┐ Linux
├── ui_gtk/          its HTML/CSS/JS assets  ─┘
├── app_tk.py        the native window       ─┐ Windows, and the Linux
├── widgets.py       controls drawn on canvas │ fallback when the GTK
├── theme.py         palette and ttk styling  │ bindings are missing
├── anim.py          easing and timers        │
└── splash.py        the launch screen       ─┘

linux/               Linux only: build-deb.sh, install.sh, uninstall.sh, bin/
windows/             Windows only: build.ps1, build-under-wine.sh, bin/
dist/linux/          the .deb          dist/windows/   the .exe files + zip
tools/               make-icon.py — regenerates the icon set from geometry
tests/               engine and GUI tests, both platforms
share/               icons and branding
```

Each platform folder has its own README. The `rebrandx/` package is
deliberately **not** split by platform: the engine, the safety rules, the
encoding handling and the CLI are one codebase, and forking them per OS
would mean fixing every bug twice.

## Windows: why the build looks like this

`rbx.exe` is a **console-subsystem** binary that also opens the GUI. That
combination is deliberate and easy to break.

- **It carries tkinter.** `rbx` with no arguments opens the app, and that is
  what a double-click is. An earlier build passed `--exclude-module tkinter`
  to save four megabytes and shipped a binary that crashed with
  `ModuleNotFoundError` the first time anyone double-clicked it. Do not
  strip the toolkit out again.
- **Console, not windowed.** A GUI-subsystem binary does not make a shell
  wait for it: `rbx Old New .` would hand the prompt back immediately,
  output would land over the next prompt, and the `[y/N]` confirmation would
  fight cmd for stdin. Console subsystem keeps all of that correct.
- **`--hide-console hide-early`** is what stops a double-click from showing a
  terminal. PyInstaller's bootloader hides the console before Python starts,
  and only when the program owns it.
- **`win.owns_console()`** answers "is this console ours?" — not by counting
  attached processes (a one-file frozen build is two, bootloader plus child)
  but by checking whether every attached pid runs our own image. Get this
  wrong in one direction and a shell's window disappears; wrong in the other
  and a modal dialog blocks a CI runner forever.
- **Errors on the double-click path go to a message box**, because printing
  to a hidden console is the same as saying nothing. `cli.report()` picks
  stderr or a dialog based on `win.hidden_console()`.

`rbx.exe --self-test` reports what a binary is made of and exits non-zero if
the toolkit, the window or the engine did not make it in. The build script
and CI both run it. If you change the freeze, run it.

## Portable, and tested as such

Windows has **no installer**. `install.ps1`/`uninstall.ps1` were deleted:
one file is the whole program, it runs from anywhere, and deleting it
removes it. CI enforces this — it copies the `.exe` to an unrelated
directory, runs it there, and fails if any `HKCU\...\RebrandX` key or
`%LOCALAPPDATA%\RebrandX` folder appeared.

Linux keeps normal packaging (`.deb`, plus a no-sudo `install.sh` for a
checkout), because that is what a Linux desktop expects.

## Building and testing

```bash
python tests/test_engine.py         # 35 checks
python tests/test_windows.py        # 99 checks; needs a display (xvfb-run on Linux)
python tests/gui_probe_tk.py        # look at the tk window, --shot to capture
python tests/gui_probe.py           # the GTK window
```

```powershell
powershell -ExecutionPolicy Bypass -File windows\build.ps1     # → dist\windows\
```

```bash
./linux/build-deb.sh                                           # → dist/linux/
```

`tests/test_windows.py` is named for the behaviour it covers, not the
machine it runs on — the filename rules, the root guard and the encoding
sniffing matter on Linux too, because a project rebranded there still has to
open on Windows. It runs on both, and CI runs it on both.

## Traps

- **Line endings.** Every text file in this repo is LF. Editing on Windows
  with anything that round-trips through Python's text mode (`read_text` →
  `write_text`) silently converts them to CRLF and produces whole-file
  diffs. Check `git diff --stat` before committing; if a two-line change
  shows 400 lines, that is what happened.
- **`--specpath`** re-roots every relative `--add-data` path against wherever
  the spec lands, which breaks the `share\` bundling. The build sweeps the
  generated `.spec` files up at the end instead.
- **A running .exe is locked.** `windows\build.ps1` stops any running
  `RebrandX`/`rbx` process first, otherwise PyInstaller fails deep inside
  with "Access is denied".
- **PyInstaller 6.0+** is required for `--hide-console`; the build script
  pins it.

## Open items

- `%APPDATA%\RebrandX\config.json` is the one trace the "portable" Windows
  build still leaves on a machine. A portable app would normally keep that
  next to the `.exe` and fall back to `%APPDATA%` only when its own folder
  is read-only. Not done — it changes where existing settings live.
- `windows/build-under-wine.sh` builds only `RebrandX.exe`; it never built
  `rbx.exe`, so the Wine route does not produce the portable CLI. It also
  has not been exercised since the reorganisation.
- `windows/build.ps1` is the only PowerShell left. It could become
  `packaging`-free Python (`build.py`) and absorb the Wine route, leaving one
  build script for both.
- Version `1.2.0` is hard-coded in `windows/build.ps1` and
  `linux/build-deb.sh` separately. They will drift.
