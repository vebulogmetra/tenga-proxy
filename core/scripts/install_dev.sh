#!/bin/bash
#
# Development environment setup script
# Installs dependencies for development
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# messages
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}


check_os() {
    info "Проверка операционной системы..."
    
    OS="$(uname -s)"
    case "${OS}" in
        Linux*)
            # Ubuntu/Debian
            if [ -f /etc/os-release ]; then
                . /etc/os-release
                if [[ "$ID" == "ubuntu" ]] || [[ "$ID" == "debian" ]]; then
                    success "Система: $PRETTY_NAME"
                    return 0
                else
                    warning "Linux система: $PRETTY_NAME"
                    warning "Установщик протестирован для Ubuntu/Debian, но может работать и на других дистрибутивах"
                    read -p "Продолжить установку? (y/n): " -n 1 -r
                    echo
                    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
                        exit 1
                    fi
                    return 0
                fi
            else
                warning "Система Linux - продолжаем"
                return 0
            fi
            ;;
        Darwin*)
            error "macOS не поддерживается."
            exit 1
            ;;
        MINGW*|MSYS*|CYGWIN*)
            error "Windows не поддерживается."
            exit 1
            ;;
        *)
            error "Неподдерживаемая операционная система: $OS"
            error "Поддерживается только Linux/Ubuntu."
            exit 1
            ;;
    esac
}


check_root() {
    if [ "$EUID" -eq 0 ]; then
        error "Не запускайте скрипт от имени root!"
        error "Скрипт сам запросит sudo при необходимости."
        exit 1
    fi
}


check_command() {
    if ! command -v "$1" &> /dev/null; then
        return 1
    fi
    return 0
}

# System deps
install_system_deps() {
    info "Проверка системных зависимостей..."
    
    MISSING_DEPS=()

    if ! check_command python3; then
        MISSING_DEPS+=("python3")
    fi

    if ! check_command pip3; then
        MISSING_DEPS+=("python3-pip")
    fi

    if ! python3 -c "import venv" 2>/dev/null; then
        MISSING_DEPS+=("python3-venv")
    fi

    if ! check_command curl; then
        MISSING_DEPS+=("curl")
    fi

    if ! check_command tar; then
        MISSING_DEPS+=("tar")
    fi

    if ! dpkg -l | grep -q "^ii.*libfuse2" && ! dpkg -l | grep -q "^ii.*libfuse2t64"; then
        MISSING_DEPS+=("libfuse2t64")
    fi

    if ! dpkg -l | grep -q "^ii.*python3-gi "; then
        MISSING_DEPS+=("python3-gi")
    fi

    if ! dpkg -l | grep -q "^ii.*gir1.2-appindicator3-0.1 " && \
       ! dpkg -l | grep -q "^ii.*gir1.2-ayatanaappindicator3-0.1 "; then
        MISSING_DEPS+=("gir1.2-ayatanaappindicator3-0.1")
    fi

    if ! dpkg -l | grep -q "^ii.*gir1.2-notify-0.7 "; then
        MISSING_DEPS+=("gir1.2-notify-0.7")
    fi

    # gsettings (GNOME) or kwriteconfig5 (KDE)
    if ! check_command gsettings && ! check_command kwriteconfig5; then
        warning "Не найдены GNOME или KDE"
        warning "Автоматическая настройка системного прокси может не работать"
    fi

    if [ ${#MISSING_DEPS[@]} -eq 0 ]; then
        success "Все системные зависимости установлены"
        return 0
    fi

    info "Необходимо установить следующие пакеты: ${MISSING_DEPS[*]}"
    read -p "Установить их сейчас? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        error "Установка отменена. Установите зависимости вручную:"
        echo "  sudo apt update"
        echo "  sudo apt install -y ${MISSING_DEPS[*]}"
        exit 1
    fi

    info "Обновление списка пакетов..."
    sudo apt update

    info "Установка зависимостей..."
    sudo apt install -y "${MISSING_DEPS[@]}"

    success "Системные зависимости установлены"
}

install_python_deps() {
    info "Проверка Python зависимостей..."
    
    if [ ! -f "$PROJECT_ROOT/requirements.txt" ]; then
        error "Файл requirements.txt не найден!"
        exit 1
    fi

    if [ ! -d "$PROJECT_ROOT/.venv" ]; then
        info "Создание виртуального окружения Python..."
        if ! python3 -m venv "$PROJECT_ROOT/.venv"; then
            error "Не удалось создать виртуальное окружение"
            error "Установите python3-venv: sudo apt install python3-venv"
            exit 1
        fi
        success "Виртуальное окружение создано"
    fi

    info "Активация виртуального окружения и установка зависимостей..."

    source "$PROJECT_ROOT/.venv/bin/activate"
    pip install -U pip setuptools wheel
    pip install -r "$PROJECT_ROOT/requirements.txt"
    
    success "Python зависимости установлены"
}

check_singbox() {
    local bin_path="$PROJECT_ROOT/core/bin/sing-box"
    if [ -f "$bin_path" ] && [ -x "$bin_path" ]; then
        if "$bin_path" version &>/dev/null 2>&1; then
            return 0
        fi
    fi
    
    # Также проверяем системный sing-box
    if check_command sing-box; then
        return 0
    fi
    
    return 1
}

download_singbox() {
    if check_singbox; then
        success "sing-box найден"
        return 0
    fi
    
    info "sing-box не найден, скачиваем..."
    
    # Check arch
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)
            ARCH="amd64"
            ;;
        aarch64|arm64)
            ARCH="arm64"
            ;;
        *)
            error "Неподдерживаемая архитектура: $ARCH"
            exit 1
            ;;
    esac

    info "Получение информации о последней версии sing-box..."
    LATEST_VERSION=$(curl -s https://api.github.com/repos/SagerNet/sing-box/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' | sed 's/^v//')
    
    if [ -z "$LATEST_VERSION" ]; then
        error "Не удалось получить версию sing-box"
        exit 1
    fi
    
    info "Последняя версия: $LATEST_VERSION"
    
    DOWNLOAD_URL="https://github.com/SagerNet/sing-box/releases/download/v${LATEST_VERSION}/sing-box-${LATEST_VERSION}-linux-${ARCH}.tar.gz"
    
    info "Скачивание: $DOWNLOAD_URL"
    
    mkdir -p "$PROJECT_ROOT/core/bin"
    cd "$PROJECT_ROOT/core/bin"
    
    if [ -f "sing-box" ]; then
        warning "Найдена нерабочая версия sing-box"
        read -p "Перезаписать? (y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            cd "$PROJECT_ROOT"
            return 0
        fi
        rm -f sing-box
    fi
    
    if ! curl -L -o sing-box.tar.gz "$DOWNLOAD_URL"; then
        error "Ошибка при скачивании sing-box"
        cd "$PROJECT_ROOT"
        return 1
    fi
    
    if ! tar -xzf sing-box.tar.gz; then
        error "Ошибка при распаковке архива"
        rm -f sing-box.tar.gz
        cd "$PROJECT_ROOT"
        return 1
    fi

    rm sing-box.tar.gz

    if [ -f "sing-box-${LATEST_VERSION}-linux-${ARCH}/sing-box" ]; then
        mv "sing-box-${LATEST_VERSION}-linux-${ARCH}/sing-box" .
        rm -rf "sing-box-${LATEST_VERSION}-linux-${ARCH}"
    fi

    chmod +x sing-box
    cd "$PROJECT_ROOT"

    success "sing-box установлен в core/bin"
}

install_singbox() {
    info "Установка sing-box..."
    
    if check_singbox; then
        success "sing-box уже установлен"
        return 0
    fi
    
    echo
    echo "sing-box не найден. Варианты установки:"
    echo "  1. Скачать с GitHub (рекомендуется)"
    echo "  2. Пропустить (установите вручную позже)"
    echo
    
    read -p "Выберите вариант (1-2) [1]: " -n 1 -r
    echo
    
    case $REPLY in
        1|"")
            if ! download_singbox; then
                error "Не удалось установить sing-box"
                exit 1
            fi
            ;;
        2)
            warning "Пропущено. Вы можете установить sing-box вручную:"
            echo "  - Поместите бинарник в core/bin/sing-box"
            echo "  - Или установите системно: https://sing-box.sagernet.org/installation/"
            ;;
        *)
            error "Неверный выбор"
            exit 1
            ;;
    esac
}


main() {
    echo "=========================================="
    echo "   Tenga Proxy - Dev Environment Setup   "
    echo "=========================================="
    echo
    
    check_os
    check_root
    install_system_deps
    install_python_deps
    install_singbox
    
    echo
    echo "=========================================="
    echo "          Установка завершена!            "
    echo "=========================================="
    echo
    echo "Для использования:"
    echo "  1. Активируйте виртуальное окружение:"
    echo "     source .venv/bin/activate"
    echo
    echo "  2. Используйте CLI:"
    echo "     python cli.py --help"
    echo
    echo "  3. Или запустите GUI:"
    echo "     python gui.py"
    echo
}

main "$@"
