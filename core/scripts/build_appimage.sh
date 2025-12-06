#!/bin/bash
#
# Build script for Tenga Proxy AppImage
# Tested on Ubuntu 24.04
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

APP_NAME="tenga-proxy"
APP_VERSION="1.4.3"
BUILD_DIR="$PROJECT_ROOT/build"
APPDIR="$BUILD_DIR/${APP_NAME}.AppDir"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

check_deps() {
    info "Проверка зависимостей..."
    
    if [ ! -f "$PROJECT_ROOT/core/bin/sing-box" ]; then
        error "sing-box не найден в core/bin/"
    fi
    
    if ! command -v wget &>/dev/null && ! command -v curl &>/dev/null; then
        error "Требуется wget или curl"
    fi
    
    success "Зависимости готовы"
}

get_appimagetool() {
    local tool_path="$BUILD_DIR/appimagetool-x86_64.AppImage"
    
    if [ -f "$tool_path" ] && [ -x "$tool_path" ]; then
        return 0
    fi
    
    info "Загрузка appimagetool..."
    mkdir -p "$BUILD_DIR"
    
    local url="https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
    
    if command -v wget &>/dev/null; then
        wget -q --show-progress -O "$tool_path" "$url"
    else
        curl -L -o "$tool_path" "$url"
    fi
    
    chmod +x "$tool_path"
    success "appimagetool загружен"
}

create_appdir() {
    info "Создание структуры AppDir..."
    
    rm -rf "$APPDIR"
    mkdir -p "$APPDIR/usr/bin"
    mkdir -p "$APPDIR/usr/share/tenga-proxy"
    mkdir -p "$APPDIR/usr/share/applications"
    mkdir -p "$APPDIR/usr/share/icons/hicolor/scalable/apps"
    mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"
    
    # Copy Python source
    cp -r "$PROJECT_ROOT/src" "$APPDIR/usr/share/tenga-proxy/"
    cp "$PROJECT_ROOT/gui.py" "$APPDIR/usr/share/tenga-proxy/"
    cp "$PROJECT_ROOT/cli.py" "$APPDIR/usr/share/tenga-proxy/"
    
    # Copy core files
    mkdir -p "$APPDIR/usr/share/tenga-proxy/core/bin"
    cp "$PROJECT_ROOT/core/bin/sing-box" "$APPDIR/usr/share/tenga-proxy/core/bin/"
    chmod +x "$APPDIR/usr/share/tenga-proxy/core/bin/sing-box"

    
    # Copy assets
    cp -r "$PROJECT_ROOT/assets" "$APPDIR/usr/share/tenga-proxy/" 2>/dev/null || true
    
    # Desktop and icons
    cp "$PROJECT_ROOT/assets/tenga-proxy.desktop" "$APPDIR/usr/share/applications/"
    cp "$PROJECT_ROOT/assets/tenga-proxy.desktop" "$APPDIR/"
    cp "$PROJECT_ROOT/assets/tenga-proxy.svg" "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
    cp "$PROJECT_ROOT/assets/tenga-proxy.svg" "$APPDIR/tenga-proxy.svg"
    
    if command -v rsvg-convert &>/dev/null; then
        rsvg-convert -w 256 -h 256 "$PROJECT_ROOT/assets/tenga-proxy.svg" \
            -o "$APPDIR/usr/share/icons/hicolor/256x256/apps/tenga-proxy.png"
    fi
    
    # Create launcher script
    cat > "$APPDIR/usr/bin/tenga-proxy" << 'LAUNCHER'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$SCRIPT_DIR/../share/tenga-proxy"

# Set up environment
export TENGA_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/tenga-proxy"
export GI_TYPELIB_PATH="/usr/lib/girepository-1.0:/usr/lib/x86_64-linux-gnu/girepository-1.0:${GI_TYPELIB_PATH}"

# Wayland compatibility
if [ -n "$WAYLAND_DISPLAY" ] && [ -n "$DISPLAY" ]; then
    export GDK_BACKEND=x11
fi

# Make sing-box available
export PATH="$APP_DIR/core/bin:$PATH"

# Create config dir
mkdir -p "$TENGA_CONFIG_DIR"

# Check dependencies
check_deps() {
    local missing=()
    
    # Check Python3
    if ! command -v python3 &> /dev/null; then
        missing+=("python3")
    fi
    
    # Check Python packages
    if command -v python3 &> /dev/null; then
        if ! python3 -c "import gi" 2>/dev/null; then
            missing+=("python3-gi")
        fi
        if ! python3 -c "from gi.repository import Gtk" 2>/dev/null; then
            missing+=("python3-gi (GTK3)")
        fi
        if ! python3 -c "import requests" 2>/dev/null; then
            missing+=("python3-requests или pip install requests")
        fi
        if ! python3 -c "import yaml" 2>/dev/null; then
            missing+=("python3-yaml или pip install PyYAML")
        fi
    fi
    
    if [ ${#missing[@]} -gt 0 ]; then
        echo "Ошибка: отсутствуют необходимые зависимости:" >&2
        for dep in "${missing[@]}"; do
            echo "  - $dep" >&2
        done
        echo "" >&2
        echo "Для Ubuntu/Debian установите:" >&2
        echo "  sudo apt update" >&2
        echo "  sudo apt install -y python3 python3-gi python3-pip gir1.2-gtk-3.0 \\" >&2
        echo "    gir1.2-appindicator3-0.1 gir1.2-notify-0.7" >&2
        echo "  pip3 install requests PyYAML" >&2
        echo "" >&2
        echo "Подробнее см. README.md: https://github.com/vebulogmetra/tenga-proxy#зависимости" >&2
        exit 1
    fi
}

check_deps

# Run with system Python
cd "$APP_DIR"
exec python3 gui.py "$@"
LAUNCHER
    chmod +x "$APPDIR/usr/bin/tenga-proxy"
    
    # Create AppRun
    cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
SELF=$(readlink -f "$0")
HERE=${SELF%/*}
exec "${HERE}/usr/bin/tenga-proxy" "$@"
APPRUN
    chmod +x "$APPDIR/AppRun"
    
    success "AppDir создан"
}

# Build AppImage
build_appimage() {
    info "Сборка AppImage..."
    
    local output="$PROJECT_ROOT/dist/${APP_NAME}-${APP_VERSION}-x86_64.AppImage"
    mkdir -p "$PROJECT_ROOT/dist"
    rm -f "$output"
    
    ARCH=x86_64 "$BUILD_DIR/appimagetool-x86_64.AppImage" \
        --no-appstream \
        "$APPDIR" \
        "$output"
    
    chmod +x "$output"
    
    success "AppImage создан: $output"
    echo
    echo "=========================================="
    echo "           Сборка завершена!              "
    echo "=========================================="
    echo
    echo "Файл: dist/${APP_NAME}-${APP_VERSION}-x86_64.AppImage"
    echo "Размер: $(du -h "$output" | cut -f1)"
    echo
}

# Main
main() {
    echo "=========================================="
    echo "      Tenga Proxy - AppImage Build        "
    echo "=========================================="
    echo
    
    check_deps
    get_appimagetool
    create_appdir
    build_appimage
}

main "$@"
