# Сетевой слой, этап 3: DNS и маршрутизация — план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Сделать так, чтобы правила маршрутизации и настройки DNS действительно
управляли трафиком: geo-записи работают и не роняют ядро, имя резолвит DNS той
сети, куда идёт трафик, есть блок-лист и готовые правила, DNS приложений в
режиме TUN проходит через ядро, а заведомо опасный конфиг не запускается.

**Architecture:** Сборка остаётся в `build_session_config`
(`src/core/config_builder.py`), но три вещи выносятся в свои модули: блок `dns`
(`src/core/dns_config.py` — сразу в формате ядра, без промежуточного
«sing-box → xray»), знание о геобазах (`src/core/geo.py` — читает названия
категорий из `.dat` и отсеивает неизвестные) и проверка готового конфига
(`src/core/config_validator.py`). Всё, что спрашивает систему — физический
интерфейс, DNS-серверы сети, systemd-resolved, — живёт в `src/sys/` и в сборщик
приходит значениями, поэтому сборка тестируется без сети и без прав. Схему
конфига знает только ядро: каждое изменение закреплено тестом через настоящий
`xray -test`, а поведение DNS-модуля проверено запуском ядра.

**Tech Stack:** Python 3.11, xray-core 26.9.9 (обязательно: `rules` и
`rewriteAddress` у dns-outbound и `gateway` у TUN появились после 26.3.27),
pytest, ruff, GTK 4 + libadwaita (только задачи 12 и 14), systemd-resolved
(только задача 9).

Дорожная карта всех этапов — `2026-10-03-network-parity-roadmap.md`, раздел
«Этап 3». Первоисточник поведения — Android-версия:
`tenga-proxy-android/docs/config-builder/` (в первую очередь `gotchas.md`).

**План предполагает, что этап 1 выполнен** (`2026-10-03-network-phase1-protocols.md`):
ядро 26.9.9, `apply_transport_tweaks` в сборщике. Планы этапов 2 и 4 написаны
параллельно на той же базе; общие с ними файлы перечислены в задаче 0.

---

## Принятые решения

Решения 1–6 — ответы владельца проекта на вопросы дорожной карты; прототип
сверен с ними. Решения 7–12 приняты при написании плана. Каждое меняется в
одном месте; если решение другое, поправь соответствующую задачу до начала
работы.

| № | Решение | Где меняется |
|---|---|---|
| 1 | **D5: «Локальные сети напрямую» включено по умолчанию** для новых установок и новых профилей; сохранённые настройки не трогаются. Нынешнее поведение от этого не хуже: правило переезжает в конец, после пользовательских списков — раньше оно вливалось в список «Напрямую» и при порядке «напрямую → VPN» перебивало подсети `10.x` из списка «Через VPN»; а запрос к DNS-серверу VPN, который теперь попал бы под это правило, получает своё правило в задаче 11. **Отклонение от формулировки «через `geoip:private`»**: правило остаётся списком CIDR (`LOCAL_NETWORKS`, те же сети плюс IPv6) — так оно работает и без геобаз, которых в нынешней установке нет («Что проверено», п. 5). | задачи 7, 11 |
| 2 | **D5: «Российские сайты и IP напрямую» выключено по умолчанию** — нынешнее поведение (всё в прокси, кроме списков) сохраняется. Действует только в режиме списков. | задача 7 |
| 3 | **D7: геобазы обновляются только по кнопке, с проверкой SHA256** — из релизов `Loyalsoldier/v2ray-rules-dat` по их `.sha256sum`. `install_dev.sh` геобазы не скачивает вовсе (они лежат в git), поэтому «тот же источник» взять неоткуда; Loyalsoldier — источник баз в официальных сборках xray-core. **Задача последняя из задач с кодом и необязательная: можно вычеркнуть без последствий для остальных.** | задача 14 |
| 4 | **Режим «VPN поверх» (`vpn_list`, NetworkManager) сохраняется**: как с ним сочетаются D1–D3 — раздел «Режим „VPN поверх“» ниже. То, что не должно сломаться, закреплено тестами в задачах 3, 4, 6, 7, 8, 10, 11. | — |
| 5 | **`domainStrategy` остаётся `IPOnDemand`.** Замеров, оправдывающих переход на `IPIfNonMatch`, нет. | раздел «Не делаем» |
| 6 | **D4: категории из `.dat` читаются без новых зависимостей**: ручной разбор двух полей protobuf, 60 строк. `grpcio` protobuf за собой не тянет. | задача 2 |
| 7 | **Домен с точкой — это домен с поддоменами, а не подстрока.** Сейчас `ok.ru` в списке совпадает с `facebook.ru`, а `*.example.com` не совпадает ни с чем. Слово без точки (`google`) остаётся подстрокой. Это меняет смысл существующих списков — в сторону того, что обещает документация. | задача 1 |
| 8 | **Блок-лист всегда первый** и в порядке групп не участвует: порядок групп в интерфейсе — шесть перестановок трёх групп, четвёртая группа дала бы двадцать четыре. | задача 5 |
| 9 | **Системный резолвер больше не запасной для удалённого DNS.** Раньше при недоступном DoH имена молча уходили резолверу провайдера. Теперь он обслуживает только свои домены (`skipFallback`). | задача 4 |
| 10 | **При перехвате DNS запросы не-A/AAAA пересылаются DNS-серверу сети.** DNS-модуль ядра отвечает только на A и AAAA; без пересылки `dig TXT`, MX и SRV получали бы пустой ответ. Для провайдера это не хуже нынешнего: сейчас туда идут вообще все запросы. Строже — одна строка (убрать правило `direct`). | задача 8 |
| 11 | **Проверка конфига не отказывает за адрес входа не на loopback** — адрес задаётся в настройках, это решение пользователя; пишется предупреждение в журнал. И не требует «частные сети только в direct»: в списке «Через VPN» частные подсети законны. Запрещено только отправлять не напрямую loopback и `geoip:private`. | задача 10 |
| 12 | **Системный DNS направляется в TUN только через systemd-resolved.** Для остальных резолверов перехват работает, лишь если запросы и так идут через TUN. Адрес TUN-интерфейса — `198.18.0.1/30`, объявляемый DNS — `1.1.1.1`. | задача 9 |

## Что проверено до написания плана

Проверено 2026-10-03 запуском, а не предположено.

1. **Весь код этого плана прототипирован** на копии проекта с выполненным
   этапом 1, по одному коммиту на задачу, а затем применён из этого файла к
   чистой копии: дерево после каждой задачи совпало с коммитом прототипа.
   Полный набор — `795 passed` (было 634) на ядре 26.9.9, `ruff check` и `ruff format` чистые.
   Строки «Expected» в шагах — фактический вывод прогонов на коде до и после
   реализации.
2. **GTK-тесты запускались без экрана** — бэкенд Broadway (`gtk4-broadwayd`)
   и отдельная шина (`dbus-run-session`) вместо `xvfb-run`, которого на машине
   нет. Новые GTK-тесты задач 12 и 14 падают до реализации и проходят после;
   во всём GTK-наборе (`2 failed, 211 passed`; до плана — `2 failed, 206 passed`) падают только два теста геометрии окна в
   `tests/test_ui_window.py` — они так же падают и на коде до плана (Broadway не
   выполняет запросы размера окна). **Глазами диалоги не смотрелись.**
   Shell-скрипты (задачи 9 и 13) проверены `sh -n` / `bash -n`, не запуском.
3. **DNS-модуль ядра проверен запуском 26.9.9 без TUN** — SOCKS-вход с тегом
   `tun-in`, DNS-запросы по TCP через SOCKS (сценарий — в задаче 15):

   | Что | Результат |
   |---|---|
   | правило `inboundTag: tun-in, port: 53 → dns-out` | запрос обрабатывает DNS-модуль |
   | `hosts` со значением `#3`; ключи `domain:`, `full:`, `keyword:`, `geosite:` | NXDOMAIN, совпадение как у правил маршрутизации |
   | сервер с `domains` и `skipFallback` | чужие имена ему не достаются, даже когда остальные серверы недоступны |
   | UDP-сервер сети + правило `inboundTag: dns-internal → direct` | запрос уходит через direct, привязанный к интерфейсу |
   | dns-outbound без настроек | на TXT и MX пустой ответ |
   | dns-outbound с `rules: [hijack 1,28; direct]` и `rewriteAddress` | TXT и MX пересылаются DNS-серверу сети |

4. **Геобазы.** Неизвестная категория `geosite:`/`geoip:` — отказ ядра
   загрузить конфиг целиком, и в правилах, и в `dns.servers[].domains`.
   Неизвестный атрибут (`geosite:x@нет`) принимается. Без файлов рядом с
   бинарником отвергается даже `geoip:private`. В `core/bin/geosite.dat` есть
   `category-ru` и `category-gov-ru`, но нет `tld-ru` и `category-bank-ru`,
   на которые ссылается Android.
5. **В установленном приложении геобаз нет.** `build_appimage.sh` и
   `install_appimage.sh` копируют только бинарник: в
   `~/.config/tenga-proxy/bin/` лежит один `xray`. Любое geo-правило там уронило
   бы подключение. Отсюда задача 13 и требование «без баз geo-записи молча
   пропускаются» в задаче 2.
6. **На системах с systemd-resolved DNS приложений до TUN не доходит.**
   Приложения спрашивают заглушку `127.0.0.53`, она — DNS-сервер физического
   интерфейса, привязывая сокет к интерфейсу, то есть мимо таблицы маршрутов.
   Правило перехвата в конфиге само по себе ничего не перехватит. Кроме того,
   resolved не шлёт запросы через интерфейс без маршрутизируемого адреса, а у
   `xray0` есть только link-local IPv6; менять DNS интерфейса можно только с
   правами (`org.freedesktop.resolve1.set-dns-servers` — `auth_admin`). Отсюда
   задача 9.
7. **Прямой выход в режиме TUN без VPN-интеграции ведёт в петлю** — вывод из
   кода и таблицы маршрутов, вживую не воспроизводился. Маршрут по умолчанию
   указывает в TUN, а outbound `direct` привязывается к физическому интерфейсу,
   только если у профиля включён VPN. Соединение «напрямую» к публичному адресу
   возвращается в TUN и снова попадает под то же правило. У `xray-core` защиты
   от этого нет (README TUN-модуля прямо предупреждает). Привязка в ветке VPN
   работает на машине разработчика каждый день; задача 6 распространяет её на
   весь режим TUN. Без неё готовое правило «российские IP напрямую» было бы
   нерабочим.
8. **`get_default_interface` на поднятом туннеле возвращает сам TUN**: первая
   строка `ip route show default` — `default dev xray0`, а отсеиваются только
   имена на `tun`/`tap`. При пересборке конфига на живом подключении outbound'ы
   привязались бы к `xray0`. Исправляется в задаче 6.
9. **Привязка сокета к интерфейсу** (`SO_BINDTODEVICE`) на ядре Linux 5.7+ не
   требует прав; на более старых нужен `CAP_NET_RAW` — он у установленного
   бинарника есть (`install_appimage.sh` выдаёт его вместе с `CAP_NET_ADMIN`).
10. **Источник геобаз.** `…/releases/latest/download/geoip.dat` и
    `geoip.dat.sha256sum` у `Loyalsoldier/v2ray-rules-dat` существуют, формат
    суммы — `sha256sum` («сумма  имя»). `update_geo_bases` один раз выполнен по
    сети: 16,5 и 11 МБ за 15 секунд, суммы сошлись, нужные категории есть.
11. **`xray -test` на TUN-конфиге**: 26.3.27 пытается создать интерфейс, 26.9.9
    — нет (проверено с несуществующим именем и без прав). Тесты плана всё равно
    не отдают ядру TUN-inbound: на машине разработчика `xray0` занят рабочим
    подключением.
12. **Тесты не трогают DNS и маршруты машины.** Полный набор прогнан с
    перехватчиком `subprocess`, запрещающим `sudo`, `resolvectl`, `ip`, `nmcli`,
    `busctl`: ни одного вызова `resolvectl` или `sudo`; к D-Bus systemd-resolved
    код плана не обращается вовсе. Страховка на будущее — autouse-фикстура в
    `tests/conftest.py` (задача 9): подключение в тестах не вызывает
    направление системного DNS, даже если тест забыл его подменить. Без неё
    тест подключения в режиме TUN с перехватом на машине с установленным
    помощником выполнил бы `sudo -n tun-route-helper dns xray0`.
13. **Запрос DNS-модуля к DNS-серверу VPN уходил не туда — и до плана.** В
    старом коде у этого сервера стоял `detour: vpn` в формате sing-box, а при
    переводе в формат ядра он терялся (комментарий «xray-core doesn't support
    detour in DNS config»). Сборкой конфига старого и нового кода проверено:
    запрос к `10.222.0.7` шёл в прокси (выход по умолчанию), а с «локальными
    сетями напрямую» — в direct на физическом интерфейсе. Ни там, ни там сервер
    VPN не отвечает; работало, только если подсеть сервера внесена в список
    «Через VPN». Исправляется в задаче 11.

**Не проверено и остаётся на ручную проверку** (чек-лист — в задаче 15):
поведение на живом TUN — перехват DNS, направление системного DNS через
resolved, отсутствие петли у прямого выхода; режим «VPN поверх» на живом
VPN-подключении; внешний вид диалогов; установочные скрипты.

## Режим «VPN поверх»

Профиль с `vpn_settings.enabled` и поднятым подключением NetworkManager
получает outbound `vpn` (freedom, привязан к интерфейсу VPN) и список
«Через VPN». В Android такого режима нет, поэтому сочетание с D1–D3 решено
здесь.

| | Как сочетается | Тесты |
|---|---|---|
| D2, split-DNS | Домены списка «Через VPN» резолвит первый DNS-сервер VPN из NetworkManager (`skipFallback`); место сервера — по порядку групп, как у правил. DoH при активном VPN, как и раньше, заменяется системным резолвером (DoH поверх VPN — кольцевая зависимость). VPN не поднят — список игнорируется, его домены резолвит основной DNS. Нет DNS-серверов у VPN — домены резолвит системный. Запрос к серверу VPN идёт через outbound `vpn` (задача 11). | задачи 3, 4, 11: `tests/test_core_dns_config.py` |
| D1, перехват DNS | Работает и с VPN: системный резолвер называется адресами серверов физической сети, сервер VPN остаётся для своих доменов. Физический интерфейс ищется в обход интерфейса VPN и своего TUN; явный интерфейс из настроек VPN профиля главнее. Правило перехвата первое, за ним — правило для сервера VPN. | задачи 6, 8, 11: `tests/test_core_tun_outbounds.py`, `tests/test_core_dns_intercept.py`, `tests/test_core_dns_config.py` |
| D3, блок-лист | Первый при любом порядке групп, в том числе раньше «Через VPN»; NXDOMAIN из `hosts` отвечается раньше любого сервера, включая сервер VPN. | задача 5 |
| D5, локальные сети | Правило стоит после пользовательских групп: подсеть `10.x` из списка «Через VPN» идёт в `vpn`, а не в `direct`, при любом порядке. | задача 7: `tests/test_core_routing_rules.py` |
| D6, проверка конфига | Частные подсети в `vpn` законны (решение 11); полный конфиг со всеми возможностями, включая VPN, проверку проходит во всех режимах. | задача 10: `tests/test_core_config_validator.py` |

## Не делаем

- **Смену `domainStrategy`** на `IPIfNonMatch` — нет замеров (решение 5).
- **Профили порядка правил** Android (`BASIC_DEFAULT`, `BLOCK_PRIORITY`…): здесь
  порядок трёх групп уже настраивается, блок-лист закреплён первым.
- **Импорт маршрутов Happ**, per-app, exclude-маршруты — нет на десктопе.
- **Блокировку DoT (порт 853)**: в Android она нужна из-за Private DNS; resolved
  по умолчанию DoT не использует.
- **Строку «BLOCK» на странице мониторинга** — счётчики правил там и так
  условны; добавим, если попросят.
- **Простой UDP-DNS «мимо прокси»**: при выключенном «DNS через прокси» сервер
  вида `8.8.8.8` по-прежнему идёт по правилам маршрутизации (так было и до
  плана; для DoH работает `https+local://`).
- **Ключи `autoRoute`/`strictRoute`** в настройках TUN-inbound — это ключи
  sing-box, ядро их игнорирует. Не трогаем: к этапу не относится.

## Соглашения

- Рабочая ветка: `feature/network-phase3` от ветки, где выполнены этапы 1 и 2.
- Тесты: `uv run pytest <путь> -q`. Полный набор: `uv run pytest -q`.
- Перед каждым коммитом: `python cli.py lint-all`.
- Сообщения коммитов — как в истории: `fix(core): …`, `feat(core): …`, по-русски.
- Исправление поведения и рефакторинг — разными коммитами (задача 3 — чистый
  рефакторинг).
- Блок «Создать» — новый файл целиком. Блок «Изменить» — `diff` относительно
  файла после предыдущей задачи; номера строк — ориентир, привязывайся к
  содержимому. Если контекст не совпал, файл изменили этапы 2 или 4: внеси
  правку по смыслу, не затирая чужую.
- Настоящему ядру TUN-конфиги не отдаём. Правила с `inboundTag: tun-in`
  проверяются на SOCKS-входе с тем же тегом (`with_socks_inbound` в
  `tests/support/session.py`).
- Сборка конфига в тестах не читает состояние машины, а подключение не меняет
  её DNS: autouse-фикстуры в `tests/conftest.py` (задачи 6, 8 и 9) подменяют
  определение интерфейса, DNS-серверов сети и направление системного DNS в
  TUN; тест, которому они нужны, подменяет их сам.

---

### Task 0: Сверка с кодом

План написан до того, как этапы 1 и 2 выполнены в репозитории. Прежде чем
менять код, убедись, что он тот, на который рассчитаны фрагменты.

**Step 1: Создать ветку**

```bash
git switch -c feature/network-phase3
```

**Step 2: Проверить предпосылки**

```bash
core/bin/xray version | head -1          # Xray 26.9.9
ls core/bin/geoip.dat core/bin/geosite.dat
ls core/scripts/tun_route_helper.sh core/scripts/build_appimage.sh core/scripts/install_appimage.sh
grep -n "apply_transport_tweaks(outbound, context.config)" src/core/config_builder.py
grep -n "Convert DNS config from sing-box format" src/core/config_builder.py
grep -n "def parse_entries" src/db/config.py
grep -n "def get_default_interface" src/sys/vpn.py
uv run pytest -q
```

Expected: ядро 26.9.9; обе геобазы и три скрипта на месте (скрипты задачи 9
и 13 меняют, в репозитории они есть давно); каждая из четырёх строк `grep`
находит ровно одно место; набор зелёный. Запиши число пройденных тестов: в
конце плана их должно стать на 161 больше (без учёта GTK).

Если ядро старее — сначала задача 3 этапа 1. Если `grep` не находит строку —
файл уже переписан, читай его перед тем как применять `diff`.

**Step 3: Посмотреть, что изменил этап 2 в общих файлах**

Файлы, которые меняет и этот план, и соседние этапы:

| Файл | Что делает этот план | Кто ещё может менять |
|---|---|---|
| `src/core/config_builder.py` | почти весь `build_session_config` | этап 4 (пробные конфиги — низ файла) |
| `src/core/connection.py` | `connect`, `reload_config` | этап 4 (проверка соединения, failover) |
| `src/core/xray_manager.py` | `_SERVICE_TAGS`, окружение `Popen` | этап 4 |
| `src/db/config.py` | `DnsSettings`, `RoutingSettings` | этапы 2 и 4 (новые поля настроек) |
| `src/ui/dialogs/settings.py` | страницы «DNS» и «О программе» | этапы 1, 2, 4 (свои страницы) |
| `tests/conftest.py` | две autouse-фикстуры | этапы 2 и 4 |
| `tests/test_core_config_builder.py` | одна строка в одном тесте | этап 4 |

```bash
git log --oneline -15 -- src/core/config_builder.py src/core/connection.py \
    src/core/xray_manager.py src/db/config.py src/ui/dialogs/settings.py tests/conftest.py
```

Незнакомые коммиты в этих файлах — прочитать до начала.

---

### Task 1: Разбор записей списков

Сейчас `parse_entries` делит записи на «похоже на IP» и «всё остальное».
Последствия: `geoip:ru` попадает в домены и молча не работает; голый домен
ядро сравнивает как подстроку (`ok.ru` совпадает с `facebook.ru`);
`*.example.com` не совпадает ни с чем; `::1` считается доменом;
`example.com/24` попадает в сети и роняет ядро.

Новое правило: запись приводится к виду, который понимает ядро, а негодная —
выбрасывается (решение 7).

**Files:**
- Modify: `src/db/config.py` (`RoutingSettings.parse_entries`, новая
  `classify_routing_entry`)
- Create: `tests/test_db_config_routing_entries.py`

**Step 1: Написать падающие тесты**

Создать `tests/test_db_config_routing_entries.py`:

```python
"""Разбор записей списков маршрутизации.

Строка списка превращается в то, что понимает ядро. Ошибка разбора обходится
дорого: непонятую запись ядро либо молча не применяет, либо отвергает вместе со
всем конфигом.
"""

import pytest

from src.db.config import RoutingSettings


def parse(*entries: str) -> tuple[list[str], list[str]]:
    return RoutingSettings().parse_entries(list(entries))


def test_dotted_domain_matches_itself_and_subdomains():
    """Голую строку ядро считает подстрокой: `ok.ru` совпал бы с `facebook.ru`."""
    assert parse("ok.ru") == (["domain:ok.ru"], [])


@pytest.mark.parametrize("entry", ["*.example.com", ".example.com", "Example.COM"])
def test_wildcard_and_case_are_normalized(entry):
    assert parse(entry) == (["domain:example.com"], [])


def test_word_without_dot_stays_a_keyword():
    assert parse("google") == (["google"], [])


@pytest.mark.parametrize(
    "entry",
    ["domain:example.com", "full:example.com", "regexp:^a\\.example$", "keyword:video"],
)
def test_core_prefixes_pass_through(entry):
    assert parse(entry) == ([entry], [])


def test_geosite_goes_to_domains():
    assert parse("geosite:category-ru", "GeoSite:Google@cn", "geosite:geolocation-!cn") == (
        ["geosite:category-ru", "geosite:google@cn", "geosite:geolocation-!cn"],
        [],
    )


def test_geoip_goes_to_ips():
    """Раньше `geoip:ru` попадал в домены и молча не работал."""
    assert parse("geoip:ru", "GEOIP:Private") == ([], ["geoip:ru", "geoip:private"])


@pytest.mark.parametrize(
    "entry", ["geoip:", "geosite:", "geoip:ru@attr", "geosite:bad name", "geoip:!ru"]
)
def test_malformed_geo_entry_is_dropped(entry):
    """Похожее на geo, но невалидное: в домены не проваливается."""
    assert parse(entry) == ([], [])


def test_ipv4_address_and_cidr():
    assert parse("1.2.3.4", "10.0.0.0/8") == ([], ["1.2.3.4/32", "10.0.0.0/8"])


def test_ipv6_address_and_cidr():
    assert parse("::1", "fc00::/7") == ([], ["::1/128", "fc00::/7"])


@pytest.mark.parametrize("entry", ["example.com/24", "1.2.3.4/99", "300.1.1.1/8"])
def test_broken_cidr_is_dropped(entry):
    """Такую запись ядро не примет ни доменом, ни сетью — и отвергнет весь конфиг."""
    assert parse(entry) == ([], [])


def test_comma_separated_line_is_split():
    assert parse("a.example, 1.1.1.1,geoip:ru") == (
        ["domain:a.example"],
        ["1.1.1.1/32", "geoip:ru"],
    )


def test_blank_entries_are_skipped():
    assert parse("", "  ", ",") == ([], [])
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_db_config_routing_entries.py -q`
Expected: `16 failed, 7 passed` — проходят только префиксы ядра, слово без точки, IPv4
и пустые записи.

**Step 3: Реализовать**

Изменить `src/db/config.py`:

```diff
--- a/src/db/config.py
+++ b/src/db/config.py
@@ -1,5 +1,6 @@
 from __future__ import annotations
 
+import ipaddress
 import json
 import re
 from abc import ABC
@@ -364,6 +365,62 @@ class ProxyMode:
     }
 
 
+# Имя geo-категории и атрибута: как в .dat, в нижнем регистре. `!` законен
+# внутри имени (`geolocation-!cn`), но не первым: отрицание не поддерживаем.
+_GEO_NAME = re.compile(r"^[a-z0-9][a-z0-9._!-]{0,63}$")
+# Префиксы доменных правил ядра: такие записи передаются как есть.
+_DOMAIN_RULE_PREFIXES = ("domain:", "full:", "regexp:", "keyword:", "dotless:")
+
+
+def _classify_geo(entry: str) -> tuple[str, str] | None:
+    """`geosite:имя[@атрибут]` — доменное правило, `geoip:имя` — сетевое."""
+    kind, _, rest = entry.lower().partition(":")
+    name, has_attr, attr = rest.partition("@")
+    if not _GEO_NAME.match(name):
+        return None
+    if kind == "geoip":
+        return None if has_attr else ("ip", f"geoip:{name}")
+    if has_attr and not _GEO_NAME.match(attr):
+        return None
+    return ("domain", f"geosite:{rest}")
+
+
+def classify_routing_entry(entry: str) -> tuple[str, str] | None:
+    """Привести запись списка к виду, который понимает ядро.
+
+    Returns:
+        `("domain", правило)`, `("ip", сеть)` или None, если запись не годится.
+        Негодную запись лучше выбросить: непонятное правило ядро отвергает
+        вместе со всем конфигом.
+    """
+    entry = entry.strip()
+    if not entry:
+        return None
+
+    lower = entry.lower()
+    if lower.startswith(("geosite:", "geoip:")):
+        return _classify_geo(entry)
+    if lower.startswith(_DOMAIN_RULE_PREFIXES):
+        return ("domain", entry)
+
+    try:
+        network = ipaddress.ip_network(entry, strict=False)
+    except ValueError:
+        network = None
+    if network is not None:
+        return ("ip", entry if "/" in entry else f"{entry}/{network.prefixlen}")
+    if "/" in entry:
+        return None
+
+    domain = lower.removeprefix("*").lstrip(".")
+    if not domain:
+        return None
+    # Голую строку ядро сравнивает как подстроку: `ok.ru` совпал бы с
+    # `facebook.ru`. `domain:` — сам домен и его поддомены. Слово без точки
+    # оставляем подстрокой: так записывают «всё, где встречается google».
+    return ("domain", f"domain:{domain}" if "." in domain else domain)
+
+
 ROUTING_GROUPS = ["direct", "vpn", "proxy"]
 DEFAULT_ROUTING_ORDER = ["direct", "vpn", "proxy"]
 
@@ -438,7 +495,10 @@ class RoutingSettings(ConfigBase):
 
     def parse_entries(self, entries: list[str]) -> tuple[list[str], list[str]]:
         """
-        Split entries into domains and IP/CIDR.
+        Split entries into domain rules and IP rules of the core.
+
+        `geosite:` уходит в домены, `geoip:` — в сети; негодные записи
+        отбрасываются (см. `classify_routing_entry`).
 
         Returns:
             (domains, ips)
@@ -461,16 +521,11 @@ class RoutingSettings(ConfigBase):
                     ips.extend(part_ips)
                 continue
 
-            if "/" in entry:
-                parts = entry.split("/")
-                if len(parts) == 2 and parts[1].isdigit():
-                    ips.append(entry)
-                    continue
-
-            if entry[0].isdigit() and all(c.isdigit() or c == "." for c in entry):
-                ips.append(entry + "/32")
+            classified = classify_routing_entry(entry)
+            if classified is None:
                 continue
-            domains.append(entry)
+            kind, value = classified
+            (ips if kind == "ip" else domains).append(value)
 
         return domains, ips
 
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_db_config_routing_entries.py -q`
Expected: `23 passed`. Затем полный набор — `uv run pytest -q`: зелёный
(существующий тест списков проверяет вхождение `example.org` в правило и с
`domain:example.org` проходит).

**Step 5: Commit**

```bash
git add src/db/config.py \
        tests/test_db_config_routing_entries.py
git commit -m "fix(db): разбирать geosite/geoip и приводить домены к правилам ядра"
```

---

### Task 2: Каталог geo-категорий

Ссылка на категорию, которой нет в `.dat`, — не пустое правило: ядро отвергает
конфиг целиком. Сборщик должен знать, какие категории есть, и пропускать
остальные с предупреждением. Если баз нет вовсе (сегодняшняя установка, см.
«Что проверено», п. 5) — пропускаются все geo-записи, подключение работает.

Из списка запись не удаляется: появится база с категорией — правило заработает.

Формат `.dat` — protobuf: `GeoSiteList { repeated GeoSite entry = 1 }`,
`GeoSite { string country_code = 1; … }`, у `geoip.dat` так же. Нужны только
названия, поэтому запись читается до первого поля, остальное пропускается по
длине (решение 6).

**Files:**
- Create: `src/core/geo.py`
- Modify: `src/core/config_builder.py` (`_parse_list`, три вызова `parse_entries`)
- Create: `tests/support/session.py` — общие заготовки тестов сборки конфига
- Create: `tests/test_core_geo.py`, `tests/test_core_routing_rules.py`

**Step 1: Общие заготовки тестов**

Ими пользуются все тесты сборки конфига в этом плане. `with_socks_inbound` и
`xray_verdict` — способ показать конфиг настоящему ядру, не отдавая ему TUN.

Создать `tests/support/session.py`:

```python
"""Общие заготовки тестов сборки конфига сессии."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from src.core.context import AppContext, init_context
from src.db.config import RoutingMode
from src.db.profiles import ProfileEntry
from src.fmt import parse_link

XRAY = Path("core/bin/xray")
BUNDLED_GEO_DIR = XRAY.parent.resolve()

VLESS_LINK = (
    "vless://11111111-1111-1111-1111-111111111111@proxy.example.org:443"
    "?type=tcp&security=tls&sni=proxy.example.org#Test"
)


def use_bundled_geo(monkeypatch) -> None:
    """Направить и сборщик, и `xray -test` на геобазы из core/bin.

    Без этого каталог зависел бы от того, какой бинарник найдёт приложение, а
    `tests/test_core_config.py` перезагружает модуль путей с чужим каталогом.
    """
    monkeypatch.setenv("XRAY_LOCATION_ASSET", str(BUNDLED_GEO_DIR))


def make_context(tmp_path: Path) -> AppContext:
    return init_context(config_dir=tmp_path)


def make_profile(context: AppContext, link: str = VLESS_LINK) -> ProfileEntry:
    bean = parse_link(link)
    assert bean is not None
    entry = ProfileEntry(id=1, group_id=0, bean=bean)
    context.profiles.profiles[1] = entry
    return entry


def use_custom_lists(context: AppContext, **lists: list[str]) -> None:
    """Включить режим списков и записать их на диск: сборщик читает списки из файлов."""
    routing = context.config.routing
    routing.mode = RoutingMode.CUSTOM
    for name, entries in lists.items():
        setattr(routing, f"{name}_list", list(entries))
    routing.save_lists_to_files(context.config_dir)


def rules_to(config: dict, outbound_tag: str) -> list[dict]:
    return [r for r in config["routing"]["rules"] if r.get("outboundTag") == outbound_tag]


def rule_values(config: dict, outbound_tag: str, key: str) -> list[str]:
    return [value for rule in rules_to(config, outbound_tag) for value in rule.get(key, [])]


def with_socks_inbound(config: dict) -> dict:
    """Тот же конфиг, но вместо TUN — SOCKS с тем же тегом.

    `xray -test` на TUN-inbound пытается создать интерфейс, а на машине
    разработчика он занят рабочим подключением. Правила с `inboundTag` при этом
    проверяются так же: ядру важен тег, а не протокол входа.
    """
    copy = json.loads(json.dumps(config))
    for index, inbound in enumerate(copy["inbounds"]):
        if inbound.get("protocol") == "tun":
            copy["inbounds"][index] = {
                "tag": inbound.get("tag", "tun-in"),
                "listen": "127.0.0.1",
                "port": 10800 + index,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
            }
    return copy


def xray_verdict(config: dict, tmp_path: Path) -> str:
    """Вывод `xray -test` для конфига; «Configuration OK» — принят."""
    assert not any(i.get("protocol") == "tun" for i in config["inbounds"]), (
        "TUN-конфиг настоящему ядру не отдаём: см. with_socks_inbound"
    )
    path = tmp_path / "session.json"
    path.write_text(json.dumps(config))
    result = subprocess.run(
        [str(XRAY), "-test", "-config", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return result.stdout + result.stderr
```

**Step 2: Написать падающие тесты**

Создать `tests/test_core_geo.py`:

```python
"""Каталог geo-категорий: что на самом деле есть в geosite.dat и geoip.dat.

Ссылка на категорию, которой в базе нет, — не пустое правило: ядро отвергает
конфиг целиком. Поэтому перед сборкой такие записи надо уметь отсеять.
"""

from pathlib import Path

import pytest

from src.core.geo import (
    GEOIP_FILE,
    GEOSITE_FILE,
    GeoCatalog,
    asset_dirs,
    load_catalog,
    read_categories,
)

BUNDLED = Path("core/bin")


def _varint(value: int) -> bytes:
    out = bytearray()
    while value > 0x7F:
        out.append(value & 0x7F | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _field(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def make_dat(*codes: str, filler: bytes = b"") -> bytes:
    """GeoSiteList/GeoIPList: entry = 1 { country_code = 1; ...остальное = 2 }."""
    return b"".join(_field(1, _field(1, code.encode()) + _field(2, filler)) for code in codes)


def test_reads_category_names_in_lower_case(tmp_path):
    path = tmp_path / GEOSITE_FILE
    path.write_bytes(make_dat("CATEGORY-RU", "GOOGLE", filler=b"x" * 300))

    assert read_categories(path) == frozenset({"category-ru", "google"})


def test_missing_file_gives_empty_set(tmp_path):
    assert read_categories(tmp_path / "nope.dat") == frozenset()


def test_corrupt_file_gives_empty_set(tmp_path):
    """Обрезанная при скачивании база не должна ронять сборку конфига."""
    path = tmp_path / GEOIP_FILE
    path.write_bytes(make_dat("RU", "CN")[:-3] + b"\xff\xff\xff\xff")

    assert read_categories(path) == frozenset()


def test_catalog_knows_entries_by_kind():
    catalog = GeoCatalog(geosite=frozenset({"category-ru"}), geoip=frozenset({"ru"}))

    assert catalog.knows("geosite:category-ru")
    assert catalog.knows("geosite:category-ru@ads")  # атрибут каталог не проверяет
    assert catalog.knows("geoip:ru")
    assert not catalog.knows("geosite:ru")
    assert not catalog.knows("geoip:category-ru")


def test_split_keeps_non_geo_rules_and_reports_unknown():
    catalog = GeoCatalog(geosite=frozenset({"google"}), geoip=frozenset())

    kept, dropped = catalog.split(["domain:a.example", "geosite:google", "geosite:nope"])

    assert kept == ["domain:a.example", "geosite:google"]
    assert dropped == ["geosite:nope"]


def test_load_catalog_takes_first_directory_that_has_the_file(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / GEOSITE_FILE).write_bytes(make_dat("ONE"))
    (second / GEOSITE_FILE).write_bytes(make_dat("TWO"))
    (second / GEOIP_FILE).write_bytes(make_dat("RU"))

    catalog = load_catalog([first, second])

    assert catalog.geosite == frozenset({"one"})
    assert catalog.geoip == frozenset({"ru"})


def test_load_catalog_notices_replaced_file(tmp_path):
    path = tmp_path / GEOIP_FILE
    path.write_bytes(make_dat("RU"))
    assert load_catalog([tmp_path]).geoip == frozenset({"ru"})

    path.write_bytes(make_dat("RU", "BY"))

    assert load_catalog([tmp_path]).geoip == frozenset({"ru", "by"})


def test_asset_dirs_follow_the_core_lookup_order(tmp_path, monkeypatch):
    """Ядро ищет базы в XRAY_LOCATION_ASSET, иначе рядом с бинарником."""
    monkeypatch.delenv("XRAY_LOCATION_ASSET", raising=False)
    assert asset_dirs(tmp_path / "bin" / "xray")[0] == tmp_path / "bin"

    monkeypatch.setenv("XRAY_LOCATION_ASSET", str(tmp_path / "geo"))
    assert asset_dirs(tmp_path / "bin" / "xray")[0] == tmp_path / "geo"


@pytest.mark.skipif(not (BUNDLED / GEOSITE_FILE).exists(), reason="нет core/bin/geosite.dat")
def test_bundled_bases_have_the_categories_the_builder_refers_to():
    catalog = load_catalog([BUNDLED])

    assert {"category-ru", "category-gov-ru"} <= catalog.geosite
    assert {"ru", "private"} <= catalog.geoip
```

Создать `tests/test_core_routing_rules.py`:

```python
"""Правила маршрутизации в конфиге сессии."""

from __future__ import annotations

import shutil

import pytest

from src.core import config_builder
from src.core.config_builder import build_session_config
from src.core.geo import GeoCatalog
from tests.support.session import (
    XRAY,
    make_context,
    make_profile,
    rule_values,
    use_bundled_geo,
    use_custom_lists,
    with_socks_inbound,
    xray_verdict,
)

needs_xray = pytest.mark.skipif(
    not XRAY.exists() or not shutil.which(str(XRAY)),
    reason="бинарник xray недоступен (core/bin/xray)",
)


@pytest.fixture(autouse=True)
def geo(monkeypatch):
    use_bundled_geo(monkeypatch)


@pytest.fixture
def context(tmp_path):
    return make_context(tmp_path)


@pytest.fixture
def profile(context):
    return make_profile(context)


# --- geo-записи -----------------------------------------------------------


def test_geo_entries_reach_the_right_rule_fields(context, profile):
    """`geoip:` — в ip, `geosite:` — в domain; раньше оба попадали в домены."""
    use_custom_lists(context, direct=["geosite:category-ru", "geoip:ru"])

    config = build_session_config(context, profile)

    assert "geosite:category-ru" in rule_values(config, "direct", "domain")
    assert "geoip:ru" in rule_values(config, "direct", "ip")


def test_unknown_geo_categories_are_dropped(context, profile):
    """Неизвестная категория роняет ядро — запись пропускаем, остальные работают."""
    use_custom_lists(
        context,
        direct=["geosite:category-ru", "geosite:no-such-category", "geoip:zz-nowhere"],
        proxy=["geosite:no-such-either", "blocked.example"],
    )

    config = build_session_config(context, profile)

    everything = str(config["routing"]["rules"])
    assert "no-such" not in everything
    assert "zz-nowhere" not in everything
    assert "geosite:category-ru" in rule_values(config, "direct", "domain")
    assert "domain:blocked.example" in rule_values(config, profile.bean.display_name, "domain")


def test_without_geo_bases_every_geo_entry_is_dropped(context, profile, monkeypatch):
    """Баз рядом с ядром нет (старая установка): geo-правила не должны ронять подключение."""
    monkeypatch.setattr(config_builder, "load_catalog", lambda _dirs: GeoCatalog())
    use_custom_lists(context, direct=["geosite:category-ru", "geoip:ru", "direct.example"])

    config = build_session_config(context, profile)

    assert "geo" not in str(config["routing"]["rules"])
    assert rule_values(config, "direct", "domain") == ["domain:direct.example"]


@needs_xray
def test_core_accepts_lists_with_unknown_geo_categories(context, profile, tmp_path):
    use_custom_lists(
        context,
        direct=["geosite:category-ru", "geosite:no-such-category", "geoip:ru", "geoip:zz-nowhere"],
        proxy=["geosite:google", "*.blocked.example"],
    )

    config = build_session_config(context, profile)

    assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)
```

**Step 3: Убедиться, что падают**

Run: `uv run pytest tests/test_core_geo.py tests/test_core_routing_rules.py -q`
Expected: `2 errors` — `ModuleNotFoundError: No module named 'src.core.geo'`
при сборе обоих файлов.

**Step 4: Написать модуль**

Создать `src/core/geo.py`:

```python
"""Каталог geo-категорий из geosite.dat и geoip.dat.

Ссылка на категорию, которой нет в базе, — не пустое правило: ядро отвергает
конфиг целиком, и подключение не поднимается. Здесь читаются только названия
категорий, чтобы сборщик конфига мог отсеять неизвестные заранее.

Файлы — protobuf (`GeoSiteList` / `GeoIPList`): повторяющееся поле 1, внутри
которого поле 1 — название категории. Остальное содержимое записи пропускается
по длине, поэтому базы на десятки мегабайт читаются за десятки миллисекунд и
без protobuf-библиотеки.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("tenga.core.geo")

GEOSITE_FILE = "geosite.dat"
GEOIP_FILE = "geoip.dat"
ASSET_ENV = "XRAY_LOCATION_ASSET"
# Куда ядро заглядывает, если рядом с бинарником файла нет.
SYSTEM_ASSET_DIRS = (Path("/usr/local/share/xray"), Path("/usr/share/xray"))

GEOSITE_PREFIX = "geosite:"
GEOIP_PREFIX = "geoip:"

# Поле 1, тип «строка байтов» — и у записи списка, и у названия внутри записи.
_LENGTH_DELIMITED_FIELD_1 = 0x0A


def _read_varint(data: memoryview, pos: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7


def _parse_categories(data: memoryview) -> frozenset[str]:
    names: set[str] = set()
    pos, size = 0, len(data)
    while pos < size:
        tag, pos = _read_varint(data, pos)
        if tag != _LENGTH_DELIMITED_FIELD_1:
            raise ValueError(f"неожиданное поле {tag:#x}")
        length, pos = _read_varint(data, pos)
        end = pos + length
        if end > size:
            raise ValueError("запись выходит за конец файла")

        inner_tag, inner = _read_varint(data, pos)
        if inner_tag == _LENGTH_DELIMITED_FIELD_1:
            name_length, inner = _read_varint(data, inner)
            names.add(bytes(data[inner : inner + name_length]).decode("utf-8").lower())
        pos = end
    return frozenset(names)


def read_categories(path: Path) -> frozenset[str]:
    """Названия категорий базы в нижнем регистре; пусто, если файла нет или он битый."""
    try:
        data = memoryview(path.read_bytes())
    except OSError:
        return frozenset()
    try:
        return _parse_categories(data)
    except (ValueError, IndexError, UnicodeDecodeError) as e:
        logger.warning("Геобаза %s повреждена: %s", path, e)
        return frozenset()


@dataclass(frozen=True)
class GeoCatalog:
    """Какие категории можно упоминать в правилах, не уронив ядро."""

    geosite: frozenset[str] = frozenset()
    geoip: frozenset[str] = frozenset()

    def knows(self, rule: str) -> bool:
        """Есть ли категория правила `geosite:имя[@атрибут]` / `geoip:имя` в базе."""
        if rule.startswith(GEOSITE_PREFIX):
            # Атрибут не проверяем: неизвестный атрибут ядро принимает (пустой набор).
            return rule[len(GEOSITE_PREFIX) :].partition("@")[0] in self.geosite
        if rule.startswith(GEOIP_PREFIX):
            return rule[len(GEOIP_PREFIX) :] in self.geoip
        return True

    def split(self, rules: Iterable[str]) -> tuple[list[str], list[str]]:
        """Разделить правила на пригодные и ссылающиеся на неизвестную категорию."""
        kept: list[str] = []
        dropped: list[str] = []
        for rule in rules:
            (kept if self.knows(rule) else dropped).append(rule)
        return kept, dropped


def asset_dirs(binary_path: str | Path | None) -> list[Path]:
    """Каталоги, где ядро ищет геобазы, в порядке его поиска."""
    dirs: list[Path] = []
    env_dir = os.environ.get(ASSET_ENV)
    if env_dir:
        dirs.append(Path(env_dir))
    elif binary_path:
        dirs.append(Path(binary_path).parent)
    dirs.extend(SYSTEM_ASSET_DIRS)
    return dirs


def find_geo_file(name: str, dirs: Iterable[Path]) -> Path | None:
    for directory in dirs:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None


# Ключ — путь, размер и время изменения: заменённый файл перечитывается сам.
_cache: dict[tuple[str, int, int], frozenset[str]] = {}


def _cached_categories(path: Path | None) -> frozenset[str]:
    if path is None:
        return frozenset()
    try:
        stat = path.stat()
    except OSError:
        return frozenset()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key not in _cache:
        _cache[key] = read_categories(path)
    return _cache[key]


def load_catalog(dirs: Iterable[Path]) -> GeoCatalog:
    """Каталог по первым найденным geosite.dat и geoip.dat."""
    dirs = list(dirs)
    return GeoCatalog(
        geosite=_cached_categories(find_geo_file(GEOSITE_FILE, dirs)),
        geoip=_cached_categories(find_geo_file(GEOIP_FILE, dirs)),
    )
```

Run: `uv run pytest tests/test_core_geo.py -q`
Expected: `9 passed`. `tests/test_core_routing_rules.py` пока даёт `3 failed,
1 passed`: первый тест проходит благодаря задаче 1, остальные ждут сборщика.

**Step 5: Подключить к сборщику**

Изменить `src/core/config_builder.py`:

```diff
--- a/src/core/config_builder.py
+++ b/src/core/config_builder.py
@@ -12,9 +12,16 @@ import random
 import socket
 
 from src.core.context import AppContext
+from src.core.geo import GeoCatalog, asset_dirs, load_catalog
 from src.core.proxy_mode import build_inbounds_for_mode
 from src.core.transport_tweaks import apply_transport_tweaks
-from src.db.config import DEFAULT_ROUTING_ORDER, LOCAL_NETWORKS, ProxyMode, RoutingMode
+from src.db.config import (
+    DEFAULT_ROUTING_ORDER,
+    LOCAL_NETWORKS,
+    ProxyMode,
+    RoutingMode,
+    RoutingSettings,
+)
 from src.db.profiles import ProfileEntry
 from src.sys.vpn import (
     get_default_interface,
@@ -26,6 +33,28 @@ from src.sys.vpn import (
 logger = logging.getLogger("tenga.core.config_builder")
 
 
+def _parse_list(
+    routing: RoutingSettings, entries: list[str], catalog: GeoCatalog, list_name: str
+) -> tuple[list[str], list[str]]:
+    """Разобрать список на доменные и сетевые правила, отсеяв неизвестные geo-категории.
+
+    Категория, которой нет в geosite.dat / geoip.dat, роняет ядро вместе со всем
+    конфигом. Из списка запись не удаляется: появится база с этой категорией —
+    правило заработает.
+    """
+    domains, ips = routing.parse_entries(entries)
+    domains, dropped_domains = catalog.split(domains)
+    ips, dropped_ips = catalog.split(ips)
+    dropped = dropped_domains + dropped_ips
+    if dropped:
+        logger.warning(
+            "Список «%s»: категорий нет в геобазах, записи пропущены: %s",
+            list_name,
+            ", ".join(dropped),
+        )
+    return domains, ips
+
+
 def build_session_config(context: AppContext, profile: ProfileEntry | None) -> dict | None:
     """Create xray-core configuration for profile."""
     try:
@@ -96,6 +125,7 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
                 )
                 logger.debug("Added local networks bypass rule for PROXY_ALL mode")
         elif routing.mode == RoutingMode.CUSTOM:
+            catalog = load_catalog(asset_dirs(context.find_xray_binary()))
             direct_list = list(routing.direct_list) if routing.direct_list else []
 
             if routing.bypass_local_networks:
@@ -105,15 +135,17 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
                         direct_list.append(network)
 
             if direct_list:
-                direct_domains, direct_ips = routing.parse_entries(direct_list)
+                direct_domains, direct_ips = _parse_list(routing, direct_list, catalog, "direct")
 
             if routing.vpn_list and vpn_tag and vpn_interface:
-                vpn_domains, vpn_ips = routing.parse_entries(routing.vpn_list)
+                vpn_domains, vpn_ips = _parse_list(routing, routing.vpn_list, catalog, "vpn")
                 if vpn_domains:
                     over_vpn_domains_for_dns = vpn_domains
 
             if routing.proxy_list:
-                proxy_domains, proxy_ips = routing.parse_entries(routing.proxy_list)
+                proxy_domains, proxy_ips = _parse_list(
+                    routing, routing.proxy_list, catalog, "proxy"
+                )
 
             try:
                 rule_order = routing.get_rule_order()
```

**Step 6: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_geo.py tests/test_core_routing_rules.py -q`
Expected: `13 passed`

**Step 7: Commit**

```bash
git add src/core/config_builder.py \
        src/core/geo.py \
        tests/support/session.py \
        tests/test_core_geo.py \
        tests/test_core_routing_rules.py
git commit -m "feat(core): отсеивать неизвестные geo-категории перед сборкой конфига"
```

---

### Task 3: Рефакторинг — блок DNS одним шагом

Сейчас блок `dns` собирается в два приёма: сначала список серверов и правил в
формате sing-box (`type`, `server`, `detour`, `domain_suffix`), затем
преобразование в формат ядра тремя одинаковыми циклами. Разбор адреса
DNS-сервера VPN занимает ещё восемьдесят строк. Следующие задачи меняют именно
этот блок, поэтому сначала он выносится в модуль — **без изменения результата**.

**Files:**
- Create: `src/core/dns_config.py`
- Modify: `src/core/config_builder.py` (блок от `# DNS (xray-core format)` до
  `inbounds = build_inbounds_for_mode(`)
- Create: `tests/test_core_dns_config.py`

**Step 1: Написать тесты-характеристики**

Они закрепляют нынешний результат и должны пройти сразу — до рефакторинга.

Создать `tests/test_core_dns_config.py`:

```python
"""Блок `dns` конфига сессии."""

from __future__ import annotations

import pytest

from src.core import config_builder
from src.core.config_builder import build_session_config
from src.db.config import DnsProvider, VpnSettings
from tests.support.session import (
    make_context,
    make_profile,
    use_bundled_geo,
    use_custom_lists,
)

IP_SERVER_LINK = "vless://11111111-1111-1111-1111-111111111111@203.0.113.7:443?security=tls#IP"


@pytest.fixture(autouse=True)
def geo(monkeypatch):
    use_bundled_geo(monkeypatch)


@pytest.fixture
def context(tmp_path):
    return make_context(tmp_path)


@pytest.fixture
def profile(context):
    return make_profile(context)


@pytest.fixture
def vpn(monkeypatch, profile):
    """Профиль с поднятым VPN NetworkManager (интерфейс tun0)."""
    profile.vpn_settings = VpnSettings(enabled=True, connection_name="corp")
    monkeypatch.setattr(config_builder, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(config_builder, "get_vpn_interface", lambda _name: "tun0")
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: "eth0")
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: ["10.222.0.7"])
    return profile.vpn_settings


def dns_of(context, profile) -> dict:
    config = build_session_config(context, profile)
    assert config is not None
    return config["dns"]


# Сервер профиля задан доменом: его имя всегда резолвит системный резолвер,
# иначе DNS через прокси ждал бы соединения с прокси, а оно — DNS.
BOOTSTRAP = {"address": "localhost", "domains": ["proxy.example.org"]}


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({}, [{"address": "https://dns.google/dns-query"}, BOOTSTRAP]),
        ({"use_proxy": False}, [{"address": "https+local://dns.google/dns-query"}, BOOTSTRAP]),
        ({"provider": DnsProvider.SYSTEM}, ["localhost", BOOTSTRAP]),
        ({"custom_url": "8.8.8.8"}, [{"address": "8.8.8.8", "port": 53}, BOOTSTRAP]),
        ({"custom_url": "tls://dns.google"}, [BOOTSTRAP]),
    ],
    ids=["doh", "doh-direct", "system", "udp", "dot-skipped"],
)
def test_main_server_follows_dns_settings(context, profile, settings, expected):
    for name, value in settings.items():
        setattr(context.config.dns, name, value)

    assert dns_of(context, profile) == {"servers": expected}


def test_ip_server_needs_no_bootstrap_rule(context):
    profile = make_profile(context, IP_SERVER_LINK)

    assert dns_of(context, profile) == {
        "servers": [{"address": "https://dns.google/dns-query"}, "localhost"]
    }


def test_active_vpn_replaces_doh_with_system_resolver(context, profile, vpn):
    """DoH поверх VPN даёт кольцевую зависимость: резолвит системный резолвер."""
    assert dns_of(context, profile) == {"servers": ["localhost", BOOTSTRAP]}


@pytest.mark.parametrize(
    ("reported", "address", "port"),
    [
        ("10.222.0.7", "10.222.0.7", 53),
        ("IP4.DNS[1]:10.222.0.7:5353", "10.222.0.7", 5353),
    ],
    ids=["plain", "nmcli"],
)
def test_vpn_list_domains_use_the_vpn_dns_server(
    context, profile, vpn, monkeypatch, reported, address, port
):
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: [reported])
    use_custom_lists(context, vpn=["corp.example", "10.14.0.0/16"], direct=["direct.example"])

    assert dns_of(context, profile)["servers"] == [
        "localhost",
        BOOTSTRAP,
        {"address": address, "port": port, "domains": ["domain:corp.example"]},
    ]


def test_vpn_without_dns_servers_resolves_its_domains_locally(context, profile, vpn, monkeypatch):
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: [])
    use_custom_lists(context, vpn=["corp.example"])

    assert dns_of(context, profile)["servers"] == [
        "localhost",
        BOOTSTRAP,
        {"address": "localhost", "domains": ["domain:corp.example"]},
    ]


def test_unreadable_vpn_dns_address_falls_back_to_public_resolver(
    context, profile, vpn, monkeypatch
):
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: ["not-an-address"])
    use_custom_lists(context, vpn=["corp.example"])

    assert dns_of(context, profile)["servers"][-1] == {
        "address": "8.8.8.8",
        "port": 53,
        "domains": ["domain:corp.example"],
    }
```

**Step 2: Убедиться, что проходят на старом коде**

Run: `uv run pytest tests/test_core_dns_config.py -q`
Expected: `11 passed`. Если какой-то тест падает — рефакторинг не начинать:
сначала разобраться, чем код отличается от того, на который рассчитан план.

**Step 3: Вынести сборку в модуль**

Создать `src/core/dns_config.py`:

```python
"""Блок `dns` конфига xray-core.

Сервер описывается сразу в формате ядра: строка `"localhost"` либо объект
`{"address", "port"?, "domains"?}`. Ядро сначала спрашивает серверы, у которых
`domains` совпал с именем, затем остальные по порядку.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from src.db.config import DnsSettings

logger = logging.getLogger("tenga.core.dns_config")

# Системный резолвер процесса ядра.
LOCALHOST = "localhost"
# Запасной адрес, когда DNS-сервер VPN не удалось разобрать.
FALLBACK_VPN_DNS = ("8.8.8.8", 53)

_IPV4_ENDPOINT = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::(\d+))?")

DnsServer = str | dict[str, Any]


def parse_dns_endpoint(raw: str) -> tuple[str, int] | None:
    """IPv4-адрес и порт DNS-сервера из строки NetworkManager.

    nmcli отдаёт и `10.222.0.7`, и `IP4.DNS[1]:10.222.0.7:5353` — берём первый
    IPv4-адрес в строке и порт сразу за ним.
    """
    match = _IPV4_ENDPOINT.search(raw)
    if not match:
        return None
    return match.group(1), int(match.group(2) or 53)


def _server(
    address: str, *, port: int | None = None, domains: list[str] | None = None
) -> DnsServer:
    if address == LOCALHOST and not domains:
        return LOCALHOST
    server: dict[str, Any] = {"address": address}
    if port is not None:
        server["port"] = port
    if domains:
        server["domains"] = list(domains)
    return server


def _main_server(dns_url: str, *, through_proxy: bool) -> DnsServer | None:
    """Сервер для всех имён, у которых нет своего сервера."""
    if dns_url == "local":
        return LOCALHOST
    if dns_url.startswith("https://"):
        # DoH: ядро принимает его только URL-строкой в address. Отдельные
        # host:port и path оно читает как имя UDP-сервера — запрос висит до
        # таймаута и уходит на localhost. `https+local://` идёт напрямую, мимо
        # маршрутизации; обычный `https://` — через неё, то есть в прокси.
        if not through_proxy:
            dns_url = "https+local://" + dns_url[len("https://") :]
        return _server(dns_url)
    if dns_url.startswith("tls://"):
        # DoT в xray-core нет: адрес `tls://…` оно прочло бы как имя UDP-сервера.
        logger.warning("DNS-over-TLS не поддерживается xray-core, %s пропущен", dns_url)
        return None
    return _server(dns_url.replace("udp://", "").replace("tcp://", ""), port=53)


def _vpn_server(vpn_dns_servers: list[str], vpn_domains: list[str]) -> DnsServer:
    """Сервер для доменов из списка «через VPN»."""
    if not vpn_dns_servers:
        logger.warning("У VPN-подключения нет DNS-серверов: его домены резолвит системный")
        return _server(LOCALHOST, domains=vpn_domains)

    endpoint = parse_dns_endpoint(vpn_dns_servers[0])
    if endpoint is None:
        logger.error("Не удалось разобрать адрес DNS-сервера VPN: %s", vpn_dns_servers[0])
        endpoint = FALLBACK_VPN_DNS
    address, port = endpoint
    logger.info("Домены списка «через VPN» резолвит %s:%d", address, port)
    return _server(address, port=port, domains=vpn_domains)


def build_dns(
    settings: DnsSettings,
    *,
    proxy_host: str,
    vpn_active: bool = False,
    vpn_domains: list[str] | None = None,
    vpn_dns_servers: list[str] | None = None,
) -> dict[str, Any]:
    """Собрать блок `dns`.

    Args:
        settings: настройки DNS приложения.
        proxy_host: адрес сервера профиля; домен резолвится системным резолвером.
        vpn_active: поднят VPN NetworkManager, привязанный к профилю.
        vpn_domains: доменные правила списка «через VPN».
        vpn_dns_servers: DNS-серверы VPN-подключения, как их отдал NetworkManager.
    """
    dns_url = settings.get_dns_url()
    if vpn_active and dns_url.startswith(("https://", "tls://")):
        # DoH поверх VPN даёт кольцевую зависимость, а приватность DNS уже
        # обеспечивает сам VPN.
        logger.info("VPN активен: DoH/DoT заменён системным резолвером")
        dns_url = "local"

    servers: list[DnsServer] = []

    main = _main_server(dns_url, through_proxy=settings.use_proxy)
    if main is not None:
        servers.append(main)

    # Имя сервера профиля резолвит системный резолвер: DNS через прокси ждал бы
    # соединения с прокси, а оно — этого самого ответа.
    bootstrap = [proxy_host] if proxy_host and not proxy_host[0].isdigit() else []
    servers.append(_server(LOCALHOST, domains=bootstrap))

    if vpn_active and vpn_domains:
        servers.append(_vpn_server(vpn_dns_servers or [], vpn_domains))

    return {"servers": servers}
```

**Step 4: Заменить блок в сборщике вызовом**

Изменить `src/core/config_builder.py`:

```diff
--- a/src/core/config_builder.py
+++ b/src/core/config_builder.py
@@ -12,6 +12,7 @@ import random
 import socket
 
 from src.core.context import AppContext
+from src.core.dns_config import build_dns
 from src.core.geo import GeoCatalog, asset_dirs, load_catalog
 from src.core.proxy_mode import build_inbounds_for_mode
 from src.core.transport_tweaks import apply_transport_tweaks
@@ -303,295 +304,17 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
                 logger.info("Profile configuration: VPN disabled, proxy + direct rules (if any)")
         else:
             logger.info("Profile configuration: No VPN settings, proxy only")
-        # DNS (xray-core format)
-        dns_settings = context.config.dns
-        dns_url = dns_settings.get_dns_url()
-        dns_detour = proxy_tag if dns_settings.use_proxy else "direct"
-
-        # Extract proxy server address from profile bean (not from outbound config)
-        # For VLESS/VMess/etc the server is in settings.vnext[0].address, not in outbound.server
-        vps_server = profile.bean.server_address if profile.bean else ""
-
-        # IMPORTANT: When VPN is enabled, disable DoH/DoT to avoid circular DNS dependencies
-        # VPN already provides DNS privacy through its tunnel
-        if vpn_tag and vpn_interface and dns_url.startswith(("https://", "tls://")):
-            logger.info(
-                "VPN enabled: switching from DoH/DoT to localhost DNS "
-                "to avoid circular dependencies"
-            )
-            dns_url = "local"
-
-        # Build DNS servers list (new format: type + server instead of address)
-        dns_servers = []
-
-        # Main DNS server
-        if dns_url == "local":
-            dns_servers.append(
-                {
-                    "tag": "main-dns",
-                    "type": "local",
-                    "detour": dns_detour,
-                }
-            )
-        elif dns_url.startswith("https://"):
-            # DoH: ядро принимает его только URL-строкой в address. Отдельные
-            # host:port и path оно читает как имя UDP-сервера — запрос висит до
-            # таймаута и уходит на localhost. `https+local://` идёт напрямую, мимо
-            # маршрутизации; обычный `https://` — через неё, то есть в прокси.
-            doh_url = dns_url
-            if not dns_settings.use_proxy:
-                doh_url = "https+local://" + dns_url[len("https://") :]
-
-            dns_servers.append(
-                {
-                    "tag": "main-dns",
-                    "type": "https",
-                    "url": doh_url,
-                }
-            )
-        elif dns_url.startswith("tls://"):
-            # DoT в xray-core нет: адрес `tls://…` оно прочло бы как имя UDP-сервера.
-            # Сервер пропускаем, запросы достаются local-dns ниже.
-            logger.warning("DNS-over-TLS не поддерживается xray-core, %s пропущен", dns_url)
-        else:
-            # Plain IP or domain - use UDP
-            server = dns_url.replace("udp://", "").replace("tcp://", "")
-            dns_servers.append(
-                {
-                    "tag": "main-dns",
-                    "type": "udp",
-                    "server": server,
-                    "detour": dns_detour,
-                }
-            )
-
-        # Local DNS server (no detour needed for local type)
-        dns_servers.append(
-            {
-                "tag": "local-dns",
-                "type": "local",
-            }
-        )
-
-        if vpn_tag and vpn_interface and over_vpn_domains_for_dns:
-            # Get DNS servers from VPN connection settings
+        vpn_active = bool(vpn_tag and vpn_interface)
+        vpn_dns_servers: list[str] = []
+        if vpn_active and over_vpn_domains_for_dns:
             vpn_dns_servers = get_vpn_dns_servers(vpn_settings.connection_name)
-
-            if vpn_dns_servers:
-                # Use first DNS server from VPN settings
-                vpn_dns_ip = vpn_dns_servers[0]
-                logger.debug("Raw VPN DNS server from NetworkManager: %s", vpn_dns_ip)
-
-                # Clean up the address: remove protocol prefixes, brackets, etc.
-                clean_ip = vpn_dns_ip.strip()
-
-                # Remove protocol prefixes
-                for prefix in ["udp://", "tcp://", "tls://", "https://"]:
-                    if clean_ip.startswith(prefix):
-                        clean_ip = clean_ip[len(prefix) :]
-
-                # Remove brackets if present
-                clean_ip = clean_ip.strip("[]")
-
-                # Handle NetworkManager format like "IP4.DNS[1]:10.222.0.7:53" or "IP4.DNS[1]:10.222.0.7"
-                # Extract IP address and port using regex-like approach
-                import re
-
-                # Pattern to match IP address (IPv4 or IPv6) with optional port
-                ip_pattern = r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::(\d+))?"
-                ipv6_pattern = r"([0-9a-fA-F:]+)(?::(\d+))?"
-
-                # Try to find IP address in the string
-                match = re.search(ip_pattern, clean_ip)
-                if not match:
-                    match = re.search(ipv6_pattern, clean_ip)
-
-                if match:
-                    server_ip = match.group(1)
-                    server_port = int(match.group(2)) if match.group(2) else 53
-                    logger.debug(
-                        "Extracted IP: %s, port: %d from: %s",
-                        server_ip,
-                        server_port,
-                        vpn_dns_ip,
-                    )
-                else:
-                    # Fallback: try to extract by splitting on colons
-                    # Remove any non-IP prefix (like "IP4.DNS[1]:")
-                    parts = clean_ip.split(":")
-                    # Find the part that looks like an IP address
-                    for part in parts:
-                        # Check if part looks like an IP (contains dots or is IPv6)
-                        if "." in part or ":" in part:
-                            # This might be the IP
-                            ip_candidate = part
-                            port_candidate = 53
-                            # Check if next part is a number (port)
-                            part_idx = parts.index(part)
-                            if part_idx + 1 < len(parts):
-                                try:
-                                    port_candidate = int(parts[part_idx + 1])
-                                except (ValueError, IndexError):
-                                    pass
-
-                            # Validate IP format
-                            if re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip_candidate):
-                                server_ip = ip_candidate
-                                server_port = port_candidate
-                                logger.debug(
-                                    "Extracted IP (fallback): %s, port: %d from: %s",
-                                    server_ip,
-                                    server_port,
-                                    vpn_dns_ip,
-                                )
-                                break
-                    else:
-                        # No valid IP found, use fallback
-                        logger.error("Could not extract IP address from: %s", vpn_dns_ip)
-                        server_ip = "8.8.8.8"
-                        server_port = 53
-
-                # Final validation: server_ip should be a valid IP format
-                if not re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", server_ip):
-                    logger.error(
-                        "Invalid VPN DNS server IP format: %s (from: %s)", server_ip, vpn_dns_ip
-                    )
-                    server_ip = "8.8.8.8"  # Fallback
-                    server_port = 53
-
-                logger.info(
-                    "Using VPN DNS server %s:%d for over_vpn domains (from connection %s, original: %s, available: %s)",
-                    server_ip,
-                    server_port,
-                    vpn_settings.connection_name,
-                    vpn_dns_ip,
-                    vpn_dns_servers,
-                )
-                # Use detour to VPN outbound for UDP DNS
-                # This routes DNS queries through VPN interface via VPN outbound
-                dns_servers.append(
-                    {
-                        "tag": "vpn-dns",
-                        "type": "udp",
-                        "server": server_ip,
-                        "server_port": server_port,
-                        "detour": vpn_tag,
-                    }
-                )
-            else:
-                # Fallback to local DNS through VPN interface
-                logger.warning(
-                    "No DNS servers found in VPN connection %s settings, using local DNS through VPN interface",
-                    vpn_settings.connection_name,
-                )
-                dns_servers.append(
-                    {
-                        "tag": "vpn-dns",
-                        "type": "local",
-                        "detour": vpn_tag,
-                    }
-                )
-            logger.info("Added VPN DNS server for over_vpn domains")
-
-        dns_rules = []
-
-        # IMPORTANT: DNS rules are evaluated in order, so more specific rules should come first
-        # 1. over_vpn domains should use VPN DNS (highest priority)
-        if vpn_tag and over_vpn_domains_for_dns:
-            # Use domain_suffix for matching subdomains
-            dns_rules.append(
-                {
-                    "domain_suffix": over_vpn_domains_for_dns,
-                    "server": "vpn-dns",
-                }
-            )
-            logger.info(
-                "Added DNS rule for over_vpn domains (VPN DNS): %s", over_vpn_domains_for_dns
-            )
-
-        # 2. VPS server domain should use local DNS (critical for proxy+vpn to avoid bootstrap issues)
-        if vps_server and not vps_server[0].isdigit():
-            dns_rules.append(
-                {
-                    "domain": [vps_server],
-                    "server": "local-dns",
-                }
-            )
-            logger.info("Added DNS rule for proxy server domain (local DNS): %s", vps_server)
-
-        # Note: xray-core DNS configuration uses servers with optional domains, not separate rules
-
-        # Log DNS configuration for debugging (before conversion)
-        logger.info("DNS configuration (before xray-core conversion):")
-        logger.info("  Servers: %s", [s.get("tag", "unknown") for s in dns_servers])
-        logger.info("  Rules: %s", len(dns_rules))
-
-        # Convert DNS config from sing-box format to xray-core format
-        xray_dns_servers = []
-
-        # Convert DNS servers
-        for server in dns_servers:
-            server_type = server.get("type", "local")
-            server_tag = server.get("tag", "")
-
-            if server_type == "local":
-                # Check if this local DNS server has specific domains from rules
-                domains_for_server = []
-                for rule in dns_rules:
-                    if rule.get("server") == server_tag:
-                        if "domain" in rule:
-                            domains_for_server.extend(rule["domain"])
-                        elif "domain_suffix" in rule:
-                            domains_for_server.extend(rule["domain_suffix"])
-
-                if domains_for_server:
-                    # xray-core format: localhost DNS with specific domains
-                    xray_dns_servers.append(
-                        {
-                            "address": "localhost",
-                            "domains": domains_for_server,
-                        }
-                    )
-                else:
-                    # No specific domains, just use simple localhost string
-                    xray_dns_servers.append("localhost")
-            elif server_type == "udp":
-                addr = server.get("server", "8.8.8.8")
-                port_num = server.get("server_port", 53)
-                # xray-core expects UDP DNS servers as object with address and port
-                # or just IP string if port is 53 (default)
-                server_config = {
-                    "address": addr,
-                    "port": port_num,
-                }
-                # Add domains from DNS rules if this server is referenced
-                domains_for_server = []
-                for rule in dns_rules:
-                    if rule.get("server") == server_tag:
-                        if "domain" in rule:
-                            domains_for_server.extend(rule["domain"])
-                        elif "domain_suffix" in rule:
-                            domains_for_server.extend(rule["domain_suffix"])
-                if domains_for_server:
-                    server_config["domains"] = domains_for_server
-                # Note: xray-core doesn't support detour in DNS config directly
-                # DNS queries routing through VPN is handled via routing rules
-                xray_dns_servers.append(server_config)
-            elif server_type == "https":
-                server_config = {
-                    "address": server["url"],
-                }
-                # Add domains from DNS rules if this server is referenced
-                domains_for_server = []
-                for rule in dns_rules:
-                    if rule.get("server") == server_tag:
-                        if "domain" in rule:
-                            domains_for_server.extend(rule["domain"])
-                        elif "domain_suffix" in rule:
-                            domains_for_server.extend(rule["domain_suffix"])
-                if domains_for_server:
-                    server_config["domains"] = domains_for_server
-                xray_dns_servers.append(server_config)
+        dns = build_dns(
+            context.config.dns,
+            proxy_host=profile.bean.server_address if profile.bean else "",
+            vpn_active=vpn_active,
+            vpn_domains=over_vpn_domains_for_dns,
+            vpn_dns_servers=vpn_dns_servers,
+        )
 
         inbounds = build_inbounds_for_mode(
             mode=getattr(context.config, "proxy_mode", None),
@@ -603,9 +326,7 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
 
         config = {
             "log": {"loglevel": context.config.log_level},
-            "dns": {
-                "servers": xray_dns_servers if xray_dns_servers else ["localhost"],
-            },
+            "dns": dns,
             "inbounds": inbounds,
             "outbounds": outbounds,
             "routing": {
```

**Step 5: Убедиться, что результат не изменился**

Run: `uv run pytest tests/test_core_dns_config.py -q`
Expected: `11 passed`. Полный набор — зелёный.

**Step 6: Commit**

```bash
git add src/core/config_builder.py \
        src/core/dns_config.py \
        tests/test_core_dns_config.py
git commit -m "refactor(core): собирать блок DNS одним шагом в src/core/dns_config.py"
```

---

### Task 4: Split-DNS

Имя должен резолвить DNS той сети, в которую пойдёт сам трафик. Сейчас домен
из списка «Напрямую» резолвится удалённым DNS через прокси — CDN отдаёт адрес
чужого региона, и «мимо прокси» получается только наполовину.

Новая раскладка серверов:

1. имя сервера профиля — системный резолвер (`full:`, раньше была подстрока);
2. домены списков — в порядке групп маршрутизации: «напрямую» — системный
   резолвер, «через VPN» — DNS-сервер VPN, «через прокси» — удалённый DNS
   (отдельным сервером, чтобы домен из двух списков достался тому, чья группа
   раньше);
3. всё остальное — основной DNS из настроек.

Системный резолвер помечен `skipFallback`, и общего `localhost` после
удалённого сервера больше нет (решение 9). В `geosite.dat` нет инверсии для RU
(`geolocation-!ru`), поэтому «всё, кроме RU» выражается порядком серверов, а не
фильтром у удалённого.

**Files:**
- Modify: `src/core/dns_config.py`, `src/core/config_builder.py`
- Modify: `tests/test_core_dns_config.py` (переписывается), `tests/test_core_config_builder.py`

**Step 1: Переписать тесты блока DNS**

Тесты-характеристики задачи 3 описывали старую раскладку. Файл заменяется:

Заменить `tests/test_core_dns_config.py` целиком:

```python
"""Блок `dns` конфига сессии."""

from __future__ import annotations

import shutil

import pytest

from src.core import config_builder
from src.core.config_builder import build_session_config
from src.db.config import DnsProvider, VpnSettings
from tests.support.session import (
    XRAY,
    make_context,
    make_profile,
    use_bundled_geo,
    use_custom_lists,
    with_socks_inbound,
    xray_verdict,
)

needs_xray = pytest.mark.skipif(
    not XRAY.exists() or not shutil.which(str(XRAY)),
    reason="бинарник xray недоступен (core/bin/xray)",
)

IP_SERVER_LINK = "vless://11111111-1111-1111-1111-111111111111@203.0.113.7:443?security=tls#IP"


@pytest.fixture(autouse=True)
def geo(monkeypatch):
    use_bundled_geo(monkeypatch)


@pytest.fixture
def context(tmp_path):
    return make_context(tmp_path)


@pytest.fixture
def profile(context):
    return make_profile(context)


@pytest.fixture
def vpn(monkeypatch, profile):
    """Профиль с поднятым VPN NetworkManager (интерфейс tun0)."""
    profile.vpn_settings = VpnSettings(enabled=True, connection_name="corp")
    monkeypatch.setattr(config_builder, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(config_builder, "get_vpn_interface", lambda _name: "tun0")
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: "eth0")
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: ["10.222.0.7"])
    return profile.vpn_settings


def dns_of(context, profile) -> dict:
    config = build_session_config(context, profile)
    assert config is not None
    return config["dns"]


DOH = "https://dns.google/dns-query"

# Сервер профиля задан доменом: его имя всегда резолвит системный резолвер,
# иначе DNS через прокси ждал бы соединения с прокси, а оно — DNS.
BOOTSTRAP = {"address": "localhost", "domains": ["full:proxy.example.org"], "skipFallback": True}


def direct_dns(*domains: str) -> dict:
    return {"address": "localhost", "domains": list(domains), "skipFallback": True}


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({}, [BOOTSTRAP, {"address": DOH}]),
        ({"use_proxy": False}, [BOOTSTRAP, {"address": "https+local://dns.google/dns-query"}]),
        ({"provider": DnsProvider.SYSTEM}, [BOOTSTRAP, "localhost"]),
        ({"custom_url": "8.8.8.8"}, [BOOTSTRAP, {"address": "8.8.8.8", "port": 53}]),
        ({"custom_url": "tls://dns.google"}, [BOOTSTRAP, "localhost"]),
    ],
    ids=["doh", "doh-direct", "system", "udp", "dot-skipped"],
)
def test_main_server_follows_dns_settings(context, profile, settings, expected):
    for name, value in settings.items():
        setattr(context.config.dns, name, value)

    assert dns_of(context, profile) == {"servers": expected}


def test_ip_server_needs_no_bootstrap_rule(context):
    profile = make_profile(context, IP_SERVER_LINK)

    assert dns_of(context, profile) == {"servers": [{"address": DOH}]}


def test_system_resolver_is_not_a_fallback_for_remote_dns(context, profile):
    """Упал туннель — имена не должны утекать системному резолверу.

    `skipFallback` оставляет системному резолверу только его домены; общего
    `localhost` после удалённого сервера нет.
    """
    use_custom_lists(context, direct=["direct.example"])

    servers = dns_of(context, profile)["servers"]

    assert "localhost" not in servers
    assert all(s.get("skipFallback") for s in servers if s["address"] == "localhost")


def test_direct_list_domains_use_the_system_resolver(context, profile):
    """Трафик идёт напрямую — и имя должен резолвить DNS той же сети.

    Иначе запрос ушёл бы через прокси, и CDN вернул бы адрес чужого региона.
    """
    use_custom_lists(context, direct=["direct.example", "geosite:category-ru", "1.2.3.0/24"])

    assert dns_of(context, profile)["servers"] == [
        BOOTSTRAP,
        direct_dns("domain:direct.example", "geosite:category-ru"),
        {"address": DOH},
    ]


def test_proxy_list_domains_use_the_remote_dns(context, profile):
    """Домен из proxy-списка не должен достаться системному резолверу.

    Сервер с доменами proxy-списка стоит по порядку групп: при порядке
    «прокси → напрямую» домен из обоих списков резолвится удалённо.
    """
    use_custom_lists(context, direct=["ru.example"], proxy=["blocked.ru.example"])
    context.config.routing.rule_order = ["proxy", "direct", "vpn"]

    assert dns_of(context, profile)["servers"] == [
        BOOTSTRAP,
        {"address": DOH, "domains": ["domain:blocked.ru.example"]},
        direct_dns("domain:ru.example"),
        {"address": DOH},
    ]


def test_dns_servers_follow_the_rule_order(context, profile):
    use_custom_lists(context, direct=["ru.example"], proxy=["blocked.ru.example"])
    context.config.routing.rule_order = ["direct", "vpn", "proxy"]

    addresses = [s["address"] for s in dns_of(context, profile)["servers"]]

    assert addresses == ["localhost", "localhost", DOH, DOH]


def test_proxy_list_needs_no_own_server_with_system_dns(context, profile):
    """Удалённого DNS нет — отдельный сервер для proxy-списка ничего бы не изменил."""
    context.config.dns.provider = DnsProvider.SYSTEM
    use_custom_lists(context, proxy=["blocked.example"])

    assert dns_of(context, profile)["servers"] == [BOOTSTRAP, "localhost"]


def test_active_vpn_replaces_doh_with_system_resolver(context, profile, vpn):
    """DoH поверх VPN даёт кольцевую зависимость: резолвит системный резолвер."""
    assert dns_of(context, profile) == {"servers": [BOOTSTRAP, "localhost"]}


@pytest.mark.parametrize(
    ("reported", "address", "port"),
    [
        ("10.222.0.7", "10.222.0.7", 53),
        ("IP4.DNS[1]:10.222.0.7:5353", "10.222.0.7", 5353),
    ],
    ids=["plain", "nmcli"],
)
def test_vpn_list_domains_use_the_vpn_dns_server(
    context, profile, vpn, monkeypatch, reported, address, port
):
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: [reported])
    use_custom_lists(context, vpn=["corp.example", "10.14.0.0/16"], direct=["direct.example"])

    assert dns_of(context, profile)["servers"] == [
        BOOTSTRAP,
        direct_dns("domain:direct.example"),
        {
            "address": address,
            "port": port,
            "domains": ["domain:corp.example"],
            "skipFallback": True,
        },
        "localhost",
    ]


def test_vpn_without_dns_servers_resolves_its_domains_locally(context, profile, vpn, monkeypatch):
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: [])
    use_custom_lists(context, vpn=["corp.example"])

    assert dns_of(context, profile)["servers"] == [
        BOOTSTRAP,
        direct_dns("domain:corp.example"),
        "localhost",
    ]


def test_unreadable_vpn_dns_address_falls_back_to_public_resolver(
    context, profile, vpn, monkeypatch
):
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: ["not-an-address"])
    use_custom_lists(context, vpn=["corp.example"])

    assert dns_of(context, profile)["servers"][1] == {
        "address": "8.8.8.8",
        "port": 53,
        "domains": ["domain:corp.example"],
        "skipFallback": True,
    }


def test_vpn_list_is_ignored_while_the_vpn_is_down(context, profile):
    use_custom_lists(context, vpn=["corp.example"])

    assert dns_of(context, profile)["servers"] == [BOOTSTRAP, {"address": DOH}]


@needs_xray
@pytest.mark.parametrize("provider", DnsProvider.ALL)
def test_core_accepts_split_dns(context, profile, tmp_path, provider):
    context.config.dns.provider = provider
    use_custom_lists(
        context,
        direct=["direct.example", "geosite:category-ru", "geoip:ru"],
        proxy=["*.blocked.example", "geosite:google"],
    )

    config = build_session_config(context, profile)

    assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)
```

В старом наборе один тест проверял, что DoH стоит первым сервером. Теперь
первым идёт сервер для имени профиля, а основной — последним:

Изменить `tests/test_core_config_builder.py`:

```diff
--- a/tests/test_core_config_builder.py
+++ b/tests/test_core_config_builder.py
@@ -182,7 +182,7 @@ def test_doh_bypasses_proxy_when_dns_via_proxy_is_off(context, profile):
     config = build_session_config(context, profile)
 
     assert config is not None
-    assert _dns_addresses(config)[0] == "https+local://cloudflare-dns.com/dns-query"
+    assert _dns_addresses(config)[-1] == "https+local://cloudflare-dns.com/dns-query"
 
 
 def test_dot_server_is_skipped(context, profile):
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_config_builder.py tests/test_core_dns_config.py -q`
Expected: `18 failed, 15 passed`

**Step 3: Реализовать**

Изменить `src/core/dns_config.py`:

```diff
--- a/src/core/dns_config.py
+++ b/src/core/dns_config.py
@@ -1,14 +1,27 @@
 """Блок `dns` конфига xray-core.
 
 Сервер описывается сразу в формате ядра: строка `"localhost"` либо объект
-`{"address", "port"?, "domains"?}`. Ядро сначала спрашивает серверы, у которых
-`domains` совпал с именем, затем остальные по порядку.
+`{"address", "port"?, "domains"?, "skipFallback"?}`. Ядро сначала спрашивает
+серверы, у которых `domains` совпал с именем, затем остальные по порядку;
+сервер со `skipFallback` чужих имён не получает вовсе.
+
+Раскладка (split-DNS):
+
+1. имя сервера профиля — системный резолвер;
+2. домены списков — по порядку групп маршрутизации: «напрямую» резолвит
+   системный резолвер, «через VPN» — DNS-сервер VPN, «через прокси» —
+   удалённый DNS;
+3. всё остальное — основной DNS из настроек.
+
+Системный резолвер помечен `skipFallback`: если удалённый DNS недоступен
+(туннель упал), остальные имена не утекают провайдеру.
 """
 
 from __future__ import annotations
 
 import logging
 import re
+from collections.abc import Sequence
 from typing import Any
 
 from src.db.config import DnsSettings
@@ -38,15 +51,19 @@ def parse_dns_endpoint(raw: str) -> tuple[str, int] | None:
 
 
 def _server(
-    address: str, *, port: int | None = None, domains: list[str] | None = None
+    address: str,
+    *,
+    port: int | None = None,
+    domains: list[str] | None = None,
 ) -> DnsServer:
-    if address == LOCALHOST and not domains:
-        return LOCALHOST
+    """Сервер в формате ядра; с `domains` он обслуживает только их."""
+    if not domains:
+        return address if port is None else {"address": address, "port": port}
     server: dict[str, Any] = {"address": address}
     if port is not None:
         server["port"] = port
-    if domains:
-        server["domains"] = list(domains)
+    server["domains"] = list(domains)
+    server["skipFallback"] = True
     return server
 
 
@@ -61,7 +78,7 @@ def _main_server(dns_url: str, *, through_proxy: bool) -> DnsServer | None:
         # маршрутизации; обычный `https://` — через неё, то есть в прокси.
         if not through_proxy:
             dns_url = "https+local://" + dns_url[len("https://") :]
-        return _server(dns_url)
+        return {"address": dns_url}
     if dns_url.startswith("tls://"):
         # DoT в xray-core нет: адрес `tls://…` оно прочло бы как имя UDP-сервера.
         logger.warning("DNS-over-TLS не поддерживается xray-core, %s пропущен", dns_url)
@@ -88,8 +105,8 @@ def build_dns(
     settings: DnsSettings,
     *,
     proxy_host: str,
+    domain_groups: Sequence[tuple[str, list[str]]] = (),
     vpn_active: bool = False,
-    vpn_domains: list[str] | None = None,
     vpn_dns_servers: list[str] | None = None,
 ) -> dict[str, Any]:
     """Собрать блок `dns`.
@@ -97,8 +114,9 @@ def build_dns(
     Args:
         settings: настройки DNS приложения.
         proxy_host: адрес сервера профиля; домен резолвится системным резолвером.
+        domain_groups: доменные правила списков по группам (`direct`, `vpn`,
+            `proxy`) в порядке групп маршрутизации.
         vpn_active: поднят VPN NetworkManager, привязанный к профилю.
-        vpn_domains: доменные правила списка «через VPN».
         vpn_dns_servers: DNS-серверы VPN-подключения, как их отдал NetworkManager.
     """
     dns_url = settings.get_dns_url()
@@ -108,18 +126,33 @@ def build_dns(
         logger.info("VPN активен: DoH/DoT заменён системным резолвером")
         dns_url = "local"
 
-    servers: list[DnsServer] = []
+    # Без удалённого сервера (системный DNS, пропущенный DoT) всё резолвит
+    # системный резолвер — тогда он законный сервер по умолчанию.
+    main = _main_server(dns_url, through_proxy=settings.use_proxy) or LOCALHOST
+    main_is_remote = main != LOCALHOST
 
-    main = _main_server(dns_url, through_proxy=settings.use_proxy)
-    if main is not None:
-        servers.append(main)
+    servers: list[DnsServer] = []
 
     # Имя сервера профиля резолвит системный резолвер: DNS через прокси ждал бы
     # соединения с прокси, а оно — этого самого ответа.
-    bootstrap = [proxy_host] if proxy_host and not proxy_host[0].isdigit() else []
-    servers.append(_server(LOCALHOST, domains=bootstrap))
+    if proxy_host and not proxy_host[0].isdigit():
+        servers.append(_server(LOCALHOST, domains=[f"full:{proxy_host}"]))
+
+    for group, domains in domain_groups:
+        if not domains:
+            continue
+        if group == "direct":
+            servers.append(_server(LOCALHOST, domains=domains))
+        elif group == "vpn":
+            servers.append(_vpn_server(vpn_dns_servers or [], domains))
+        elif group == "proxy" and main_is_remote:
+            # Иначе домен из proxy-списка мог бы совпасть с доменами direct-сервера
+            # ниже и отрезолвиться в сети провайдера.
+            servers.append({**_as_object(main), "domains": list(domains)})
+
+    servers.append(main)
+    return {"servers": servers}
 
-    if vpn_active and vpn_domains:
-        servers.append(_vpn_server(vpn_dns_servers or [], vpn_domains))
 
-    return {"servers": servers}
+def _as_object(server: DnsServer) -> dict[str, Any]:
+    return {"address": server} if isinstance(server, str) else dict(server)
```

Изменить `src/core/config_builder.py`:

```diff
--- a/src/core/config_builder.py
+++ b/src/core/config_builder.py
@@ -84,10 +84,13 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
                 routing.load_lists_from_files(context.config_dir)
 
         route_rules: list[dict] = []
+        try:
+            rule_order = routing.get_rule_order()
+        except AttributeError:
+            rule_order = DEFAULT_ROUTING_ORDER
         vpn_settings = profile.vpn_settings
         vpn_tag = None
         vpn_interface = None
-        over_vpn_domains_for_dns = []
         direct_domains: list[str] = []
         direct_ips: list[str] = []
         vpn_domains: list[str] = []
@@ -140,19 +143,12 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
 
             if routing.vpn_list and vpn_tag and vpn_interface:
                 vpn_domains, vpn_ips = _parse_list(routing, routing.vpn_list, catalog, "vpn")
-                if vpn_domains:
-                    over_vpn_domains_for_dns = vpn_domains
 
             if routing.proxy_list:
                 proxy_domains, proxy_ips = _parse_list(
                     routing, routing.proxy_list, catalog, "proxy"
                 )
 
-            try:
-                rule_order = routing.get_rule_order()
-            except AttributeError:
-                rule_order = DEFAULT_ROUTING_ORDER
-
             for group in rule_order:
                 if group == "direct":
                     if direct_ips:
@@ -306,13 +302,16 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
             logger.info("Profile configuration: No VPN settings, proxy only")
         vpn_active = bool(vpn_tag and vpn_interface)
         vpn_dns_servers: list[str] = []
-        if vpn_active and over_vpn_domains_for_dns:
+        if vpn_active and vpn_domains:
             vpn_dns_servers = get_vpn_dns_servers(vpn_settings.connection_name)
+        # Серверы DNS идут в том же порядке, что и группы правил: имя должен
+        # резолвить DNS той сети, в которую уйдёт сам трафик.
+        domains_by_group = {"direct": direct_domains, "vpn": vpn_domains, "proxy": proxy_domains}
         dns = build_dns(
             context.config.dns,
             proxy_host=profile.bean.server_address if profile.bean else "",
+            domain_groups=[(group, domains_by_group[group]) for group in rule_order],
             vpn_active=vpn_active,
-            vpn_domains=over_vpn_domains_for_dns,
             vpn_dns_servers=vpn_dns_servers,
         )
 
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_config_builder.py tests/test_core_dns_config.py -q`
Expected: `33 passed`

**Step 5: Commit**

```bash
git add src/core/config_builder.py \
        src/core/dns_config.py \
        tests/test_core_config_builder.py \
        tests/test_core_dns_config.py
git commit -m "feat(core): split-DNS — домены списков резолвит DNS той же сети"
```

---

### Task 5: Блок-лист

Новый список `block_list`: трафик — в `blackhole`, имена — NXDOMAIN через
`dns.hosts` со значением `#3`. Адрес-заглушка `127.0.0.1` не годится: он попал
бы под «локальные сети напрямую». Список стоит первым при любом порядке групп
(решение 8) и, как остальные списки, действует только в режиме списков.

Файл общего списка — `block_list.txt` рядом с остальными.

**Files:**
- Modify: `src/db/config.py` (`RoutingSettings.block_list`, `LIST_FILES`)
- Modify: `src/core/config_builder.py`, `src/core/dns_config.py`
- Modify: `src/core/xray_manager.py` (`_SERVICE_TAGS`: трафик в `block` — не трафик прокси)
- Test: `tests/test_core_routing_rules.py`, `tests/test_db_config_routing_entries.py`

**Step 1: Написать падающие тесты**

Изменить `tests/test_core_routing_rules.py`:

```diff
--- a/tests/test_core_routing_rules.py
+++ b/tests/test_core_routing_rules.py
@@ -9,11 +9,13 @@ import pytest
 from src.core import config_builder
 from src.core.config_builder import build_session_config
 from src.core.geo import GeoCatalog
+from src.db.config import RoutingMode
 from tests.support.session import (
     XRAY,
     make_context,
     make_profile,
     rule_values,
+    rules_to,
     use_bundled_geo,
     use_custom_lists,
     with_socks_inbound,
@@ -93,3 +95,80 @@ def test_core_accepts_lists_with_unknown_geo_categories(context, profile, tmp_pa
     config = build_session_config(context, profile)
 
     assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)
+
+
+# --- блок-лист ------------------------------------------------------------
+
+
+def test_block_list_goes_to_blackhole_before_every_other_group(context, profile):
+    """Блокировка главнее пользовательских групп при любом их порядке."""
+    use_custom_lists(
+        context,
+        block=["ads.example", "203.0.113.0/24"],
+        direct=["direct.example"],
+        proxy=["proxy.example"],
+    )
+    context.config.routing.rule_order = ["proxy", "direct", "vpn"]
+
+    config = build_session_config(context, profile)
+
+    rules = config["routing"]["rules"]
+    assert [r["outboundTag"] for r in rules[:2]] == ["block", "block"]
+    assert rule_values(config, "block", "domain") == ["domain:ads.example"]
+    assert rule_values(config, "block", "ip") == ["203.0.113.0/24"]
+    assert {"protocol": "blackhole", "tag": "block"} in config["outbounds"]
+
+
+def test_blocked_domains_get_nxdomain(context, profile):
+    """Соединение по IP режет правило, а имя не резолвится вовсе: `#3` — NXDOMAIN.
+
+    Адрес-заглушка `127.0.0.1` не годится: он попал бы под «локальные сети
+    напрямую», и заблокированный запрос ушёл бы мимо блокировки.
+    """
+    use_custom_lists(context, block=["ads.example", "tracker", "geosite:category-ru", "10.0.0.1"])
+
+    config = build_session_config(context, profile)
+
+    assert config["dns"]["hosts"] == {
+        "domain:ads.example": "#3",
+        "keyword:tracker": "#3",
+        "geosite:category-ru": "#3",
+    }
+
+
+def test_no_block_outbound_without_block_list(context, profile):
+    use_custom_lists(context, direct=["direct.example"])
+
+    config = build_session_config(context, profile)
+
+    assert "block" not in {o.get("tag") for o in config["outbounds"]}
+    assert "hosts" not in config["dns"]
+
+
+def test_block_list_is_not_applied_in_proxy_all_mode(context, profile):
+    """В режиме «весь трафик через прокси» списки не действуют — и этот тоже."""
+    use_custom_lists(context, block=["ads.example"])
+    context.config.routing.mode = RoutingMode.PROXY_ALL
+
+    config = build_session_config(context, profile)
+
+    assert not rules_to(config, "block")
+    assert "hosts" not in config["dns"]
+
+
+@needs_xray
+def test_core_accepts_block_list(context, profile, tmp_path):
+    use_custom_lists(
+        context,
+        block=["ads.example", "tracker", "full:exact.example", "geosite:category-ru", "10.0.0.1"],
+    )
+
+    config = build_session_config(context, profile)
+
+    assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)
+
+
+def test_blocked_traffic_is_not_counted_as_proxy_traffic():
+    from src.core.xray_manager import XrayManager
+
+    assert "block" in XrayManager._SERVICE_TAGS
```

Изменить `tests/test_db_config_routing_entries.py`:

```diff
--- a/tests/test_db_config_routing_entries.py
+++ b/tests/test_db_config_routing_entries.py
@@ -79,3 +79,28 @@ def test_comma_separated_line_is_split():
 
 def test_blank_entries_are_skipped():
     assert parse("", "  ", ",") == ([], [])
+
+
+def test_block_list_is_saved_next_to_other_lists(tmp_path):
+    routing = RoutingSettings(
+        block_list=["ads.example", "# комментарий"], direct_list=["a.example"]
+    )
+
+    assert routing.save_lists_to_files(tmp_path)
+    assert (tmp_path / "block_list.txt").read_text(encoding="utf-8").splitlines() == [
+        "ads.example",
+        "# комментарий",
+    ]
+
+    loaded = RoutingSettings()
+    loaded.load_lists_from_files(tmp_path)
+    assert loaded.block_list == ["ads.example"]
+    assert loaded.direct_list == ["a.example"]
+
+
+def test_missing_block_list_file_means_empty_list(tmp_path):
+    routing = RoutingSettings(block_list=["stale.example"])
+
+    routing.load_lists_from_files(tmp_path)
+
+    assert routing.block_list == []
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_routing_rules.py tests/test_db_config_routing_entries.py -q`
Expected: `5 failed, 30 passed`

**Step 3: Реализовать**

Изменить `src/db/config.py`:

```diff
--- a/src/db/config.py
+++ b/src/db/config.py
@@ -424,6 +424,14 @@ def classify_routing_entry(entry: str) -> tuple[str, str] | None:
 ROUTING_GROUPS = ["direct", "vpn", "proxy"]
 DEFAULT_ROUTING_ORDER = ["direct", "vpn", "proxy"]
 
+# Списки общей маршрутизации лежат текстовыми файлами в каталоге конфигурации.
+LIST_FILES = {
+    "proxy_list": "proxy_list.txt",
+    "direct_list": "direct_list.txt",
+    "vpn_list": "vpn_list.txt",
+    "block_list": "block_list.txt",
+}
+
 # Сети, которые никогда не должны уходить в прокси (bypass_local_networks)
 LOCAL_NETWORKS: tuple[str, ...] = (
     "127.0.0.0/8",
@@ -445,6 +453,9 @@ class RoutingSettings(ConfigBase):
     proxy_list: list[str] = field(default_factory=list)
     direct_list: list[str] = field(default_factory=list)
     vpn_list: list[str] = field(default_factory=list)
+    # Блокировка: blackhole для трафика и NXDOMAIN для имён. Применяется раньше
+    # остальных групп и в порядке групп не участвует.
+    block_list: list[str] = field(default_factory=list)
     bypass_local_networks: bool = False
     # direct/vpn/proxy
     rule_order: list[str] = field(default_factory=lambda: DEFAULT_ROUTING_ORDER.copy())
@@ -468,26 +479,16 @@ class RoutingSettings(ConfigBase):
 
     def load_lists_from_files(self, config_dir: Path) -> None:
         """Load routing lists from files in config directory."""
-        proxy_file = config_dir / "proxy_list.txt"
-        direct_file = config_dir / "direct_list.txt"
-        vpn_file = config_dir / "vpn_list.txt"
-
-        self.proxy_list = self.load_list_file(proxy_file)
-        self.direct_list = self.load_list_file(direct_file)
-        self.vpn_list = self.load_list_file(vpn_file)
+        for name in LIST_FILES:
+            setattr(self, name, self.load_list_file(config_dir / LIST_FILES[name]))
 
     def save_lists_to_files(self, config_dir: Path) -> bool:
         """Save routing lists to files in config directory."""
         try:
             config_dir.mkdir(parents=True, exist_ok=True)
 
-            proxy_file = config_dir / "proxy_list.txt"
-            direct_file = config_dir / "direct_list.txt"
-            vpn_file = config_dir / "vpn_list.txt"
-
-            proxy_file.write_text("\n".join(self.proxy_list), encoding="utf-8")
-            direct_file.write_text("\n".join(self.direct_list), encoding="utf-8")
-            vpn_file.write_text("\n".join(self.vpn_list), encoding="utf-8")
+            for name, filename in LIST_FILES.items():
+                (config_dir / filename).write_text("\n".join(getattr(self, name)), encoding="utf-8")
 
             return True
         except Exception:
```

Изменить `src/core/config_builder.py`:

```diff
--- a/src/core/config_builder.py
+++ b/src/core/config_builder.py
@@ -33,6 +33,8 @@ from src.sys.vpn import (
 
 logger = logging.getLogger("tenga.core.config_builder")
 
+BLOCK_TAG = "block"
+
 
 def _parse_list(
     routing: RoutingSettings, entries: list[str], catalog: GeoCatalog, list_name: str
@@ -97,6 +99,7 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
         vpn_ips: list[str] = []
         proxy_domains: list[str] = []
         proxy_ips: list[str] = []
+        block_domains: list[str] = []
 
         # Process VPN routing rules (only if VPN is enabled and active)
         if vpn_settings and vpn_settings.enabled:
@@ -149,6 +152,15 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
                     routing, routing.proxy_list, catalog, "proxy"
                 )
 
+            # Блок-лист — раньше пользовательских групп при любом их порядке.
+            block_domains, block_ips = _parse_list(routing, routing.block_list, catalog, "block")
+            if block_domains:
+                route_rules.append(
+                    {"type": "field", "domain": block_domains, "outboundTag": BLOCK_TAG}
+                )
+            if block_ips:
+                route_rules.append({"type": "field", "ip": block_ips, "outboundTag": BLOCK_TAG})
+
             for group in rule_order:
                 if group == "direct":
                     if direct_ips:
@@ -288,6 +300,9 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
             )
             outbounds.append(vpn_outbound)
 
+        if any(rule["outboundTag"] == BLOCK_TAG for rule in route_rules):
+            outbounds.append({"protocol": "blackhole", "tag": BLOCK_TAG})
+
         if vpn_settings:
             if vpn_settings.enabled:
                 if vpn_tag:
@@ -311,6 +326,7 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
             context.config.dns,
             proxy_host=profile.bean.server_address if profile.bean else "",
             domain_groups=[(group, domains_by_group[group]) for group in rule_order],
+            blocked_domains=block_domains,
             vpn_active=vpn_active,
             vpn_dns_servers=vpn_dns_servers,
         )
```

Изменить `src/core/dns_config.py`:

```diff
--- a/src/core/dns_config.py
+++ b/src/core/dns_config.py
@@ -30,6 +30,9 @@ logger = logging.getLogger("tenga.core.dns_config")
 
 # Системный резолвер процесса ядра.
 LOCALHOST = "localhost"
+# Значение `hosts`: ответить кодом 3 (NXDOMAIN). Адрес-заглушка вроде 127.0.0.1
+# не годится — он попадает под «локальные сети напрямую».
+NXDOMAIN = "#3"
 # Запасной адрес, когда DNS-сервер VPN не удалось разобрать.
 FALLBACK_VPN_DNS = ("8.8.8.8", 53)
 
@@ -106,6 +109,7 @@ def build_dns(
     *,
     proxy_host: str,
     domain_groups: Sequence[tuple[str, list[str]]] = (),
+    blocked_domains: Sequence[str] = (),
     vpn_active: bool = False,
     vpn_dns_servers: list[str] | None = None,
 ) -> dict[str, Any]:
@@ -116,6 +120,7 @@ def build_dns(
         proxy_host: адрес сервера профиля; домен резолвится системным резолвером.
         domain_groups: доменные правила списков по группам (`direct`, `vpn`,
             `proxy`) в порядке групп маршрутизации.
+        blocked_domains: доменные правила блок-листа — на них отвечаем NXDOMAIN.
         vpn_active: поднят VPN NetworkManager, привязанный к профилю.
         vpn_dns_servers: DNS-серверы VPN-подключения, как их отдал NetworkManager.
     """
@@ -151,7 +156,20 @@ def build_dns(
             servers.append({**_as_object(main), "domains": list(domains)})
 
     servers.append(main)
-    return {"servers": servers}
+
+    dns: dict[str, Any] = {"servers": servers}
+    if blocked_domains:
+        dns["hosts"] = {_hosts_key(rule): NXDOMAIN for rule in blocked_domains}
+    return dns
+
+
+def _hosts_key(rule: str) -> str:
+    """Доменное правило в виде ключа `hosts`.
+
+    Голую строку правило маршрутизации считает подстрокой, а `hosts` — точным
+    именем; чтобы оба блокировали одно и то же, подстроку называем явно.
+    """
+    return rule if ":" in rule else f"keyword:{rule}"
 
 
 def _as_object(server: DnsServer) -> dict[str, Any]:
```

Изменить `src/core/xray_manager.py`:

```diff
--- a/src/core/xray_manager.py
+++ b/src/core/xray_manager.py
@@ -43,9 +43,10 @@ class XrayManager:
     """
 
     # Служебные каналы в счёт трафика не идут: direct — мимо прокси, vpn —
-    # через туннель, api — сам опрос статистики, остальные три — резолвинг DNS.
+    # через туннель, block — в никуда, api — сам опрос статистики, остальные три —
+    # резолвинг DNS.
     # Список отражает теги, которые заводит `src/core/config_builder.py`.
-    _SERVICE_TAGS = frozenset({"direct", "vpn", "api", "main-dns", "local-dns", "vpn-dns"})
+    _SERVICE_TAGS = frozenset({"direct", "vpn", "block", "api", "main-dns", "local-dns", "vpn-dns"})
 
     def __init__(
         self,
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_routing_rules.py tests/test_db_config_routing_entries.py -q`
Expected: `35 passed`

**Step 5: Commit**

```bash
git add src/core/config_builder.py \
        src/core/dns_config.py \
        src/core/xray_manager.py \
        src/db/config.py \
        tests/test_core_routing_rules.py \
        tests/test_db_config_routing_entries.py
git commit -m "feat(core): блок-лист — blackhole для трафика и NXDOMAIN для имён"
```

---

### Task 6: Прямой выход в режиме TUN — привязка к физическому интерфейсу

Предпосылка для задач 7 и 8 и самостоятельное исправление («Что проверено»,
п. 7 и 8). В режиме TUN outbound `direct` и соединение с сервером профиля
привязываются к физическому интерфейсу (`sockopt.interface`) — так же, как это
уже делается для профилей с VPN. Собственный TUN приложения исключается из
кандидатов. Профиль с сервером на loopback (локальный обфускатор) не
привязывается: через сетевой интерфейс его не достать.

Маршрут `/32` к серверу профиля (`src/sys/tun_route.py`) остаётся: он нужен
ядрам Linux старше 5.7 без `CAP_NET_RAW` и ничему не мешает.

**Files:**
- Modify: `src/sys/vpn.py` (`get_default_interface` — параметр `exclude`)
- Modify: `src/core/config_builder.py` (`_physical_interface`, `_bind_to_interface`)
- Modify: `tests/conftest.py` — сборка в тестах не спрашивает систему
- Create: `tests/test_core_tun_outbounds.py`, `tests/test_sys_vpn_default_interface.py`

**Step 1: Написать падающие тесты**

Создать `tests/test_core_tun_outbounds.py`:

```python
"""Привязка исходящих соединений к физическому интерфейсу в режиме TUN.

Маршрут по умолчанию в режиме TUN ведёт в сам TUN. Соединение ядра «напрямую»
без привязки к интерфейсу вернулось бы в туннель и зациклилось.
"""

from __future__ import annotations

import pytest

from src.core import config_builder
from src.core.config_builder import build_session_config
from src.db.config import ProxyMode, VpnSettings
from tests.support.session import make_context, make_profile, use_bundled_geo


@pytest.fixture(autouse=True)
def geo(monkeypatch):
    use_bundled_geo(monkeypatch)


@pytest.fixture
def context(tmp_path):
    return make_context(tmp_path)


@pytest.fixture
def profile(context):
    return make_profile(context)


@pytest.fixture
def physical(monkeypatch):
    """Физический интерфейс системы — eth0; запоминает, что просили исключить."""
    calls: list[tuple] = []

    def fake(vpn_interface=None, exclude=()):
        calls.append((vpn_interface, tuple(exclude)))
        return "eth0"

    monkeypatch.setattr(config_builder, "get_default_interface", fake)
    return calls


def outbound(config: dict, tag: str) -> dict:
    return next(o for o in config["outbounds"] if o.get("tag") == tag)


def bound_interface(config: dict, tag: str) -> str | None:
    return outbound(config, tag).get("streamSettings", {}).get("sockopt", {}).get("interface")


def test_tun_mode_binds_direct_and_proxy_to_the_physical_interface(context, profile, physical):
    context.config.proxy_mode = ProxyMode.TUN
    context.config.tun_name = "xray7"

    config = build_session_config(context, profile)

    assert bound_interface(config, "direct") == "eth0"
    assert bound_interface(config, profile.bean.display_name) == "eth0"
    # Собственный TUN среди кандидатов быть не должен: при пересборке конфига на
    # поднятом туннеле маршрут по умолчанию указывает именно на него.
    assert physical == [(None, ("xray7",))]


def test_binding_keeps_other_stream_settings_of_the_profile(context, profile, physical):
    context.config.proxy_mode = ProxyMode.TUN

    config = build_session_config(context, profile)

    stream = outbound(config, profile.bean.display_name)["streamSettings"]
    assert stream["security"] == "tls"
    assert stream["tlsSettings"] == {"serverName": "proxy.example.org"}


def test_system_proxy_mode_binds_nothing(context, profile, physical):
    """Без TUN маршрут по умолчанию и так ведёт в сеть — привязка только мешала бы."""
    context.config.proxy_mode = ProxyMode.SYSTEM_PROXY

    config = build_session_config(context, profile)

    assert bound_interface(config, "direct") is None
    assert bound_interface(config, profile.bean.display_name) is None
    assert physical == []


def test_unknown_physical_interface_leaves_outbounds_unbound(context, profile, monkeypatch):
    context.config.proxy_mode = ProxyMode.TUN
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: None)

    config = build_session_config(context, profile)

    assert bound_interface(config, "direct") is None


def test_vpn_profile_keeps_its_explicit_direct_interface(context, profile, physical, monkeypatch):
    profile.vpn_settings = VpnSettings(
        enabled=True, connection_name="corp", direct_interface="wlan9"
    )
    monkeypatch.setattr(config_builder, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(config_builder, "get_vpn_interface", lambda _name: "tun0")
    context.config.proxy_mode = ProxyMode.TUN

    config = build_session_config(context, profile)

    assert bound_interface(config, "direct") == "wlan9"
    assert bound_interface(config, "vpn") == "tun0"
    assert physical == []


def test_vpn_profile_detects_interface_skipping_vpn_and_own_tun(
    context, profile, physical, monkeypatch
):
    profile.vpn_settings = VpnSettings(enabled=True, connection_name="corp")
    monkeypatch.setattr(config_builder, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(config_builder, "get_vpn_interface", lambda _name: "tun0")
    context.config.proxy_mode = ProxyMode.SYSTEM_PROXY
    context.config.tun_name = "xray7"

    config = build_session_config(context, profile)

    assert bound_interface(config, "direct") == "eth0"
    assert physical == [("tun0", ("xray7",))]


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost"])
def test_profile_on_loopback_is_not_bound(context, physical, host):
    """Локальный обфускатор перед сервером слушает на loopback — через eth0 его не достать."""
    profile = make_profile(
        context, f"vless://11111111-1111-1111-1111-111111111111@{host}:443?security=tls#L"
    )
    context.config.proxy_mode = ProxyMode.TUN

    config = build_session_config(context, profile)

    assert bound_interface(config, profile.bean.display_name) is None
    assert bound_interface(config, "direct") == "eth0"
```

Создать `tests/test_sys_vpn_default_interface.py`:

```python
"""Определение физического интерфейса для прямого выхода."""

from __future__ import annotations

import subprocess

from src.sys import vpn

ROUTES_WITH_TUN_UP = """\
default dev xray0 scope link
default via 10.8.0.1 dev tun0 proto static metric 50
default via 192.168.0.1 dev wlp1s0 proto dhcp src 192.168.0.154 metric 600
"""


def fake_ip(monkeypatch, routes: str) -> None:
    def run(cmd, **_kwargs):
        stdout = routes if cmd[:4] == ["ip", "route", "show", "default"] else ""
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(vpn.subprocess, "run", run)


def test_own_tun_is_not_a_physical_interface(monkeypatch):
    """На поднятом туннеле первый маршрут по умолчанию — сам TUN приложения."""
    fake_ip(monkeypatch, ROUTES_WITH_TUN_UP)

    assert vpn.get_default_interface(exclude=("xray0",)) == "wlp1s0"


def test_without_exclusions_behaviour_is_unchanged(monkeypatch):
    fake_ip(monkeypatch, "default via 192.168.0.1 dev eth0 proto dhcp metric 100\n")

    assert vpn.get_default_interface() == "eth0"
    assert vpn.get_default_interface("eth0") is None
```

С этой задачи сборщик в режиме TUN спрашивает у системы интерфейс. Чтобы
остальные тесты не зависели от сети машины, на которой идут:

Изменить `tests/conftest.py`:

```diff
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -9,6 +9,18 @@ from __future__ import annotations
 import pytest
 
 
+@pytest.fixture(autouse=True)
+def _no_system_probing(monkeypatch) -> None:
+    """Сборка конфига не должна зависеть от сети машины, на которой идут тесты.
+
+    В режиме TUN сборщик спрашивает у системы физический интерфейс. Тест,
+    которому это нужно, подменяет функцию сам.
+    """
+    from src.core import config_builder
+
+    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: None)
+
+
 @pytest.fixture(scope="session")
 def gtk_ready() -> None:
     """Skip the test unless GTK4 can talk to a display."""
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_tun_outbounds.py tests/test_sys_vpn_default_interface.py -q`
Expected: `5 failed, 5 passed`

**Step 3: Реализовать**

Изменить `src/sys/vpn.py`:

```diff
--- a/src/sys/vpn.py
+++ b/src/sys/vpn.py
@@ -2,6 +2,7 @@ from __future__ import annotations
 
 import logging
 import subprocess
+from collections.abc import Iterable
 
 logger = logging.getLogger("tenga.sys.vpn")
 
@@ -376,16 +377,21 @@ def list_network_interfaces() -> list[str]:
         return []
 
 
-def get_default_interface(vpn_interface: str | None = None) -> str | None:
+def get_default_interface(
+    vpn_interface: str | None = None, exclude: Iterable[str] = ()
+) -> str | None:
     """
     Get default network interface.
 
     Args:
         vpn_interface: VPN interface name to exclude
+        exclude: other interfaces to skip — собственный TUN приложения: на
+            поднятом туннеле маршрут по умолчанию указывает именно на него
 
     Returns:
         Default interface name or None
     """
+    skipped = set(exclude)
     try:
         result = subprocess.run(
             ["ip", "route", "show", "default"],
@@ -406,6 +412,8 @@ def get_default_interface(vpn_interface: str | None = None) -> str | None:
                             # Exclude VPN interfaces
                             if vpn_interface and interface == vpn_interface:
                                 continue
+                            if interface in skipped:
+                                continue
                             if interface.startswith(("tun", "tap")):
                                 continue
                             return interface
@@ -429,6 +437,8 @@ def get_default_interface(vpn_interface: str | None = None) -> str | None:
                         continue
                     if vpn_interface and interface == vpn_interface:
                         continue
+                    if interface in skipped:
+                        continue
                     if interface.startswith(("tun", "tap")):
                         continue
                     if interface.startswith(("eth", "enp", "wlan", "wlp", "ens")):
```

Изменить `src/core/config_builder.py`:

```diff
--- a/src/core/config_builder.py
+++ b/src/core/config_builder.py
@@ -7,6 +7,7 @@ AppContext explicitly instead of reading it from `self`.
 
 from __future__ import annotations
 
+import ipaddress
 import logging
 import random
 import socket
@@ -14,7 +15,7 @@ import socket
 from src.core.context import AppContext
 from src.core.dns_config import build_dns
 from src.core.geo import GeoCatalog, asset_dirs, load_catalog
-from src.core.proxy_mode import build_inbounds_for_mode
+from src.core.proxy_mode import build_inbounds_for_mode, normalize_proxy_mode
 from src.core.transport_tweaks import apply_transport_tweaks
 from src.db.config import (
     DEFAULT_ROUTING_ORDER,
@@ -22,6 +23,7 @@ from src.db.config import (
     ProxyMode,
     RoutingMode,
     RoutingSettings,
+    VpnSettings,
 )
 from src.db.profiles import ProfileEntry
 from src.sys.vpn import (
@@ -58,6 +60,40 @@ def _parse_list(
     return domains, ips
 
 
+def _physical_interface(
+    *,
+    tun_mode: bool,
+    tun_name: str,
+    vpn_interface: str | None,
+    vpn_settings: VpnSettings | None,
+) -> str | None:
+    """Интерфейс, через который ядро выходит в сеть мимо туннелей.
+
+    None — привязка не нужна (системный прокси без VPN) или интерфейс не найден.
+    """
+    if vpn_interface:
+        explicit = getattr(vpn_settings, "direct_interface", "") or ""
+        return explicit or get_default_interface(vpn_interface, exclude=(tun_name,))
+    if tun_mode:
+        return get_default_interface(exclude=(tun_name,))
+    return None
+
+
+def _is_loopback(host: str) -> bool:
+    """Сервер на этой же машине (локальный обфускатор): через сетевой интерфейс не достать."""
+    if host == "localhost":
+        return True
+    try:
+        return ipaddress.ip_address(host).is_loopback
+    except ValueError:
+        return False
+
+
+def _bind_to_interface(outbound: dict, interface: str) -> None:
+    sockopt = outbound.setdefault("streamSettings", {}).setdefault("sockopt", {})
+    sockopt["interface"] = interface
+
+
 def build_session_config(context: AppContext, profile: ProfileEntry | None) -> dict | None:
     """Create xray-core configuration for profile."""
     try:
@@ -245,35 +281,23 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
                         )
 
         # Outbounds
+        runtime_mode = normalize_proxy_mode(getattr(context.config, "proxy_mode", None))
+        tun_name = getattr(context.config, "tun_name", "xray0")
         direct_outbound = {"protocol": "freedom", "tag": "direct"}
-        if vpn_tag and vpn_interface and vpn_settings:
-            direct_interface = getattr(vpn_settings, "direct_interface", "") or ""
-            if not direct_interface:
-                direct_interface = get_default_interface(vpn_interface)
-
-            if direct_interface:
-                direct_outbound["streamSettings"] = {
-                    "sockopt": {
-                        "interface": direct_interface,
-                    },
-                }
-                logger.info(
-                    "Direct outbound bound to interface: %s (bypassing VPN %s)",
-                    direct_interface,
-                    vpn_interface,
-                )
-
-                # CRITICAL: Proxy outbound must also use direct interface to reach proxy server
-                # Otherwise it goes through VPN tunnel which may not route to proxy correctly
-                if "streamSettings" not in outbound:
-                    outbound["streamSettings"] = {}
-                if "sockopt" not in outbound["streamSettings"]:
-                    outbound["streamSettings"]["sockopt"] = {}
-                outbound["streamSettings"]["sockopt"]["interface"] = direct_interface
-                logger.info(
-                    "Proxy outbound bound to interface: %s (bypassing VPN to reach proxy server)",
-                    direct_interface,
-                )
+        physical_interface = _physical_interface(
+            tun_mode=runtime_mode == ProxyMode.TUN,
+            tun_name=tun_name,
+            vpn_interface=vpn_interface if vpn_tag else None,
+            vpn_settings=vpn_settings,
+        )
+        if physical_interface:
+            # И прямой выход, и соединение с сервером профиля должны уходить через
+            # физический интерфейс: маршрут по умолчанию ведёт в туннель (TUN
+            # приложения или VPN), и без привязки они вернулись бы в него же.
+            _bind_to_interface(direct_outbound, physical_interface)
+            if not _is_loopback(profile.bean.server_address):
+                _bind_to_interface(outbound, physical_interface)
+            logger.info("Direct and proxy outbounds bound to interface: %s", physical_interface)
 
         outbounds = [
             outbound,
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_tun_outbounds.py tests/test_sys_vpn_default_interface.py -q`
Expected: `10 passed`

**Step 5: Commit**

```bash
git add src/core/config_builder.py \
        src/sys/vpn.py \
        tests/conftest.py \
        tests/test_core_tun_outbounds.py \
        tests/test_sys_vpn_default_interface.py
git commit -m "fix(core): привязывать прямой выход и прокси к физическому интерфейсу в режиме TUN"
```

---

### Task 7: Готовые правила

Два тумблера в `RoutingSettings` (решения 1 и 2):

- `bypass_local_networks` — уже есть; меняется значение по умолчанию (`True`) и
  место правила: после пользовательских групп, а не внутри списка «Напрямую».
- `ru_direct` — новое: `geoip:ru`, `geosite:category-ru`,
  `geosite:category-gov-ru` в direct, тоже после пользовательских групп, плюс
  эти геосайты в доменах системного резолвера. Категории проходят через каталог
  из задачи 2: без баз правило просто не пишется.

Пользовательский proxy-список обязан бить готовое `geoip:ru` при любом порядке
групп — это и проверяют тесты.

**Files:**
- Modify: `src/db/config.py` (`RoutingSettings`)
- Modify: `src/core/geo.py` (`RU_DIRECT_GEOSITES`, `RU_DIRECT_GEOIP`)
- Modify: `src/core/config_builder.py`
- Test: `tests/test_core_routing_rules.py`, `tests/test_core_dns_config.py`

**Step 1: Написать падающие тесты**

Изменить `tests/test_core_routing_rules.py`:

```diff
--- a/tests/test_core_routing_rules.py
+++ b/tests/test_core_routing_rules.py
@@ -9,7 +9,7 @@ import pytest
 from src.core import config_builder
 from src.core.config_builder import build_session_config
 from src.core.geo import GeoCatalog
-from src.db.config import RoutingMode
+from src.db.config import LOCAL_NETWORKS, RoutingMode, RoutingSettings
 from tests.support.session import (
     XRAY,
     make_context,
@@ -172,3 +172,109 @@ def test_blocked_traffic_is_not_counted_as_proxy_traffic():
     from src.core.xray_manager import XrayManager
 
     assert "block" in XrayManager._SERVICE_TAGS
+
+
+# --- готовые правила ------------------------------------------------------
+
+
+def rule_index(config: dict, key: str, value: str) -> int:
+    for index, rule in enumerate(config["routing"]["rules"]):
+        if value in rule.get(key, []):
+            return index
+    raise AssertionError(f"нет правила с {key}={value}")
+
+
+def test_local_networks_go_direct_by_default():
+    assert RoutingSettings().bypass_local_networks is True
+
+
+def test_local_networks_rule_comes_after_user_lists(context, profile):
+    """Готовое правило не должно перебивать явное: подсеть из списка главнее.
+
+    Иначе `10.14.0.0/16` из списка «через VPN» при порядке «напрямую → VPN» ушла
+    бы напрямую, совпав с `10.0.0.0/8`.
+    """
+    use_custom_lists(context, proxy=["10.14.0.0/16"], direct=["direct.example"])
+    context.config.routing.bypass_local_networks = True
+    context.config.routing.rule_order = ["direct", "vpn", "proxy"]
+
+    config = build_session_config(context, profile)
+
+    assert rule_index(config, "ip", "10.14.0.0/16") < rule_index(config, "ip", "10.0.0.0/8")
+    assert set(LOCAL_NETWORKS) <= set(rule_values(config, "direct", "ip"))
+
+
+def test_local_networks_switch_can_be_turned_off(context, profile):
+    use_custom_lists(context, direct=["direct.example"])
+    context.config.routing.bypass_local_networks = False
+
+    config = build_session_config(context, profile)
+
+    assert "10.0.0.0/8" not in rule_values(config, "direct", "ip")
+
+
+def test_russian_sites_go_through_proxy_by_default(context, profile):
+    use_custom_lists(context, direct=["direct.example"])
+
+    config = build_session_config(context, profile)
+
+    assert RoutingSettings().ru_direct is False
+    assert "geoip:ru" not in str(config["routing"]["rules"])
+
+
+def test_ru_direct_adds_ip_and_domain_rules(context, profile):
+    use_custom_lists(context)
+    context.config.routing.ru_direct = True
+
+    config = build_session_config(context, profile)
+
+    assert "geoip:ru" in rule_values(config, "direct", "ip")
+    assert rule_values(config, "direct", "domain") == [
+        "geosite:category-ru",
+        "geosite:category-gov-ru",
+    ]
+
+
+@pytest.mark.parametrize("order", [["direct", "vpn", "proxy"], ["proxy", "direct", "vpn"]])
+def test_user_proxy_list_beats_ru_direct(context, profile, order):
+    """Российский домен, явно отправленный в прокси, не должен уйти напрямую."""
+    use_custom_lists(context, proxy=["blocked.ru.example", "77.88.0.0/16"])
+    context.config.routing.ru_direct = True
+    context.config.routing.rule_order = order
+
+    config = build_session_config(context, profile)
+
+    ru_rule = rule_index(config, "ip", "geoip:ru")
+    assert rule_index(config, "domain", "domain:blocked.ru.example") < ru_rule
+    assert rule_index(config, "ip", "77.88.0.0/16") < ru_rule
+
+
+def test_ru_direct_is_ignored_in_proxy_all_mode(context, profile):
+    context.config.routing.mode = RoutingMode.PROXY_ALL
+    context.config.routing.ru_direct = True
+
+    config = build_session_config(context, profile)
+
+    assert "geoip:ru" not in str(config["routing"]["rules"])
+
+
+def test_ru_direct_without_geo_bases_adds_nothing(context, profile, monkeypatch):
+    """Старая установка без геобаз: тумблер не должен ронять подключение."""
+    monkeypatch.setattr(config_builder, "load_catalog", lambda _dirs: GeoCatalog())
+    use_custom_lists(context)
+    context.config.routing.ru_direct = True
+
+    config = build_session_config(context, profile)
+
+    assert "geo" not in str(config)
+
+
+@needs_xray
+def test_core_accepts_ready_made_rules(context, profile, tmp_path):
+    use_custom_lists(context, proxy=["blocked.ru.example"], direct=["direct.example"])
+    context.config.routing.ru_direct = True
+    context.config.routing.bypass_local_networks = True
+
+    config = build_session_config(context, profile)
+
+    assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)
```

Изменить `tests/test_core_dns_config.py`:

```diff
--- a/tests/test_core_dns_config.py
+++ b/tests/test_core_dns_config.py
@@ -232,3 +232,16 @@ def test_core_accepts_split_dns(context, profile, tmp_path, provider):
     config = build_session_config(context, profile)
 
     assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)
+
+
+def test_ru_direct_resolves_russian_sites_with_the_system_resolver(context, profile):
+    """Готовое правило стоит после пользовательских: домен из proxy-списка главнее."""
+    use_custom_lists(context, proxy=["blocked.ru.example"])
+    context.config.routing.ru_direct = True
+
+    assert dns_of(context, profile)["servers"] == [
+        BOOTSTRAP,
+        {"address": DOH, "domains": ["domain:blocked.ru.example"]},
+        direct_dns("geosite:category-ru", "geosite:category-gov-ru"),
+        {"address": DOH},
+    ]
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_dns_config.py tests/test_core_routing_rules.py -q`
Expected: `7 failed, 35 passed`

**Step 3: Реализовать**

Изменить `src/db/config.py`:

```diff
--- a/src/db/config.py
+++ b/src/db/config.py
@@ -456,7 +456,10 @@ class RoutingSettings(ConfigBase):
     # Блокировка: blackhole для трафика и NXDOMAIN для имён. Применяется раньше
     # остальных групп и в порядке групп не участвует.
     block_list: list[str] = field(default_factory=list)
-    bypass_local_networks: bool = False
+    # Готовые правила; оба стоят после пользовательских групп.
+    bypass_local_networks: bool = True
+    # Российские сайты и IP — напрямую (geosite:category-ru, geoip:ru).
+    ru_direct: bool = False
     # direct/vpn/proxy
     rule_order: list[str] = field(default_factory=lambda: DEFAULT_ROUTING_ORDER.copy())
 
```

Изменить `src/core/geo.py`:

```diff
--- a/src/core/geo.py
+++ b/src/core/geo.py
@@ -29,6 +29,11 @@ SYSTEM_ASSET_DIRS = (Path("/usr/local/share/xray"), Path("/usr/share/xray"))
 GEOSITE_PREFIX = "geosite:"
 GEOIP_PREFIX = "geoip:"
 
+# Готовое правило «российские сайты и IP — напрямую». Категории проверяются по
+# каталогу, как и пользовательские: без них в базе правило просто не пишется.
+RU_DIRECT_GEOSITES = ("geosite:category-ru", "geosite:category-gov-ru")
+RU_DIRECT_GEOIP = "geoip:ru"
+
 # Поле 1, тип «строка байтов» — и у записи списка, и у названия внутри записи.
 _LENGTH_DELIMITED_FIELD_1 = 0x0A
 
```

Изменить `src/core/config_builder.py`:

```diff
--- a/src/core/config_builder.py
+++ b/src/core/config_builder.py
@@ -14,7 +14,13 @@ import socket
 
 from src.core.context import AppContext
 from src.core.dns_config import build_dns
-from src.core.geo import GeoCatalog, asset_dirs, load_catalog
+from src.core.geo import (
+    RU_DIRECT_GEOIP,
+    RU_DIRECT_GEOSITES,
+    GeoCatalog,
+    asset_dirs,
+    load_catalog,
+)
 from src.core.proxy_mode import build_inbounds_for_mode, normalize_proxy_mode
 from src.core.transport_tweaks import apply_transport_tweaks
 from src.db.config import (
@@ -156,29 +162,13 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
                     vpn_settings.connection_name,
                 )
 
-        if routing.mode == RoutingMode.PROXY_ALL:
-            if routing.bypass_local_networks:
-                local_networks = list(LOCAL_NETWORKS)
-                route_rules.append(
-                    {
-                        "type": "field",
-                        "ip": local_networks,
-                        "outboundTag": "direct",
-                    }
-                )
-                logger.debug("Added local networks bypass rule for PROXY_ALL mode")
-        elif routing.mode == RoutingMode.CUSTOM:
+        if routing.mode == RoutingMode.CUSTOM:
             catalog = load_catalog(asset_dirs(context.find_xray_binary()))
-            direct_list = list(routing.direct_list) if routing.direct_list else []
 
-            if routing.bypass_local_networks:
-                local_networks = list(LOCAL_NETWORKS)
-                for network in local_networks:
-                    if network not in direct_list:
-                        direct_list.append(network)
-
-            if direct_list:
-                direct_domains, direct_ips = _parse_list(routing, direct_list, catalog, "direct")
+            if routing.direct_list:
+                direct_domains, direct_ips = _parse_list(
+                    routing, routing.direct_list, catalog, "direct"
+                )
 
             if routing.vpn_list and vpn_tag and vpn_interface:
                 vpn_domains, vpn_ips = _parse_list(routing, routing.vpn_list, catalog, "vpn")
@@ -280,6 +270,25 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
                             proxy_domains,
                         )
 
+        # Готовые правила — после пользовательских групп: явная запись списка
+        # главнее. Подсеть из списка «через VPN» не должна уйти напрямую только
+        # потому, что входит в 10.0.0.0/8.
+        ru_direct_domains: list[str] = []
+        if routing.bypass_local_networks:
+            route_rules.append(
+                {"type": "field", "ip": list(LOCAL_NETWORKS), "outboundTag": "direct"}
+            )
+        if routing.mode == RoutingMode.CUSTOM and routing.ru_direct:
+            ru_direct_domains, ru_direct_ips = _parse_list(
+                routing, [*RU_DIRECT_GEOSITES, RU_DIRECT_GEOIP], catalog, "готовые правила"
+            )
+            if ru_direct_ips:
+                route_rules.append({"type": "field", "ip": ru_direct_ips, "outboundTag": "direct"})
+            if ru_direct_domains:
+                route_rules.append(
+                    {"type": "field", "domain": ru_direct_domains, "outboundTag": "direct"}
+                )
+
         # Outbounds
         runtime_mode = normalize_proxy_mode(getattr(context.config, "proxy_mode", None))
         tun_name = getattr(context.config, "tun_name", "xray0")
@@ -349,7 +358,10 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
         dns = build_dns(
             context.config.dns,
             proxy_host=profile.bean.server_address if profile.bean else "",
-            domain_groups=[(group, domains_by_group[group]) for group in rule_order],
+            domain_groups=[
+                *((group, domains_by_group[group]) for group in rule_order),
+                ("direct", ru_direct_domains),
+            ],
             blocked_domains=block_domains,
             vpn_active=vpn_active,
             vpn_dns_servers=vpn_dns_servers,
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_dns_config.py tests/test_core_routing_rules.py -q`
Expected: `42 passed`. Полный набор — зелёный: значение по умолчанию
сменилось, но сохранённые настройки хранят своё значение явно.

**Step 5: Commit**

```bash
git add src/core/config_builder.py \
        src/core/geo.py \
        src/db/config.py \
        tests/test_core_dns_config.py \
        tests/test_core_routing_rules.py
git commit -m "feat(core): готовые правила — локальные сети и российские сайты напрямую"
```

---

### Task 8: Перехват DNS в режиме TUN — конфиг

Правило `{inboundTag: [tun-in], port: 53} → dns-out` первым в списке и outbound
`protocol: dns`. Без этого настройки DNS влияют только на внутренний резолв
ядра, а запросы приложений идут как обычный UDP.

На Linux у перехвата есть цена, которой нет в Android: процесс ядра не исключён
из туннеля. Запрос ядра к «системному резолверу» (`localhost`) сам может
прийти в TUN и быть перехвачен снова — петля. Поэтому при перехвате:

- системный резолвер называется адресами — DNS-серверами сети на физическом
  интерфейсе (`resolvectl dns <интерфейс>`, без resolved — `/etc/resolv.conf`);
- блок `dns` получает тег `dns-internal`, и правило
  `{inboundTag: [dns-internal], ip: <эти адреса>} → direct` отправляет запросы
  к ним через direct, привязанный к интерфейсу (задача 6);
- если адреса или интерфейс определить не удалось — перехвата нет, всё
  работает как в режиме системного прокси.

DNS-модуль отвечает только на A и AAAA. Остальные типы dns-outbound пересылает
первому DNS-серверу сети (решение 10); сам outbound тоже привязан к интерфейсу.

Перехват включён настройкой `DnsSettings.intercept` (по умолчанию `True`).

**Важно:** на системах с systemd-resolved этот конфиг ничего не меняет, пока
системный DNS не направлен в TUN (задача 9). Вреда от него тоже нет.

**Files:**
- Create: `src/sys/resolver.py`
- Modify: `src/db/config.py` (`DnsSettings.intercept`)
- Modify: `src/core/dns_config.py` (`system_resolvers`, `DNS_TAG`)
- Modify: `src/core/config_builder.py`, `src/core/proxy_mode.py` (`TUN_INBOUND_TAG`)
- Modify: `src/core/xray_manager.py` (`_SERVICE_TAGS`)
- Modify: `tests/conftest.py`
- Create: `tests/test_sys_resolver.py`, `tests/test_core_dns_intercept.py`

**Step 1: Написать падающие тесты**

Создать `tests/test_sys_resolver.py`:

```python
"""Какие DNS-серверы использует система на физическом интерфейсе."""

from __future__ import annotations

import subprocess

from src.sys import resolver


def fake_resolvectl(monkeypatch, stdout: str, returncode: int = 0) -> list[list[str]]:
    calls: list[list[str]] = []

    def run(cmd, **_kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(resolver.subprocess, "run", run)
    return calls


def test_link_servers_come_from_systemd_resolved(monkeypatch):
    calls = fake_resolvectl(monkeypatch, "Link 2 (wlp1s0): 192.168.0.1 fe80::1%2 8.8.8.8\n")

    assert resolver.link_dns_servers("wlp1s0") == ["192.168.0.1", "8.8.8.8"]
    assert calls == [["resolvectl", "dns", "wlp1s0"]]


def test_link_without_servers_gives_empty_list(monkeypatch):
    fake_resolvectl(monkeypatch, "Link 5 (docker0):\n")

    assert resolver.link_dns_servers("docker0") == []


def test_missing_resolvectl_gives_empty_list(monkeypatch):
    def run(*_args, **_kwargs):
        raise FileNotFoundError("resolvectl")

    monkeypatch.setattr(resolver.subprocess, "run", run)

    assert resolver.link_dns_servers("eth0") == []


def test_resolv_conf_servers_skip_loopback_stub(tmp_path):
    """`127.0.0.53` — заглушка systemd-resolved, а не настоящий сервер."""
    path = tmp_path / "resolv.conf"
    path.write_text("# comment\nnameserver 127.0.0.53\nnameserver 77.88.8.8\nnameserver ::1\n")

    assert resolver.resolv_conf_servers(path) == ["77.88.8.8"]


def test_system_servers_prefer_the_link_and_fall_back_to_resolv_conf(monkeypatch, tmp_path):
    path = tmp_path / "resolv.conf"
    path.write_text("nameserver 77.88.8.8\n")
    monkeypatch.setattr(resolver, "RESOLV_CONF", path)

    fake_resolvectl(monkeypatch, "Link 2 (eth0): 192.168.0.1\n")
    assert resolver.system_dns_servers("eth0") == ["192.168.0.1"]

    fake_resolvectl(monkeypatch, "", returncode=1)
    assert resolver.system_dns_servers("eth0") == ["77.88.8.8"]
```

Создать `tests/test_core_dns_intercept.py`:

```python
"""Перехват DNS-запросов приложений в режиме TUN.

Без него настройки DNS действуют только на внутренний резолв ядра, а запросы
приложений идут мимо: split-DNS и блок-лист на них не влияют.
"""

from __future__ import annotations

import shutil

import pytest

from src.core import config_builder
from src.core.config_builder import build_session_config
from src.db.config import DnsProvider, ProxyMode, VpnSettings
from tests.support.session import (
    XRAY,
    make_context,
    make_profile,
    use_bundled_geo,
    use_custom_lists,
    with_socks_inbound,
    xray_verdict,
)

needs_xray = pytest.mark.skipif(
    not XRAY.exists() or not shutil.which(str(XRAY)),
    reason="бинарник xray недоступен (core/bin/xray)",
)

DOH = "https://dns.google/dns-query"
INTERCEPT_RULE = {
    "type": "field",
    "inboundTag": ["tun-in"],
    "port": "53",
    "outboundTag": "dns-out",
}


@pytest.fixture(autouse=True)
def geo(monkeypatch):
    use_bundled_geo(monkeypatch)


@pytest.fixture
def context(tmp_path):
    context = make_context(tmp_path)
    context.config.proxy_mode = ProxyMode.TUN
    return context


@pytest.fixture
def profile(context):
    return make_profile(context)


@pytest.fixture
def system(monkeypatch):
    """Система с интерфейсом eth0 и резолвером 192.168.0.1 на нём."""
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: "eth0")
    monkeypatch.setattr(config_builder, "system_dns_servers", lambda _iface: ["192.168.0.1"])


def outbound_tags(config: dict) -> set[str]:
    return {o.get("tag") for o in config["outbounds"]}


def test_dns_queries_from_tun_are_handed_to_the_dns_module(context, profile, system):
    config = build_session_config(context, profile)

    # Первым: иначе адрес DNS-сервера совпал бы с каким-нибудь IP-правилом раньше.
    assert config["routing"]["rules"][0] == INTERCEPT_RULE
    assert {
        "protocol": "dns",
        "tag": "dns-out",
        "settings": {
            # A и AAAA отвечает DNS-модуль ядра; остальные типы (TXT, MX, SRV…) он
            # не умеет — их пересылаем системному резолверу, как было до перехвата.
            "rewriteAddress": "192.168.0.1",
            "rewritePort": 53,
            "rules": [{"action": "hijack", "qType": "1,28"}, {"action": "direct"}],
        },
        "streamSettings": {"sockopt": {"interface": "eth0"}},
    } in config["outbounds"]


def test_system_resolver_is_addressed_explicitly(context, profile, system):
    """`localhost` при перехвате дал бы петлю: запрос ядра вернулся бы в TUN.

    Поэтому системный резолвер пишется адресом, а его запросы отдельным
    правилом уходят в direct, привязанный к физическому интерфейсу.
    """
    use_custom_lists(context, direct=["direct.example"])

    config = build_session_config(context, profile)

    assert config["dns"]["tag"] == "dns-internal"
    assert config["dns"]["servers"] == [
        {
            "address": "192.168.0.1",
            "port": 53,
            "domains": ["full:proxy.example.org"],
            "skipFallback": True,
        },
        {
            "address": "192.168.0.1",
            "port": 53,
            "domains": ["domain:direct.example"],
            "skipFallback": True,
        },
        {"address": DOH},
    ]
    assert config["routing"]["rules"][1] == {
        "type": "field",
        "inboundTag": ["dns-internal"],
        "ip": ["192.168.0.1"],
        "port": "53",
        "outboundTag": "direct",
    }


def test_system_dns_provider_uses_the_explicit_resolver_too(context, profile, system):
    context.config.dns.provider = DnsProvider.SYSTEM

    servers = build_session_config(context, profile)["dns"]["servers"]

    assert "localhost" not in str(servers)
    assert servers[-1] == {"address": "192.168.0.1", "port": 53}


def test_block_list_comes_right_after_the_dns_rules(context, profile, system):
    use_custom_lists(context, block=["ads.example"])

    rules = build_session_config(context, profile)["routing"]["rules"]

    assert [r["outboundTag"] for r in rules[:3]] == ["dns-out", "direct", "block"]


def test_no_interception_in_system_proxy_mode(context, profile, system):
    context.config.proxy_mode = ProxyMode.SYSTEM_PROXY

    config = build_session_config(context, profile)

    assert "dns-out" not in outbound_tags(config)
    assert "tag" not in config["dns"]
    assert "localhost" in str(config["dns"]["servers"])


def test_interception_can_be_switched_off(context, profile, system):
    context.config.dns.intercept = False

    config = build_session_config(context, profile)

    assert "dns-out" not in outbound_tags(config)
    assert INTERCEPT_RULE not in config["routing"]["rules"]


def test_no_interception_without_known_system_resolver(context, profile, monkeypatch):
    """Не знаем, куда слать прямые запросы, — оставляем `localhost` и не перехватываем."""
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: "eth0")
    monkeypatch.setattr(config_builder, "system_dns_servers", lambda _iface: [])

    config = build_session_config(context, profile)

    assert "dns-out" not in outbound_tags(config)
    assert "localhost" in str(config["dns"]["servers"])


def test_no_interception_without_physical_interface(context, profile, monkeypatch):
    """Без привязки к интерфейсу прямой запрос к резолверу мог бы вернуться в TUN."""
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: None)
    monkeypatch.setattr(config_builder, "system_dns_servers", lambda _iface: ["192.168.0.1"])

    config = build_session_config(context, profile)

    assert "dns-out" not in outbound_tags(config)


def test_interception_with_active_vpn_keeps_vpn_dns(context, profile, system, monkeypatch):
    """Режим «VPN поверх»: домены VPN-списка по-прежнему резолвит DNS-сервер VPN."""
    profile.vpn_settings = VpnSettings(enabled=True, connection_name="corp")
    monkeypatch.setattr(config_builder, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(config_builder, "get_vpn_interface", lambda _name: "tun0")
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: ["10.222.0.7"])
    use_custom_lists(context, vpn=["corp.example", "10.222.0.0/16"])

    config = build_session_config(context, profile)

    assert config["routing"]["rules"][0] == INTERCEPT_RULE
    assert {
        "address": "10.222.0.7",
        "port": 53,
        "domains": ["domain:corp.example"],
        "skipFallback": True,
    } in config["dns"]["servers"]
    # DoH при активном VPN заменяется системным резолвером — здесь его адресом.
    assert config["dns"]["servers"][-1] == {"address": "192.168.0.1", "port": 53}
    assert "vpn" in outbound_tags(config)


def test_dns_outbound_traffic_is_not_counted_as_proxy_traffic():
    from src.core.xray_manager import XrayManager

    assert "dns-out" in XrayManager._SERVICE_TAGS


@needs_xray
def test_core_accepts_interception_config(context, profile, system, tmp_path):
    """Правило с `inboundTag: tun-in` проверяем на SOCKS-входе с тем же тегом."""
    use_custom_lists(
        context,
        direct=["direct.example", "geosite:category-ru"],
        proxy=["blocked.example"],
        block=["ads.example"],
    )
    context.config.routing.ru_direct = True

    config = build_session_config(context, profile)

    assert config["inbounds"][0]["protocol"] == "tun"
    assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_dns_intercept.py tests/test_sys_resolver.py -q`
Expected: `1 error` — `ImportError: cannot import name 'resolver' from 'src.sys'`.

**Step 3: Определение DNS-серверов сети**

Создать `src/sys/resolver.py`:

```python
"""DNS-серверы, которыми система пользуется на физическом интерфейсе.

Нужны при перехвате DNS в режиме TUN: ядро не может спрашивать «системный
резолвер» (`localhost`) — его запрос вернулся бы в TUN и был бы перехвачен
снова. Поэтому настоящие серверы сети называются адресами.
"""

from __future__ import annotations

import ipaddress
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("tenga.sys.resolver")

RESOLV_CONF = Path("/etc/resolv.conf")


def _usable_ipv4(value: str) -> str | None:
    """IPv4-адрес настоящего сервера; loopback — заглушка локального резолвера."""
    try:
        address = ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return None
    if address.version != 4 or address.is_loopback:
        return None
    return str(address)


def link_dns_servers(interface: str) -> list[str]:
    """Серверы интерфейса по данным systemd-resolved (`resolvectl dns <iface>`)."""
    try:
        result = subprocess.run(
            ["resolvectl", "dns", interface],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []

    # Строка вида «Link 2 (wlp1s0): 192.168.0.1 fe80::1%2».
    _, _, tail = result.stdout.partition("):")
    servers = [_usable_ipv4(token) for token in tail.split()]
    return [server for server in servers if server]


def resolv_conf_servers(path: Path | None = None) -> list[str]:
    """Серверы из resolv.conf, кроме локальных заглушек."""
    try:
        lines = (path or RESOLV_CONF).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    servers = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[0] == "nameserver":
            server = _usable_ipv4(parts[1])
            if server:
                servers.append(server)
    return servers


def system_dns_servers(interface: str) -> list[str]:
    """Настоящие DNS-серверы сети: интерфейса, а без systemd-resolved — из resolv.conf."""
    return link_dns_servers(interface) or resolv_conf_servers()
```

Сборщик начнёт вызывать `system_dns_servers` — в тестах она, как и определение
интерфейса, по умолчанию отвечает «неизвестно»:

Изменить `tests/conftest.py`:

```diff
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -13,12 +13,13 @@ import pytest
 def _no_system_probing(monkeypatch) -> None:
     """Сборка конфига не должна зависеть от сети машины, на которой идут тесты.
 
-    В режиме TUN сборщик спрашивает у системы физический интерфейс. Тест,
-    которому это нужно, подменяет функцию сам.
+    В режиме TUN сборщик спрашивает у системы физический интерфейс и её
+    DNS-серверы. Тест, которому это нужно, подменяет функции сам.
     """
     from src.core import config_builder
 
     monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: None)
+    monkeypatch.setattr(config_builder, "system_dns_servers", lambda _interface: [])
 
 
 @pytest.fixture(scope="session")
```

**Step 4: Настройка и блок DNS**

Изменить `src/db/config.py`:

```diff
--- a/src/db/config.py
+++ b/src/db/config.py
@@ -259,6 +259,9 @@ class DnsSettings(ConfigBase):
     custom_url: str = ""
     # DNS via proxy
     use_proxy: bool = True
+    # В режиме TUN отдавать DNS-запросы приложений DNS-модулю ядра: без этого
+    # split-DNS и блок-лист действуют только на внутренний резолв.
+    intercept: bool = True
 
     def get_dns_url(self) -> str:
         """Get DNS server URL."""
```

Изменить `src/core/dns_config.py`:

```diff
--- a/src/core/dns_config.py
+++ b/src/core/dns_config.py
@@ -30,6 +30,8 @@ logger = logging.getLogger("tenga.core.dns_config")
 
 # Системный резолвер процесса ядра.
 LOCALHOST = "localhost"
+# Тег, которым помечены собственные запросы DNS-модуля в маршрутизации.
+DNS_TAG = "dns-internal"
 # Значение `hosts`: ответить кодом 3 (NXDOMAIN). Адрес-заглушка вроде 127.0.0.1
 # не годится — он попадает под «локальные сети напрямую».
 NXDOMAIN = "#3"
@@ -89,11 +91,26 @@ def _main_server(dns_url: str, *, through_proxy: bool) -> DnsServer | None:
     return _server(dns_url.replace("udp://", "").replace("tcp://", ""), port=53)
 
 
-def _vpn_server(vpn_dns_servers: list[str], vpn_domains: list[str]) -> DnsServer:
-    """Сервер для доменов из списка «через VPN»."""
+def _system_servers(
+    system_resolvers: Sequence[str], domains: list[str] | None = None
+) -> list[DnsServer]:
+    """Системный резолвер: `localhost` либо — при перехвате DNS — серверы сети адресами.
+
+    При перехвате `localhost` дал бы петлю: запрос ядра к системному резолверу
+    вернулся бы в TUN и был бы перехвачен снова.
+    """
+    if not system_resolvers:
+        return [_server(LOCALHOST, domains=domains)]
+    return [_server(address, port=53, domains=domains) for address in system_resolvers]
+
+
+def _vpn_servers(
+    vpn_dns_servers: list[str], vpn_domains: list[str], system_resolvers: Sequence[str]
+) -> list[DnsServer]:
+    """Серверы для доменов из списка «через VPN»."""
     if not vpn_dns_servers:
         logger.warning("У VPN-подключения нет DNS-серверов: его домены резолвит системный")
-        return _server(LOCALHOST, domains=vpn_domains)
+        return _system_servers(system_resolvers, vpn_domains)
 
     endpoint = parse_dns_endpoint(vpn_dns_servers[0])
     if endpoint is None:
@@ -101,7 +118,7 @@ def _vpn_server(vpn_dns_servers: list[str], vpn_domains: list[str]) -> DnsServer
         endpoint = FALLBACK_VPN_DNS
     address, port = endpoint
     logger.info("Домены списка «через VPN» резолвит %s:%d", address, port)
-    return _server(address, port=port, domains=vpn_domains)
+    return [_server(address, port=port, domains=vpn_domains)]
 
 
 def build_dns(
@@ -112,6 +129,7 @@ def build_dns(
     blocked_domains: Sequence[str] = (),
     vpn_active: bool = False,
     vpn_dns_servers: list[str] | None = None,
+    system_resolvers: Sequence[str] = (),
 ) -> dict[str, Any]:
     """Собрать блок `dns`.
 
@@ -123,6 +141,9 @@ def build_dns(
         blocked_domains: доменные правила блок-листа — на них отвечаем NXDOMAIN.
         vpn_active: поднят VPN NetworkManager, привязанный к профилю.
         vpn_dns_servers: DNS-серверы VPN-подключения, как их отдал NetworkManager.
+        system_resolvers: адреса DNS-серверов сети. Заданы при перехвате DNS в
+            режиме TUN — тогда они заменяют `localhost`, а блок получает тег
+            `DNS_TAG`, по которому их запросы направляются в direct.
     """
     dns_url = settings.get_dns_url()
     if vpn_active and dns_url.startswith(("https://", "tls://")):
@@ -141,23 +162,28 @@ def build_dns(
     # Имя сервера профиля резолвит системный резолвер: DNS через прокси ждал бы
     # соединения с прокси, а оно — этого самого ответа.
     if proxy_host and not proxy_host[0].isdigit():
-        servers.append(_server(LOCALHOST, domains=[f"full:{proxy_host}"]))
+        servers.extend(_system_servers(system_resolvers, [f"full:{proxy_host}"]))
 
     for group, domains in domain_groups:
         if not domains:
             continue
         if group == "direct":
-            servers.append(_server(LOCALHOST, domains=domains))
+            servers.extend(_system_servers(system_resolvers, domains))
         elif group == "vpn":
-            servers.append(_vpn_server(vpn_dns_servers or [], domains))
+            servers.extend(_vpn_servers(vpn_dns_servers or [], domains, system_resolvers))
         elif group == "proxy" and main_is_remote:
             # Иначе домен из proxy-списка мог бы совпасть с доменами direct-сервера
             # ниже и отрезолвиться в сети провайдера.
             servers.append({**_as_object(main), "domains": list(domains)})
 
-    servers.append(main)
+    if main_is_remote:
+        servers.append(main)
+    else:
+        servers.extend(_system_servers(system_resolvers))
 
     dns: dict[str, Any] = {"servers": servers}
+    if system_resolvers:
+        dns["tag"] = DNS_TAG
     if blocked_domains:
         dns["hosts"] = {_hosts_key(rule): NXDOMAIN for rule in blocked_domains}
     return dns
```

**Step 5: Правила и outbound**

Изменить `src/core/proxy_mode.py`:

```diff
--- a/src/core/proxy_mode.py
+++ b/src/core/proxy_mode.py
@@ -8,6 +8,8 @@ from src.db.config import ProxyMode
 # из udp:443 — доменные правила маршрутизации для такого трафика молча не работают.
 SNIFFING_DEST_OVERRIDE = ("http", "tls", "quic")
 
+TUN_INBOUND_TAG = "tun-in"
+
 
 def normalize_proxy_mode(mode: str | None) -> str:
     """Normalize runtime proxy mode."""
@@ -32,7 +34,7 @@ def build_inbounds_for_mode(
         mtu = tun_mtu if 576 <= tun_mtu <= 9000 else 1500
         return [
             {
-                "tag": "tun-in",
+                "tag": TUN_INBOUND_TAG,
                 "port": 0,
                 "protocol": "tun",
                 "settings": {
```

Изменить `src/core/config_builder.py`:

```diff
--- a/src/core/config_builder.py
+++ b/src/core/config_builder.py
@@ -13,7 +13,7 @@ import random
 import socket
 
 from src.core.context import AppContext
-from src.core.dns_config import build_dns
+from src.core.dns_config import DNS_TAG, build_dns
 from src.core.geo import (
     RU_DIRECT_GEOIP,
     RU_DIRECT_GEOSITES,
@@ -21,7 +21,7 @@ from src.core.geo import (
     asset_dirs,
     load_catalog,
 )
-from src.core.proxy_mode import build_inbounds_for_mode, normalize_proxy_mode
+from src.core.proxy_mode import TUN_INBOUND_TAG, build_inbounds_for_mode, normalize_proxy_mode
 from src.core.transport_tweaks import apply_transport_tweaks
 from src.db.config import (
     DEFAULT_ROUTING_ORDER,
@@ -32,6 +32,7 @@ from src.db.config import (
     VpnSettings,
 )
 from src.db.profiles import ProfileEntry
+from src.sys.resolver import system_dns_servers
 from src.sys.vpn import (
     get_default_interface,
     get_vpn_dns_servers,
@@ -42,6 +43,7 @@ from src.sys.vpn import (
 logger = logging.getLogger("tenga.core.config_builder")
 
 BLOCK_TAG = "block"
+DNS_OUT_TAG = "dns-out"
 
 
 def _parse_list(
@@ -313,6 +315,44 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
             direct_outbound,
         ]
 
+        # Перехват DNS приложений в режиме TUN. Нужны и физический интерфейс, и
+        # адреса настоящих DNS-серверов сети: `localhost` при перехвате дал бы
+        # петлю, а непривязанный прямой запрос мог бы вернуться в TUN.
+        system_resolvers: list[str] = []
+        if runtime_mode == ProxyMode.TUN and context.config.dns.intercept and physical_interface:
+            system_resolvers = system_dns_servers(physical_interface)
+            if not system_resolvers:
+                logger.warning("DNS-серверы сети не определены: DNS приложений не перехватывается")
+        if system_resolvers:
+            route_rules[:0] = [
+                {
+                    "type": "field",
+                    "inboundTag": [TUN_INBOUND_TAG],
+                    "port": "53",
+                    "outboundTag": DNS_OUT_TAG,
+                },
+                {
+                    "type": "field",
+                    "inboundTag": [DNS_TAG],
+                    "ip": system_resolvers,
+                    "port": "53",
+                    "outboundTag": "direct",
+                },
+            ]
+            dns_outbound = {
+                "protocol": "dns",
+                "tag": DNS_OUT_TAG,
+                "settings": {
+                    # A и AAAA отвечает DNS-модуль; остальные типы запросов он не
+                    # умеет — пересылаем их серверу сети, как было до перехвата.
+                    "rewriteAddress": system_resolvers[0],
+                    "rewritePort": 53,
+                    "rules": [{"action": "hijack", "qType": "1,28"}, {"action": "direct"}],
+                },
+            }
+            _bind_to_interface(dns_outbound, physical_interface)
+            outbounds.append(dns_outbound)
+
         if vpn_tag and vpn_interface:
             vpn_outbound = {
                 "protocol": "freedom",
@@ -365,6 +405,7 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
             blocked_domains=block_domains,
             vpn_active=vpn_active,
             vpn_dns_servers=vpn_dns_servers,
+            system_resolvers=system_resolvers,
         )
 
         inbounds = build_inbounds_for_mode(
```

Изменить `src/core/xray_manager.py`:

```diff
--- a/src/core/xray_manager.py
+++ b/src/core/xray_manager.py
@@ -43,10 +43,12 @@ class XrayManager:
     """
 
     # Служебные каналы в счёт трафика не идут: direct — мимо прокси, vpn —
-    # через туннель, block — в никуда, api — сам опрос статистики, остальные три —
-    # резолвинг DNS.
+    # через туннель, block — в никуда, dns-out — перехваченные DNS-запросы, api —
+    # сам опрос статистики, остальные три — резолвинг DNS.
     # Список отражает теги, которые заводит `src/core/config_builder.py`.
-    _SERVICE_TAGS = frozenset({"direct", "vpn", "block", "api", "main-dns", "local-dns", "vpn-dns"})
+    _SERVICE_TAGS = frozenset(
+        {"direct", "vpn", "block", "dns-out", "api", "main-dns", "local-dns", "vpn-dns"}
+    )
 
     def __init__(
         self,
```

**Step 6: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_dns_intercept.py tests/test_sys_resolver.py -q`
Expected: `16 passed`. Полный набор — зелёный.

**Step 7: Commit**

```bash
git add src/core/config_builder.py \
        src/core/dns_config.py \
        src/core/proxy_mode.py \
        src/core/xray_manager.py \
        src/db/config.py \
        src/sys/resolver.py \
        tests/conftest.py \
        tests/test_core_dns_intercept.py \
        tests/test_sys_resolver.py
git commit -m "feat(core): перехватывать DNS приложений в режиме TUN"
```

---

### Task 9: Системный DNS — в TUN (systemd-resolved)

Задача 8 перехватывает запросы, дошедшие до TUN. На системах с
systemd-resolved они туда не доходят («Что проверено», п. 6). Здесь TUN-интерфейсу
назначается адрес (поле `gateway` у TUN-inbound, ядро 26.9.9), а resolved
получает для него DNS-сервер и домен `~.` — после этого все запросы резолвера
уходят через TUN и попадают под правило перехвата. Отменять нечего: настройки
привязаны к интерфейсу и исчезают вместе с ним.

Менять DNS интерфейса можно только с правами, поэтому это делает установленный
помощник `tun-route-helper` (новое действие `dns`). Адрес сервера в нём зашит:
помощник запускается от root без пароля и не должен принимать произвольный DNS.
Отказ не фатален — подключение работает, DNS идёт как раньше.

**Это единственная задача плана, поведение которой нельзя проверить без живого
TUN и прав. Шаг 1 — эксперимент; по его итогу задача либо выполняется, либо
вычёркивается.** Остальные задачи от неё не зависят.

**Files:**
- Create: `src/sys/tun_dns.py`
- Modify: `core/scripts/tun_route_helper.sh` (действие `dns`)
- Modify: `src/core/proxy_mode.py` (`TUN_ADDRESS`, параметр `tun_address`)
- Modify: `src/core/config_builder.py` (`intercepts_dns`), `src/core/connection.py`
- Modify: `tests/conftest.py` — подключение в тестах не трогает DNS машины
- Create: `tests/test_sys_tun_dns.py`, `tests/test_core_connection_dns.py`
- Test: `tests/test_core_dns_intercept.py`

**Step 1: Эксперимент на живой системе (вручную, до кода)**

Нужны: система с systemd-resolved, приложение, подключённое в режиме TUN
(интерфейс `xray0`), журнал ядра на уровне `debug`, права root. Собрать
приложение нужно из ветки с задачей 8, иначе в конфиге нет правила перехвата.

```bash
resolvectl status xray0                    # до: Current Scopes: none
sudo ip addr add 198.18.0.1/30 dev xray0
sudo resolvectl dns xray0 1.1.1.1
sudo resolvectl domain xray0 '~.'
resolvectl status xray0                    # ожидаем: Current Scopes: DNS, DNS Domain: ~.
resolvectl query example.com               # ожидаем: ответ и «-- link: xray0»
dig +short TXT example.com                 # ожидаем: непустой ответ (пересылка не-A/AAAA)
grep "tun-in -> dns-out" ~/.config/tenga-proxy/logs/xray.log | tail -3
```

Откат (или просто отключиться — интерфейс исчезнет вместе с настройками):

```bash
sudo resolvectl revert xray0
sudo ip addr del 198.18.0.1/30 dev xray0
```

Что должно получиться: `Current Scopes: DNS`; запрос помечен `link: xray0`; в
журнале ядра есть `[tun-in -> dns-out]`; сайты открываются; после отключения
`resolvectl status` показывает прежние настройки.

Если `Current Scopes` остаётся `none` или запросы в журнале ядра не появляются
— **задачу не выполнять**: записать наблюдение в дорожную карту (этап 3, D1) и
перейти к задаче 10. Если не хватило только адреса — попробовать другой
(`169.254.10.1/30`) и поправить `TUN_ADDRESS` ниже.

**Step 2: Написать падающие тесты**

Создать `tests/test_sys_tun_dns.py`:

```python
"""Направление системного DNS в TUN через systemd-resolved."""

from __future__ import annotations

from src.sys import tun_dns


def test_installed_helper_is_preferred(monkeypatch):
    calls: list[tuple] = []

    def helper(action, args, timeout=15):
        calls.append((action, args))
        return True, ""

    monkeypatch.setattr(tun_dns, "_run_helper", helper)
    monkeypatch.setattr(tun_dns.shutil, "which", lambda _name: "/usr/bin/resolvectl")

    assert tun_dns.route_system_dns_to_tun("xray0") == (True, "")
    assert calls == [("dns", ["xray0"])]


def test_without_helper_resolvectl_is_called_without_prompting(monkeypatch):
    """Старый helper действия `dns` не знает — пробуем сами, но пароль не спрашиваем."""
    commands: list[list[str]] = []

    def run(cmd, timeout=10):
        commands.append(cmd)
        return True, "", ""

    monkeypatch.setattr(tun_dns, "_run_helper", lambda *_a, **_k: (False, "unknown action"))
    monkeypatch.setattr(tun_dns, "_run_command", run)
    monkeypatch.setattr(tun_dns.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert tun_dns.route_system_dns_to_tun("xray0") == (True, "")
    assert commands == [
        ["resolvectl", "--no-ask-password", "dns", "xray0", tun_dns.TUN_DNS_ADDRESS],
        ["resolvectl", "--no-ask-password", "domain", "xray0", "~."],
    ]


def test_sudo_is_the_last_resort(monkeypatch):
    commands: list[list[str]] = []

    def run(cmd, timeout=10):
        commands.append(cmd)
        return cmd[0] == "sudo", "", "" if cmd[0] == "sudo" else "access denied"

    monkeypatch.setattr(tun_dns, "_run_helper", lambda *_a, **_k: (False, "helper not installed"))
    monkeypatch.setattr(tun_dns, "_run_command", run)
    monkeypatch.setattr(tun_dns.shutil, "which", lambda name: f"/usr/bin/{name}")

    assert tun_dns.route_system_dns_to_tun("xray0") == (True, "")
    assert commands[-1] == ["sudo", "-n", "resolvectl", "domain", "xray0", "~."]


def test_failure_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(tun_dns, "_run_helper", lambda *_a, **_k: (False, "helper not installed"))
    monkeypatch.setattr(tun_dns, "_run_command", lambda *_a, **_k: (False, "", "denied"))
    monkeypatch.setattr(tun_dns.shutil, "which", lambda name: f"/usr/bin/{name}")

    ok, error = tun_dns.route_system_dns_to_tun("xray0")

    assert not ok
    assert "denied" in error


def test_system_without_systemd_resolved_is_left_alone(monkeypatch):
    called: list[str] = []
    monkeypatch.setattr(tun_dns, "_run_helper", lambda *_a, **_k: called.append("helper"))
    monkeypatch.setattr(tun_dns.shutil, "which", lambda _name: None)

    ok, error = tun_dns.route_system_dns_to_tun("xray0")

    assert not ok
    assert "resolvectl" in error
    assert called == []
```

Создать `tests/test_core_connection_dns.py`:

```python
"""Подключение в режиме TUN направляет системный DNS в туннель."""

from __future__ import annotations

import pytest

from src.core.connection import ConnectionService
from tests.test_core_connection import FakeProfile, make_context

INTERCEPTING = {"outbounds": [{"tag": "proxy"}, {"tag": "dns-out", "protocol": "dns"}]}
PLAIN = {"outbounds": [{"tag": "proxy"}]}


@pytest.fixture
def steering(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr("src.core.connection.apply_tun_routes", lambda *_: (True, object(), ""))
    monkeypatch.setattr(
        "src.core.connection.route_system_dns_to_tun",
        lambda tun_name: calls.append(tun_name) or (True, ""),
    )
    return calls


def connect(tmp_path, monkeypatch, config, mode="tun"):
    context = make_context(tmp_path, FakeProfile())
    context.config.proxy_mode = mode
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: config)
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    return ConnectionService(context).connect(1)


def test_system_dns_is_routed_into_the_tunnel(tmp_path, monkeypatch, steering):
    assert connect(tmp_path, monkeypatch, INTERCEPTING).ok
    assert steering == ["xray0"]


def test_config_without_interception_leaves_system_dns_alone(tmp_path, monkeypatch, steering):
    assert connect(tmp_path, monkeypatch, PLAIN).ok
    assert steering == []


def test_system_proxy_mode_leaves_system_dns_alone(tmp_path, monkeypatch, steering):
    assert connect(tmp_path, monkeypatch, INTERCEPTING, mode="system_proxy").ok
    assert steering == []


def test_failed_steering_does_not_fail_the_connection(tmp_path, monkeypatch):
    """Без него DNS идёт как раньше, мимо туннеля: хуже, но подключение работает."""
    monkeypatch.setattr("src.core.connection.apply_tun_routes", lambda *_: (True, object(), ""))
    monkeypatch.setattr(
        "src.core.connection.route_system_dns_to_tun", lambda _tun: (False, "access denied")
    )

    assert connect(tmp_path, monkeypatch, INTERCEPTING).ok
```

Изменить `tests/test_core_dns_intercept.py`:

```diff
--- a/tests/test_core_dns_intercept.py
+++ b/tests/test_core_dns_intercept.py
@@ -219,3 +219,16 @@ def test_core_accepts_interception_config(context, profile, system, tmp_path):
 
     assert config["inbounds"][0]["protocol"] == "tun"
     assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)
+
+
+def test_tun_gets_an_address_when_dns_is_intercepted(context, profile, system):
+    """systemd-resolved не шлёт запросы через интерфейс без маршрутизируемого адреса."""
+    config = build_session_config(context, profile)
+
+    assert config["inbounds"][0]["settings"]["gateway"] == ["198.18.0.1/30"]
+
+
+def test_tun_has_no_address_without_interception(context, profile):
+    config = build_session_config(context, profile)
+
+    assert "gateway" not in config["inbounds"][0]["settings"]
```

**Step 3: Убедиться, что падают**

Run: `uv run pytest tests/test_core_connection_dns.py tests/test_core_dns_intercept.py tests/test_sys_tun_dns.py -q`
Expected: `1 error` — `ImportError: cannot import name 'tun_dns' from 'src.sys'`.

**Step 4: Помощник**

Изменить `core/scripts/tun_route_helper.sh`:

```diff
--- a/core/scripts/tun_route_helper.sh
+++ b/core/scripts/tun_route_helper.sh
@@ -5,6 +5,7 @@ set -eu
 # Usage:
 #   tun-route-helper apply <tun_name> <proxy_ip> <gateway|- > <dev> <metric|->
 #   tun-route-helper restore <proxy_ip> <gateway|- > <dev> <metric|->
+#   tun-route-helper dns <tun_name>
 
 die() {
   echo "tun-route-helper: $*" >&2
@@ -86,6 +87,20 @@ case "$action" in
     ip route del "$proxy_ip/32" >/dev/null 2>&1 || true
     ;;
 
+  dns)
+    # Направить системный DNS (systemd-resolved) в TUN. Адрес сервера зашит:
+    # helper запускается от root без пароля и не должен принимать чужой DNS.
+    # Отмена не нужна: настройки исчезают вместе с интерфейсом.
+    [ $# -eq 1 ] || die "dns requires 1 arg"
+    tun_name="$1"
+
+    is_ifname "$tun_name" || die "invalid tun_name"
+    command -v resolvectl >/dev/null 2>&1 || die "resolvectl not found"
+
+    resolvectl dns "$tun_name" 1.1.1.1
+    resolvectl domain "$tun_name" "~."
+    ;;
+
   *)
     die "unknown action: $action"
     ;;
```

Run: `sh -n core/scripts/tun_route_helper.sh`
Expected: без вывода.

**Step 5: Модуль**

Создать `src/sys/tun_dns.py`:

```python
"""Направление системного DNS в TUN.

На системах с systemd-resolved приложения спрашивают заглушку `127.0.0.53`, а
она — DNS-сервер физического интерфейса, причём мимо таблицы маршрутов. До TUN
такие запросы не доходят, и правило перехвата в конфиге ядра остаётся без дела.
Здесь TUN-интерфейсу назначается DNS-сервер и домен `~.`: резолвер начинает
слать все запросы через него.

Отменять ничего не нужно: настройки привязаны к интерфейсу и исчезают вместе с
ним, когда ядро останавливается.
"""

from __future__ import annotations

import logging
import shutil

from src.sys.tun_route import _run_command, _run_helper

logger = logging.getLogger("tenga.sys.tun_dns")

# Адрес, который объявляется DNS-сервером TUN-интерфейса. Запрос к нему
# перехватывает правило `tun-in:53 → dns-out`, до самого адреса он не доходит.
# Публичный адрес выбран на случай, если перехват не сработает: тогда запрос
# уйдёт через прокси и всё равно получит ответ.
TUN_DNS_ADDRESS = "1.1.1.1"
# «Все домены»: с ним интерфейс выигрывает у DNS физического интерфейса.
ALL_DOMAINS = "~."


def route_system_dns_to_tun(tun_name: str) -> tuple[bool, str]:
    """Попросить systemd-resolved слать запросы через TUN-интерфейс.

    Returns:
        (успех, причина отказа). Отказ не фатален: DNS идёт как раньше, мимо туннеля.
    """
    if not shutil.which("resolvectl"):
        return False, "resolvectl не найден: система без systemd-resolved"

    ok, error = _run_helper("dns", [tun_name])
    if ok:
        logger.info("Системный DNS направлен в %s", tun_name)
        return True, ""

    commands = [
        ["dns", tun_name, TUN_DNS_ADDRESS],
        ["domain", tun_name, ALL_DOMAINS],
    ]
    # Старый helper действия `dns` не знает. Пробуем сами: сначала без прав (вдруг
    # разрешено политикой), затем через sudo — оба раза без запроса пароля.
    prefixes = [["resolvectl", "--no-ask-password"]]
    if shutil.which("sudo"):
        prefixes.append(["sudo", "-n", "resolvectl"])

    for prefix in prefixes:
        for args in commands:
            ok, _out, command_error = _run_command([*prefix, *args])
            if not ok:
                error = command_error or error
                break
        else:
            logger.info("Системный DNS направлен в %s", tun_name)
            return True, ""

    return False, error or "не удалось настроить systemd-resolved"
```

**Step 6: Адрес TUN-интерфейса и вызов при подключении**

Изменить `src/core/proxy_mode.py`:

```diff
--- a/src/core/proxy_mode.py
+++ b/src/core/proxy_mode.py
@@ -9,6 +9,10 @@ from src.db.config import ProxyMode
 SNIFFING_DEST_OVERRIDE = ("http", "tls", "quic")
 
 TUN_INBOUND_TAG = "tun-in"
+# Адрес TUN-интерфейса. Нужен только systemd-resolved: через интерфейс без
+# маршрутизируемого адреса он запросы не шлёт. Диапазон 198.18.0.0/15 отведён
+# под стенды и в настоящих сетях не встречается.
+TUN_ADDRESS = "198.18.0.1/30"
 
 
 def normalize_proxy_mode(mode: str | None) -> str:
@@ -25,24 +29,31 @@ def build_inbounds_for_mode(
     socks_port: int,
     tun_name: str,
     tun_mtu: int,
+    tun_address: str | None = None,
 ) -> list[dict[str, Any]]:
-    """Build xray inbounds according to selected runtime mode."""
+    """Build xray inbounds according to selected runtime mode.
+
+    `tun_address` — адрес, который ядро назначит TUN-интерфейсу (поле `gateway`).
+    """
     normalized_mode = normalize_proxy_mode(mode)
 
     if normalized_mode == ProxyMode.TUN:
         tun_ifname = (tun_name or "").strip() or "xray0"
         mtu = tun_mtu if 576 <= tun_mtu <= 9000 else 1500
+        settings: dict[str, Any] = {
+            "name": tun_ifname,
+            "MTU": mtu,
+            "autoRoute": True,
+            "strictRoute": True,
+        }
+        if tun_address:
+            settings["gateway"] = [tun_address]
         return [
             {
                 "tag": TUN_INBOUND_TAG,
                 "port": 0,
                 "protocol": "tun",
-                "settings": {
-                    "name": tun_ifname,
-                    "MTU": mtu,
-                    "autoRoute": True,
-                    "strictRoute": True,
-                },
+                "settings": settings,
                 "sniffing": {
                     "enabled": True,
                     "destOverride": list(SNIFFING_DEST_OVERRIDE),
```

Изменить `src/core/config_builder.py`:

```diff
--- a/src/core/config_builder.py
+++ b/src/core/config_builder.py
@@ -21,7 +21,12 @@ from src.core.geo import (
     asset_dirs,
     load_catalog,
 )
-from src.core.proxy_mode import TUN_INBOUND_TAG, build_inbounds_for_mode, normalize_proxy_mode
+from src.core.proxy_mode import (
+    TUN_ADDRESS,
+    TUN_INBOUND_TAG,
+    build_inbounds_for_mode,
+    normalize_proxy_mode,
+)
 from src.core.transport_tweaks import apply_transport_tweaks
 from src.db.config import (
     DEFAULT_ROUTING_ORDER,
@@ -414,6 +419,7 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
             socks_port=port,
             tun_name=getattr(context.config, "tun_name", "xray0"),
             tun_mtu=getattr(context.config, "tun_mtu", 1500),
+            tun_address=TUN_ADDRESS if system_resolvers else None,
         )
 
         config = {
@@ -441,6 +447,11 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
         return None
 
 
+def intercepts_dns(config: dict) -> bool:
+    """Собран ли конфиг с перехватом DNS приложений (режим TUN)."""
+    return any(outbound.get("tag") == DNS_OUT_TAG for outbound in config.get("outbounds", []))
+
+
 def reserve_latency_port_pair(host: str) -> int:
     """
     Reserve a free consecutive TCP port pair (socks, http=socks+1).
```

Изменить `src/core/connection.py`:

```diff
--- a/src/core/connection.py
+++ b/src/core/connection.py
@@ -13,10 +13,11 @@ import logging
 from dataclasses import dataclass
 from typing import TYPE_CHECKING
 
-from src.core.config_builder import build_session_config
+from src.core.config_builder import build_session_config, intercepts_dns
 from src.core.proxy_mode import normalize_proxy_mode, should_manage_system_proxy
 from src.db.config import ProxyMode
 from src.sys.proxy import clear_system_proxy, set_system_proxy
+from src.sys.tun_dns import route_system_dns_to_tun
 from src.sys.tun_route import apply_tun_routes, restore_tun_routes
 from src.sys.vpn import connect_vpn, disconnect_vpn, is_vpn_active
 
@@ -87,11 +88,24 @@ class ConnectionService:
         if not routed.ok:
             return routed
 
+        if runtime_mode == ProxyMode.TUN and intercepts_dns(config):
+            self._route_system_dns()
+
         if context.monitor is not None:
             context.monitor.start()
 
         return ConnectionResult(True)
 
+    def _route_system_dns(self) -> None:
+        """Направить системный DNS в TUN, чтобы перехват в конфиге получил запросы.
+
+        Отказ не срывает подключение: DNS пойдёт как раньше, мимо туннеля.
+        """
+        tun_name = getattr(self._context.config, "tun_name", "xray0")
+        ok, error = route_system_dns_to_tun(tun_name)
+        if not ok:
+            logger.warning("Системный DNS не направлен в %s: %s", tun_name, error)
+
     def _reset_vpn_flag(self) -> None:
         try:
             self._context.proxy_state.vpn_auto_connected = False
```

С этого момента подключение в режиме TUN с перехватом обращается к системе —
через установленный помощник или `sudo -n`. На машине разработчика это
изменило бы DNS рабочего интерфейса. Тесты подключения обязаны подменять этот
вызов; страховка на случай, если тест забыл:

Изменить `tests/conftest.py`:

```diff
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -22,6 +22,23 @@ def _no_system_probing(monkeypatch) -> None:
     monkeypatch.setattr(config_builder, "system_dns_servers", lambda _interface: [])
 
 
+@pytest.fixture(autouse=True)
+def _no_system_dns_changes(monkeypatch) -> list[str]:
+    """Подключение в тестах не трогает DNS машины.
+
+    В режиме TUN с перехватом DNS подключение просит systemd-resolved слать
+    запросы через туннель — через установленный помощник или `sudo -n`. На
+    машине разработчика это изменило бы DNS рабочего интерфейса. Тест,
+    которому нужен вызов, подменяет функцию сам; здесь он только записывается.
+    """
+    calls: list[str] = []
+    monkeypatch.setattr(
+        "src.core.connection.route_system_dns_to_tun",
+        lambda tun_name: calls.append(tun_name) or (False, "tests: system DNS is not touched"),
+    )
+    return calls
+
+
 @pytest.fixture(scope="session")
 def gtk_ready() -> None:
     """Skip the test unless GTK4 can talk to a display."""
```

**Step 7: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_connection_dns.py tests/test_core_dns_intercept.py tests/test_sys_tun_dns.py -q`
Expected: `22 passed`. Полный набор — зелёный.

**Step 8: Проверить на живой системе с установленным помощником**

Помощник обновляется установкой: `python cli.py install` (копирует
`tun_route_helper.sh` в `/usr/local/libexec/tenga-proxy/`). Подключиться в
режиме TUN и повторить проверки шага 1 без ручных команд: `resolvectl status
xray0` должен показать `DNS Servers: 1.1.1.1` и `DNS Domain: ~.` сразу после
подключения.

**Step 9: Commit**

```bash
git add core/scripts/tun_route_helper.sh \
        src/core/config_builder.py \
        src/core/connection.py \
        src/core/proxy_mode.py \
        src/sys/tun_dns.py \
        tests/conftest.py \
        tests/test_core_connection_dns.py \
        tests/test_core_dns_intercept.py \
        tests/test_sys_tun_dns.py
git commit -m "feat(sys): направлять системный DNS в TUN через systemd-resolved"
```

---

### Task 10: Проверка готового конфига

Ядро проверяет схему, но не смысл. Конфиг, где весь трафик идёт мимо прокси или
DNS ходит по кругу, оно примет молча. `validate_session_config` проверяет
инварианты после сборки; нарушение — отказ подключения с причиной, которую видит
пользователь.

Что проверяется:

| Инвариант | Почему |
|---|---|
| есть outbound'ы и первый — не `freedom`/`blackhole`/`dns` | первый outbound — выход по умолчанию |
| правило без условий ведёт только в прокси | иначе мимо прокси идёт всё |
| loopback и `geoip:private` — только в direct | иначе локальные запросы уходят в прокси |
| правило ведёт в существующий outbound | опечатку в теге ядро молча заменяет выходом по умолчанию |
| при перехвате DNS: правило перехвата первое, `localhost` среди серверов нет, есть правило для запросов DNS-модуля | иначе петля или запрос мимо DNS-модуля |

Адрес входа не на loopback — предупреждение в журнале, не отказ (решение 11).
Пробные конфиги замера задержки не проверяются: пользовательский трафик через
них не идёт.

Чтобы пользовательский список не приводил к отказу там, где можно обойтись
пропуском, сборщик сам выбрасывает `geoip:private` из списков, кроме
«Напрямую».

**Files:**
- Create: `src/core/config_validator.py`
- Modify: `src/core/config_builder.py` (`UnsafeConfigError`; прежнее тело
  `build_session_config` становится `_build_session_config`)
- Modify: `src/core/connection.py` (`connect`, `reload_config`)
- Create: `tests/test_core_config_validator.py`, `tests/test_core_connection_validation.py`

**Step 1: Написать падающие тесты**

Создать `tests/test_core_config_validator.py`:

```python
"""Проверка готового конфига перед запуском ядра.

Каждое правило ловит ошибку, которую ядро приняло бы молча, а пользователь
получил бы утечку мимо прокси или петлю.
"""

from __future__ import annotations

import copy

import pytest

from src.core import config_builder
from src.core.config_builder import UnsafeConfigError, build_session_config
from src.core.config_validator import exposed_inbounds, validate_session_config
from src.db.config import ProxyMode, VpnSettings
from tests.support.session import make_context, make_profile, use_bundled_geo, use_custom_lists


def valid_config() -> dict:
    return {
        "dns": {"servers": [{"address": "https://dns.google/dns-query"}]},
        "inbounds": [{"listen": "127.0.0.1", "port": 2080, "protocol": "socks"}],
        "outbounds": [
            {"protocol": "vless", "tag": "proxy"},
            {"protocol": "freedom", "tag": "direct"},
        ],
        "routing": {
            "rules": [{"type": "field", "domain": ["domain:a.example"], "outboundTag": "direct"}]
        },
    }


def tun_config() -> dict:
    config = valid_config()
    config["inbounds"] = [{"tag": "tun-in", "port": 0, "protocol": "tun"}]
    config["dns"] = {"tag": "dns-internal", "servers": [{"address": "192.168.0.1", "port": 53}]}
    config["outbounds"].append({"protocol": "dns", "tag": "dns-out"})
    config["routing"]["rules"] = [
        {"type": "field", "inboundTag": ["tun-in"], "port": "53", "outboundTag": "dns-out"},
        {
            "type": "field",
            "inboundTag": ["dns-internal"],
            "ip": ["192.168.0.1"],
            "port": "53",
            "outboundTag": "direct",
        },
    ]
    return config


def test_valid_configs_pass():
    assert validate_session_config(valid_config()) == []
    assert validate_session_config(tun_config()) == []


def test_config_without_outbounds_is_rejected():
    config = valid_config()
    config["outbounds"] = []

    assert validate_session_config(config) == ["в конфиге нет ни одного outbound"]


@pytest.mark.parametrize("protocol", ["freedom", "blackhole", "dns"])
def test_default_outbound_must_be_the_proxy(protocol):
    """Первый outbound — выход по умолчанию: всё несопоставленное ушло бы мимо прокси."""
    config = valid_config()
    config["outbounds"].insert(0, {"protocol": protocol, "tag": "first"})

    (violation,) = validate_session_config(config)

    assert "первый outbound" in violation
    assert protocol in violation


@pytest.mark.parametrize("target", ["direct", "block"])
def test_rule_without_conditions_must_not_bypass_the_proxy(target):
    config = valid_config()
    config["outbounds"].append({"protocol": "blackhole", "tag": "block"})
    config["routing"]["rules"].append(
        {"type": "field", "network": "tcp,udp", "outboundTag": target}
    )

    (violation,) = validate_session_config(config)

    assert "без условий" in violation


def test_rule_without_conditions_may_lead_to_the_proxy():
    config = valid_config()
    config["routing"]["rules"].append(
        {"type": "field", "network": "tcp,udp", "outboundTag": "proxy"}
    )

    assert validate_session_config(config) == []


@pytest.mark.parametrize("network", ["127.0.0.0/8", "::1/128", "geoip:private"])
def test_loopback_must_not_be_sent_to_the_proxy(network):
    config = valid_config()
    config["routing"]["rules"].append({"type": "field", "ip": [network], "outboundTag": "proxy"})

    (violation,) = validate_session_config(config)

    assert network in violation


def test_rule_must_point_to_an_existing_outbound():
    """Опечатку в теге ядро молча заменяет выходом по умолчанию."""
    config = valid_config()
    config["routing"]["rules"].append({"type": "field", "ip": ["1.1.1.1"], "outboundTag": "vpn"})

    (violation,) = validate_session_config(config)

    assert "vpn" in violation


def test_dns_interception_rule_must_be_first():
    """Иначе адрес DNS-сервера совпадёт с IP-правилом раньше и запрос уйдёт мимо DNS-модуля."""
    config = tun_config()
    config["routing"]["rules"].insert(
        0, {"type": "field", "ip": ["8.8.8.8"], "outboundTag": "direct"}
    )

    (violation,) = validate_session_config(config)

    assert "первым" in violation


def test_intercepting_config_must_not_use_localhost_dns():
    """Запрос ядра к системному резолверу вернулся бы в TUN и был бы перехвачен снова."""
    config = tun_config()
    config["dns"]["servers"].append("localhost")

    (violation,) = validate_session_config(config)

    assert "localhost" in violation


def test_intercepting_config_must_route_own_dns_queries_directly():
    config = tun_config()
    del config["routing"]["rules"][1]

    (violation,) = validate_session_config(config)

    assert "dns-internal" in violation


def test_non_loopback_inbound_is_reported_but_allowed():
    """Адрес входящего соединения задаёт пользователь: это предупреждение, не отказ."""
    config = valid_config()
    config["inbounds"].append({"listen": "0.0.0.0", "port": 2081, "protocol": "http"})

    assert validate_session_config(config) == []
    assert exposed_inbounds(config) == ["http 0.0.0.0:2081"]
    assert exposed_inbounds(valid_config()) == []


# --- сборщик и проверка вместе --------------------------------------------


@pytest.fixture
def context(tmp_path, monkeypatch):
    use_bundled_geo(monkeypatch)
    return make_context(tmp_path)


@pytest.fixture
def profile(context):
    return make_profile(context)


@pytest.mark.parametrize("mode", ProxyMode.ALL)
def test_builder_output_passes_validation(context, profile, monkeypatch, mode):
    """Всё, что сборщик умеет, собрано разом: списки, готовые правила, VPN, перехват DNS."""
    monkeypatch.setattr(config_builder, "get_default_interface", lambda *_a, **_k: "eth0")
    monkeypatch.setattr(config_builder, "system_dns_servers", lambda _iface: ["192.168.0.1"])
    monkeypatch.setattr(config_builder, "is_vpn_active", lambda _name: True)
    monkeypatch.setattr(config_builder, "get_vpn_interface", lambda _name: "tun0")
    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: ["10.222.0.7"])
    profile.vpn_settings = VpnSettings(enabled=True, connection_name="corp")
    context.config.proxy_mode = mode
    context.config.routing.ru_direct = True
    use_custom_lists(
        context,
        direct=["direct.example", "192.168.5.0/24"],
        proxy=["blocked.example"],
        vpn=["corp.example", "10.14.0.0/16"],
        block=["ads.example"],
    )

    config = build_session_config(context, profile)

    assert validate_session_config(copy.deepcopy(config)) == []


def test_private_geoip_in_proxy_list_is_dropped_by_the_builder(context, profile):
    """`geoip:private` в прокси увёл бы туда и loopback — запись пропускаем."""
    use_custom_lists(context, proxy=["geoip:private", "blocked.example"], direct=["geoip:private"])

    config = build_session_config(context, profile)

    proxy_rules = [r for r in config["routing"]["rules"] if r["outboundTag"] != "direct"]
    assert "geoip:private" not in str(proxy_rules)
    assert "geoip:private" in str(config["routing"]["rules"])


def test_unsafe_config_is_refused_with_the_reason(context, profile):
    use_custom_lists(context, proxy=["127.0.0.0/8"])

    with pytest.raises(UnsafeConfigError, match=r"127\.0\.0\.0/8"):
        build_session_config(context, profile)
```

Создать `tests/test_core_connection_validation.py`:

```python
"""Небезопасный конфиг не запускается, а причина доходит до пользователя."""

from __future__ import annotations

from src.core.config_builder import UnsafeConfigError
from src.core.connection import ConnectionService
from tests.test_core_connection import FakeProfile, make_context


def refuse(*_args):
    raise UnsafeConfigError(["первый outbound — freedom"])


def test_connect_reports_why_the_config_was_refused(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    monkeypatch.setattr("src.core.connection.build_session_config", refuse)

    result = ConnectionService(context).connect(1)

    assert not result.ok
    assert result.error == "Конфигурация отклонена: первый outbound — freedom"
    context.xray_manager.start.assert_not_called()


def test_reload_reports_why_the_config_was_refused(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.is_running = True
    monkeypatch.setattr("src.core.connection.build_session_config", refuse)

    result = ConnectionService(context).reload_config()

    assert not result.ok
    assert "Конфигурация отклонена" in result.error
    context.xray_manager.reload_config.assert_not_called()
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_config_validator.py tests/test_core_connection_validation.py -q`
Expected: `2 errors` — нет `UnsafeConfigError` и модуля `config_validator`.

**Step 3: Написать проверку**

Создать `src/core/config_validator.py`:

```python
"""Проверка готового конфига сессии перед запуском ядра.

Ядро проверяет схему, но не смысл: конфиг, где весь трафик идёт мимо прокси или
DNS ходит по кругу, оно примет молча. Здесь — инварианты, нарушение которых
означает ошибку сборки; с таким конфигом подключение не начинается.

Проверяется только то, что собирает `config_builder`. Пробные конфиги замера
задержки сюда не попадают.
"""

from __future__ import annotations

import ipaddress
from typing import Any

# Протоколы, которым нельзя быть выходом по умолчанию.
_NOT_A_PROXY = frozenset({"freedom", "blackhole", "dns"})
# Ключи правила, не являющиеся условием: правило только из них ловит всё подряд.
_NOT_A_CONDITION = frozenset({"type", "outboundTag", "network", "ruleTag"})
# Сети, которым нечего делать нигде, кроме direct.
_LOOPBACK = frozenset({"127.0.0.0/8", "::1/128", "geoip:private"})

TUN_INBOUND_TAG = "tun-in"
DNS_OUT_TAG = "dns-out"
LOCALHOST = "localhost"


def _dns_addresses(config: dict[str, Any]) -> list[str]:
    servers = config.get("dns", {}).get("servers", [])
    return [s if isinstance(s, str) else s.get("address", "") for s in servers]


def _check_outbounds(config: dict[str, Any]) -> list[str]:
    outbounds = config.get("outbounds") or []
    if not outbounds:
        return ["в конфиге нет ни одного outbound"]
    protocol = outbounds[0].get("protocol")
    if protocol in _NOT_A_PROXY:
        return [
            f"первый outbound — {protocol}: он выход по умолчанию, "
            "и весь несопоставленный трафик ушёл бы мимо прокси"
        ]
    return []


def _check_rules(config: dict[str, Any]) -> list[str]:
    outbounds = config.get("outbounds") or []
    known_tags = {o.get("tag") for o in outbounds}
    default_tag = outbounds[0].get("tag") if outbounds else None
    violations: list[str] = []

    for rule in config.get("routing", {}).get("rules", []):
        target = rule.get("outboundTag")
        if target not in known_tags:
            violations.append(f"правило ведёт в несуществующий outbound «{target}»")
            continue
        if set(rule) <= _NOT_A_CONDITION and target != default_tag:
            violations.append(
                f"правило без условий ведёт в «{target}»: мимо прокси ушёл бы весь трафик"
            )
        if target != "direct":
            for network in _LOOPBACK.intersection(rule.get("ip", [])):
                violations.append(f"{network} направлен в «{target}», а не напрямую")
    return violations


def _check_dns_interception(config: dict[str, Any]) -> list[str]:
    """Инварианты перехвата DNS; без outbound `dns-out` проверять нечего."""
    if not any(o.get("tag") == DNS_OUT_TAG for o in config.get("outbounds") or []):
        return []

    violations: list[str] = []
    rules = config.get("routing", {}).get("rules", [])
    first = rules[0] if rules else {}
    if not (
        first.get("outboundTag") == DNS_OUT_TAG
        and str(first.get("port")) == "53"
        and TUN_INBOUND_TAG in first.get("inboundTag", [])
    ):
        violations.append("правило перехвата DNS должно стоять первым")

    if LOCALHOST in _dns_addresses(config):
        violations.append("при перехвате DNS сервер localhost дал бы петлю запросов")

    dns_tag = config.get("dns", {}).get("tag")
    if not dns_tag or not any(
        dns_tag in rule.get("inboundTag", []) and rule.get("outboundTag") == "direct"
        for rule in rules
    ):
        violations.append(
            f"нет правила для собственных запросов DNS-модуля ({dns_tag or 'без тега'})"
        )
    return violations


def validate_session_config(config: dict[str, Any]) -> list[str]:
    """Нарушения, с которыми конфиг запускать нельзя; пустой список — конфиг годен."""
    if not config.get("outbounds"):
        # Остальные проверки без outbound'ов дали бы только шум.
        return _check_outbounds(config)
    return [
        *_check_outbounds(config),
        *_check_rules(config),
        *_check_dns_interception(config),
    ]


def exposed_inbounds(config: dict[str, Any]) -> list[str]:
    """Локальные входы, слушающие не на loopback: открытый прокси для всей сети.

    Это не нарушение — адрес задаёт пользователь, — но в журнале должно быть видно.
    """
    exposed: list[str] = []
    for inbound in config.get("inbounds", []):
        if inbound.get("protocol") not in ("socks", "http"):
            continue
        listen = inbound.get("listen") or "0.0.0.0"
        try:
            loopback = ipaddress.ip_address(listen).is_loopback
        except ValueError:
            loopback = listen == LOCALHOST
        if not loopback:
            exposed.append(f"{inbound.get('protocol')} {listen}:{inbound.get('port')}")
    return exposed
```

**Step 4: Подключить к сборщику и подключению**

Изменить `src/core/config_builder.py`:

```diff
--- a/src/core/config_builder.py
+++ b/src/core/config_builder.py
@@ -12,6 +12,7 @@ import logging
 import random
 import socket
 
+from src.core.config_validator import exposed_inbounds, validate_session_config
 from src.core.context import AppContext
 from src.core.dns_config import DNS_TAG, build_dns
 from src.core.geo import (
@@ -48,6 +49,7 @@ from src.sys.vpn import (
 logger = logging.getLogger("tenga.core.config_builder")
 
 BLOCK_TAG = "block"
+GEOIP_PRIVATE = "geoip:private"
 DNS_OUT_TAG = "dns-out"
 
 
@@ -61,6 +63,10 @@ def _parse_list(
     правило заработает.
     """
     domains, ips = routing.parse_entries(entries)
+    if list_name != "direct" and GEOIP_PRIVATE in ips:
+        # Вместе с частными сетями в прокси, VPN или блокировку ушёл бы и loopback.
+        logger.warning("Список «%s»: %s допустим только в direct", list_name, GEOIP_PRIVATE)
+        ips = [ip for ip in ips if ip != GEOIP_PRIVATE]
     domains, dropped_domains = catalog.split(domains)
     ips, dropped_ips = catalog.split(ips)
     dropped = dropped_domains + dropped_ips
@@ -107,8 +113,34 @@ def _bind_to_interface(outbound: dict, interface: str) -> None:
     sockopt["interface"] = interface
 
 
+class UnsafeConfigError(Exception):
+    """Собранный конфиг нарушает инварианты безопасности и запускаться не должен."""
+
+    def __init__(self, violations: list[str]) -> None:
+        super().__init__("; ".join(violations))
+        self.violations = list(violations)
+
+
 def build_session_config(context: AppContext, profile: ProfileEntry | None) -> dict | None:
-    """Create xray-core configuration for profile."""
+    """Create xray-core configuration for profile.
+
+    Raises:
+        UnsafeConfigError: конфиг собран, но не прошёл `validate_session_config`.
+    """
+    config = _build_session_config(context, profile)
+    if config is None:
+        return None
+
+    violations = validate_session_config(config)
+    if violations:
+        logger.error("Конфигурация профиля отклонена: %s", "; ".join(violations))
+        raise UnsafeConfigError(violations)
+    for inbound in exposed_inbounds(config):
+        logger.warning("Локальный вход открыт для сети: %s", inbound)
+    return config
+
+
+def _build_session_config(context: AppContext, profile: ProfileEntry | None) -> dict | None:
     try:
         result = profile.bean.build_core_obj_xray()
 
@@ -493,7 +525,7 @@ def build_latency_probe_config(
     Uses profile outbound/routing/dns from normal config but forces
     SYSTEM_PROXY inbounds to avoid TUN conflicts with active session.
     """
-    config = build_session_config(context, profile)
+    config = _build_session_config(context, profile)
     if not config:
         return None
 
```

Изменить `src/core/connection.py`:

```diff
--- a/src/core/connection.py
+++ b/src/core/connection.py
@@ -13,7 +13,7 @@ import logging
 from dataclasses import dataclass
 from typing import TYPE_CHECKING
 
-from src.core.config_builder import build_session_config, intercepts_dns
+from src.core.config_builder import UnsafeConfigError, build_session_config, intercepts_dns
 from src.core.proxy_mode import normalize_proxy_mode, should_manage_system_proxy
 from src.db.config import ProxyMode
 from src.sys.proxy import clear_system_proxy, set_system_proxy
@@ -30,6 +30,7 @@ logger = logging.getLogger("tenga.core.connection")
 PROFILE_NOT_FOUND = "Профиль не найден"
 NO_CONFIG = "Не удалось построить конфигурацию профиля"
 NOT_RUNNING = "Прокси не запущен"
+UNSAFE_CONFIG = "Конфигурация отклонена"
 
 
 @dataclass(frozen=True)
@@ -65,7 +66,10 @@ class ConnectionService:
         self._auto_connect_vpn(profile, profile_id)
 
         runtime_mode = normalize_proxy_mode(getattr(context.config, "proxy_mode", None))
-        config = build_session_config(context, profile)
+        try:
+            config = build_session_config(context, profile)
+        except UnsafeConfigError as e:
+            return ConnectionResult(False, f"{UNSAFE_CONFIG}: {e}")
         if not config:
             logger.error("Could not build a configuration for profile %s", profile_id)
             return ConnectionResult(False, NO_CONFIG)
@@ -259,7 +263,10 @@ class ConnectionService:
             logger.error("Profile %s not found for reload", profile_id)
             return ConnectionResult(False, PROFILE_NOT_FOUND)
 
-        config = build_session_config(context, profile)
+        try:
+            config = build_session_config(context, profile)
+        except UnsafeConfigError as e:
+            return ConnectionResult(False, f"{UNSAFE_CONFIG}: {e}")
         if not config:
             logger.error("Failed to create configuration for reload")
             return ConnectionResult(False, NO_CONFIG)
```

**Step 5: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_config_validator.py tests/test_core_connection_validation.py -q`
Expected: `22 passed`. Полный набор — зелёный: существующие тесты
подключения подменяют `build_session_config` и проверку не задевают.

**Step 6: Commit**

```bash
git add src/core/config_builder.py \
        src/core/config_validator.py \
        src/core/connection.py \
        tests/test_core_config_validator.py \
        tests/test_core_connection_validation.py
git commit -m "feat(core): проверять готовый конфиг перед запуском ядра"
```

---

### Task 11: Запросы к DNS-серверу VPN — через VPN

Найдено при сверке с режимом «VPN поверх» («Что проверено», п. 13). Домены
списка «Через VPN» резолвит DNS-сервер VPN, но сам запрос DNS-модуля к этому
серверу идёт по правилам маршрутизации, и правила для него нет — ни сейчас, ни
до плана. Запрос к частному адресу сервера уходил в прокси, а с «локальными
сетями напрямую», включёнными по умолчанию с задачи 7, ушёл бы в direct на
физическом интерфейсе. Без этой задачи решение 1 ухудшило бы режим «VPN поверх»
для тех, у кого подсеть сервера не внесена в список.

Правило `{ip: [сервер VPN], port: 53} → vpn` ставится первым — после правил
перехвата DNS, которые обязаны идти первыми (задача 10 это проверяет). Пишется,
только если адрес сервера разобран; при запасном `8.8.8.8` (адрес не разобран)
маршрут прежний.

**Files:**
- Modify: `src/core/config_builder.py`
- Test: `tests/test_core_dns_config.py`

**Step 1: Написать падающие тесты**

Изменить `tests/test_core_dns_config.py`:

```diff
--- a/tests/test_core_dns_config.py
+++ b/tests/test_core_dns_config.py
@@ -245,3 +245,64 @@ def test_ru_direct_resolves_russian_sites_with_the_system_resolver(context, prof
         direct_dns("geosite:category-ru", "geosite:category-gov-ru"),
         {"address": DOH},
     ]
+
+
+VPN_DNS_RULE = {"type": "field", "ip": ["10.222.0.7"], "port": "53", "outboundTag": "vpn"}
+
+
+def rules_of(context, profile) -> list[dict]:
+    config = build_session_config(context, profile)
+    assert config is not None
+    return config["routing"]["rules"]
+
+
+def test_queries_to_the_vpn_dns_server_go_through_the_vpn(context, profile, vpn):
+    """Сервер VPN доступен только через VPN: без правила запрос DNS-модуля к нему
+    ушёл бы в прокси, а с «локальными сетями напрямую» — мимо VPN в direct."""
+    use_custom_lists(context, vpn=["corp.example"])
+
+    rules = rules_of(context, profile)
+
+    assert rules[0] == VPN_DNS_RULE
+    assert any(
+        rule["outboundTag"] == "direct" and "10.0.0.0/8" in rule.get("ip", []) for rule in rules
+    )
+
+
+def test_vpn_dns_rule_follows_the_interception_rules(context, profile, vpn, monkeypatch):
+    """Правило перехвата обязано быть первым — правило сервера VPN идёт за ним."""
+    monkeypatch.setattr(config_builder, "system_dns_servers", lambda _iface: ["192.168.0.1"])
+    context.config.proxy_mode = "tun"
+    use_custom_lists(context, vpn=["corp.example"])
+
+    rules = rules_of(context, profile)
+
+    assert rules[0]["outboundTag"] == "dns-out"
+    assert rules[2] == VPN_DNS_RULE
+
+
+@pytest.mark.parametrize("reported", [[], ["не адрес"]], ids=["no-servers", "unreadable"])
+def test_no_vpn_dns_rule_without_a_known_vpn_dns_server(
+    context, profile, vpn, monkeypatch, reported
+):
+    monkeypatch.setattr(config_builder, "get_vpn_dns_servers", lambda _name: reported)
+    use_custom_lists(context, vpn=["corp.example"])
+
+    assert not any(rule.get("port") == "53" for rule in rules_of(context, profile))
+
+
+def test_no_vpn_dns_rule_without_vpn_domains(context, profile, vpn):
+    """Домены VPN-списка не заданы — сервер VPN не используется, правило не нужно."""
+    use_custom_lists(context, vpn=["10.14.0.0/16"])
+
+    assert VPN_DNS_RULE not in rules_of(context, profile)
+
+
+@needs_xray
+def test_core_accepts_vpn_dns_rule(context, profile, vpn, tmp_path):
+    use_custom_lists(context, vpn=["corp.example", "10.14.0.0/16"], direct=["direct.example"])
+
+    config = build_session_config(context, profile)
+
+    assert VPN_DNS_RULE in config["routing"]["rules"]
+    assert "Configuration OK" in xray_verdict(with_socks_inbound(config), tmp_path)
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_dns_config.py -q`
Expected: `3 failed, 25 passed` — падают три теста, где правило должно быть (включая
проверку ядром); тесты «правила нет» проходят и на старом коде.

**Step 3: Реализовать**

Изменить `src/core/config_builder.py`:

```diff
--- a/src/core/config_builder.py
+++ b/src/core/config_builder.py
@@ -14,7 +14,7 @@ import socket
 
 from src.core.config_validator import exposed_inbounds, validate_session_config
 from src.core.context import AppContext
-from src.core.dns_config import DNS_TAG, build_dns
+from src.core.dns_config import DNS_TAG, build_dns, parse_dns_endpoint
 from src.core.geo import (
     RU_DIRECT_GEOIP,
     RU_DIRECT_GEOSITES,
@@ -429,6 +429,21 @@ def _build_session_config(context: AppContext, profile: ProfileEntry | None) ->
         vpn_dns_servers: list[str] = []
         if vpn_active and vpn_domains:
             vpn_dns_servers = get_vpn_dns_servers(vpn_settings.connection_name)
+        vpn_dns = parse_dns_endpoint(vpn_dns_servers[0]) if vpn_dns_servers else None
+        if vpn_dns:
+            # Сервер VPN доступен только через VPN. Без правила запрос DNS-модуля к
+            # нему ушёл бы в прокси, а частный адрес — под «локальные сети» в direct.
+            # Правила перехвата DNS, если они есть, остаются первыми.
+            vpn_dns_address, vpn_dns_port = vpn_dns
+            route_rules.insert(
+                2 if system_resolvers else 0,
+                {
+                    "type": "field",
+                    "ip": [vpn_dns_address],
+                    "port": str(vpn_dns_port),
+                    "outboundTag": vpn_tag,
+                },
+            )
         # Серверы DNS идут в том же порядке, что и группы правил: имя должен
         # резолвить DNS той сети, в которую уйдёт сам трафик.
         domains_by_group = {"direct": direct_domains, "vpn": vpn_domains, "proxy": proxy_domains}
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_dns_config.py -q`
Expected: `28 passed`. Полный набор — зелёный: полный конфиг из
`tests/test_core_config_validator.py` с VPN проходит проверку и с новым
правилом.

**Step 5: Commit**

```bash
git add src/core/config_builder.py \
        tests/test_core_dns_config.py
git commit -m "fix(core): запросы к DNS-серверу VPN — через VPN"
```

---

### Task 12: Интерфейс — блок-лист, готовые правила, перехват DNS

Диалог «VPN и маршруты» профиля получает список «Блокировать» и тумблер
«Российские сайты и IP напрямую»; настройки приложения — тумблер «Перехватывать
DNS приложений» на странице DNS. Подписи считаются в `src/ui/logic/` и
проверяются без GTK: подзаголовок тумблера говорит, сработает ли он с
нынешними геобазами.

Заодно исправляется расхождение: «Локальные сети напрямую» действует в обоих
режимах маршрутизации, а диалог в режиме «весь трафик» делал его неактивным.

**GTK-тесты при написании плана запускались без экрана (Broadway), диалоги
глазами не смотрелись** — шаг 6 за тобой.

**Files:**
- Create: `src/ui/logic/routing_form.py`
- Modify: `src/ui/logic/monitoring_view.py` (счётчик direct-правил)
- Modify: `src/ui/dialogs/profile_routing.py`, `src/ui/dialogs/settings.py`
- Create: `tests/test_ui_logic_routing_form.py`
- Test: `tests/test_ui_logic_monitoring_view.py`,
  `tests/test_ui_dialogs_profile_routing.py`, `tests/test_ui_dialogs_settings.py`

**Step 1: Написать падающие тесты**

Без GTK:

Создать `tests/test_ui_logic_routing_form.py`:

```python
"""Подписи формы маршрутизации (без GTK)."""

from __future__ import annotations

from src.core.geo import GeoCatalog
from src.ui.logic.routing_form import LIST_HINT, ru_direct_subtitle

FULL = GeoCatalog(geosite=frozenset({"category-ru", "category-gov-ru"}), geoip=frozenset({"ru"}))


def test_subtitle_names_the_rules_when_bases_have_them():
    assert ru_direct_subtitle(FULL) == "geosite:category-ru, geosite:category-gov-ru, geoip:ru"


def test_subtitle_warns_when_a_category_is_missing():
    """Тумблер без категории в базе ничего не сделает — пользователь должен это видеть."""
    catalog = GeoCatalog(geosite=frozenset({"category-ru"}), geoip=frozenset())

    assert ru_direct_subtitle(catalog) == (
        "Не сработает полностью: в геобазах нет geosite:category-gov-ru, geoip:ru"
    )


def test_subtitle_without_geo_bases():
    assert ru_direct_subtitle(GeoCatalog()) == "Не сработает: геобазы не найдены"


def test_list_hint_mentions_geo_entries():
    assert "geosite:" in LIST_HINT
    assert "geoip:" in LIST_HINT
```

Изменить `tests/test_ui_logic_monitoring_view.py`:

```diff
--- a/tests/test_ui_logic_monitoring_view.py
+++ b/tests/test_ui_logic_monitoring_view.py
@@ -160,3 +160,10 @@ def test_vpn_connection_row_is_active_when_configured_and_up():
     )
     vpn_row = next(row for row in view.connection if row.title == "VPN")
     assert vpn_row.value == "Активен"
+
+
+def test_custom_counts_ready_made_rules():
+    routing = FakeRouting(mode="custom", direct_list=["a.example"], bypass_local_networks=True)
+    routing.ru_direct = True
+
+    assert values(routing_rows(routing))["DIRECT"] == "активен (3 правил)"
```

С GTK (`make test-gtk`):

Изменить `tests/test_ui_dialogs_profile_routing.py`:

```diff
--- a/tests/test_ui_dialogs_profile_routing.py
+++ b/tests/test_ui_dialogs_profile_routing.py
@@ -178,3 +178,35 @@ def test_all_three_lists_are_saved(gtk_ready):
     assert profile.routing_settings.proxy_list == ["p.com"]
     assert profile.routing_settings.direct_list == ["d.com"]
     assert profile.routing_settings.vpn_list == ["v.com"]
+
+
+def test_block_list_round_trips(gtk_ready):
+    routing = routing_settings(mode="custom", block_list=["ads.example"])
+    profile = make_profile(routing=routing)
+    dialog = make_dialog(profile)
+    assert dialog.block_text() == "ads.example"
+
+    dialog.set_block_text("ads.example\ntracker.example")
+    dialog.save()
+
+    assert profile.routing_settings.block_list == ["ads.example", "tracker.example"]
+
+
+def test_ru_direct_switch_round_trips(gtk_ready):
+    profile = make_profile(routing=routing_settings(mode="custom"))
+    dialog = make_dialog(profile)
+    assert not dialog.ru_direct_row.get_active()
+
+    dialog.ru_direct_row.set_active(True)
+    dialog.save()
+
+    assert profile.routing_settings.ru_direct is True
+
+
+def test_ready_made_rules_follow_the_mode(gtk_ready):
+    """Локальные сети напрямую действуют и в режиме «весь трафик», российские — нет."""
+    dialog = make_dialog(make_profile(routing=routing_settings(mode="proxy_all")))
+
+    assert dialog.bypass_row.get_sensitive()
+    assert not dialog.ru_direct_row.get_sensitive()
+    assert not dialog.block_view.get_sensitive()
```

Изменить `tests/test_ui_dialogs_settings.py`:

```diff
--- a/tests/test_ui_dialogs_settings.py
+++ b/tests/test_ui_dialogs_settings.py
@@ -128,3 +128,14 @@ def test_the_dns_through_proxy_switch_round_trips(gtk_ready):
     dialog.dns_proxy_row.set_active(False)
     dialog.save()
     assert config.dns.use_proxy is False
+
+
+def test_the_dns_interception_switch_round_trips(gtk_ready):
+    config = make_config()
+    dialog = make_dialog(config)
+    assert dialog.dns_intercept_row.get_active()
+
+    dialog.dns_intercept_row.set_active(False)
+    dialog.save()
+
+    assert config.dns.intercept is False
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_ui_logic_monitoring_view.py tests/test_ui_logic_routing_form.py -q`
Expected: `1 error` — `ModuleNotFoundError: No module named 'src.ui.logic.routing_form'`.

`make test-gtk` на этом шаге не поможет: он собирает и тесты без GTK, и сбор
прерывается на той же `ModuleNotFoundError`. GTK-файлы задачи можно прогнать
отдельно — в той же обстановке, что `make test-gtk` (свой D-Bus, дисплей):

```bash
dbus-run-session -- xvfb-run -a uv run pytest -m gtk tests/test_ui_dialogs_profile_routing.py tests/test_ui_dialogs_settings.py -q
```

Expected (при написании плана, Broadway вместо `xvfb-run`): `4 failed, 32 passed` —
три новых теста диалога маршрутов (`block_text`, `ru_direct_row`, неактивность
готовых правил) и тест тумблера `dns_intercept_row`.

**Step 3: Логика без GTK**

Создать `src/ui/logic/routing_form.py`:

```python
"""Подписи формы маршрутизации. GTK не импортируется."""

from __future__ import annotations

from src.core.config import find_xray_binary
from src.core.geo import RU_DIRECT_GEOIP, RU_DIRECT_GEOSITES, GeoCatalog, asset_dirs, load_catalog

LIST_HINT = "По одной записи в строке: домен, подсеть, geosite:категория, geoip:страна"
BLOCK_HINT = "Соединения обрываются, имена не резолвятся. Применяется раньше остальных списков"

_RU_DIRECT_RULES = (*RU_DIRECT_GEOSITES, RU_DIRECT_GEOIP)


def current_catalog() -> GeoCatalog:
    """Каталог тех геобаз, которые увидит ядро."""
    return load_catalog(asset_dirs(find_xray_binary()))


def ru_direct_subtitle(catalog: GeoCatalog) -> str:
    """Что сделает тумблер «российские сайты и IP напрямую» с этими геобазами."""
    missing = [rule for rule in _RU_DIRECT_RULES if not catalog.knows(rule)]
    if not missing:
        return ", ".join(_RU_DIRECT_RULES)
    if len(missing) == len(_RU_DIRECT_RULES):
        return "Не сработает: геобазы не найдены"
    return "Не сработает полностью: в геобазах нет " + ", ".join(missing)
```

Изменить `src/ui/logic/monitoring_view.py`:

```diff
--- a/src/ui/logic/monitoring_view.py
+++ b/src/ui/logic/monitoring_view.py
@@ -73,6 +73,8 @@ def routing_rows(
     direct_count = len(routing.direct_list or [])
     if routing.bypass_local_networks:
         direct_count += 1
+    if getattr(routing, "ru_direct", False):
+        direct_count += 1
     direct = f"активен ({direct_count} правил)" if direct_count else NOT_SET
 
     proxy_count = len(routing.proxy_list or [])
```

**Step 4: Диалоги**

Изменить `src/ui/dialogs/profile_routing.py`:

```diff
--- a/src/ui/dialogs/profile_routing.py
+++ b/src/ui/dialogs/profile_routing.py
@@ -12,6 +12,7 @@ from gi.repository import Adw, GObject, Gtk
 from src.db.config import RoutingMode, RoutingSettings, VpnSettings
 from src.ui.dialogs.settings import KeyedCombo
 from src.ui.logic.forms import parse_host_list
+from src.ui.logic.routing_form import BLOCK_HINT, LIST_HINT, current_catalog, ru_direct_subtitle
 
 ORDER_PRESETS: dict[str, list[str]] = {
     "direct_vpn_proxy": ["direct", "vpn", "proxy"],
@@ -31,8 +32,6 @@ ORDER_LABELS = {
     "proxy_vpn_direct": "Прокси → VPN → Напрямую",
 }
 
-LIST_HINT = "По одному домену или подсети в строке"
-
 
 def _list_view(title: str, subtitle: str) -> tuple[Adw.PreferencesGroup, Gtk.TextView]:
     """Build a titled text area for one routing list."""
@@ -146,10 +145,19 @@ class ProfileRoutingDialog(Adw.PreferencesDialog):
 
         self.bypass_row = Adw.SwitchRow(
             title="Локальные сети напрямую",
-            subtitle="127.0.0.0/8, 10.0.0.0/8, 192.168.0.0/16 и другие",
+            subtitle="127.0.0.0/8, 10.0.0.0/8, 192.168.0.0/16 и другие — после ваших списков",
         )
         mode_group.add(self.bypass_row)
 
+        self.ru_direct_row = Adw.SwitchRow(
+            title="Российские сайты и IP напрямую",
+            subtitle=ru_direct_subtitle(current_catalog()),
+        )
+        mode_group.add(self.ru_direct_row)
+
+        self.block_group, self.block_view = _list_view("Блокировать", BLOCK_HINT)
+        page.add(self.block_group)
+
         self.proxy_group, self.proxy_view = _list_view("Через прокси", LIST_HINT)
         page.add(self.proxy_group)
 
@@ -174,13 +182,15 @@ class ProfileRoutingDialog(Adw.PreferencesDialog):
     def _sync_mode(self) -> None:
         # В режиме «весь трафик через прокси» списки не применяются вовсе:
         # оставлять их активными — обещать пользователю несуществующий эффект.
+        # «Локальные сети напрямую» действует в обоих режимах и остаётся активным.
         custom = self._mode.selected() == RoutingMode.CUSTOM
         for widget in (
+            self.block_view,
             self.proxy_view,
             self.direct_view,
             self.vpn_view,
             self.order_row,
-            self.bypass_row,
+            self.ru_direct_row,
         ):
             widget.set_sensitive(custom)
 
@@ -202,8 +212,10 @@ class ProfileRoutingDialog(Adw.PreferencesDialog):
         routing = getattr(profile, "routing_settings", None) or RoutingSettings()
         self._mode.select(routing.mode)
         self.bypass_row.set_active(routing.bypass_local_networks)
+        self.ru_direct_row.set_active(getattr(routing, "ru_direct", False))
         self.select_order(_current_order(routing))
 
+        self.set_block_text("\n".join(getattr(routing, "block_list", None) or []))
         self.set_proxy_text("\n".join(routing.proxy_list or []))
         self.set_direct_text("\n".join(routing.direct_list or []))
         self.set_vpn_text("\n".join(routing.vpn_list or []))
@@ -234,7 +246,9 @@ class ProfileRoutingDialog(Adw.PreferencesDialog):
         routing = profile.routing_settings
         routing.mode = self._mode.selected()
         routing.bypass_local_networks = self.bypass_row.get_active()
+        routing.ru_direct = self.ru_direct_row.get_active()
         routing.rule_order = list(self.selected_order())
+        routing.block_list = parse_host_list(self.block_text())
         routing.proxy_list = parse_host_list(self.proxy_text())
         routing.direct_list = parse_host_list(self.direct_text())
         routing.vpn_list = parse_host_list(self.vpn_text())
@@ -261,6 +275,9 @@ class ProfileRoutingDialog(Adw.PreferencesDialog):
         # Порядок из другой версии или испорченный файл: берём первый пресет.
         self._order.select(next(iter(ORDER_PRESETS)))
 
+    def block_text(self) -> str:
+        return _read(self.block_view)
+
     def proxy_text(self) -> str:
         return _read(self.proxy_view)
 
@@ -270,6 +287,9 @@ class ProfileRoutingDialog(Adw.PreferencesDialog):
     def vpn_text(self) -> str:
         return _read(self.vpn_view)
 
+    def set_block_text(self, text: str) -> None:
+        self.block_view.get_buffer().set_text(text)
+
     def set_proxy_text(self, text: str) -> None:
         self.proxy_view.get_buffer().set_text(text)
 
```

Изменить `src/ui/dialogs/settings.py`:

```diff
--- a/src/ui/dialogs/settings.py
+++ b/src/ui/dialogs/settings.py
@@ -164,6 +164,13 @@ class SettingsDialog(Adw.PreferencesDialog):
         )
         options.add(self.dns_proxy_row)
 
+        self.dns_intercept_row = Adw.SwitchRow(
+            title="Перехватывать DNS приложений",
+            subtitle="Режим TUN: запросы приложений обрабатывает ядро — "
+            "действуют списки маршрутизации и блокировка",
+        )
+        options.add(self.dns_intercept_row)
+
     def _build_about_page(self) -> None:
         page = Adw.PreferencesPage(title="О программе", icon_name="help-about-symbolic")
         self.add(page)
@@ -230,6 +237,7 @@ class SettingsDialog(Adw.PreferencesDialog):
         self._dns.select(dns.provider)
         self.dns_url_row.set_text(dns.custom_url)
         self.dns_proxy_row.set_active(dns.use_proxy)
+        self.dns_intercept_row.set_active(getattr(dns, "intercept", True))
 
     def save(self) -> None:
         """Write the form back into the configuration object."""
@@ -251,6 +259,7 @@ class SettingsDialog(Adw.PreferencesDialog):
         config.dns.provider = self._dns.selected()
         config.dns.custom_url = self.dns_url_row.get_text().strip()
         config.dns.use_proxy = self.dns_proxy_row.get_active()
+        config.dns.intercept = self.dns_intercept_row.get_active()
 
         self.emit("settings-saved")
 
```

**Step 5: Убедиться, что проходят**

Run: `uv run pytest tests/test_ui_logic_monitoring_view.py tests/test_ui_logic_routing_form.py -q`
Expected: `23 passed`

Run: `make test-gtk`
Expected: `2 failed, 210 passed` — падают только два теста геометрии окна в `tests/test_ui_window.py`, которые падали и до плана.

**Step 6: Проверить глазами**

`python gui.py` → контекстное меню профиля → «VPN и маршруты…» → вкладка
«Маршрутизация»: список «Блокировать» стоит первым; в режиме «Весь трафик
через прокси» списки и «Российские сайты» неактивны, «Локальные сети напрямую»
активен. «Настройки → DNS»: новый тумблер включён.

**Step 7: Commit**

```bash
git add src/ui/dialogs/profile_routing.py \
        src/ui/dialogs/settings.py \
        src/ui/logic/monitoring_view.py \
        src/ui/logic/routing_form.py \
        tests/test_ui_dialogs_profile_routing.py \
        tests/test_ui_dialogs_settings.py \
        tests/test_ui_logic_monitoring_view.py \
        tests/test_ui_logic_routing_form.py
git commit -m "feat(ui): блок-лист, готовые правила и перехват DNS в настройках"
```

---

### Task 13: Поставка геобаз

В установленном приложении геобаз нет («Что проверено», п. 5): до этой задачи
geo-записи там молча пропускаются (задача 2), а тумблер «Российские сайты»
ничего не делает.

Три изменения:

1. `build_appimage.sh` кладёт `geoip.dat` и `geosite.dat` в AppImage рядом с
   бинарником ядра.
2. `install_appimage.sh` копирует их в `~/.config/tenga-proxy/bin/` — туда, где
   ядро ищет их само.
3. Если рядом с бинарником баз нет (установка обновлена одним AppImage, без
   скрипта), ядру называется каталог комплекта через `XRAY_LOCATION_ASSET`, и
   каталог категорий читается оттуда же. AppImage вырастет примерно на 30 МБ.

**Скрипты при написании плана не запускались**, только `bash -n`.

**Files:**
- Modify: `core/scripts/build_appimage.sh`, `core/scripts/install_appimage.sh`
- Modify: `src/core/geo.py` (`BUNDLED_GEO_DIR`, `asset_dir_for_core`)
- Modify: `src/core/xray_manager.py` (`_core_env`)
- Create: `tests/test_core_xray_manager_assets.py`
- Test: `tests/test_core_geo.py`

**Step 1: Написать падающие тесты**

Изменить `tests/test_core_geo.py`:

```diff
--- a/tests/test_core_geo.py
+++ b/tests/test_core_geo.py
@@ -8,10 +8,12 @@ from pathlib import Path
 
 import pytest
 
+from src.core import geo
 from src.core.geo import (
     GEOIP_FILE,
     GEOSITE_FILE,
     GeoCatalog,
+    asset_dir_for_core,
     asset_dirs,
     load_catalog,
     read_categories,
@@ -115,3 +117,55 @@ def test_bundled_bases_have_the_categories_the_builder_refers_to():
 
     assert {"category-ru", "category-gov-ru"} <= catalog.geosite
     assert {"ru", "private"} <= catalog.geoip
+
+
+# --- где ядро возьмёт базы -------------------------------------------------
+
+
+def put_bases(directory: Path) -> Path:
+    directory.mkdir(parents=True, exist_ok=True)
+    (directory / GEOSITE_FILE).write_bytes(make_dat("X"))
+    (directory / GEOIP_FILE).write_bytes(make_dat("X"))
+    return directory
+
+
+def test_bundled_bases_are_a_fallback_after_the_binary_directory(tmp_path, monkeypatch):
+    """Установка без баз рядом с ядром берёт их из комплекта приложения."""
+    monkeypatch.delenv("XRAY_LOCATION_ASSET", raising=False)
+    monkeypatch.setattr(geo, "BUNDLED_GEO_DIR", tmp_path / "bundle")
+
+    dirs = asset_dirs(tmp_path / "bin" / "xray")
+
+    assert dirs[:2] == [tmp_path / "bin", tmp_path / "bundle"]
+
+
+def test_core_needs_no_hint_when_bases_lie_next_to_it(tmp_path, monkeypatch):
+    monkeypatch.delenv("XRAY_LOCATION_ASSET", raising=False)
+    monkeypatch.setattr(geo, "BUNDLED_GEO_DIR", put_bases(tmp_path / "bundle"))
+    put_bases(tmp_path / "bin")
+
+    assert asset_dir_for_core(tmp_path / "bin" / "xray") is None
+
+
+def test_core_is_pointed_at_bundled_bases_when_it_has_none(tmp_path, monkeypatch):
+    """Сам ядро в комплект приложения не заглянет — каталог называем через окружение."""
+    monkeypatch.delenv("XRAY_LOCATION_ASSET", raising=False)
+    bundle = put_bases(tmp_path / "bundle")
+    monkeypatch.setattr(geo, "BUNDLED_GEO_DIR", bundle)
+
+    assert asset_dir_for_core(tmp_path / "bin" / "xray") == bundle
+
+
+def test_user_chosen_asset_directory_is_respected(tmp_path, monkeypatch):
+    monkeypatch.setenv("XRAY_LOCATION_ASSET", str(tmp_path / "mine"))
+    monkeypatch.setattr(geo, "BUNDLED_GEO_DIR", put_bases(tmp_path / "bundle"))
+
+    assert asset_dir_for_core(tmp_path / "bin" / "xray") is None
+
+
+def test_no_bases_anywhere_gives_no_hint(tmp_path, monkeypatch):
+    monkeypatch.delenv("XRAY_LOCATION_ASSET", raising=False)
+    monkeypatch.setattr(geo, "BUNDLED_GEO_DIR", tmp_path / "bundle")
+    monkeypatch.setattr(geo, "SYSTEM_ASSET_DIRS", ())
+
+    assert asset_dir_for_core(tmp_path / "bin" / "xray") is None
```

Создать `tests/test_core_xray_manager_assets.py`:

```python
"""Ядру передаётся каталог геобаз, если рядом с бинарником их нет."""

from __future__ import annotations

from src.core import xray_manager
from src.core.xray_manager import XrayManager


def start_and_capture_env(monkeypatch, tmp_path, asset_dir):
    captured: dict = {}

    class FakeProcess:
        pid = 1

        def poll(self):
            return None

    def popen(_cmd, **kwargs):
        captured.update(kwargs)
        return FakeProcess()

    monkeypatch.setattr(XrayManager, "_fetch_version", lambda _self: None)
    monkeypatch.setattr(XrayManager, "_wait_for_process_ready", lambda _self, **_k: True)
    monkeypatch.setattr(xray_manager, "XRAY_LOG_FILE", tmp_path / "xray.log")
    monkeypatch.setattr(xray_manager.subprocess, "Popen", popen)
    monkeypatch.setattr(xray_manager, "asset_dir_for_core", lambda _binary: asset_dir)

    manager = XrayManager(binary_path=str(tmp_path / "xray"))
    assert manager.start({"inbounds": [], "outbounds": []}) == (True, "")
    return captured.get("env")


def test_bundled_bases_are_passed_through_the_environment(monkeypatch, tmp_path):
    env = start_and_capture_env(monkeypatch, tmp_path, tmp_path / "bundle")

    assert env["XRAY_LOCATION_ASSET"] == str(tmp_path / "bundle")
    assert "PATH" in env  # остальное окружение сохранено


def test_environment_is_untouched_when_the_core_finds_bases_itself(monkeypatch, tmp_path):
    assert start_and_capture_env(monkeypatch, tmp_path, None) is None
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_geo.py tests/test_core_xray_manager_assets.py -q`
Expected: `1 error` — `ImportError: cannot import name 'asset_dir_for_core'`.

**Step 3: Реализовать**

Изменить `src/core/geo.py`:

```diff
--- a/src/core/geo.py
+++ b/src/core/geo.py
@@ -18,11 +18,15 @@ from collections.abc import Iterable
 from dataclasses import dataclass
 from pathlib import Path
 
+from src.core.config import BUNDLE_DIR
+
 logger = logging.getLogger("tenga.core.geo")
 
 GEOSITE_FILE = "geosite.dat"
 GEOIP_FILE = "geoip.dat"
 ASSET_ENV = "XRAY_LOCATION_ASSET"
+# Базы из комплекта приложения: в AppImage и в дереве исходников они лежат здесь.
+BUNDLED_GEO_DIR = BUNDLE_DIR / "core" / "bin"
 # Куда ядро заглядывает, если рядом с бинарником файла нет.
 SYSTEM_ASSET_DIRS = (Path("/usr/local/share/xray"), Path("/usr/share/xray"))
 
@@ -107,14 +111,40 @@ class GeoCatalog:
         return kept, dropped
 
 
+def _has_bases(directory: Path) -> bool:
+    return (directory / GEOSITE_FILE).is_file() and (directory / GEOIP_FILE).is_file()
+
+
+def asset_dir_for_core(binary_path: str | Path | None) -> Path | None:
+    """Каталог геобаз, который надо назвать ядру через `XRAY_LOCATION_ASSET`.
+
+    None — называть нечего: каталог уже задан пользователем, базы лежат рядом с
+    бинарником (там ядро найдёт их само) или их нет нигде.
+    """
+    if os.environ.get(ASSET_ENV):
+        return None
+    if binary_path and _has_bases(Path(binary_path).parent):
+        return None
+    if _has_bases(BUNDLED_GEO_DIR):
+        return BUNDLED_GEO_DIR
+    return None
+
+
 def asset_dirs(binary_path: str | Path | None) -> list[Path]:
-    """Каталоги, где ядро ищет геобазы, в порядке его поиска."""
+    """Каталоги, где окажутся геобазы ядра, в порядке поиска.
+
+    Повторяет поиск самого ядра (`XRAY_LOCATION_ASSET`, иначе каталог бинарника,
+    затем системные) с одной поправкой: если рядом с бинарником баз нет, ядру
+    называется каталог комплекта приложения — см. `asset_dir_for_core`.
+    """
     dirs: list[Path] = []
     env_dir = os.environ.get(ASSET_ENV)
     if env_dir:
         dirs.append(Path(env_dir))
-    elif binary_path:
-        dirs.append(Path(binary_path).parent)
+    else:
+        if binary_path:
+            dirs.append(Path(binary_path).parent)
+        dirs.append(BUNDLED_GEO_DIR)
     dirs.extend(SYSTEM_ASSET_DIRS)
     return dirs
 
```

Изменить `src/core/xray_manager.py`:

```diff
--- a/src/core/xray_manager.py
+++ b/src/core/xray_manager.py
@@ -2,6 +2,7 @@ from __future__ import annotations
 
 import json
 import logging
+import os
 import subprocess
 import tempfile
 import time
@@ -19,6 +20,7 @@ from src.core.config import (
     XRAY_LOG_FILE,
     find_xray_binary,
 )
+from src.core.geo import ASSET_ENV, asset_dir_for_core
 from src.core.performance import measure_time
 
 logger = logging.getLogger("tenga.xray_manager")
@@ -84,6 +86,18 @@ class XrayManager:
         # Cache xray version on initialization
         self._version_cache = self._fetch_version()
 
+    def _core_env(self) -> dict[str, str] | None:
+        """Окружение процесса ядра; None — унаследовать как есть.
+
+        Геобазы ядро ищет рядом с собой. Если их там нет (установка, сделанная до
+        появления баз в комплекте), называем каталог комплекта: правила с
+        `geosite:`/`geoip:` иначе уронили бы запуск.
+        """
+        asset_dir = asset_dir_for_core(self._binary_path)
+        if asset_dir is None:
+            return None
+        return {**os.environ, ASSET_ENV: str(asset_dir)}
+
     def _wait_for_process_ready(self, timeout: float = 2.0) -> bool:
         """Wait for xray process to be ready.
 
@@ -275,12 +289,14 @@ class XrayManager:
                     [self._binary_path, "-config", str(self._config_file)],
                     stdout=self._log_file,
                     stderr=subprocess.STDOUT,
+                    env=self._core_env(),
                 )
             else:
                 self._process = subprocess.Popen(
                     [self._binary_path, "-config", str(self._config_file)],
                     stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE,
+                    env=self._core_env(),
                 )
 
             if not self._wait_for_process_ready(timeout=2.0):
```

**Step 4: Скрипты**

Изменить `core/scripts/build_appimage.sh`:

```diff
--- a/core/scripts/build_appimage.sh
+++ b/core/scripts/build_appimage.sh
@@ -32,6 +32,12 @@ check_deps() {
     if [ ! -f "$PROJECT_ROOT/core/bin/xray" ]; then
         error "xray-core не найден в core/bin/"
     fi
+
+    for geo_file in geoip.dat geosite.dat; do
+        if [ ! -f "$PROJECT_ROOT/core/bin/$geo_file" ]; then
+            error "$geo_file не найден в core/bin/"
+        fi
+    done
     
     if ! command -v wget &>/dev/null && ! command -v curl &>/dev/null; then
         error "Требуется wget или curl"
@@ -81,6 +87,10 @@ create_appdir() {
     mkdir -p "$APPDIR/usr/share/tenga-proxy/core/bin"
     cp "$PROJECT_ROOT/core/bin/xray" "$APPDIR/usr/share/tenga-proxy/core/bin/"
     chmod +x "$APPDIR/usr/share/tenga-proxy/core/bin/xray"
+    # Геобазы: без них правила geosite:/geoip: роняют запуск ядра.
+    for geo_file in geoip.dat geosite.dat; do
+        cp "$PROJECT_ROOT/core/bin/$geo_file" "$APPDIR/usr/share/tenga-proxy/core/bin/"
+    done
 
     
     # Copy assets
```

Изменить `core/scripts/install_appimage.sh`:

```diff
--- a/core/scripts/install_appimage.sh
+++ b/core/scripts/install_appimage.sh
@@ -105,6 +105,16 @@ install_appimage() {
         chmod +x "$user_xray_path"
         info "Установлен xray: $user_xray_path"
 
+        # Геобазы ядро ищет рядом с собой.
+        for geo_file in geoip.dat geosite.dat; do
+            if [ -f "$PROJECT_ROOT/core/bin/$geo_file" ]; then
+                cp "$PROJECT_ROOT/core/bin/$geo_file" "$config_bin_dir/$geo_file"
+                info "Установлена геобаза: $config_bin_dir/$geo_file"
+            else
+                warning "Геобаза не найдена: $PROJECT_ROOT/core/bin/$geo_file"
+            fi
+        done
+
         if command -v setcap &>/dev/null; then
             info "Выдача прав для TUN режимa (cap_net_admin, cap_net_raw)..."
             if sudo setcap cap_net_admin,cap_net_raw+ep "$user_xray_path"; then
```

Run: `bash -n core/scripts/build_appimage.sh && bash -n core/scripts/install_appimage.sh`
Expected: без вывода.

**Step 5: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_geo.py tests/test_core_xray_manager_assets.py -q`
Expected: `16 passed`

**Step 6: Commit**

```bash
git add core/scripts/build_appimage.sh \
        core/scripts/install_appimage.sh \
        src/core/geo.py \
        src/core/xray_manager.py \
        tests/test_core_geo.py \
        tests/test_core_xray_manager_assets.py
git commit -m "build: поставлять геобазы с приложением и называть их каталог ядру"
```

---

### Task 14: Обновление геобаз по кнопке

> **Необязательная задача: можно вычеркнуть без последствий для остальных.**
> Без неё базы обновляются вместе с приложением.

Кнопка «Обновить» в «Настройки → О программе». Базы скачиваются из релизов
`Loyalsoldier/v2ray-rules-dat` (решение 3) в `<каталог конфигурации>/geo/` и
встроенные не заменяют. Устанавливаются, только если совпала SHA256 из
`.sha256sum` того же релиза и в базах есть категории готовых правил; обе базы
меняются вместе. Если файл в `geo/` окажется битым, каталог пропускается и
работают базы из комплекта — запуск не ломается.

Скачивание идёт обычным `requests`: в режиме TUN — через туннель, в режиме
системного прокси — напрямую. Если этап 2 добавил общую загрузку «через туннель
с откатом» (S4), её стоит подставить в `_http_fetch`.

**GTK-тест запускался без экрана (Broadway); глазами кнопка не проверялась.**

**Files:**
- Create: `src/core/geo_update.py`
- Modify: `src/core/geo.py` (`USER_GEO_DIR`, `REQUIRED_RULES`, `parse_categories`)
- Modify: `src/ui/logic/routing_form.py` (`geo_summary`), `src/ui/dialogs/settings.py`
- Create: `tests/test_core_geo_update.py`
- Test: `tests/test_ui_logic_routing_form.py`, `tests/test_ui_dialogs_settings.py`

**Step 1: Написать падающие тесты**

Создать `tests/test_core_geo_update.py`:

```python
"""Обновление геобаз по кнопке: проверка суммы, атомарная замена, откат."""

from __future__ import annotations

import hashlib

import pytest

from src.core import geo
from src.core.geo import GEOIP_FILE, GEOSITE_FILE, asset_dir_for_core, asset_dirs, load_catalog
from src.core.geo_update import GEO_SOURCE, GeoUpdateError, update_geo_bases
from tests.test_core_geo import make_dat, put_bases

GOOD = {
    GEOSITE_FILE: make_dat("CATEGORY-RU", "CATEGORY-GOV-RU", "GOOGLE"),
    GEOIP_FILE: make_dat("RU", "PRIVATE", "CN"),
}


def checksum_line(name: str, data: bytes) -> bytes:
    return f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode()


def make_fetch(files: dict[str, bytes], checksums: dict[str, bytes] | None = None):
    """Подмена сети: отдаёт файлы и их `.sha256sum` по адресам источника."""
    checksums = checksums or {name: checksum_line(name, data) for name, data in files.items()}
    requested: list[str] = []

    def fetch(url: str, limit: int) -> bytes:
        requested.append(url)
        assert url.startswith(GEO_SOURCE + "/")
        name = url.removeprefix(GEO_SOURCE + "/")
        if name.endswith(".sha256sum"):
            return checksums[name.removesuffix(".sha256sum")]
        data = files[name]
        if len(data) > limit:
            raise GeoUpdateError("файл больше допустимого")
        return data

    fetch.requested = requested
    return fetch


def test_verified_bases_are_installed(tmp_path):
    target = tmp_path / "geo"

    update_geo_bases(target, fetch=make_fetch(GOOD))

    assert (target / GEOSITE_FILE).read_bytes() == GOOD[GEOSITE_FILE]
    assert (target / GEOIP_FILE).read_bytes() == GOOD[GEOIP_FILE]
    assert sorted(p.name for p in target.iterdir()) == [GEOIP_FILE, GEOSITE_FILE]


def test_checksum_mismatch_keeps_the_old_bases(tmp_path):
    target = put_bases(tmp_path / "geo")
    old = (target / GEOSITE_FILE).read_bytes()
    bad_sums = {name: checksum_line(name, b"something else") for name in GOOD}

    with pytest.raises(GeoUpdateError, match="контрольная сумма"):
        update_geo_bases(target, fetch=make_fetch(GOOD, bad_sums))

    assert (target / GEOSITE_FILE).read_bytes() == old
    assert sorted(p.name for p in target.iterdir()) == [GEOIP_FILE, GEOSITE_FILE]


def test_bases_without_required_categories_are_rejected(tmp_path):
    """База без категорий готовых правил уронила бы ядро при включённом тумблере."""
    files = {**GOOD, GEOIP_FILE: make_dat("CN")}

    with pytest.raises(GeoUpdateError, match="geoip:ru"):
        update_geo_bases(tmp_path / "geo", fetch=make_fetch(files))

    assert not (tmp_path / "geo" / GEOSITE_FILE).exists()


def test_one_bad_file_installs_nothing(tmp_path):
    """Базы меняются парой: половина обновления хуже, чем никакого."""
    files = {**GOOD, GEOIP_FILE: b"\xff\xff\xff"}

    with pytest.raises(GeoUpdateError):
        update_geo_bases(tmp_path / "geo", fetch=make_fetch(files))

    assert not (tmp_path / "geo" / GEOSITE_FILE).exists()


# --- использование скачанных баз -------------------------------------------


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.delenv("XRAY_LOCATION_ASSET", raising=False)
    monkeypatch.setattr(geo, "USER_GEO_DIR", tmp_path / "geo")
    monkeypatch.setattr(geo, "BUNDLED_GEO_DIR", put_bases(tmp_path / "bundle"))
    put_bases(tmp_path / "bin")
    return tmp_path


def test_downloaded_bases_win_over_bundled_ones(dirs):
    update_geo_bases(dirs / "geo", fetch=make_fetch(GOOD))

    assert asset_dir_for_core(dirs / "bin" / "xray") == dirs / "geo"
    assert "google" in load_catalog(asset_dirs(dirs / "bin" / "xray")).geosite


def test_corrupt_downloaded_bases_fall_back_to_bundled_ones(dirs):
    """Битый файл в каталоге обновлений не должен ломать запуск."""
    update_geo_bases(dirs / "geo", fetch=make_fetch(GOOD))
    (dirs / "geo" / GEOIP_FILE).write_bytes(b"\xff\xff\xff")

    assert asset_dir_for_core(dirs / "bin" / "xray") is None
    assert load_catalog(asset_dirs(dirs / "bin" / "xray")).geosite == frozenset({"x"})
```

Изменить `tests/test_ui_logic_routing_form.py`:

```diff
--- a/tests/test_ui_logic_routing_form.py
+++ b/tests/test_ui_logic_routing_form.py
@@ -3,7 +3,7 @@
 from __future__ import annotations
 
 from src.core.geo import GeoCatalog
-from src.ui.logic.routing_form import LIST_HINT, ru_direct_subtitle
+from src.ui.logic.routing_form import LIST_HINT, geo_summary, ru_direct_subtitle
 
 FULL = GeoCatalog(geosite=frozenset({"category-ru", "category-gov-ru"}), geoip=frozenset({"ru"}))
 
@@ -28,3 +28,11 @@ def test_subtitle_without_geo_bases():
 def test_list_hint_mentions_geo_entries():
     assert "geosite:" in LIST_HINT
     assert "geoip:" in LIST_HINT
+
+
+def test_geo_summary_counts_categories():
+    assert geo_summary(FULL) == "geosite: 2 категорий, geoip: 1"
+
+
+def test_geo_summary_without_bases():
+    assert geo_summary(GeoCatalog()) == "Не найдены: правила geosite: и geoip: не применяются"
```

С GTK:

Изменить `tests/test_ui_dialogs_settings.py`:

```diff
--- a/tests/test_ui_dialogs_settings.py
+++ b/tests/test_ui_dialogs_settings.py
@@ -139,3 +139,8 @@ def test_the_dns_interception_switch_round_trips(gtk_ready):
     dialog.save()
 
     assert config.dns.intercept is False
+
+
+def test_the_about_page_shows_geo_bases(gtk_ready):
+    dialog = make_dialog(make_config())
+    assert dialog.geo_row.get_subtitle()
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_geo_update.py tests/test_ui_logic_routing_form.py -q`
Expected: `2 errors` — нет модуля `geo_update` и функции `geo_summary`.

**Step 3: Реализовать**

Изменить `src/core/geo.py`:

```diff
--- a/src/core/geo.py
+++ b/src/core/geo.py
@@ -18,13 +18,15 @@ from collections.abc import Iterable
 from dataclasses import dataclass
 from pathlib import Path
 
-from src.core.config import BUNDLE_DIR
+from src.core.config import BUNDLE_DIR, CORE_DIR
 
 logger = logging.getLogger("tenga.core.geo")
 
 GEOSITE_FILE = "geosite.dat"
 GEOIP_FILE = "geoip.dat"
 ASSET_ENV = "XRAY_LOCATION_ASSET"
+# Базы, скачанные пользователем по кнопке «Обновить» (src/core/geo_update.py).
+USER_GEO_DIR = CORE_DIR / "geo"
 # Базы из комплекта приложения: в AppImage и в дереве исходников они лежат здесь.
 BUNDLED_GEO_DIR = BUNDLE_DIR / "core" / "bin"
 # Куда ядро заглядывает, если рядом с бинарником файла нет.
@@ -37,6 +39,8 @@ GEOIP_PREFIX = "geoip:"
 # каталогу, как и пользовательские: без них в базе правило просто не пишется.
 RU_DIRECT_GEOSITES = ("geosite:category-ru", "geosite:category-gov-ru")
 RU_DIRECT_GEOIP = "geoip:ru"
+# Без этих категорий базу устанавливать нельзя.
+REQUIRED_RULES = (*RU_DIRECT_GEOSITES, RU_DIRECT_GEOIP, "geoip:private")
 
 # Поле 1, тип «строка байтов» — и у записи списка, и у названия внутри записи.
 _LENGTH_DELIMITED_FIELD_1 = 0x0A
@@ -53,7 +57,13 @@ def _read_varint(data: memoryview, pos: int) -> tuple[int, int]:
         shift += 7
 
 
-def _parse_categories(data: memoryview) -> frozenset[str]:
+def parse_categories(raw: bytes | memoryview) -> frozenset[str]:
+    """Названия категорий базы в нижнем регистре.
+
+    Raises:
+        ValueError, IndexError, UnicodeDecodeError: содержимое — не геобаза.
+    """
+    data = memoryview(raw)
     names: set[str] = set()
     pos, size = 0, len(data)
     while pos < size:
@@ -76,11 +86,11 @@ def _parse_categories(data: memoryview) -> frozenset[str]:
 def read_categories(path: Path) -> frozenset[str]:
     """Названия категорий базы в нижнем регистре; пусто, если файла нет или он битый."""
     try:
-        data = memoryview(path.read_bytes())
+        data = path.read_bytes()
     except OSError:
         return frozenset()
     try:
-        return _parse_categories(data)
+        return parse_categories(data)
     except (ValueError, IndexError, UnicodeDecodeError) as e:
         logger.warning("Геобаза %s повреждена: %s", path, e)
         return frozenset()
@@ -115,14 +125,33 @@ def _has_bases(directory: Path) -> bool:
     return (directory / GEOSITE_FILE).is_file() and (directory / GEOIP_FILE).is_file()
 
 
+def missing_required(catalog: GeoCatalog) -> list[str]:
+    """Категории готовых правил, которых нет в базах."""
+    return [rule for rule in REQUIRED_RULES if not catalog.knows(rule)]
+
+
+def _downloaded_bases_usable() -> bool:
+    """Годны ли базы из каталога обновлений.
+
+    Битый или неполный файл там не должен ломать запуск: тогда каталог
+    пропускается и работают базы из комплекта.
+    """
+    if not _has_bases(USER_GEO_DIR):
+        return False
+    return not missing_required(load_catalog([USER_GEO_DIR]))
+
+
 def asset_dir_for_core(binary_path: str | Path | None) -> Path | None:
     """Каталог геобаз, который надо назвать ядру через `XRAY_LOCATION_ASSET`.
 
     None — называть нечего: каталог уже задан пользователем, базы лежат рядом с
-    бинарником (там ядро найдёт их само) или их нет нигде.
+    бинарником (там ядро найдёт их само) или их нет нигде. Обновлённые
+    пользователем базы главнее тех, что рядом с бинарником.
     """
     if os.environ.get(ASSET_ENV):
         return None
+    if _downloaded_bases_usable():
+        return USER_GEO_DIR
     if binary_path and _has_bases(Path(binary_path).parent):
         return None
     if _has_bases(BUNDLED_GEO_DIR):
@@ -134,14 +163,17 @@ def asset_dirs(binary_path: str | Path | None) -> list[Path]:
     """Каталоги, где окажутся геобазы ядра, в порядке поиска.
 
     Повторяет поиск самого ядра (`XRAY_LOCATION_ASSET`, иначе каталог бинарника,
-    затем системные) с одной поправкой: если рядом с бинарником баз нет, ядру
-    называется каталог комплекта приложения — см. `asset_dir_for_core`.
+    затем системные) с поправкой на то, что называет ядру `asset_dir_for_core`:
+    годные базы из каталога обновлений, а если рядом с бинарником баз нет —
+    каталог комплекта приложения.
     """
     dirs: list[Path] = []
     env_dir = os.environ.get(ASSET_ENV)
     if env_dir:
         dirs.append(Path(env_dir))
     else:
+        if _downloaded_bases_usable():
+            dirs.append(USER_GEO_DIR)
         if binary_path:
             dirs.append(Path(binary_path).parent)
         dirs.append(BUNDLED_GEO_DIR)
```

Создать `src/core/geo_update.py`:

```python
"""Обновление геобаз по запросу пользователя.

Базы скачиваются в каталог конфигурации (`geo/`), рядом со встроенными не
ложатся и их не заменяют: испорченное обновление всегда можно обойти, вернувшись
к базам из комплекта (см. `src/core/geo.py`).

Файл устанавливается, только если совпала контрольная сумма из того же релиза и
в базе есть категории, на которые ссылаются готовые правила. Обе базы меняются
вместе: сначала всё проверяется, потом переименовывается.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path

import requests

from src.core.geo import (
    GEOIP_FILE,
    GEOSITE_FILE,
    GeoCatalog,
    missing_required,
    parse_categories,
)

logger = logging.getLogger("tenga.core.geo_update")

# Тот же источник, из которого берёт базы сборка самого xray-core.
GEO_SOURCE = "https://github.com/Loyalsoldier/v2ray-rules-dat/releases/latest/download"
MAX_BASE_SIZE = 64 * 1024 * 1024
MAX_CHECKSUM_SIZE = 4096

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

Fetch = Callable[[str, int], bytes]


class GeoUpdateError(Exception):
    """Обновление не установлено; прежние базы остались на месте."""


def _http_fetch(url: str, limit: int) -> bytes:
    """Скачать файл, не принимая больше `limit` байт."""
    try:
        with requests.get(url, stream=True, timeout=(10, 60)) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(chunk_size=1 << 16):
                size += len(chunk)
                if size > limit:
                    raise GeoUpdateError(f"{url}: файл больше {limit} байт")
                chunks.append(chunk)
            return b"".join(chunks)
    except requests.RequestException as e:
        raise GeoUpdateError(f"{url}: {e}") from e


def _expected_sha256(checksum_file: bytes, name: str) -> str:
    """Сумма из файла `.sha256sum` (формат `sha256sum`: «сумма  имя»)."""
    parts = checksum_file.decode("ascii", errors="replace").split()
    digest = parts[0].lower() if parts else ""
    if not _SHA256.match(digest):
        raise GeoUpdateError(f"{name}: файл контрольной суммы не разобран")
    return digest


def _download_verified(name: str, fetch: Fetch) -> bytes:
    data = fetch(f"{GEO_SOURCE}/{name}", MAX_BASE_SIZE)
    expected = _expected_sha256(fetch(f"{GEO_SOURCE}/{name}.sha256sum", MAX_CHECKSUM_SIZE), name)
    if hashlib.sha256(data).hexdigest() != expected:
        raise GeoUpdateError(f"{name}: контрольная сумма не совпала")
    return data


def _categories(name: str, data: bytes) -> frozenset[str]:
    try:
        return parse_categories(data)
    except (ValueError, IndexError, UnicodeDecodeError) as e:
        raise GeoUpdateError(f"{name}: файл повреждён ({e})") from e


def update_geo_bases(target_dir: Path, *, fetch: Fetch = _http_fetch) -> GeoCatalog:
    """Скачать, проверить и установить обе базы.

    Raises:
        GeoUpdateError: что-то не сошлось; в `target_dir` ничего не изменилось.
    """
    bases = {name: _download_verified(name, fetch) for name in (GEOSITE_FILE, GEOIP_FILE)}
    catalog = GeoCatalog(
        geosite=_categories(GEOSITE_FILE, bases[GEOSITE_FILE]),
        geoip=_categories(GEOIP_FILE, bases[GEOIP_FILE]),
    )
    missing = missing_required(catalog)
    if missing:
        raise GeoUpdateError("в скачанных базах нет категорий: " + ", ".join(missing))

    target_dir.mkdir(parents=True, exist_ok=True)
    temporary = {name: target_dir / f".{name}.tmp" for name in bases}
    try:
        for name, data in bases.items():
            temporary[name].write_bytes(data)
        for name in bases:
            os.replace(temporary[name], target_dir / name)
    except OSError as e:
        raise GeoUpdateError(f"не удалось записать базы: {e}") from e
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)

    logger.info("Геобазы обновлены: %s", target_dir)
    return catalog
```

Изменить `src/ui/logic/routing_form.py`:

```diff
--- a/src/ui/logic/routing_form.py
+++ b/src/ui/logic/routing_form.py
@@ -24,3 +24,10 @@ def ru_direct_subtitle(catalog: GeoCatalog) -> str:
     if len(missing) == len(_RU_DIRECT_RULES):
         return "Не сработает: геобазы не найдены"
     return "Не сработает полностью: в геобазах нет " + ", ".join(missing)
+
+
+def geo_summary(catalog: GeoCatalog) -> str:
+    """Строка состояния геобаз для страницы «О программе»."""
+    if not catalog.geosite and not catalog.geoip:
+        return "Не найдены: правила geosite: и geoip: не применяются"
+    return f"geosite: {len(catalog.geosite)} категорий, geoip: {len(catalog.geoip)}"
```

Изменить `src/ui/dialogs/settings.py`:

```diff
--- a/src/ui/dialogs/settings.py
+++ b/src/ui/dialogs/settings.py
@@ -9,7 +9,11 @@ gi.require_version("Adw", "1")
 
 from gi.repository import Adw, GObject, Gtk
 
+from src.core.geo import USER_GEO_DIR
+from src.core.geo_update import update_geo_bases
 from src.db.config import DnsProvider, ProxyMode
+from src.ui.logic.async_utils import run_in_background
+from src.ui.logic.routing_form import current_catalog, geo_summary
 from src.ui.logic.version import UNKNOWN, app_version, core_version
 
 LOG_LEVELS = ["debug", "info", "warning", "error", "none"]
@@ -197,6 +201,12 @@ class SettingsDialog(Adw.PreferencesDialog):
         self.clear_logs_row.set_sensitive(self._context is not None)
         actions.add(self.clear_logs_row)
 
+        self.geo_row = Adw.ActionRow(title="Геобазы", subtitle=geo_summary(current_catalog()))
+        self.geo_update_button = Gtk.Button(label="Обновить", valign=Gtk.Align.CENTER)
+        self.geo_update_button.connect("clicked", self._on_update_geo)
+        self.geo_row.add_suffix(self.geo_update_button)
+        actions.add(self.geo_row)
+
     @staticmethod
     def _value_row(title: str, value: str) -> Adw.ActionRow:
         row = Adw.ActionRow(title=title, subtitle=value)
@@ -278,6 +288,25 @@ class SettingsDialog(Adw.PreferencesDialog):
     def select_log_level(self, key: str) -> None:
         self._log_level.select(key)
 
+    def _on_update_geo(self, _button: Gtk.Button) -> None:
+        # Скачивание — десятки мегабайт: в главном потоке окно бы замерло.
+        self.geo_update_button.set_sensitive(False)
+        self.geo_row.set_subtitle("Скачивание…")
+        run_in_background(
+            lambda: update_geo_bases(USER_GEO_DIR),
+            on_done=self._on_geo_updated,
+            on_error=self._on_geo_update_failed,
+            name="tenga-geo-update",
+        )
+
+    def _on_geo_updated(self, catalog) -> None:
+        self.geo_update_button.set_sensitive(True)
+        self.geo_row.set_subtitle(f"{geo_summary(catalog)} — применятся при следующем подключении")
+
+    def _on_geo_update_failed(self, error: BaseException) -> None:
+        self.geo_update_button.set_sensitive(True)
+        self.geo_row.set_subtitle(f"Не обновлены: {error}")
+
     def _on_clear_logs(self, _button: Gtk.Button) -> None:
         if self._context is None:
             return
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_geo_update.py tests/test_ui_logic_routing_form.py -q`
Expected: `12 passed`

Run: `make test-gtk`
Expected: `2 failed, 211 passed` — те же два теста геометрии окна.

**Step 5: Проверить настоящим скачиванием**

```bash
uv run python -c "
import pathlib, tempfile
from src.core.geo_update import update_geo_bases
catalog = update_geo_bases(pathlib.Path(tempfile.mkdtemp()))
print(len(catalog.geosite), len(catalog.geoip))
"
```

Expected: два числа (при написании плана — `1549 260`), без исключения.

**Step 6: Commit**

```bash
git add src/core/geo.py \
        src/core/geo_update.py \
        src/ui/dialogs/settings.py \
        src/ui/logic/routing_form.py \
        tests/test_core_geo_update.py \
        tests/test_ui_dialogs_settings.py \
        tests/test_ui_logic_routing_form.py
git commit -m "feat(core): обновление геобаз по кнопке с проверкой SHA256"
```

---

### Task 15: Документация и итоговая проверка

**Files:**
- Modify: `docs/ru/routing.md`, `docs/en/routing.md`
- Modify: `docs/plans/2026-10-03-network-parity-roadmap.md`

**Step 1: Обновить описание маршрутизации**

Разделы «Форматы записей» обещали то, чего не было (`*.example.com`,
регулярные выражения), и не описывали нового. Если задачи 9 или 14 вычеркнуты —
убери из текста упоминания помощника и кнопки «Обновить».

Изменить `docs/ru/routing.md`:

````diff
--- a/docs/ru/routing.md
+++ b/docs/ru/routing.md
@@ -49,23 +49,67 @@
 
 ## Форматы записей
 
-### Доменные имена
+В каждой строке списка — одна запись. Запись, которую ядро не поняло бы,
+пропускается: одно негодное правило иначе сорвало бы всё подключение.
 
-- `example.com` - конкретный домен
-- `*.example.com` - поддомены домена
-- `domain:example.com` - указание типа домена
+### Домены
 
-### IP-адреса и подсети
+| Запись | Что совпадает |
+|---|---|
+| `example.com` | домен и все его поддомены |
+| `*.example.com`, `.example.com` | то же самое |
+| `full:example.com` | только сам домен |
+| `google` | любое имя, где встречается слово (без точки — подстрока) |
+| `keyword:video` | то же, явно |
+| `regexp:^ads\d+\.example\.com$` | регулярное выражение |
+| `geosite:category-ru` | категория из geosite.dat |
 
-- `192.168.1.1` - конкретный IP-адрес
-- `192.168.1.0/24` - подсеть
-- `geoip:cn` - географическое расположение (если поддерживается)
+### Адреса и сети
 
-### Паттерны и маски
+| Запись | Что совпадает |
+|---|---|
+| `192.168.1.1`, `2001:db8::1` | один адрес |
+| `192.168.1.0/24`, `fc00::/7` | подсеть |
+| `geoip:ru` | страна из geoip.dat |
 
-- Поддержка различных форматов
-- Возможность использования регулярных выражений
-- Совместимость с популярными форматами подписок
+`geoip:private` допустим только в списке «Напрямую»; для частных сетей есть
+готовое правило (см. ниже).
+
+Категория, которой нет в геобазах, пропускается с предупреждением в журнале.
+Состояние баз видно в «Настройки → О программе», там же кнопка «Обновить».
+
+## Блокировка
+
+Список «Блокировать»: соединения обрываются, а имена не резолвятся (ответ
+NXDOMAIN). Применяется раньше остальных списков при любом порядке групп.
+
+## Готовые правила
+
+Стоят после пользовательских списков: явная запись всегда главнее.
+
+- **Локальные сети напрямую** — `127.0.0.0/8`, `10.0.0.0/8`, `192.168.0.0/16` и
+  другие частные диапазоны. Включено по умолчанию, действует в обоих режимах.
+- **Российские сайты и IP напрямую** — `geosite:category-ru`,
+  `geosite:category-gov-ru`, `geoip:ru`. Выключено по умолчанию, действует в
+  режиме списков. Нужны геобазы.
+
+## DNS
+
+Имя резолвит DNS той сети, в которую пойдёт сам трафик:
+
+- домены списка «Напрямую» и российские сайты готового правила — DNS вашей сети;
+- домены списка «Через VPN» — DNS-сервер VPN (запросы к нему идут через VPN);
+- домены списка «Через прокси» и всё остальное — DNS из настроек (по умолчанию
+  DoH через прокси).
+
+Если DNS из настроек недоступен, имена провайдеру не уходят: системный
+резолвер обслуживает только свои домены.
+
+В режиме TUN запросы приложений перехватываются и обрабатываются теми же
+правилами («Настройки → DNS → Перехватывать DNS приложений»). На системах с
+systemd-resolved для этого нужен установленный помощник маршрутов
+(`python cli.py install`); запросы типов, отличных от A и AAAA, пересылаются
+DNS вашей сети без изменений.
 
 ## Приоритет правил
 
@@ -107,8 +151,8 @@ VPN: *.company.com
 ### Сложный пример
 
 ```
-DIRECT: geoip:private, domain:local, domain:localhost
-PROXY: geosite:geolocation-!cn
+DIRECT: geosite:category-ru, geoip:ru, domain:local
+PROXY: geosite:google, blocked.example
 VPN: domain:restricted-site.com, 10.10.10.0/24
 ```
 
````

Изменить `docs/en/routing.md`:

````diff
--- a/docs/en/routing.md
+++ b/docs/en/routing.md
@@ -49,23 +49,67 @@ List of domains and IP addresses whose traffic:
 
 ## Entry Formats
 
-### Domain Names
+One entry per line. An entry the core would not understand is skipped: a single
+bad rule would otherwise break the whole connection.
 
-- `example.com` - specific domain
-- `*.example.com` - domain subdomains
-- `domain:example.com` - domain type specification
+### Domains
 
-### IP Addresses and Subnets
+| Entry | Matches |
+|---|---|
+| `example.com` | the domain and all its subdomains |
+| `*.example.com`, `.example.com` | the same |
+| `full:example.com` | the domain itself only |
+| `google` | any name containing the word (no dot means substring) |
+| `keyword:video` | the same, explicitly |
+| `regexp:^ads\d+\.example\.com$` | regular expression |
+| `geosite:category-ru` | a category from geosite.dat |
 
-- `192.168.1.1` - specific IP address
-- `192.168.1.0/24` - subnet
-- `geoip:cn` - geographic location (if supported)
+### Addresses and Networks
 
-### Patterns and Masks
+| Entry | Matches |
+|---|---|
+| `192.168.1.1`, `2001:db8::1` | a single address |
+| `192.168.1.0/24`, `fc00::/7` | a subnet |
+| `geoip:ru` | a country from geoip.dat |
 
-- Support for various formats
-- Regular expression support
-- Compatibility with popular subscription formats
+`geoip:private` is allowed in the Direct list only; private networks have a
+ready-made rule (see below).
+
+A category missing from the geo databases is skipped with a warning in the log.
+The state of the databases is shown in Settings → About, next to the Update
+button.
+
+## Blocking
+
+The Block list drops connections and makes names unresolvable (NXDOMAIN). It is
+applied before all other lists, whatever the group order.
+
+## Ready-made Rules
+
+They come after the user lists: an explicit entry always wins.
+
+- **Local networks direct** — `127.0.0.0/8`, `10.0.0.0/8`, `192.168.0.0/16` and
+  other private ranges. On by default, works in both modes.
+- **Russian sites and IPs direct** — `geosite:category-ru`,
+  `geosite:category-gov-ru`, `geoip:ru`. Off by default, works in the lists
+  mode. Requires geo databases.
+
+## DNS
+
+A name is resolved by the DNS of the network its traffic will use:
+
+- Direct-list domains and Russian sites of the ready-made rule — your network's DNS;
+- VPN-list domains — the VPN DNS server (queried through the VPN);
+- Proxy-list domains and everything else — the DNS from settings (DoH through
+  the proxy by default).
+
+If the configured DNS is unreachable, names do not leak to the provider: the
+system resolver serves its own domains only.
+
+In TUN mode application queries are intercepted and handled by the same rules
+(Settings → DNS → Intercept application DNS). On systems with systemd-resolved
+this needs the installed route helper (`python cli.py install`); query types
+other than A and AAAA are forwarded to your network's DNS unchanged.
 
 ## Rule Priority
 
@@ -107,8 +151,8 @@ VPN: *.company.com
 ### Complex Example
 
 ```
-DIRECT: geoip:private, domain:local, domain:localhost
-PROXY: geosite:geolocation-!cn
+DIRECT: geosite:category-ru, geoip:ru, domain:local
+PROXY: geosite:google, blocked.example
 VPN: domain:restricted-site.com, 10.10.10.0/24
 ```
 
````

**Step 2: Полная проверка**

```bash
uv run pytest -q
make test-gtk
python cli.py lint-all
```

Expected: всё зелёное, линтер без замечаний. При написании плана полный набор
без GTK — `795 passed` (было 634); GTK-набор — `2 failed, 211 passed`; до плана — `2 failed, 206 passed` (два теста геометрии окна в
`tests/test_ui_window.py` падали и до плана — без экрана, на Broadway).

**Step 3: Проверка DNS-модуля настоящим ядром без TUN**

Сценарий собирает конфиг как для режима TUN, заменяет TUN-вход SOCKS-входом с
тем же тегом и шлёт DNS-запросы через него. Прав не требует, работающему
подключению не мешает. Сохрани как `live_dns_check.py` в корне проекта, после
проверки удали — в репозиторий он не идёт.

```python
"""Живая проверка DNS-модуля настоящим ядром — без TUN и без прав.

Собирает конфиг сессии как для режима TUN, но TUN-inbound заменяет SOCKS-входом
с тем же тегом, запускает ядро на свободном порту и шлёт DNS-запросы по TCP
через SOCKS. Правилу перехвата важен тег входа, а не протокол.

Запуск из корня проекта:  uv run python live_dns_check.py <интерфейс> <DNS сети>
Пример:                   uv run python live_dns_check.py wlp1s0 192.168.0.1
"""

import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, ".")
os.environ.setdefault("XRAY_LOCATION_ASSET", str(Path("core/bin").resolve()))

from src.core import config_builder
from src.core.config_builder import build_session_config
from src.db.config import ProxyMode
from tests.support.session import make_context, make_profile, use_custom_lists, with_socks_inbound


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


PORT = free_port()


def query(name: str, qtype: int = 1) -> str:
    sock = socket.create_connection(("127.0.0.1", PORT), timeout=8)
    try:
        sock.sendall(b"\x05\x01\x00")
        assert sock.recv(2) == b"\x05\x00"
        # CONNECT 1.1.1.1:53 — адрес не важен: запрос перехватит правило tun-in:53.
        sock.sendall(b"\x05\x01\x00\x01" + socket.inet_aton("1.1.1.1") + struct.pack(">H", 53))
        assert sock.recv(10)[1] == 0
        question = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
        packet = struct.pack(">HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) + question
        packet += struct.pack(">HH", qtype, 1)
        sock.sendall(struct.pack(">H", len(packet)) + packet)
        header = sock.recv(2)
        if len(header) < 2:
            return "соединение закрыто"
        data = sock.recv(struct.unpack(">H", header)[0])
        flags, _questions, answers = struct.unpack(">HHH", data[2:8])
        return f"rcode={flags & 15} answers={answers}"
    except TimeoutError:
        return "нет ответа"
    finally:
        sock.close()


def main(interface: str, resolver: str) -> None:
    config_builder.get_default_interface = lambda *_a, **_k: interface
    config_builder.system_dns_servers = lambda _iface: [resolver]

    workdir = Path(tempfile.mkdtemp())
    context = make_context(workdir)
    profile = make_profile(context)
    context.config.proxy_mode = ProxyMode.TUN
    context.config.log_level = "debug"
    # Сервер профиля в тесте ненастоящий: удалённый DNS пускаем напрямую.
    context.config.dns.use_proxy = False
    use_custom_lists(context, direct=["ya.ru"], block=["ads.example"])

    config = with_socks_inbound(build_session_config(context, profile))
    config["inbounds"][0]["port"] = PORT
    assert not any(i.get("protocol") == "tun" for i in config["inbounds"])
    path = workdir / "config.json"
    path.write_text(json.dumps(config))

    log = (workdir / "xray.log").open("w")
    # `timeout` — страховка: ядро не переживёт сценарий, даже если тот упадёт.
    core = subprocess.Popen(
        ["timeout", "60", "core/bin/xray", "run", "-config", str(path)], stdout=log, stderr=log
    )
    try:
        time.sleep(2)
        expectations = [
            ("ya.ru", 1, "rcode=0, ответы есть — резолвит DNS сети (в журнале: UDP:<DNS сети>)"),
            ("example.com", 1, "rcode=0, ответы есть — резолвит DoH"),
            ("sub.ads.example", 1, "rcode=3 — блок-лист"),
            ("ya.ru", 16, "rcode=0, ответы есть — TXT переслан DNS сети"),
        ]
        for name, qtype, expected in expectations:
            print(f"{name} тип {qtype}: {query(name, qtype)}   ожидается: {expected}")
    finally:
        core.terminate()
        core.wait(timeout=5)
    print(f"журнал ядра: {workdir / 'xray.log'}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
```

Run: `uv run python live_dns_check.py <физический интерфейс> <DNS-сервер сети>`
(интерфейс и сервер — из `resolvectl dns`)

Expected (при написании плана):

```
ya.ru тип 1: rcode=0 answers=3
example.com тип 1: rcode=0 answers=2
sub.ads.example тип 1: rcode=3 answers=0
ya.ru тип 16: rcode=0 answers=4
```

**Step 4: Проверка на живом подключении**

Юнит-тесты и `xray -test` подтверждают только то, что ядро принимает конфиг.
Остальное — руками, с журналом ядра на уровне `debug`
(`~/.config/tenga-proxy/logs/xray.log`). Перед проверкой переустановить
приложение (`python cli.py setup`): нужны новый помощник и геобазы.

Режим TUN, профиль без VPN:

- [ ] Подключение поднимается; в `current_config.json` у outbound'ов `direct` и
      профиля — `sockopt.interface` с физическим интерфейсом.
- [ ] Домен из списка «Напрямую» открывается; в журнале `[tun-in -> direct]`,
      и строка не повторяется лавиной (петли нет).
- [ ] Включить «Российские сайты и IP напрямую»: `ya.ru` идёт в `direct`,
      заблокированный сайт — в прокси. Проверять браузером: по HTTP/3 домен
      виден только при работающем QUIC-sniffing.
- [ ] Домен из списка «Блокировать»: `resolvectl query` отвечает «not found»,
      сайт не открывается.
- [ ] `resolvectl status xray0`: `DNS Servers: 1.1.1.1`, `DNS Domain: ~.`
      (задача 9). В журнале ядра — `[tun-in -> dns-out]`.
- [ ] `dig +short TXT example.com` и `dig +short MX example.com` отвечают.
- [ ] После отключения `resolvectl status` — как до подключения; сайты
      открываются.
- [ ] Отключить «Перехватывать DNS приложений», переподключиться: `dns-out` в
      конфиге нет, всё работает.

Режим TUN, профиль с VPN («VPN поверх»):

- [ ] Домен из списка «Через VPN» резолвится DNS-сервером VPN и открывается.
- [ ] Подсеть `10.x` из списка «Через VPN» идёт в `vpn`, а не в `direct`, при
      включённых «Локальных сетях напрямую» и порядке «Напрямую → VPN → Прокси».

Режим системного прокси:

- [ ] Подключение, списки и блок-лист работают; `dns-out` в конфиге нет.

Установка:

- [ ] После `python cli.py setup` в `~/.config/tenga-proxy/bin/` лежат
      `geoip.dat` и `geosite.dat`; «Настройки → О программе → Геобазы»
      показывает число категорий.
- [ ] Кнопка «Обновить» (задача 14): базы появляются в
      `~/.config/tenga-proxy/geo/`, после переподключения в журнале нет
      предупреждений о пропущенных категориях.

Что проверить не удалось — записать в дорожную карту, в статус этапа 3.

**Step 5: Записать статус в дорожную карту и закоммитить**

В `docs/plans/2026-10-03-network-parity-roadmap.md`, раздел «Этап 3»: статус,
какие задачи выполнены, какие вычеркнуты и почему, результаты ручной проверки.
Туда же — находки этого плана, которых в карте нет: привязка прямого выхода в
режиме TUN (задача 6), направление системного DNS в TUN через
systemd-resolved (задача 9, к нюансу D1), маршрут запросов к DNS-серверу VPN
(задача 11), поставка геобаз (задача 13), нормализация доменных записей
(задача 1); отклонения: «локальные сети» — списком CIDR, а не `geoip:private`
(решение 1), адрес входа не на loopback — предупреждение, а не отказ
(решение 11).

```bash
git add docs/en/routing.md \
        docs/ru/routing.md
git commit -m "docs: маршрутизация — форматы записей, блокировка, готовые правила, DNS"
```

```bash
git add docs/plans/2026-10-03-network-parity-roadmap.md
git commit -m "docs: статус этапа 3 в дорожной карте"
```

Версию приложения поднимает владелец проекта: `python cli.py bump-version <версия>`.
