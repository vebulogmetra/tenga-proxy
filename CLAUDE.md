# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Tenga Proxy - это клиент прокси для Linux с backend xray-core. Поддерживает протоколы VLESS, Trojan, VMess, Shadowsocks, SOCKS и HTTP. Имеет CLI и GTK GUI интерфейс с системным треем.

## Common Commands

### Development Setup
```bash
# Установить окружение для разработки (зависимости + xray-core)
python cli.py setup-dev

# Установить только Python зависимости
uv sync

# С dev зависимостями (pytest, ruff, coverage)
uv sync --extra dev
```

### Running
```bash
# Запустить GUI
python gui.py

# Запустить CLI
python cli.py --help
```

### Testing
```bash
# Запустить все тесты
uv run pytest

# С покрытием кода
uv run pytest --cov=src --cov-report=term-missing --cov-report=html

# Или через make
make test
make test-cov
```

### Code Quality
```bash
# Проверить код линтером (ruff)
python cli.py lint

# Исправить автоматически исправимые проблемы
python cli.py lint --fix

# Отформатировать код (ruff format)
python cli.py format

# Проверить форматирование без изменений
python cli.py format --check

# Запустить все проверки (lint + format)
python cli.py lint-all

# Или через make
make lint
make lint-fix
make format
make lint-all
```

### Building & Installation
```bash
# Собрать и установить AppImage в систему
python cli.py setup

# Только собрать AppImage
python cli.py build

# Установить AppImage в систему
python cli.py install

# Удалить AppImage из системы
python cli.py install --uninstall

# Обновить версию проекта
python cli.py bump-version 0.9.0
python cli.py bump-version 0.9.0 --build  # с автоматической сборкой
```

## Architecture

### Project Structure

```
src/
├── core/          # Ядро приложения
│   ├── config.py      # Конфигурация путей (BUNDLE_DIR, CORE_DIR, LOG_DIR)
│   ├── context.py     # AppContext - центральное состояние приложения
│   ├── xray_manager.py # Управление процессом xray-core
│   ├── monitor.py     # Мониторинг соединения и статистики
│   └── logging_utils.py # Настройка логирования
├── fmt/           # Парсинг share links и подписок
│   ├── base.py        # ProxyBean - базовый класс для всех протоколов
│   ├── parsers.py     # parse_link(), parse_subscription_content()
│   ├── stream.py      # StreamSettings (transport, TLS, Reality)
│   └── protocols/     # Реализации протоколов
│       ├── trojan_vless.py  # TrojanBean, VLESSBean
│       ├── vmess.py         # VMessBean
│       ├── shadowsocks.py   # ShadowsocksBean
│       └── socks_http.py    # SocksBean, HttpBean
├── db/            # Хранение данных
│   ├── profiles.py    # ProfileEntry, ProfileStore - управление профилями
│   ├── data_store.py  # Низкоуровневое хранилище (JSON файлы)
│   └── config.py      # Настройки (routing, VPN, DNS)
├── ui/            # GTK4 + libadwaita интерфейс
│   ├── application.py # TengaApplication - Adw.Application, действия, трей
│   ├── window.py      # MainWindow - Adw.ApplicationWindow
│   ├── pages/         # Страницы: профили, подписки, мониторинг
│   ├── widgets/       # Виджеты (статус-карточка)
│   ├── dialogs/       # Диалоги на Adw.Dialog / Adw.PreferencesDialog
│   ├── tray/          # StatusNotifierItem + com.canonical.dbusmenu
│   ├── logic/         # Логика без GTK: форматирование, задержка, формы
│   └── models/        # Модели и фильтры списков
├── sys/           # Системные функции
│   ├── proxy.py       # set_system_proxy(), clear_system_proxy()
│   ├── vpn.py         # Управление VPN подключением
│   └── single_instance.py # Контроль единственного экземпляра
└── sub/           # Обновление подписок
    └── updater.py     # SubscriptionUpdater

core/              # Директория конфигурации (в dev режиме)
├── bin/xray       # Бинарник xray-core
├── profiles/      # JSON файлы профилей
├── settings.json  # Настройки приложения
└── current_config.json # Текущая конфигурация xray
```

### Key Design Patterns

**AppContext (`src/core/context.py`)** - центральный контекст приложения:
- Хранит ссылки на ProfileStore, XrayManager, ConnectionMonitor
- Доступен через `get_context()` или `init_context()`
- Используется для координации между компонентами

**ProxyBean Hierarchy (`src/fmt/base.py`)** - иерархия классов для протоколов:
- `ProxyBean` - абстрактный базовый класс
- Каждый протокол (VLESS, Trojan, VMess и т.д.) наследуется от ProxyBean
- Методы: `try_parse_link()`, `to_share_link()`, `build_core_obj_xray()`
- Профиль может быть сериализован в JSON через `to_dict()` / `from_dict()`

**ProfileStore (`src/db/profiles.py`)** - управление профилями:
- Профили хранятся в JSON файлах в `core/profiles/`
- Группы профилей (ProfileGroup) для организации подписок
- ProfileEntry = ProxyBean + метаданные (latency, selected, group_id)

**XrayManager (`src/core/xray_manager.py`)** - управление xray-core:
- Запуск/остановка процесса xray через subprocess
- Генерация конфигурации из ProxyBean
- Мониторинг через Stats API (gRPC или HTTP)
- Получение статистики трафика

**ConnectionMonitor (`src/core/monitor.py`)** - мониторинг соединения:
- Периодическая проверка доступности proxy
- Отслеживание статуса (Disconnected, Connecting, Connected, Error)
- Уведомления об изменении статуса

### Configuration System

**Пути и окружение**:
- В dev режиме: конфигурация в `./core/`, логи в `./logs/`
- В AppImage/frozen: конфигурация в `~/.config/tenga-proxy/`
- Переменная окружения `TENGA_CONFIG_DIR` переопределяет путь к конфигурации

**Файлы конфигурации** (в `core/`):
- `settings.json` - настройки приложения (routing mode, DNS, VPN)
- `current_config.json` - активная конфигурация xray-core
- `profiles/*.json` - сохраненные профили и группы

### xray-core Integration

**Бинарник xray**:
- Поиск: bundled (PyInstaller) → core/bin/xray → PATH
- Управление: `XrayManager` запускает через subprocess
- Конфигурация: генерируется из ProxyBean через `build_core_obj_xray()`

**Stats API**:
- Адрес по умолчанию: `127.0.0.1:10085`
- Используется для получения статистики трафика
- Настраивается через `DEFAULT_STATS_API_ADDR`

### GUI Architecture

Интерфейс на GTK 4 и libadwaita 1.5, по GNOME HIG. Системная тема,
своей нет.

**TengaApplication** (`src/ui/application.py`) - главный класс:
- Наследует `Adw.Application`, `application_id="ru.tenga.Proxy"`
- Держит единый набор `Gio.SimpleAction`: их используют меню окна,
  контекстные меню, ускорители и трей — по одному пути на каждое действие
- Создаёт MainWindow и TrayController
- Показывает диалоги через `present_dialog()`: одновременно открыт один
- Управляет системным прокси через `src/sys/proxy.py`

**Трей** (`src/ui/tray/`) - своя реализация `org.kde.StatusNotifierItem`
и `com.canonical.dbusmenu` поверх `Gio.DBusConnection`. AppIndicator3 не
используется: он собран против GTK3 и в одном процессе с GTK4 не живёт.

**Логика без GTK** (`src/ui/logic/`, `src/ui/models/filters.py`,
`src/ui/tray/{dbusmenu,menu}.py`) не импортирует GTK и тестируется обычным
pytest, без дисплея.

**Single Instance**:
- Единственность обеспечивает `Gio.Application` через имя на шине сессии:
  второй запуск активирует окно первого и завершается
- `src/sys/single_instance.py` держит файловую блокировку как страховку
  от двух процессов xray там, где D-Bus недоступен

### Routing System

**Режимы маршрутизации** (`RoutingMode` in `src/db/config.py`):
- `PROXY_ONLY` - весь трафик через прокси
- `VPN_WITH_DIRECT_RULES` - VPN + правила для прямого подключения
- `VPN_WITH_PROXY_RULES` - VPN по умолчанию, но некоторые домены через прокси
- `DIRECT_WITH_PROXY_RULES` - прямое подключение, некоторые домены через прокси

**VPN Integration** (`src/sys/vpn.py`):
- Управление VPN подключением через NetworkManager
- Настройка DNS серверов для VPN
- Определение активного VPN интерфейса

## Working with Share Links

Парсинг share links через `src/fmt/parsers.py`:
```python
from src.fmt import parse_link, parse_subscription_content

# Парсинг одной ссылки
bean = parse_link("vless://...")
if bean:
    config = bean.build_core_obj_xray()  # xray-core config
    link = bean.to_share_link()  # обратно в share link

# Парсинг подписки
profiles = parse_subscription_content(content)  # List[ProxyBean]
```

## Important Notes

### Testing
- Тесты используют pytest с coverage
- Конфигурация pytest в `pyproject.toml`
- Моки для GTK компонентов и subprocess вызовов
- Тесты виджетов помечены маркером `gtk` и по умолчанию не запускаются;
  для них есть отдельная цель `make test-gtk` (нужен дисплей или `xvfb-run`)

### Code Style
- Линтер: ruff
- Форматтер: ruff format
- Конфигурация в `[tool.ruff]` в `pyproject.toml`
- Line length: 100
- Используется isort для импортов

### Logging
- Логи в `logs/` (dev) или `~/.config/tenga-proxy/logs/` (prod)
- Отдельные файлы для GUI, CLI и xray-core
- Настройка через `src/core/logging_utils.py`

### Dependencies
- Менеджер зависимостей: `uv`
- Python 3.11+
- Основные зависимости: PyGObject, grpcio, requests, psutil
- Dev зависимости: pytest, ruff, coverage

### AppImage Building
- PyInstaller для сборки в исполняемый файл
- Используется `appimagetool` для создания AppImage
- Встроенный xray binary в bundle
- Десктоп файл и иконки включены в AppImage
