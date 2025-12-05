# Tenga Proxy

Клиент прокси для Linux. Использует движок [sing-box](https://github.com/SagerNet/sing-box).

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
- Гибкая маршрутизация трафика (через VLESS, VPN или напрямую)
- Управление профилями
- Системный трей с уведомлениями (GTK)
- Мониторинг через Clash API (статистика, соединения)

## Установка

### Быстрая установка

Для сборки и установки/обновления AppImage в систему:

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

- Системный трей с быстрым подключением/отключением
- Управление профилями
- Настройки DNS, VPN и маршрутов
- Статистика подключений и задержки

![Основное окно приложения](assets/main-screen.png)

*Основное окно*

![Меню системного трея](assets/tray.png)

*Контекстное меню в системном трее*

### Быстрый запуск прокси

```bash
# Запустить прокси на порту 2080 (по умолчанию)
python cli.py run "vless://..."

# Проверить работу
curl -x socks5://127.0.0.1:2080 https://ifconfig.me
curl -x http://127.0.0.1:2080 https://ifconfig.me
```

## Зависимости

### Требования для AppImage

AppImage использует системный Python3 и требует установленных зависимостей.

#### Системные пакеты (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install -y \
    python3 \
    python3-gi \
    python3-pip \
    gir1.2-gtk-3.0 \
    gir1.2-appindicator3-0.1 \
    gir1.2-notify-0.7 \
    libfuse2t64
```

#### Python пакеты

```bash
pip3 install requests PyYAML
```

Или установите все зависимости из `requirements.txt`:

```bash
pip3 install -r requirements.txt
```
