#!/usr/bin/env python3
"""RebrandX Windows tests. Pure stdlib, no test runner.

    python tests\\test_windows.py

The name rules, the root guard and the encoding sniffing are platform
independent by design -- a project rebranded on Linux still has to open on
Windows -- so those checks run everywhere. The ones that need real NTFS
behaviour (read-only attributes, junctions, case-insensitive renames) skip
themselves off Windows and say so.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rebrandx import engine, win
from rebrandx.engine import Options

# Windows consoles default to cp1252, which cannot encode the tick marks.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PASS, FAIL, SKIP = [], [], []
IS_WIN = os.name == "nt"


def check(name, got, want):
    (PASS if got == want else FAIL).append((name, got, want))
    print("  %s %s" % ("✓" if got == want else "✗", name), end="")
    print("" if got == want else "\n      got  %r\n      want %r" % (got, want))


def skip(name, why):
    SKIP.append(name)
    print("  – %s (%s)" % (name, why))


def section(title):
    print("\n%s" % title)


def main() -> int:                                          # noqa: C901
    tmp = Path(tempfile.mkdtemp(prefix="rbx-win-"))
    try:
        # ------------------------------------------------------------------
        section("Illegal Windows names")
        for bad, why in [("CON.txt", "reserved"), ("com1", "reserved"),
                         ("nul.tar.gz", "reserved"), ("aux", "reserved"),
                         ("CONIN$", "reserved"), ("a:b.js", "colon"),
                         ('q"x', "quote"), ("pipe|d", "pipe"),
                         ("star*", "star"), ("back\\slash", "separator"),
                         ("trailing ", "trailing space"),
                         ("trailing.", "trailing dot"), ("x" * 300, "too long")]:
            check("rejects %-14s" % ("%r" % bad)[:14], bool(win.unsafe_name(bad)), True)
        for good in ["index.js", "README.md", ".gitignore", "CONSOLE.md",
                     "console.log.js", "a.b.c", "COMx", "LPT0"]:
            check("accepts %-14s" % ("%r" % good)[:14], win.unsafe_name(good), None)

        section("Sanitising a name the rebrand made illegal")
        check("colon replaced", win.sanitize_name("api:v2.js"), "api-v2.js")
        check("device escaped", win.sanitize_name("aux.py"), "_aux.py")
        check("trailing dot cut", win.sanitize_name("name."), "name")
        check("never empty", win.sanitize_name("..."), "_")
        check("stays legal", win.unsafe_name(win.sanitize_name('a<b>c:"d')), None)

        # ------------------------------------------------------------------
        section("Roots that must be refused")
        if IS_WIN:
            drive = os.environ.get("SystemDrive", "C:") + os.sep
            for bad in [drive, drive + "Users", os.environ.get("SystemRoot", r"C:\Windows"),
                        str(Path.home()), str(Path.home() / "Desktop"),
                        str(Path.home() / "Documents"), r"\\server\share"]:
                check("refuses %s" % bad, win.is_unsafe_root(bad), True)
            check("allows a project folder",
                  win.is_unsafe_root(str(Path.home() / "dev" / "myproject")), False)
            check("allows a UNC project",
                  win.is_unsafe_root(r"\\server\share\myproject"), False)
        else:
            for bad in ["/", "/usr", "/etc", str(Path.home())]:
                check("refuses %s" % bad, win.is_unsafe_root(bad), True)
            check("allows a project folder",
                  win.is_unsafe_root(str(Path.home() / "dev" / "myproject")), False)

        check("apply refuses a drive root", *_expect_apply_error(
            os.environ.get("SystemDrive", "C:") + os.sep if IS_WIN else "/usr"))

        # ------------------------------------------------------------------
        section("Path comparison uses the filesystem's case rules")
        if IS_WIN:
            check("same_path ignores case", win.same_path(r"C:\A\b.JS", r"c:\a\B.js"), True)
            check("is_inside ignores case", win.is_inside(r"C:\dev\App", r"c:\DEV"), True)
        else:
            check("same_path is exact", win.same_path("/a/B", "/a/b"), False)
            check("is_inside is exact", win.is_inside("/dev/App", "/dev"), True)
        check("is_inside rejects a sibling",
              win.is_inside(os.path.join("x", "devtools"), "x" + os.sep + "dev"), False)
        check("is_inside accepts itself", win.is_inside("x", "x"), True)

        # ------------------------------------------------------------------
        section("Encodings Windows tools actually produce")
        enc = tmp / "enc"
        enc.mkdir()
        cases = {
            "utf8.txt":     ("taskly ok".encode("utf-8"), "utf-8", b""),
            "utf8bom.txt":  (b"\xef\xbb\xbf" + "taskly ok".encode("utf-8"), "utf-8", b"\xef\xbb\xbf"),
            "utf16le.txt":  (b"\xff\xfe" + "taskly ok".encode("utf-16-le"), "utf-16-le", b"\xff\xfe"),
            "utf16be.txt":  (b"\xfe\xff" + "taskly ok".encode("utf-16-be"), "utf-16-be", b"\xfe\xff"),
            "cp1252.txt":   ("taskly caf\xe9".encode("cp1252"), "cp1252", b""),
        }
        for name, (raw, want_enc, want_bom) in cases.items():
            (enc / name).write_bytes(raw)
            tf = engine.read_text(enc / name, engine.DEFAULT_MAX_FILE_BYTES)
            check("reads %-12s" % name, tf is not None and tf.encoding, want_enc)
            check("BOM   %-12s" % name, tf is not None and tf.bom, want_bom)

        (enc / "real-binary.bin").write_bytes(b"\x00\x01\x02taskly\x00\xff")
        check("binary still refused",
              engine.read_text(enc / "real-binary.bin", engine.DEFAULT_MAX_FILE_BYTES), None)

        section("A rebrand preserves the encoding it found")
        opts = Options(find="taskly", replace="flowdesk", excludes={})
        engine.apply(str(enc), opts, mode="inplace", backup=False)
        for name, (raw, want_enc, want_bom) in cases.items():
            out = (enc / name).read_bytes()
            check("%-12s keeps its BOM" % name, out.startswith(want_bom) if want_bom
                  else not out.startswith(b"\xef\xbb\xbf") and not out.startswith(b"\xff\xfe"), True)
            decoded = out[len(want_bom):].decode(want_enc)
            check("%-12s was rebranded" % name, "flowdesk" in decoded, True)
        check("cp1252 accent survived",
              "caf\xe9" in (enc / "cp1252.txt").read_bytes().decode("cp1252"), True)

        # ------------------------------------------------------------------
        section("Line endings")
        nl = tmp / "nl"
        nl.mkdir()
        (nl / "crlf.txt").write_bytes(b"taskly a\r\ntaskly b\r\n")
        (nl / "lf.txt").write_bytes(b"taskly a\ntaskly b\n")
        # Mostly LF with one stray CRLF: the stray must not convert the file.
        (nl / "mixed.txt").write_bytes(b"taskly a\ntaskly b\ntaskly c\r\ntaskly d\n")
        engine.apply(str(nl), Options(find="taskly", replace="flowdesk", excludes={}),
                     mode="inplace", backup=False)
        check("CRLF stays CRLF", (nl / "crlf.txt").read_bytes(),
              b"flowdesk a\r\nflowdesk b\r\n")
        check("LF stays LF", (nl / "lf.txt").read_bytes(),
              b"flowdesk a\nflowdesk b\n")
        check("one stray CRLF does not convert the file",
              (nl / "mixed.txt").read_bytes().count(b"\r\n"), 0)

        # ------------------------------------------------------------------
        section("Read-only files")
        ro = tmp / "ro"
        ro.mkdir()
        (ro / "taskly.txt").write_text("taskly here")
        os.chmod(ro / "taskly.txt", stat.S_IREAD)
        try:
            engine.apply(str(ro), Options(find="taskly", replace="flowdesk", excludes={}),
                         mode="inplace", backup=True)
            check("rewrites a read-only file",
                  "flowdesk" in (ro / "flowdesk.txt").read_text(), True)
        except OSError as exc:
            check("rewrites a read-only file", "OSError: %s" % exc, "no error")
        # The backup wipe is the step that used to fail: git leaves every
        # object read-only, so rmtree could not clear its own backup.
        rotree = tmp / "rotree"
        (rotree / "sub").mkdir(parents=True)
        (rotree / "sub" / "locked.txt").write_text("x")
        os.chmod(rotree / "sub" / "locked.txt", stat.S_IREAD)
        try:
            win.rmtree(rotree)
            check("rmtree clears read-only files", rotree.exists(), False)
        except OSError as exc:
            check("rmtree clears read-only files", "OSError: %s" % exc, "no error")

        # ------------------------------------------------------------------
        section("Case-only renames")
        cs = tmp / "cs"
        cs.mkdir()
        (cs / "taskly.js").write_text("x")
        engine.safe_rename(cs / "taskly.js", cs / "Taskly.js")
        names = [p.name for p in cs.iterdir()]
        check("no -2 duplicate invented", len(names), 1)
        check("renamed to the new casing", names[0], "Taskly.js")

        # ------------------------------------------------------------------
        section("Junctions and symlinks are not followed")
        if IS_WIN:
            jroot = tmp / "junc"
            (jroot / "real").mkdir(parents=True)
            (jroot / "real" / "taskly.txt").write_text("taskly")
            rc = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(jroot / "link"), str(jroot / "real")],
                capture_output=True, text=True)
            if rc.returncode != 0:
                skip("junction is skipped", "mklink unavailable")
            else:
                seen = [rel for rel, _d, _dep, _f in engine.walk(jroot, Options())]
                check("junction is not descended into",
                      any(r.startswith("link/") for r in seen), False)
                check("the real folder still is",
                      "real/taskly.txt" in seen, True)
        else:
            sroot = tmp / "sym"
            (sroot / "real").mkdir(parents=True)
            (sroot / "real" / "taskly.txt").write_text("taskly")
            os.symlink(sroot / "real", sroot / "link")
            seen = [rel for rel, _d, _dep, _f in engine.walk(sroot, Options())]
            check("symlink is not descended into",
                  any(r.startswith("link/") for r in seen), False)

        # ------------------------------------------------------------------
        section("Long paths")
        deep = tmp / "deep"
        # Comfortably past MAX_PATH once the temp prefix is counted in.
        rel = "/".join(["taskly-%02d-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" % i for i in range(8)])
        target = deep / rel
        try:
            os.makedirs(win.extended(target), exist_ok=True)
            with open(win.extended(target / "taskly.txt"), "w", encoding="utf-8") as fh:
                fh.write("taskly deep")
            check("created a path over %d chars" % win.MAX_PATH,
                  len(str(target)) > win.MAX_PATH, True)
            engine.apply(str(deep), Options(find="taskly", replace="flowdesk", excludes={}),
                         mode="inplace", backup=False)
            newrel = rel.replace("taskly", "flowdesk")
            out = deep / newrel / "flowdesk.txt"
            check("rebranded a long path", os.path.exists(win.extended(out)), True)
        except OSError as exc:
            check("long path handling", "OSError: %s" % exc, "no error")

        # ------------------------------------------------------------------
        section("A rename that would produce an illegal name")
        if IS_WIN:
            bad = tmp / "bad"
            bad.mkdir()
            (bad / "api.txt").write_text("api")
            # api -> aux would create aux.txt, which Windows refuses.
            engine.apply(str(bad), Options(find="api", replace="aux", excludes={}),
                         mode="inplace", backup=False)
            produced = [p.name for p in bad.iterdir()]
            check("did not crash", len(produced), 1)
            check("landed on a legal name", win.unsafe_name(produced[0]), None)
        else:
            skip("illegal-name rename", "Windows only")

        # ------------------------------------------------------------------
        section("The desktop window (headless)")
        app, root = _tk_app(tmp)
        if app is None:
            skip("window", "no display available")
        else:
            try:
                _pump(root, 2.2)
                check("scan reached the window", app.totals["filesChanged"], 2)
                check("file tree populated", len(app.tree.get_children("")) > 0, True)
                check("a file auto-selected", bool(app.selected), True)
                check("diff rendered",
                      "flowdesk" in app.text.get("1.0", "end").lower(), True)
                check("apply is enabled", app.apply_btn["state"], "normal")

                # Every control must survive being asked for its state, and
                # the mode switch must swap the two output controls.
                app.mode_var.set("inplace")
                app._on_mode()
                _pump(root, 0.2)
                check("in place hides the destination",
                      app.dest_row.winfo_ismapped(), False)
                check("in place shows the backup toggle",
                      app.backup_cb.winfo_ismapped(), True)

                # A bad regex belongs in the rules panel, not in a traceback.
                app.opt["useRegex"].set(True)
                app.find_var.set("Flow(")
                _pump(root, 1.4)
                check("bad regex reported",
                      "invalid regex" in app.chips_lbl.cget("text"), True)
                check("bad regex blocks apply", app.apply_btn["state"], "disabled")

                check("no window uses pywebview", "webview" in sys.modules, False)
            finally:
                root.destroy()

        # ------------------------------------------------------------------
        section("The launch sequence leaves a visible window")
        # The window fades in, and the splash is destroyed mid-flight. A
        # dropped animation frame there once left the app stranded at 15%
        # opacity -- running, responsive and almost invisible. Screenshots
        # cannot catch it (PrintWindow ignores layered alpha), so it is
        # asserted here instead.
        root2 = _launch_sequence(tmp)
        if root2 is None:
            skip("window ends opaque", "no display available")
        else:
            try:
                alpha = float(root2.attributes("-alpha"))
                check("window ends fully opaque", round(alpha, 3), 1.0)
                check("window is mapped", bool(root2.winfo_ismapped()), True)
            finally:
                root2.destroy()

        # ------------------------------------------------------------------
        section("Console helpers")
        check("ANSI decision is a bool", isinstance(win.enable_ansi(), bool), True)
        check("ASCII stream refuses a tick",
              win.encodable("✓", _FakeStream("ascii")), False)
        check("UTF-8 stream accepts a tick",
              win.encodable("✓", _FakeStream("utf-8")), True)
        check("cp1252 stream refuses an arrow",
              win.encodable("→", _FakeStream("cp1252")), False)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n%d passed, %d failed, %d skipped" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print("\nfailures:")
        for name, got, want in FAIL:
            print("  %s\n    got  %r\n    want %r" % (name, got, want))
    return 1 if FAIL else 0


class _FakeStream:
    """Just enough of a stream for win.encodable() to interrogate."""

    def __init__(self, encoding):
        self.encoding = encoding


def _launch_sequence(tmp):
    """Run main()'s splash -> reveal -> fade path and settle.

    Mirrors the real startup rather than constructing the window directly:
    the bug this guards against lived in the hand-off between the two.
    """
    proj = tmp / "launch"
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "taskly.txt").write_text("taskly\n", encoding="utf-8")
    try:
        import tkinter as tk
        from rebrandx import anim, splash, theme
        from rebrandx.app_tk import RebrandX, _size_window
        root = tk.Tk()
    except Exception:
        return None

    theme.init_scaling(root)
    root.withdraw()
    launch = splash.Splash(root).show()
    app = RebrandX(root, str(proj))
    root.update_idletasks()
    _size_window(root)

    def reveal():
        root.deiconify()
        anim.fade_in(root, 120)

    root.after(60, lambda: launch.close(reveal))
    _pump(root, 2.0)          # comfortably past the fade and its failsafe
    return root


def _pump(root, seconds: float) -> None:
    """Run the Tk event loop for a while without entering mainloop()."""
    import time
    end_at = time.time() + seconds
    while time.time() < end_at:
        root.update()
        root.update_idletasks()
        time.sleep(0.01)


def _tk_app(tmp):
    """Build the real window over a small fixture, or (None, None) headless.

    The window is the product on Windows, so it is worth constructing for
    real rather than mocking -- this catches a pane that fails to build, a
    scan that never comes back and a control wired to nothing.
    """
    proj = tmp / "window"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "taskly.js").write_text("class Taskly {}\n", encoding="utf-8")
    (proj / "README.md").write_text("# Taskly\n", encoding="utf-8")
    try:
        import tkinter as tk
        from rebrandx.app_tk import RebrandX
        root = tk.Tk()
        root.geometry("1180x760")
    except Exception:
        return None, None
    app = RebrandX(root, str(proj))
    app.find_var.set("Taskly")
    app.repl_var.set("Flowdesk")
    return app, root


def _expect_apply_error(root: str):
    """(got, want) for 'engine.apply refuses this root'."""
    try:
        engine.apply(root, Options(find="a", replace="b"), mode="inplace")
        return "no error", "ApplyError"
    except engine.ApplyError:
        return "ApplyError", "ApplyError"
    except OSError as exc:
        return "OSError: %s" % exc, "ApplyError"


if __name__ == "__main__":
    sys.exit(main())
