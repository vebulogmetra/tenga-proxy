#!/bin/bash
#
# Install Tenga Proxy AppImage to system
# Creates desktop entry, icon
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

APP_NAME="tenga-proxy"
APP_VERSION="1.0.0"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

find_appimage() {
    local appimage=""

    if [ -f "$PROJECT_ROOT/dist/${APP_NAME}-${APP_VERSION}-x86_64.AppImage" ]; then
        appimage="$PROJECT_ROOT/dist/${APP_NAME}-${APP_VERSION}-x86_64.AppImage"
    elif [ -f "$PROJECT_ROOT/${APP_NAME}-${APP_VERSION}-x86_64.AppImage" ]; then
        appimage="$PROJECT_ROOT/${APP_NAME}-${APP_VERSION}-x86_64.AppImage"
    else
        appimage=$(find "$PROJECT_ROOT" -maxdepth 2 -name "${APP_NAME}*.AppImage" -type f | head -1)
    fi
    
    if [ -z "$appimage" ] || [ ! -f "$appimage" ]; then
        error "AppImage не найден. Сначала запустите core/scripts/build_appimage.sh"
    fi
    
    echo "$appimage"
}

install_appimage() {
    local appimage=$(find_appimage)
    local install_dir="$HOME/.local/bin"
    local apps_dir="$HOME/.local/share/applications"
    local icons_dir="$HOME/.local/share/icons/hicolor"
    local installed_path="$install_dir/$APP_NAME.AppImage"
    
    info "Найден AppImage: $appimage"

    mkdir -p "$install_dir"
    mkdir -p "$apps_dir"
    mkdir -p "$icons_dir/scalable/apps"
    mkdir -p "$icons_dir/256x256/apps"

    info "Копирование AppImage в $install_dir..."
    cp "$appimage" "$installed_path"
    chmod +x "$installed_path"

    if [ -f "$PROJECT_ROOT/assets/tenga-proxy.svg" ]; then
        info "Установка иконки..."
        cp "$PROJECT_ROOT/assets/tenga-proxy.svg" "$icons_dir/scalable/apps/"

        if command -v rsvg-convert &>/dev/null; then
            rsvg-convert -w 256 -h 256 "$PROJECT_ROOT/assets/tenga-proxy.svg" \
                -o "$icons_dir/256x256/apps/tenga-proxy.png"
        elif command -v convert &>/dev/null; then
            convert -background none "$PROJECT_ROOT/assets/tenga-proxy.svg" \
                -resize 256x256 "$icons_dir/256x256/apps/tenga-proxy.png"
        fi
    fi

    info "Создание .desktop файла..."
    cat > "$apps_dir/tenga-proxy.desktop" << EOF
[Desktop Entry]
Name=Tenga Proxy
GenericName=Proxy Client
Comment=Secure proxy client with sing-box backend
Exec=$installed_path %U
Icon=tenga-proxy
Terminal=false
Type=Application
Categories=Network;Security;
Keywords=proxy;vpn;singbox;network;
StartupNotify=true
StartupWMClass=tenga-proxy
Actions=quit;

[Desktop Action quit]
Name=Выход
Exec=$installed_path --quit
EOF

    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$apps_dir" 2>/dev/null || true
    fi

    if command -v gtk-update-icon-cache &>/dev/null; then
        gtk-update-icon-cache -f -t "$icons_dir" 2>/dev/null || true
    fi
    
    # Check if ~/.local/bin is in PATH
    if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
        warning "$HOME/.local/bin не в PATH"
        echo
        echo "Добавьте в ~/.bashrc или ~/.profile:"
        echo '  export PATH="$HOME/.local/bin:$PATH"'
        echo
    fi

    echo
    echo "=========================================="
    echo "          Установка завершена!            "
    echo "=========================================="
    echo
    echo "Для удаления запустите:"
    echo "  core/scripts/install_appimage.sh uninstall"
    echo
}

uninstall_appimage() {
    local install_dir="$HOME/.local/bin"
    local apps_dir="$HOME/.local/share/applications"
    local icons_dir="$HOME/.local/share/icons/hicolor"
    
    info "Удаление Tenga Proxy..."
    
    rm -f "$install_dir/$APP_NAME.AppImage"
    rm -f "$apps_dir/tenga-proxy.desktop"
    rm -f "$icons_dir/scalable/apps/tenga-proxy.svg"
    rm -f "$icons_dir/256x256/apps/tenga-proxy.png"

    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$apps_dir" 2>/dev/null || true
    fi
    
    success "Tenga Proxy удалён"
    echo
    echo "Конфигурация сохранена в ~/.config/tenga-proxy"
    echo "Для полного удаления: rm -rf ~/.config/tenga-proxy"
}

case "${1:-install}" in
    install)
        install_appimage
        ;;
    uninstall|remove)
        uninstall_appimage
        ;;
    *)
        echo "Использование: $0 [install|uninstall]"
        exit 1
        ;;
esac
