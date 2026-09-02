# Установка

## Требования

Для работы Tenga Proxy требуются:

- Python 3.11+
- Зависимости из `pyproject.toml`
- Бинарник `xray` (для запуска прокси)

## Установка зависимостей

### Используя uv (рекомендуется)

```bash
uv sync
```

### Используя pip

```bash
pip3 install -e .
```

## Установка xray-core

CLI и GUI требуют наличия бинарника `xray`. Он может быть:

1. **В директории проекта:** `core/bin/xray`
2. **В системном PATH:** установлен системно
3. **В AppImage:** встроен в образ

### Вариант 1: Скачать бинарник

```bash
# Скачать с https://github.com/XTLS/Xray-core/releases
# Распаковать
# Поместить в core/bin/xray
chmod +x core/bin/xray
```

### Вариант 2: Установить системно

```bash
# См. официальную документацию: https://xtls.github.io
```

## Быстрая установка

Для сборки и установки/обновления AppImage в систему:

```bash
python cli.py setup
```

- Соберёт AppImage
- Установит его в систему
- Создаст ярлык в меню приложений

После этого приложение будет доступно в меню.

## Установка окружения для разработки

Для разработки и запуска из исходников:

```bash
python cli.py setup-dev
```

- Системные зависимости
- Python venv
- Python зависимости из `pyproject.toml`
- Бинарник xray-core

## Сборка AppImage

Для создания портативного AppImage файла:

### Требования для сборки

- Системные зависимости (устанавливаются через `python cli.py setup-dev`)
- Бинарник `xray` в `core/bin/xray`

### Сборка

```bash
python cli.py build
```

Результат будет в `dist/tenga-proxy-x.AppImage`.

### Установка AppImage в систему

```bash
python cli.py install
```

После установки "Tenga Proxy" будет доступен в меню приложений.

### Удаление AppImage

```bash
python cli.py install --uninstall
```

## Системные зависимости (Ubuntu/Debian)

Интерфейсу нужна libadwaita 1.5 или новее: Ubuntu 24.04, Fedora 40,
Debian 13 и новее подходят без дополнительных репозиториев.

```bash
sudo apt update
sudo apt install -y \
    python3 \
    python3-gi \
    python3-pip \
    gir1.2-gtk-4.0 \
    gir1.2-adw-1 \
    libfuse2t64
```