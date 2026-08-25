#!/usr/bin/env python3
"""RebrandX desktop app -- a native window, built on tkinter.

No web view, no browser engine, no network, no third-party packages: tkinter
ships with Python on Windows, so this runs on a stock install and offline.

The engine, the rules and every behaviour are shared with the CLI. Only the
window is here.

    python -m rebrandx.app_tk [FOLDER]

Layout follows the documented three-column workflow:

    Rules            Files                  Diff
    what changes     what it affects        what it actually does
"""

from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import tkinter as tk                                        # noqa: E402
from tkinter import ttk, filedialog, messagebox             # noqa: E402

from rebrandx import anim, engine, splash, theme, widgets, win  # noqa: E402
from rebrandx.core import Core, tilde                       # noqa: E402
from rebrandx.theme import px as P                          # noqa: E402
from rebrandx.widgets import Bar, Button, Card, Check, Chip, Field, Segmented  # noqa: E402

APP_ID = "dev.rebrandx.RebrandX"


def _assets() -> Path:
    """Where share/ lives, running from source or from a frozen build.

    PyInstaller unpacks a one-file build into a temp directory and points
    sys._MEIPASS at it, so the path next to __file__ is wrong there.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "share"
    return Path(__file__).resolve().parent.parent / "share"


ICON = _assets() / "rebrandx.ico"
ICON_PNG = _assets() / "rebrandx.png"

SCAN_DEBOUNCE_MS = 250
MAX_ROWS = 4000
MAX_DIFF_ROWS = 4000


# --------------------------------------------------------------------------
# Windows integration
# --------------------------------------------------------------------------

def _windows_app_identity() -> None:
    """Claim a taskbar identity, and become genuinely DPI-aware.

    The DPI call is the one that matters for how the app *looks*. Its
    argument is a DPI_AWARENESS_CONTEXT, which is a pointer-sized handle --
    passing the pseudo-handle -4 as a plain Python int makes ctypes marshal
    a 32-bit value, the call fails, and the process silently stays
    DPI-unaware. Windows then renders the window at 96 DPI and bitmap-
    stretches it to the real display, which is exactly as blurry as it
    sounds. Every call below is therefore typed, and its result checked.
    """
    if os.name != "nt":
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

    user32 = ctypes.windll.user32
    # Per-monitor v2 (Windows 10 1703+): the window is re-rendered, not
    # scaled, when it moves to a monitor with a different DPI.
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    # Windows 8.1: 2 == PROCESS_PER_MONITOR_DPI_AWARE.
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


def _windows_titlebar(root) -> None:
    """Paint the title bar in the app's own colours.

    Windows 11 (build 22000+) lets an app set its caption colours; before
    that the call fails harmlessly and the system accent is used, which is
    fine. Doing this stops a light porcelain window from being topped by
    whatever accent colour the user happens to have chosen.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetAncestor(int(root.winfo_id()), 2)
        dwm = ctypes.windll.dwmapi

        def rgb(hex_colour: str) -> int:
            r = int(hex_colour[1:3], 16)
            g = int(hex_colour[3:5], 16)
            b = int(hex_colour[5:7], 16)
            return (b << 16) | (g << 8) | r        # COLORREF is 0x00BBGGRR

        # Match the caption to the app's own header bar, so the title bar
        # reads as the top of the window chrome rather than a strip of
        # whatever accent colour the machine happens to be set to.
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_CAPTION_COLOR = 35
        DWMWA_TEXT_COLOR = 36
        DWMWA_BORDER_COLOR = 34
        for attr, value in ((DWMWA_USE_IMMERSIVE_DARK_MODE, 1),
                            (DWMWA_CAPTION_COLOR, rgb(theme.INK)),
                            (DWMWA_TEXT_COLOR, rgb(theme.INK_TEXT)),
                            (DWMWA_BORDER_COLOR, rgb(theme.INK))):
            dwm.DwmSetWindowAttribute(
                hwnd, ctypes.c_int(attr),
                ctypes.byref(ctypes.c_int(value)), ctypes.sizeof(ctypes.c_int))
    except Exception:
        pass


# --------------------------------------------------------------------------
# background work
# --------------------------------------------------------------------------

class Worker:
    """Runs engine calls off the UI thread and delivers results back on it.

    Tk is not thread-safe: touching a widget from anywhere but the main
    thread corrupts the interpreter, usually much later and somewhere else.
    So workers only ever put a callable on a queue, and the Tk thread drains
    that queue on a timer.
    """

    def __init__(self, root):
        self.root = root
        self.q: queue.Queue = queue.Queue()
        self._pump()

    def _pump(self):
        try:
            while True:
                fn = self.q.get_nowait()
                try:
                    fn()
                except Exception:
                    traceback.print_exc()
        except queue.Empty:
            pass
        self.root.after(40, self._pump)

    def post(self, fn):
        self.q.put(fn)

    def run(self, work, on_done, on_error=None):
        """Call `work()` on a thread, then `on_done(result)` on the UI thread."""
        def body():
            try:
                result = work()
            except Exception as exc:
                traceback.print_exc()
                if on_error:
                    self.post(lambda: on_error(exc))
                return
            self.post(lambda: on_done(result))

        threading.Thread(target=body, daemon=True).start()


# --------------------------------------------------------------------------
# the window
# --------------------------------------------------------------------------

class RebrandX(tk.Frame):

    def __init__(self, root: tk.Tk, folder: str | None = None):
        super().__init__(root, background=theme.BG)
        self.root = root
        self.core = Core()
        self.worker = Worker(root)

        self.ui, self.ui_bold, self.ui_small, self.mono = theme.apply_theme(root)
        self.ui_eyebrow = theme.eyebrow_font()

        # -- state ---------------------------------------------------------
        self.source = ""
        self.entries: list[dict] = []
        self.totals = {"filesChanged": 0, "replacements": 0, "renames": 0,
                       "removed": 0, "dropped": 0}
        self.chips: list[str] = []
        self.selected: str | None = None
        self.diff: dict | None = None
        self.skipped_files: set[str] = set()
        self.skipped_lines: set[str] = set()
        self.scan_error: str | None = None
        self.regex_error: str | None = None
        self.truncated = False
        self.applied = False
        self.dest_touched = False
        self.scan_token = 0
        self.diff_token = 0
        self.busy = False
        self._scan_job = None
        self._row_of: dict[str, str] = {}
        self.scanning = False
        self._pulse_job = None
        self._pulse_t = 0.0

        self._build()
        self._bind_keys()

        if folder:
            self.set_source(folder)
        else:
            self.render()

    # ------------------------------------------------------------------ UI
    def _build(self):
        self.pack(fill="both", expand=True)
        self._build_header()

        body = tk.Frame(self, background=theme.BG)
        body.pack(fill="both", expand=True, padx=P(10), pady=(P(8), P(0)))

        panes = ttk.PanedWindow(body, orient="horizontal")
        panes.pack(fill="both", expand=True)
        self.panes = panes

        panes.add(self._build_rules(panes), weight=0)
        panes.add(self._build_files(panes), weight=2)
        panes.add(self._build_diff(panes), weight=3)

        self._build_status()

    # -- section label: small caps, letter-spaced by hand -----------------
    def _eyebrow(self, parent, text, bg=None):
        return tk.Label(parent, text=theme.spaced(text),
                        background=bg or theme.SURFACE,
                        foreground=theme.TEXT_SUBTLE, font=self.ui_eyebrow,
                        anchor="w")

    def _card(self, parent, title):
        """A raised card with an eyebrow title.

        Returns (holder, body, head, label) -- the holder goes in the paned
        window, everything else is content.
        """
        holder = tk.Frame(parent, background=theme.BG)
        card = Card(holder, radius=12)
        card.pack(fill="both", expand=True)
        head = tk.Frame(card.body, background=theme.SURFACE)
        head.pack(fill="x", padx=P(18), pady=(P(15), P(0)))
        lbl = self._eyebrow(head, title)
        lbl.pack(side="left")
        return holder, card.body, head, lbl

    def _build_header(self):
        rail = widgets.Rail(self, height=72, edge="bottom")
        rail.pack(fill="x", side="top")
        bar = tk.Frame(rail, background=theme.CHROME)
        bar.place(relx=0, rely=0, relwidth=1, relheight=1)
        C = theme.CHROME

        left = tk.Frame(bar, background=C)
        left.pack(side="left", padx=(P(20), P(0)))
        widgets.Mark(left, size=34, bg=C).pack(side="left")
        wordmark = tk.Frame(left, background=C)
        wordmark.pack(side="left", padx=(P(13), P(0)))
        tk.Label(wordmark, text="RebrandX", background=C,
                 foreground=theme.TEXT_STRONG,
                 font=theme.display_font()).pack(anchor="w")
        tk.Label(wordmark, text=theme.spaced("project renamer"),
                 background=C, foreground=theme.TEXT_FAINT,
                 font=self.ui_eyebrow).pack(anchor="w", pady=(P(1), P(0)))

        right = tk.Frame(bar, background=C)
        right.pack(side="right", padx=(P(0), P(20)))
        self.revert_btn = Button(right, text="Revert", kind="danger",
                                 command=self.do_revert, font=self.ui,
                                 height=38, bg=C)
        self.revert_btn.configure(state="disabled")
        self.revert_btn.pack(side="right", padx=(P(10), P(0)))
        self.open_btn = Button(right, text="Reveal", command=self.open_folder,
                               kind="ghost", font=self.ui, height=38, bg=C)
        self.open_btn.configure(state="disabled")
        self.open_btn.pack(side="right", padx=(P(10), P(0)))
        self.recents_btn = Button(right, text="Recent  ⌄",
                                  command=self._show_recents, kind="ghost",
                                  font=self.ui, height=38, bg=C)
        self.recents_btn.pack(side="right", padx=(P(10), P(0)))

        self.folder_chip = Chip(bar, text="Choose a folder to rebrand…",
                                icon="◈", command=self.pick_folder,
                                font=self.ui, mono=self.mono, bg=C,
                                hint="Ctrl+O", height=40)
        self.folder_chip.pack(side="left", fill="x", expand=True,
                              padx=(P(26), P(18)), pady=P(16))

    # -- rules ------------------------------------------------------------
    def _build_rules(self, parent):
        holder, outer, _head, _lbl = self._card(parent, "RULES")
        holder.configure(width=P(346))
        holder.pack_propagate(False)

        # Even trimmed down this is the tallest column in the window, so it
        # scrolls rather than losing its last controls on a short screen.
        scroller = widgets.ScrollFrame(outer)
        scroller.pack(fill="both", expand=True, pady=(0, P(8)))
        self.rules_scroller = scroller
        body = scroller.body

        S = theme.SURFACE

        def label(text, style="muted", parent=None, **kw):
            """A field label, a hint, or a letter-spaced section eyebrow."""
            host = parent if parent is not None else body
            if style == "head":
                return tk.Label(host, text=theme.spaced(text), background=S,
                                foreground=theme.TEXT_SUBTLE,
                                font=self.ui_eyebrow, anchor="w", **kw)
            return tk.Label(host, text=text, background=S,
                            foreground={"muted": theme.TEXT_MUTED,
                                        "subtle": theme.TEXT_SUBTLE}[style],
                            font=self.ui_small if style == "subtle" else self.ui,
                            anchor="w", **kw)

        self.opt = {}

        def toggle(host, key, text, hint, default):
            v = tk.BooleanVar(value=default)
            self.opt[key] = v
            Check(host, text=text, hint=hint, variable=v, bg=S,
                  command=self._on_rule_typed, font=self.ui,
                  hint_font=self.ui_small).pack(fill="x", padx=P(18))

        # -- the two fields the whole app is about ------------------------
        label("FIND", "head").pack(fill="x", padx=P(18), pady=(P(14), P(5)))
        self.find_var = tk.StringVar()
        self.find_field = Field(body, textvariable=self.find_var,
                                font=self.mono, fg=theme.DANGER)
        self.find_field.pack(fill="x", padx=P(18))
        self.find_entry = self.find_field.entry

        label("REPLACE WITH", "head").pack(fill="x", padx=P(18),
                                           pady=(P(12), P(5)))
        self.repl_var = tk.StringVar()
        self.repl_field = Field(body, textvariable=self.repl_var,
                                font=self.mono, fg=theme.BRASS_TEXT)
        self.repl_field.pack(fill="x", padx=P(18))
        self.repl_entry = self.repl_field.entry

        for var in (self.find_var, self.repl_var):
            var.trace_add("write", lambda *_: self._on_rule_typed())

        self.chips_lbl = tk.Label(body, text="", background=S,
                                  foreground=theme.BRASS_TEXT, font=self.mono,
                                  justify="left", anchor="w",
                                  wraplength=P(270))
        self.chips_lbl.pack(fill="x", padx=P(18), pady=(P(10), P(4)))

        toggle(body, "matchVariants", "Case variants",
               "Name, NAME and name too", True)
        toggle(body, "caseSensitive", "Case sensitive",
               "Off matches any casing", True)
        toggle(body, "renameFiles", "Rename files and folders", "", True)
        toggle(body, "replaceContents", "Replace file contents", "", True)

        self._rule(body).pack(fill="x", padx=P(18), pady=(P(12), P(12)))

        # -- output -------------------------------------------------------
        label("OUTPUT", "head").pack(fill="x", padx=P(18), pady=(0, P(7)))
        self.mode_var = tk.StringVar(value="copy")
        Segmented(body, [("copy", "Rebranded copy"), ("inplace", "In place")],
                  self.mode_var, command=self._on_mode, bg=S,
                  font=self.ui).pack(fill="x", padx=P(18))

        # A fixed container keeps ordering stable: pack_forget() then
        # pack() would re-add the widget at the end of the column.
        self.mode_extra = tk.Frame(body, background=S)
        self.mode_extra.pack(fill="x", padx=P(18), pady=(P(10), 0))

        self.dest_row = tk.Frame(self.mode_extra, background=S)
        self.dest_var = tk.StringVar()
        self.dest_field = Field(self.dest_row, textvariable=self.dest_var,
                                font=self.mono)
        self.dest_field.pack(side="left", fill="x", expand=True)
        self.dest_entry = self.dest_field.entry
        self.dest_var.trace_add("write", lambda *_: self._on_dest_typed())
        Button(self.dest_row, text="\u2026", command=self.pick_dest,
               kind="ghost", width=P(40), height=38, font=self.ui,
               bg=S).pack(side="left", padx=(P(6), 0))

        self.backup_var = tk.BooleanVar(value=bool(
            self.core.cfg["settings"].get("backup", True)))
        self.backup_cb = Check(self.mode_extra,
                               text="Keep a .rebrandx-backup copy",
                               variable=self.backup_var, bg=S, font=self.ui,
                               command=self._save_settings)

        self._rule(body).pack(fill="x", padx=P(18), pady=(P(12), P(10)))

        # -- advanced ------------------------------------------------------
        # Everything below is used occasionally. Folding it away is what
        # keeps the column short enough to read without scrolling, and
        # keeps the two fields that matter at the top.
        self.adv_open = tk.BooleanVar(value=False)
        self.adv_btn = Button(body, text="Advanced  \u2304", kind="quiet",
                              font=self.ui, height=30, bg=S,
                              command=self._toggle_advanced)
        self.adv_btn.pack(fill="x", padx=P(14))

        self.adv = tk.Frame(body, background=S)

        toggle(self.adv, "useRegex", "Regular expression",
               "$1 groups in the replacement", False)
        toggle(self.adv, "stripMeta", "Drop old repo links",
               "Lines pointing at the old remote", False)
        toggle(self.adv, "stripProjectFiles", "Remove old project files",
               "LICENSE, CHANGELOG, .github/ \u2026", False)

        self.dry_var = tk.BooleanVar(value=False)
        Check(self.adv, text="Dry run (write nothing)", variable=self.dry_var,
              bg=S, font=self.ui,
              command=self.render_actions).pack(fill="x", padx=P(18))

        label("IGNORED", "head", parent=self.adv).pack(
            fill="x", padx=P(18), pady=(P(10), P(6)))
        self.ignore_var = tk.StringVar(value=".git/, node_modules/, *.lock")
        Field(self.adv, textvariable=self.ignore_var, font=self.mono,
              height=36).pack(fill="x", padx=P(18))
        self.ignore_var.trace_add("write", lambda *_: self._on_rule_typed())
        label("Comma-separated globs", "subtle", parent=self.adv).pack(
            fill="x", padx=P(18), pady=(P(6), P(14)))

        # The wheel should work anywhere over the column, not only in the
        # gaps between controls.
        for host in (body, self.adv):
            for child in host.winfo_children():
                scroller.bind_wheel(child)
        return holder

    def _toggle_advanced(self):
        """Fold the occasional options away, or bring them back."""
        opening = not self.adv_open.get()
        self.adv_open.set(opening)
        self.adv_btn.configure(
            text="Advanced  \u2303" if opening else "Advanced  \u2304")
        if opening:
            self.adv.pack(fill="x", pady=(P(4), 0))
        else:
            self.adv.pack_forget()
        self.rules_scroller._sync()

    def _rule(self, parent):
        return tk.Frame(parent, background=theme.BORDER, height=1)

    # -- files ------------------------------------------------------------
    def _build_files(self, parent):
        holder, body, head, self.files_lbl = self._card(parent, "FILES")
        S = theme.SURFACE
        self.skip_hint = tk.Label(head, text="", background=S,
                                  foreground=theme.TEXT_SUBTLE,
                                  font=self.ui_small)
        self.skip_hint.pack(side="right")

        wrap = tk.Frame(body, background=S)
        wrap.pack(fill="both", expand=True, padx=(P(12), P(8)), pady=(P(12), P(14)))

        self.tree = ttk.Treeview(wrap, columns=("new", "n"), show="tree",
                                 selectmode="browse")
        # The "becomes" column carries the rename, which is the point of
        # the pane -- give it room and let the name column give way first.
        self.tree.column("#0", width=P(180), minwidth=P(110), stretch=True)
        self.tree.column("new", width=P(175), minwidth=P(100), stretch=True)
        self.tree.column("n", width=P(44), minwidth=P(44), stretch=False, anchor="e")

        vs = widgets.Scrollbar(wrap, command=self.tree.yview, bg=S)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.files_scroll = vs

        self.tree.tag_configure("dir", foreground=theme.TEXT_MUTED)
        self.tree.tag_configure("excluded", foreground=theme.TEXT_FAINT)
        self.tree.tag_configure("skipped", foreground=theme.TEXT_FAINT)
        self.tree.tag_configure("drop", foreground=theme.DANGER)
        self.tree.tag_configure("renamed", foreground=theme.BRASS_TEXT)
        self.tree.tag_configure("warn", foreground=theme.DANGER)
        self.tree.tag_configure("plain", foreground=theme.TEXT)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<space>", lambda e: (self.toggle_skip(), "break")[1])
        self.tree.bind("<Double-1>", lambda e: (self.toggle_skip(), "break")[1])
        self.tree.bind("<Button-3>", self._file_menu)

        self.file_menu = tk.Menu(self, tearoff=0, font=self.ui,
                                 background=theme.SURFACE_2,
                                 foreground=theme.TEXT,
                                 activebackground=theme.SURFACE_4,
                                 activeforeground=theme.TEXT_STRONG,
                                 borderwidth=0, relief="flat")
        self.file_menu.add_command(label="Skip this file",
                                   command=self.toggle_skip)
        return holder

    # -- diff -------------------------------------------------------------
    def _build_diff(self, parent):
        holder, body, head, head_lbl = self._card(parent, "DIFF")
        head_lbl.pack_forget()
        S = theme.SURFACE
        self.diff_path = tk.Label(head, text=theme.spaced("DIFF"), background=S,
                                  foreground=theme.TEXT_SUBTLE,
                                  font=self.ui_eyebrow, anchor="w")
        self.diff_path.pack(side="left")
        self.diff_stat = tk.Label(head, text="", background=S,
                                  foreground=theme.TEXT_SUBTLE,
                                  font=self.ui_small)
        self.diff_stat.pack(side="right")

        self.diff_rename = tk.Label(body, text="", background=S,
                                    foreground=theme.BRASS_TEXT, font=self.mono,
                                    anchor="w")
        self.diff_rename.pack(fill="x", padx=P(18), pady=(P(6), P(0)))
        self.diff_warn = tk.Label(body, text="", background=S,
                                  foreground=theme.DANGER, font=self.ui_small,
                                  anchor="w", justify="left", wraplength=P(520))
        self.diff_warn.pack(fill="x", padx=P(18))

        wrap = tk.Frame(body, background=S)
        wrap.pack(fill="both", expand=True, padx=(P(12), P(8)), pady=(P(10), P(14)))

        self.text = tk.Text(wrap, wrap="none", font=self.mono, relief="flat",
                            background=S, foreground=theme.TEXT,
                            insertwidth=0, padx=P(0), pady=P(6),
                            spacing1=2, spacing3=2,
                            highlightthickness=0, cursor="arrow", borderwidth=0)
        vs = widgets.Scrollbar(wrap, command=self.text.yview, bg=S)
        self.text.configure(yscrollcommand=vs.set)
        self.text.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.diff_scroll = vs

        # A coloured rail down the left of a changed line, rather than a
        # wash across the whole row: it marks the change without drowning
        # the code, which is the thing being read.
        self.text.tag_configure("rail_old", background=theme.DANGER_DIM)
        self.text.tag_configure("rail_new", background=theme.ADD_DIM)
        self.text.tag_configure("rail_off", background=theme.SURFACE_3)
        self.text.tag_configure("old", background=theme.DANGER_GHOST,
                                foreground=theme.DANGER)
        self.text.tag_configure("new", background=theme.ADD_GHOST,
                                foreground=theme.ADD)
        self.text.tag_configure("same", foreground=theme.TEXT_SUBTLE)
        self.text.tag_configure("gutter", foreground=theme.TEXT_FAINT)
        self.text.tag_configure("skipped", foreground=theme.TEXT_FAINT,
                                background=theme.SURFACE_2, overstrike=True)
        self.text.tag_configure("note", foreground=theme.TEXT_SUBTLE)
        self.text.tag_configure("empty_title", foreground=theme.TEXT_MUTED,
                                font=theme.display_font(), justify="center")
        self.text.tag_configure("empty_body", foreground=theme.TEXT_FAINT,
                                font=self.ui, justify="center")
        self.text.configure(state="disabled")
        self.text.bind("<Button-1>", self._on_diff_click)
        return holder

    # -- status bar -------------------------------------------------------
    def _build_status(self):
        rail = widgets.Rail(self, height=76, edge="top")
        rail.pack(fill="x", side="bottom")
        bar = tk.Frame(rail, background=theme.CHROME)
        bar.place(relx=0, rely=0, relwidth=1, relheight=1)
        C = theme.CHROME

        stats = tk.Frame(bar, background=C)
        stats.pack(side="left", padx=(P(22), P(0)))

        big = (self.ui_bold[0], self.ui_bold[1] + 8)
        self.stats = {}
        for key, label in [("filesChanged", "files"),
                           ("replacements", "replacements"),
                           ("renames", "renames"),
                           ("removed", "lines removed"),
                           ("dropped", "deleted")]:
            cell = tk.Frame(stats, background=C)
            cell.pack(side="left", padx=(P(0), P(26)))
            # The headline number is the one in brass; the rest are
            # supporting detail and stay in plain type.
            v = tk.Label(cell, text="0", background=C,
                         foreground=(theme.BRASS if key == "filesChanged"
                                     else theme.TEXT),
                         font=big)
            v.pack(anchor="w")
            tk.Label(cell, text=theme.spaced(label), background=C,
                     foreground=theme.TEXT_FAINT,
                     font=self.ui_eyebrow).pack(anchor="w", pady=(P(2), P(0)))
            self.stats[key] = (cell, v)

        self.apply_btn = Button(bar, text="Apply rebrand", kind="cta",
                                command=self.do_apply, font=self.ui_bold,
                                height=44, padx=P(30), radius=13, bg=C)
        self.apply_btn.configure(state="disabled")
        self.apply_btn.pack(side="right", padx=(P(0), P(22)))

        self.progress = Bar(bar, height=5, width=190, bg=C,
                            trough=theme.SURFACE_2, fill=theme.BRASS)
        self.msg = tk.Label(bar, text="", background=C,
                            foreground=theme.TEXT_MUTED, font=self.ui_small,
                            anchor="w")
        self.msg.pack(side="left", fill="x", expand=True, padx=(P(18), P(16)))

    def _bind_keys(self):
        r = self.root
        r.bind("<Control-o>", lambda e: (self.pick_folder(), "break")[1])
        r.bind("<Control-Return>", lambda e: (self.do_apply(), "break")[1])
        r.bind("<Control-q>", lambda e: (self.on_close(), "break")[1])
        r.bind("<F5>", lambda e: (self.schedule_scan(now=True), "break")[1])
        r.bind("<Escape>", lambda e: r.focus_set())

    # -------------------------------------------------------------- inputs
    def _current_opts(self) -> dict:
        ignores = {}
        for part in self.ignore_var.get().split(","):
            part = part.strip()
            if part:
                ignores[part] = True
        return {
            "find": self.find_var.get(),
            "replace": self.repl_var.get(),
            "caseSensitive": self.opt["caseSensitive"].get(),
            "matchVariants": self.opt["matchVariants"].get(),
            "useRegex": self.opt["useRegex"].get(),
            "renameFiles": self.opt["renameFiles"].get(),
            "replaceContents": self.opt["replaceContents"].get(),
            "stripMeta": self.opt["stripMeta"].get(),
            "stripProjectFiles": self.opt["stripProjectFiles"].get(),
            "excludes": ignores,
            "skippedFiles": sorted(self.skipped_files),
            "skippedLines": sorted(self.skipped_lines),
        }

    def _on_rule_typed(self):
        self.applied = False
        self.schedule_scan()
        self._suggest_dest()

    def _on_dest_typed(self):
        self.dest_touched = True
        self.render_actions()

    def _on_mode(self):
        self._render_mode_extra()
        self._suggest_dest()
        self.render_actions()

    def _render_mode_extra(self):
        """Show the destination box or the backup toggle, never both."""
        self.dest_row.pack_forget()
        self.backup_cb.pack_forget()
        if self.mode_var.get() == "copy":
            self.dest_row.pack(fill="x")
        else:
            self.backup_cb.pack(anchor="w")

    def _suggest_dest(self):
        if self.dest_touched or self.mode_var.get() != "copy" or not self.source:
            return
        try:
            self.dest_var.set(self.core.suggest_dest({
                "source": self.source,
                "find": self.find_var.get(),
                "replace": self.repl_var.get(),
                "caseSensitive": self.opt["caseSensitive"].get(),
                "matchVariants": self.opt["matchVariants"].get(),
            }))
        except Exception:
            pass
        finally:
            self.dest_touched = False

    # ------------------------------------------------------------- folders
    def pick_folder(self):
        start = self.source or str(Path.home())
        path = filedialog.askdirectory(title="Choose the folder to rebrand",
                                       initialdir=start, mustexist=True)
        if path:
            self.set_source(os.path.normpath(path))

    def pick_dest(self):
        start = self.dest_var.get() or self.source or str(Path.home())
        start = os.path.expanduser(start)
        if not os.path.isdir(start):
            start = str(Path.home())
        path = filedialog.askdirectory(title="Choose the destination folder",
                                       initialdir=start, mustexist=False)
        if path:
            self.dest_var.set(os.path.normpath(path))
            self.dest_touched = True

    def set_source(self, path: str):
        self.source = path
        self.core.remember(path)
        self.skipped_files.clear()
        self.skipped_lines.clear()
        self.selected = None
        self.diff = None
        self.applied = False
        self.dest_touched = False
        self.folder_chip.set_text(self._short(tilde(path)))
        self.open_btn.configure(state="normal")
        self._suggest_dest()
        self.schedule_scan(now=True)

    def _short(self, p: str, width: int = 52) -> str:
        return p if len(p) <= width else "…" + p[-(width - 1):]

    def _show_recents(self):
        menu = tk.Menu(self, tearoff=0, font=self.ui)
        recents = self.core.cfg.get("recents", [])
        if not recents:
            menu.add_command(label="No recent folders yet", state="disabled")
        for p in recents:
            menu.add_command(label=tilde(p),
                             command=lambda q=p: self.set_source(q))
        try:
            menu.tk_popup(self.recents_btn.winfo_rootx(),
                          self.recents_btn.winfo_rooty()
                          + self.recents_btn.winfo_height())
        finally:
            menu.grab_release()

    def open_folder(self):
        target = self.source
        if self.applied and self.mode_var.get() == "copy":
            target = os.path.expanduser(self.dest_var.get()) or target
        try:
            win.open_folder(target)
        except OSError as exc:
            messagebox.showerror("RebrandX", str(exc), parent=self.root)

    # -------------------------------------------------------------- scanning
    def schedule_scan(self, now: bool = False):
        if self._scan_job:
            self.root.after_cancel(self._scan_job)
        self._scan_job = self.root.after(0 if now else SCAN_DEBOUNCE_MS,
                                         self.run_scan)
        self.render_actions()

    def run_scan(self):
        self._scan_job = None
        if not self.source:
            self.entries = []
            self.totals = dict.fromkeys(self.totals, 0)
            self.render()
            return
        self.scan_token += 1
        token = self.scan_token
        params = {"source": self.source, "opts": self._current_opts()}
        self.msg.configure(text="Scanning…")
        self.scanning = True
        self._start_pulse()

        def done(res):
            if token != self.scan_token:
                return
            self.scanning = False
            self._stop_pulse()
            self.entries = res["entries"]
            self.totals = res["totals"]
            self.chips = res["chips"]
            self.scan_error = res["error"]
            self.regex_error = res["regexError"]
            self.truncated = res["truncated"]
            self.msg.configure(text="")
            if self.selected and not any(
                    e["path"] == self.selected and not e["dir"] and not e["excluded"]
                    for e in self.entries):
                self.selected = None
                self.diff = None
            if not self.selected:
                self._auto_select()
            self.render()
            if self.selected:
                self.load_diff(self.selected)

        def failed(exc):
            if token != self.scan_token:
                return
            self.scanning = False
            self._stop_pulse()
            self.scan_error = str(exc)
            self.msg.configure(text="")
            self.render()

        self.worker.run(lambda: self.core.scan(params), done, failed)

    def _auto_select(self):
        for e in self.entries:
            if not e["dir"] and not e["excluded"] and (
                    e["count"] or e["removed"] or e["renamed"]):
                self.selected = e["path"]
                self.diff = None
                return

    def load_diff(self, path: str):
        self.diff_token += 1
        token = self.diff_token
        params = {"source": self.source, "path": path,
                  "opts": self._current_opts()}

        def done(d):
            if token == self.diff_token:
                self.diff = d
                self.render_diff()

        self.worker.run(lambda: self.core.diff(params), done, lambda e: None)

    # ------------------------------------------------------------ rendering
    def render(self):
        self.render_rules()
        self.render_files()
        self.render_diff()
        self.render_status()
        self.render_actions()

    def render_rules(self):
        if self.regex_error:
            self.chips_lbl.configure(text="invalid regex: %s" % self.regex_error,
                                     foreground=theme.DANGER)
        else:
            self.chips_lbl.configure(text="\n".join(self.chips[:4]),
                                     foreground=theme.BRASS_TEXT)
        self._render_mode_extra()

    def render_files(self):
        self.tree.delete(*self.tree.get_children())
        self._row_of.clear()

        if self.scan_error:
            self.tree.insert("", "end", text=self.scan_error, tags=("drop",))
            self.files_lbl.configure(text="FILES")
            return

        shown = self.entries[:MAX_ROWS]
        for e in shown:
            path = e["path"]
            parent_path = path.rsplit("/", 1)[0] if "/" in path else ""
            parent = self._row_of.get(parent_path, "")
            name = path.rsplit("/", 1)[-1]

            tags = []
            new_name = ""
            if e["dir"]:
                tags.append("dir")
            if e["excluded"]:
                tags.append("excluded")
            if e.get("drop"):
                tags.append("drop")
                new_name = "delete"
            elif e["renamed"]:
                tags.append("renamed")
                new_name = e["newPath"].rsplit("/", 1)[-1]
            if path in self.skipped_files:
                tags.append("skipped")
                new_name = "skipped"
            if e.get("winWarn"):
                tags.append("warn")
                new_name = (new_name or "") + "  ⚠"

            count = (e["count"] or 0) + (e["removed"] or 0)
            iid = self.tree.insert(
                parent, "end", text=name,
                values=(new_name, str(count) if count else ""),
                open=True, tags=tuple(tags))
            self._row_of[path] = iid

        label = " ".join("FILES")
        if self.totals["filesChanged"]:
            label += "   ·   %d changed" % self.totals["filesChanged"]
        if len(self.entries) > MAX_ROWS:
            label += "   (first %d shown)" % MAX_ROWS
        self.files_lbl.configure(text=label)
        self.skip_hint.configure(
            text="double-click to skip" if self.entries else "")

        if self.selected and self.selected in self._row_of:
            iid = self._row_of[self.selected]
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def render_diff(self):
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")

        d = self.diff
        if not d:
            self._render_diff_empty()
            return

        self.diff_path.configure(text=d["path"], font=self.mono,
                                 foreground=theme.TEXT)
        n = (d["count"] or 0) + (d["removed"] or 0)
        self.diff_stat.configure(
            text=("%d change%s" % (n, "" if n == 1 else "s")) if n
            else "no changes")
        self.diff_rename.configure(
            text=("\u2192  " + d["newPath"]) if d["renamed"] else "")

        entry = next((e for e in self.entries if e["path"] == d["path"]), None)
        warn = entry.get("winWarn") if entry else None
        if warn:
            extra = " \u2014 RebrandX will adjust it" if os.name == "nt" else ""
            self.diff_warn.configure(
                text="\u26a0  the new name %s on Windows%s" % (warn, extra))
        else:
            self.diff_warn.configure(text="")

        if d["binary"]:
            t.insert("end", "\n   Binary file \u2014 contents left alone.\n", "note")
        elif d["tooBig"]:
            t.insert("end", "\n   Too large to scan \u2014 contents left alone.\n",
                     "note")
        elif d["skippedFile"]:
            t.insert("end", "\n   This file is skipped.\n", "note")

        show_nums = bool(self.core.cfg["settings"].get("showLineNumbers", True))
        rows = d["rows"][:MAX_DIFF_ROWS]

        def row_line(num, rail, sign, body, tags):
            """One diff line: gutter, coloured rail, then the text."""
            gutter = ("%5d " % (num + 1)) if show_nums else "  "
            t.insert("end", gutter, ("gutter",) + tags[1:])
            t.insert("end", "  ", (rail,) + tags[1:])
            t.insert("end", " %s %s\n" % (sign, body), tags)

        for row in rows:
            i = row["i"]
            if row["kind"] == "same":
                gutter = ("%5d " % (i + 1)) if show_nums else "  "
                t.insert("end", gutter, "gutter")
                t.insert("end", "  ", "rail_off")
                t.insert("end", "   " + row["text"] + "\n", "same")
                continue
            skipped = ("%s::%d" % (d["path"], i)) in self.skipped_lines
            mark = "line:%d" % i
            old_tag = "skipped" if skipped else "old"
            new_tag = "skipped" if skipped else "new"
            old_rail = "rail_off" if skipped else "rail_old"
            new_rail = "rail_off" if skipped else "rail_new"
            row_line(i, old_rail, "\u2212", row["old"], (old_tag, mark))
            if row["new"] is not None:
                row_line(i, new_rail, "+", row["new"], (new_tag, mark))

        if len(d["rows"]) > MAX_DIFF_ROWS:
            t.insert("end", "\n   \u2026%d more lines not shown\n"
                     % (len(d["rows"]) - MAX_DIFF_ROWS), "note")
        if any(r["kind"] == "pair" for r in rows):
            t.insert("end", "\n   click a changed line to keep it as it is\n",
                     "note")
        t.configure(state="disabled")

    def _render_diff_empty(self):
        """What the diff pane says when there is nothing to show yet.

        An empty pane with a bare label reads as broken; saying which of
        the three states this is reads as guidance.
        """
        self.diff_path.configure(text=theme.spaced("DIFF"),
                                 font=self.ui_eyebrow,
                                 foreground=theme.TEXT_SUBTLE)
        self.diff_stat.configure(text="")
        self.diff_rename.configure(text="")
        self.diff_warn.configure(text="")
        t = self.text
        if not self.source:
            title = "Pick a folder"
            body = ("Choose the project you want to rename.\n"
                    "Nothing is written until you press Apply.")
        elif not self.find_var.get():
            title = "Type a name to replace"
            body = ("RebrandX finds it in file contents,\n"
                    "file names and folder names.")
        else:
            title = "No matches"
            body = "Nothing in this folder contains that name."
        t.insert("end", "\n" * 5)
        t.insert("end", title + "\n\n", "empty_title")
        t.insert("end", body + "\n", "empty_body")
        t.configure(state="disabled")

    def render_status(self):
        for key, (cell, lbl) in self.stats.items():
            lbl.configure(text=str(self.totals.get(key, 0)))
            if key == "dropped" and not self.opt["stripProjectFiles"].get():
                cell.pack_forget()
            else:
                cell.pack(side="left", padx=(P(0), P(16)))
        if self.truncated:
            self.msg.configure(text="⚠ folder too large — tree truncated")

    def render_actions(self):
        ready = bool(self.source and self.find_var.get() and self.repl_var.get()
                     and not self.regex_error and not self.busy)
        if self.mode_var.get() == "copy" and not self.dest_var.get().strip():
            ready = False
        self.apply_btn.configure(
            text="Run dry run" if self.dry_var.get() else "Apply rebrand",
            state="normal" if ready else "disabled")
        self.revert_btn.configure(
            state="normal" if (self.core.last_manifest and not self.busy)
            else "disabled")

    # --------------------------------------------------------------- events
    def _on_tree_select(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        path = next((p for p, iid in self._row_of.items() if iid == sel[0]), None)
        if not path:
            return
        entry = next((e for e in self.entries if e["path"] == path), None)
        if not entry or entry["dir"] or entry["excluded"]:
            return
        self.selected = path
        self.load_diff(path)

    def _file_menu(self, evt):
        iid = self.tree.identify_row(evt.y)
        if not iid:
            return
        self.tree.selection_set(iid)
        path = next((p for p, i in self._row_of.items() if i == iid), None)
        if not path:
            return
        self.file_menu.entryconfigure(
            0, label="Restore this file" if path in self.skipped_files
            else "Skip this file")
        try:
            self.file_menu.tk_popup(evt.x_root, evt.y_root)
        finally:
            self.file_menu.grab_release()

    def toggle_skip(self):
        sel = self.tree.selection()
        if not sel:
            return
        path = next((p for p, iid in self._row_of.items() if iid == sel[0]), None)
        if not path:
            return
        if path in self.skipped_files:
            self.skipped_files.discard(path)
        else:
            self.skipped_files.add(path)
        self.applied = False
        self.schedule_scan(now=True)

    def _on_diff_click(self, evt):
        if not self.diff:
            return
        idx = self.text.index("@%d,%d" % (evt.x, evt.y))
        for tag in self.text.tag_names(idx):
            if tag.startswith("line:"):
                key = "%s::%s" % (self.diff["path"], tag[5:])
                if key in self.skipped_lines:
                    self.skipped_lines.discard(key)
                else:
                    self.skipped_lines.add(key)
                self.applied = False
                self.schedule_scan(now=True)
                return

    def _save_settings(self):
        self.core.set_settings({"backup": self.backup_var.get()})

    # ---------------------------------------------------------------- apply
    def do_apply(self):
        if self.busy or not self.source:
            return
        if self.dry_var.get():
            messagebox.showinfo(
                "RebrandX — dry run",
                "Nothing was written.\n\n"
                "%d files would change\n%d replacements\n%d renames\n"
                "%d lines removed\n%d files deleted"
                % (self.totals["filesChanged"], self.totals["replacements"],
                   self.totals["renames"], self.totals["removed"],
                   self.totals["dropped"]),
                parent=self.root)
            return

        mode = self.mode_var.get()
        dest = self.dest_var.get().strip()
        if mode == "copy":
            where = "copied into\n%s" % dest
        else:
            where = "rewritten in place inside\n%s" % tilde(self.source)
            if self.backup_var.get():
                where += "\n\nA .rebrandx-backup copy is kept."

        if self.core.cfg["settings"].get("confirmBeforeApply", True):
            ok = messagebox.askokcancel(
                "Apply rebrand",
                "%d file%s will be %s"
                % (self.totals["filesChanged"],
                   "" if self.totals["filesChanged"] == 1 else "s", where),
                parent=self.root, icon="warning")
            if not ok:
                return

        params = {"source": self.source, "mode": mode, "dest": dest,
                  "backup": self.backup_var.get(),
                  "copyIgnored": bool(self.core.cfg["settings"].get("copyIgnored")),
                  "opts": self._current_opts()}

        self._set_busy(True, "Applying…")

        def progress(i, total, rel):
            self.worker.post(lambda: self._progress(i, total, rel))

        def done(res):
            self._set_busy(False)
            self.applied = True
            if res["mode"] == "copy":
                self.msg.configure(text="Wrote %d files to %s"
                                        % (res["files"], res["destLabel"]))
            else:
                self.msg.configure(
                    text="Rewrote %d, renamed %d, deleted %d"
                         % (res["files"], res["renames"], res["dropped"]))
            self.open_btn.configure(state="normal")
            self.schedule_scan(now=True)

        def failed(exc):
            self._set_busy(False)
            messagebox.showerror("RebrandX", str(exc), parent=self.root)

        self.worker.run(lambda: self.core.apply(params, progress), done, failed)

    def _progress(self, i, total, rel):
        self.progress.set(i, total or 1)
        self.msg.configure(text=self._short(rel, 60))

    def do_revert(self):
        if self.busy or not self.core.last_manifest:
            return
        if not messagebox.askokcancel(
                "Revert", "Undo the last rebrand?", parent=self.root,
                icon="warning"):
            return
        self._set_busy(True, "Reverting…")

        def done(res):
            self._set_busy(False)
            self.applied = False
            self.msg.configure(text=res["message"])
            self.schedule_scan(now=True)

        def failed(exc):
            self._set_busy(False)
            messagebox.showerror("RebrandX", str(exc), parent=self.root)

        self.worker.run(lambda: self.core.revert({}), done, failed)

    def _set_busy(self, busy: bool, message: str = ""):
        self.busy = busy
        if busy:
            self.msg.configure(text=message)
            self.progress.pack(side="right", padx=(P(0), P(14)))
            self.progress.set(0, 1)
        else:
            self.progress.pack_forget()
        self.render_actions()

    # -- scanning indicator ------------------------------------------------
    def _start_pulse(self):
        """A brass sweep on the headline stat while a scan is running.

        A scan of a large tree takes long enough to look like nothing is
        happening. This says otherwise without claiming to know how far
        along it is -- the walk cannot report progress until it finishes.
        """
        if self._pulse_job is not None:
            return
        self._pulse_t = 0.0
        self._pulse_step()

    def _pulse_step(self):
        if not self.scanning:
            self._stop_pulse()
            return
        self._pulse_t += 0.06
        glow = anim.ease_in_out(abs((self._pulse_t % 2.0) - 1.0))
        try:
            self.stats["filesChanged"][1].configure(
                foreground=anim.lerp_colour(theme.BRASS_DIM, theme.BRASS, glow))
            self._pulse_job = self.root.after(anim.FRAME_MS, self._pulse_step)
        except tk.TclError:
            self._pulse_job = None

    def _stop_pulse(self):
        if self._pulse_job is not None:
            try:
                self.root.after_cancel(self._pulse_job)
            except tk.TclError:
                pass
            self._pulse_job = None
        try:
            self.stats["filesChanged"][1].configure(foreground=theme.BRASS)
        except tk.TclError:
            pass

    # ---------------------------------------------------------------- close
    def on_close(self):
        try:
            # Stored in device-independent units to match how it is read
            # back; saving raw pixels would make the window grow every time
            # it was opened on a higher-DPI screen.
            scale = max(0.1, theme.SCALE)
            self.core.save_window(int(self.root.winfo_width() / scale),
                                  int(self.root.winfo_height() / scale))
        except Exception:
            pass
        self.root.destroy()


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def main(argv=None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    folder = next((str(Path(os.path.expanduser(a)).resolve())
                   for a in argv[1:] if os.path.isdir(os.path.expanduser(a))), None)

    _windows_app_identity()

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        return _no_display(exc)

    # Must run before anything is built: every widget sizes itself from
    # theme.px(), and that needs the display scale first.
    theme.init_scaling(root)
    root.title("RebrandX")
    root.minsize(theme.px(980), theme.px(620))

    # Hide the real window until it is fully built, and put the launch
    # screen up in its place. Building the three panes takes long enough on
    # a cold start to be visible, and a half-drawn window is worse than a
    # deliberate one.
    root.withdraw()
    launch = splash.Splash(root).show()
    splash.close_pyinstaller_splash()

    _set_icon(root)

    app = RebrandX(root, folder)
    root.protocol("WM_DELETE_WINDOW", app.on_close)

    # Size it only once the panes exist. Asking for a geometry before the
    # children are packed does not stick: Tk maps the window at whatever
    # the content ends up requesting, which here is far wider than the
    # window should be, and the layout opens full of dead space.
    root.update_idletasks()
    _size_window(root)

    def reveal():
        """Swap the launch screen for the finished window."""
        root.deiconify()
        _windows_titlebar(root)
        anim.fade_in(root, 200)
        # The find box is where every session starts.
        root.after(60, lambda: app.find_entry.focus_set())

    # The splash is closed on a short timer only so it is never gone before
    # it has finished fading in.
    root.after(240, lambda: launch.close(reveal))

    root.mainloop()
    return 0


def _size_window(root) -> None:
    """Centre the window at its remembered size, in device-independent units.

    Storing the size that way means a window moved between a laptop screen
    and a 4K monitor opens at the right *size* rather than the same number
    of pixels.
    """
    cfg = Core().cfg.get("window", {})
    w = theme.px(int(cfg.get("width", 1240)))
    h = theme.px(int(cfg.get("height", 800)))

    # Never open larger than the screen it is opening on.
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    w = max(theme.px(980), min(w, screen_w - theme.px(40)))
    h = max(theme.px(620), min(h, screen_h - theme.px(90)))

    root.geometry("%dx%d+%d+%d" % (w, h, max(0, (screen_w - w) // 2),
                                   max(0, (screen_h - h) // 3)))


def _set_icon(root) -> None:
    """Give the window its icon, at the sizes this display actually needs."""
    if os.name == "nt" and ICON.exists() and _set_icon_win32(root):
        return
    try:
        if os.name == "nt" and ICON.exists():
            root.iconbitmap(default=str(ICON))
            return
    except Exception:
        pass
    try:
        if ICON_PNG.exists():
            img = tk.PhotoImage(file=str(ICON_PNG))
            root.iconphoto(True, img)
            root._icon_ref = img          # Tk keeps no reference of its own
    except Exception:
        pass


_ICON_HANDLES = []          # keeps the HICONs alive for the process


def _set_icon_win32(root) -> bool:
    """Load the icon at the exact pixel sizes Windows will draw.

    Tk's iconbitmap hands Windows a single image and lets it rescale, which
    on a 150% display means a 32-pixel icon stretched to 48 -- the blur you
    see in the taskbar. Loading each size explicitly lets the shell pick the
    matching entry out of the .ico instead.
    """
    try:
        import ctypes
        user32 = ctypes.windll.user32
        root.update_idletasks()
        hwnd = user32.GetAncestor(int(root.winfo_id()), 2)   # GA_ROOT
        if not hwnd:
            return False

        try:
            dpi = user32.GetDpiForWindow(hwnd) or 96
        except Exception:
            dpi = 96
        scale = dpi / 96.0

        IMAGE_ICON, LR_LOADFROMFILE = 1, 0x0010
        WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1
        user32.LoadImageW.restype = ctypes.c_void_p
        user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                        ctypes.c_void_p, ctypes.c_void_p]

        ok = False
        for which, base in ((ICON_SMALL, 16), (ICON_BIG, 32)):
            px = max(1, int(round(base * scale)))
            handle = user32.LoadImageW(None, str(ICON), IMAGE_ICON, px, px,
                                       LR_LOADFROMFILE)
            if handle:
                _ICON_HANDLES.append(handle)
                user32.SendMessageW(ctypes.c_void_p(hwnd), WM_SETICON,
                                    ctypes.c_void_p(which),
                                    ctypes.c_void_p(handle))
                ok = True
        return ok
    except Exception:
        return False


def _no_display(exc: Exception) -> int:
    """Tk could not open a display -- say so usefully, on a console or not."""
    message = (
        "RebrandX could not open a window.\n\n%s\n\n"
        "On Linux this usually means there is no display available "
        "(running over SSH without X forwarding, for example).\n\n"
        "The command line does not need one:\n"
        "    rbx OldName NewName PATH" % exc)
    sys.stderr.write(message + "\n")
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "RebrandX", 0x10)
        except Exception:
            pass
    return 3


if __name__ == "__main__":
    sys.exit(main())
