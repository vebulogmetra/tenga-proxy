#!/bin/bash
# Сборка установщика Veblock для Windows. Выполнять в Git Bash: Python берёт uv
# (группы windows и build), Inno Setup — из Program Files.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

command -v uv >/dev/null || { echo "[ERROR] uv не найден: bash core/scripts/install_dev.sh"; exit 1; }
# Группы ставятся поверх уже установленных: dev для тестов остаётся.
PY=(uv run --extra windows --extra build python)

VERSION="$("${PY[@]}" -c 'import runpy; print(runpy.run_path("packaging/windows/version_info.py")["project_version"]())')"

for f in xray.exe wintun.dll geoip.dat geosite.dat; do
    [ -f "core/bin/$f" ] || { echo "[ERROR] core/bin/$f не найден: bash core/scripts/install_dev.sh"; exit 1; }
done
for f in assets/tenga-proxy.ico assets/icons/win/tenga-proxy-connected.ico; do
    [ -f "$f" ] || { echo "[ERROR] $f не найден: uv run python tools/make_ico.py"; exit 1; }
done

mkdir -p build/windows
"${PY[@]}" packaging/windows/version_info.py build/windows/version_info.txt

"${PY[@]}" -m PyInstaller --noconfirm --clean \
    --workpath build/windows/pyinstaller --distpath dist/windows \
    packaging/windows/tenga-proxy.spec

for exe in tenga-proxy.exe tenga-proxy-svc.exe; do
    [ -f "dist/windows/tenga-proxy/$exe" ] || { echo "[ERROR] $exe не собран"; exit 1; }
done

ISCC="${ISCC:-/c/Program Files (x86)/Inno Setup 6/ISCC.exe}"
[ -x "$ISCC" ] || { echo "[ERROR] Inno Setup 6 не найден: $ISCC (переменная ISCC задаёт путь)"; exit 1; }
# Git Bash (среда MSYS2) принял бы «/DAppVersion=…» за путь и переписал бы его.
MSYS2_ARG_CONV_EXCL="*" "$ISCC" "/DAppVersion=$VERSION" 'packaging\windows\tenga-proxy.iss'

echo "[OK] dist/windows/veblock-$VERSION-windows-x64-setup.exe"
