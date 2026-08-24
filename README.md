# RebrandX

Rebrand a folder. Point it at a project, give it an old name and a new one, and
it replaces that name across **file contents, file names and folder names** —
showing you every change as a diff before anything is written.

Built for Ubuntu. Ships as a desktop app and as an `rbx` command.

---

## Install

### Option A — the .deb (system-wide, the normal Ubuntu way)

```bash
cd ~/.local/share/rebrandx && ./packaging/build-deb.sh
sudo apt install ~/.local/share/rebrandx/dist/rebrandx_1.0.0_all.deb
```

Puts `rebrandx` and `rbx` on everyone's PATH and registers the app with GNOME.
Remove it later with `sudo apt remove rebrandx`.

### Option B — just for you, no sudo

```bash
cd ~/.local/share/rebrandx && ./install.sh          # add --no-desktop-icon to skip the Desktop shortcut
```

Installs into `~/.local` only. Undo it with `./uninstall.sh`.

Either way you then get:

- **Press Super, type "RebrandX"** — or pin it to the dock
- **A double-clickable icon on the Desktop** (Option B)
- **Right-click any folder in Files → Scripts → Rebrand with RebrandX**
- `rbx` in the terminal

### Requirements

Ubuntu with GNOME, and:

```bash
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1
```

These are already present on a stock Ubuntu desktop. There is nothing to
compile and no `pip install` — RebrandX is pure Python on the system GTK stack.

---

## The app

One window, three columns.

**Rules** (left) — the find and replace names, plus the switches:

| Option | What it does |
| --- | --- |
| Match case variants | `taskly` · `Taskly` · `TASKLY` all get mapped, each to the matching casing of the new name |
| Rename files & folders | Applies the rules to paths, not just contents |
| Remove old repo lines | Deletes whole lines pointing at the old GitHub/GitLab/Bitbucket remote |
| Remove old project files | Deletes the old project's *own* files — see below |
| Case sensitive | *Advanced.* Off = match any casing, replace with exactly what you typed |
| Regex find | *Advanced.* `FIND` becomes a pattern; use `$1` for groups in the replacement |
| Replace inside contents | *Advanced.* Turn off to rename only |
| Dry-run mode | *Advanced.* Scans and reports, writes nothing |

**Remove GitHub & licence files** — the button under Options, or the matching
toggle. It deletes the files that carry the *old project's identity* rather
than its code, leaving you the part that matters:

    .github/  .gitlab/  .circleci/  .travis.yml  appveyor.yml
    LICENSE  LICENCE  COPYING  NOTICE
    CHANGELOG  CHANGES  HISTORY  RELEASES  RELEASE-NOTES
    AUTHORS  CONTRIBUTORS  MAINTAINERS  CODEOWNERS
    CODE_OF_CONDUCT  CONTRIBUTING  SECURITY  SUPPORT
    CITATION  FUNDING.yml  .all-contributorsrc

`README.md`, `package.json` and your source are **not** touched by this — they
get rebranded normally. Every pattern is editable under **Advanced › Files to
delete**, and any single file can be kept with the ✕ beside it in the list.

Deletions are backed up like everything else, and **Revert** brings them back —
including whole folders such as `.github/`. In copy mode they are simply never
written to the new folder, so the original is untouched either way.

**Ignore flags** — `.git/`, `node_modules/` and `*.lock` are skipped by default.
Click one to un-ignore it; `+` adds your own pattern.

**Files** (middle) — every entry, with a change count and its new name.
The `✕` on a row skips that whole file; `↺` puts it back.

**Diff** (right) — the actual before/after lines. Every changed line has its own
**skip** button, so you can keep individual lines exactly as they are.

**Two modes**, chosen in the toolbar:

- **Rebrand in place** — rewrites the folder. A `.rebrandx-backup/` copy is kept
  (switch it off in Settings), and **Revert** restores it.
- **Copy to new folder** — leaves the original untouched and writes the
  rebranded result somewhere new. Ignored paths are *not* copied, so you get a
  clean tree; the "Copy ignored files too" setting changes that.

Nothing is written until you press **Apply rebrand**, and you get a summary
dialog before it happens.

### Shortcuts

`Ctrl+O` pick a folder · `Ctrl+Enter` apply · `Esc` close a dialog · `Ctrl+Q` quit

---

## The command line

The shape you'd expect — old name, new name, then one or more folders:

```bash
rbx Taskly Flowdesk ~/dev/taskly
```

```bash
rbx Taskly Flowdesk ~/dev/taskly -n          # preview only, writes nothing
rbx Taskly Flowdesk ~/dev/taskly --into ~/dev/flowdesk
rbx Taskly Flowdesk ~/dev/taskly --clean       # also delete LICENSE, CHANGELOG, .github/
rbx Taskly Flowdesk ./a ./b ./c              # several folders in one go
rbx                                          # opens the app
```

| Flag | |
| --- | --- |
| `-n`, `--dry-run` | preview, write nothing |
| `-y`, `--yes` | skip the confirmation prompt |
| `-i`, `--ignore-case` | match any casing |
| `-V`, `--no-variants` | only the exact casing you typed |
| `-e`, `--regex` | treat FIND as a regex |
| `--into DEST` | write a copy instead of editing in place |
| `--strip-repo` | drop lines linking to the old git remote |
| `--clean` | delete the old project's own files (LICENSE, CHANGELOG, `.github/`, …) |
| `--ignore GLOB` | extra ignore pattern (repeatable) |
| `--no-default-ignores` | scan `.git/`, `node_modules/`, `*.lock` too |
| `--no-rename` / `--no-contents` | do one half of the job only |
| `--no-backup` | in place: skip the backup copy |
| `-v` | list every changed file |
| `--revert PATH` | undo the last in-place rebrand of PATH from its backup |

By default it asks before writing, and in-place runs keep a backup.

---

## How it decides what to change

- **Case variants** are compiled into a *single* alternation, so one pass does
  all the work. Replacing `task` with `taskly` can't re-match its own output.
- **Binary files are never edited.** Anything with a NUL byte in its first 8 KB,
  or that isn't valid UTF-8, is copied through untouched — it can still be
  renamed. Same for files over 2 MB.
- **Line endings and encoding are preserved.** A CRLF file stays CRLF; a file
  with no trailing newline doesn't gain one.
- **Renames run deepest-first**, so parent folders stay valid while their
  children move. Collisions get a `-2` suffix rather than overwriting.
- **Symlinks are skipped**, so a link can't walk the rebrand outside the tree.
- **"Remove old repo lines"** only deletes a line if it *both* mentions a code
  host (or a `"repository"` field) *and* contains the name you're replacing.
- **The folder you point at is not itself renamed** in place — only things
  inside it. In copy mode you choose the new folder's name directly.
- It refuses to run on `/`, `/usr`, your home directory and similar.

---

## Layout

```
~/.local/share/rebrandx/
├── rebrandx/
│   ├── engine.py     the rebrand engine — scan, diff, apply, revert
│   ├── app.py        GTK3 window hosting the WebKit UI + the JS bridge
│   ├── cli.py        the rbx command
│   └── ui/           index.html · app.css · app.js
├── bin/              rbx, rebrandx launchers
├── packaging/        build-deb.sh
├── share/            app icon
├── install.sh        no-sudo install into ~/.local
└── uninstall.sh      removes it again
```

`engine.py` imports nothing but the standard library and knows nothing about
GTK — the app and the CLI are two front ends over the same code.

---

## Prior art

The tool this resembles is **`repren`** — same idea of one pass over contents
*and* filenames with case variants. `rpl`, `sd`, `fastmod` and plain
`find | sed` cover parts of it. RebrandX's angle is the preview: seeing the
diff and skipping individual lines before committing to the rewrite.
