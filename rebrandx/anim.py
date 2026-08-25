"""A very small tweening helper for the Tk window.

Tk has no animation of any kind: a widget is whatever colour you last drew
it. Everything that moves or fades in RebrandX is therefore a value being
stepped on a timer, and this is the timer.

Deliberately tiny. Animation here is for state that has *changed* -- a
button lighting up, a panel arriving -- never for making the user wait.
Nothing in this module gates an action: if every tween were dropped the app
would still work, just more abruptly.
"""

from __future__ import annotations

FRAME_MS = 16          # ~60fps


def ease_out_cubic(t: float) -> float:
    """Fast to start, settling gently -- right for things arriving."""
    return 1.0 - pow(1.0 - t, 3)


def ease_out_quad(t: float) -> float:
    return 1.0 - (1.0 - t) * (1.0 - t)


def ease_in_out(t: float) -> float:
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_colour(a: str, b: str, t: float) -> str:
    """Blend two #rrggbb colours."""
    t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
    ar, ag, ab = int(a[1:3], 16), int(a[3:5], 16), int(a[5:7], 16)
    br, bg, bb = int(b[1:3], 16), int(b[3:5], 16), int(b[5:7], 16)
    return "#%02x%02x%02x" % (round(ar + (br - ar) * t),
                              round(ag + (bg - ag) * t),
                              round(ab + (bb - ab) * t))


class Tween:
    """One running animation. Starting a new one on the same key cancels it.

    Keying by (widget, name) is what stops a button that is moused over
    repeatedly from accumulating a pile of timers all fighting to set the
    same value.
    """

    _running: dict = {}

    def __init__(self, widget, name, start, end, ms, setter,
                 ease=ease_out_cubic, on_done=None):
        self.widget = widget
        self.key = (id(widget), name)
        self.start, self.end = start, end
        self.ms = max(1, ms)
        self.setter = setter
        self.ease = ease
        self.on_done = on_done
        self.elapsed = 0
        self._job = None

        old = Tween._running.get(self.key)
        if old is not None:
            old.cancel()
        Tween._running[self.key] = self
        self._step()

    def cancel(self):
        if self._job is not None:
            try:
                self.widget.after_cancel(self._job)
            except Exception:
                pass
            self._job = None
        Tween._running.pop(self.key, None)

    def _step(self):
        self.elapsed += FRAME_MS
        t = min(1.0, self.elapsed / self.ms)
        try:
            self.setter(lerp(self.start, self.end, self.ease(t)))
        except Exception:
            # The widget went away mid-flight; that is not an error.
            self.cancel()
            return
        if t >= 1.0:
            Tween._running.pop(self.key, None)
            self._job = None
            if self.on_done:
                try:
                    self.on_done()
                except Exception:
                    pass
            return
        try:
            self._job = self.widget.after(FRAME_MS, self._step)
        except Exception:
            self.cancel()


def tween(widget, name, start, end, ms, setter, ease=ease_out_cubic,
          on_done=None) -> Tween:
    return Tween(widget, name, start, end, ms, setter, ease, on_done)


def opaque(window) -> None:
    """Force a window fully visible. Never fails."""
    try:
        window.attributes("-alpha", 1.0)
    except Exception:
        pass


def fade_in(window, ms=220, on_done=None):
    """Bring a window up from transparent.

    A fade is decoration; a window stuck at alpha 0 is a dead app. So the
    end state is guaranteed twice over -- once when the tween finishes, and
    again from a timer that does not depend on the tween having survived at
    all. An animation frame can be lost (a sibling widget being destroyed
    mid-flight is enough to break Tk's timer chain), and the cost of losing
    one must never be an invisible window.
    """
    try:
        window.attributes("-alpha", 0.0)
    except Exception:
        # No alpha support here: just show it.
        if on_done:
            on_done()
        return None

    def setter(v):
        window.attributes("-alpha", v)

    def finish():
        opaque(window)
        if on_done:
            on_done()

    handle = tween(window, "alpha", 0.0, 1.0, ms, setter, ease_out_quad,
                   finish)
    try:
        window.after(ms + 400, lambda: opaque(window))
    except Exception:
        opaque(window)
    return handle


def fade_out(window, ms=160, on_done=None, timer=None):
    """Fade a window away, then call `on_done`.

    `timer` lets the frames be driven by a *different* widget -- the caller
    passes a window that will outlive this one, so nothing is left pending
    on a widget that is about to be destroyed.
    """
    try:
        current = float(window.attributes("-alpha"))
    except Exception:
        if on_done:
            on_done()
        return None

    def setter(v):
        try:
            window.attributes("-alpha", v)
        except Exception:
            pass

    host = timer if timer is not None else window
    return tween(host, "fade_out:%d" % id(window), current, 0.0, ms,
                 setter, ease_out_quad, on_done)
