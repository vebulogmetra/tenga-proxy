#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warning() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

INIT_FILE="$PROJECT_ROOT/src/__init__.py"
BUILD_SCRIPT="$PROJECT_ROOT/core/scripts/build_appimage.sh"

if [ ! -f "$INIT_FILE" ]; then
    error "Файл $INIT_FILE не найден"
fi

if [ ! -f "$BUILD_SCRIPT" ]; then
    error "Файл $BUILD_SCRIPT не найден"
fi

get_current_version() {
    if grep -q '__version__ = ' "$INIT_FILE"; then
        grep '__version__ = ' "$INIT_FILE" | sed "s/.*__version__ = \"\(.*\)\".*/\1/"
    else
        error "Не удалось найти версию в $INIT_FILE"
    fi
}

update_init_version() {
    local new_version="$1"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s/__version__ = \".*\"/__version__ = \"$new_version\"/" "$INIT_FILE"
    else
        # Linux
        sed -i "s/__version__ = \".*\"/__version__ = \"$new_version\"/" "$INIT_FILE"
    fi
    success "Версия обновлена в $INIT_FILE"
}

update_build_script_version() {
    local new_version="$1"
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        sed -i '' "s/APP_VERSION=\".*\"/APP_VERSION=\"$new_version\"/" "$BUILD_SCRIPT"
    else
        # Linux
        sed -i "s/APP_VERSION=\".*\"/APP_VERSION=\"$new_version\"/" "$BUILD_SCRIPT"
    fi
    success "Версия обновлена в $BUILD_SCRIPT"
}

validate_version() {
    local version="$1"
    if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        error "Неверный формат версии. Используйте формат X.Y.Z (например, 1.3.0)"
    fi
}

main() {
    echo "=========================================="
    echo "      Tenga Proxy - Bump Version          "
    echo "=========================================="
    echo
    
    # Current version
    CURRENT_VERSION=$(get_current_version)
    info "Текущая версия: $CURRENT_VERSION"
    echo
    read -p "Введите новую версию (например, 1.3.0): " NEW_VERSION
    
    if [ -z "$NEW_VERSION" ]; then
        error "Версия не введена"
    fi
    
    NEW_VERSION=$(echo "$NEW_VERSION" | xargs)
    
    validate_version "$NEW_VERSION"
    
    if [ "$CURRENT_VERSION" == "$NEW_VERSION" ]; then
        warning "Новая версия совпадает с текущей. Продолжить? (y/N)"
        read -r response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            info "Отменено"
            exit 0
        fi
    fi
    
    echo
    info "Обновление версии с $CURRENT_VERSION на $NEW_VERSION..."
    
    update_init_version "$NEW_VERSION"
    update_build_script_version "$NEW_VERSION"
    
    echo
    success "Версия успешно обновлена!"
    echo
    
    read -p "Запустить сборку AppImage? (Y/n): " BUILD_RESPONSE
    BUILD_RESPONSE=${BUILD_RESPONSE:-Y}
    
    if [[ "$BUILD_RESPONSE" =~ ^[Yy]$ ]] || [ -z "$BUILD_RESPONSE" ]; then
        echo
        info "Запуск сборки AppImage..."
        echo
        bash "$BUILD_SCRIPT"
    else
        info "Сборка пропущена. Запустите вручную: $BUILD_SCRIPT"
    fi
}

main "$@"
