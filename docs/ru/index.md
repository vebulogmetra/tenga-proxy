# Tenga Proxy

**Tenga Proxy** — это клиент прокси для Linux с backend [xray-core](https://github.com/XTLS/Xray-core), который предоставляет удобный интерфейс для работы с различными протоколами прокси.

## Основные возможности

- Поддержка различных протоколов: VLESS, Trojan, VMess, Shadowsocks, SOCKS, HTTP
- Парсинг share links (vless://, trojan://, vmess://, ss://, socks://)
- Импорт подписок (base64, plain text)
- Генерация конфигураций xray-core
- Автоматическая настройка системного прокси (GNOME/KDE)
- Гибкая маршрутизация трафика (через VLESS, VPN или напрямую)
- Управление профилями
- Системный трей с уведомлениями (GTK)
- Мониторинг через Stats API (статистика)

## Быстрый старт

Для быстрой установки и запуска:

```bash
# Установка и сборка AppImage
python cli.py setup

# Запуск GUI
python gui.py

# Или запуск CLI
python cli.py --help
```

## Поддерживаемые протоколы

- **VLESS** — включая поддержку Reality, XTLS
- **Trojan** — с TLS и без
- **VMess** — V2Ray совместимый
- **Shadowsocks** — включая методы 2022
- **SOCKS4/4a/5** — стандартные прокси
- **HTTP/HTTPS** — HTTP прокси