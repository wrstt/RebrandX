#!/bin/bash
# Remove the user-level RebrandX install. Leaves this folder alone --
# delete it yourself afterwards if you want the source gone too.
set -euo pipefail
DESKTOP_DIR="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
say() { printf '  %s\n' "$*"; }

for f in "$HOME/.local/bin/rbx" \
         "$HOME/.local/bin/rebrandx" \
         "$HOME/.local/share/applications/rebrandx.desktop" \
         "$HOME/.local/share/icons/hicolor/scalable/apps/rebrandx.svg" \
         "$HOME/.local/share/nautilus/scripts/Rebrand with RebrandX" \
         "$DESKTOP_DIR/RebrandX.desktop"; do
  if [ -e "$f" ] || [ -L "$f" ]; then rm -f "$f"; say "removed ${f/$HOME/\~}"; fi
done

read -r -p "Also delete saved settings and recent folders? [y/N] " a || a=n
case "$a" in
  y|Y) rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/rebrandx"; say "removed ~/.config/rebrandx" ;;
  *)   say "kept ~/.config/rebrandx" ;;
esac

update-desktop-database -q "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -q -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo
echo "Done. If you installed the .deb as well, remove it with: sudo apt remove rebrandx"
