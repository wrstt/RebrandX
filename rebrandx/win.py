"""Windows platform primitives.

Everything the rest of RebrandX needs that behaves differently on Windows
lives here, so `engine.py` can stay a readable description of *what* a
rebrand does rather than a catalogue of Win32 special cases.

Every function in this module is safe to call on Linux -- the Windows-only
behaviour is guarded by `IS_WINDOWS` and the POSIX path is always the plain
stdlib one. That keeps the callers free of `if os.name == "nt"` noise.

Pure stdlib, no GUI imports: the CLI and both app shells use it.
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import sys
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"

# Win32 file attribute bits we care about. Python exposes these on
# os.stat_result as st_file_attributes, but only on Windows.
FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4
FILE_ATTRIBUTE_REPARSE_POINT = 0x400

# Windows caps a path at 260 characters unless the process opts in. We add
# the \\?\ prefix ourselves past this length rather than relying on the
# machine being configured, so a deep tree works on a stock install.
MAX_PATH = 260
_LONG_PATH_MARGIN = 240


# --------------------------------------------------------------------------
# long paths
# --------------------------------------------------------------------------

def extended(path) -> str:
    """The \\\\?\\ form of `path`, which lifts the 260-character limit.

    Returns the path unchanged on Linux, on short paths, and on anything
    already prefixed. Relative paths are resolved first because the extended
    form is only meaningful when absolute -- Win32 does no normalisation on
    a \\\\?\\ path, which is exactly why it is fast and exactly why it must
    already be clean.
    """
    s = str(path)
    if not IS_WINDOWS or len(s) < _LONG_PATH_MARGIN or s.startswith("\\\\?\\"):
        return s
    s = os.path.abspath(s)
    if s.startswith("\\\\"):
        # \\server\share -> \\?\UNC\server\share
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def shorten(path) -> str:
    """Undo `extended()` -- for anything the user will read."""
    s = str(path)
    if s.startswith("\\\\?\\UNC\\"):
        return "\\\\" + s[8:]
    if s.startswith("\\\\?\\"):
        return s[4:]
    return s


def long_paths_enabled() -> bool:
    """Whether the machine has LongPathsEnabled set (informational only)."""
    if not IS_WINDOWS:
        return True
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem")
        with key:
            return bool(winreg.QueryValueEx(key, "LongPathsEnabled")[0])
    except OSError:
        return False


# --------------------------------------------------------------------------
# reparse points (junctions, symlinks, OneDrive placeholders)
# --------------------------------------------------------------------------

def is_reparse_point(entry) -> bool:
    """True for a symlink, a directory junction or any other reparse point.

    `os.path.islink()` is False for a junction, so a walk that only checks
    for symlinks will happily descend into one -- following it out of the
    project tree, or straight into a loop when it points at an ancestor.
    Junctions are common on Windows (``C:\\Documents and Settings``, Visual
    Studio build links, OneDrive), so this checks the attribute bit instead.
    """
    try:
        if entry.is_symlink():
            return True
    except OSError:
        return False
    if not IS_WINDOWS:
        return False
    try:
        st = entry.stat(follow_symlinks=False) if hasattr(entry, "stat") \
            else os.stat(entry, follow_symlinks=False)
    except OSError:
        return False
    return bool(getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def is_hidden(entry) -> bool:
    """True for a dotfile on Linux, or the hidden/system attribute on Windows."""
    name = getattr(entry, "name", None) or os.path.basename(str(entry))
    if name.startswith("."):
        return True
    if not IS_WINDOWS:
        return False
    try:
        st = entry.stat(follow_symlinks=False) if hasattr(entry, "stat") \
            else os.stat(entry, follow_symlinks=False)
    except OSError:
        return False
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))


def hide(path) -> None:
    """Mark a path hidden, so `.rebrandx-backup` behaves like a dotfile."""
    if not IS_WINDOWS:
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetFileAttributesW(str(path), FILE_ATTRIBUTE_HIDDEN)
    except Exception:
        pass


# --------------------------------------------------------------------------
# read-only files
# --------------------------------------------------------------------------

def make_writable(path) -> bool:
    """Clear the read-only attribute. True if the path is now writable."""
    try:
        os.chmod(extended(path), stat.S_IWRITE | stat.S_IREAD)
        return True
    except OSError:
        return False


def ensure_writable(path):
    """Make `path` writable for one write, returning the mode to put back.

    Read-only means different things on the two platforms -- on Windows it
    is an attribute git sets on every object it stores, on Linux it is a
    deliberate permission -- but in both cases the user has explicitly
    asked for this file to be rebranded, and it has already been backed up.
    So the bit is lifted for the write and restored immediately after,
    rather than being cleared for good.

    Returns None when the file was already writable, or when the mode could
    not be changed at all (not ours to change, most likely).
    """
    p = extended(path)
    try:
        mode = os.stat(p).st_mode
    except OSError:
        return None
    if os.access(p, os.W_OK):
        return None
    want = stat.S_IWRITE if IS_WINDOWS else stat.S_IWUSR
    try:
        os.chmod(p, mode | want)
        return mode
    except OSError:
        return None


def restore_mode(path, mode) -> None:
    """Put back a mode captured by ensure_writable()."""
    if mode is None:
        return
    try:
        os.chmod(extended(path), mode)
    except OSError:
        pass


def _clear_readonly_and_retry(func, path, err, *, quiet: bool):
    """rmtree fallback: clear read-only and try the delete once more.

    Windows refuses to delete a file carrying the read-only attribute, and
    git sets exactly that on everything in `.git/objects`. Without this,
    wiping a backup or removing `.github/` fails half way through and
    leaves the project in a state Revert cannot describe.
    """
    if make_writable(path):
        try:
            func(extended(path))
            return
        except OSError:
            pass
    if not quiet:
        raise err


def rmtree(path, ignore_errors: bool = False) -> None:
    """shutil.rmtree that copes with read-only files and long paths.

    `ignore_errors` still clears read-only bits first: "ignore errors"
    should mean "do not raise", not "give up on the usual Windows case and
    leave half a folder behind".
    """
    p = extended(path)
    if not os.path.exists(p):
        return

    def handler(func, pth, err):
        _clear_readonly_and_retry(func, pth, err, quiet=ignore_errors)

    if sys.version_info >= (3, 12):
        shutil.rmtree(p, onexc=handler)
    else:
        # Pre-3.12 hands the handler a sys.exc_info() triple instead.
        shutil.rmtree(p, onerror=lambda f, pth, exc: handler(f, pth, exc[1]))


def unlink(path) -> None:
    """Delete one file, clearing read-only first if that is what blocks it."""
    p = extended(path)
    try:
        os.unlink(p)
    except PermissionError:
        if make_writable(path):
            os.unlink(p)
        else:
            raise


# --------------------------------------------------------------------------
# renaming
# --------------------------------------------------------------------------

RENAME_RETRIES = 5
RENAME_BACKOFF = 0.05


def rename(src, dst) -> None:
    """os.rename with the two things Windows adds: locks and long paths.

    A virus scanner, a file indexer or an editor holding a handle makes a
    rename fail with a transient PermissionError. Retrying briefly turns an
    aborted rebrand into a slight pause. A genuinely locked file still
    raises, just a fraction of a second later.
    """
    s, d = extended(src), extended(dst)
    last: OSError | None = None
    for attempt in range(RENAME_RETRIES if IS_WINDOWS else 1):
        try:
            os.rename(s, d)
            return
        except PermissionError as exc:
            last = exc
            time.sleep(RENAME_BACKOFF * (attempt + 1))
        except OSError as exc:
            # Cross-volume moves cannot be renamed; copy instead.
            if IS_WINDOWS and exc.errno == errno.EXDEV:
                shutil.move(s, d)
                return
            raise
    raise last if last else OSError("rename failed: %s -> %s" % (src, dst))


def same_path(a, b) -> bool:
    """Path equality using the filesystem's own case rules."""
    return os.path.normcase(os.path.abspath(str(a))) == \
        os.path.normcase(os.path.abspath(str(b)))


def is_inside(child, parent) -> bool:
    """True when `child` is `parent` or lives under it, case-insensitively
    on Windows. `Path.relative_to` compares case-sensitively, so on NTFS it
    would miss C:\\dev\\App inside c:\\dev."""
    c = os.path.normcase(os.path.abspath(str(child)))
    p = os.path.normcase(os.path.abspath(str(parent))).rstrip(os.sep)
    return c == p or c.startswith(p + os.sep)


# --------------------------------------------------------------------------
# file names Windows will not accept
# --------------------------------------------------------------------------

BAD_CHARS = set('<>:"|?*/\\')
RESERVED = (
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {"COM%d" % i for i in range(1, 10)}
    | {"LPT%d" % i for i in range(1, 10)}
    # Win32 also resolves the superscript digits to the same devices.
    | {"COM%s" % c for c in "¹²³"} | {"LPT%s" % c for c in "¹²³"}
)
MAX_COMPONENT = 255


def unsafe_name(name: str) -> str | None:
    """Why Windows would reject this file name, or None if it is fine.

    Checked on every platform, so a project rebranded on Linux still opens
    on Windows -- a rename that produces `CON.txt` or `api:v2.js` is a real
    bug whether or not the machine doing it would notice.
    """
    if not name:
        return None
    bad = sorted(set(name) & BAD_CHARS)
    if bad:
        return "cannot contain %s" % " ".join(bad)
    if any(ord(c) < 32 for c in name):
        return "cannot contain control characters"
    # Devices are matched on the stem, ignoring case and any extension --
    # `CON`, `con.txt` and `Con.tar.gz` are all the same device.
    stem = name.split(".")[0].strip().upper()
    if stem in RESERVED:
        return "%s is a reserved device name" % stem
    if name[-1] in " .":
        return "cannot end with a space or a dot"
    if len(name) > MAX_COMPONENT:
        return "is longer than %d characters" % MAX_COMPONENT
    return None


def sanitize_name(name: str) -> str:
    """A close, legal stand-in for a name Windows would reject."""
    out = "".join("-" if (c in BAD_CHARS or ord(c) < 32) else c for c in name)
    out = out.rstrip(" .")
    if out.split(".")[0].strip().upper() in RESERVED:
        out = "_" + out
    return out[:MAX_COMPONENT] or "_"


# --------------------------------------------------------------------------
# roots that must never be rebranded
# --------------------------------------------------------------------------

_POSIX_UNSAFE = {"/", "/home", "/usr", "/etc", "/var", "/boot", "/bin",
                 "/sbin", "/opt", "/root", "/lib", "/tmp"}


def _root_key(path) -> str:
    """One canonical spelling of a path, for comparing against the deny list.

    Trailing separators go, except on a drive root -- `C:\\` stripped down
    to `C:` is a *different* location (the drive's current directory), so
    the separator is what makes it a root at all.
    """
    p = os.path.normcase(os.path.abspath(str(path)))
    stripped = p.rstrip("\\/")
    if not stripped or stripped.endswith(":"):
        return stripped + os.sep if IS_WINDOWS else "/"
    return stripped


def unsafe_roots() -> set[str]:
    """Folders a rebrand would wreck rather than rename.

    On Windows that is every drive root, the system and program folders and
    the whole of `C:\\Users`, plus the current user's own profile and its
    top-level shell folders -- rebranding `Documents` is never what anyone
    meant.
    """
    if not IS_WINDOWS:
        return {_root_key(p) for p in _POSIX_UNSAFE}

    roots: set[str] = set()
    env = os.environ.get
    for var in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)",
                "ProgramData", "ProgramW6432", "PUBLIC", "USERPROFILE",
                "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        val = env(var)
        if val:
            roots.add(_root_key(val))

    profile = env("USERPROFILE") or str(Path.home())
    for shell in ("Desktop", "Documents", "Downloads", "Pictures", "Music",
                  "Videos", "OneDrive", "AppData"):
        roots.add(_root_key(os.path.join(profile, shell)))

    # Every drive root: C:\, D:\ ... and the users folder on each.
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = "%s:\\" % letter
        roots.add(_root_key(drive))
        roots.add(_root_key(drive + "Users"))
    return roots


def is_unsafe_root(path) -> bool:
    p = os.path.abspath(str(path))
    if IS_WINDOWS and p.startswith("\\\\"):
        # A bare UNC share root (\\server\share) has nothing above it to
        # restore from, so treat it like a drive root.
        if len([s for s in p.strip("\\").split("\\") if s]) <= 2:
            return True
    return _root_key(p) in unsafe_roots() or same_path(p, Path.home())


# --------------------------------------------------------------------------
# console
# --------------------------------------------------------------------------

def enable_ansi(stream=None) -> bool:
    """Turn on VT processing for a Windows console. True if colour will work.

    Windows Terminal, VS Code and any conhost since the 2016 update accept
    ANSI once ENABLE_VIRTUAL_TERMINAL_PROCESSING is set; older ones refuse,
    and SetConsoleMode tells us which by failing. The existing mode is
    preserved -- overwriting it outright turns off line wrapping.
    """
    stream = stream or sys.stdout
    if not IS_WINDOWS:
        return True
    if os.environ.get("WT_SESSION") or os.environ.get("ANSICON"):
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-12 if stream is sys.stderr else -11)
        if handle in (0, -1, None):
            return False
        mode = wintypes.DWORD()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        if mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            return True
        return bool(kernel32.SetConsoleMode(
            handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING))
    except Exception:
        return False


def encodable(text: str, stream=None) -> bool:
    """Whether `stream` can actually represent `text`.

    Redirecting to a file on Windows gives a cp1252 stream, and printing a
    tick or an arrow to it raises UnicodeEncodeError -- so `rbx ... > log`
    dies where the same command on screen is fine.
    """
    stream = stream or sys.stdout
    enc = getattr(stream, "encoding", None) or "ascii"
    try:
        text.encode(enc)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


def use_utf8(*streams) -> None:
    """Ask the standard streams for UTF-8 where the runtime allows it."""
    for s in (streams or (sys.stdout, sys.stderr)):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def open_folder(path) -> bool:
    """Reveal a folder in Explorer / the desktop's file manager."""
    p = os.path.expanduser(str(path))
    if not os.path.isdir(p):
        return False
    if IS_WINDOWS:
        os.startfile(p)  # noqa: S606  -- a directory, opened by the shell
        return True
    import subprocess
    subprocess.Popen(["xdg-open", p])
    return True
