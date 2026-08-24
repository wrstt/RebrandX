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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rebrandx import engine                      # noqa: E402
from rebrandx.engine import Options, ApplyError  # noqa: E402

C = {"dim": "\033[2m", "red": "\033[31m", "grn": "\033[33m", "bold": "\033[1m",
     "acc": "\033[36m", "off": "\033[0m"}


def paint(on: bool):
    if on and os.name == "nt":
        # Windows consoles need VT processing switched on before ANSI works.
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)
        except Exception:
            return {k: "" for k in C}
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


def preview(path: str, opts: Options, c, verbose: bool):
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
            rn = "  %s→ %s%s" % (c["grn"], e["newPath"], c["off"]) if e["renamed"] else ""
            print("  %s%s%s%s   %s%s%s" % (c["red"] if e["renamed"] else "", e["path"], c["off"],
                                           rn, c["dim"], ", ".join(bits), c["off"]))
    if res.truncated:
        print("  %s! tree hit the %d-entry limit; not everything was scanned%s"
              % (c["red"], opts.max_entries, c["off"]))
    print("  %s%d%s files changed  %s%d%s replacements  %s%d%s renames  "
          "%s%d%s lines removed  %s%d%s files deleted" % (
              c["acc"], res.files_changed, c["off"], c["acc"], res.replacements, c["off"],
              c["acc"], res.renames, c["off"], c["acc"], res.removed, c["off"],
              c["acc"], res.dropped, c["off"]))
    return res


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    a = build_parser().parse_args(argv)
    c = paint(sys.stdout.isatty() and not a.no_color)

    if a.revert:
        import json
        rc = 0
        for raw in ([a.find] if a.find else []) + ([a.replace] if a.replace else []) + a.paths:
            man_path = Path(os.path.expanduser(raw)) / engine.BACKUP_DIRNAME / "manifest.json"
            if not man_path.is_file():
                print("%sno backup found in %s%s" % (c["red"], raw, c["off"]), file=sys.stderr)
                rc = 1
                continue
            try:
                print("%s✓%s %s" % (c["grn"], c["off"], engine.revert(json.loads(man_path.read_text()))))
            except (ApplyError, OSError, ValueError) as exc:
                print("%s%s%s" % (c["red"], exc, c["off"]), file=sys.stderr)
                rc = 1
        return rc

    if a.gui or (not a.find and not a.replace and not a.paths):
        args = [sys.argv[0]] + ([a.paths[0]] if a.paths else [])
        if os.name == "nt":
            from rebrandx.app_win import main as gui_main
        else:
            from rebrandx.app import main as gui_main
        return gui_main(args)

    if not a.find or not a.replace or not a.paths:
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
        res = preview(p, opts, c, a.verbose or a.dry_run)
        if res is None:
            return 1
        results.append((p, res))
        print()

    total = sum(r.files_changed for _, r in results)
    if a.dry_run:
        print("%sdry run — nothing written%s" % (c["dim"], c["off"]))
        return 0
    if total == 0:
        print("%snothing to do%s" % (c["dim"], c["off"]))
        return 0

    if not a.yes:
        where = ("copied into %s" % a.into) if a.into else "rewritten in place"
        extra = "" if (a.into or a.no_backup) else " (a .rebrandx-backup copy is kept)"
        try:
            ans = input("Rebrand %d file%s — they will be %s%s. Continue? [y/N] "
                        % (total, "" if total == 1 else "s", where, extra))
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
            print("%s✓%s %s → %s (%d files)" % (c["grn"], c["off"], p, man["dest"], man["files"]))
        else:
            print("%s✓%s %s — %d rewritten, %d renamed, %d deleted%s" % (
                c["grn"], c["off"], p, man["files"], len(man["renames"]),
                man.get("dropped", 0),
                "" if a.no_backup else ", backup in .rebrandx-backup/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
