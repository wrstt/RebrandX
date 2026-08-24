"""Platform-independent half of the RebrandX app.

Everything the UI asks for that isn't a window or a native dialog lives here,
so the GTK shell (Linux) and the WebView2 shell (Windows) share one
implementation and one set of behaviours.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from rebrandx import engine
from rebrandx.engine import Options, ApplyError  # noqa: F401  (re-exported)

APP_ID = "dev.rebrandx.RebrandX"
UI_DIR = Path(__file__).resolve().parent / "ui"

DEFAULT_CONFIG = {
    "recents": [],
    "settings": {"confirmBeforeApply": True, "showLineNumbers": True,
                 "backup": True, "copyIgnored": False},
    "window": {"width": 1180, "height": 760},
}


def config_dir() -> Path:
    """Per-user config location, following each platform's convention."""
    if os.name == "nt":
        base = os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")
        return Path(base) / "RebrandX"
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "rebrandx"


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        disk = json.loads((config_dir() / "config.json").read_text())
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
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "config.json").write_text(json.dumps(cfg, indent=2))
    except OSError:
        pass


def tilde(p: str) -> str:
    """Shorten a path for display: ~/dev/x on unix, %USERPROFILE% stays whole."""
    if not p:
        return ""
    home = str(Path.home())
    if p.startswith(home):
        return ("~" + p[len(home):]).replace("\\", "/") if os.name != "nt" \
            else "~" + p[len(home):]
    return p


class Core:
    """Handles every UI request that isn't window- or dialog-related."""

    def __init__(self):
        self.cfg = load_config()
        self.last_manifest: dict | None = None

    # -- boot --------------------------------------------------------------
    def boot_payload(self, start_folder: str | None) -> dict:
        # Never open anything on its own -- only an explicitly passed folder.
        folder = start_folder or ""
        return {
            "source": folder,
            "sourceLabel": tilde(folder) if folder else "",
            "recents": [{"path": p, "label": tilde(p)} for p in self.cfg["recents"]],
            "settings": self.cfg["settings"],
            "home": str(Path.home()),
            "platform": "windows" if os.name == "nt" else "linux",
            "defaults": {
                "excludes": {".git/": True, "node_modules/": True, "*.lock": True},
                "projectGlobs": dict(engine.PROJECT_FILE_GLOBS),
            },
        }

    # -- recents -----------------------------------------------------------
    def remember(self, path: str) -> list[dict]:
        if path and os.path.isdir(path):
            rec = [p for p in self.cfg["recents"] if p != path]
            rec.insert(0, path)
            self.cfg["recents"] = rec[:6]
            save_config(self.cfg)
        return [{"path": p, "label": tilde(p)} for p in self.cfg["recents"]]

    def set_settings(self, settings: dict) -> dict:
        self.cfg["settings"].update(settings or {})
        save_config(self.cfg)
        return self.cfg["settings"]

    def save_window(self, width: int, height: int) -> None:
        self.cfg["window"] = {"width": width, "height": height}
        save_config(self.cfg)

    # -- engine ------------------------------------------------------------
    def suggest_dest(self, params: dict) -> str:
        src = os.path.expanduser(params.get("source", ""))
        if not src:
            return ""
        p = Path(src)
        name = p.name
        find, rep = params.get("find", ""), params.get("replace", "")
        if find and rep:
            r = engine.Rules(find, rep,
                             case_sensitive=params.get("caseSensitive", True),
                             match_variants=params.get("matchVariants", True))
            if r.ok:
                name = r.sub(name)
        if name == p.name:
            name = p.name + "-rebranded"
        return tilde(str(p.parent / name))

    def scan(self, params: dict) -> dict:
        opts = Options.from_dict(params.get("opts") or {})
        res = engine.scan(params.get("source", ""), opts)
        return {
            "root": res.root, "rootLabel": tilde(res.root),
            "entries": res.entries,
            "totals": {"filesChanged": res.files_changed,
                       "replacements": res.replacements,
                       "renames": res.renames, "removed": res.removed,
                       "dropped": res.dropped},
            "truncated": res.truncated, "error": res.error,
            "regexError": res.regex_error, "chips": opts.rules().chips(),
            "elapsed": round(res.elapsed, 3),
        }

    def diff(self, params: dict) -> dict:
        opts = Options.from_dict(params.get("opts") or {})
        root = Path(os.path.expanduser(params.get("source", ""))).resolve()
        d = engine.diff_file(root, params.get("path", ""), opts.rules(), opts,
                             want_rows=True)
        return {"path": d.path, "rows": d.rows, "count": d.count,
                "removed": d.removed, "newPath": d.new_path,
                "renamed": d.renamed, "binary": d.binary, "tooBig": d.too_big,
                "skippedFile": d.skipped_file}

    def apply(self, params: dict, progress=None) -> dict:
        opts = Options.from_dict(params.get("opts") or {})
        opts.copy_ignored = bool(params.get("copyIgnored"))
        mode = params.get("mode", "copy")
        man = engine.apply(params.get("source", ""), opts, mode=mode,
                           dest=params.get("dest", ""),
                           backup=bool(params.get("backup", True)),
                           progress=progress)
        self.last_manifest = man
        if mode == "copy":
            self.remember(man["dest"])
        return {"files": man.get("files", 0), "dropped": man.get("dropped", 0),
                "mode": mode, "dest": man.get("dest", ""),
                "destLabel": tilde(man.get("dest", "")),
                "renames": len(man.get("renames", [])),
                "backup": man.get("backup")}

    def revert(self, params: dict) -> dict:
        if not self.last_manifest:
            raise ApplyError("Nothing to revert in this session.")
        msg = engine.revert(self.last_manifest)
        self.last_manifest = None
        return {"message": msg}

    # -- shared dispatch ---------------------------------------------------
    def handle(self, method: str, params: dict, progress=None):
        """Returns (handled, result). Window/dialog calls return handled=False."""
        if method == "scan":
            return True, self.scan(params)
        if method == "diff":
            return True, self.diff(params)
        if method == "apply":
            return True, self.apply(params, progress)
        if method == "revert":
            return True, self.revert(params)
        if method == "suggest.dest":
            return True, self.suggest_dest(params)
        if method == "config.set":
            return True, self.set_settings(params.get("settings") or {})
        if method == "config.remember":
            return True, self.remember(params.get("path", ""))
        return False, None
