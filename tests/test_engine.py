#!/usr/bin/env python3
"""RebrandX engine tests. Pure stdlib, no test runner, runs on any platform.

    python3 tests/test_engine.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rebrandx import engine
from rebrandx.engine import Options, Rules, windows_unsafe, safe_rename

PASS, FAIL = [], []


def check(name, got, want):
    (PASS if got == want else FAIL).append((name, got, want))
    print("  %s %s" % ("✓" if got == want else "✗", name), end="")
    print("" if got == want else "\n      got  %r\n      want %r" % (got, want))


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)).replace(os.sep, "/"):
            hashlib.md5(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file() and engine.BACKUP_DIRNAME not in p.parts}


def fixture(base: Path) -> Path:
    """A small but representative old project."""
    r = base / "taskly"
    for d in ("src", "docs", ".github/workflows", "node_modules/dep"):
        (r / d).mkdir(parents=True, exist_ok=True)
    (r / "README.md").write_text(
        "# Taskly\nSource: github.com/alexdev/taskly\nRun taskly now.\nTASKLY rocks.\n")
    (r / "package.json").write_text('{"name": "taskly"}\n')
    (r / "src/index.js").write_text("const taskly = require('./taskly-core');\n")
    (r / "src/taskly-core.js").write_text("class TasklyCore {}\n")
    (r / "docs/guide.md").write_text("taskly docs\n")
    (r / "LICENSE").write_text("MIT License\n")
    (r / "CHANGELOG.md").write_text("# Changelog\n")
    (r / ".github/workflows/build.yml").write_text("name: build\n")
    (r / "node_modules/dep/i.js").write_text("taskly\n")
    (r / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00taskly\x00binary")
    (r / "crlf.txt").write_bytes(b"taskly one\r\ntaskly two\r\n")
    (r / "notrail.txt").write_bytes(b"taskly")
    return r


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="rbx-test-"))
    try:
        print("\nRules")
        r = Rules("taskly", "flowdesk")
        check("case variants", r.sub("taskly Taskly TASKLY"), "flowdesk Flowdesk FLOWDESK")
        check("variant chips", len(r.chips()), 3)
        check("no double-substitution", Rules("task", "taskly").sub("task task"), "taskly taskly")
        check("case-insensitive", Rules("taskly", "flowdesk", case_sensitive=False)
              .sub("Taskly TASKLY"), "flowdesk flowdesk")
        check("no variants", Rules("taskly", "flowdesk", match_variants=False)
              .sub("taskly Taskly"), "flowdesk Taskly")
        check("regex $1 groups", Rules(r"(\w+)ly", "$1LY", use_regex=True)
              .sub("quickly slowly"), "quickLY slowLY")
        check("invalid regex is caught", Rules("[bad(", "x", use_regex=True).ok, False)

        print("\nWindows-safe names")
        check("reserved device name", bool(windows_unsafe("CON.txt")), True)
        check("illegal character", bool(windows_unsafe('a:b.js')), True)
        check("normal name", windows_unsafe("index.js"), None)
        cs = tmp / "cs"; cs.mkdir(); (cs / "a.js").write_text("x")
        safe_rename(cs / "a.js", cs / "A.js")
        check("case-only rename", [p.name for p in cs.iterdir()], ["A.js"])

        print("\nScan")
        src = fixture(tmp)
        o = Options(find="taskly", replace="flowdesk", strip_meta=True)
        res = engine.scan(str(src), o)
        paths = {e["path"]: e for e in res.entries}
        check("ignores node_modules", paths["node_modules"]["excluded"], True)
        check("detects binary", paths["logo.png"]["binary"], True)
        check("binary not counted", paths["logo.png"]["count"], 0)
        check("detects rename", paths["src/taskly-core.js"]["newPath"], "src/flowdesk-core.js")
        check("counts repo line", paths["README.md"]["removed"], 1)

        print("\nCopy mode")
        dest = tmp / "out"
        m = engine.apply(str(src), o, mode="copy", dest=str(dest))
        check("source untouched", (src / "src/taskly-core.js").exists(), True)
        check("renamed in copy", (dest / "src/flowdesk-core.js").exists(), True)
        check("ignored dir not copied", (dest / "node_modules").exists(), False)
        check("repo line stripped", "github.com" in (dest / "README.md").read_text(), False)
        check("binary preserved",
              (dest / "logo.png").read_bytes(), (src / "logo.png").read_bytes())
        check("CRLF preserved", b"\r\n" in (dest / "crlf.txt").read_bytes(), True)
        check("no newline added", (dest / "notrail.txt").read_bytes(), b"flowdesk")

        print("\nIn-place + revert")
        before = tree(src)
        m2 = engine.apply(str(src), o, mode="inplace", backup=True)
        check("renamed in place", (src / "src/flowdesk-core.js").exists(), True)
        engine.revert(m2)
        check("revert is byte-identical", tree(src), before)
        check("backup removed", (src / engine.BACKUP_DIRNAME).exists(), False)

        print("\nRemove old project files")
        o2 = Options(find="taskly", replace="flowdesk", strip_project_files=True)
        res2 = engine.scan(str(src), o2)
        dropped = sorted(e["path"] for e in res2.entries if e.get("drop") and not e["dir"])
        check("flags project files", dropped,
              [".github/workflows/build.yml", "CHANGELOG.md", "LICENSE"])
        check("keeps README", any(e["path"] == "README.md" and e.get("drop")
                                  for e in res2.entries), False)
        before2 = tree(src)
        m3 = engine.apply(str(src), o2, mode="inplace", backup=True)
        check("deleted them", (src / "LICENSE").exists(), False)
        check(".github gone", (src / ".github").exists(), False)
        engine.revert(m3)
        check("revert restores deletions", tree(src), before2)

        print("\nNested renames")
        n = tmp / "n"; (n / "taskly-core" / "taskly-deep").mkdir(parents=True)
        (n / "taskly-core" / "taskly-deep" / "taskly.txt").write_text("taskly\n")
        engine.apply(str(n), Options(find="taskly", replace="flowdesk"), mode="inplace", backup=False)
        check("no stray duplicate dirs", len(list(n.glob("**/*-2"))), 0)
        check("deep rename correct",
              (n / "flowdesk-core" / "flowdesk-deep" / "flowdesk.txt").exists(), True)

        print("\nSafety")
        try:
            engine.apply(str(Path.home()), Options(find="a", replace="b"), mode="inplace")
            check("refuses home directory", "no error", "ApplyError")
        except engine.ApplyError:
            check("refuses home directory", True, True)
        try:
            engine.apply(str(src), Options(find="", replace="b"), mode="inplace")
            check("refuses empty find", "no error", "ApplyError")
        except engine.ApplyError:
            check("refuses empty find", True, True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d passed, %d failed" % (len(PASS), len(FAIL)))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
