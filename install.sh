#!/bin/bash
# RebrandX installer — wires the app into GNOME so it launches with one click.
# Everything it touches lives under $HOME; nothing needs sudo.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APPS="$HOME/.local/share/applications"
ICONS="$HOME/.local/share/icons/hicolor/scalable/apps"
BIN="$HOME/.local/bin"
NAUT="$HOME/.local/share/nautilus/scripts"

say() { printf '  %s\n' "$*"; }

echo "Installing RebrandX from $HERE"

# --- dependency check -------------------------------------------------------
if ! /usr/bin/python3 -c "
import gi
gi.require_version('Gtk','3.0'); gi.require_version('WebKit2','4.1')
from gi.repository import Gtk, WebKit2
" 2>/dev/null; then
  echo
  echo "Missing GTK/WebKit bindings. Install them with:"
  echo
  echo "    sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1"
  echo
  exit 1
fi
say "dependencies OK (python3-gi + WebKit2 4.1)"

# --- icon -------------------------------------------------------------------
mkdir -p "$ICONS"
cp "$HERE/share/rebrandx.svg" "$ICONS/rebrandx.svg"
say "icon      -> $ICONS/rebrandx.svg"

# --- launcher on PATH -------------------------------------------------------
mkdir -p "$BIN"
ln -sf "$HERE/bin/rbx" "$BIN/rbx"
ln -sf "$HERE/bin/rebrandx" "$BIN/rebrandx"
say "commands  -> $BIN/rbx, $BIN/rebrandx"

# --- desktop entry ----------------------------------------------------------
mkdir -p "$APPS"
cat > "$APPS/rebrandx.desktop" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=RebrandX
GenericName=Folder Rebrander
Comment=Replace a project name across a folder's files, names and contents
Exec=$HERE/bin/rebrandx %f
Icon=rebrandx
Terminal=false
Categories=Development;
Keywords=rename;rebrand;replace;refactor;project;
StartupNotify=true
StartupWMClass=rebrandx
MimeType=inode/directory;
EOF
chmod +x "$APPS/rebrandx.desktop"
say "launcher  -> $APPS/rebrandx.desktop"

# --- double-clickable copy on the Desktop (skip with --no-desktop-icon) -----
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ "${1:-}" = "--no-desktop-icon" ]; then
  rm -f "$DESKTOP_DIR/RebrandX.desktop"
  say "desktop   -> skipped (--no-desktop-icon)"
elif [ -d "$DESKTOP_DIR" ]; then
  cp "$APPS/rebrandx.desktop" "$DESKTOP_DIR/RebrandX.desktop"
  chmod +x "$DESKTOP_DIR/RebrandX.desktop"
  gio set "$DESKTOP_DIR/RebrandX.desktop" metadata::trusted true 2>/dev/null || true
  say "desktop   -> $DESKTOP_DIR/RebrandX.desktop"
fi

# --- right-click a folder in Files ------------------------------------------
mkdir -p "$NAUT"
cat > "$NAUT/Rebrand with RebrandX" <<EOF
#!/bin/sh
# Nautilus passes the selected folder in NAUTILUS_SCRIPT_SELECTED_FILE_PATHS.
target="\$(printf '%s' "\$NAUTILUS_SCRIPT_SELECTED_FILE_PATHS" | head -n1)"
[ -z "\$target" ] && target="\$PWD"
exec "$HERE/bin/rebrandx" "\$target"
EOF
chmod +x "$NAUT/Rebrand with RebrandX"
say "files menu-> Scripts › Rebrand with RebrandX"

# --- refresh caches ---------------------------------------------------------
update-desktop-database "$APPS" 2>/dev/null || true
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true

echo
echo "Done."
echo
echo "  Launch it        : press Super, type 'RebrandX'  (or double-click the Desktop icon)"
echo "  Right-click menu : in Files, right-click a folder -> Scripts -> Rebrand with RebrandX"
echo "  Terminal         : rbx OldName NewName ~/path/to/folder"
echo
case ":$PATH:" in
  *":$BIN:"*) ;;
  *) echo "  Note: $BIN is not on your PATH yet — open a new terminal, or add it to ~/.zshrc." ;;
esac
