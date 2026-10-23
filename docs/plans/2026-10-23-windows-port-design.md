# Дизайн: порт Tenga Proxy на Windows

Дата: 2026-10-23
Статус: одобрено (brainstorming с владельцем проекта); уточнено при планировании,
планы — `2026-10-23-windows-port-plan.md`
База: desktop 0.17.0 (`37ad36a`)

## Цель

Выпустить Tenga Proxy для Windows 10/11 x64 с полным паритетом с Linux:
GUI на GTK4 + libadwaita, системный трей, системный прокси, TUN-режим с
маршрутами и DNS, режимы маршрутизации с VPN, обновление ядра и приложения.

## Решения (по итогам brainstorming)

1. **Объём**: полный паритет с Linux сразу, включая TUN и VPN-интеграцию.
2. **GUI**: тот же GTK4 + libadwaita, один код UI на обе ОС. Рантайм GTK
   из MSYS2 UCRT64 поставляется в установщике (~80–120 МБ). Платформенными
   становятся только трей и единственность экземпляра.
3. **Права для TUN**: служба Windows от SYSTEM, ставится установщиком.
   GUI работает без прав и управляет службой через named pipe; UAC
   запрашивается только при установке. Аналог sudo-helper на Linux.
4. **Сборка и проверка**: GitHub Actions (`windows-latest` + MSYS2) собирает
   установщик и гоняет тесты; трей, UAC, живой TUN и VPN проверяются вручную
   на Windows VM владельца.
5. **Платформенный слой — подход A**: фасады плюс пакеты по ОС. Отвергнуты:
   интерфейс `Platform` в `AppContext` (переписывание всех вызовов и моков без
   выигрыша) и `if sys.platform` внутри модулей (каша при полном паритете).

## Что переносится без изменений

`src/fmt/`, `src/db/`, `src/sub/`, большая часть `src/core/` (сборка конфигов,
Stats API, пробы, failover, geo), `src/ui/logic/`, `src/ui/models/`, модель меню
трея `src/ui/tray/menu.py`. xray-core официально собирается под Windows.

## Что требует Windows-реализации

| Модуль | Linux | Windows |
|---|---|---|
| `src/sys/proxy.py` | gsettings, kwriteconfig5 | реестр `Internet Settings` + `InternetSetOption(REFRESH)` |
| `src/sys/vpn.py`, `resolver.py` | nmcli, `ip`, resolvectl | `GetAdaptersAddresses`, `rasdial`, службы WireGuard |
| `src/sys/tun_route.py`, `tun_dns.py` | `ip route` + sudo-helper | служба: `/1`-маршруты, NRPT |
| `src/sys/single_instance.py` | fcntl | именованный mutex |
| `src/ui/tray/` | SNI + dbusmenu по D-Bus | `Shell_NotifyIcon` через ctypes |
| `src/core/config.py` | XDG, AppImage | `%APPDATA%`, `%LOCALAPPDATA%`, `xray.exe` |
| `app_update` | ищет AppImage в релизе | ищет установщик в релизе |
| `xray_manager`, `batch_probe` | subprocess, unix-сокет статистики в `/tmp` | `CREATE_NO_WINDOW`, сокет в `%TEMP%`; в TUN ядро в службе |
| `application.py` | `GLib.unix_signal_add` | на Windows не вызывается |

## Архитектура

### Структура

```
src/sys/
├── proxy.py, vpn.py, resolver.py, tun_route.py, tun_dns.py, single_instance.py  ← фасады
├── linux/      ← нынешний код без изменений поведения
└── windows/
    ├── proxy.py            WinINet
    ├── netinfo.py          GetAdaptersAddresses / GetBestRoute2 через ctypes
    ├── vpn.py              RAS + WireGuard + обнаружение прочих адаптеров
    ├── single_instance.py  именованный mutex + pipe активации
    └── service_client.py   клиент pipe службы
src/winsvc/
    ├── protocol.py         JSON-сообщения, без зависимостей от Windows
    ├── policy.py           проверка и переписывание конфига xray
    ├── journal.py          журнал отката
    ├── netops.py           команды netsh и PowerShell (NRPT)
    ├── state.py            ядро, маршруты, DNS, откат; dispatch.py — команды
    ├── server.py           named pipe (pywin32)
    └── service.py          ServiceFramework; install.py — установка
src/ui/tray/win32/          Shell_NotifyIcon, нативное меню из menu.py
```

Фасад выбирает реализацию по `sys.platform` при импорте и сохраняет
публичные имена и типы (`set_system_proxy`, `apply_tun_routes`,
`TunRouteState`, `get_default_interface`, `connect_vpn` и т. д.).
`connection.py`, `config_builder.py` и UI почти не меняются.

### Границы процессов

- **Режим системного прокси** работает целиком в процессе GUI, без службы.
- **TUN-режим**: GUI передаёт службе готовый конфиг xray (собранный
  `config_builder`). Служба запускает `xray.exe` с wintun, ставит маршруты и
  DNS, следит за процессом и откатывает изменения. Stats API слушает
  `127.0.0.1:10085`, GUI читает статистику напрямую, как сейчас.

### Служба `TengaProxySvc`

- Работает от SYSTEM, тип запуска — автоматически с задержкой. Правила NRPT
  хранятся в реестре и переживают перезагрузку, поэтому служба должна
  стартовать при загрузке и откатить незавершённую сессию по журналу. Право
  запуска и остановки интерактивным пользователям выдаёт установщик.
- Внутри использует тот же `XrayManager`, что и GUI: с бинарником из каталога
  установки и логом в `%ProgramData%`.
- На Windows `AppContext.xray_manager` — диспетчер: конфиг с inbound `tun`
  уходит в службу, остальные запускаются локально, как на Linux.
- Запускает только свой `xray.exe` из каталога установки (рядом
  `wintun.dll`). Пути к чужим бинарникам не принимает.

### Протокол

Pipe `\\.\pipe\tenga-proxy-svc`, JSON по строкам, `{"v":1,"id":…,"cmd":…}`.
Команды повторяют вызовы, которые `connection.py` уже делает на Linux, поэтому
сам `connection.py` не меняется: на Windows фасады `src/sys/` и менеджер ядра
переадресуют вызовы службе.

| Команда | Аналог на Linux |
|---|---|
| `hello {version}` | — (версии GUI и службы должны совпадать, иначе GUI просит переустановить) |
| `core.start {config}`, `core.stop` | `XrayManager.start/stop` |
| `core.status` → `{running, exited, log}` | `XrayManager.is_running`; заодно отдаёт накопленные строки лога ядра |
| `core.stats` | `XrayManager.get_traffic`: `xray api statsquery` выполняет служба |
| `routes.apply {tun_name, proxy_host}`, `routes.restore` | `apply_tun_routes`, `restore_tun_routes` |
| `dns.apply {tun_name}` | `route_system_dns_to_tun` |
| `wireguard.list`, `wireguard.up/down {name}` | `nmcli connection up/down` для WireGuard |

Служба ничего не присылает сама. Синхронный named pipe сериализует ввод-вывод
на одном дескрипторе, поэтому push-события мешали бы ответам. Лог ядра и факт
его падения GUI получает в ответе на `core.status`, который монитор и так
опрашивает.

### Безопасность канала

- DACL пускает только SYSTEM и интерактивных пользователей (S-1-5-4).
- `policy.py` прогоняет конфиг через `config_validator`, отклоняет любые ключи
  с путями к файлам (`certificateFile`, `keyFile` и т. п.) и переписывает
  опасные поля: `log.access` и `log.error` уводятся в каталог службы. Inbound
  разрешены только `tun`, а также `socks`, `http` и `dokodemo-door` на loopback;
  API — только на `127.0.0.1`. Через службу нельзя писать файлы от имени SYSTEM
  или открыть порт наружу.
- Остаточный риск: локальный пользователь может направить трафик машины через
  свой прокси. Для однопользовательского десктопа это приемлемо, отражается в
  документации.

### Маршруты

Default-маршрут не заменяется. Добавляются `0.0.0.0/1` и `128.0.0.0/1` через
TUN и host-маршрут до IP прокси-сервера через исходный шлюз (аналог
`apply_tun_routes`). Реализация — `netsh interface ipv4 add route … store=active`:
такие маршруты не переживают перезагрузку. Интерфейсы задаются индексом, а не
именем: в именах бывают пробелы и скобки. Сведения о сети — PowerShell с
выводом в JSON, он не зависит от языка системы. Разбор вывода и сборка команд —
чистые функции.

Привязка outbound к физическому интерфейсу (`sockopt.interface`) на Windows
используется, только если её поддержку подтвердит проверка версии xray.
Основная защита от петли — host-маршрут.

### DNS

На TUN-интерфейсе ставятся DNS `TUN_DNS_ADDRESS` и низкая метрика. От утечек
через другие адаптеры (Smart Multi-Homed Name Resolution) защищает правило NRPT
`.` → адрес TUN; это аналог `resolvectl domain ~.`.

### Откат

Перед каждым изменением (маршрут, правило NRPT, метрика) служба пишет запись
в `%ProgramData%\tenga-proxy\svc-state.json`. Откат по журналу выполняется:

- при `tun.stop`;
- при падении xray;
- при обрыве pipe, если GUI не переподключился за 15 секунд;
- при старте службы, если журнал остался после краша или перезагрузки.

### Единственный экземпляр

Уникальность `Gio.Application` держится на сессионной шине D-Bus, которой на
Windows нет. На Windows приложение запускается с `NON_UNIQUE`, единственность
обеспечивает mutex `Local\ru.tenga.Proxy`. Второй запуск через pipe `activate`
просит первый показать окно и завершается.

### Трей

Скрытое HWND в отдельном потоке со своим message loop; `Shell_NotifyIcon` и
`TrackPopupMenu` через ctypes. Меню строится из модели `menu.py`, клики
вызывают существующие `Gio.SimpleAction` через `GLib.idle_add`, так что путь
каждого действия остаётся один. `.ico` генерируются из вариантов
`variants.py`. `TrayController` выбирает backend по платформе.

### VPN-режимы (`VPN_WITH_*`)

- Встроенные VPN Windows (IKEv2, L2TP, SSTP) подключаются без прав администратора.
- Встроенные VPN: список и состояние — `Get-VpnConnection`, подключение —
  `rasdial`.
- WireGuard: конфигурации в каталоге данных WireGuard доступны только SYSTEM,
  поэтому список, подъём (`wireguard.exe /installtunnelservice`) и опускание
  туннеля идут через службу.
- Интерфейс, IP и DNS VPN берутся из `GetAdaptersAddresses`.
- OpenVPN и прочие VPN только обнаруживаются по адаптеру, без управления;
  UI это показывает.

### Пути

- Конфигурация: `%APPDATA%\tenga-proxy` (`TENGA_CONFIG_DIR` по-прежнему
  переопределяет путь).
- Логи GUI: `%LOCALAPPDATA%\tenga-proxy\logs`; логи службы и xray-TUN:
  `%ProgramData%\tenga-proxy\logs`.
- `find_xray_binary` ищет `xray.exe`: bundle → каталог установки → PATH.

## Сборка и поставка

- MSYS2 UCRT64: `gtk4`, `libadwaita`, `python-gobject` из пакетов MSYS2,
  PyInstaller в том же Python. Два exe: `tenga-proxy.exe` (GUI, windowed)
  и `tenga-proxy-svc.exe` (служба, pywin32).
- Установщик на Inno Setup: Program Files, регистрация службы и права на её
  старт, ярлык в меню «Пуск», опциональный автозапуск (`HKCU\…\Run`). При
  удалении сначала откат сети через службу, затем удаление службы.
- `xray.exe`, `wintun.dll` и геобазы входят в установщик и обновляются вместе с
  приложением. `core_update` и `app_update`, как и на Linux, только сообщают о
  новой версии и ничего не устанавливают; `app_update` на Windows ищет в релизе
  установщик вместо AppImage.
- `python cli.py build` и `setup` получают ветку для Windows.

## Тестирование

- Разбор вывода `route print`/`netsh`, сборка команд, протокол, `policy.py`,
  журнал отката — чистые функции. Unit-тесты идут обычным pytest на Linux.
- CI, job `windows-latest` (раннер с правами администратора):
  - pytest, включая тесты ctypes и реестра;
  - интеграционный тест службы: установить, поднять TUN с локальным тестовым
    outbound, проверить маршруты и откат, удалить;
  - сборка установщика как артефакт.
- Вручную на VM: трей, UAC при установке, живые TUN и VPN, обновления.

## Фазы

1. **Фундамент**: пути, фасады `src/sys/`, mutex, WinINet, `xray.exe`,
   `core_update`. Приложение запускается из исходников в MSYS2 в режиме прокси.
2. **Поставка**: трей Win32, PyInstaller, Inno Setup, CI.
3. **Служба и TUN**: протокол, политика конфига, маршруты, DNS, откат.
4. **Завершение**: VPN-интеграция, обновления приложения, документация.

## Открытые вопросы для проверки при реализации

- Поддержка `sockopt.interface` в xray на Windows и минимальная версия xray с
  TUN-inbound на Windows.
- Поведение PyInstaller с GTK4/libadwaita из MSYS2 (typelibs, схемы, иконки,
  loaders gdk-pixbuf).
- Работа `Adw.StyleManager` с тёмной темой Windows.
