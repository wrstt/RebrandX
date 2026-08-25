"""The drawn controls RebrandX is built from.

Tk's stock themes are either uncustomisable (`vista`, `xpnative` draw from
the OS atlas) or badly dated (`clam`'s X-in-a-box checkbuttons, sunken
entries, 3-D scrollbars). Neither can carry a dark theme.

So everything that carries the design is painted on a Canvas here: cards,
buttons, checkboxes, the segmented switch, entry fields, scrollbars, the
app mark. All stdlib tkinter -- no image files, no fonts to ship, and it
stays sharp at any DPI.

ttk keeps only the Treeview, whose tree and keyboard behaviour is worth
more than its styling costs.
"""

from __future__ import annotations

import tkinter as tk

from rebrandx import anim
from rebrandx import theme as T


# --------------------------------------------------------------------------
# drawing helpers
# --------------------------------------------------------------------------

def round_rect(cv: tk.Canvas, x1, y1, x2, y2, r, **kw):
    """A rounded rectangle as one smoothed polygon.

    Canvas has no rounded-rect primitive. Doubling each corner point and
    smoothing gives a clean radius at any size, and it stays a single item
    so it can be re-coloured in one call.
    """
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [
        x1 + r, y1, x2 - r, y1, x2 - r, y1, x2, y1,
        x2, y1 + r, x2, y2 - r, x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2, x1 + r, y2, x1, y2,
        x1, y2 - r, x1, y1 + r, x1, y1 + r, x1, y1,
    ]
    return cv.create_polygon(pts, smooth=True, splinesteps=18, **kw)


# --------------------------------------------------------------------------
# anti-aliased corners
# --------------------------------------------------------------------------
# Tk's canvas has no anti-aliasing whatsoever: create_polygon(smooth=True)
# still lands on whole pixels, so every rounded corner comes out visibly
# stair-stepped. That single detail is most of what separates a drawn UI
# that looks made from one that looks approximated.
#
# The fix is to draw the corners as small pre-rendered images and leave the
# straight parts to plain rectangles, which need no smoothing. Each tile is
# only radius x radius, and they are cached, so the cost is a few hundred
# bytes per (radius, colour) pair and nothing per frame.

_TILE_CACHE: dict = {}
# A fade produces roughly a dozen distinct colours per widget kind, so the
# cache settles quickly. The cap is a backstop against a caller animating a
# colour continuously forever, not something normal use reaches.
_TILE_CACHE_MAX = 600


def _rgb(colour: str):
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def _png_rgb(w: int, h: int, rows) -> bytes:
    """Encode RGB rows (each w*3 bytes) as a PNG."""
    import struct
    import zlib
    raw = bytearray()
    for row in rows:
        raw.append(0)                     # filter: none
        raw += row

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + chunk(b"IEND", b""))


def _corner_tile(r: int, fill: str, outline: str, bg: str, width: float,
                 corner: int):
    """One anti-aliased corner, as a cached Tk image.

    `corner` is 0=top-left, 1=top-right, 2=bottom-left, 3=bottom-right.

    Coverage comes from the distance field rather than by supersampling:
    for a circle the exact distance is already known, so one sqrt per pixel
    gives a better edge than 16 point samples and is an order of magnitude
    cheaper -- about 0.07 ms a tile. That speed is what lets these be
    generated mid-fade without stuttering, and what makes it affordable to
    key the cache on the exact colour rather than a rounded one.
    """
    import base64
    key = (r, fill, outline, bg, round(width, 1), corner)
    img = _TILE_CACHE.get(key)
    if img is not None:
        return img
    if len(_TILE_CACHE) > _TILE_CACHE_MAX:
        _TILE_CACHE.clear()

    fr, fg, fb = _rgb(fill)
    orr, og, ob = _rgb(outline)
    br, bgc, bb = _rgb(bg)
    # The arc centre is whichever tile corner faces into the shape.
    cx = r if corner in (0, 2) else 0.0
    cy = r if corner in (0, 1) else 0.0
    inner = max(0.0, r - max(0.0, width))

    rows = []
    for y in range(r):
        py = y + 0.5
        dy2 = (py - cy) ** 2
        row = bytearray()
        for x in range(r):
            px = x + 0.5
            d = (dy2 + (px - cx) ** 2) ** 0.5
            # A half-pixel ramp either side of each edge of the ring.
            a_out = d and (r - d) + 0.5 or 1.0
            a_out = 0.0 if a_out < 0.0 else (1.0 if a_out > 1.0 else a_out)
            a_in = (d - inner) + 0.5
            a_in = 0.0 if a_in < 0.0 else (1.0 if a_in > 1.0 else a_in)
            edge = a_out * a_in
            body = a_out - edge
            rest = 1.0 - a_out
            row.append(int(br * rest + orr * edge + fr * body + 0.5))
            row.append(int(bgc * rest + og * edge + fg * body + 0.5))
            row.append(int(bb * rest + ob * edge + fb * body + 0.5))
        rows.append(bytes(row))

    img = tk.PhotoImage(data=base64.b64encode(_png_rgb(r, r, rows)))
    _TILE_CACHE[key] = img            # the cache is what keeps it referenced
    return img


def round_rect_aa(cv: tk.Canvas, x1, y1, x2, y2, r, fill,
                  outline=None, bg=None, width=1.0, tags=()):
    """A rounded rectangle with smooth corners.

    Falls back to the plain polygon if anything about the image path fails,
    so the worst case is the look we had before rather than a blank widget.
    """
    x1, y1, x2, y2 = int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2))
    r = int(min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    if r < 2 or not fill:
        return round_rect(cv, x1, y1, x2, y2, max(0, r), fill=fill or "",
                          outline=outline or fill or "", width=width, tags=tags)

    outline = outline or fill
    bg = bg or _bg_of(cv)
    try:
        for corner, (px, py) in enumerate(((x1, y1), (x2 - r, y1),
                                           (x1, y2 - r), (x2 - r, y2 - r))):
            cv.create_image(px, py, anchor="nw", tags=tags,
                            image=_corner_tile(r, fill, outline, bg, width,
                                               corner))
    except Exception:
        return round_rect(cv, x1, y1, x2, y2, r, fill=fill, outline=outline,
                          width=width, tags=tags)

    # The straight parts need no smoothing, so they stay as rectangles.
    cv.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="",
                        tags=tags)
    cv.create_rectangle(x1, y1 + r, x1 + r, y2 - r, fill=fill, outline="",
                        tags=tags)
    cv.create_rectangle(x2 - r, y1 + r, x2, y2 - r, fill=fill, outline="",
                        tags=tags)

    if outline != fill:
        half = width / 2.0
        cv.create_line(x1 + r, y1 + half, x2 - r, y1 + half, fill=outline,
                       width=width, tags=tags)
        cv.create_line(x1 + r, y2 - half, x2 - r, y2 - half, fill=outline,
                       width=width, tags=tags)
        cv.create_line(x1 + half, y1 + r, x1 + half, y2 - r, fill=outline,
                       width=width, tags=tags)
        cv.create_line(x2 - half, y1 + r, x2 - half, y2 - r, fill=outline,
                       width=width, tags=tags)
    return None


def mix(a: str, b: str, t: float) -> str:
    """Blend two #rrggbb colours. Tk has no alpha, so translucency is
    pre-computed against whatever is actually behind the element."""
    t = max(0.0, min(1.0, t))
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return "#%02x%02x%02x" % (round(ar + (br - ar) * t),
                              round(ag + (bg - ag) * t),
                              round(ab + (bb - ab) * t))


def _fit(text: str, font, width: int) -> str:
    """Trim `text` with an ellipsis so it fits `width` pixels.

    A Canvas does not clip or wrap its text, so anything too long simply
    runs out of the panel and off the edge of the card. Measuring and
    truncating is the only way to keep a long hint inside its column.
    """
    if width <= 0 or not text:
        return text
    try:
        import tkinter.font as tkfont
        f = tkfont.Font(font=font)
        if f.measure(text) <= width:
            return text
        ell = "\u2026"
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if f.measure(text[:mid] + ell) <= width:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + ell if lo else ell
    except Exception:
        return text


def _bg_of(widget) -> str:
    try:
        return widget.cget("background") or T.BG
    except tk.TclError:
        return T.BG


class _Drawn(tk.Canvas):
    """Base for a canvas control: borderless, repaints on resize."""

    def __init__(self, parent, height=None, bg=None, **kw):
        if height is not None:
            kw["height"] = height
        super().__init__(parent, highlightthickness=0, bd=0,
                         background=(bg or _bg_of(parent)), takefocus=0, **kw)
        self.bind("<Configure>", lambda e: self._draw())

    def _draw(self):
        raise NotImplementedError


# --------------------------------------------------------------------------
# card
# --------------------------------------------------------------------------

class Card(tk.Frame):
    """A raised panel: rounded, hairline border, lit along its top edge.

    That top highlight is the whole trick. One pixel of a lighter colour
    across the top of a dark panel reads as light falling from above, and
    is most of the difference between a flat rectangle and something that
    looks made.
    """

    INSET = 6

    def __init__(self, parent, radius=14, bg=T.SURFACE, border=T.BORDER,
                 highlight=True, inset=None, **kw):
        super().__init__(parent, background=_bg_of(parent), **kw)
        self._radius, self._bg, self._border = T.px(radius), bg, border
        self._highlight = highlight
        self._inset = T.px(self.INSET if inset is None else inset)
        self._cv = tk.Canvas(self, highlightthickness=0, bd=0,
                             background=_bg_of(parent), takefocus=0)
        self._cv.place(x=0, y=0, relwidth=1, relheight=1)

        i = self._inset
        self.body = tk.Frame(self, background=bg)
        self.body.place(x=i, y=i, relwidth=1, relheight=1,
                        width=-2 * i, height=-2 * i)
        self.bind("<Configure>", self._draw)

    def _draw(self, _evt=None):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        cv = self._cv
        cv.delete("all")
        i, r = self._inset, self._radius
        x1, y1, x2, y2 = i, i, w - i, h - i

        for n, colour in enumerate(T.SHADOW):
            grow = T.px(len(T.SHADOW) - n)
            round_rect(cv, x1 - grow, y1 - grow + T.px(2),
                       x2 + grow, y2 + grow + T.px(2),
                       r + grow, fill=colour, outline=colour)

        round_rect_aa(cv, x1, y1, x2, y2, r, fill=self._bg,
                      outline=self._border, bg=_bg_of(self), width=1)
        if self._highlight:
            cv.create_line(x1 + r * 0.8, y1 + 0.5, x2 - r * 0.8, y1 + 0.5,
                           fill=T.HIGHLIGHT)


# --------------------------------------------------------------------------
# app mark
# --------------------------------------------------------------------------

class Mark(tk.Canvas):
    """The RebrandX mark, drawn rather than loaded.

    Same construction as share/rebrandx.svg -- a rounded tile, the brand
    strip across the top, an off-white R -- so it is crisp at any DPI
    without shipping a bitmap per size.
    """

    def __init__(self, parent, size=32, bg=None):
        size = T.px(size)
        super().__init__(parent, width=size, height=size, highlightthickness=0,
                         bd=0, background=(bg or _bg_of(parent)), takefocus=0)
        self.size = size
        self._draw()

    def _draw(self):
        s = self.size
        self.delete("all")
        r = s * 0.27
        round_rect(self, 0.5, 0.5, s - 0.5, s - 0.5, r,
                   fill=T.SURFACE_3, outline=T.BORDER_STRONG, width=1)
        self.create_line(r * 0.8, 1, s - r * 0.8, 1, fill=T.SURFACE_4)

        # The strip is inset past the corner radius rather than masked
        # afterwards; masking used to clip it into a broken line.
        inset = r * 0.72
        seg = (s - inset * 2) / 3.0
        top, thick = s * 0.155, max(2.0, s * 0.075)
        for i, colour in enumerate(T.STRIP):
            self.create_rectangle(inset + i * seg, top,
                                  inset + (i + 1) * seg, top + thick,
                                  fill=colour, outline=colour)
        self.create_text(s / 2, s * 0.645, text="R", fill=T.TEXT_STRONG,
                         font=(T.fonts()[0][0], int(s * 0.42), "bold"),
                         anchor="center")


# --------------------------------------------------------------------------
# button
# --------------------------------------------------------------------------

#            (fill,        text,           hover,          border,           press)
_KINDS = {
    "cta":   (T.BRASS,     "#191307",      T.BRASS_BRIGHT, "",               T.BRASS_DIM),
    "ghost": (T.SURFACE_2, T.TEXT,         T.SURFACE_3,    T.BORDER_STRONG,  T.SURFACE_4),
    "quiet": ("",          T.TEXT_MUTED,   T.SURFACE_2,    "",               T.SURFACE_3),
    "danger": (T.DANGER_GHOST, T.DANGER,   "#3A211C",      T.DANGER_DIM,     "#43251F"),
}


class Button(_Drawn):
    """A flat rounded button with hover, press and disabled states."""

    def __init__(self, parent, text="", command=None, kind="ghost", width=None,
                 height=34, radius=10, font=None, padx=16, bg=None, icon=""):
        super().__init__(parent, height=T.px(height), bg=bg)
        self.text, self.command, self.kind, self.icon = text, command, kind, icon
        self.radius, self.padx = T.px(radius), T.px(padx)
        self.font = font or T.fonts()[0]
        self._state = "normal"
        self._hover = self._down = False
        # 0 = at rest, 1 = fully hovered. Tweened rather than switched, so
        # the button lights up instead of blinking.
        self._lit = 0.0
        self.configure(cursor="hand2")
        self.configure(width=width or self._natural_width())

        self.bind("<Enter>", lambda e: self._hover_to(True))
        self.bind("<Leave>", lambda e: self._hover_to(False))
        self.bind("<Button-1>", lambda e: self._set("_down", True))
        self.bind("<ButtonRelease-1>", self._release)

    def _hover_to(self, on):
        if self._hover == on:
            return
        self._hover = on
        if not on:
            self._down = False
        if self._state == "disabled":
            self._lit = 0.0
            self._draw()
            return
        anim.tween(self, "lit", self._lit, 1.0 if on else 0.0,
                   130 if on else 170, self._set_lit)

    def _set_lit(self, value):
        self._lit = value
        self._draw()

    def _natural_width(self) -> int:
        try:
            import tkinter.font as tkfont
            w = tkfont.Font(font=self.font).measure(self.text)
        except Exception:
            w = len(self.text) * 8
        return w + self.padx * 2 + (T.px(18) if self.icon else 0)

    def _set(self, attr, value):
        if getattr(self, attr) != value:
            setattr(self, attr, value)
            self._draw()

    def _release(self, _e):
        fire = self._down and self._state != "disabled"
        self._set("_down", False)
        if fire and self.command:
            self.command()

    # -- a ttk-ish surface, so callers can use ["state"] and .configure ---
    def configure(self, **kw):                                # type: ignore[override]
        redraw = False
        if "text" in kw:
            self.text = kw.pop("text"); redraw = True
        if "state" in kw:
            self._state = kw.pop("state")
            super().configure(cursor="arrow" if self._state == "disabled"
                              else "hand2")
            redraw = True
        if "command" in kw:
            self.command = kw.pop("command")
        if kw:
            super().configure(**kw)
        if redraw:
            self._draw()

    config = configure

    def __setitem__(self, key, value):
        self.configure(**{key: value})

    def __getitem__(self, key):
        if key == "state":
            return self._state
        if key == "text":
            return self.text
        return super().cget(key)

    def cget(self, key):                                      # type: ignore[override]
        return self[key] if key in ("state", "text") else super().cget(key)

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        self.delete("all")
        fill, fg, hover, border, press = _KINDS.get(self.kind, _KINDS["ghost"])
        base = _bg_of(self)

        if self._state == "disabled":
            fill = T.SURFACE if self.kind != "quiet" else ""
            fg, border = T.TEXT_FAINT, T.BORDER
        elif self._down:
            fill, border = press, border or press
        elif self._lit > 0.0:
            # Blend rest -> hover by however far the tween has come.
            base = fill or _bg_of(self)
            fill = anim.lerp_colour(base, hover, self._lit)
            border = (anim.lerp_colour(border, hover, self._lit * 0.6)
                      if border else fill)

        if fill:
            round_rect_aa(self, 0, 0, w, h, self.radius, fill=fill,
                          outline=border or fill, bg=base, width=1)
            # The CTA gets the same lit top edge the cards have.
            if self.kind == "cta" and self._state != "disabled":
                self.create_line(self.radius, 1, w - self.radius, 1,
                                 fill=mix(fill, "#ffffff", 0.28))

        elif border:
            round_rect_aa(self, 0, 0, w, h, self.radius, fill=base,
                          outline=border, bg=base, width=1)

        x = w / 2
        if self.icon:
            self.create_text(x - self._text_w() / 2 - T.px(9), h / 2,
                             text=self.icon, anchor="e", font=self.font,
                             fill=fg)
        self.create_text(x, h / 2 + 0.5, text=self.text, fill=fg,
                         font=self.font, anchor="center")

    def _text_w(self) -> int:
        try:
            import tkinter.font as tkfont
            return tkfont.Font(font=self.font).measure(self.text)
        except Exception:
            return len(self.text) * 8


# --------------------------------------------------------------------------
# checkbox
# --------------------------------------------------------------------------

class Check(_Drawn):
    """A checkbox with a drawn tick, an optional hint, and a hit area that
    covers the whole row rather than a 13-pixel square."""

    BOX = 18

    def __init__(self, parent, text="", variable=None, hint="", command=None,
                 font=None, hint_font=None, bg=None):
        self.hint = hint
        super().__init__(parent, height=T.px(46 if hint else 30), bg=bg)
        self.text = text
        self.var = variable if variable is not None else tk.BooleanVar()
        self.command = command
        self.font = font or T.fonts()[0]
        self.hint_font = hint_font or T.fonts()[2]
        self._hover = False
        self._lit = 0.0
        self._on = 1.0 if self.var.get() else 0.0
        self.configure(cursor="hand2")
        self.bind("<Enter>", lambda e: self._hover_set(True))
        self.bind("<Leave>", lambda e: self._hover_set(False))
        self.bind("<Button-1>", self._toggle)
        self.var.trace_add("write", lambda *_: self._on_changed())

    def _hover_set(self, on):
        if self._hover == on:
            return
        self._hover = on
        anim.tween(self, "lit", self._lit, 1.0 if on else 0.0, 120,
                   self._set_lit)

    def _set_lit(self, value):
        self._lit = value
        self._draw()

    def _on_changed(self):
        """Fill or empty the box over a few frames rather than in one."""
        anim.tween(self, "on", self._on, 1.0 if self.var.get() else 0.0,
                   140, self._set_on)

    def _set_on(self, value):
        self._on = value
        self._draw()

    def _toggle(self, _e=None):
        self.var.set(not self.var.get())
        if self.command:
            self.command()

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        self.delete("all")
        on = bool(self.var.get())
        b, top = T.px(self.BOX), T.px(5)
        base = _bg_of(self)

        wash = anim.lerp_colour(base, T.SURFACE_2, self._lit)
        if self._lit > 0.0:
            round_rect_aa(self, -T.px(6), 0, w, h, T.px(9), fill=wash,
                          outline=wash, bg=base)

        rest = anim.lerp_colour(T.SURFACE_2, T.SURFACE_3, self._lit)
        fill = anim.lerp_colour(rest, T.BRASS, self._on)
        edge = anim.lerp_colour(
            anim.lerp_colour(T.BORDER, T.BORDER_STRONG, self._lit),
            T.BRASS, self._on)

        round_rect_aa(self, 0, top, b, top + b, T.px(6), fill=fill,
                      outline=edge, bg=(wash if self._lit > 0.0 else base),
                      width=max(1.0, T.px(1.3)))
        if self._on > 0.02:
            # A drawn tick stays crisp where a font glyph would not.
            u = b / 18.0
            x, y = 4.4 * u, top + b / 2
            # The tick draws itself on, so a toggle reads as an action.
            g = anim.ease_out_cubic(min(1.0, self._on))
            mx, my = x + 3.7 * u, y + 4.0 * u
            if g < 0.45:
                k = g / 0.45
                self.create_line(x, y, x + 3.7 * u * k, y + 4.0 * u * k,
                                 fill="#191307", width=max(1.6, 2.1 * u),
                                 capstyle="round")
            else:
                k = (g - 0.45) / 0.55
                self.create_line(x, y, mx, my,
                                 mx + (6.3 * u) * k, my - (8.6 * u) * k,
                                 fill="#191307", width=max(1.6, 2.1 * u),
                                 capstyle="round", joinstyle="round")

        tx = b + T.px(12)
        avail = max(20, w - tx - T.px(6))
        self.create_text(tx, top + b / 2 + 0.5,
                         text=_fit(self.text, self.font, avail), anchor="w",
                         font=self.font,
                         fill=anim.lerp_colour(T.TEXT_MUTED, T.TEXT, self._on))
        if self.hint:
            self.create_text(tx, top + b + T.px(11),
                             text=_fit(self.hint, self.hint_font, avail),
                             anchor="w", font=self.hint_font,
                             fill=T.TEXT_SUBTLE)


# --------------------------------------------------------------------------
# segmented control
# --------------------------------------------------------------------------

class Segmented(_Drawn):
    """A two-way switch with a raised selected pill, in place of radios."""

    def __init__(self, parent, options, variable, command=None, height=36,
                 font=None, bg=None):
        super().__init__(parent, height=T.px(height), bg=bg)
        self.options = options                      # [(value, label), ...]
        self.var = variable
        self.command = command
        self.font = font or T.fonts()[0]
        self._hover = None
        self.configure(cursor="hand2")
        self.bind("<Motion>", self._move)
        self.bind("<Leave>", lambda e: self._hover_set(None))
        self.bind("<Button-1>", self._click)
        self.var.trace_add("write", lambda *_: self._draw())

    def _index_at(self, x):
        return min(len(self.options) - 1,
                   max(0, int(x / (max(1, self.winfo_width()) / len(self.options)))))

    def _hover_set(self, i):
        if i != self._hover:
            self._hover = i
            self._draw()

    def _move(self, e):
        self._hover_set(self._index_at(e.x))

    def _click(self, e):
        value = self.options[self._index_at(e.x)][0]
        if value != self.var.get():
            self.var.set(value)
            if self.command:
                self.command()

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        self.delete("all")
        round_rect_aa(self, 0, 0, w, h, T.px(10), fill=T.FIELD,
                      outline=T.BORDER, bg=_bg_of(self), width=1)
        seg = w / len(self.options)
        pad, r = T.px(3), T.px(7)
        for i, (value, label) in enumerate(self.options):
            x1, x2 = i * seg, (i + 1) * seg
            chosen = self.var.get() == value
            if chosen:
                round_rect_aa(self, x1 + pad, pad, x2 - pad, h - pad, r,
                              fill=T.SURFACE_3, outline=T.BORDER_STRONG,
                              bg=T.FIELD, width=1)
                self.create_line(x1 + T.px(8), pad + 1, x2 - T.px(8), pad + 1,
                                 fill=T.SURFACE_4)
            elif self._hover == i:
                round_rect(self, x1 + pad, pad, x2 - pad, h - pad, r,
                           fill=T.SURFACE_2, outline=T.SURFACE_2)
            self.create_text((x1 + x2) / 2, h / 2 + 0.5, text=label,
                             font=self.font, anchor="center",
                             fill=T.TEXT_STRONG if chosen else T.TEXT_SUBTLE)


# --------------------------------------------------------------------------
# entry field
# --------------------------------------------------------------------------

class Field(tk.Frame):
    """A tk.Entry inside a drawn well that lights brass on focus."""

    def __init__(self, parent, textvariable=None, font=None, height=38,
                 radius=10, fg=T.TEXT, fill=T.FIELD, **kw):
        super().__init__(parent, background=_bg_of(parent), height=T.px(height))
        self.pack_propagate(False)
        self._radius, self._fill = T.px(radius), fill
        self._focused = False
        self._glow = 0.0
        self._cv = tk.Canvas(self, highlightthickness=0, bd=0,
                             background=_bg_of(parent), takefocus=0)
        self._cv.place(x=0, y=0, relwidth=1, relheight=1)

        self.entry = tk.Entry(
            self, textvariable=textvariable, font=font or T.fonts()[3],
            relief="flat", bd=0, highlightthickness=0,
            background=fill, foreground=fg,
            insertbackground=T.BRASS, insertwidth=2,
            selectbackground=T.BRASS_DEEP, selectforeground=T.TEXT_STRONG,
            disabledbackground=fill, **kw)
        # Inset enough that the drawn border and its corners are never
        # painted over by the Entry itself.
        pad_x, pad_y = T.px(13), T.px(3)
        self.entry.place(x=pad_x, y=pad_y, relwidth=1, relheight=1,
                         width=-2 * pad_x, height=-2 * pad_y)

        self.entry.bind("<FocusIn>", lambda e: self._focus(True))
        self.entry.bind("<FocusOut>", lambda e: self._focus(False))
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", lambda e: self.entry.focus_set())

    def _focus(self, on):
        self._focused = on
        anim.tween(self, "focus", self._glow, 1.0 if on else 0.0,
                   150 if on else 200, self._set_glow)

    def _set_glow(self, value):
        self._glow = value
        self._draw()

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        cv = self._cv
        cv.delete("all")
        if self._glow > 0.01:
            # A soft brass halo outside the border, faked with two rings
            # blended against the card behind it.
            base = _bg_of(self)
            for step, t in ((3, 0.10), (2, 0.18), (1, 0.34)):
                grow = T.px(step)
                colour = mix(base, T.BRASS, t * self._glow)
                round_rect(cv, 0.5 - grow, 0.5 - grow, w - 0.5 + grow,
                           h - 0.5 + grow, self._radius + grow,
                           fill="", outline=colour, width=1)
        round_rect_aa(cv, 1, 1, w - 1, h - 1, self._radius,
                      fill=self._fill,
                      outline=anim.lerp_colour(T.FIELD_BORDER, T.BRASS,
                                               self._glow),
                      bg=_bg_of(self), width=1.2 + 0.5 * self._glow)

    def focus_set(self):                                      # type: ignore[override]
        self.entry.focus_set()

    def get(self):
        return self.entry.get()


# --------------------------------------------------------------------------
# scrollbar
# --------------------------------------------------------------------------

class Scrollbar(_Drawn):
    """A thin drawn scrollbar that fades in on hover and hides when unused.

    ttk's is the last obviously-dated thing in the window even after
    restyling -- clam draws it with 3-D edges and stepper arrows.
    """

    def __init__(self, parent, command=None, width=11, bg=None):
        super().__init__(parent, bg=bg, width=T.px(width))
        self.command = command
        self._first, self._last = 0.0, 1.0
        self._hover = self._drag = False
        self._grab = 0.0
        self.bind("<Enter>", lambda e: self._hover_set(True))
        self.bind("<Leave>", lambda e: self._hover_set(False))
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)

    def set(self, first, last):
        self._first, self._last = float(first), float(last)
        self._draw()

    def _hover_set(self, on):
        self._hover = on
        self._draw()

    def _span(self):
        h = self.winfo_height()
        top = self._first * h
        bottom = max(top + T.px(24), self._last * h)
        return top, bottom

    def _press(self, e):
        top, bottom = self._span()
        if top <= e.y <= bottom:
            self._drag, self._grab = True, e.y - top
        else:
            self._jump(e.y - (bottom - top) / 2)
            self._drag, self._grab = True, (bottom - top) / 2
        self._draw()

    def _motion(self, e):
        if self._drag:
            self._jump(e.y - self._grab)

    def _release(self, _e):
        self._drag = False
        self._draw()

    def _jump(self, top_px):
        h = max(1, self.winfo_height())
        if self.command:
            self.command("moveto", max(0.0, min(1.0, top_px / h)))

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        self.delete("all")
        if self._last - self._first >= 1.0:
            return
        top, bottom = self._span()
        if self._drag:
            colour = T.BRASS_DIM
        elif self._hover:
            colour = mix(_bg_of(self), T.TEXT, 0.30)
        else:
            # Visible enough at rest to say "there is more below" without
            # competing with the content.
            colour = mix(_bg_of(self), T.TEXT, 0.16)
        pad = T.px(2.5)
        round_rect(self, pad, top + pad, w - pad, bottom - pad,
                   (w - pad * 2) / 2, fill=colour, outline=colour)


class ScrollFrame(tk.Frame):
    """A vertically scrollable frame whose scrollbar appears only when the
    content overflows. Put content in `.body`."""

    def __init__(self, parent, bg=T.SURFACE, **kw):
        super().__init__(parent, background=bg, **kw)
        self._cv = tk.Canvas(self, background=bg, highlightthickness=0, bd=0,
                             takefocus=0)
        self._sb = Scrollbar(self, command=self._cv.yview, bg=bg)
        self._cv.configure(yscrollcommand=self._sb.set)
        self._cv.pack(side="left", fill="both", expand=True)

        self.body = tk.Frame(self._cv, background=bg)
        self._win = self._cv.create_window((0, 0), window=self.body, anchor="nw")

        self.body.bind("<Configure>", self._sync)
        self._cv.bind("<Configure>", self._on_canvas)
        for widget in (self._cv, self.body):
            self.bind_wheel(widget)

    def _on_canvas(self, e):
        self._cv.itemconfigure(self._win, width=e.width)
        self._sync()

    def _sync(self, _e=None):
        """Resize the scroll region, and show the bar only when needed.

        Decided from geometry rather than from yscrollcommand: Tk does not
        reliably re-issue that callback when only the scrollregion changes,
        so a column that grew past the window kept its scrollbar hidden and
        simply lost the controls at the bottom.
        """
        self._cv.configure(scrollregion=self._cv.bbox("all"))
        needed = self.body.winfo_reqheight() > self._cv.winfo_height() + 1
        if needed and not self._sb.winfo_ismapped():
            # `before` matters: the canvas is packed expand=True and has
            # already claimed the cavity, so a plain pack() would leave the
            # scrollbar no room and it would never map.
            self._sb.pack(side="right", fill="y", before=self._cv)
        elif not needed and self._sb.winfo_ismapped():
            self._sb.pack_forget()
            self._cv.yview_moveto(0)

    def _wheel(self, e):
        if not self._sb.winfo_ismapped():
            return
        num = getattr(e, "num", None)
        delta = -1 if num == 4 else 1 if num == 5 else (-1 if e.delta > 0 else 1)
        self._cv.yview_scroll(delta * 2, "units")

    def bind_wheel(self, widget):
        widget.bind("<MouseWheel>", self._wheel)     # Windows / macOS
        widget.bind("<Button-4>", self._wheel)       # X11
        widget.bind("<Button-5>", self._wheel)


# --------------------------------------------------------------------------
# chrome
# --------------------------------------------------------------------------

class Chip(_Drawn):
    """The folder well in the header: wide, clickable, inset.

    Drawn as a recess rather than a raised button -- it is where the
    current folder lives, not an action.
    """

    def __init__(self, parent, text="", command=None, icon="", height=40,
                 font=None, bg=None, hint="", mono=None):
        super().__init__(parent, height=T.px(height), bg=bg)
        self.text, self.command, self.icon, self.hint = text, command, icon, hint
        self.font = font or T.fonts()[0]
        self.mono = mono or T.fonts()[3]
        self._hover = False
        self._lit = 0.0
        self._placeholder = True
        self.configure(cursor="hand2")
        self.bind("<Enter>", lambda e: self._hover_set(True))
        self.bind("<Leave>", lambda e: self._hover_set(False))
        self.bind("<Button-1>", lambda e: self.command and self.command())

    def _hover_set(self, on):
        if self._hover == on:
            return
        self._hover = on
        anim.tween(self, "lit", self._lit, 1.0 if on else 0.0, 140,
                   self._set_lit)

    def _set_lit(self, value):
        self._lit = value
        self._draw()

    def set_text(self, text, placeholder=False):
        self.text, self._placeholder = text, placeholder
        self._draw()

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        self.delete("all")
        round_rect_aa(self, 0, 0, w, h, T.px(11),
                      fill=anim.lerp_colour(T.BG, T.CHROME_2, self._lit),
                      outline=anim.lerp_colour(T.BORDER, T.BORDER_STRONG,
                                               self._lit),
                      bg=_bg_of(self), width=1)
        x = T.px(15)
        if self.icon:
            self.create_text(x, h / 2, text=self.icon, anchor="w",
                             font=self.font, fill=T.BRASS)
            x += T.px(22)
        hint_w = T.px(70) if self.hint else T.px(12)
        font = self.font if self._placeholder else self.mono
        self.create_text(x, h / 2 + 0.5,
                         text=_fit(self.text, font, w - x - hint_w),
                         anchor="w", font=font,
                         fill=T.TEXT_SUBTLE if self._placeholder else T.TEXT)
        if self.hint:
            self.create_text(w - T.px(15), h / 2 + 0.5, text=self.hint,
                             anchor="e", font=T.fonts()[2], fill=T.TEXT_FAINT)


class Rail(tk.Canvas):
    """A chrome bar: flat, with one hairline along the edge that faces the
    work area."""

    def __init__(self, parent, height=72, edge="bottom", bg=T.CHROME):
        super().__init__(parent, height=T.px(height), highlightthickness=0,
                         bd=0, background=bg, takefocus=0)
        self._edge, self._bg = edge, bg
        self.bind("<Configure>", lambda e: self._draw())

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        self.delete("all")
        self.create_rectangle(0, 0, w, h, fill=self._bg, outline=self._bg)
        y = h - 0.5 if self._edge == "bottom" else 0.5
        self.create_line(0, y, w, y, fill=T.BORDER)


class Bar(_Drawn):
    """A slim progress bar, drawn to match everything else."""

    def __init__(self, parent, height=5, width=180, bg=None,
                 trough=T.SURFACE_2, fill=T.BRASS):
        super().__init__(parent, height=T.px(height), bg=bg, width=T.px(width))
        self.value, self.maximum = 0, 100
        self._trough, self._fill = trough, fill

    def set(self, value, maximum):
        self.value, self.maximum = value, max(1, maximum)
        self._draw()

    def _draw(self):
        w, h = self.winfo_width(), self.winfo_height()
        if w < 2 or h < 2:
            return
        self.delete("all")
        round_rect(self, 0, 0, w, h, h / 2, fill=self._trough,
                   outline=self._trough)
        frac = max(0.0, min(1.0, self.value / self.maximum))
        if frac > 0:
            round_rect(self, 0, 0, max(h, w * frac), h, h / 2,
                       fill=self._fill, outline=self._fill)
