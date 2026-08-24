"""RebrandX rebrand engine.

Pure-stdlib. Scans a folder tree, computes the rebrand preview (per-file
replacement counts, renames, removed lines, line diffs) and applies it either
in place (with an optional backup) or as a transformed copy into a new folder.

Nothing in here imports GTK -- the CLI and the GUI share this module.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import shutil
import stat
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Iterable

BACKUP_DIRNAME = ".rebrandx-backup"
MANIFEST_NAME = "manifest.json"

# Files larger than this are copied/renamed but never content-scanned.
DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024
# Hard ceiling on tree size so a mistaken pick of ~ or / cannot hang the UI.
DEFAULT_MAX_ENTRIES = 40000

REPO_HOST_RE = re.compile(r'((github|gitlab|bitbucket)\.com|"repository")', re.I)

# Files that carry the *previous* project's identity rather than its code:
# licences, history, governance and forge configuration. Removing these is
# opt-in ("Remove old project files") and always backed up.
PROJECT_FILE_GLOBS = {
    "LICENSE*": True, "LICENCE*": True, "COPYING*": True, "NOTICE*": True,
    "CHANGELOG*": True, "CHANGES*": True, "HISTORY*": True,
    "RELEASES*": True, "RELEASE-NOTES*": True,
    "AUTHORS*": True, "CONTRIBUTORS*": True, "MAINTAINERS*": True,
    "CODE_OF_CONDUCT*": True, "CONTRIBUTING*": True,
    "SECURITY*": True, "SUPPORT*": True, "CITATION*": True,
    "CODEOWNERS": True, "FUNDING.yml": True, ".all-contributorsrc": True,
    ".github/": True, ".gitlab/": True, ".circleci/": True,
    ".travis.yml": True, "appveyor.yml": True,
}


# --------------------------------------------------------------------------
# rules
# --------------------------------------------------------------------------

def _cap(s: str) -> str:
    return s[:1].upper() + s[1:] if s else s


def _dollar_to_backref(rep: str) -> str:
    """Translate JS-style $1 / $& groups into Python \\1 / \\g<0>."""
    out = []
    i = 0
    while i < len(rep):
        c = rep[i]
        if c == "\\":
            out.append("\\\\")
            i += 1
        elif c == "$" and i + 1 < len(rep):
            nxt = rep[i + 1]
            if nxt == "$":
                out.append("$")
                i += 2
            elif nxt == "&":
                out.append("\\g<0>")
                i += 2
            elif nxt.isdigit():
                j = i + 1
                while j < len(rep) and rep[j].isdigit():
                    j += 1
                out.append("\\g<%s>" % rep[i + 1:j])
                i = j
            elif nxt == "{":
                j = rep.find("}", i + 2)
                if j != -1:
                    out.append("\\g<%s>" % rep[i + 2:j])
                    i = j + 1
                else:
                    out.append("$")
                    i += 1
            else:
                out.append("$")
                i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


class Rules:
    """The find/replace mapping, compiled once per scan.

    Literal mode compiles every case variant into ONE alternation so a single
    pass does all the work -- this avoids the classic bug where replacing
    ``task`` -> ``taskly`` and then a second variant re-hits its own output.
    """

    def __init__(self, find: str, replace: str, *, case_sensitive: bool = True,
                 match_variants: bool = True, use_regex: bool = False):
        self.find = find or ""
        self.replace = replace or ""
        self.case_sensitive = case_sensitive
        self.match_variants = match_variants
        self.use_regex = use_regex
        self.error: str | None = None
        self._re: re.Pattern | None = None
        self._reps: dict[str, str] = {}
        self._regex_rep = ""
        self._literals: list[str] = []
        self._compile()

    # -- construction ------------------------------------------------------
    def _compile(self) -> None:
        if not self.find:
            return
        if self.use_regex:
            try:
                self._re = re.compile(self.find, 0 if self.case_sensitive else re.I)
            except re.error as exc:
                self.error = str(exc)
                self._re = None
                return
            self._regex_rep = _dollar_to_backref(self.replace)
            return

        if not self.case_sensitive:
            # Wrapped in a named group so _expand() can find its replacement,
            # exactly like the case-variant alternation below.
            self._literals = [self.find]
            self._re = re.compile("(?P<v0>%s)" % re.escape(self.find), re.I)
            self._reps = {"v0": self.replace}
            return

        pairs = [(self.find, self.replace)]
        if self.match_variants:
            pairs += [
                (_cap(self.find), _cap(self.replace)),
                (self.find.upper(), self.replace.upper()),
                (self.find.lower(), self.replace.lower()),
            ]
        seen: dict[str, str] = {}
        for a, b in pairs:
            if a and a not in seen:
                seen[a] = b
        # Longest alternatives first so a variant can never be shadowed by a
        # shorter one that happens to be a prefix of it.
        ordered = sorted(seen.items(), key=lambda kv: -len(kv[0]))
        self._literals = [a for a, _ in ordered]
        parts = []
        for idx, (a, b) in enumerate(ordered):
            name = "v%d" % idx
            self._reps[name] = b
            parts.append("(?P<%s>%s)" % (name, re.escape(a)))
        self._re = re.compile("|".join(parts))

    # -- use ---------------------------------------------------------------
    @property
    def ok(self) -> bool:
        return self._re is not None

    def _expand(self, m: re.Match) -> str:
        for name, rep in self._reps.items():
            try:
                if m.group(name) is not None:
                    return rep
            except (IndexError, re.error):
                continue
        return m.group(0)

    def sub(self, s: str) -> str:
        if not self._re:
            return s
        if self.use_regex:
            try:
                return self._re.sub(self._regex_rep, s)
            except re.error:
                return s
        return self._re.sub(self._expand, s)

    def count(self, s: str) -> int:
        if not self._re:
            return 0
        return sum(1 for _ in self._re.finditer(s))

    def may_hit(self, s: str) -> bool:
        """Cheap pre-filter: can this text possibly contain a match?"""
        if not self._re:
            return False
        if self.use_regex:
            return True
        if not self.case_sensitive:
            return self.find.lower() in s.lower()
        return any(lit in s for lit in self._literals)

    def chips(self) -> list[str]:
        """Variant preview chips for the rules panel."""
        if not self.find:
            return []
        if self.use_regex:
            if not self.ok:
                return ["invalid regex"]
            return ["/%s/%s → %s" % (self.find, "" if self.case_sensitive else "i", self.replace)]
        if not self.case_sensitive:
            return ["any case of %s → %s" % (self.find, self.replace)]
        if not self.match_variants:
            return ["%s → %s" % (self.find, self.sub(self.find))]
        seen, out = set(), []
        for v in (self.find, _cap(self.find), self.find.upper(), self.find.lower()):
            if v and v not in seen:
                seen.add(v)
                out.append("%s → %s" % (v, self.sub(v)))
        return out


# --------------------------------------------------------------------------
# options
# --------------------------------------------------------------------------

@dataclass
class Options:
    find: str = ""
    replace: str = ""
    case_sensitive: bool = True
    match_variants: bool = True
    use_regex: bool = False
    rename_files: bool = True
    replace_contents: bool = True
    strip_meta: bool = False
    excludes: dict[str, bool] = field(default_factory=lambda: {
        ".git/": True, "node_modules/": True, "*.lock": True})
    skipped_files: set[str] = field(default_factory=set)
    skipped_lines: set[str] = field(default_factory=set)   # "path::lineno"
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_entries: int = DEFAULT_MAX_ENTRIES
    copy_ignored: bool = False
    strip_project_files: bool = False
    project_globs: dict[str, bool] = field(
        default_factory=lambda: dict(PROJECT_FILE_GLOBS))

    def rules(self) -> Rules:
        return Rules(self.find, self.replace,
                     case_sensitive=self.case_sensitive,
                     match_variants=self.match_variants,
                     use_regex=self.use_regex)

    @classmethod
    def from_dict(cls, d: dict) -> "Options":
        o = cls()
        for k, v in (d or {}).items():
            key = re.sub(r"(?<!^)(?=[A-Z])", "_", k).lower()
            if not hasattr(o, key):
                continue
            if key in ("skipped_files", "skipped_lines"):
                v = set(v or [])
            if key == "project_globs" and not v:
                v = dict(PROJECT_FILE_GLOBS)
            setattr(o, key, v)
        return o


def _active_globs(excludes: dict[str, bool]) -> list[str]:
    return [p for p, on in (excludes or {}).items() if on]


def is_project_file(rel: str, is_dir: bool, opts: "Options") -> bool:
    """True when `rel` (or an ancestor) is one of the old project's own files.

    An ancestor match counts, so everything under `.github/` goes with it.
    A file the user chose to keep -- itself or via an ancestor -- never does.
    """
    if not opts.strip_project_files:
        return False
    active = [g for g, on in (opts.project_globs or {}).items() if on]
    if not any(matches_glob(rel, is_dir, g) for g in active):
        return False
    parts = rel.split("/")
    for i in range(1, len(parts) + 1):
        if "/".join(parts[:i]) in opts.skipped_files:
            return False
    return True


def matches_glob(rel: str, is_dir: bool, pattern: str) -> bool:
    """Match a path against one ignore pattern.

    ``name/`` matches a directory (and everything under it) anywhere in the
    tree; anything else is a normal glob tested against both the basename and
    the full relative path.
    """
    pat = pattern.strip()
    if not pat:
        return False
    if pat.endswith("/"):
        base = pat[:-1]
        segs = rel.split("/")
        if is_dir and segs and fnmatch.fnmatch(segs[-1], base):
            return True
        return any(fnmatch.fnmatch(s, base) for s in segs[:-1])
    name = rel.split("/")[-1]
    return fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel, pat)


# --------------------------------------------------------------------------
# text io
# --------------------------------------------------------------------------

@dataclass
class TextFile:
    text: str
    newline: str
    trailing_newline: bool
    encoding: str = "utf-8"


def read_text(path: Path, limit: int) -> TextFile | None:
    """Return decoded text, or None when the file is binary/oversized."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > limit:
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw[:8192]:
        return None
    for enc in ("utf-8", "utf-8-sig"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        return None
    newline = "\r\n" if "\r\n" in text else "\n"
    if newline == "\r\n":
        text = text.replace("\r\n", "\n")
    trailing = text.endswith("\n")
    if trailing:
        text = text[:-1]
    return TextFile(text=text, newline=newline, trailing_newline=trailing, encoding=enc)


def join_lines(lines: list[str], tf: TextFile) -> str:
    out = tf.newline.join(lines)
    if tf.trailing_newline:
        out += tf.newline
    return out


# --------------------------------------------------------------------------
# per-file diff
# --------------------------------------------------------------------------

@dataclass
class FileDiff:
    path: str
    rows: list[dict]
    count: int = 0
    removed: int = 0
    new_path: str = ""
    renamed: bool = False
    skipped_file: bool = False
    binary: bool = False
    too_big: bool = False


def _is_repo_line(line: str, opts: Options) -> bool:
    if not opts.strip_meta or not opts.find:
        return False
    if not REPO_HOST_RE.search(line):
        return False
    return opts.find.lower() in line.lower()


def diff_path(rel: str, rules: Rules, opts: Options, skipped_file: bool) -> tuple[str, bool]:
    """Apply rename rules to every segment of a relative path."""
    if not opts.rename_files or skipped_file or not rules.ok:
        return rel, False
    segs = rel.split("/")
    new = "/".join(rules.sub(s) for s in segs)
    return new, new != rel


def diff_file(root: Path, rel: str, rules: Rules, opts: Options, *,
              want_rows: bool = True) -> FileDiff:
    skipped_file = rel in opts.skipped_files
    new_path, renamed = diff_path(rel, rules, opts, skipped_file)
    d = FileDiff(path=rel, rows=[], new_path=new_path, renamed=renamed,
                 skipped_file=skipped_file)

    # Nothing to look for -> don't touch the disk at all. Without this,
    # merely listing a folder reads every file in it.
    if not rules.ok:
        return d

    full = root / rel
    try:
        size = full.stat().st_size
    except OSError:
        return d
    if size > opts.max_file_bytes:
        d.too_big = True
        return d

    tf = read_text(full, opts.max_file_bytes)
    if tf is None:
        d.binary = True
        return d

    scanning = rules.ok and not skipped_file
    # Fast path: file cannot contain a hit and no repo-line stripping is on.
    if not want_rows and scanning and not opts.strip_meta:
        if not rules.may_hit(tf.text):
            return d

    lines = tf.text.split("\n")
    for i, line in enumerate(lines):
        skip = ("%s::%d" % (rel, i)) in opts.skipped_lines
        if not skipped_file and _is_repo_line(line, opts):
            if want_rows:
                d.rows.append({"kind": "pair", "i": i, "old": line,
                               "new": None, "skip": skip})
            if not skip:
                d.removed += 1
            continue
        new_line = rules.sub(line) if (opts.replace_contents and scanning) else line
        if new_line != line:
            if want_rows:
                d.rows.append({"kind": "pair", "i": i, "old": line,
                               "new": new_line, "skip": skip})
            if not skip:
                d.count += rules.count(line)
        elif want_rows:
            d.rows.append({"kind": "same", "i": i, "text": line})
    return d


def rewrite_text(root: Path, rel: str, rules: Rules, opts: Options) -> str | None:
    """Produce the final content for a file, or None if it is unchanged."""
    skipped_file = rel in opts.skipped_files
    tf = read_text(root / rel, opts.max_file_bytes)
    if tf is None:
        return None
    scanning = rules.ok and not skipped_file
    if not scanning:
        return None
    if not opts.strip_meta and not rules.may_hit(tf.text):
        return None

    out: list[str] = []
    changed = False
    for i, line in enumerate(tf.text.split("\n")):
        skip = ("%s::%d" % (rel, i)) in opts.skipped_lines
        if not skipped_file and _is_repo_line(line, opts):
            if skip:
                out.append(line)
            else:
                changed = True          # drop the line entirely
            continue
        if skip or not opts.replace_contents:
            out.append(line)
            continue
        new_line = rules.sub(line)
        if new_line != line:
            changed = True
        out.append(new_line)
    if not changed:
        return None
    return join_lines(out, tf)


# --------------------------------------------------------------------------
# scanning
# --------------------------------------------------------------------------

@dataclass
class ScanResult:
    root: str
    entries: list[dict]
    files_changed: int = 0
    replacements: int = 0
    renames: int = 0
    removed: int = 0
    dropped: int = 0
    truncated: bool = False
    error: str | None = None
    regex_error: str | None = None
    elapsed: float = 0.0


def walk(root: Path, opts: Options) -> Iterable[tuple[str, bool, int, str | None]]:
    """Yield (rel_path, is_dir, depth, matched_ignore_glob) depth-first."""
    globs = _active_globs(opts.excludes)
    all_globs = list((opts.excludes or {}).keys())
    count = 0

    def flag_for(rel: str, is_dir: bool) -> str | None:
        for g in all_globs:
            if matches_glob(rel, is_dir, g):
                return g
        return None

    def rec(d: Path, rel_base: str, depth: int):
        nonlocal count
        try:
            items = sorted(os.scandir(d), key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
        except OSError:
            return
        for e in items:
            if count >= opts.max_entries:
                return
            rel = "%s/%s" % (rel_base, e.name) if rel_base else e.name
            if rel_base == "" and e.name == BACKUP_DIRNAME:
                continue
            try:
                is_dir = e.is_dir(follow_symlinks=False)
                is_link = e.is_symlink()
            except OSError:
                continue
            if is_link:
                continue
            flag = flag_for(rel, is_dir)
            hidden_by = flag if (flag in globs) else None
            count += 1
            yield_val = (rel, is_dir, depth, flag)
            yield yield_val
            if is_dir and not hidden_by:
                yield from rec(d / e.name, rel, depth + 1)

    yield from rec(root, "", 0)


def scan(root_str: str, opts: Options, *, progress: Callable[[int], None] | None = None) -> ScanResult:
    started = time.time()
    root = Path(os.path.expanduser(root_str)).resolve()
    res = ScanResult(root=str(root), entries=[])
    if not root.is_dir():
        res.error = "Not a folder: %s" % root
        return res

    rules = opts.rules()
    if opts.use_regex and opts.find and not rules.ok:
        res.regex_error = rules.error

    globs = _active_globs(opts.excludes)
    n = 0
    for rel, is_dir, depth, flag in walk(root, opts):
        n += 1
        if progress and n % 500 == 0:
            progress(n)
        excluded = bool(flag and flag in globs)
        drop = (not excluded) and is_project_file(rel, is_dir, opts)
        item = {
            "path": rel, "dir": is_dir, "depth": depth,
            "flag": flag, "excluded": excluded,
            "count": 0, "removed": 0, "newPath": rel,
            "renamed": False, "binary": False, "tooBig": False,
            "skipped": rel in opts.skipped_files,
            "drop": drop,
        }
        if drop:
            res.entries.append(item)
            if not is_dir:
                res.dropped += 1
                res.files_changed += 1
            continue
        if is_dir:
            if not excluded:
                np, rn = diff_path(rel, rules, opts, rel in opts.skipped_files)
                item["newPath"], item["renamed"] = np, rn
                if rn:
                    item["winWarn"] = windows_unsafe(np.rsplit("/", 1)[-1])
            res.entries.append(item)
            continue
        if excluded:
            res.entries.append(item)
            continue

        d = diff_file(root, rel, rules, opts, want_rows=False)
        item.update(count=d.count, removed=d.removed, newPath=d.new_path,
                    renamed=d.renamed, binary=d.binary, tooBig=d.too_big)
        if d.renamed:
            item["winWarn"] = windows_unsafe(d.new_path.rsplit("/", 1)[-1])
        res.entries.append(item)

        if d.count or d.removed or d.renamed:
            res.files_changed += 1
        res.replacements += d.count
        res.removed += d.removed
        if d.renamed:
            res.renames += 1

    # Folder renames count too -- they move every file beneath them.
    for it in res.entries:
        if it["dir"] and it["renamed"] and not it["excluded"]:
            res.renames += 1

    res.truncated = n >= opts.max_entries
    res.elapsed = time.time() - started
    return res


# --------------------------------------------------------------------------
# apply / revert
# --------------------------------------------------------------------------

class ApplyError(Exception):
    pass


UNSAFE_ROOTS = {"/", "/home", "/usr", "/etc", "/var", "/boot", "/bin", "/sbin", "/opt", "/root"}


def _guard_root(root: Path) -> None:
    p = str(root)
    if p in UNSAFE_ROOTS or root == Path.home():
        raise ApplyError("Refusing to rebrand %s -- pick a project folder." % p)


def _plan(root: Path, opts: Options, rules: Rules):
    """Collect (rel, is_dir, excluded, new_rel, drop) for the whole tree."""
    globs = _active_globs(opts.excludes)
    out = []
    for rel, is_dir, depth, flag in walk(root, opts):
        excluded = bool(flag and flag in globs)
        drop = (not excluded) and is_project_file(rel, is_dir, opts)
        new_rel, _ = diff_path(rel, rules, opts, rel in opts.skipped_files) if not excluded else (rel, False)
        out.append((rel, is_dir, excluded, new_rel, drop))
    return out


def _drop_roots(plan) -> list[str]:
    """The top-most paths marked for removal (so `.github/` goes once, whole)."""
    dropped = [rel for rel, _d, _e, _n, drop in plan if drop]
    roots = []
    for rel in sorted(dropped, key=lambda r: r.count("/")):
        if not any(rel == r or rel.startswith(r + "/") for r in roots):
            roots.append(rel)
    return roots


def apply_copy(root: Path, dest: Path, opts: Options, rules: Rules,
               progress: Callable[[int, int, str], None] | None = None) -> dict:
    if dest.exists() and any(dest.iterdir()):
        raise ApplyError("Destination is not empty: %s" % dest)
    try:
        dest.relative_to(root)
        raise ApplyError("Destination cannot live inside the source folder.")
    except ValueError:
        pass

    plan = _plan(root, opts, rules)
    total = len(plan)
    dest.mkdir(parents=True, exist_ok=True)
    files = 0
    dropped = 0
    for idx, (rel, is_dir, excluded, new_rel, drop) in enumerate(plan):
        if drop:
            if not is_dir:
                dropped += 1
            continue
        if excluded and not opts.copy_ignored:
            continue
        target = dest / new_rel
        if progress and idx % 50 == 0:
            progress(idx, total, rel)
        if is_dir:
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        src = root / rel
        content = None if excluded else rewrite_text(root, rel, rules, opts)
        if content is None:
            shutil.copy2(src, target)
        else:
            tf = read_text(src, opts.max_file_bytes)
            target.write_text(content, encoding=(tf.encoding if tf else "utf-8"))
            shutil.copystat(src, target)
        files += 1
    return {"mode": "copy", "source": str(root), "dest": str(dest),
            "files": files, "dropped": dropped,
            "created_dest": True, "time": time.time()}


def apply_in_place(root: Path, opts: Options, rules: Rules, *, backup: bool,
                   progress: Callable[[int, int, str], None] | None = None) -> dict:
    _guard_root(root)
    plan = _plan(root, opts, rules)
    total = len(plan)
    backup_dir = root / BACKUP_DIRNAME
    manifest = {"mode": "inplace", "source": str(root), "backup": None,
                "renames": [], "rewritten": [], "deleted": [], "time": time.time()}

    if backup:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        backup_dir.mkdir(parents=True)
        manifest["backup"] = str(backup_dir)

    # 1. remove the old project's own files -- copied into the backup first,
    #    so Revert can put every one of them back.
    dropped = 0
    for rel in _drop_roots(plan):
        src = root / rel
        if not src.exists():
            continue
        if backup:
            bpath = backup_dir / rel
            bpath.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, bpath, dirs_exist_ok=True)
            else:
                shutil.copy2(src, bpath)
        if src.is_dir():
            dropped += sum(1 for f in src.rglob("*") if f.is_file())
            shutil.rmtree(src)
        else:
            dropped += 1
            src.unlink()
        manifest["deleted"].append(rel)

    # 2. content rewrites (paths are still the originals here)
    files = 0
    for idx, (rel, is_dir, excluded, _new, drop) in enumerate(plan):
        if is_dir or excluded or drop:
            continue
        if progress and idx % 50 == 0:
            progress(idx, total, rel)
        content = rewrite_text(root, rel, rules, opts)
        if content is None:
            continue
        src = root / rel
        if backup:
            bpath = backup_dir / rel
            bpath.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, bpath)
        tf = read_text(src, opts.max_file_bytes)
        src.write_text(content, encoding=(tf.encoding if tf else "utf-8"))
        manifest["rewritten"].append(rel)
        files += 1

    # 3. renames, shallowest first.
    # Renaming a folder carries its children with it, so once a parent has
    # moved a child's *current* location is no longer its original path --
    # `moved` tracks those prefix rewrites so each child is found where it
    # actually is now, and only its own basename changes.
    renames = [(rel, new) for rel, is_dir, excluded, new, drop in plan
               if not excluded and not drop and new != rel]
    renames.sort(key=lambda pair: pair[0].count("/"))
    moved: dict[str, str] = {}

    def current(rel: str) -> str:
        """Where `rel` lives right now, after any ancestor renames."""
        parts = rel.split("/")
        for i in range(len(parts), 0, -1):
            prefix = "/".join(parts[:i])
            if prefix in moved:
                tail = parts[i:]
                return moved[prefix] + ("/" + "/".join(tail) if tail else "")
        return rel

    for rel, new in renames:
        src_rel = current(rel)
        src = root / src_rel
        if not src.exists():
            continue
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        dst_parent = current(parent) if parent else ""
        dst_rel = (dst_parent + "/" if dst_parent else "") + new.rsplit("/", 1)[-1]
        dst = safe_rename(src, root / dst_rel)
        dst_rel = str(dst.relative_to(root)).replace(os.sep, "/")
        moved[rel] = dst_rel
        manifest["renames"].append([rel, dst_rel])

    if backup:
        (backup_dir / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2))
    return {**manifest, "files": files, "dropped": dropped}


# Names Windows will not accept. Checked on every platform so a project
# rebranded on Linux still opens on Windows.
WIN_BAD_CHARS = set('<>:"|?*')
WIN_RESERVED = {"CON", "PRN", "AUX", "NUL"} | \
    {"COM%d" % i for i in range(1, 10)} | {"LPT%d" % i for i in range(1, 10)}


def windows_unsafe(name: str) -> str | None:
    """Why Windows would reject this file name, or None if it is fine."""
    if not name:
        return None
    bad = sorted(set(name) & WIN_BAD_CHARS)
    if bad:
        return "cannot contain %s" % " ".join(bad)
    if any(ord(c) < 32 for c in name):
        return "cannot contain control characters"
    stem = name.split(".")[0].upper()
    if stem in WIN_RESERVED:
        return "%s is a reserved device name" % stem
    if name[-1] in " .":
        return "cannot end with a space or a dot"
    return None


def safe_rename(src: Path, dst: Path) -> Path:
    """Rename, coping with case-insensitive filesystems.

    On NTFS and APFS `foo.js` and `Foo.js` are the same file, so a plain
    existence check would treat a case-only rebrand as a collision and
    invent `Foo-2.js`. Going via a temporary name does it properly.
    """
    # Compare as strings: Path equality is case-INSENSITIVE on Windows, so
    # `src == dst` is true for a.js vs A.js and would skip the rename that
    # this whole function exists to perform.
    if str(src) == str(dst):
        return dst
    if str(src).lower() == str(dst).lower():
        tmp = src.with_name(src.name + ".rbx-tmp")
        i = 0
        while tmp.exists():
            i += 1
            tmp = src.with_name("%s.rbx-tmp%d" % (src.name, i))
        os.rename(src, tmp)
        os.rename(tmp, dst)
        return dst
    if dst.exists():
        dst = _unique(dst)
    os.rename(src, dst)
    return dst


def _unique(p: Path) -> Path:
    base, ext = p.stem, p.suffix
    i = 2
    while True:
        cand = p.with_name("%s-%d%s" % (base, i, ext))
        if not cand.exists():
            return cand
        i += 1


def revert(manifest: dict) -> str:
    """Undo the last apply using its manifest."""
    if not manifest:
        raise ApplyError("Nothing to revert.")
    if manifest.get("mode") == "copy":
        dest = Path(manifest["dest"])
        if manifest.get("created_dest") and dest.is_dir():
            shutil.rmtree(dest)
            return "Removed %s" % dest
        raise ApplyError("Copy destination is gone already.")

    root = Path(manifest["source"])
    # Undo renames in exactly the reverse of the order they were applied.
    # At each step the entry's parent is still under its rebranded name, so
    # only the basename goes back -- the parent is restored on a later step.
    for rel, new in reversed(manifest.get("renames", [])):
        src = root / new
        if not src.exists():
            continue
        parent = new.rsplit("/", 1)[0] if "/" in new else ""
        dst = root / ((parent + "/" if parent else "") + rel.rsplit("/", 1)[-1])
        if dst.exists() and str(src).lower() != str(dst).lower():
            continue
        safe_rename(src, dst)
    bdir = manifest.get("backup")
    n = 0
    if bdir and Path(bdir).is_dir():
        # put back anything that was deleted outright
        for rel in manifest.get("deleted", []):
            b = Path(bdir) / rel
            target = root / rel
            if b.is_dir() and not target.exists():
                shutil.copytree(b, target)
                n += sum(1 for f in target.rglob("*") if f.is_file())
            elif b.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(b, target)
                n += 1
        for rel in manifest.get("rewritten", []):
            b = Path(bdir) / rel
            if b.is_file():
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(b, target)
                n += 1
        shutil.rmtree(bdir, ignore_errors=True)
    return "Restored %d file%s in %s" % (n, "" if n == 1 else "s", root)


def apply(root_str: str, opts: Options, *, mode: str = "copy", dest: str = "",
          backup: bool = True,
          progress: Callable[[int, int, str], None] | None = None) -> dict:
    root = Path(os.path.expanduser(root_str)).resolve()
    if not root.is_dir():
        raise ApplyError("Not a folder: %s" % root)
    if not opts.find:
        raise ApplyError("Nothing to find -- enter a name to replace.")
    rules = opts.rules()
    if not rules.ok:
        raise ApplyError("Invalid pattern: %s" % (rules.error or "empty"))

    if mode == "copy":
        if not dest:
            raise ApplyError("Choose a destination folder.")
        d = Path(os.path.expanduser(dest)).resolve()
        return apply_copy(root, d, opts, rules, progress)
    return apply_in_place(root, opts, rules, backup=backup, progress=progress)
