#!/bin/bash
#
# Install Tenga Proxy AppImage to system
# Creates desktop entry, icon
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

APP_NAME="tenga-proxy"

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

    if ls "$PROJECT_ROOT/dist/${APP_NAME}-"*"-x86_64.AppImage" >/dev/null 2>&1; then
        appimage=$(ls -t "$PROJECT_ROOT"/dist/${APP_NAME}-*-x86_64.AppImage | head -1)
    elif ls "$PROJECT_ROOT/${APP_NAME}-"*"-x86_64.AppImage" >/dev/null 2>&1; then
        appimage=$(ls -t "$PROJECT_ROOT"/${APP_NAME}-*-x86_64.AppImage | head -1)
    else
        appimage=$(find "$PROJECT_ROOT" -maxdepth 2 -name "${APP_NAME}-*-x86_64.AppImage" -type f -printf "%T@ %p\n" 2>/dev/null | sort -nr | head -1 | awk '{print $2}')
    fi

    if [ -z "$appimage" ] || [ ! -f "$appimage" ]; then
        error "AppImage не найден. Сначала запустите core/scripts/build_appimage.sh"
    fi

    echo "$appimage"
}

install_appimage() {
    local appimage=$(find_appimage)
    local current_user
    current_user="$(id -un)"
    local install_dir="$HOME/.local/bin"
    local apps_dir="$HOME/.local/share/applications"
    local icons_dir="$HOME/.local/share/icons/hicolor"
    local config_bin_dir="$HOME/.config/tenga-proxy/bin"
    local user_xray_path="$config_bin_dir/xray"
    local installed_path="$install_dir/$APP_NAME.AppImage"
    local helper_src="$PROJECT_ROOT/core/scripts/tun_route_helper.sh"
    local helper_dir="/usr/local/libexec/tenga-proxy"
    local helper_path="$helper_dir/tun-route-helper"
    local sudoers_path="/etc/sudoers.d/tenga-proxy-tun-helper-$current_user"
    
    info "Найден AppImage: $appimage"

    mkdir -p "$install_dir"
    mkdir -p "$apps_dir"
    mkdir -p "$icons_dir/scalable/apps"
    mkdir -p "$icons_dir/256x256/apps"

    info "Копирование AppImage в $install_dir..."
    cp "$appimage" "$installed_path"
    chmod +x "$installed_path"

    # Install privileged helper and sudoers rule for passwordless TUN route switch.
    if [ -f "$helper_src" ]; then
        if ! echo "$current_user" | grep -Eq '^[a-zA-Z0-9._-]+$'; then
            warning "Небезопасное имя пользователя '$current_user', пропуск настройки sudoers."
            current_user=""
        fi
        info "Установка helper для маршрутизации TUN..."
        if sudo install -d -m 0755 "$helper_dir" \
            && sudo install -o root -g root -m 0755 "$helper_src" "$helper_path"; then
            success "Helper установлен: $helper_path"
        else
            warning "Не удалось установить helper маршрутизации TUN"
        fi

        if [ -n "$current_user" ]; then
            info "Настройка sudoers (NOPASSWD только для helper)..."
            tmp_sudoers="$(mktemp)"
            printf "%s ALL=(root) NOPASSWD: %s\n" "$current_user" "$helper_path" > "$tmp_sudoers"
            if command -v visudo >/dev/null 2>&1 \
                && visudo -cf "$tmp_sudoers" >/dev/null 2>&1 \
                && sudo install -o root -g root -m 0440 "$tmp_sudoers" "$sudoers_path"; then
                success "Sudoers правило установлено: $sudoers_path"
            else
                warning "Не удалось установить sudoers правило. Будет запрашиваться пароль."
            fi
            rm -f "$tmp_sudoers"
        fi
    else
        warning "Helper скрипт не найден: $helper_src"
    fi

    # Install xray binary into user config dir so AppImage runtime can use it
    # and apply capabilities required for TUN mode.
    if [ -f "$PROJECT_ROOT/core/bin/xray" ]; then
        mkdir -p "$config_bin_dir"
        cp "$PROJECT_ROOT/core/bin/xray" "$user_xray_path"
        chmod +x "$user_xray_path"
        info "Установлен xray: $user_xray_path"

        if command -v setcap &>/dev/null; then
            info "Выдача прав для TUN режимa (cap_net_admin, cap_net_raw)..."
            if sudo setcap cap_net_admin,cap_net_raw+ep "$user_xray_path"; then
                success "Права выданы: $user_xray_path"
                if command -v getcap &>/dev/null; then
                    getcap "$user_xray_path" || true
                fi
            else
                warning "Не удалось выдать права setcap. TUN режим может не работать."
                warning "Выполните вручную:"
                echo "  sudo setcap cap_net_admin,cap_net_raw+ep $user_xray_path"
            fi
        else
            warning "Утилита setcap не найдена. Установите libcap и выполните:"
            echo "  sudo setcap cap_net_admin,cap_net_raw+ep $user_xray_path"
        fi
    else
        warning "Локальный xray не найден: $PROJECT_ROOT/core/bin/xray"
        warning "Пропускаю настройку TUN прав."
    fi

    if [ -f "$PROJECT_ROOT/assets/tenga-proxy.png" ]; then
        info "Установка иконки..."
        cp "$PROJECT_ROOT/assets/tenga-proxy.png" "$icons_dir/256x256/apps/tenga-proxy.png"
    fi

    if [ -f "$PROJECT_ROOT/assets/tenga-proxy.svg" ]; then
        cp "$PROJECT_ROOT/assets/tenga-proxy.svg" "$icons_dir/scalable/apps/"
    fi

    info "Создание .desktop файла..."
    cat > "$apps_dir/tenga-proxy.desktop" << EOF
[Desktop Entry]
Name=Tenga Proxy
GenericName=Proxy Client
Comment=Secure proxy client with xray-core backend
Exec=$installed_path %U
Icon=tenga-proxy
Terminal=false
Type=Application
Categories=Network;Security;
Keywords=proxy;vpn;xray;network;
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
    local current_user
    current_user="$(id -un)"
    local install_dir="$HOME/.local/bin"
    local apps_dir="$HOME/.local/share/applications"
    local icons_dir="$HOME/.local/share/icons/hicolor"
    local helper_path="/usr/local/libexec/tenga-proxy/tun-route-helper"
    local sudoers_path="/etc/sudoers.d/tenga-proxy-tun-helper-$current_user"
    
    info "Удаление Tenga Proxy..."
    
    rm -f "$install_dir/$APP_NAME.AppImage"
    rm -f "$apps_dir/tenga-proxy.desktop"
    rm -f "$icons_dir/scalable/apps/tenga-proxy.svg"
    rm -f "$icons_dir/256x256/apps/tenga-proxy.png"
    sudo rm -f "$helper_path" "$sudoers_path" 2>/dev/null || true

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
