# Разработка

В этом разделе вы найдете информацию о структуре проекта, процессе разработки и вкладе в проект.

## Структура проекта

```
tenga-proxy/
├── cli.py              # CLI интерфейс
├── gui.py              # GUI интерфейс
├── pyproject.toml      # Зависимости и настройки проекта
├── README.md           # Основная документация
├── core/               # Ядро приложения
│   ├── __init__.py
│   ├── config.py       # Конфигурация приложения
│   ├── context.py      # Контекст приложения
│   ├── logging_utils.py # Утилиты логирования
│   ├── monitor.py      # Мониторинг соединений
│   └── xray_manager.py # Управление xray-core
├── src/
│   ├── __init__.py
│   ├── db/             # Управление данными
│   │   ├── profiles.py # Управление профилями
│   │   └── data_store.py # Хранилище данных
│   ├── fmt/            # Форматирование и парсинг
│   │   ├── base.py     # Базовые классы протоколов
│   │   ├── protocols/  # Реализации протоколов
│   │   └── stream.py   # Настройки транспорта
│   ├── sys/            # Системные утилиты
│   └── ui/             # GUI компоненты
│       ├── app.py      # Главное приложение
│       ├── main_window.py # Основное окно
│       └── tray.py     # Иконка в трее
├── docs/               # Документация
└── tests/              # Тесты
```

## Установка для разработки

Для начала разработки:

```bash
# Клонирование репозитория
git clone https://github.com/vebulogmetra/tenga-proxy.git
cd tenga-proxy

# Установка зависимостей разработки
python cli.py setup-dev

# Или вручную
uv sync --all-extras
```

## Зависимости разработки

Проект использует следующие инструменты разработки:

- **uv** - менеджер пакетов
- **ruff** - линтер и форматтер
- **pytest** - фреймворк для тестирования
- **pyinstaller** - сборка установщика Windows

## Стиль кода

### Python

- Используется форматирование **Black** через **ruff**
- Следуйте стандартам **PEP 8**
- Используйте аннотации типов
- Пишите документацию к функциям и классам

### Проверка кода

```bash
# Проверить код линтером
python cli.py lint

# Исправить автоматически исправимые проблемы
python cli.py lint --fix

# Отформатировать код
python cli.py format

# Запустить все проверки
python cli.py lint-all
```

## Тестирование

### Запуск тестов

```bash
# Запустить все тесты
uv run pytest

# Запустить тесты с покрытием
uv run pytest --cov=src

# Запустить конкретный тест
uv run pytest tests/test_specific.py
```

### Написание тестов

- Тесты находятся в директории `tests/`
- Используйте `pytest` для написания тестов

## Вклад в проект

### Создание нового функционала

1. **Форкните репозиторий**
2. **Создайте ветку** для новой функции: `feature/имя-функции`
3. **Реализуйте функцию** с соответствующими тестами
4. **Обновите документацию**, если необходимо
5. **Создайте Pull Request**

## Архитектура приложения

### Контекст приложения

Класс `AppContext` управляет всеми основными зависимостями и состоянием приложения:

- `config` - настройки приложения
- `profiles` - менеджер профилей
- `xray_manager` - управление xray-core
- `proxy_state` - состояние прокси
- `monitor` - мониторинг соединений

### Контроллер приложения

`AppController` (`src/ui/controller.py`) держит оркестровку без GTK:
подключение, профили и группы, подписки, замер задержки, failover,
проверку обновлений и импорт ссылок. С интерфейсом он говорит через
протокол `Shell`, с главным потоком — через `MainLoop`
(`src/core/main_loop.py`). `TengaApplication` реализует `Shell` и
делегирует контроллеру; тесты контроллера идут без дисплея.

### Интерфейс Qt

`src/ui/qt/` — интерфейс Windows на PySide6. На Linux он запускается
`python gui.py --ui qt` после `uv sync --extra windows`. Тесты —
`make test-qt` (платформа offscreen, дисплей не нужен).

Формы и окно настроек — в `src/ui/qt/dialogs/`; правила проверки полей
общие с GTK и лежат в `src/ui/logic/`. Новое поле настроек добавляется в
обе реализации окна настроек.

На Windows окружение разработки — Git Bash, Python 3.12 с python.org и uv:
`bash core/scripts/install_dev.sh`, затем `uv run python gui.py`.

### Управление профилями

Модуль `src.db.profiles` управляет профилями и группами:

- `ProfileManager` - основной класс управления
- `ProfileEntry` - отдельный профиль
- `ProfileGroup` - группа профилей

### Форматирование и парсинг

Модуль `src.fmt` отвечает за парсинг и форматирование ссылок:

- `ProxyBean` - базовый класс для всех протоколов
- `protocols/` - реализации конкретных протоколов
- `stream.py` - настройки транспорта

## Сборка проекта

### Сборка deb-пакета

```bash
# Собрать dist/tenga-proxy_<версия>_<arch>.deb
python cli.py build

# Установить его через apt
python cli.py install
```

Сборка — `core/scripts/build_deb.sh`: исходники и xray-core в
`/usr/lib/tenga-proxy`, запуск системным Python. Лаунчер, правило sudoers и
сценарии postinst/prerm лежат в `packaging/linux/`. Пакет работает на
системных requests и urllib3 (2.31 и 2.0 в Ubuntu 24.04), поэтому CI гоняет
тесты и на этих версиях.

### Обновление версии

```bash
# Интерактивное обновление версии
python cli.py bump-version

# С указанием версии
python cli.py bump-version 1.0.0
```

## Windows

### Окружение

Интерфейс Windows — Qt (PySide6), GTK на Windows не используется. Нужны
Git for Windows (Git Bash), Python 3.12 с python.org и uv. В Git Bash:

```bash
# Python по умолчанию читает файлы в cp1252
export PYTHONUTF8=1

bash core/scripts/install_dev.sh     # uv sync --extra windows --extra dev, xray.exe, wintun.dll, геобазы
uv run python gui.py
uv run pytest -q --no-cov
QT_QPA_PLATFORM=offscreen uv run pytest -q --no-cov -m qt tests/test_ui_qt_*.py
```

### Сборка установщика

Нужен Inno Setup 6 (`ISCC.exe`; путь можно задать переменной `ISCC`).
PyInstaller сценарий ставит сам (группа `build`):

```bash
bash core/scripts/build_windows.sh
# → dist/windows/veblock-<версия>-windows-x64-setup.exe
```

В каталоге сборки два exe: `tenga-proxy.exe` (GUI) и `tenga-proxy-svc.exe`
(служба; аргументы `install`, `remove`, `cleanup`, `debug`).

### Устройство

- `src/sys/*.py` — фасады: реализацию выбирает `IS_WINDOWS` из
  `src/core/platform_info.py` при импорте фасада, код для Linux лежит в
  `src/sys/linux/`, для Windows — в `src/sys/windows/`. Имена и сигнатуры
  двух реализаций обязаны совпадать — это проверяет `tests/test_sys_facades.py`.
- Отличия интерфейса по ОС — только тексты в `src/ui/logic/platform_texts.py`:
  GTK работает на Linux, Qt — на Windows. Виджеты ОС напрямую не проверяют.
- Журнал отката сети (`src/core/net_journal.py`) общий: его пишут служба
  Windows и маршруты TUN на Linux. После падения приложения на Linux
  маршрут по умолчанию возвращается при следующем запуске.
- `src/sys/tun_access.py` проверяет, чего не хватает для TUN: на Linux —
  `cap_net_admin` у xray и правило sudo для помощника маршрутов, на
  Windows — установленная служба.
- `src/winsvc/` — служба: протокол канала, политика конфигурации, журнал
  отката, команды `netsh`/PowerShell, состояние и pipe-сервер.
- На Windows `AppContext.xray_manager` — `WindowsXrayManager`: конфиг с
  TUN-inbound запускает служба, остальные — сам GUI.
- Трей Windows — `QSystemTrayIcon` (`src/ui/qt/tray.py`) за тем же
  `TrayController`, что и трей Linux.
- `packaging/windows/` — spec PyInstaller (Qt без неиспользуемых модулей,
  без GTK), сценарий Inno Setup и `ico.py` для `tools/make_ico.py`.

### Тесты

Windows-модули импортируются и на Linux: системные вызовы внедряются или
импортируются лениво, поэтому большая часть их тестов идёт в обычном прогоне.
Тесты, которым нужна настоящая Windows, помечены маркером `windows` и вне
win32 пропускаются.

`tests/integration/` — проверка службы на живой системе (TUN, маршруты,
NRPT, откат). Нужны установленная служба и права администратора; включается
переменной `TENGA_SERVICE_TESTS=1`. Запускается в CI или на тестовой машине,
не на рабочей: маршруты на время теста перехватывают сеть.

### CI

`.github/workflows/linux.yml` на `ubuntu-24.04`: линтер, тесты,
`make test-gtk`, `make test-tray`, тесты на requests из Ubuntu, сборка
deb-пакета и его установка на раннере; по тегу `v*` пакет прикрепляется к
релизу.

`.github/workflows/windows.yml` на `windows-latest` в Git Bash с uv: тесты
Windows-кода, Qt-тесты (offscreen), полный прогон (информационный), сборка
установщика, запуск собранного `tenga-proxy.exe` с проверкой журнала,
установка службы из сборки и интеграционные тесты. По тегу `v*` установщик прикрепляется к
релизу; тег обязан совпадать с версией в `src/__init__.py`.

## Отладка

### Логирование

Логи лежат в `logs/` (в режиме разработки), в `~/.config/tenga-proxy/logs/`
(deb-пакет) или в `%LOCALAPPDATA%\tenga-proxy\logs` (Windows):

- `tenga_gui.log` - логи GUI
- `tenga_cli.log` - логи CLI
- `xray.log` - вывод xray-core

В полночь файл уходит в архив с датой в имени (`xray.log.2026-10-08`).
Хранятся логи за три дня: сегодняшний файл и два архива, остальное
удаляется при ротации и при запуске приложения.

### Переменные окружения

- `TENGA_CONFIG_DIR` - директория конфигурации
- `XDG_CONFIG_HOME` - стандартная директория конфигурации XDG

## Внесение изменений

При внесении изменений:

1. **Обновите тесты**, если это необходимо
2. **Проверьте форматирование и линтинг**
3. **Убедитесь, что все тесты проходят**
4. **Обновите документацию**, если это необходимо