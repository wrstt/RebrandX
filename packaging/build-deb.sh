#!/bin/bash
# Build rebrandx_<version>_all.deb — a normal Ubuntu package.
#   ./packaging/build-deb.sh    then:   sudo apt install ./dist/rebrandx_1.0.0_all.deb
set -euo pipefail

VERSION="1.0.0"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="$HERE/build/deb"
DIST="$HERE/dist"
PKG="rebrandx_${VERSION}_all"

rm -rf "$BUILD"
mkdir -p "$BUILD/DEBIAN" \
         "$BUILD/usr/lib/rebrandx/rebrandx/ui" \
         "$BUILD/usr/bin" \
         "$BUILD/usr/share/applications" \
         "$BUILD/usr/share/icons/hicolor/scalable/apps" \
         "$BUILD/usr/share/doc/rebrandx" \
         "$DIST"

# --- payload ---------------------------------------------------------------
install -m644 "$HERE/rebrandx/"*.py            "$BUILD/usr/lib/rebrandx/rebrandx/"
install -m644 "$HERE/rebrandx/ui/"*            "$BUILD/usr/lib/rebrandx/rebrandx/ui/"
install -m644 "$HERE/share/rebrandx.svg"       "$BUILD/usr/share/icons/hicolor/scalable/apps/rebrandx.svg"
install -m644 "$HERE/README.md"                "$BUILD/usr/share/doc/rebrandx/README.md"

cat > "$BUILD/usr/bin/rebrandx" <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /usr/lib/rebrandx/rebrandx/app.py "$@"
EOF
cat > "$BUILD/usr/bin/rbx" <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /usr/lib/rebrandx/rebrandx/cli.py "$@"
EOF
chmod 755 "$BUILD/usr/bin/rebrandx" "$BUILD/usr/bin/rbx"

cat > "$BUILD/usr/share/applications/rebrandx.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Version=1.0
Name=RebrandX
GenericName=Folder Rebrander
Comment=Replace a project name across a folder's files, names and contents
Exec=rebrandx %f
Icon=rebrandx
Terminal=false
Categories=Development;
Keywords=rename;rebrand;replace;refactor;project;
StartupNotify=true
StartupWMClass=rebrandx
MimeType=inode/directory;
EOF

# --- control ---------------------------------------------------------------
INSTALLED_KB=$(du -sk "$BUILD" | cut -f1)
cat > "$BUILD/DEBIAN/control" <<EOF
Package: rebrandx
Version: $VERSION
Section: devel
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1
Recommends: nautilus
Installed-Size: $INSTALLED_KB
Maintainer: RebrandX <rgbmusic360@gmail.com>
Description: Rebrand a folder — rename a project everywhere at once
 RebrandX finds a name across a folder's file contents, file names and folder
 names and replaces it with a new one. It previews every change as a diff
 first, lets you skip individual lines or whole files, and can either rewrite
 the folder in place (keeping a backup) or write a rebranded copy elsewhere.
 .
 It ships both a GTK/WebKit desktop app and an "rbx" command line tool.
EOF

cat > "$BUILD/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
  update-desktop-database -q /usr/share/applications 2>/dev/null || true
  gtk-update-icon-cache -q -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
exit 0
EOF
cat > "$BUILD/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
  update-desktop-database -q /usr/share/applications 2>/dev/null || true
  gtk-update-icon-cache -q -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
rm -rf /usr/lib/rebrandx/rebrandx/__pycache__ 2>/dev/null || true
exit 0
EOF
chmod 755 "$BUILD/DEBIAN/postinst" "$BUILD/DEBIAN/postrm"

find "$BUILD" -type d -exec chmod 755 {} +
fakeroot dpkg-deb --build --root-owner-group "$BUILD" "$DIST/$PKG.deb" >/dev/null
echo "built $DIST/$PKG.deb"
dpkg-deb --info "$DIST/$PKG.deb" | sed -n '2,8p'
