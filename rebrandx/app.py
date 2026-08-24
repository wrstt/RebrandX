#!/usr/bin/python3
"""RebrandX on Linux: a GTK3 window hosting the WebKit-rendered UI.

The window is undecorated -- the title bar, folder pill and traffic-light
buttons in the design are drawn by the web layer and route back here through
the ``rbx`` message bridge for the real window operations.

Everything that isn't a window or a native dialog lives in core.py, shared
with the Windows build.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import traceback
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib, WebKit2, Gio  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rebrandx.core import Core, UI_DIR, APP_ID, tilde  # noqa: E402


class RebrandXWindow(Gtk.Window):
    def __init__(self, app: Gtk.Application, start_folder: str | None = None):
        super().__init__(application=app, title="RebrandX")
        self.core = Core()
        self.start_folder = start_folder

        win = self.core.cfg.get("window", {})
        self.set_default_size(int(win.get("width", 1180)), int(win.get("height", 760)))
        self.set_size_request(880, 540)
        self.set_decorated(False)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("rebrandx")
        self.connect("destroy", self._on_destroy)

        # rounded corners + drop shadow for the undecorated window
        self.set_app_paintable(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        css = Gtk.CssProvider()
        css.load_from_data(b"window { background: transparent; }")
        Gtk.StyleContext.add_provider_for_screen(
            screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        ucm = WebKit2.UserContentManager()
        ucm.register_script_message_handler("rbx")
        ucm.connect("script-message-received::rbx", self._on_message)

        self.web = WebKit2.WebView.new_with_user_content_manager(ucm)
        st = self.web.get_settings()
        st.set_allow_file_access_from_file_urls(True)
        st.set_allow_universal_access_from_file_urls(True)
        st.set_enable_developer_extras(bool(os.environ.get("REBRANDX_DEBUG")))
        st.set_enable_back_forward_navigation_gestures(False)
        self.web.set_background_color(Gdk.RGBA(0.98, 0.976, 0.961, 1.0))
        self.add(self.web)

        self.web.load_uri((UI_DIR / "index.html").as_uri())
        self.web.connect("load-changed", self._on_load)
        self.show_all()

    # -- lifecycle ---------------------------------------------------------
    def _on_destroy(self, *_):
        alloc = self.get_allocation()
        self.core.save_window(alloc.width, alloc.height)

    def _on_load(self, web, event):
        if event == WebKit2.LoadEvent.FINISHED:
            self._emit("boot", self.core.boot_payload(self.start_folder))

    # -- bridge ------------------------------------------------------------
    def _js(self, script: str) -> None:
        try:
            self.web.evaluate_javascript(script, -1, None, None, None, None, None)
        except (AttributeError, TypeError):
            self.web.run_javascript(script, None, None, None)

    def _emit(self, channel: str, payload) -> None:
        self._js("window.__rbx_event(%s,%s)" % (json.dumps(channel), json.dumps(payload)))

    def _reply(self, rid, payload=None, error=None) -> None:
        self._js("window.__rbx_reply(%s,%s,%s)" % (
            json.dumps(rid), json.dumps(payload), json.dumps(error)))

    def _on_message(self, manager, result):
        try:
            value = result.get_js_value() if hasattr(result, "get_js_value") else result
            # The UI posts a JSON *string*; older JSC builds only expose to_string().
            if hasattr(value, "is_string") and value.is_string():
                text = value.to_string()
            elif hasattr(value, "to_json"):
                text = value.to_json(0)
            else:
                text = value.to_string()
            msg = json.loads(text)
        except Exception:
            traceback.print_exc()
            return
        rid, method = msg.get("id"), msg.get("method", "")
        params = msg.get("params") or {}
        try:
            self._dispatch(rid, method, params)
        except Exception as exc:
            traceback.print_exc()
            if rid is not None:
                self._reply(rid, None, str(exc))

    def _dispatch(self, rid, method, params):
        # --- window controls (synchronous) ---
        if method == "window.minimize":
            self.iconify(); return self._reply(rid, True)
        if method == "window.maximize":
            self.unmaximize() if self.is_maximized() else self.maximize()
            return self._reply(rid, self.is_maximized())
        if method == "window.close":
            self.close(); return
        if method == "window.drag":
            self.begin_move_drag(1, int(params.get("x", 0)), int(params.get("y", 0)),
                                 Gtk.get_current_event_time())
            return self._reply(rid, True)
        if method == "window.resize":
            edges = {
                "n": Gdk.WindowEdge.NORTH, "s": Gdk.WindowEdge.SOUTH,
                "e": Gdk.WindowEdge.EAST, "w": Gdk.WindowEdge.WEST,
                "ne": Gdk.WindowEdge.NORTH_EAST, "nw": Gdk.WindowEdge.NORTH_WEST,
                "se": Gdk.WindowEdge.SOUTH_EAST, "sw": Gdk.WindowEdge.SOUTH_WEST,
            }
            self.begin_resize_drag(edges.get(params.get("edge", "se"), Gdk.WindowEdge.SOUTH_EAST),
                                   1, int(params.get("x", 0)), int(params.get("y", 0)),
                                   Gtk.get_current_event_time())
            return self._reply(rid, True)

        # --- native dialogs ---
        if method == "pick.folder":
            return self._pick_folder(rid, params)
        if method == "open.folder":
            path = os.path.expanduser(params.get("path", ""))
            if os.path.isdir(path):
                Gio.AppInfo.launch_default_for_uri("file://" + path, None)
            return self._reply(rid, True)

        # --- everything else is shared with the Windows build ---
        self._run_bg(rid, method, params)

    # -- helpers -----------------------------------------------------------
    def _pick_folder(self, rid, params):
        dlg = Gtk.FileChooserDialog(
            title=params.get("title", "Choose a folder"), transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        "_Select", Gtk.ResponseType.OK)
        dlg.set_create_folders(bool(params.get("createFolders")))
        start = os.path.expanduser(params.get("start") or str(Path.home()))
        if os.path.isdir(start):
            dlg.set_current_folder(start)
        resp = dlg.run()
        path = dlg.get_filename() if resp == Gtk.ResponseType.OK else None
        dlg.destroy()
        if path and params.get("remember", True):
            self.core.remember(path)
        self._reply(rid, {"path": path, "label": tilde(path) if path else "",
                          "recents": [{"path": p, "label": tilde(p)}
                                      for p in self.core.cfg["recents"]]})

    def _run_bg(self, rid, method, params):
        def progress(i, total, rel):
            GLib.idle_add(self._emit, "progress", {"i": i, "total": total, "path": rel})

        def work():
            try:
                handled, out = self.core.handle(method, params, progress)
                if not handled:
                    raise ValueError("Unknown method: %s" % method)
                GLib.idle_add(self._reply, rid, out, None)
            except Exception as exc:
                traceback.print_exc()
                GLib.idle_add(self._reply, rid, None, str(exc))

        threading.Thread(target=work, daemon=True).start()


class RebrandXApp(Gtk.Application):
    def __init__(self, folder=None):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.folder = folder
        self.win = None
        self.connect("command-line", self._cmdline)

    def _cmdline(self, app, cl):
        folder = self.folder
        for a in cl.get_arguments()[1:]:
            if os.path.isdir(os.path.expanduser(a)):
                folder = str(Path(os.path.expanduser(a)).resolve())
        self.activate_with(folder)
        return 0

    def activate_with(self, folder):
        if not self.win:
            self.win = RebrandXWindow(self, folder)
        else:
            if folder:
                self.win._emit("open-folder", {"path": folder, "label": tilde(folder)})
            self.win.present()


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv)
    folder, rest = None, [argv[0]]
    for a in argv[1:]:
        if os.path.isdir(os.path.expanduser(a)):
            folder = str(Path(os.path.expanduser(a)).resolve())
        else:
            rest.append(a)
    return RebrandXApp(folder).run(rest)


if __name__ == "__main__":
    sys.exit(main())
