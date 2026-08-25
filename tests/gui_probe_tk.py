#!/usr/bin/env python3
"""Drives the real RebrandX window and reports what it actually shows.

    python tests/gui_probe_tk.py [FOLDER]

Builds the window, types a rebrand into it, waits for the background scan
and then reads the widgets back -- so this catches a pane that renders
nothing, a scan that never returns, and a button left disabled when it
should not be.

Needs a display. It never writes to the folder it is given: the probe stops
short of pressing Apply, and uses a throwaway fixture unless told otherwise.

    --shot FILE   also save a PNG of the window (Windows only)
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tkinter as tk                                        # noqa: E402
from rebrandx import theme                                  # noqa: E402
from rebrandx.app_tk import (RebrandX, _set_icon,           # noqa: E402
                             _windows_app_identity, _windows_titlebar)

TMP = Path(tempfile.mkdtemp(prefix="rbx-tkprobe-"))
OUT: list[str] = []


def fixture() -> str:
    r = TMP / "taskly"
    (r / "src" / "taskly-core").mkdir(parents=True)
    (r / "docs").mkdir()
    (r / ".github" / "workflows").mkdir(parents=True)
    (r / "README.md").write_text(
        "# Taskly\nSource: github.com/alexdev/taskly\nRun taskly now.\nTASKLY rocks.\n",
        encoding="utf-8")
    (r / "package.json").write_text('{"name": "taskly"}\n', encoding="utf-8")
    (r / "src" / "index.js").write_text(
        "const taskly = require('./taskly-core');\n", encoding="utf-8")
    (r / "src" / "taskly-core" / "taskly.js").write_text(
        "class TasklyCore {}\n", encoding="utf-8")
    (r / "docs" / "guide.md").write_text("taskly docs\n", encoding="utf-8")
    (r / "LICENSE").write_text("MIT\n", encoding="utf-8")
    (r / ".github" / "workflows" / "build.yml").write_text(
        "name: taskly\n", encoding="utf-8")
    return str(r)


def pump(root, seconds: float) -> None:
    """Run the Tk event loop for a while without blocking in mainloop()."""
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        root.update_idletasks()
        time.sleep(0.01)


def shown(widget) -> str:
    try:
        return "SHOWN" if widget.winfo_ismapped() and widget.winfo_width() > 1 \
            else "hidden"
    except tk.TclError:
        return "gone"


def main() -> int:
    argv = [a for a in sys.argv[1:]]
    shot = None
    if "--shot" in argv:
        i = argv.index("--shot")
        shot = argv[i + 1]
        del argv[i:i + 2]
    folder = argv[0] if argv else fixture()

    # Same first move as main(): without it the process is DPI-unaware and
    # Windows stretches the window, so the screenshot is not what a user
    # would actually see.
    _windows_app_identity()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print("no display: %s" % exc)
        return 0

    theme.init_scaling(root)
    root.title("RebrandX")
    # Device-independent, so the probe frames the window the same way on a
    # 1x screen and a 1.5x one.
    root.geometry("%dx%d" % (theme.px(1240), theme.px(800)))
    _set_icon(root)
    app = RebrandX(root, folder)
    _windows_titlebar(root)
    pump(root, 0.6)

    OUT.append("title            : %r" % root.title())
    OUT.append("source           : %s" % (app.source or "(none)"))
    OUT.append("panes            : rules=%s files=%s diff=%s" % (
        shown(app.find_entry), shown(app.tree), shown(app.text)))
    OUT.append("apply at rest    : %s" % app.apply_btn["state"])

    # Type a rebrand, exactly as a person would.
    app.find_var.set("Taskly")
    app.repl_var.set("Flowdesk")
    pump(root, 2.5)

    OUT.append("chips            : %r" % app.chips_lbl.cget("text").replace("\n", " | "))
    OUT.append("totals           : %s" % app.totals)
    rows = app.tree.get_children("")
    OUT.append("tree roots       : %d" % len(rows))
    OUT.append("tree labels      : %s" % [app.tree.item(r, "text") for r in rows][:8])

    renamed = []
    def walk(node):
        for child in app.tree.get_children(node):
            new = app.tree.set(child, "new")
            if new:
                renamed.append("%s -> %s" % (app.tree.item(child, "text"), new))
            walk(child)
    walk("")
    OUT.append("renames shown    : %s" % renamed[:6])

    OUT.append("selected file    : %s" % app.selected)
    body = app.text.get("1.0", "end").strip().splitlines()
    OUT.append("diff header      : %r / %r" % (app.diff_path.cget("text"),
                                               app.diff_stat.cget("text")))
    OUT.append("diff rename      : %r" % app.diff_rename.cget("text"))
    OUT.append("diff first lines : %s" % [ln.rstrip() for ln in body[:4]])
    OUT.append("diff has -/+     : %s" % (
        any(ln.strip().startswith("-") for ln in body)
        and any(ln.strip().startswith("+") for ln in body)))

    OUT.append("dest suggested   : %r" % app.dest_var.get())
    OUT.append("apply now        : %s" % app.apply_btn["state"])
    OUT.append("status files     : %s" % app.stats["filesChanged"][1].cget("text"))
    OUT.append("status repl      : %s" % app.stats["replacements"][1].cget("text"))

    # In-place mode swaps the destination box for the backup toggle.
    app.mode_var.set("inplace")
    app._on_mode()
    pump(root, 0.3)
    OUT.append("inplace: dest=%s backup=%s" % (shown(app.dest_row),
                                               shown(app.backup_cb)))
    app.mode_var.set("copy")
    app._on_mode()
    pump(root, 0.3)
    OUT.append("copy   : dest=%s backup=%s" % (shown(app.dest_row),
                                               shown(app.backup_cb)))

    # Skipping a file must take it out of the totals.
    before = app.totals["filesChanged"]
    first = next(e["path"] for e in app.entries
                 if not e["dir"] and (e["count"] or e["renamed"]))
    app.skipped_files.add(first)
    app.schedule_scan(now=True)
    pump(root, 2.0)
    OUT.append("skip %-16s: %d -> %d files" % (first, before,
                                               app.totals["filesChanged"]))
    app.skipped_files.discard(first)
    app.schedule_scan(now=True)
    pump(root, 1.5)

    # An invalid regex must be reported in the rules panel, not thrown.
    app.opt["useRegex"].set(True)
    app.find_var.set("Taskly(")
    pump(root, 1.5)
    OUT.append("bad regex        : %r" % app.chips_lbl.cget("text")[:60])
    OUT.append("apply blocked    : %s" % app.apply_btn["state"])
    app.opt["useRegex"].set(False)
    app.find_var.set("Taskly")
    pump(root, 1.5)
    OUT.append("recovered        : %s" % app.apply_btn["state"])

    if shot:
        pump(root, 0.4)
        ok = _screenshot(root, shot)
        OUT.append("screenshot       : %s" % (shot if ok else "failed"))

    print("\n".join(OUT))
    root.destroy()
    return 0


def _screenshot(root, path: str) -> bool:
    """Grab the window rectangle off the screen. Windows only, stdlib only."""
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes
        root.update()
        root.lift()
        root.focus_force()
        time.sleep(0.4)
        root.update()

        hwnd = int(root.winfo_id())
        # winfo_id is the Tk child; the frame Windows draws is its ancestor.
        top = ctypes.windll.user32.GetAncestor(hwnd, 2)      # GA_ROOT
        rect = wintypes.RECT()
        ctypes.windll.user32.GetWindowRect(top, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top

        gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
        src = user32.GetWindowDC(top)
        dst = gdi32.CreateCompatibleDC(src)
        bmp = gdi32.CreateCompatibleBitmap(src, w, h)
        gdi32.SelectObject(dst, bmp)
        # PW_RENDERFULLCONTENT, so the frame is included.
        if not user32.PrintWindow(top, dst, 2):
            gdi32.BitBlt(dst, 0, 0, w, h, src, 0, 0, 0x00CC0020)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

        hdr = BITMAPINFOHEADER()
        hdr.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        hdr.biWidth, hdr.biHeight = w, -h        # negative = top-down
        hdr.biPlanes, hdr.biBitCount = 1, 32
        buf = ctypes.create_string_buffer(w * h * 4)
        gdi32.GetDIBits(dst, bmp, 0, h, buf, ctypes.byref(hdr), 0)

        _write_png(path, w, h, bytes(buf))

        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(dst)
        user32.ReleaseDC(top, src)
        return True
    except Exception as exc:
        print("screenshot failed: %s" % exc, file=sys.stderr)
        return False


def _write_png(path: str, w: int, h: int, bgra: bytes) -> None:
    """Minimal PNG writer, so the probe needs no imaging library."""
    import struct
    import zlib
    rows = bytearray()
    for y in range(h):
        rows.append(0)                                  # filter: none
        row = bgra[y * w * 4:(y + 1) * w * 4]
        # BGRA -> RGB
        rows.extend(b"".join(row[x * 4 + 2:x * 4 + 3] + row[x * 4 + 1:x * 4 + 2]
                             + row[x * 4:x * 4 + 1] for x in range(w)))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xffffffff))

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)))
        fh.write(chunk(b"IDAT", zlib.compress(bytes(rows), 6)))
        fh.write(chunk(b"IEND", b""))


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
