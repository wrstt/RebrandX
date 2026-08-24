#!/usr/bin/env python3
"""RebrandX on Windows: a frameless WebView2 window driven by pywebview.

The UI, the engine and every behaviour are shared with the Linux build -- only
the window itself and the native folder dialog differ. WebView2 ships with
Windows 10/11, so nothing but pywebview needs installing.

    pip install pywebview
    python -m rebrandx.app_win [FOLDER]
"""

from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import webview
except ImportError:
    sys.exit("RebrandX needs pywebview on this platform:\n\n    pip install pywebview\n")

from rebrandx.core import Core, UI_DIR, tilde  # noqa: E402


class Api:
    """Exposed to the page as window.pywebview.api.*"""

    def __init__(self):
        self.core = Core()
        self.window: "webview.Window | None" = None
        self.start_folder: str | None = None

    # -- the single entry point the UI calls -------------------------------
    def rpc(self, method: str, params: dict | None = None):
        params = params or {}
        try:
            handled, result = self.core.handle(method, params, self._progress)
            if handled:
                return {"ok": True, "value": result}
            return {"ok": True, "value": self._platform(method, params)}
        except Exception as exc:                      # surfaced as a toast
            return {"ok": False, "error": str(exc)}

    def boot(self):
        return self.core.boot_payload(self.start_folder)

    # -- window + dialogs --------------------------------------------------
    def _platform(self, method: str, params: dict):
        w = self.window
        if method == "window.minimize":
            w.minimize(); return True
        if method == "window.maximize":
            # pywebview has no "is maximized" flag, so track it ourselves.
            self._maxed = not getattr(self, "_maxed", False)
            w.maximize() if self._maxed else w.restore()
            return self._maxed
        if method == "window.close":
            w.destroy(); return True
        if method in ("window.drag", "window.resize"):
            # Frameless dragging/resizing is done in CSS on WebView2
            # (-webkit-app-region), so these are no-ops here.
            return True
        if method == "pick.folder":
            start = params.get("start") or str(Path.home())
            start = os.path.expanduser(start)
            res = w.create_file_dialog(webview.FOLDER_DIALOG,
                                       directory=start if os.path.isdir(start) else "")
            path = res[0] if res else None
            if path and params.get("remember", True):
                self.core.remember(path)
            return {"path": path, "label": tilde(path) if path else "",
                    "recents": [{"path": p, "label": tilde(p)}
                                for p in self.core.cfg["recents"]]}
        if method == "open.folder":
            p = os.path.expanduser(params.get("path", ""))
            if os.path.isdir(p):
                if os.name == "nt":
                    os.startfile(p)                   # noqa: S606
                else:
                    import subprocess
                    subprocess.Popen(["xdg-open", p])
            return True
        raise ValueError("Unknown method: %s" % method)

    def _progress(self, i, total, rel):
        if self.window:
            self.window.evaluate_js(
                "window.__rbx_event('progress',%s)"
                % json.dumps({"i": i, "total": total, "path": rel}))


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv)
    folder = next((str(Path(os.path.expanduser(a)).resolve())
                   for a in argv[1:] if os.path.isdir(os.path.expanduser(a))), None)

    api = Api()
    api.start_folder = folder
    cfg = api.core.cfg.get("window", {})

    window = webview.create_window(
        "RebrandX",
        str(UI_DIR / "index.html"),
        js_api=api,
        width=int(cfg.get("width", 1180)),
        height=int(cfg.get("height", 760)),
        min_size=(880, 540),
        frameless=True,
        easy_drag=False,          # the header handles dragging itself
        background_color="#FAF9F5",
    )
    api.window = window

    def on_closing():
        try:
            api.core.save_window(window.width, window.height)
        except Exception:
            pass

    window.events.closing += on_closing
    try:
        webview.start(debug=bool(os.environ.get("REBRANDX_DEBUG")))
    except Exception as exc:
        # Almost always a missing WebView2 runtime. It ships with Windows 10
        # and 11, but not with Server images, stripped installs, or Wine --
        # so say what is wrong instead of exiting silently.
        _fatal(
            "RebrandX could not open its window.\n\n"
            "%s\n\n"
            "This usually means the Microsoft Edge WebView2 runtime is "
            "missing. Install the Evergreen Runtime from:\n\n"
            "https://developer.microsoft.com/microsoft-edge/webview2/\n\n"
            "The command line does not need it:  rbx OldName NewName PATH"
            % exc)
        return 3
    return 0


def _fatal(message: str) -> None:
    """Show the error in a dialog when there is no console to print to."""
    sys.stderr.write(message + "\n")
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "RebrandX", 0x10)
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
