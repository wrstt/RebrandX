#!/bin/bash
# Build RebrandX.exe from Linux, using Windows Python under Wine.
#
#   ./packaging/build-windows-wine.sh
#
# PyInstaller cannot cross-compile, but it runs perfectly well inside Wine
# against a Windows Python, and the .exe it produces is a genuine PE binary.
# The first run downloads the Python installer (~28 MB) into the prefix.
#
# The alternative, and the more faithful build, is CI: every push builds this
# on a real windows-latest runner. See .github/workflows/build.yml
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export WINEPREFIX="${WINEPREFIX:-$HOME/.wine-rebrandx}"
export WINEDEBUG="${WINEDEBUG:--all}"
export WINEARCH=win64

PY_VERSION="${PY_VERSION:-3.12.7}"
PY_URL="https://www.python.org/ftp/python/${PY_VERSION}/python-${PY_VERSION}-amd64.exe"
CACHE="$HOME/.cache/rebrandx"
INSTALLER="$CACHE/python-${PY_VERSION}-amd64.exe"

command -v wine >/dev/null || { echo "wine is not installed: sudo apt install wine"; exit 1; }

WINPY="$WINEPREFIX/drive_c/Python312/python.exe"
if [ ! -f "$WINPY" ]; then
  echo "Setting up Windows Python ${PY_VERSION} in $WINEPREFIX"
  mkdir -p "$CACHE"
  if [ ! -f "$INSTALLER" ]; then
    echo "  downloading $PY_URL"
    curl -fL --progress-bar -o "$INSTALLER" "$PY_URL"
  fi
  wineboot -i >/dev/null 2>&1 || true
  echo "  installing (silent)…"
  wine "$INSTALLER" /quiet InstallAllUsers=1 TargetDir='C:\Python312' \
       Include_test=0 Include_launcher=0 PrependPath=1 >/dev/null 2>&1 || true
  [ -f "$WINPY" ] || { echo "Windows Python did not install cleanly"; exit 1; }
fi

echo "Installing build dependencies into the prefix…"
wine "$WINPY" -m pip install --quiet --upgrade pip pyinstaller pywebview

echo "Building…"
cd "$HERE"
wine "$WINPY" -m PyInstaller \
  --name RebrandX --onefile --windowed --noconfirm --clean \
  --icon 'share\rebrandx.ico' \
  --add-data 'rebrandx\ui;rebrandx/ui' \
  --hidden-import webview.platforms.edgechromium \
  --collect-all webview \
  'rebrandx\app_win.py'

if [ -f dist/RebrandX.exe ]; then
  echo
  echo "Built dist/RebrandX.exe ($(du -h dist/RebrandX.exe | cut -f1))"
  file dist/RebrandX.exe
else
  echo "Build did not produce dist/RebrandX.exe" >&2
  exit 1
fi
