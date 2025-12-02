# Tenga Proxy

Клиент прокси для Linux с поддержкой CLI и GUI интерфейсов. Использует движок [sing-box](https://github.com/SagerNet/sing-box) для туннелирования трафика.

## Поддерживаемые протоколы

- **VLESS** — включая поддержку Reality, XTLS
- **Trojan** — с TLS и без
- **VMess** — V2Ray совместимый
- **Shadowsocks** — включая методы 2022
- **SOCKS4/4a/5** — стандартные прокси
- **HTTP/HTTPS** — HTTP прокси

## Функционал

- Парсинг share links (vless://, trojan://, vmess://, ss://, socks://)
- Импорт подписок (base64, plain text)
- Генерация конфигураций sing-box
- Автоматическая настройка системного прокси (GNOME/KDE)
- Управление профилями
- Системный трей с уведомлениями (GTK)
- Мониторинг через Clash API (статистика, соединения)

## Структура проекта

```
tenga-proxy/
├── cli.py              # CLI точка входа
├── gui.py              # GUI точка входа
├── setup.sh            # Скрипт сборки и установки AppImage
├── requirements.txt    # Python зависимости
├── README.md           # Документация
├── core/
│   ├── bin/            # Бинарник sing-box
│   └── scripts/        # Скрипты сборки и установки
│       ├── build_appimage.sh    # Сборка AppImage
│       ├── install_appimage.sh  # Установка AppImage
│       └── install_dev.sh       # Установка окружения для разработки
└── src/                # Основной Python модуль
    ├── core/           # Контекст и менеджер sing-box
    ├── db/             # Хранение конфигурации и профилей
    ├── fmt/            # Парсинг и форматирование протоколов
    │   └── protocols/  # Реализации протоколов
    ├── sub/            # Работа с подписками
    ├── sys/            # Системные функции (прокси)
    └── ui/             # GTK интерфейс
```

## Установка

### Быстрая установка

Для сборки и установки AppImage в систему:

```bash
./setup.sh
```

- Соберёт AppImage
- Установит его в систему
- Создаст ярлык в меню приложений

После этого приложение будет доступно в меню.

### Установка окружения для разработки

Для разработки и запуска из исходников:

```bash
core/scripts/install_dev.sh
```

- Системные зависимости
- Python venv
- Python зависимости из `requirements.txt`
- Бинарник sing-box

Этот скрипт нужен только для разработки. Для обычного использования достаточно `./setup.sh`.

#### Установка sing-box

**Вариант 1: Собрать из исходников**
```bash
# Скачать source code с https://github.com/SagerNet/sing-box/releases
# Собрать бинарник
# Поместить в core/bin/sing-box
chmod +x core/bin/sing-box
```

**Вариант 2: Установить системно**
```bash
# См. официальную документацию: https://sing-box.sagernet.org
```

## Сборка AppImage

Для создания портативного AppImage файла:

### Требования для сборки

- Системные зависимости (устанавливаются через `core/scripts/install_dev.sh`)
- Бинарник `sing-box` в `core/bin/sing-box`

### Сборка

```bash
core/scripts/build_appimage.sh
```

Результат будет в `dist/tenga-proxy-x.AppImage`.

### Установка AppImage в систему

```bash
core/scripts/install_appimage.sh
```

После установки "Tenga Proxy" будет доступен в меню приложений.

### Удаление AppImage

```bash
core/scripts/install_appimage.sh uninstall
```

## Использование

### CLI

```bash
# Парсинг share link
python cli.py parse "vless://..."

# Парсинг с выводом JSON конфигурации
python cli.py parse "vless://..." -f json

# Загрузка подписки
python cli.py sub "https://example.com/subscription"

# Генерация конфигурации sing-box
python cli.py gen "vless://..." -o config.json

# Генерация с указанием порта
python cli.py gen "vless://..." -p 8080 -o config.json

# Добавить профиль в базу
python cli.py add "vless://..."

# Показать сохранённые профили
python cli.py list

# Запустить прокси по share link
python cli.py run "vless://..."

# Запустить прокси по порядковому номеру из списка
python cli.py run 1

# Запустить без настройки системного прокси
python cli.py run 1 --no-system-proxy

# Запустить на указанном порту
python cli.py run 1 -p 8080
```

### GUI

```bash
python gui.py
```

**Возможности GUI:**
- Системный трей с быстрым подключением/отключением
- Управление профилями (добавление, удаление, выбор)
- Уведомления о статусе подключения
- Настройки DNS, Маршрутизации
- Статистика подключений и задержки

![Основное окно приложения](assets/main-screen.png)

*Основное окно с развёрнутой вкладкой "Статистика"*

![Меню системного трея](assets/tray.png)

*Контекстное меню в системном трее*

## Конфигурация

Конфигурация хранится в `core/` проекта:

```
core/
├── settings.json       # Настройки приложения
└── profiles/
    ├── meta.json       # Метаданные профилей
    ├── groups.json     # Группы профилей
    └── profiles.json   # Профили
```

### Быстрый запуск прокси

```bash
# Запустить прокси на порту 2080 (по умолчанию)
python cli.py run "vless://..."

# Проверить работу
curl -x socks5://127.0.0.1:2080 https://ifconfig.me
curl -x http://127.0.0.1:2080 https://ifconfig.me
```


## Зависимости

### Системные (для GUI)

- `python3-gi` — Python bindings для GTK
- `gir1.2-appindicator3-0.1` или `gir1.2-ayatanaappindicator3-0.1` — индикатор в трее
- `gir1.2-notify-0.7` — уведомления
- `libfuse2t64` или `libfuse2` — для запуска AppImage

### Движок

- **sing-box** — движок туннелирования (https://github.com/SagerNet/sing-box)
