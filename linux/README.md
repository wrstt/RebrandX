# RebrandX on Linux

The engine, the rules and every behaviour are shared with the Windows
build. Only the window differs: Linux uses **GTK + WebKit**
(`rebrandx/app_gtk.py`), Windows uses a native tkinter window.

If the GTK bindings are not installed, the CLI falls back to the same
tkinter window Windows uses — so `rbx` still opens *something* on a machine
without `python3-gi`.

## What is in here

```text
linux/
├── build-deb.sh    builds dist/linux/rebrandx_<version>_all.deb
├── install.sh      wires the source checkout into GNOME (no sudo)
├── uninstall.sh    takes that back out again
└── bin/
    ├── rbx         command line
    └── rebrandx    the GTK window
```

## Option A — the .deb

```bash
./linux/build-deb.sh
sudo apt install ./dist/linux/rebrandx_1.2.0_all.deb
```

Installs `rebrandx` and `rbx` into `/usr/bin`, the app into
`/usr/lib/rebrandx`, a desktop entry and the icon. Remove it the normal
way: `sudo apt remove rebrandx`.

## Option B — install from the checkout

No sudo, nothing outside `$HOME`:

```bash
./linux/install.sh
```

Adds the icon, a desktop entry, symlinks in `~/.local/bin`, a Desktop
launcher (skip it with `--no-desktop-icon`) and a **Scripts › Rebrand with
RebrandX** item in the Files right-click menu. Undo all of it with
`./linux/uninstall.sh`.

Both routes are ordinary Linux packaging. Unlike Windows — where RebrandX
is a portable `.exe` with no installer at all — a Linux desktop expects an
app to register itself, so it does.

## Option C — run from source

```bash
python3 rebrandx/app_gtk.py          # the GTK window
python3 rebrandx/cli.py --help       # the command line
./linux/bin/rebrandx ~/dev/taskly    # same window, via the launcher
```

## Requirements

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

The system GTK stack, nothing from PyPI. There is no virtualenv and no
`requirements.txt` — the app imports only the standard library plus `gi`.

## Verifying

```bash
python3 tests/test_engine.py
xvfb-run -a python3 tests/test_windows.py
python3 tests/gui_probe.py
```

`tests/test_windows.py` is named for the behaviour it covers, not the
machine it runs on: the filename rules, the root guard and the encoding
sniffing all matter here too, because a project rebranded on Linux still
has to open on Windows. It runs on both.
