<p align="center">
  <img src="share/banner.svg" alt="RebrandX" width="100%">
</p>

<h1 align="center">RebrandX</h1>

<p align="center">
  <b>Rename an entire project without hunting through it by hand.</b><br>
  Files · folders · source contents · repo references
</p>

<p align="center">
  Ubuntu &nbsp;•&nbsp; Windows &nbsp;•&nbsp; Desktop + CLI
</p>

---

## What is RebrandX?

RebrandX takes an existing project name and replaces it across the entire project:

* **File contents**
* **File names**
* **Folder names**
* **Case variants**
* **Repository references**

Before anything is changed, RebrandX shows you exactly what it found and lets you review the result.

Skip entire files, individual lines, or run the whole operation as a dry run.

> **Nothing is written until you approve it.**

---

## Why?

Renaming a project sounds simple until the old name exists in:

```text
Taskly/
├── src/taskly/
├── taskly.config.json
├── README.md
├── package.json
├── .github/
└── hundreds of source files
```

RebrandX handles the rename as one operation.

```text
Taskly  →  Flowdesk
taskly  →  flowdesk
TASKLY  →  FLOWDESK
```

Including paths and contents.

---

## Features

### 🔎 Preview everything

Scan the project before touching it.

RebrandX shows:

* every affected file
* every path rename
* change counts
* line-by-line diffs

Individual files and changed lines can be excluded before applying.

### 🔤 Case-aware replacement

One rule can automatically handle common variants:

```text
taskly  → flowdesk
Taskly  → Flowdesk
TASKLY  → FLOWDESK
```

Or switch to exact matching, case-insensitive replacement, or regex.

### 📁 Rename paths too

RebrandX doesn't stop at file contents.

```text
taskly.config.json
↓
flowdesk.config.json
```

Folders are renamed as well.

### 🧹 Clean old project metadata

Optionally remove project-specific files from the original repository:

```text
.github/
.gitlab/
LICENSE
CHANGELOG
CONTRIBUTING
CODE_OF_CONDUCT
SECURITY
AUTHORS
FUNDING.yml
```

The list is customizable.

Your source, README and package metadata remain available for normal rebranding.

### ↩ Safe in-place mode

Modify the existing project while keeping a backup in:

```text
.rebrandx-backup/
```

Use **Revert** to restore the previous state.

### 📋 Copy mode

Prefer not to touch the original?

Create a completely rebranded copy in another directory.

Ignored paths such as `.git/` and `node_modules/` can be excluded automatically.

### 🖥 Desktop + CLI

The same engine powers:

* Linux desktop app
* Windows desktop app
* `rbx` command-line interface

---

# Desktop App

The interface uses a simple three-column workflow:

| Rules               | Files                 | Diff                   |
| ------------------- | --------------------- | ---------------------- |
| Define what changes | Review affected files | Inspect actual changes |

### Rules

Configure:

* find + replace
* case variants
* file/folder renaming
* content replacement
* regex
* repository cleanup
* ignore rules
* dry-run mode

### Files

See every affected file and its resulting name.

Skip anything that should remain untouched.

### Diff

Inspect the exact before/after result.

Individual changed lines can be excluded before applying the rebrand.

---

## Install

### Ubuntu

#### `.deb` package

```bash
cd ~/.local/share/rebrandx
./packaging/build-deb.sh

sudo apt install ~/.local/share/rebrandx/dist/rebrandx_1.1.0_all.deb
```

This installs both:

```text
rebrandx
rbx
```

and registers RebrandX with GNOME.

#### Local install

No sudo:

```bash
./install.sh
```

Optional:

```bash
./install.sh --no-desktop-icon
```

Remove later with:

```bash
./uninstall.sh
```

### Linux requirements

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

RebrandX uses the system GTK stack and does not require a Python package environment for the Linux desktop build.

---

### Windows

Needs [Python 3.8+](https://www.python.org/downloads/) — and nothing else. The window is a native desktop app built on tkinter, which ships with Python. No runtime, no browser engine, no packages to install, and it works entirely offline.

#### Standalone .exe (no install)

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1
```

Produces two self-contained files that need no Python and no install step:

```text
dist\RebrandX.exe          the app — double-click it
dist\rbx.exe               the command line
dist\RebrandX-windows.zip  both, ready to hand to someone
```

Put them anywhere. Every release also ships them as build artifacts.

#### Run from source

```powershell
python rebrandx\app_tk.py
```

Nothing to install first. Or double-click `bin\rebrandx.bat`; for the command line, `bin\rbx.bat`.

#### Optional: register it with Windows

If you would rather have it in the Start menu than run a loose `.exe`:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

That adds a Start menu entry, a desktop shortcut, `rbx` and `rebrandx` on your PATH, and a **Rebrand with RebrandX** item on the right-click menu of any folder. Everything is per-user — no admin rights, nothing outside `HKCU` and `%LOCALAPPDATA%`.

Preview it with `-DryRun`, tune it with `-NoDesktopIcon` / `-NoContextMenu` / `-NoPath`, and undo it with `uninstall.ps1`.

See [`packaging/README-windows.md`](packaging/README-windows.md) for Windows-specific behaviour — NTFS case-only renames, long paths, invalid filenames, encodings and read-only files.

---

# Command Line

Basic usage:

```bash
rbx OLD_NAME NEW_NAME PATH
```

Example:

```bash
rbx Taskly Flowdesk ~/dev/taskly
```

### Preview only

```bash
rbx Taskly Flowdesk ~/dev/taskly -n
```

### Create a renamed copy

```bash
rbx Taskly Flowdesk ~/dev/taskly --into ~/dev/flowdesk
```

### Clean old project metadata

```bash
rbx Taskly Flowdesk ~/dev/taskly --clean
```

### Multiple directories

```bash
rbx Taskly Flowdesk ./a ./b ./c
```

Running `rbx` without arguments opens the desktop application.

---

## CLI Options

| Option                 | Purpose                                 |
| ---------------------- | --------------------------------------- |
| `-n`, `--dry-run`      | Preview without writing                 |
| `-y`, `--yes`          | Skip confirmation                       |
| `-i`, `--ignore-case`  | Match regardless of casing              |
| `-V`, `--no-variants`  | Disable automatic case variants         |
| `-e`, `--regex`        | Treat the find value as regex           |
| `--into DEST`          | Write to a new directory                |
| `--strip-repo`         | Remove references to the old repository |
| `--clean`              | Remove old project metadata files       |
| `--ignore GLOB`        | Add an ignore pattern                   |
| `--no-default-ignores` | Include normally ignored paths          |
| `--no-rename`          | Change contents only                    |
| `--no-contents`        | Rename paths only                       |
| `--no-backup`          | Disable in-place backup                 |
| `-v`                   | Show every changed file                 |
| `--revert PATH`        | Restore an in-place backup              |

---

# Safety

RebrandX is intentionally conservative.

### Binary files are not edited

Files containing binary data or invalid UTF-8 are left untouched internally, although their filenames can still be renamed.

### Encoding is preserved

RebrandX preserves:

* CRLF / LF line endings
* existing encoding behavior
* trailing-newline state

### Renames happen deepest-first

Nested folders are renamed safely before their parents.

Name collisions receive a suffix rather than overwriting another file.

### Symlinks are skipped

A symlink cannot cause RebrandX to modify content outside the selected project tree.

### Dangerous roots are blocked

RebrandX refuses to operate on locations such as:

```text
/
/usr
$HOME
```

and similar high-risk directories.

---

# Architecture

```text
rebrandx/
├── engine.py       Rebrand engine
├── core.py         Shared application logic
├── app_tk.py       native desktop window (Windows + fallback)
├── widgets.py      the drawn controls it is built from
├── theme.py        palette and ttk styling
├── win.py          Windows filesystem + console primitives
├── app.py          Linux GTK shell
├── cli.py          rbx CLI
└── ui/             assets for the GTK shell

bin/                CLI / launcher scripts
packaging/          Linux + Windows packaging
tests/              Engine and GUI tests
share/              App icons and branding
```

The architecture intentionally keeps the rename engine separate from the interface.

```text
             ┌─────────────┐
             │   engine.py │
             └──────┬──────┘
                    │
                ┌───▼───┐
                │ core.py│
                └───┬───┘
                    │
        ┌───────────┼───────────┐
        ▼           ▼           ▼
     Windows      Linux         CLI
      tkinter      GTK          rbx
     (stdlib)
```

`engine.py` uses only the Python standard library and has no dependency on a GUI toolkit.

---

# Tests

Run the engine test suite:

```bash
python3 tests/test_engine.py
```

The suite currently covers **35 checks**, including:

* replacement rules
* scanning
* in-place operations
* copy mode
* backups and revert
* nested renames
* project-file cleanup
* Windows filename handling

Windows behaviour has its own suite:

```bash
python tests/test_windows.py
```

89 checks covering illegal filenames, drive-root guards, encodings and
BOMs, line endings, read-only files, junctions, long paths, case-only
renames and the desktop window itself.

GUI probes drive the real interfaces and report what they painted:

```bash
python tests/gui_probe_tk.py        # the native window
python tests/gui_probe_tk.py --shot window.png
python3 tests/gui_probe.py          # the Linux GTK shell
```

---

## Keyboard Shortcuts

| Shortcut       | Action        |
| -------------- | ------------- |
| `Ctrl + O`     | Open folder   |
| `Ctrl + Enter` | Apply rebrand |
| `Esc`          | Close dialog  |
| `Ctrl + Q`     | Quit          |

---

## Built With

* Python — standard library only
* tkinter for the native desktop window
* GTK 3 / WebKitGTK for the Linux shell

The Windows app has **no third-party dependencies at all**. Every interface shares the same underlying RebrandX engine.

---

<p align="center">
  <b>Rebrand the project — not your afternoon.</b>
</p>
