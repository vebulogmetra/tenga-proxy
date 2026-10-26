#!/bin/bash
#
# Установка собранного deb-пакета Veblock через apt: зависимости, права
# xray для TUN, помощник маршрутов и правило sudoers ставит сам пакет.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

APP_NAME="tenga-proxy"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

find_deb() {
    local arch deb
    arch="$(dpkg --print-architecture)"
    deb="$(ls -t "$PROJECT_ROOT"/dist/${APP_NAME}_*_"$arch".deb 2>/dev/null | head -1 || true)"
    [ -n "$deb" ] || error "deb-пакет не найден в dist/. Сначала запустите: python cli.py build"
    echo "$deb"
}

install_deb() {
    local deb
    deb="$(find_deb)"
    info "Установка $deb..."
    # Путь с каталогом: так apt понимает, что это файл, а не имя пакета.
    sudo apt-get install -y --reinstall "$deb"
    success "Veblock установлен. Запуск: tenga-proxy или из меню приложений"
}

uninstall_deb() {
    info "Удаление Veblock..."
    sudo apt-get remove -y "$APP_NAME"
    success "Veblock удалён"
    echo
    echo "Конфигурация сохранена в ~/.config/tenga-proxy"
    echo "Для полного удаления: rm -rf ~/.config/tenga-proxy"
}

case "${1:-install}" in
    install)
        install_deb
        ;;
    uninstall|remove)
        uninstall_deb
        ;;
    *)
        echo "Использование: $0 [install|uninstall]"
        exit 1
        ;;
esac
