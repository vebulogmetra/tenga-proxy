# VK-туннель для Linux — исследование и план реализации

> **Для исполнителя:** использовать навык `superpowers:executing-plans`. Сначала завершить исследовательский этап; дальнейшие задачи уточнить по его результатам. Не считать Android AAR готовым Linux-ядром.

**Цель:** добавить отдельный тип профиля для подключения через TURN звонков VK, сохранив обычные подключения xray, корректную отмену, восстановление и отсутствие утечек через TUN.

**Архитектура:** предпочтительный вариант — отдельный Linux helper с WDTT-ядром и локальным защищённым каналом управления. Python управляет его жизненным циклом, GTK отображает состояние и подтверждение VK, xray использует доступный транспорт helper. Конкретный data path определяется экспериментом: Android использует in-process dialer, эквивалентность внешнему SOCKS заранее не гарантируется.

**Стек:** существующие Python/GTK4/xray; Go helper — только если исходное WDTT-ядро позволяет Linux-сборку и распространение. Способ капчи и native-зависимости выбираются после прототипа.

**Статус:** план, прототип не запускался. База сравнения: Android 1.4.5 (`8b056d4d`), desktop 0.16.2 (`a17384a`), 20.10.2026.

## Источники для исследования

Пути относительно `../tenga-proxy-android/`:

- `docs/vpn-stack/components.md`, раздел WDTT, и `docs/vpn-stack/flows.md`.
- `app/src/main/java/com/wingeon/app/service/wdtt/`: lifecycle, host callbacks, ошибки, кэш доступа и статус.
- `app/src/main/java/com/wingeon/app/ui/captcha/`: политика URL и передача результата капчи.
- `tools/build-gomobile.sh`, `tools/gomobile.lock`, `tools/libxray.version`.
- `tools/gomobile/wdttglue/glue.go`, `go.mod`, `memory.go`: обход локального сокета и установка dialer.
- Фактический источник `tunnelmobile` и его закреплённый revision определить по build-скриптам; не придумывать URL upstream.

Для сети и зависимостей использовать актуальные первичные источники на момент реализации. Android UI и changelog подтверждают поведение продукта, но не совместимость Go-ядра с Linux.

## Выбор подхода

| Подход | Преимущества | Ограничения |
|---|---|---|
| Отдельный helper-процесс | Изоляция падений, понятная отмена, независимое тестирование | Нужен поддерживаемый внешний data path и защищённый IPC |
| Встраивание Go через shared library | Можно приблизиться к Android dialer | ABI, потоки/callbacks, сборка и освобождение памяти усложняются |
| Отдельное внешнее приложение | Минимум интеграции | Нельзя надёжно управлять статусом, credentials и восстановлением |

Начать с helper. Если его data path несовместим с ядром, оформить решение по shared library отдельным дополнением; не маскировать ограничение цепочкой непроверенных прокси.

## Общие требования

- Общий план `2026-10-20-desktop-android-parity.md`: переиспользовать маскирование журналов, политику URL, отслеживание применённых настроек и сериализованное переподключение.
- Код разбора, выбора состояния и retry — GTK-независимый. Android VpnService, Binder и Keystore не переносить.
- На каждом этапе сначала регрессионные тесты, затем минимальная реализация и целевая проверка; один логический коммит на задачу. Сеть VK не использовать в обычных unit-тестах.
- Не хранить реальные ссылки звонков, токены и ответы капчи в репозитории, аргументах процесса, диагностическом конфиге и журнале.
- Тесты с TUN и изменением маршрутов проводить в отдельном namespace/VM, не менять рабочую сессию пользователя.

## Этап 0. Проверка реализуемости — обязательное условие

### Задача 0.1. Источник, лицензия и Linux-сборка

**Создать:** `docs/research/2026-10-20-wdtt-linux-feasibility.md`.

1. Найти точный source/revision WDTT и xray glue, проверить лицензии исходников и native-зависимостей, возможность поставки внутри AppImage.
2. Составить список Android-specific вызовов: protect(fd), captcha callback, сетевые события, хранилище и logging. Для каждого определить Linux-эквивалент.
3. В отдельном временном build-каталоге собрать минимальную Linux amd64-цель; arm64 включать только если этот desktop target реально поддерживается проектом.
4. Записать команды, toolchain, revision, hashes и результат. Исходный Android AAR в desktop не копировать.
5. Коммит документа: `docs: assess WDTT Linux build feasibility`.

**Выход:** воспроизводимая сборка либо конкретный список препятствий. Если лицензия или обязательная зависимость не позволяет поставку, следующие этапы остаются неисполненными с объяснением причины.

### Задача 0.2. Минимальный data path и капча

**Предлагаемые файлы:** `tools/wdtt-prototype/README.md`, `tools/wdtt-prototype/` — исходники только после выбора upstream API.

1. На тестовом сервере/звонке проверить: запуск сессии → готовый поток → запрос через туннель → остановка → немедленный повторный запуск.
2. Проверить, предоставляет ли ядро настоящий внешний SOCKS endpoint; выяснить TCP, UDP и DNS-возможности. Если доступен только in-memory dialer, проверить необходимую модификацию desktop xray или shared library.
3. Воспроизвести запрос капчи, отмену и timeout. Определить, можно ли безопасно получить результат через внешний браузер; наличие браузера само по себе не решает возврат результата.
4. Сравнить три режима до VK: auto/UDP/TCP, проверить отказ UDP и fallback TCP. Не переносить численные retry-константы без проверки текущего ядра.
5. Измерить время подключения, память после stop и восстановление после потери сети. Для живого опыта использовать отдельно предоставленные тестовые credentials, не искать их в пользовательских файлах.
6. В исследовании зафиксировать выбранную схему, ограничения и критерий готовности. Коммит: `docs: record WDTT Linux prototype results`.

**Решение о продолжении:** сборка воспроизводится, трафик действительно проходит, stop прерывает start, капча реализуема, лицензии позволяют поставку. При несовпадении архитектуры переписать последующие шаги до кода продукта.

## Этап 1. Helper и управление процессом

### Задача 1.1. Версионированный управляющий протокол

**Предлагаемые файлы:** `core/wdtt-helper/` (если нужен собственный Go wrapper), `src/core/wdtt_protocol.py`, `tests/test_core_wdtt_protocol.py`.

1. Описать протокол с `protocol_version`, `request_id`, `session_id`, командами start/stop/submit_captcha и событиями status/error/captcha/stopped. Определить ограничение длины сообщения и таймаут ответа.
2. Предпочесть stdin/stdout или Unix socket в приватном каталоге. Логи отделить от машинного протокола. Публичный TCP control endpoint не открывать.
3. Credentials передавать через приватный pipe/IPC. Если data endpoint — SOCKS, проверить поддержку аутентификации, ограничить loopback, использовать одноразовый пароль; Unix socket предпочтительнее при поддержке обеих сторон.
4. Тесты: чужой/устаревший session_id, повреждённый JSON, неизвестное событие, переполненное сообщение, закрытие pipe, утечка secrets. Проверить настоящий helper контрактными тестами.
5. Проверка: `uv run pytest tests/test_core_wdtt_protocol.py -q`; Go-тесты — `(cd core/wdtt-helper && go test ./...)`, если создан Go wrapper.
6. Коммит: `feat(core): define WDTT helper protocol`.

### Задача 1.2. Менеджер сессии и единая отмена

**Создать:** `src/core/wdtt_manager.py`, `tests/test_core_wdtt_manager.py`.
**Изменить:** `src/core/connection.py`, `src/core/context.py`.

1. Состояния: stopped, starting, awaiting_captcha, connected, recovering, stopping, failed. Каждой попытке дать generation/session_id.
2. С fake helper проверить start/stop, stop во время start, повторный start, запоздалый callback, crash и timeout. Старое событие не переводит новую сессию в connected.
3. Shutdown: отменить ожидания → остановить xray/зависимые запросы в корректном порядке → остановить helper → дождаться завершения → ограниченный kill при зависании → удалить endpoint и временные файлы.
4. Подключение считать готовым после требуемой готовности потоков и проверки data path, а не по одному живому процессу.
5. Проверка: `uv run pytest tests/test_core_wdtt_manager.py tests/test_core_connection.py tests/test_core_context.py -q`.
6. Коммит: `feat(core): manage WDTT session lifecycle`.

## Этап 2. Профили и конфигурация трафика

### Задача 2.1. Модель и импорт

**Создать:** `src/fmt/protocols/wdtt.py`, `tests/test_fmt_wdtt.py`.
**Изменить:** `src/fmt/parsers.py`, `src/fmt/__init__.py`, `src/db/profiles.py`, `src/ui/logic/forms.py`; `src/fmt/app_links.py` из общего плана.

1. Поддержать реальные форматы `wdtt://connect`, `wingeon://connect`, `veblock://connect` после изучения Android parser. Ограничить длину и типы параметров.
2. Отделить параметры ноды от персональных ссылок звонков. Внешняя подписка не подменяет ручные ссылки при обновлении.
3. Тесты: все алиасы, percent-encoding, неверный порт/ключ/тип, round-trip, старый JSON, неизвестный протокол, sync подписки и сохранение персональных настроек.
4. Импорт не запускает VK/API/капчу. При отсутствии helper профиль хранится с объяснением недоступности подключения.
5. Проверка: `uv run pytest tests/test_fmt_wdtt.py tests/test_fmt_app_links.py tests/test_db_profiles.py tests/test_sub_updater.py -q`.
6. Коммит: `feat(fmt): import WDTT profiles and preserve call links`.

### Задача 2.2. Интеграция с xray, TUN и DNS

**Изменить:** `src/core/config_builder.py`, `src/core/connection.py`, `src/core/health_probe.py`, `src/core/batch_probe.py`, `src/sys/tun_route.py`.
**Создать:** `tests/test_core_wdtt_config.py`, `tests/test_core_wdtt_routing.py`.

1. Реализовать только data path, подтверждённый этапом 0. Проверить, как xray получает адрес ноды, как идут DNS и UDP и что значит health probe для этой схемы.
2. Управляющий трафик VK/TURN/helper направлять вне собственного TUN через физический интерфейс/маршрут, сохраняя корректную маршрутизацию пользовательского трафика. Смена default interface не должна оставлять маршрут через старую сеть.
3. Проверить совместимость с системным прокси, split-DNS и режимом NetworkManager «VPN поверх». Неподдерживаемое сочетание явно блокировать до старта.
4. Отдельный массовый probe не должен открывать капчи или создавать множество звонков. До появления безопасного способа WDTT исключать из пакетного замера с объяснением; активный профиль проверять через готовую сессию.
5. Проверка: `uv run pytest tests/test_core_wdtt_config.py tests/test_core_wdtt_routing.py tests/test_core_connection.py tests/test_core_dns_config.py tests/test_core_batch_probe.py tests/test_fmt_xray_config_valid.py -q`.
6. Ручной сетевой тест в namespace/VM: отсутствие петли и утечек до подключения, при reconnect и после stop. Коммит: `feat(core): route WDTT connections through the desktop stack`.

## Этап 3. Капча, доступ и интерфейс

### Задача 3.1. Безопасное подтверждение VK

**Создать:** `src/core/wdtt_captcha.py`, `src/ui/dialogs/wdtt_captcha.py`, `tests/test_core_wdtt_captcha.py`, `tests/test_ui_dialogs_wdtt_captcha.py`.

1. Реализовать способ подтверждения из этапа 0. Если нужен WebKitGTK, зафиксировать минимальную версию, поставку и graceful degradation при отсутствии зависимости. Не добавлять WebView до проверки необходимости.
2. Валидировать HTTPS URL, origin и все переходы по списку из действующего VK-flow; исключить userinfo, file/data/javascript URI и произвольный JS bridge.
3. Результат связывать с session_id; отмена, закрытие окна, timeout, stop и падение browser process завершают ожидание ровно один раз.
4. Не логировать URL с токенами, cookies и ответ капчи. Закрывать browser context и очищать временные данные после завершения.
5. Настройки: автоматическое открытие, timeout, ручное действие «Подтвердить». Изменения применять согласно snapshot общего плана.
6. Проверка: `uv run pytest tests/test_core_wdtt_captcha.py -q`, `make test-gtk`; реальные подтверждение/отмена/timeout — отдельно.
7. Коммит: `feat(ui): handle VK tunnel confirmation safely`.

### Задача 3.2. Хранилище доступа

**Создать:** `src/core/wdtt_credentials.py`, `tests/test_core_wdtt_credentials.py`.
**Изменить:** `src/db/config.py`, интерфейс настроек туннеля.

1. Использовать Secret Service при доступности и совместимости размера. При отсутствии/блокировке keyring работать с памятью текущей сессии; не делать plaintext-fallback.
2. Ключ кэша связывать с набором звонков и форматом состояния, соблюдать TTL/лимиты ядра, атомарную запись и ограничение размера. Данные из Android Keystore не переносить.
3. Предусмотреть очистку доступа, отзыв/expiry, повреждённую запись и миграцию формата. Сброс кэша не удаляет профили и ссылки звонков.
4. Проверка: `uv run pytest tests/test_core_wdtt_credentials.py -q` с fake backend; ручной тест закрытого keyring.
5. Коммит: `feat(core): cache WDTT access in the desktop keyring`.

### Задача 3.3. Настройки, состояние потоков и ошибки

**Создать:** `src/ui/dialogs/wdtt_settings.py`, `src/ui/logic/wdtt_status.py`, `tests/test_ui_logic_wdtt_status.py`, `tests/test_ui_dialogs_wdtt_settings.py`.
**Изменить:** `src/ui/widgets/status_card.py`, `src/ui/pages/profiles.py`, `src/ui/tray/menu.py`, `src/db/config.py`.

1. Поля: ссылки звонков, число потоков, auto/UDP/TCP, критерий готовности, параметры капчи, сброс доступа. Допустимые значения брать из фактического API ядра, не из предположений.
2. Показывать работающие/целевые потоки, ожидание капчи, отсутствие сети и восстановление. Техническую ошибку отличать от временной потери связи.
3. Экран специфичных настроек показывать при наличии WDTT-профиля; доступ из его меню. Подключение/отключение из трея использует тот же manager.
4. Тестировать состояния и ошибки без реального helper; проверить клавиатурную навигацию и длинные сообщения. Снимки всех основных состояний — в `docs/screenshots/`.
5. Проверка: `uv run pytest tests/test_ui_logic_wdtt_status.py -q`, `make test-gtk`, `make test-tray`.
6. Коммит: `feat(ui): expose VK tunnel settings and runtime status`.

## Этап 4. Восстановление, сборка и выпуск

### Задача 4.1. Сеть, резервные звонки и failover

**Изменить:** `src/core/wdtt_manager.py`, `src/core/failover.py`, `src/core/monitor.py`.
**Создать:** `tests/test_core_wdtt_recovery.py`.

1. События сети ускоряют восстановление; отсутствие сети приостанавливает лишние retries. Использовать bounded backoff с jitter и ограничением общей попытки.
2. Перебирать действительно доступные резервные звонки, учитывать capacity и сигналы rate limit ядра. Распределение потоков между TURN-серверами делегировать ядру, если оно уже реализовано.
3. Failover не уводит с WDTT во время ограниченного окна восстановления, но не отключается навсегда. Окно обосновать измерениями и сигналами API; Android-значение до 11 минут не переносить как необъяснимую константу.
4. Тесты с fake clock/network: потеря и возврат сети, все звонки недоступны, rate limit, исчерпание окна, ручное отключение во время recovery, смена профиля и повторное подключение.
5. Проверка: `uv run pytest tests/test_core_wdtt_recovery.py tests/test_core_failover.py tests/test_core_monitor.py -q`.
6. Коммит: `feat(core): recover VK tunnels without failover races`.

### Задача 4.2. Поставка и финальная приёмка

**Изменить:** скрипты сборки/AppImage в `core/`, `docs/ru/protocols.md`, `docs/ru/gui.md`, `docs/ru/installation.md`, README.
**Создать:** `tests/test_core_wdtt_assets.py`.

1. Закрепить source revisions/toolchain/checksums helper, включить лицензии. Проверить ABI/minimum glibc, права исполняемого файла, поиск путей в dev и AppImage; не скачивать исполняемый helper при первом подключении.
2. Отсутствие/неподходящая версия helper даёт понятную ошибку и не ломает обычные профили. Не включать экспериментальный тип по умолчанию до приёмки.
3. Выполнить `make test-cov`, `make lint`, `make format-check`, `make test-gtk`, `make test-tray`, `git diff --check`, `uv run python cli.py build`. Проверить реальные helper contract-тесты, а не только mock.
4. Матрица ручной проверки: системный прокси/TUN; auto/UDP/TCP; рабочая/завершённая/резервная ссылка; капча success/cancel/timeout; suspend/resume; смена Wi-Fi; отсутствие сети; helper crash; десять start/stop подряд; выход приложения при восстановлении.
5. Подтвердить отсутствие оставшихся процессов, портов и маршрутов, отсутствие secrets в логах/экспорте, возврат памяти после stop. Проверить обычные VLESS/Trojan/SS/Hysteria2 после WDTT-сессии.
6. Коммит: `build: ship and document the Linux WDTT helper`.

## Условия готовности

План считается реализованным после доказанной Linux-совместимости ядра, безопасного подключения и остановки, работоспособной капчи, восстановления с ограничениями, тестов обычных протоколов и проверки AppImage. Отдельно записать, какие сети и реальные сценарии проверены. До завершения этапа 0 сроки и точный объём native-интеграции остаются предварительными.
