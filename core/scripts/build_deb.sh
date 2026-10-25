#!/bin/bash
#
# Сборка deb-пакета Tenga Proxy. Проверено на Ubuntu 24.04.
#
# Пакет — исходники и xray-core в /usr/lib/tenga-proxy, запуск системным
# Python: GTK 4, libadwaita и requests приходят зависимостями пакета.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

APP_NAME="tenga-proxy"
# Версия одна — в src/__init__.py, её правит `cli.py bump-version`.
APP_VERSION="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' src/__init__.py)"
BUILD_DIR="$PROJECT_ROOT/build"
PKG_ROOT="$BUILD_DIR/deb/$APP_NAME"
LIB_DIR="usr/lib/$APP_NAME"
PACKAGING="$PROJECT_ROOT/packaging/linux"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

check_deps() {
    info "Проверка зависимостей..."

    [ -n "$APP_VERSION" ] || error "Версия не найдена в src/__init__.py"
    command -v dpkg-deb &>/dev/null || error "Требуется dpkg-deb"
    [ -f "$PROJECT_ROOT/core/bin/xray" ] || error "xray-core не найден в core/bin/"

    for geo_file in geoip.dat geosite.dat; do
        [ -f "$PROJECT_ROOT/core/bin/$geo_file" ] || error "$geo_file не найден в core/bin/"
    done

    ARCH="$(dpkg --print-architecture)"
    success "Зависимости готовы"
}

stage_files() {
    info "Сборка дерева пакета..."

    rm -rf "$PKG_ROOT"
    mkdir -p "$PKG_ROOT/DEBIAN" "$PKG_ROOT/$LIB_DIR/core/bin"

    # Исходники без байт-кода: его соберёт postinst под системный Python.
    cp -r "$PROJECT_ROOT/src" "$PKG_ROOT/$LIB_DIR/"
    find "$PKG_ROOT/$LIB_DIR" -name __pycache__ -type d -prune -exec rm -rf {} +
    # Метаданные `uv sync` (setuptools develop) в пакет не нужны.
    rm -rf "$PKG_ROOT/$LIB_DIR/src/"*.egg-info
    cp "$PROJECT_ROOT/gui.py" "$PKG_ROOT/$LIB_DIR/"
    cp -r "$PROJECT_ROOT/assets" "$PKG_ROOT/$LIB_DIR/"
    # Снимки экрана и исходники логотипа — для README, ICO и BMP — для Windows.
    rm -rf "$PKG_ROOT/$LIB_DIR/assets/"{screen-*.png,logo_inner.png,tenga-proxy.png,*.ico} \
        "$PKG_ROOT/$LIB_DIR/assets/icons/win" "$PKG_ROOT/$LIB_DIR/assets/flags/win"

    install -m 0755 "$PROJECT_ROOT/core/bin/xray" "$PKG_ROOT/$LIB_DIR/core/bin/xray"
    # Геобазы: без них правила geosite:/geoip: роняют запуск ядра.
    for geo_file in geoip.dat geosite.dat; do
        install -m 0644 "$PROJECT_ROOT/core/bin/$geo_file" "$PKG_ROOT/$LIB_DIR/core/bin/"
    done

    # Иконки трея приложение берёт из своего каталога по IconThemePath, а не
    # из системной темы: если их не окажется на месте, панель покажет пустой квадрат.
    for icon in tenga-proxy-disconnected tenga-proxy-connecting tenga-proxy-connected; do
        [ -f "$PKG_ROOT/$LIB_DIR/assets/icons/${icon}.svg" ] \
            || error "Иконка трея ${icon}.svg не попала в пакет"
    done
    [ -f "$PKG_ROOT/$LIB_DIR/assets/logo-inner-256.png" ] \
        || error "Логотип статус-карточки не попал в пакет"
    [ -f "$PKG_ROOT/$LIB_DIR/assets/theme/hicolor/index.theme" ] \
        || error "Тема значков приложения не попала в пакет"

    install -D -m 0755 "$PACKAGING/tenga-proxy" "$PKG_ROOT/usr/bin/tenga-proxy"
    install -D -m 0755 "$PROJECT_ROOT/core/scripts/tun_route_helper.sh" \
        "$PKG_ROOT/usr/libexec/tenga-proxy/tun-route-helper"
    install -D -m 0440 "$PACKAGING/sudoers" "$PKG_ROOT/etc/sudoers.d/tenga-proxy"
    install -D -m 0644 "$PROJECT_ROOT/assets/tenga-proxy.desktop" \
        "$PKG_ROOT/usr/share/applications/tenga-proxy.desktop"

    for size in 64 128 256; do
        src="$PROJECT_ROOT/assets/theme/hicolor/${size}x${size}/apps/tenga-proxy.png"
        [ -f "$src" ] || error "Иконка приложения ${size}x${size} не найдена"
        install -D -m 0644 "$src" \
            "$PKG_ROOT/usr/share/icons/hicolor/${size}x${size}/apps/tenga-proxy.png"
    done

    install -m 0755 "$PACKAGING/postinst" "$PACKAGING/prerm" "$PKG_ROOT/DEBIAN/"
    echo "/etc/sudoers.d/tenga-proxy" > "$PKG_ROOT/DEBIAN/conffiles"

    # Ошибка в sudoers ломает sudo целиком: файл проверяется до упаковки.
    if command -v visudo &>/dev/null; then
        visudo -cf "$PKG_ROOT/etc/sudoers.d/tenga-proxy" >/dev/null \
            || error "Правило sudoers не прошло visudo"
    fi

    # Права не зависят от umask сборщика: каталоги 0755, записи для группы нет.
    find "$PKG_ROOT" -type d -exec chmod 0755 {} +
    chmod -R go-w "$PKG_ROOT"

    success "Дерево пакета готово"
}

write_control() {
    local size
    size="$(du -sk --exclude=DEBIAN "$PKG_ROOT" | cut -f1)"

    cat > "$PKG_ROOT/DEBIAN/control" << EOF
Package: $APP_NAME
Version: $APP_VERSION
Section: net
Priority: optional
Architecture: $ARCH
Installed-Size: $size
Depends: python3 (>= 3.11), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.5), python3-requests, libcap2-bin, iproute2, sudo
Recommends: systemd-resolved
Maintainer: Artem G. <vebulogmetra@yandex.ru>
Homepage: https://github.com/vebulogmetra/tenga-proxy
Description: Proxy client with xray-core backend
 Tenga Proxy connects through VLESS, Trojan, VMess, Shadowsocks, SOCKS
 and HTTP servers in system proxy or TUN mode. GTK 4 and libadwaita
 interface with a tray icon.
EOF
}

build_deb() {
    info "Сборка deb-пакета..."

    local output="$PROJECT_ROOT/dist/${APP_NAME}_${APP_VERSION}_${ARCH}.deb"
    mkdir -p "$PROJECT_ROOT/dist"
    rm -f "$output"

    dpkg-deb --root-owner-group -Zxz --build "$PKG_ROOT" "$output" >/dev/null

    success "Пакет создан: $output"
    echo
    echo "Размер: $(du -h "$output" | cut -f1)"
    echo "Установка: sudo apt install ./dist/$(basename "$output")"
    echo
}

main() {
    echo "=========================================="
    echo "         Tenga Proxy - deb Build          "
    echo "=========================================="
    echo

    check_deps
    stage_files
    write_control
    build_deb
}

main "$@"
