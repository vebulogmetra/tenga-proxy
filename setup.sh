#!/bin/bash
#
# Setup script for Tenga Proxy
# Builds AppImage and installs it to system
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

main() {
    echo "=========================================="
    echo "          Tenga Proxy - Setup             "
    echo "=========================================="
    echo

    if [ ! -f "$SCRIPT_DIR/core/bin/sing-box" ]; then
        error "sing-box не найден в core/bin/"
        echo
        echo "Для разработки запустите:"
        echo "  core/scripts/install_dev.sh"
        exit 1
    fi

    info "Шаг 1/2: Сборка AppImage..."
    if ! "$SCRIPT_DIR/core/scripts/build_appimage.sh"; then
        error "Ошибка при сборке AppImage"
        exit 1
    fi
    
    echo
    info "Шаг 2/2: Установка в систему..."
    if ! "$SCRIPT_DIR/core/scripts/install_appimage.sh"; then
        error "Ошибка при установке"
        exit 1
    fi
    
    echo
    echo "=========================================="
    echo "          Установка завершена!            "
    echo "=========================================="
    echo
}

main "$@"
