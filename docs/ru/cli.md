# CLI

Консольный интерфейс Tenga Proxy предоставляет широкие возможности для управления прокси-соединениями.

## Парсинг ссылок

```bash
# Парсинг share link с выводом информации
python cli.py parse "vless://..."

# Парсинг с выводом JSON конфигурации для xray-core
python cli.py parse "vless://..." -f json
```

## Работа с подписками

```bash
# Загрузка и парсинг подписки (список профилей)
python cli.py sub "https://example.com/subscription"

# Вывод подписки в формате JSON
python cli.py sub "https://example.com/subscription" -f json
```

## Генерация конфигураций

```bash
# Генерация конфигурации xray-core из share link
python cli.py gen "vless://..." -o config.json

# Генерация с указанием порта прокси
python cli.py gen "vless://..." -p 8080 -o config.json
```

## Управление профилями

```bash
# Добавить профиль
python cli.py add "vless://..."

# Показать список сохранённых профилей
python cli.py ls

# Удалить профиль по ID
python cli.py rm 1
```

## Запуск прокси

```bash
# Запустить прокси по share link
python cli.py run "vless://..."

# Запустить прокси по номеру из списка (ls)
python cli.py run 1

# Запустить прокси по ID профиля
python cli.py run 123

# Запустить прокси по имени профиля
python cli.py run "My Profile"

# Запустить на указанном порту (по умолчанию 2080)
python cli.py run 1 -p 8080

# Запустить без автоматической настройки системного прокси
python cli.py run 1 --no-system-proxy

# Запустить из файла (путь к файлу со share link)
python cli.py run /path/to/link.txt
```

## Информация о версии

```bash
# Показать версию приложения и xray-core
python cli.py ver
```

## Сборка и установка

```bash
# Собрать и установить AppImage
python cli.py setup

# Только собрать AppImage
python cli.py build

# Установить AppImage в систему
python cli.py install

# Удалить AppImage из системы
python cli.py install --uninstall

# Установить окружение для разработки
python cli.py setup-dev

# Обновить версию проекта
python cli.py bump-version 0.9.0
```

## Проверка кода и форматирование

```bash
# Проверить код линтером
python cli.py lint

# Исправить автоматически исправимые проблемы
python cli.py lint --fix

# Отформатировать код
python cli.py format

# Проверить форматирование без изменений
python cli.py format --check

# Запустить все проверки (линтинг + форматирование)
python cli.py lint-all
```

## Справка

```bash
# Показать общую справку
python cli.py --help

# Показать справку по конкретной команде
python cli.py run --help
python cli.py parse --help
python cli.py build --help
python cli.py lint --help
```

## Быстрый запуск прокси

```bash
# 1. Добавить профиль из share link
python cli.py add "vless://..."

# 2. Просмотреть список профилей
python cli.py ls

# 3. Запустить прокси (по порядковому номеру из списка)
python cli.py run 1

# 4. Проверить работу прокси
curl -x socks5://127.0.0.1:2080 https://ifconfig.me
curl -x http://127.0.0.1:2080 https://ifconfig.me

# 5. Остановить прокси: нажмите Ctrl+C
```

**Примечание:** По умолчанию CLI автоматически настраивает системный прокси. Если нужно запустить только локальный прокси без изменения системных настроек, используйте флаг `--no-system-proxy`.