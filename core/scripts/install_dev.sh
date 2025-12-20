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
    
    if [ ! -f "$PROJECT_ROOT/pyproject.toml" ]; then
        error "Файл pyproject.toml не найден!"
        exit 1
    fi

    if ! check_command uv; then
        info "uv не найден, устанавливаем..."
        if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
            error "Не удалось установить uv"
            error "Установите вручную: curl -LsSf https://astral.sh/uv/install.sh | sh"
            exit 1
        fi
        export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"
        if ! command -v uv &> /dev/null; then
            error "uv не найден после установки. Перезапустите скрипт или добавьте ~/.cargo/bin и ~/.local/bin в PATH"
            exit 1
        fi
        success "uv установлен"
    fi

    info "Установка зависимостей через uv..."
    
    if ! uv sync; then
        error "Не удалось установить зависимости через uv"
        exit 1
    fi
    
    success "Python зависимости установлены"
}

check_xray() {
    local bin_path="$PROJECT_ROOT/core/bin/xray"
    if [ -f "$bin_path" ] && [ -x "$bin_path" ]; then
        if "$bin_path" version &>/dev/null 2>&1; then
            return 0
        fi
    fi
    
    # Также проверяем системный xray
    if check_command xray; then
        return 0
    fi
    
    return 1
}

download_xray() {
    if check_xray; then
        success "xray-core найден"
        return 0
    fi
    
    info "xray-core не найден, скачиваем..."
    
    # Check arch
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)
            ARCH="64"
            ;;
        aarch64|arm64)
            ARCH="arm64-v8a"
            ;;
        *)
            error "Неподдерживаемая архитектура: $ARCH"
            exit 1
            ;;
    esac

    info "Получение информации о последней версии xray-core..."
    LATEST_VERSION=$(curl -s https://api.github.com/repos/XTLS/Xray-core/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' | sed 's/^v//')
    
    if [ -z "$LATEST_VERSION" ]; then
        error "Не удалось получить версию xray-core"
        exit 1
    fi
    
    info "Последняя версия: $LATEST_VERSION"
    
    DOWNLOAD_URL="https://github.com/XTLS/Xray-core/releases/download/v${LATEST_VERSION}/Xray-linux-${ARCH}.zip"
    
    info "Скачивание: $DOWNLOAD_URL"
    
    mkdir -p "$PROJECT_ROOT/core/bin"
    cd "$PROJECT_ROOT/core/bin"
    
    if [ -f "xray" ]; then
        warning "Найдена нерабочая версия xray-core"
        read -p "Перезаписать? (y/n): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            cd "$PROJECT_ROOT"
            return 0
        fi
        rm -f xray
    fi
    
    if ! curl -L -o xray.zip "$DOWNLOAD_URL"; then
        error "Ошибка при скачивании xray-core"
        cd "$PROJECT_ROOT"
        return 1
    fi
    
    if ! unzip -q xray.zip; then
        error "Ошибка при распаковке архива"
        rm -f xray.zip
        cd "$PROJECT_ROOT"
        return 1
    fi

    rm xray.zip

    if [ -f "xray" ]; then
        chmod +x xray
    else
        error "Бинарник xray не найден в архиве"
        cd "$PROJECT_ROOT"
        return 1
    fi

    cd "$PROJECT_ROOT"

    success "xray-core установлен в core/bin"
}

install_xray() {
    info "Установка xray-core..."
    
    if check_xray; then
        success "xray-core уже установлен"
        return 0
    fi
    
    echo
    echo "xray-core не найден. Варианты установки:"
    echo "  1. Скачать с GitHub (рекомендуется)"
    echo "  2. Пропустить (установите вручную позже)"
    echo
    
    read -p "Выберите вариант (1-2) [1]: " -n 1 -r
    echo
    
    case $REPLY in
        1|"")
            if ! download_xray; then
                error "Не удалось установить xray-core"
                exit 1
            fi
            ;;
        2)
            warning "Пропущено. Вы можете установить xray-core вручную:"
            echo "  - Поместите бинарник в core/bin/xray"
            echo "  - Или установите системно: https://github.com/XTLS/Xray-core"
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
    install_xray
    
    echo
    echo "=========================================="
    echo "          Установка завершена!            "
    echo "=========================================="
    echo
    echo "Для использования:"
    echo "  1. Используйте uv для запуска команд:"
    echo "     uv run python cli.py --help"
    echo
    echo "  2. Или активируйте виртуальное окружение:"
    echo "     source .venv/bin/activate"
    echo "     python cli.py --help"
    echo
    echo "  3. Запустите GUI:"
    echo "     uv run python gui.py"
    echo "     # или: python gui.py (после активации .venv)"
    echo
}

main "$@"
