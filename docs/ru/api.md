# API Документация

## Обзор API

Tenga Proxy предоставляет модульную архитектуру с четко определенными интерфейсами между компонентами. В этом разделе описаны основные классы и модули, которые могут быть полезны для расширения функциональности или интеграции с приложением.

## Основные модули

### Core (src/core/)

#### AppContext

Центральный класс приложения, управляющий всеми основными зависимостями и состоянием:

```python
from src.core import AppContext, init_context, get_context

# Инициализация контекста
context = init_context()

# Получение глобального контекста
context = get_context()
```

**Основные свойства:**
- `config` - настройки приложения
- `profiles` - менеджер профилей
- `xray_manager` - управление xray-core
- `proxy_state` - состояние прокси
- `monitor` - мониторинг соединений

#### XrayManager

Класс для управления xray-core:

```python
from src.core.xray_manager import XrayManager

manager = XrayManager(binary_path=None)
success, error = manager.start(config)
```

### Профили (src/db/)

#### ProfileManager

Менеджер профилей и групп:

```python
from src.db.profiles import ProfileManager

profiles = context.profiles  # из контекста приложения
profile = profiles.add_profile(bean)
```

#### ProfileEntry

Отдельный профиль:

```python
from src.db.profiles import ProfileEntry

# Свойства профиля
profile.id
profile.name
profile.proxy_type
profile.bean  # объект с настройками подключения
```

### Форматирование (src/fmt/)

#### ProxyBean

Базовый класс для всех протоколов:

```python
from src.fmt.base import ProxyBean

class MyProtocolBean(ProxyBean):
    @property
    def proxy_type(self):
        return "myprotocol"
    
    def build_outbound(self, skip_cert=False):
        # Построение конфигурации для xray-core
        pass
```

### Графический интерфейс (src/ui/)

#### TengaApp

Основное приложение GUI:

```python
from src.ui.app import TengaApp

app = TengaApp(context)
app.run()
```

## Ключевые классы и методы

### AppContext

Класс управления состоянием приложения:

- `init_context()` - инициализация глобального контекста
- `get_context()` - получение глобального контекста
- `config_dir` - директория конфигурации
- `profiles` - менеджер профилей
- `xray_manager` - менеджер xray-core
- `proxy_state` - состояние прокси
- `find_xray_binary()` - поиск бинарного файла xray-core

### ProfileManager

Класс управления профилями:

- `add_profile(bean, group_id=None)` - добавление профиля
- `get_profile(profile_id)` - получение профиля по ID
- `get_profiles_in_group(group_id)` - получение профилей в группе
- `remove_profile(profile_id)` - удаление профиля
- `load()` - загрузка профилей из файлов
- `save()` - сохранение профилей в файлы

### ProxyBean

Базовый класс для всех протоколов:

- `proxy_type` - тип протокола
- `display_name` - отображаемое имя
- `display_address` - отображаемый адрес
- `to_share_link()` - создание share-ссылки
- `try_parse_link(link)` - попытка парсинга ссылки
- `build_outbound(skip_cert=False)` - построение outbound-конфигурации
- `build_core_obj_xray(skip_cert=False)` - построение полной конфигурации для xray-core

## Расширение функциональности

### Добавление нового протокола

Для добавления нового протокола:

1. Создайте класс, наследующийся от `ProxyBean`
2. Реализуйте абстрактные методы
3. Добавьте поддержку в парсеры
4. Обновите документацию

### Интеграция с внешними системами

Приложение предоставляет API для интеграции:

- Через `AppContext` можно получить доступ ко всем основным компонентам
- Модуль `src.sys` содержит системные утилиты
- Модуль `src.sub` содержит функции работы с подписками

## Примеры использования API

### Создание профиля программно

```python
from src import init_context
from src.fmt.protocols import VLESSBean

context = init_context()

# Создание VLESS-профиля
bean = VLESSBean()
bean.try_parse_link("vless://...")

# Добавление в профили
profile = context.profiles.add_profile(bean)
context.profiles.save()
```

### Запуск прокси программно

```python
from src import init_context

context = init_context()

# Создание конфигурации
config = bean.build_core_obj_xray()["outbound"]

# Запуск xray-core
success, error = context.xray_manager.start(config)
```

## Системные утилиты

### Управление системным прокси

```python
from src.sys.proxy import set_system_proxy, clear_system_proxy

# Установка системного прокси
set_system_proxy(http_port=2080, socks_port=2080)

# Очистка системного прокси
clear_system_proxy()
```

### Управление VPN

```python
from src.sys.vpn import connect_vpn, disconnect_vpn, is_vpn_active

# Подключение к VPN
connect_vpn("connection_name")

# Проверка статуса VPN
active = is_vpn_active("connection_name")

# Отключение от VPN
disconnect_vpn("connection_name")
```