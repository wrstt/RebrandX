"""The RebrandX palette, and the ttk styling built from it.

The app mark is charcoal and brass. Rendering the whole window that way --
warm near-black surfaces, a single metallic accent, warm off-white type --
is what lets the brass read as an accent rather than as decoration, and it
is the register a tool like this should be in.

Everything is one flat scale of warm greys. Nothing here is neutral grey:
every surface carries a little yellow, so the brass belongs to it.

Pure stdlib, and imports tkinter lazily, so this module is safe to import
on a machine with no display.
"""

from __future__ import annotations

import os

# -- surfaces --------------------------------------------------------------
# Five steps, each a clear notch above the last. Depth is carried by these
# rather than by borders, which is what keeps the window from looking like
# a stack of boxes.
BG = "#100F0D"           # the window field, behind everything
SURFACE = "#171613"      # card face
SURFACE_2 = "#1D1B17"    # raised inside a card: inputs, rows
SURFACE_3 = "#25221D"    # hover
SURFACE_4 = "#302C25"    # pressed / selected

CHROME = "#0C0B0A"       # header and footer bars, a step below the field
CHROME_2 = "#181613"

# -- lines -----------------------------------------------------------------
BORDER = "#252119"       # hairline between surfaces
BORDER_STRONG = "#332E25"
# A 1px lighter edge along the top of a panel reads as light from above.
HIGHLIGHT = "#2A251D"

# -- type ------------------------------------------------------------------
TEXT = "#EDE8DC"         # warm off-white, never pure white
TEXT_STRONG = "#FBF7EE"
TEXT_MUTED = "#9C9587"
TEXT_SUBTLE = "#6B6558"
TEXT_FAINT = "#4A453C"

# -- accent ----------------------------------------------------------------
BRASS = "#D0A94A"        # the one accent
BRASS_BRIGHT = "#E3BE63"
BRASS_DIM = "#8A7233"
BRASS_DEEP = "#5A4A22"
BRASS_GHOST = "#241E12"  # brass at low opacity, pre-blended onto SURFACE
BRASS_TEXT = "#D8B45C"

# -- semantic --------------------------------------------------------------
DANGER = "#E3766A"
DANGER_DIM = "#8C443C"
DANGER_GHOST = "#2A1A17"
ADD = "#8FC97A"
ADD_DIM = "#4E6B43"
ADD_GHOST = "#182117"

# Field fill, a notch below the card so an input reads as a well.
FIELD = "#131210"
FIELD_BORDER = "#2C2820"

# Selection in the file tree.
SEL = "#241F17"
SEL_STRONG = "#2E281D"

# Shadow ramp under a card, darkest nearest. On a near-black field a
# shadow is a *darker* halo, not a lighter one.
SHADOW = ("#0E0D0B", "#0B0A09", "#080807", "#060605")

# The three-stop brand rule from the logo.
STRIP = ("#4A443A", "#8A8578", BRASS)

# Legacy aliases, so anything still importing the old names keeps working.
ACCENT = BRASS
ACCENT_FG = "#1A1509"
ACCENT_HOVER = BRASS_BRIGHT
SURFACE_2_LIGHT = SURFACE_3
INK = CHROME
INK_2 = CHROME_2
INK_LINE = BORDER
INK_TEXT = TEXT
INK_MUTED = TEXT_MUTED
INK_SUBTLE = TEXT_SUBTLE
DANGER_DARK = DANGER
DANGER_SOFT = DANGER_GHOST
ADD_SOFT = ADD_GHOST
ADD_TEXT = ADD
BRASS_SOFT = BRASS_GHOST


# --------------------------------------------------------------------------
# scaling
# --------------------------------------------------------------------------
# Tk scales *fonts* with the display DPI but leaves every explicit pixel
# size alone. Mixing the two is what makes a layout look fine at 100% and
# fall apart at 125%: the text grows, the column it sits in does not, and
# labels get sliced off. So every structural dimension in this app goes
# through px().
SCALE = 1.0


def init_scaling(root) -> float:
    """Read the real display DPI and set both Tk's scaling and ours."""
    global SCALE
    dpi = 96.0
    if os.name == "nt":
        try:
            import ctypes
            dc = ctypes.windll.user32.GetDC(0)
            dpi = float(ctypes.windll.gdi32.GetDeviceCaps(dc, 88))  # LOGPIXELSX
            ctypes.windll.user32.ReleaseDC(0, dc)
        except Exception:
            dpi = 96.0
    else:
        try:
            dpi = float(root.winfo_fpixels("1i"))
        except Exception:
            dpi = 96.0
    if dpi <= 0:
        dpi = 96.0
    SCALE = max(1.0, min(3.0, dpi / 96.0))
    try:
        root.tk.call("tk", "scaling", dpi / 72.0)
    except Exception:
        pass
    return SCALE


def px(n: float) -> int:
    """A device-independent pixel count, scaled to this display."""
    return int(round(n * SCALE))


def fonts():
    """(ui, ui_bold, ui_small, mono) for this platform.

    Segoe UI Variable is the Windows 11 face and is noticeably better set
    than plain Segoe UI; Cascadia Mono is the modern Windows monospace.
    Both fall back cleanly.
    """
    if os.name == "nt":
        ui = _first("Segoe UI Variable Text", "Segoe UI")
        mono = _first("Cascadia Mono", "Consolas", "Courier New")
        return ((ui, 10), (ui, 10, "bold"), (ui, 9), (mono, 10))
    ui = _first("Inter", "Ubuntu", "DejaVu Sans")
    mono = _first("JetBrains Mono", "Ubuntu Mono", "DejaVu Sans Mono")
    return ((ui, 10), (ui, 10, "bold"), (ui, 9), (mono, 10))


def display_font():
    """The larger face used for the wordmark and the headline numbers."""
    if os.name == "nt":
        return (_first("Segoe UI Variable Display", "Segoe UI Semibold",
                       "Segoe UI"), 15, "bold")
    return (fonts()[0][0], 15, "bold")


def eyebrow_font():
    """Tiny caps for section labels. Letter-spacing is applied by hand."""
    return (fonts()[0][0], 8, "bold")


def _first(*names: str) -> str:
    """The first of these font families the system actually has."""
    try:
        import tkinter.font as tkfont
        have = set(tkfont.families())
        for name in names:
            if name in have:
                return name
    except Exception:
        pass
    return names[-1]


def spaced(text: str, gap: str = " ") -> str:
    """Fake letter-spacing. Tk has no such attribute, and the small caps
    used for section labels need it badly."""
    return gap.join(text.upper())


def apply_theme(root):
    """Style the ttk widgets that survive into the dark theme.

    Almost everything is drawn by hand in widgets.py; what is left here is
    the Treeview (worth keeping for its tree behaviour and keyboard
    handling) and the odd frame.
    """
    from tkinter import ttk

    ui, ui_bold, ui_small, mono = fonts()
    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    root.configure(background=BG)

    style.configure(".", background=BG, foreground=TEXT, font=ui,
                    borderwidth=0, focuscolor=BG)
    style.configure("TFrame", background=BG)

    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE,
                    foreground=TEXT, font=ui, rowheight=px(30),
                    borderwidth=0, relief="flat")
    style.map("Treeview",
              background=[("selected", SEL_STRONG)],
              foreground=[("selected", TEXT_STRONG)])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # The paned window's sash is the only thing between two cards, so it
    # should be the field colour and nothing else.
    style.configure("TPanedwindow", background=BG)
    style.configure("Sash", sashthickness=px(10), gripcount=0, background=BG,
                    lightcolor=BG, darkcolor=BG, bordercolor=BG)

    return ui, ui_bold, ui_small, mono
