# Диагностика сети на десктопе (Linux, Windows): дизайн

Дата: 2026-11-05. Статус: реализовано, отличия от этого текста — в разделе «Что вышло иначе».
План: `docs/plans/2026-11-05-network-diagnostics-desktop-plan.md`.
Источник: Android-версия Veblock (`tenga-proxy-android`), алгоритм 15, каталог целей v6,
схема экспорта 2. Документы Android, на которые опирается перенос:
`docs/plans/2026-10-20-network-diagnostics-ux-design.md`,
`2026-10-20-network-diagnostics-implementation-plan.md`, `2026-10-21-diagnostic-stage-retry.md`,
`2026-10-21-service-diagnostics.md`, `2026-10-27-network-diagnostics-result-presentation-design.md`,
`2026-10-29-network-diagnostics-dns-verdict-design.md`,
`2026-11-05-network-diagnostics-summary-and-causes-design.md` и `docs/network-diagnostics/*.md`
в репозитории Android.

## Проблема

Когда у пользователя «не работает интернет» или «не работает Telegram», десктопный клиент
ничем не помогает понять, что происходит в сети: оператор включил белые списки, подменяет
DNS, режет TLS по имени или просто нет сети. На Android эта задача решена фичей
«Диагностика сети»: пользователь нажимает «Проверить сеть», через 1–2 минуты получает
итоговую фразу («похоже, оператор включил белые списки»), три карточки этапов
(«Белые списки», «Доступ к сервисам», «DNS»), карточку причин и может скопировать текст
итога или выгрузить отчёт JSON без личных данных для поддержки.

На десктопе есть только вкладка «Диагностика» с состоянием соединения, маршрутизацией и
журналом (`src/ui/pages/monitoring.py`, окно «Диагностика — Veblock» в
`src/ui/qt/window.py`). Она отвечает на вопрос «работает ли прокси», но не «что сломал
оператор».

Цель: перенести фичу на Linux (GTK 4) и Windows (Qt) так, чтобы

- алгоритм, вердикты, тексты и формат экспорта совпадали с Android (одна поддержка читает
  отчёты с обеих платформ, один каталог целей);
- логика была без тулкита и тестировалась обычным pytest без сети;
- интерфейс в обоих тулкитах был одинаков по словарю и состояниям
  (`docs/plans/2026-11-02-shared-ui-design.md`).

## Что переносим: контракт продукта

Контракт Android переносится без изменений смысла.

- **Запуск только вручную.** Никаких фоновых проверок и истории. Одна проверка за раз;
  повторный запуск ждёт отмены предыдущей.
- **Этапы.** «Белые списки» (фазы 0–3), «Доступ к сервисам» (Telegram, Instagram, YouTube;
  фазы 4–6), «DNS» (фаза 7 плюс проверка согласованности). После завершённой проверки с
  неудачами автоматически идёт отдельный «этап причин» (`section=DETAILS`, фаза 8, срок 60 с).
  Каждую карточку можно повторить отдельно: `DiagnosticSection`
  ALLOWLIST={0,1,2,3}, SERVICES={0,4,5,6}, DNS={0,1,4,7}, DETAILS={0,1,4,8}.
- **Два маршрута.** `DIRECT` — мимо Veblock, через физический интерфейс; `ACTIVE_TUNNEL` —
  через работающий сеанс Veblock. Туннельная ветка идёт только когда ядро запущено.
- **Бюджеты.** Срок 120 с (причины — 60 с), не больше 384 попыток, не больше 8 МиБ
  трафика (резерв до ввода-вывода, без возврата), одновременно 4 пробы, на один origin — 2.
- **Вердикты.** Итог `SummaryVerdict` (MIXED_NETWORKS, NO_ACCESS, ALLOWLIST,
  PARTIAL_RESOURCES, SERVICES_BLOCKED, SOME_SERVICES_BLOCKED, DNS_PROBLEM, ALL_AVAILABLE,
  UNKNOWN), оценки этапов (`AllowlistAssessment`, `ServiceAssessment`, `DnsAssessment`,
  `CauseAssessment`), находки классификатора и коды рекомендаций — те же, что на Android.
- **Приватность.** В отчёте и тексте итога нет IP-адресов, SSID, URL, учётных данных и
  времени по часам (кроме локального времени в тексте итога). Evidence — только ключи из
  allowlist, значения не длиннее 128 символов и без управляющих символов.
- **Прерывания.** Смена сети → `NETWORK_CHANGED`, смена сеанса Veblock во время проверки →
  пробы туннеля `VPN_SESSION_CHANGED`, отмена пользователем → `USER_CANCELLED`, срок →
  `DEADLINE`. Частичный отчёт показывается всегда.

Отличия от Android перечислены в разделе «Решения» и «Вне объёма».

## Решения

| Вопрос | Решение | Почему |
| --- | --- | --- |
| Где живёт логика | Новый пакет `src/diag/` без GTK/Qt: модели, каталог, план, планировщик, пробы, оценщики, экспорт | Как `src/fmt/` и `src/ui/logic/`: тестируется pytest без дисплея; обе оболочки пользуются одним кодом |
| Насколько близко к Android | Порт 1:1 моделей, планов фаз, оценщиков, классификатора, итога и текста; имена enum и коды сохранены | Один формат отчёта для поддержки; тесты Android переносятся как сценарии |
| Каталог целей | `assets/diagnostics/targets.json` и `placements.json` копируются из Android как есть, загружаются через `get_asset_path` | Один каталог на все платформы; срок действия v6 — до 2027-01-19 |
| Прямой маршрут при TUN | Сокеты прямых проб привязываются к физическому интерфейсу: Linux `SO_BINDTODEVICE`, Windows `IP_UNICAST_IF`. Новый фасад `src/sys/netbind.py` | Иначе в TUN «прямая» проба уйдёт в туннель и ничего не покажет |
| Прямой маршрут при включённом kill switch | Прямые пробы не выполняются: `SKIPPED(SYSTEM_RESTRICTED)` без сетевых вызовов, карточки объясняют причину; туннельная ветка работает | Таблица `inet veblock` уровня `full` закрывает весь прямой трафик, ждать таймаутов 120 с бессмысленно |
| Туннельный маршрут | Через HTTP-прокси health-inbound текущего сеанса (`context.proxy_state.health_endpoint`, `requests` с `trust_env=False`, как `measure_latency`) | Уже есть, работает и при TUN на Windows (inbound входит в конфиг службы), не трогает конфиг ядра |
| Семейства адресов | Только IPv4 в версии 1 | В TUN IPv6 напрямую закрыт всегда (`ipv6_only`); оценка белых списков на Android тоже IPv4 |
| QUIC/HTTP3 | Не переносится | В стандартной библиотеке Python QUIC нет; aioquic — новая зависимость ради одной находки `QUIC_*`. На Android эта ветка требует Cronet и тоже опциональна |
| DNS-пробы | Свой wire-модуль (A/AAAA/TXT, класс CH) поверх UDP/TCP; DoH — RFC 8484 POST по HTTPS на bootstrap-адреса 1.1.1.1 и 8.8.8.8 | Как на Android (`DnsWire.kt`); без новых зависимостей, полный контроль таймаутов и размеров |
| «DNS сети» | `system_dns_servers(interface)` физического интерфейса; пусто → этап DNS `NOT_CHECKED` с объяснением | Фасад уже есть для Linux и Windows |
| Смена сети | Снимок (интерфейс по умолчанию, IPv4-адреса, DNS) каждые 3 с в фоне; изменение → `NETWORK_CHANGED` | На десктопе нет `ConnectivityManager`; опрос дешёвый |
| Смена сеанса Veblock | Токен (порт health-inbound, логин, `is_running`) проверяется до и после каждой туннельной пробы и при опросе | Пользователь может переподключиться во время проверки |
| Описание сети в итоге | «Wi-Fi» / «Ethernet» / «Сеть» плюс «Veblock подключён (TUN/Системный прокси)» или «Veblock отключён». Без оператора, SSID и captive portal | Этих данных на десктопе либо нет, либо они личные |
| Где интерфейс | Отдельное немодальное окно «Диагностика сети» в обоих тулкитах; действие `network-diagnostics`, пункт главного меню «Диагностика сети…» и кнопка «Проверить сеть…» на вкладке/в окне «Диагностика» | Результат длинный (четыре карточки и детали), на вкладку мониторинга не помещается; одна точка входа через `Gio.SimpleAction`/`QAction`, как у остальных действий |
| Состояние экрана | `src/ui/logic/diagnostics_session.py` — порт `NetworkDiagnosticsViewModel` без тулкита; виджеты только рисуют `DiagnosticsView` из `src/ui/logic/diagnostics_view.py` | Как `monitoring_view`: формы и состояния тестируются с `ImmediateLoop` |
| Экспорт | «Скопировать итог» → буфер обмена; «Экспорт отчёта…» → JSON схемы 2 через диалог сохранения файла | На десктопе нет «Поделиться»; файл — естественный способ передать поддержке |
| CLI | Команда `python cli.py diagnose [--json путь] [--section …]` поверх того же `src/diag` | Проверка в виртуалке и у пользователей без GUI; дешёвая, раз логика без тулкита |
| Имя модуля | Пакет `src/diag`, не `src/core/diagnostics*` | `src/core/diagnostics_export.py` уже занят выгрузкой журналов; не путать |

## Архитектура

```
src/diag/
├── models.py          # enum'ы и dataclass'ы отчёта, allowlist evidence
├── catalog.py         # DiagnosticTarget, загрузка targets.json, placements.json
├── plan.py            # фазы 0–8, секции, follow-up задачи, резервы байт
├── budget.py          # попытки, байты, срок — потокобезопасно
├── scheduler.py       # пул потоков, лимиты на origin, отмена, пакеты
├── runner.py          # NetworkDiagnosticRunner: запуск, события, прерывания
├── network.py         # NetworkSnapshot, NetworkWatcher, kill switch
├── session.py         # TunnelSessionSource: токен сеанса Veblock
├── export.py          # DiagnosticReportRedactor + JSON схемы 2
├── probes/
│   ├── dns_wire.py    # кодирование/разбор DNS-сообщений
│   ├── dns.py         # SystemDnsProbe, DnsTransportProbe, DohProbe
│   ├── tcp.py, tls.py # пробы причин (TCP, TLS с SNI и без)
│   ├── https.py       # HttpsProbe: DIRECT по IP с SNI, бюджет тела, тайминги
│   ├── tunnel.py      # пробы через health-inbound (requests + CONNECT)
│   ├── media.py       # Telegram og:image, YouTube ytInitialPlayerResponse
│   ├── telegram.py    # TELEGRAM_APP: TCP+TLS к DC без MTProto
│   └── support.py     # классификация исключений в DiagnosticFailure
└── assess/
    ├── allowlist.py, services.py, dns.py, causes.py
    ├── classifier.py, recommendations.py
    ├── summary.py, summary_text.py
```

Интерфейс:

```
src/ui/logic/diagnostics_session.py   # DiagnosticsSession (порт ViewModel), события → MainLoop
src/ui/logic/diagnostics_view.py      # DiagnosticsView: карточки, строки, кнопки, тексты
src/ui/dialogs/network_diagnostics.py # GTK: Adw.Window
src/ui/qt/dialogs/network_diagnostics.py # Qt: QDialog(Window)
src/ui/logic/menus.py                 # пункт меню
src/ui/controller.py                  # open_network_diagnostics(), Shell.show_network_diagnostics
src/sys/netbind.py (+ linux/, windows/) # привязка сокета к интерфейсу, тип интерфейса
cli.py                                # команда diagnose
```

### Модели (`src/diag/models.py`)

Прямой порт `DiagnosticModels.kt`, `DiagnosticRequest.kt`, `DiagnosticTarget.kt`:
`ProbeRoute`, `ProbeStage`, `ProbeStatus`, `EvidenceLevel`, `DiagnosticFailure`,
`DiagnosticTermination`, `DiagnosticSection`, `ProbeObservation`, `DiagnosticFinding`,
`DiagnosticRunContext` (`schema_version=1`, `algorithm_version=15`), `DiagnosticReport`,
`DiagnosticRequest` (`deadline_ms ≤ 120000`, `max_attempts ≤ 384`,
`max_payload_bytes ≤ 8 MiB`, `detail_target_ids ≤ 32`). Проверки инвариантов в `__post_init__`
(попытка 1..3, `elapsed_ms ≥ 0`, ключи evidence из allowlist, длина значения ≤ 128, без
управляющих символов), как `require` в Kotlin. Dataclass'ы замороженные; списки — tuple.

Платформенные поля в `NetworkDescriptor`: `kind` (wifi/ethernet/other/none),
`veblock_mode` (tun/system_proxy/None), `vpn_active` (сеанс VPN NetworkManager/RAS). Поле
`operator`/`ssid` отсутствует: его нет ни в экспорте, ни в тексте.

### Каталог (`src/diag/catalog.py`)

`assets/diagnostics/targets.json` (v6, `expires` 1800316800) и `placements.json`
копируются из Android без правок. `load_catalog()` читает и проверяет файл (ошибка в
файле — исключение при старте проверки, не при импорте); `is_stale(now)` даёт находку
`CATALOG_STALE`. `PlacementRegistry` — порт `DiagnosticPlacementRegistry.kt`: для baseline
целей проверяет, что IPv4 из ответа DNS входит в проверенные префиксы (`verifiedPlacementGroups`),
иначе цель получает `UNVERIFIED_PLACEMENT`. `dns_targets()` исключает Instagram, как в
Android. `RUSSIAN_REFERENCES` = yandex.ru, ya.ru, vk.com, ok.ru.

Обновление каталога — ручной коммит в оба репозитория; подписанных обновлений нет.

### План проб (`src/diag/plan.py`)

Порт `DiagnosticProbePlan.kt` и `ServiceProbePlanner.kt`: фазы 0–8, идентификаторы
наблюдений (`${id}-${family}-http-${attempt}`, `${id}-tunnel`,
`${id}-${family}-dns-{system|cloudflare-doh|google-doh}`, `${id}-ipv4-dns-system-2`,
`${id}-ipv4-dns-consistency`, `cloudflare-dns-{udp|tcp}-{1,2}`, `google-dns-{udp|tcp}-{1,2}`,
`cloudflare-dns-identity`, `google-dns-nxdomain`, пробы причин `${id}-tcp-{1,2}`,
`${id}-tls-{1,2}`), резервы байт (DNS 16 656, TELEGRAM_APP 4 137, медиа — страница + фрагмент,
остальное `max_bytes + 1`), follow-up задачи (tie-break третьей попытки, вторая попытка
системного DNS, согласованность DoH). Семейства — только `ipv4`; AAAA и IPv6 в плане не
появляются, но код `addressFamily` в наблюдениях остаётся, чтобы схема экспорта совпадала.

QUIC-задачи фаз не создаются; `TRANSPORT_UNSUPPORTED` не нужен, классификатор просто не
находит QUIC-наблюдений и не выдаёт `QUIC_*`.

### Планировщик и бюджеты (`scheduler.py`, `budget.py`)

`ThreadPoolExecutor(max_workers=4)`, семафоры на origin (host:port) по 2, `DiagnosticBudget`
с `threading.Lock`: `reserve_attempt()`, `reserve_bytes(n)`, `deadline_remaining()`.
Исчерпание → `SKIPPED(BUDGET)`, срок → задачи в работе `CANCELLED(DEADLINE)`, остальные
`SKIPPED(DEADLINE)`. Пакеты ≤ 160 задач, план ≤ 1024 наблюдений — те же числа, что в
`DiagnosticScheduler.kt`. Отмена: `threading.Event` плюс реестр открытых сокетов проб; «Остановить»
закрывает сокеты, чтобы не ждать таймаутов. Каждое наблюдение после завершения отдаётся
колбэком; оценщики пересчитываются по пакетам, как на Android.

### Пробы (`src/diag/probes/`)

Общее правило: сокет создаётся пробой, адрес берётся из своей DNS-пробы (или из DoH при
отказе системного DNS, как на Android — `DiagnosticAddressPolicy.kt`), небезопасные
адреса (loopback, private, link-local, multicast, 0.0.0.0) → `UNSAFE_ADDRESS`. Прямые
пробы вызывают `bind_to_interface(sock, iface, family)` до `connect`.

- **HTTPS (DIRECT).** `socket.create_connection` к IP с таймаутом, `ssl.SSLContext`
  (TLS 1.2+, проверка цепочки и имени по `hostname`, SNI=hostname), запрос `GET path`
  с `Host`, без редиректов, чтение заголовков и тела до `max_bytes`; превышение →
  `BODY_LIMIT`; `expectedStatus`/`expectedBody` → `UNEXPECTED_RESPONSE`; evidence
  `tlsVersion`, `alpn` (`h2`/`http/1.1`), `responseMatched`, `receivedBytes`, тайминги
  `tcpMs`, `tlsMs`, `headersMs`, `bodyMs`. Для `cloudflare-trace` проверяется `ip=` в
  теле без сохранения значения. Таймауты: 5 с общий, медиа 7/15 с.
- **HTTPS (ACTIVE_TUNNEL).** `requests.Session(trust_env=False)` с `proxies` из
  `ProbeEndpoint.proxy_url`, `stream=True`, чтение до `max_bytes`, таймауты 15 с
  (медиа 15/30 с). Ошибка 407 → `PROXY_AUTH`, отказ соединения с loopback →
  `PROXY_UNAVAILABLE`. Токен сеанса сверяется до и после: несовпадение →
  `VPN_SESSION_CHANGED`.
- **DNS.** `dns_wire.py`: сборка запроса (ID, RD, EDNS0 с размером 4096), разбор ответа
  (RCODE, TC, ответы A/AAAA/TXT, сжатие имён, лимит 16 КиБ). `SystemDnsProbe` — UDP к
  `system_dns_servers(iface)`, при TC — повтор по TCP, таймаут 3 с; `DnsTransportProbe` —
  UDP/TCP к 1.1.1.1 и 8.8.8.8, identity (`id.server` CH TXT, regex
  `^[A-Za-z]{3}[0-9]{0,3}$`), nxdomain (случайные 16 hex `.google.com` → NXDOMAIN);
  `DohProbe` — POST `application/dns-message` на `https://cloudflare-dns.com/dns-query`
  через 1.1.1.1 и `https://dns.google/dns-query` через 8.8.8.8 (SNI и проверка имени по
  домену, соединение по bootstrap-IP). Evidence `resolver`, `dnsRcode`, `dnsMs`,
  `validated`, `dohOverlap`, `sharedAnswer`.
- **TCP и TLS (причины).** Порт `TcpProbe.kt`/`TlsProbe.kt`: TCP connect к IP:443;
  TLS с SNI и без проверки цепочки для отличия `TLS_BLOCKED_BY_NAME` от `CONNECTION_FAILED`,
  `CERTIFICATE`, `AFTER_HANDSHAKE`. По две попытки каждой у каждой упавшей IPv4-цели и
  у контрольных целей google-web, cloudflare-trace, yandex-main.
- **Медиа.** Порт `PublicMediaProbe.kt`: Telegram — страница `t.me/telegram/319` (64 КиБ),
  `og:image` с хоста `cdnN.telesco.pe`, картинка 16 КиБ; YouTube — страница видео
  (512 КиБ), `ytInitialPlayerResponse` → URL `*.googlevideo.com`, фрагмент 16 КиБ по
  `Range`; видео jNQXAC9IVRw и aqz-KE-bpKQ. Evidence `mediaStage`, `mediaDetail`,
  `transport`. Разбор страниц — отдельные чистые функции с тестами на сохранённых
  фрагментах HTML.
- **TELEGRAM_APP.** Порт `TelegramProbe.kt`: TCP и TLS-рукопожатие к DC без MTProto; этого
  достаточно для оценки `TELEGRAM_APP` на Android, MTProto не переносится.
- **Классификация ошибок** (`support.py`): `socket.timeout` → TIMEOUT,
  `ConnectionRefusedError` → CONNECTION_REFUSED, `ConnectionResetError` → CONNECTION_RESET,
  `ssl.SSLCertVerificationError` → TLS_CERTIFICATE, прочие `ssl.SSLError` → TLS_FAILED,
  `socket.gaierror` → DNS_FAILED, `OSError` → IO, остальное — INTERNAL (наблюдение
  `FAILURE(IO)` и запись в журнал).

### Сетевой контекст (`network.py`, `session.py`)

`NetworkSnapshot` = (интерфейс по умолчанию без туннеля Veblock и VPN сеанса, его IPv4,
DNS сети, `interface_kind`). Берётся через `get_default_interface(vpn_interface,
exclude=(tun,))`, `system_dns_servers`, новый `interface_kind` фасада `netbind`
(Linux: `/sys/class/net/<iface>/wireless`; Windows: описание адаптера и
`PhysicalMediaType` из `netinfo`). Нет интерфейса → завершение сразу с `NO_NETWORK`.
`NetworkWatcher` сравнивает снимок каждые 3 с в фоне (на Windows `netinfo.invalidate()`
перед снимком); отличие → `runner.interrupt(NETWORK_CHANGED)`.

Kill switch: если `context.connection._holds_full_block()` (или состояние `BLOCKED`), прямые
задачи планируются как `SKIPPED(SYSTEM_RESTRICTED)` без ввода-вывода, классификатор даёт
`SYSTEM_RESTRICTION`, карточки показывают «Прямой трафик закрыт настройкой „Блокировать
трафик при обрыве“». Это объяснено заранее в заголовке экрана, а не только в результате.

`TunnelSessionSource.token()` → `(port, user, is_running)` из `proxy_state.health_endpoint`
или `None`, когда ядро не запущено: тогда туннельные задачи `SKIPPED(PROXY_UNAVAILABLE)`
и `compareActiveTunnel=False`.

### Оценщики (`src/diag/assess/`)

Порт 1:1 с теми же пороговыми значениями и приоритетами:

- `allowlist.py` — `DiagnosticAllowlistAssessor.kt`: пороги 3/2/6/3/2, tie-break,
  вердикты POSSIBLE/NO_PATTERN/NO_ACCESS/PARTIAL_RESTRICTIONS/INSUFFICIENT, состояния сайтов
  (AVAILABLE, UNAVAILABLE, NO_HTTP, UNVERIFIED_PLACEMENT, MISSING_REPEAT, INCONSISTENT,
  RESPONSE_REJECTED, SHARED_GROUP), счётчики РФ-ресурсов и остальных.
- `services.py` — `DiagnosticServiceAssessor.kt`: AVAILABLE/UNAVAILABLE/PARTIAL/UNKNOWN/
  NOT_CHECKED, UNAVAILABLE только при повторной неудаче (попытки 1 и 2) или полном отказе
  DNS (≥3 резолверов).
- `dns.py` — `DiagnosticDnsAssessor.kt`: факты `SystemDnsFact`, `PublicDnsFact`,
  `SecureDnsFact`, приоритет SPOOFING > INTERCEPTION > DOMAINS_HIDDEN >
  SYSTEM_NOT_RESPONDING > UNSTABLE > WORKING_DOH_BLOCKED > WORKING > UNKNOWN; подмена —
  небезопасный адрес или общая заглушка у разных владельцев, отсутствующая в DoH.
- `causes.py` — `DiagnosticCauseAssessor.kt`: `FailureCause`, контрольные цели, `topCauses`
  с обработкой равенства.
- `classifier.py` и `recommendations.py` — `DiagnosticClassifier.kt`,
  `DiagnosticRecommendations.kt`: все коды, кроме QUIC и captive portal, которые на десктопе
  просто не возникают (код в enum остаётся).
- `summary.py`, `summary_text.py` — `DiagnosticSummary.kt`, `DiagnosticSummaryText.kt`.
  Текст итога для десктопа:

```
Диагностика сети · Veblock 0.26.0 · 05.11.2026 15:36 · Linux
Сеть: Wi-Fi, Veblock подключён (TUN)
Итог: похоже, оператор включил белые списки
Белые списки: включены (РФ-ресурсы 3/4, другие 0/9)
Сервисы напрямую: 0 из 6 (Telegram 0/2, Instagram 0/2, YouTube 0/2)
DNS: работает, защищённый DNS заблокирован (сети 18/18, публичный 2/6, DoH 0/36)
Причины: чаще всего соединение обрывается при TLS (8 из 10)
Проверка завершена, проб: 238
```

Строка оператора из Android заменена на строку ОС в заголовке; остальные строки — те же
функции с теми же счётчиками.

### Runner (`runner.py`)

`NetworkDiagnosticRunner.run(request, environment, on_event)` в фоновом потоке
(`run_in_background` с `dispatch=loop.dispatch`): события `Started(context)`,
`Observation(obs)`, `Updated(report)` после каждого пакета, `Finished(report)`.
`cancel()` ставит событие отмены и закрывает сокеты. Прерывания планировщика ставят
`termination` и завершают отчёт с тем, что есть. Исключение внутри проб не роняет
проверку: наблюдение `FAILURE(IO)`, исключение в оценщиках — `INTERNAL_ERROR` с частичным
отчётом и записью в журнал.

Порт `RunNetworkDiagnostics.kt` (use case): собирает окружение (каталог, снимок сети,
источник сеанса, пробы), следит за сетью, по завершению `COMPLETED` с неудачами запускает
этап причин с `detail_target_ids` упавших IPv4-целей (≤ 32).

### Экспорт (`export.py`)

Порт `DiagnosticReportRedactor.kt` и `DiagnosticReportExporter.kt`: DTO по белому списку,
`schemaVersion: 2`, вложенные `causes`, токены целей `t1…` общие для основного отчёта и
причин, наблюдения `o1…` и `c1…`, ≤ 1 МиБ, ≤ 1024 наблюдений. В `context` — `platform`
(`linux`/`windows`) вместо `androidSdk`; поддержка читает один и тот же формат.
Файл: `veblock-diagnostics-<runId8>.json` через диалог сохранения.

## Интерфейс

Один дизайн для GTK и Qt по `docs/plans/2026-11-02-shared-ui-design.md`: словарь, действия
и состояния общие, различаются только виджеты тулкита.

**Точки входа.**

- Действие `network-diagnostics` в наборе действий (`src/ui/application.py`,
  `src/ui/qt/application.py`), сочетание `Ctrl+D`.
- Пункт «Диагностика сети…» в `MAIN_MENU` после «Проверить задержку».
- Кнопка «Проверить сеть…» на вкладке «Диагностика» (GTK) и в окне «Диагностика — Veblock»
  (Qt) рядом с «Проверить сейчас».
- В трее не показывается: окно требует внимания пользователя.

**Окно «Диагностика сети».** Немодальное, одно на приложение (повторный вызов активирует),
размер 640×720, прокручиваемое содержимое:

1. Шапка: строка сети («Wi-Fi · Veblock подключён (TUN)»), предупреждение о kill switch,
   если он держит блокировку, кнопка «Проверить сеть» / «Остановить» и индикатор
   прогресса (выполнено проб / план, этап).
2. Карточка итога: иконка состояния, фраза вердикта, рекомендации с кнопками
   (CHECK_SYSTEM_DNS → настройки DNS; USE_ACTIVE_VPN → «Подключиться» (или тост, если уже
   подключено); TRY_OTHER_PROFILE → активировать главное окно на списке серверов;
   REPEAT_STABLE_NETWORK, RETRY_LATER → «Повторить»; CHECK_SYSTEM_NETWORK — только текст).
3. Три карточки этапов и карточка причин: чип состояния (ждёт / идёт / готово / неполно),
   иконка вердикта, строки фактов, причины неполноты и кнопка «Проверить снова» для секции.
   DNS-карточка показывает три факта (DNS сети, публичный DNS, защищённый DNS).
4. Раскрывающиеся «Подробности»: списки целей с состоянием и попытками, как на Android.
5. Нижняя панель: «Скопировать итог», «Экспорт отчёта…». Активны после первого отчёта.

Тексты, подписи, порядок карточек и строки итога — порт `NetworkDiagnosticsScreen` и его
строк из `strings.xml`, собраны в `diagnostics_view.py` и `summary_text.py`; виджеты
текстов не содержат.

**Состояния экрана** (`DiagnosticsSession`): `idle`, `running(section)`,
`causes_running`, `done`, `failed(reason)`; при закрытии окна проверка отменяется, как на
Android при уходе с экрана. Повтор секции заменяет только её оценку, остальной отчёт
сохраняется; «Проверить сеть» сбрасывает всё.

**GTK.** `Adw.Window` с `Adw.ToolbarView`, карточки — `Adw.PreferencesGroup` с
`Adw.ActionRow`, детали — `Gtk.Expander`/`Adw.ExpanderRow`, прогресс —
`Gtk.ProgressBar`. Экспорт — `Gtk.FileDialog.save`.

**Qt.** `QDialog` с флагом `Qt.Window` (как окно журнала), `QScrollArea`, карточки —
`QGroupBox` с `QFormLayout`, детали — `QTreeWidget` в свёрнутом `QToolButton`,
экспорт — `QFileDialog.getSaveFileName`. Стиль берётся из `style.qss`.

**Контроллер.** `AppController.open_network_diagnostics()` создаёт `DiagnosticsSession`
(с `context`, `loop`, каталогом) и зовёт `shell.show_network_diagnostics(session)`;
оболочка открывает окно и подписывается на `session.changed`. Рекомендации, требующие
действий приложения, идут через существующие методы контроллера (`connect_selected`,
открытие настроек).

## Обработка ошибок

| Ситуация | Поведение |
| --- | --- |
| Нет интерфейса по умолчанию | Проверка завершается сразу, `termination=COMPLETED`, все пробы `SKIPPED(NO_NETWORK)`, итог «Нет сети» |
| Несколько активных сетей с разными шлюзами | `AMBIGUOUS_NETWORK` в прямых пробах, итог `MIXED_NETWORKS` |
| Kill switch `full` | Прямые пробы `SKIPPED(SYSTEM_RESTRICTED)`, предупреждение в шапке |
| Ядро не запущено | Туннельные пробы не планируются, строка «Veblock отключён», рекомендация USE_ACTIVE_VPN при неудачах |
| Переподключение во время проверки | Туннельные наблюдения после смены токена `CANCELLED(VPN_SESSION_CHANGED)`, находка `VPN_SESSION_CHANGED`, кнопка «Повторить» |
| Смена сети | `termination=NETWORK_CHANGED`, частичный отчёт, «Повторить в стабильной сети» |
| Каталог просрочен или повреждён | Просрочен — `CATALOG_STALE`, проверка идёт; повреждён — ошибка «Каталог целей повреждён» без запуска |
| Исключение в пробе | Наблюдение `FAILURE(IO)`, журнал; проверка идёт дальше |
| Исключение в оценщике | `termination=INTERNAL_ERROR`, частичный отчёт, журнал |
| Привязка к интерфейсу не удалась (`OSError`) | Прямые пробы в TUN → `SKIPPED(SYSTEM_RESTRICTED)` с evidence `networkType`; без TUN привязка не нужна и ошибка игнорируется |
| Диалог сохранения отменён | Ничего не происходит, без тоста |

## Тестирование

- **Логика без сети** (`tests/test_diag_*.py`): модели и инварианты, план фаз и
  идентификаторы (сравнение с `DiagnosticProbePlanTest.kt`), бюджеты и планировщик с
  поддельными пробами (отмена, срок, лимит байт, лимит на origin), все оценщики на
  сценариях из Kotlin-тестов, классификатор, итог и текст, редактор экспорта (нет IP,
  размер, токены).
- **Пробы на локальных серверах** (`tests/test_diag_probes.py`): HTTPS — `http.server`
  в потоке с самоподписанным сертификатом из `tests/support/certs`, собственный доверенный
  CA в контексте; DNS — поддельный UDP/TCP сервер на loopback с задаваемыми ответами
  (TC, NXDOMAIN, TXT); DoH — тот же локальный HTTPS. Проверяются тайминги, лимит тела,
  коды ошибок, закрытие сокетов при отмене. Публичная сеть в тестах не используется.
- **Фасад `netbind`**: добавляется в `FACADES` в `tests/test_sys_facades.py`;
  `bind_to_interface` на Linux проверяется на `lo` с `SO_BINDTODEVICE` (без прав), на
  Windows — через подменённый `setsockopt`.
- **Сессия и представление**: `DiagnosticsSession` с `ImmediateLoop` и поддельным runner:
  автозапуск причин, повтор секции, отмена при закрытии, формирование `DiagnosticsView`.
- **Виджеты**: маркеры `gtk` и `qt` — открытие окна, кнопки по состояниям, экспорт в
  временный файл.
- **Контроллер**: `tests/test_ui_controller.py` — действие открывает окно, повтор активирует
  уже открытое.
- **Виртуалка** (`tests/vm/`): сценарий «диагностика при TUN» на установленном deb:
  прямые пробы уходят через физический интерфейс (видно по `ss`/`nft` счётчикам), туннельные
  — через xray. Сценарий с kill switch: прямые пробы `SKIPPED`.
- На машине разработчика живой сеанс TUN (`xray0`): xray с TUN не запускать.

## Вне объёма версии 1

- QUIC/HTTP3 и находки `QUIC_TEST_FAILED`, `QUIC_NOT_CONFIRMED`.
- IPv6 и семейство `ipv6` в плане.
- MTProto-проба Telegram (на Android тоже только TCP+TLS к DC).
- Контрольные узлы (`CONTROL` purpose) и подписанные обновления каталога.
- Captive portal, Private DNS, имя оператора, SSID.
- История проверок, фоновый запуск, уведомления в трее.
- Диагностика здоровья туннеля (`2026-11-04-tunnel-health-design.md` Android) — другая фича.

## Что вышло иначе

Спорные места решались в пользу Android: отчёты с обеих платформ читает одна поддержка.

- Полная проверка — `section=None` и фазы 0..7, секции `ALL` нет; разбор причин ведёт
  `DiagnosticsSession`, как ViewModel на Android, а помощники лежат в `runner.py`.
- HTTPS — свой клиент HTTP/1.1 на сокете с `CONNECT` через health-inbound, не `requests`:
  нужны привязка сокета, лимит тела и этапы TCP/TLS. Планировщик — свои потоки-демоны.
- Ошибка каталога не исключение, а отчёт `INTERNAL_ERROR` с наблюдением `run-error`.
- В отчёте на верхнем уровне есть `platform`; подписи публичных целей оставлены, как на
  Android, а адресов и URL нет. EDNS0 в DNS-пробах нет, как на Android.
- `diagnose` работает только из исходников: `cli.py` в deb не входит. У него нет данных
  сеанса GUI: сравнения через туннель нет, блокировку трафика он не видит.
- Смена сети проверяется раз в секунду, а не раз в 3 с. Строка сети без «(TUN)», чипов
  этапов «Ожидает»/«Идёт» нет: прогресс показывают счётчики, как на Android.
- Отдельной карточки «Причины» нет: итог в сводке, причины по целям — в строках карточек.
- Сценарии на настоящем TUN (`diag_probe.py`, поскольку `cli.py` в deb нет) показали три вещи.
  Привязка работает: прямой TCP и DNS выходят с адреса физической сети, рядом с таблицей
  `ipv6_only`. Обход возможен, только пока у интерфейса есть свой маршрут по умолчанию: без него
  (исходный маршрут был без метрики и помощник его заменил) прямые пробы не идут вовсе, и это
  `SKIPPED(SYSTEM_RESTRICTED)`, а не «нет сети». Поэтому `ENETUNREACH` больше не считается
  ограничением туннеля: при живом маршруте это ответ сети. Пробы, зависящие от DNS, при запрете
  наследуют `SYSTEM_RESTRICTED`, а не `DNS_FAILED`.
- В лаборатории цели резолвятся в адреса 203.0.113.0/24: политика считает их небезопасными, и
  цепочка TCP/TLS/HTTP по именам там не проходит. Её проверяют loopback-тесты, а TCP мимо TUN —
  отдельное обращение к эхо-серверу в сценарии.

## Открытые вопросы

Вопросы 1, 2, 3, 6 и 7 решены, как предложено: отдельное окно, IPv4, без QUIC, `diagnose` есть,
`Ctrl+D`. Вопросы 4 и 5 остаются открытыми.


1. **Точка входа.** Отдельное окно плюс пункт меню и кнопка на вкладке «Диагностика» —
   или заменить содержимое вкладки «Диагностика» на новый экран, а мониторинг перенести в
   настройки? Предложение: отдельное окно, вкладку не трогать.
2. **Только IPv4.** Согласиться на IPv4 в версии 1; IPv6 добавить после снятия `ipv6_only`.
3. **QUIC.** Не переносить; при необходимости — отдельная задача с aioquic.
4. **Каталог.** Общий файл с Android, срок до 2027-01-19; нужен процесс обновления в обоих
   репозиториях одним коммитом.
5. **Windows `IP_UNICAST_IF`.** Нужна проверка на живой Windows (значение 31, индекс в
   сетевом порядке байт); пока не подтверждено — прямые пробы при TUN на Windows
   `SKIPPED(SYSTEM_RESTRICTED)` с текстом «Проверка напрямую при TUN на Windows пока не
   поддерживается».
6. **CLI `diagnose`.** Включать ли в версию 1. Предложение: да, он дёшев и нужен VM-тестам.
7. **Сочетание клавиш** `Ctrl+D` свободно в обоих тулкитах (`shortcuts`) — подтвердить.
