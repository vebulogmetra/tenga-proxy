# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Veblock (ранее Tenga Proxy) - это клиент прокси для Linux и Windows с backend xray-core. Поддерживает протоколы VLESS, Trojan, VMess, Shadowsocks, SOCKS и HTTP. Имеет CLI и GTK GUI интерфейс с системным треем.

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

# Qt-интерфейс на Linux (нужна группа windows: uv sync --extra windows)
python gui.py --ui qt

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
# Собрать и установить deb-пакет в систему
python cli.py setup

# Только собрать deb-пакет (dist/tenga-proxy_<версия>_<arch>.deb)
python cli.py build

# Установить собранный пакет (sudo apt install)
python cli.py install

# Удалить пакет из системы (sudo apt remove)
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
│   ├── main_loop.py   # MainLoop: главный цикл как зависимость (GLib, тестовый)
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
│   ├── controller.py  # AppController - оркестровка без GTK, протокол Shell
│   ├── qt/            # Интерфейс PySide6 (Windows; на Linux — gui.py --ui qt)
│   ├── window.py      # MainWindow - Adw.ApplicationWindow
│   ├── pages/         # Страницы: профили, подписки, мониторинг
│   ├── widgets/       # Виджеты (статус-карточка)
│   ├── dialogs/       # Диалоги на Adw.Dialog / Adw.PreferencesDialog
│   ├── tray/          # StatusNotifierItem + com.canonical.dbusmenu; win32/ — трей Windows
│   ├── logic/         # Логика без GTK: форматирование, задержка, формы
│   └── models/        # Модели и фильтры списков
├── sys/           # Системные функции: фасады, реализация выбирается по ОС
│   ├── proxy.py       # set_system_proxy(), clear_system_proxy()
│   ├── vpn.py         # Управление VPN подключением
│   ├── tun_route.py, tun_dns.py # Маршруты и DNS режима TUN
│   ├── single_instance.py # Контроль единственного экземпляра
│   ├── linux/         # Реализации для Linux (NetworkManager, ip, resolvectl)
│   └── windows/       # Реализации для Windows (WinINet, PowerShell, RAS, клиент службы)
├── winsvc/        # Служба Windows TengaProxySvc: TUN, маршруты, DNS, откат
└── sub/           # Обновление подписок
    └── updater.py     # SubscriptionUpdater

packaging/windows/ # PyInstaller spec и сценарий Inno Setup
svc_main.py        # Точка входа tenga-proxy-svc.exe (служба Windows)

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

**AppController (`src/ui/controller.py`)** - оркестровка приложения без GTK:
- Подключение, профили и группы, подписки и смена адреса, замер задержки,
  failover, проверка обновлений, импорт ссылок приложения
- С интерфейсом говорит через протокол `Shell` (тосты, уведомления,
  обновление окна, подтверждения, формы), с главным потоком — через
  `MainLoop` из `src/core/main_loop.py` (`GLibLoop` в GTK, `ImmediateLoop`
  в тестах)
- `TengaApplication` — тонкая оболочка: `Gio.SimpleAction`, окно, трей,
  слот диалога, `_GtkShell`; публичные методы приложения — делегаты
- Тестируется обычным pytest с подменной оболочкой (`tests/test_ui_controller.py`)

**MainLoop (`src/core/main_loop.py`)** - главный цикл как зависимость:
`dispatch` (один раз в главном потоке), `schedule` (таймер, повтор пока
True), `cancel`. `ConnectionMonitor` и `AppController` получают его
параметром; GLib импортируется лениво при каждом вызове, чтобы подмены
в тестах действовали.

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

**Фасады `src/sys/`** - `proxy.py`, `vpn.py`, `tun_route.py` и другие
выбирают реализацию по `IS_WINDOWS` из `src/core/platform_info.py`:
`src/sys/linux/` или `src/sys/windows/`. Выбор делается при импорте фасада;
совпадение имён и сигнатур двух реализаций проверяет
`tests/test_sys_facades.py`. Windows-модули импортируются и на Linux
(pywin32, winreg и ctypes — лениво), поэтому тестируются обычным pytest.

**Отличия UI по ОС** - тексты в `src/ui/logic/platform_texts.py`, компоновка
в `src/ui/logic/platform_layout.py`. Виджеты `IS_WINDOWS` не читают; где это
допустимо, перечисляет `tests/test_ui_platform_branches.py`.

**TUN на Linux** - xray получает `cap_net_admin` через `setcap` в postinst
deb-пакета, маршрут по умолчанию переключает помощник
`/usr/libexec/tenga-proxy/tun-route-helper` через `sudo -n` (правило пакета —
для группы `sudo`). Исходный
маршрут пишется в журнал (`src/core/net_journal.py`, общий со службой
Windows) и возвращается при следующем старте, если приложение упало
(`recover_tun_routes`). `src/sys/tun_access.py` называет, чего не хватает
для TUN: это видно в настройках и в ошибке подключения.

**Windows и TUN** - TUN-интерфейс без прав администратора не создать, поэтому
на Windows `AppContext.xray_manager` — `WindowsXrayManager`
(`src/sys/windows/core_runner.py`): конфиг с TUN-inbound запускает служба
`TengaProxySvc` (`src/winsvc/`), остальные — сам GUI. Служба принимает
команды JSON-строками по named pipe `\\.\pipe\tenga-proxy-svc`, проверяет
конфиг политикой (`policy.py`), журналирует каждое изменение сети и
откатывает его при остановке, падении ядра, пропаже клиента и старте.

**ConnectionMonitor (`src/core/monitor.py`)** - мониторинг соединения:
- Периодическая проверка доступности proxy
- Отслеживание статуса (Disconnected, Connecting, Connected, Error)
- Уведомления об изменении статуса

### Configuration System

**Пути и окружение**:
- В dev режиме: конфигурация в `./core/`, логи в `./logs/`
- Из deb-пакета (`/usr/lib/tenga-proxy`) и frozen: конфигурация в `~/.config/tenga-proxy/`
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

**Qt-интерфейс** (`src/ui/qt/`) — на Windows по умолчанию, на Linux по
`--ui qt`. `QtApplication` — оболочка над тем же `AppController`:
`QAction` с именами действий GTK, `_QtShell`, `QtLoop` (главный цикл Qt
как `MainLoop`), `QtTrayItem` для `TrayController`. Выбор интерфейса —
`choose_frontend()` в `gui.py`; модули `src/ui/qt` не импортируют `gi`
и не читают `IS_WINDOWS`

**Single Instance**:
- Единственность обеспечивает `Gio.Application` через имя на шине сессии:
  второй запуск активирует окно первого и завершается
- `src/sys/single_instance.py` держит файловую блокировку как страховку
  от двух процессов xray там, где D-Bus недоступен
- На Windows шины сессии нет: единственность — именованный mutex, а второй
  запуск передаёт активацию и ссылки первому через pipe
  (`src/sys/windows/activation.py`)

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
- `make test-gtk` поднимает свою шину сессии через `dbus-run-session`: иначе
  имя `ru.tenga.Proxy` занимает установленное приложение, GApplication
  становится прокси к нему, и окно создаётся в чужом процессе. Без изоляции
  тесты окна пропускаются с объяснением, а не падают
- Тесты трея — отдельная цель `make test-tray`: они поднимают собственную
  шину через `Gio.TestDBus`, и вкладывать её в `dbus-run-session` нельзя
- Тесты Qt-интерфейса — `make test-qt`: маркер `qt`, платформа offscreen,
  PySide6 из группы `windows`. pytest-qt не используется: без PySide6 его
  плагин роняет весь pytest. Фикстура `qapp` — в `tests/conftest.py`,
  ожидание событий — `tests/support/qt.py`
- CI: `.github/workflows/linux.yml` (lint, pytest, GTK, трей, deb) и
  `.github/workflows/windows.yml`
- Тесты, которым нужна настоящая Windows, помечены маркером `windows` и вне
  win32 пропускаются. `tests/integration/` — служба на живой Windows (нужны
  установленная служба, права администратора и `TENGA_SERVICE_TESTS=1`);
  запускается в CI
- Windows-разработка — Git Bash, CPython с python.org и uv
  (`bash core/scripts/install_dev.sh` ставит `--extra windows --extra dev`).
  MSYS2 UCRT64 нужна только прежней GTK-сборке и CI до фазы 4
  (`docs/plans/2026-10-28-windows-qt-frontend-design.md`)

### Code Style
- Линтер: ruff
- Форматтер: ruff format
- Конфигурация в `[tool.ruff]` в `pyproject.toml`
- Line length: 100
- Используется isort для импортов

### Logging
- Логи в `logs/` (dev) или `~/.config/tenga-proxy/logs/` (prod)
- Отдельные файлы для GUI, CLI и xray-core
- Ротация в полночь, хранятся три дня (`LOG_RETENTION_DAYS`); вывод xray идёт
  через pipe, чтобы его файл тоже поворачивался
- Настройка через `src/core/logging_utils.py`

### Dependencies
- Менеджер зависимостей: `uv`
- Python 3.11+
- Основные зависимости: PyGObject, grpcio, requests, psutil
- Dev зависимости: pytest, ruff, coverage

### Windows Building
- `bash core/scripts/build_windows.sh` в MSYS2: PyInstaller onedir
  (`tenga-proxy.exe` и `tenga-proxy-svc.exe`), затем Inno Setup
- CI `.github/workflows/windows.yml`: тесты, сборка установщика, установка
  службы и интеграционные тесты; по тегу `v*` установщик уходит в релиз

### deb Building
- `core/scripts/build_deb.sh` (`python cli.py build`): исходники и xray-core в
  `/usr/lib/tenga-proxy`, лаунчер `/usr/bin/tenga-proxy`, запуск системным
  Python; GTK, libadwaita и requests — зависимости пакета
- `packaging/linux/`: лаунчер, правило sudoers, postinst (setcap, очистка
  следов AppImage, байт-код) и prerm
- Пакет работает на системных requests/urllib3 (2.31/2.0 в Ubuntu 24.04): CI
  гоняет тесты и на этих версиях
- AppImage больше не собирается; ярлык старой установки приложение удаляет
  при старте (`src/sys/linux/legacy_appimage.py`)

### Имя приложения
- Пользователь видит «Veblock» (`src.__app_name__`), как в Android-версии
- Технические имена остались `tenga-proxy`/`ru.tenga.Proxy`/`TengaProxySvc`:
  пакет, каталоги настроек, app id, служба, pipe, exe, AppId установщика,
  значение автозапуска, репозиторий. Их смена требует миграции —
  см. `docs/plans/2026-10-26-veblock-rebrand.md`
- `tests/test_branding.py` не пускает «Tenga Proxy» обратно в интерфейс
