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

sudo apt install ~/.local/share/rebrandx/dist/rebrandx_1.0.0_all.deb
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

## Windows

Windows 10 and 11 include WebView2.

Install the UI dependency:

```powershell
pip install pywebview
```

Run:

```powershell
python rebrandx\app_win.py
```

or:

```text
bin\rebrandx.bat
```

### Build a standalone EXE

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build-windows.ps1
```

Output:

```text
RebrandX.exe
```

See [`packaging/README-windows.md`](packaging/README-windows.md) for Windows-specific behavior including NTFS case-only renames, long paths and invalid Windows filenames.

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
├── app.py          Linux GTK shell
├── app_win.py      Windows WebView2 shell
├── cli.py          rbx CLI
└── ui/
    ├── index.html
    ├── app.css
    └── app.js

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
      Linux       Windows       CLI
       GTK        WebView2      rbx
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

A separate GUI probe tests the actual GTK interface.

```bash
python3 tests/gui_probe.py
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

* Python
* GTK 3
* WebKitGTK
* WebView2
* pywebview

The Linux and Windows interfaces share the same underlying RebrandX engine.

---

<p align="center">
  <b>Rebrand the project — not your afternoon.</b>
</p>
