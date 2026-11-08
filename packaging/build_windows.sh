#!/usr/bin/env bash
# گیم سنتر — build dist/GameCenter.exe from Linux.
#
# PyInstaller has to run on Windows (its bootloader is a Windows binary), so we
# run a real Windows Python under Wine inside Docker. Nothing is installed on
# the host and the output lands in dist/ like any other build.
#
#   ./packaging/build_windows.sh                 # default image
#   IMAGE=tobix/pywine:3.11 ./packaging/build_windows.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${IMAGE:-tobix/pywine:3.12}"

cd "$ROOT"

echo "▸ building inside $IMAGE"
docker run --rm \
  -v "$ROOT":/src \
  -w /src \
  -e WINEPREFIX=/wine \
  -e WINEDEBUG=-all \
  -e PYTHONIOENCODING=utf-8 \
  "$IMAGE" bash -lc '
    set -e
    wineboot -i >/dev/null 2>&1 || true
    python -m pip install --disable-pip-version-check --quiet --upgrade pip pyinstaller
    python -m PyInstaller --clean --noconfirm packaging/gamecenter.spec
  '

ls -la dist/
echo "✓ dist/GameCenter.exe"
