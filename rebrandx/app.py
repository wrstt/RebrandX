#!/usr/bin/python3
"""RebrandX desktop shell: a GTK3 window hosting the WebKit-rendered UI.

The window is undecorated -- the title bar, folder pill and traffic-light
buttons in the design are drawn by the web layer, and route back here through
the ``rbx`` message bridge for the real window operations.
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
from rebrandx import engine  # noqa: E402
from rebrandx.engine import Options, ApplyError  # noqa: E402

APP_ID = "dev.rebrandx.RebrandX"
UI_DIR = Path(__file__).resolve().parent / "ui"
CONFIG_DIR = Path(GLib.get_user_config_dir()) / "rebrandx"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "recents": [],
    "settings": {"confirmBeforeApply": True, "showLineNumbers": True,
                 "backup": True, "copyIgnored": False},
    "window": {"width": 1180, "height": 760},
}


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        disk = json.loads(CONFIG_FILE.read_text())
        for k, v in disk.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    except Exception:
        pass
    return cfg


def save_config(cfg: dict) -> None:
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass


def tilde(p: str) -> str:
    home = str(Path.home())
    return "~" + p[len(home):] if p.startswith(home) else p


class RebrandXWindow(Gtk.Window):
    def __init__(self, app: Gtk.Application, start_folder: str | None = None):
        super().__init__(application=app, title="RebrandX")
        self.cfg = load_config()
        self.last_manifest: dict | None = None
        self._scan_token = 0

        w = int(self.cfg["window"].get("width", 1180))
        h = int(self.cfg["window"].get("height", 760))
        self.set_default_size(w, h)
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

        self.start_folder = start_folder
        self.show_all()

    # -- lifecycle ---------------------------------------------------------
    def _on_destroy(self, *_):
        alloc = self.get_allocation()
        self.cfg["window"] = {"width": alloc.width, "height": alloc.height}
        save_config(self.cfg)

    def _on_load(self, web, event):
        if event != WebKit2.LoadEvent.FINISHED:
            return
        # Never open anything on its own. Only a folder passed explicitly on
        # the command line (the Files right-click entry) opens at launch --
        # no home directory, no last-used folder, no fallback.
        folder = self.start_folder or ""
        self._emit("boot", {
            "source": folder,
            "sourceLabel": tilde(folder) if folder else "",
            "recents": [{"path": p, "label": tilde(p)} for p in self.cfg["recents"]],
            "settings": self.cfg["settings"],
            "home": str(Path.home()),
            "defaults": {
                "excludes": {".git/": True, "node_modules/": True, "*.lock": True},
                "projectGlobs": dict(engine.PROJECT_FILE_GLOBS),
            },
        })

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
        rid = msg.get("id")
        method = msg.get("method", "")
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
            if self.is_maximized():
                self.unmaximize()
            else:
                self.maximize()
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
            edge = edges.get(params.get("edge", "se"), Gdk.WindowEdge.SOUTH_EAST)
            self.begin_resize_drag(edge, 1, int(params.get("x", 0)),
                                   int(params.get("y", 0)), Gtk.get_current_event_time())
            return self._reply(rid, True)

        # --- dialogs ---
        if method == "pick.folder":
            return self._pick_folder(rid, params)
        if method == "open.folder":
            path = os.path.expanduser(params.get("path", ""))
            if os.path.isdir(path):
                Gio.AppInfo.launch_default_for_uri("file://" + path, None)
            return self._reply(rid, True)

        # --- config ---
        if method == "config.set":
            self.cfg["settings"].update(params.get("settings") or {})
            save_config(self.cfg)
            return self._reply(rid, self.cfg["settings"])
        if method == "config.remember":
            self._remember(params.get("path", ""))
            return self._reply(rid, [{"path": p, "label": tilde(p)} for p in self.cfg["recents"]])

        # --- engine (threaded) ---
        if method == "scan":
            return self._run_bg(rid, self._do_scan, params)
        if method == "diff":
            return self._run_bg(rid, self._do_diff, params)
        if method == "apply":
            return self._run_bg(rid, self._do_apply, params)
        if method == "revert":
            return self._run_bg(rid, self._do_revert, params)
        if method == "suggest.dest":
            return self._reply(rid, self._suggest_dest(params))

        self._reply(rid, None, "Unknown method: %s" % method)

    # -- helpers -----------------------------------------------------------
    def _remember(self, path: str) -> None:
        if not path or not os.path.isdir(path):
            return
        rec = [p for p in self.cfg["recents"] if p != path]
        rec.insert(0, path)
        self.cfg["recents"] = rec[:6]
        save_config(self.cfg)

    def _suggest_dest(self, params) -> str:
        src = os.path.expanduser(params.get("source", ""))
        find, rep = params.get("find", ""), params.get("replace", "")
        if not src:
            return ""
        p = Path(src)
        name = p.name
        if find and rep:
            r = engine.Rules(find, rep, case_sensitive=params.get("caseSensitive", True),
                             match_variants=params.get("matchVariants", True))
            if r.ok:
                name = r.sub(name)
        if name == p.name:
            name = p.name + "-rebranded"
        return tilde(str(p.parent / name))

    def _pick_folder(self, rid, params):
        dlg = Gtk.FileChooserDialog(
            title=params.get("title", "Choose a folder"), transient_for=self,
            action=Gtk.FileChooserAction.SELECT_FOLDER)
        dlg.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                        "_Select", Gtk.ResponseType.OK)
        if params.get("createFolders"):
            dlg.set_action(Gtk.FileChooserAction.SELECT_FOLDER)
            dlg.set_create_folders(True)
        start = os.path.expanduser(params.get("start") or str(Path.home()))
        if os.path.isdir(start):
            dlg.set_current_folder(start)
        resp = dlg.run()
        path = dlg.get_filename() if resp == Gtk.ResponseType.OK else None
        dlg.destroy()
        if path and params.get("remember", True):
            self._remember(path)
        self._reply(rid, {"path": path, "label": tilde(path) if path else "",
                          "recents": [{"path": p, "label": tilde(p)} for p in self.cfg["recents"]]})

    def _run_bg(self, rid, fn, params):
        def work():
            try:
                out = fn(params)
                GLib.idle_add(self._reply, rid, out, None)
            except Exception as exc:
                traceback.print_exc()
                GLib.idle_add(self._reply, rid, None, str(exc))
        threading.Thread(target=work, daemon=True).start()

    # -- engine calls ------------------------------------------------------
    def _do_scan(self, params):
        opts = Options.from_dict(params.get("opts") or {})
        res = engine.scan(params.get("source", ""), opts)
        r = opts.rules()
        return {
            "root": res.root, "rootLabel": tilde(res.root),
            "entries": res.entries,
            "totals": {"filesChanged": res.files_changed,
                       "replacements": res.replacements,
                       "renames": res.renames, "removed": res.removed,
                       "dropped": res.dropped},
            "truncated": res.truncated, "error": res.error,
            "regexError": res.regex_error, "chips": r.chips(),
            "elapsed": round(res.elapsed, 3),
        }

    def _do_diff(self, params):
        opts = Options.from_dict(params.get("opts") or {})
        root = Path(os.path.expanduser(params.get("source", ""))).resolve()
        rel = params.get("path", "")
        d = engine.diff_file(root, rel, opts.rules(), opts, want_rows=True)
        return {"path": d.path, "rows": d.rows, "count": d.count,
                "removed": d.removed, "newPath": d.new_path,
                "renamed": d.renamed, "binary": d.binary, "tooBig": d.too_big,
                "skippedFile": d.skipped_file}

    def _do_apply(self, params):
        opts = Options.from_dict(params.get("opts") or {})
        opts.copy_ignored = bool(params.get("copyIgnored"))
        mode = params.get("mode", "copy")
        dest = params.get("dest", "")

        def prog(i, total, rel):
            GLib.idle_add(self._emit, "progress",
                          {"i": i, "total": total, "path": rel})

        man = engine.apply(params.get("source", ""), opts, mode=mode, dest=dest,
                           backup=bool(params.get("backup", True)), progress=prog)
        self.last_manifest = man
        if mode == "copy":
            self._remember(man["dest"])
        return {"files": man.get("files", 0), "dropped": man.get("dropped", 0),
                "mode": mode,
                "dest": man.get("dest", ""), "destLabel": tilde(man.get("dest", "")),
                "renames": len(man.get("renames", [])),
                "backup": man.get("backup")}

    def _do_revert(self, params):
        if not self.last_manifest:
            raise ApplyError("Nothing to revert in this session.")
        msg = engine.revert(self.last_manifest)
        self.last_manifest = None
        return {"message": msg}


class RebrandXApp(Gtk.Application):
    def __init__(self, folder=None):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.folder = folder
        self.win = None
        self.connect("command-line", self._cmdline)

    def _cmdline(self, app, cl):
        args = cl.get_arguments()[1:]
        folder = self.folder
        for a in args:
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
    folder = None
    rest = [argv[0]]
    for a in argv[1:]:
        if os.path.isdir(os.path.expanduser(a)):
            folder = str(Path(os.path.expanduser(a)).resolve())
        else:
            rest.append(a)
    app = RebrandXApp(folder)
    return app.run(rest)


if __name__ == "__main__":
    sys.exit(main())
