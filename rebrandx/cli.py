#!/usr/bin/python3
"""rbx — RebrandX on the command line.

    rbx OldName NewName PATH [PATH ...]     rebrand in place
    rbx OldName NewName SRC --into DEST     write a rebranded copy
    rbx                                     open the app
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rebrandx import engine, win                 # noqa: E402
from rebrandx.engine import Options, ApplyError  # noqa: E402

C = {"dim": "\033[2m", "red": "\033[31m", "grn": "\033[33m", "bold": "\033[1m",
     "acc": "\033[36m", "off": "\033[0m"}

# The glyphs the output would like to use, and what to fall back to when the
# stream cannot encode them. Redirecting to a file on Windows hands us a
# cp1252 stream, and a tick or an arrow raises UnicodeEncodeError there --
# so `rbx ... > build.log` used to die where the same command on screen was
# perfectly happy.
GLYPHS = {"tick": "✓", "arrow": "→", "dash": "—", "warn": "!"}
ASCII_GLYPHS = {"tick": "OK", "arrow": "->", "dash": "-", "warn": "!"}


def glyphs(stream=None):
    stream = stream or sys.stdout
    if all(win.encodable(g, stream) for g in GLYPHS.values()):
        return GLYPHS
    return ASCII_GLYPHS


def paint(on: bool):
    """The colour table, or a table of empty strings when colour is off.

    Honours NO_COLOR, and on Windows only returns real escapes once the
    console has actually accepted VT processing -- an old conhost refuses,
    and printing escapes to it produces line noise rather than colour.
    """
    if on and os.environ.get("NO_COLOR"):
        on = False
    if on and os.environ.get("TERM") == "dumb":
        on = False
    if on and not win.enable_ansi():
        on = False
    return C if on else {k: "" for k in C}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rbx", add_help=True,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Rebrand a folder: replace a name in file contents, file names and folder names.",
        epilog="""examples:
  rbx Taskly Flowdesk ~/dev/taskly            rewrite that folder in place
  rbx Taskly Flowdesk ~/dev/taskly -n         preview only, write nothing
  rbx Taskly Flowdesk ~/dev/taskly --into ~/dev/flowdesk
  rbx Taskly Flowdesk ./a ./b ./c             several folders at once
  rbx                                         launch the RebrandX window
""")
    p.add_argument("find", nargs="?", help="the name to find")
    p.add_argument("replace", nargs="?", help="the name to replace it with")
    p.add_argument("paths", nargs="*", help="one or more folders")
    p.add_argument("--into", metavar="DEST",
                   help="write a rebranded copy here instead of editing in place (single path only)")
    p.add_argument("-n", "--dry-run", action="store_true", help="preview only, write nothing")
    p.add_argument("-y", "--yes", action="store_true", help="skip the confirmation prompt")
    p.add_argument("-i", "--ignore-case", action="store_true", help="match any case")
    p.add_argument("-V", "--no-variants", action="store_true",
                   help="only the exact casing typed (default also does Name / NAME / name)")
    p.add_argument("-e", "--regex", action="store_true", help="treat FIND as a regex ($1 groups in REPLACE)")
    p.add_argument("--no-rename", action="store_true", help="do not rename files or folders")
    p.add_argument("--no-contents", action="store_true", help="do not touch file contents")
    p.add_argument("--strip-repo", action="store_true", help="delete lines linking to the old git remote")
    p.add_argument("--strip-project-files", "--clean", action="store_true", dest="strip_project_files",
                   help="delete the old project's own files (LICENSE, CHANGELOG, .github/, …)")
    p.add_argument("--ignore", action="append", default=[], metavar="GLOB",
                   help="extra ignore pattern (repeatable)")
    p.add_argument("--no-default-ignores", action="store_true",
                   help="scan .git/, node_modules/ and *.lock too")
    p.add_argument("--no-backup", action="store_true", help="in place: skip the .rebrandx-backup copy")
    p.add_argument("--copy-ignored", action="store_true", help="--into: copy ignored paths verbatim")
    p.add_argument("-v", "--verbose", action="store_true", help="list every changed file")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--revert", action="store_true",
                   help="undo the last in-place rebrand of PATH from its .rebrandx-backup")
    p.add_argument("--gui", action="store_true", help="open the RebrandX window")
    p.add_argument("--self-test", action="store_true", dest="self_test",
                   help="check this build has everything it needs, then exit")
    return p


def make_options(a) -> Options:
    ex = {} if a.no_default_ignores else {".git/": True, "node_modules/": True, "*.lock": True}
    for g in a.ignore:
        ex[g] = True
    return Options(
        find=a.find, replace=a.replace,
        case_sensitive=not a.ignore_case,
        match_variants=not a.no_variants,
        use_regex=a.regex,
        rename_files=not a.no_rename,
        replace_contents=not a.no_contents,
        strip_meta=a.strip_repo,
        strip_project_files=a.strip_project_files,
        excludes=ex,
        copy_ignored=a.copy_ignored,
    )


def preview(path: str, opts: Options, c, verbose: bool, g=GLYPHS):
    res = engine.scan(path, opts)
    if res.error:
        print("%s%s%s" % (c["red"], res.error, c["off"]), file=sys.stderr)
        return None
    if res.regex_error:
        print("%sinvalid regex: %s%s" % (c["red"], res.regex_error, c["off"]), file=sys.stderr)
        return None
    print("%s%s%s" % (c["bold"], res.root, c["off"]))
    if verbose:
        for e in res.entries:
            if e["dir"] or e["excluded"]:
                continue
            if e.get("drop"):
                print("  %s%s%s   %sdelete%s" % (c["red"], e["path"], c["off"], c["dim"], c["off"]))
                continue
            if not (e["count"] or e["removed"] or e["renamed"]):
                continue
            bits = []
            if e["count"]:
                bits.append("%d replacement%s" % (e["count"], "" if e["count"] == 1 else "s"))
            if e["removed"]:
                bits.append("%d line%s removed" % (e["removed"], "" if e["removed"] == 1 else "s"))
            rn = "  %s%s %s%s" % (c["grn"], g["arrow"], e["newPath"], c["off"]) if e["renamed"] else ""
            print("  %s%s%s%s   %s%s%s" % (c["red"] if e["renamed"] else "", e["path"], c["off"],
                                           rn, c["dim"], ", ".join(bits), c["off"]))
    if res.truncated:
        print("  %s%s tree hit the %d-entry limit; not everything was scanned%s"
              % (c["red"], g["warn"], opts.max_entries, c["off"]))
    print("  %s%d%s files changed  %s%d%s replacements  %s%d%s renames  "
          "%s%d%s lines removed  %s%d%s files deleted" % (
              c["acc"], res.files_changed, c["off"], c["acc"], res.replacements, c["off"],
              c["acc"], res.renames, c["off"], c["acc"], res.removed, c["off"],
              c["acc"], res.dropped, c["off"]))
    return res


def report(text: str) -> None:
    """Say something that went wrong, wherever this build can be read from.

    Normally stderr. A double-clicked build has no console anybody can see
    -- Windows opened one and it was hidden on the way in, because the
    point of a double-click is the window, not a terminal -- so there it
    goes in a message box instead of nowhere.
    """
    if (win.hidden_console() or sys.stderr is None) and win.error_dialog("RebrandX", text):
        return
    if sys.stderr is not None:
        print(text, file=sys.stderr)


def _self_test(c, g) -> int:
    """Report what this build is, and prove the parts of it work.

    A frozen .exe is opaque from the outside: `rbx --help` succeeding says
    nothing about whether the window can still open, and the way that fails
    is a traceback in front of somebody who double-clicked it. So the build
    checks itself -- the build script and CI both run this against the
    freshly built rbx.exe.
    """
    ok = True
    rows = [("python", "%d.%d.%d" % sys.version_info[:3]),
            ("build", "frozen, self-contained" if getattr(sys, "frozen", False)
                      else "source checkout"),
            ("console", "ours alone" if win.owns_console()
                        else "shared with a shell" if sys.stdout and sys.stdout.isatty()
                        else "none")]

    try:
        import tkinter
        rows.append(("tkinter", "Tk %s" % tkinter.TkVersion))
    except ImportError as exc:
        ok = False
        rows.append(("tkinter", "missing -- %s" % exc))

    try:
        from rebrandx import app_tk  # noqa: F401
        rows.append(("window", "ready"))
    except Exception as exc:                                # noqa: BLE001
        ok = False
        rows.append(("window", "%s: %s" % (type(exc).__name__, exc)))

    # The engine, end to end, on a project small enough to build here.
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "taskly"
            (src / "src").mkdir(parents=True)
            (src / "src" / "taskly.txt").write_text("taskly\n", encoding="utf-8")
            res = engine.scan(str(src), Options(find="Taskly", replace="Flowdesk"))
            if res.error or res.replacements < 1 or res.renames < 1:
                raise ValueError(res.error or "nothing found in the fixture")
        rows.append(("engine", "%d replacement, %d rename on a test project"
                     % (res.replacements, res.renames)))
    except Exception as exc:                                # noqa: BLE001
        ok = False
        rows.append(("engine", "%s: %s" % (type(exc).__name__, exc)))

    print("%srbx self-test%s" % (c["bold"], c["off"]))
    for name, value in rows:
        print("  %-9s %s" % (name, value))
    print("%s%s%s %s" % (c["grn"] if ok else c["red"],
                         g["tick"] if ok else g["warn"], c["off"],
                         "everything this build needs is here" if ok
                         else "this build is incomplete"))
    return 0 if ok else 1


def _open_window(args) -> int:
    """Open the desktop window.

    Windows gets the native tkinter app -- it needs nothing installed. On
    Linux the GTK shell is preferred where its bindings are present, and
    the same native window is the fallback when they are not.

    Double-clicking rbx.exe lands here, and a console-subsystem binary is
    handed a terminal by Windows on the way in whether it wants one or not.
    It is ours alone in that case, so it goes away before the window opens
    -- an app should not come up with a black rectangle behind it.
    """
    if os.name != "nt":
        try:
            from rebrandx.app_gtk import main as gtk_main
            return gtk_main(args)
        except (ImportError, ValueError):
            pass
    win.hide_console()
    try:
        from rebrandx.app_tk import main as tk_main
    except ImportError as exc:
        # A frozen build always carries tkinter. Running from source on a
        # Linux distribution that packages it separately does not.
        report("The RebrandX window needs tkinter, which this Python does "
               "not have (%s).\n\nInstall it (Debian/Ubuntu: sudo apt "
               "install python3-tk), or use the command line:\n\n"
               "    rbx OldName NewName PATH" % exc)
        return 1
    return tk_main(args)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    a = build_parser().parse_args(argv)
    # Ask for UTF-8 first: if the stream can be persuaded, the nice glyphs
    # survive being redirected to a file on Windows.
    # pythonw.exe and a .pyw shortcut give a process with no stdout at all,
    # so this cannot assume there is a stream to ask.
    tty = bool(sys.stdout is not None and sys.stdout.isatty())
    if tty:
        # A console renders UTF-8 properly. A redirect is left in the
        # machine's own codepage instead, so `type build.log` shows text
        # rather than mojibake -- glyphs() drops to ASCII to suit.
        win.use_utf8()
    c = paint(tty and not a.no_color)
    g = glyphs()

    if a.self_test:
        return _self_test(c, g)

    if a.revert:
        rc = 0
        for raw in ([a.find] if a.find else []) + ([a.replace] if a.replace else []) + a.paths:
            man_path = (Path(os.path.expanduser(raw)) / engine.BACKUP_DIRNAME
                        / engine.MANIFEST_NAME)
            if not man_path.is_file():
                print("%sno backup found in %s%s" % (c["red"], raw, c["off"]), file=sys.stderr)
                rc = 1
                continue
            try:
                print("%s%s%s %s" % (c["grn"], g["tick"], c["off"],
                                     engine.revert(engine.read_manifest(man_path))))
            except (ApplyError, OSError, ValueError) as exc:
                print("%s%s%s" % (c["red"], exc, c["off"]), file=sys.stderr)
                rc = 1
        return rc

    # One argument, and it is a folder: that is a drag-and-drop onto the
    # .exe, or `rbx .` typed hopefully. Explorer hands the dropped path
    # straight to the program, and nobody means "find C:\dev\taskly" by it.
    dropped = bool(a.find and not a.replace and not a.paths
                   and os.path.isdir(os.path.expanduser(a.find)))
    if a.gui or dropped or not (a.find or a.replace or a.paths):
        folder = a.paths[0] if a.paths else (a.find if dropped else None)
        return _open_window([sys.argv[0]] + ([folder] if folder else []))

    if not a.find or not a.replace or not a.paths:
        # Printing usage to a console the user cannot see is the same as
        # saying nothing -- which is what dropping a *file* on rbx.exe,
        # rather than a folder, used to do.
        if win.hidden_console():
            report("RebrandX did not know what to do with:\n\n    %s\n\n"
                   "Drop a folder on rbx.exe to open it in the app, or run\n\n"
                   "    rbx OldName NewName PATH\n\nfrom a terminal."
                   % "  ".join(argv))
            return 2
        build_parser().print_usage(sys.stderr)
        print("rbx: need FIND, REPLACE and at least one PATH "
              "(or run `rbx` with no arguments for the app)", file=sys.stderr)
        return 2

    if a.into and len(a.paths) > 1:
        print("rbx: --into takes a single source folder", file=sys.stderr)
        return 2

    opts = make_options(a)
    results = []
    for p in a.paths:
        res = preview(p, opts, c, a.verbose or a.dry_run, g)
        if res is None:
            return 1
        results.append((p, res))
        print()

    total = sum(r.files_changed for _, r in results)
    if a.dry_run:
        print("%sdry run %s nothing written%s" % (c["dim"], g["dash"], c["off"]))
        return 0
    if total == 0:
        print("%snothing to do%s" % (c["dim"], c["off"]))
        return 0

    if not a.yes:
        where = ("copied into %s" % a.into) if a.into else "rewritten in place"
        extra = "" if (a.into or a.no_backup) else " (a .rebrandx-backup copy is kept)"
        try:
            ans = input("Rebrand %d file%s %s they will be %s%s. Continue? [y/N] "
                        % (total, "" if total == 1 else "s", g["dash"], where, extra))
        except (EOFError, KeyboardInterrupt):
            print(); return 130
        if ans.strip().lower() not in ("y", "yes"):
            print("cancelled")
            return 1

    for p, _ in results:
        try:
            man = engine.apply(p, opts, mode="copy" if a.into else "inplace",
                               dest=a.into or "", backup=not a.no_backup)
        except ApplyError as exc:
            print("%s%s%s" % (c["red"], exc, c["off"]), file=sys.stderr)
            return 1
        if a.into:
            print("%s%s%s %s %s %s (%d files)" % (c["grn"], g["tick"], c["off"],
                                                  p, g["arrow"], man["dest"], man["files"]))
        else:
            print("%s%s%s %s %s %d rewritten, %d renamed, %d deleted%s" % (
                c["grn"], g["tick"], c["off"], p, g["dash"],
                man["files"], len(man["renames"]),
                man.get("dropped", 0),
                "" if a.no_backup else ", backup in .rebrandx-backup/"))
    return 0


def run() -> int:
    """main(), with somewhere to put a crash.

    In a shell this changes nothing: the traceback goes to stderr, exactly
    as it always did. A double-clicked build is the case worth handling --
    its console is hidden, so the traceback would land where nobody can
    read it and the process would exit looking like it had simply declined
    to start.
    """
    try:
        return main()
    except KeyboardInterrupt:
        return 130
    except Exception:                                       # noqa: BLE001
        if not (win.hidden_console() or sys.stderr is None):
            raise
        import traceback
        report("RebrandX hit an error it could not recover from.\n\n"
               + traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(run())
