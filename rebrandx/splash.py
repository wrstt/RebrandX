"""The launch screen.

A frozen one-file build has to unpack itself and start a Python runtime
before any window can exist, which is a second or two of nothing happening.
PyInstaller's own `--splash` covers that gap before Python is even running;
this covers the shorter gap after it, while the window is being built, and
gives the app something to arrive *from* rather than snapping into
existence.

It is never on screen for a fixed length of time. `close()` is called the
moment the real window is ready, so on a fast machine it barely appears --
a splash that outlives its reason is just a delay with a logo on it.
"""

from __future__ import annotations

import tkinter as tk

from rebrandx import anim, theme
from rebrandx.widgets import Mark, round_rect

WIDTH, HEIGHT = 340, 190


class Splash:
    """A small frameless window shown while the app builds itself."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.win: tk.Toplevel | None = None
        self._pulse = 0.0
        self._alive = False
        self._job = None

    def show(self) -> "Splash":
        try:
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.configure(background=theme.CHROME)
            try:
                win.attributes("-topmost", True)
                win.attributes("-alpha", 0.0)
            except tk.TclError:
                pass

            w, h = theme.px(WIDTH), theme.px(HEIGHT)
            x = (win.winfo_screenwidth() - w) // 2
            y = (win.winfo_screenheight() - h) // 2
            win.geometry("%dx%d+%d+%d" % (w, h, x, y))

            self.cv = tk.Canvas(win, width=w, height=h, highlightthickness=0,
                                bd=0, background=theme.CHROME, takefocus=0)
            self.cv.pack(fill="both", expand=True)
            self._paint_frame(w, h)

            Mark(win, size=52, bg=theme.CHROME).place(
                x=w // 2, y=theme.px(58), anchor="center")

            self.win = win
            self._alive = True
            anim.fade_in(win, 160)
            self._tick()
        except tk.TclError:
            self.win = None
        return self

    def _paint_frame(self, w, h):
        cv = self.cv
        cv.delete("frame")
        round_rect(cv, 1, 1, w - 1, h - 1, theme.px(14), fill=theme.CHROME,
                   outline=theme.BORDER_STRONG, width=1, tags="frame")
        cv.create_text(w // 2, theme.px(106), text="RebrandX",
                       fill=theme.TEXT_STRONG, font=theme.display_font(),
                       anchor="center", tags="frame")
        cv.create_text(w // 2, theme.px(128),
                       text=theme.spaced("project renamer"),
                       fill=theme.TEXT_FAINT, font=theme.eyebrow_font(),
                       anchor="center", tags="frame")

    def _tick(self):
        """A brass sweep along the bottom edge, so the screen is alive."""
        if not self._alive or self.win is None:
            return
        try:
            w = self.cv.winfo_width()
            h = self.cv.winfo_height()
            self.cv.delete("sweep")
            track_w = theme.px(180)
            x0 = (w - track_w) / 2
            y = h - theme.px(30)
            bar = theme.px(3)
            round_rect(self.cv, x0, y, x0 + track_w, y + bar, bar / 2,
                       fill=theme.SURFACE_2, outline=theme.SURFACE_2,
                       tags="sweep")
            run = track_w * 0.34
            # Ping-pong, eased at both ends so it never looks mechanical.
            t = anim.ease_in_out(abs((self._pulse % 2.0) - 1.0))
            sx = x0 + (track_w - run) * t
            round_rect(self.cv, sx, y, sx + run, y + bar, bar / 2,
                       fill=theme.BRASS, outline=theme.BRASS, tags="sweep")
            self._pulse += 0.045
            self._job = self.win.after(anim.FRAME_MS, self._tick)
        except tk.TclError:
            self._alive = False

    def close(self, then=None):
        """Fade the splash out, then hand over to `then`.

        Order matters here. Destroying a widget that still has `after` jobs
        pending on it leaves Tk holding a callback against a dead command,
        and the exception that raises breaks the *whole* timer chain -- the
        main window's own fade included, which strands it half transparent.

        So: cancel this window's timers, drive the fade off `root` (which
        outlives it), and destroy on an idle callback once the current one
        has unwound.
        """
        self._alive = False
        win = self.win
        self.win = None
        if win is None:
            if then:
                then()
            return

        if self._job is not None:
            try:
                win.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

        def done():
            def destroy():
                try:
                    win.destroy()
                except tk.TclError:
                    pass
            try:
                self.root.after_idle(destroy)
            except tk.TclError:
                destroy()
            if then:
                then()

        anim.fade_out(win, 170, done, timer=self.root)


def close_pyinstaller_splash() -> None:
    """Dismiss the splash PyInstaller shows before Python starts.

    Only present in a frozen build that was given --splash; importing it
    anywhere else raises, which is the normal case when running from
    source.
    """
    try:
        import pyi_splash                                   # type: ignore
        pyi_splash.close()
    except Exception:
        pass
