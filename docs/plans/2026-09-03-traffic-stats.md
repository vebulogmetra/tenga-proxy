# Счётчик трафика в статус-карточке: реализация Stats API

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Показывать в статус-карточке реальный объём переданного и принятого
трафика вместо постоянных `↑ 0 B ↓ 0 B`.

**Architecture:** Счётчик не работает по четырём независимым причинам сразу:
в конфигурации нет секции `policy`, чтение статистики подменено заглушкой,
счётчик ищется по неверному имени и никто не опрашивает его периодически.
Устраняются все четыре.

Счётчики берутся у xray через его Stats API. Конфигурация
дополняется секцией `policy`, без которой ядро трафик не считает вовсе.
Опрос идёт вызовом `xray api statsquery` — тем же бинарником, что уже управляет
ядром, поэтому protobuf-стабы не нужны. Периодический вызов встраивается в
`ConnectionMonitor`, у которого уже есть таймер `GLib.timeout_add`, фоновый
поток и уведомление UI.

**Tech Stack:** Python 3.11, xray-core 26.3.27, GLib/GTK 4, pytest.

---

## Разведка: что установлено до написания плана

Проверено на работающей системе 2026-09-03, а не предположено.

1. **Счётчик не работал никогда.** Это не регрессия редизайна интерфейса:
   `ProxyState.upload_bytes` и `download_bytes` объявлены в
   `src/core/context.py:24-25`, обнуляются в `set_stopped()`
   (`src/core/context.py:61-62`) — и не записываются нигде. Писателя нет.

2. **`_get_stats_via_api()` — заглушка.** `src/core/xray_manager.py:406-411`
   логирует «Stats API not fully implemented» и безусловно возвращает 0.
   `get_traffic()` (там же, строки 413-423) вызывает её дважды, поэтому всегда
   отдаёт нули.

3. **В конфигурации не хватает `policy`.** `_inject_stats_api()`
   (`src/core/xray_manager.py:125-215`) добавляет `stats`, `api`, inbound
   `dokodemo-door`, outbound `freedom` и правило маршрутизации, но секции
   `policy` не добавляет. Без `policy.system.statsOutboundUplink` и
   `statsOutboundDownlink` xray счётчики не заводит.

   Проверено на живом процессе: порт 10085 слушается, API отвечает, но
   `xray api statsquery --server=127.0.0.1:10085` возвращает пустой `{}`.

   Затем проверено обратное — на отдельном пробном экземпляре ядра (порты
   10086/12080, чтобы не задеть рабочее подключение) с добавленной `policy`:
   до трафика счётчики появились в списке, после запроса через socks
   `outbound>>>proxy>>>traffic>>>uplink` вырос до 80. Секция `policy` и есть
   недостающее звено.

4. **HTTP у Stats API нет, только gRPC.** `curl http://127.0.0.1:10085/stats`
   возвращает код 000 (соединение не установлено). Поэтому свойство
   `stats_api_url` (`src/core/xray_manager.py:109-112`), формирующее
   `http://…`, вводит в заблуждение и должно быть удалено.

5. **Вызов CLI дёшев.** `xray api statsquery` отрабатывает за ~25 мс — для
   опроса раз в секунду приемлемо. Это снимает необходимость генерировать
   protobuf-стабы, хотя `grpcio` и `grpcio-tools` в зависимостях есть.

6. **Нулевые счётчики приходят без поля `value`.** В ответе xray у обнулённого
   счётчика ключ `value` просто отсутствует, а не равен нулю. Парсер обязан
   трактовать его отсутствие как 0, иначе получит `KeyError`.

7. **Тег outbound — имя профиля, а не `proxy`.** Это четвёртое звено бага.
   Все реализации протоколов ставят `outbound["tag"] = self.name`
   (`src/fmt/protocols/trojan_vless.py:254` и 431, `vmess.py:268`,
   `shadowsocks.py:184`, `socks_http.py:139` и 237, `hysteria2.py:148`), а
   `config_builder.py:42-43` подставляет `"proxy"` только тогда, когда тега
   нет вовсе — то есть у безымянного профиля. В конфигурации владельца тег
   равен `🇵🇱Польша | XHTTP VPN#6`.

   Поэтому ключ `outbound>>>proxy>>>traffic>>>uplink`, зашитый в
   `get_traffic()` (`src/core/xray_manager.py:420-421`), почти всегда
   промахивается мимо счётчика. Даже с исправленной `policy` и живым API
   он продолжал бы отдавать нули.

8. **Настройки под задачу уже заведены.** `traffic_loop_interval: int = 1000`
   (`src/db/data_store.py:100`) и `connection_statistics: bool = False`
   (`src/db/data_store.py:101`) объявлены, но не читаются ни одной строкой кода.
   Первое становится интервалом опроса, второе — выключателем.

9. **Место для опроса готово.** `ConnectionMonitor` (`src/core/monitor.py`)
   уже держит `GLib.timeout_add` (строка 80), уходит в фоновый поток
   (строка 132) и уведомляет интерфейс (`_notify_ui_update`, строка 311).
   Статус-карточка перерисовывается по слушателю `ProxyState`
   (`src/ui/window.py:87`, `_on_proxy_state_changed` в строке 501), а текст
   собирает `metrics_text()` (`src/ui/logic/status.py:42-60`) — она уже умеет
   печатать байты и менять ничего не требует.

## Ограничения

- **Рабочее приложение трогать нельзя.** У владельца запущен установленный
  экземпляр с живым подключением. Не закрывать его, не отключать профили, не
  занимать порт 10085. Пробные экземпляры ядра поднимать только на других
  портах и гасить строго по записанному PID, сверив командную строку.
- Тесты не должны требовать ни запущенного xray, ни сети: вызов CLI
  подменяется.
- GTK-тесты в этой системе падают, пока имя `ru.tenga.Proxy` занято рабочим
  приложением. Это не признак поломки; проверять `uv run pytest`.

---

### Задача 1: Добавить `policy` в конфигурацию ядра

Без этой секции всё остальное бессмысленно: считать будет нечего.

**Files:**
- Modify: `src/core/xray_manager.py:125-215` (`_inject_stats_api`)
- Test: `tests/test_core_xray_manager.py`

**Шаг 1. Написать падающий тест**

```python
def test_inject_stats_api_enables_the_outbound_counters():
    """Без policy ядро не считает трафик, сколько ни включай stats."""
    manager = XrayManager(binary_path="/nonexistent")
    config = manager._inject_stats_api({"inbounds": [], "outbounds": []})

    system = config["policy"]["system"]
    assert system["statsOutboundUplink"] is True
    assert system["statsOutboundDownlink"] is True


def test_inject_stats_api_keeps_an_existing_policy():
    """Своя policy пользователя не затирается, счётчики к ней добавляются."""
    manager = XrayManager(binary_path="/nonexistent")
    config = manager._inject_stats_api(
        {"policy": {"levels": {"0": {"handshake": 4}}}}
    )

    assert config["policy"]["levels"] == {"0": {"handshake": 4}}
    assert config["policy"]["system"]["statsOutboundUplink"] is True
```

**Шаг 2. Убедиться, что тест падает**

Запустить: `uv run pytest tests/test_core_xray_manager.py -k policy -v`
Ожидается: FAIL, `KeyError: 'policy'`.

**Шаг 3. Реализовать**

В `_inject_stats_api`, рядом с включением `stats`, дополнять `policy`, не
затирая пользовательскую:

```python
        # Без счётчиков в policy ядро не ведёт статистику вовсе: секции stats
        # и api сами по себе только открывают доступ к тому, что уже посчитано.
        policy = config.setdefault("policy", {})
        system = policy.setdefault("system", {})
        system["statsOutboundUplink"] = True
        system["statsOutboundDownlink"] = True
```

Учесть, что `config = config.copy()` в начале функции — копия поверхностная:
вложенный словарь `policy` из аргумента изменять на месте нельзя, иначе
правка протечёт в конфигурацию вызывающего. Копировать вложенный уровень
явно.

**Шаг 4. Проверить**

Запустить: `uv run pytest tests/test_core_xray_manager.py -k policy -v`
Ожидается: PASS.

**Шаг 5. Коммит**

```bash
git add src/core/xray_manager.py tests/test_core_xray_manager.py
git commit -m "fix(core): включить счётчики трафика в конфигурации ядра"
```

---

### Задача 2: Читать статистику вместо заглушки

**Files:**
- Modify: `src/core/xray_manager.py:406-423` (`_get_stats_via_api`, `get_traffic`)
- Modify: `src/core/xray_manager.py:109-112` (удалить `stats_api_url`)
- Test: `tests/test_core_xray_manager.py`

**Шаг 1. Написать падающие тесты**

Подменяется `subprocess.run`, чтобы тест не требовал ни ядра, ни сети.

```python
_STATS_ANSWER = """
{
    "stat": [
        {"name": "outbound>>>proxy>>>traffic>>>uplink", "value": 1024},
        {"name": "outbound>>>proxy>>>traffic>>>downlink", "value": 2048},
        {"name": "outbound>>>api>>>traffic>>>uplink"}
    ]
}
"""


def test_get_traffic_reads_the_proxy_counters(monkeypatch):
    manager = XrayManager(binary_path="/nonexistent")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=_STATS_ANSWER, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    stats = manager.get_traffic()
    assert stats.upload == 1024
    assert stats.download == 2048


def test_get_traffic_counts_a_missing_value_as_zero(monkeypatch):
    """Обнулённый счётчик приходит без ключа value, а не с нулём в нём."""
    answer = '{"stat": [{"name": "outbound>>>proxy>>>traffic>>>uplink"}]}'

    manager = XrayManager(binary_path="/nonexistent")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=answer, stderr=""),
    )

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)


def test_get_traffic_survives_a_dead_core(monkeypatch):
    """Опрос идёт по таймеру: упасть при остановленном ядре он не вправе."""
    manager = XrayManager(binary_path="/nonexistent")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("нет такого файла")),
    )

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)


def test_get_traffic_survives_broken_output(monkeypatch):
    manager = XrayManager(binary_path="/nonexistent")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="не json", stderr=""),
    )

    assert manager.get_traffic() == TrafficStats(upload=0, download=0)
```

**Шаг 2. Убедиться, что тесты падают**

Запустить: `uv run pytest tests/test_core_xray_manager.py -k traffic -v`
Ожидается: FAIL — заглушка возвращает нули там, где ждут 1024 и 2048.

**Шаг 3. Реализовать**

Заменить `_get_stats_via_api` разбором ответа целиком: одного вызова хватает
на оба счётчика, два запуска процесса ради двух чисел не нужны.

```python
    def _query_stats(self) -> dict[str, int]:
        """Read every counter the core keeps.

        Статистика снимается вызовом самого бинарника: Stats API работает
        только по gRPC, а генерировать protobuf-стабы ради двух чисел
        избыточно — вызов укладывается в 25 мс.
        """
        try:
            result = subprocess.run(
                [self._binary_path, "api", "statsquery",
                 f"--server={self._stats_api_addr}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug("Stats query failed: %s", e)
            return {}

        if result.returncode != 0:
            logger.debug("Stats query returned %s: %s", result.returncode, result.stderr)
            return {}

        try:
            answer = json.loads(result.stdout or "{}")
        except json.JSONDecodeError as e:
            logger.debug("Could not parse the stats answer: %s", e)
            return {}

        # У обнулённого счётчика ключа value нет вовсе.
        return {
            item["name"]: int(item.get("value", 0))
            for item in answer.get("stat", [])
            if "name" in item
        }

    def get_traffic(self) -> TrafficStats:
        """Current traffic totals of the proxy outbound."""
        stats = self._query_stats()
        return TrafficStats(
            upload=stats.get("outbound>>>proxy>>>traffic>>>uplink", 0),
            download=stats.get("outbound>>>proxy>>>traffic>>>downlink", 0),
        )
```

Удалить свойство `stats_api_url`: оно обещает HTTP, которого у Stats API нет
(проверено — соединение не устанавливается). Прежде убедиться, что его никто
не вызывает: `grep -rn "stats_api_url" --include=*.py .`

Ключ `outbound>>>proxy>>>traffic>>>uplink` брать нельзя — см. задачу 2а.

**Шаг 4. Проверить**

Запустить: `uv run pytest tests/test_core_xray_manager.py -k traffic -v`
Ожидается: PASS, все четыре.

**Шаг 5. Коммит**

```bash
git add src/core/xray_manager.py tests/test_core_xray_manager.py
git commit -m "feat(core): читать статистику трафика через Stats API"
```

---

### Задача 2а: Искать счётчик по фактическому тегу профиля

Счётчик называется по тегу outbound, а тег — это имя профиля (разведка,
пункт 7). Жёсткая строка `proxy` промахивается у любого именованного профиля,
то есть практически всегда.

**Files:**
- Modify: `src/core/xray_manager.py` (`get_traffic`)
- Test: `tests/test_core_xray_manager.py`

**Шаг 1. Написать падающий тест**

```python
def test_get_traffic_sums_the_proxy_outbounds(monkeypatch):
    """Тег outbound — имя профиля; direct, vpn и api в счёт не идут."""
    answer = json.dumps({"stat": [
        {"name": "outbound>>>🇵🇱Польша | XHTTP VPN#6>>>traffic>>>uplink", "value": 500},
        {"name": "outbound>>>🇵🇱Польша | XHTTP VPN#6>>>traffic>>>downlink", "value": 900},
        {"name": "outbound>>>direct>>>traffic>>>uplink", "value": 111},
        {"name": "outbound>>>vpn>>>traffic>>>downlink", "value": 222},
        {"name": "outbound>>>api>>>traffic>>>uplink", "value": 333},
    ]})

    manager = XrayManager(binary_path="/nonexistent")
    monkeypatch.setattr(
        "subprocess.run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=answer, stderr=""),
    )

    assert manager.get_traffic() == TrafficStats(upload=500, download=900)
```

**Шаг 2. Убедиться, что тест падает**

Запустить: `uv run pytest tests/test_core_xray_manager.py -k sums_the_proxy -v`
Ожидается: FAIL — вернутся нули, потому что ключа со словом `proxy` в ответе нет.

**Шаг 3. Реализовать**

Складывать все outbound, кроме служебных. Имя профиля заранее неизвестно, а
служебные теги известны наперечёт (`config_builder.py` заводит `direct`, `vpn`
и `api`), поэтому надёжнее исключать их, чем угадывать имя:

```python
    # Служебные каналы в счёт не идут: direct — трафик мимо прокси, vpn —
    # через туннель, api — сам опрос статистики.
    _SERVICE_TAGS = frozenset({"direct", "vpn", "api", "block", "dns-out"})

    def get_traffic(self) -> TrafficStats:
        """Traffic totals of every proxy outbound.

        Счётчик именуется по тегу outbound, а тег — это имя профиля, не
        строка `proxy`. Поэтому складываются все каналы, кроме служебных.
        """
        upload = download = 0
        for name, value in self._query_stats().items():
            parts = name.split(">>>")
            if len(parts) != 4 or parts[0] != "outbound":
                continue
            if parts[1] in self._SERVICE_TAGS:
                continue
            if parts[3] == "uplink":
                upload += value
            elif parts[3] == "downlink":
                download += value
        return TrafficStats(upload=upload, download=download)
```

Тесты задачи 2 остаются в силе: тег `proxy` служебным не считается, поэтому
безымянный профиль по-прежнему учитывается.

**Шаг 4. Проверить**

Запустить: `uv run pytest tests/test_core_xray_manager.py -k traffic -v`
Ожидается: PASS, включая тесты задачи 2.

**Шаг 5. Коммит**

```bash
git add src/core/xray_manager.py tests/test_core_xray_manager.py
git commit -m "fix(core): считать трафик по фактическому тегу профиля"
```

---

### Задача 3: Опрашивать статистику по таймеру

**Files:**
- Modify: `src/core/monitor.py`
- Test: `tests/test_core_monitor.py`

**Шаг 1. Написать падающий тест**

```python
def test_the_monitor_writes_traffic_into_the_state(monkeypatch):
    """Опрос кладёт цифры в состояние: карточка читает их оттуда."""
    context = _make_context()
    context.proxy_state.set_running(profile_id=1)
    monkeypatch.setattr(
        context.xray_manager, "get_traffic",
        lambda: TrafficStats(upload=4096, download=8192),
    )

    monitor = ConnectionMonitor(context)
    monitor.refresh_traffic()

    assert context.proxy_state.upload_bytes == 4096
    assert context.proxy_state.download_bytes == 8192


def test_the_monitor_skips_traffic_while_stopped(monkeypatch):
    """У остановленного ядра спрашивать нечего: процесса нет."""
    context = _make_context()
    context.proxy_state.set_stopped()
    called = []
    monkeypatch.setattr(
        context.xray_manager, "get_traffic",
        lambda: called.append(1) or TrafficStats(),
    )

    ConnectionMonitor(context).refresh_traffic()

    assert not called
```

**Шаг 2. Убедиться, что тест падает**

Запустить: `uv run pytest tests/test_core_monitor.py -k traffic -v`
Ожидается: FAIL, `AttributeError: refresh_traffic`.

**Шаг 3. Реализовать**

Добавить в `ConnectionMonitor` отдельный таймер с интервалом
`config.traffic_loop_interval` (миллисекунды, по умолчанию 1000), не смешивая
его с проверкой доступности: у той интервал 10 секунд, для счётчика это
слишком редко.

```python
    def refresh_traffic(self) -> None:
        """Pull the counters into the shared state.

        Молча ничего не делает у остановленного ядра: опрос идёт по таймеру,
        а спрашивать статистику у несуществующего процесса незачем.
        """
        state = self._context.proxy_state
        if not state.is_running:
            return

        stats = self._context.xray_manager.get_traffic()
        if stats.upload == state.upload_bytes and stats.download == state.download_bytes:
            return

        state.upload_bytes = stats.upload
        state.download_bytes = stats.download
        state.notify_listeners()
```

Требования к вызову по таймеру:

- запуск вызова в фоновом потоке, как это делает `_check_connections`
  (`src/core/monitor.py:132`): вызов процесса занимает ~25 мс, и на слабой
  машине этого хватит, чтобы интерфейс дёрнулся;
- запись в состояние и `notify_listeners()` — из главного потока через
  `GLib.idle_add`, поскольку по цепочке слушателей идёт перерисовка виджетов;
- уведомлять слушателей только при изменившихся цифрах: иначе карточка
  перерисовывается раз в секунду впустую;
- таймер снимать в `stop()` вместе с основным, чтобы не остался висеть.

Учесть выключатель `config.connection_statistics` (`src/db/data_store.py:101`):
при значении `False` таймер не заводить вовсе. Значение по умолчанию сейчас
`False` — то есть счётчик останется выключенным у всех, включая владельца.
Решить и отразить в коде: либо поменять значение по умолчанию на `True`,
либо оставить поле неиспользуемым и убрать его. Держать выключатель, который
по умолчанию прячет только что сделанную работу, смысла нет.

**Шаг 4. Проверить**

Запустить: `uv run pytest tests/test_core_monitor.py -v`
Ожидается: PASS.

**Шаг 5. Коммит**

```bash
git add src/core/monitor.py tests/test_core_monitor.py
git commit -m "feat(core): обновлять счётчик трафика по таймеру"
```

---

### Задача 4: Проверить на живом ядре

Автотесты подменяют вызов процесса, поэтому связку целиком они не проверяют.

**Ограничение:** рабочее подключение владельца не трогать. Поднимать
собственный экземпляр на отдельном каталоге конфигурации и других портах.

**Шаг 1. Запустить приложение на своей конфигурации**

```bash
SP=<каталог scratchpad>
TENGA_CONFIG_DIR=$SP/live-check uv run python gui.py --no-tray &
echo $! > $SP/gui.pid
```

**Шаг 2. Убедиться, что счётчики растут**

Подключиться к тестовому профилю, пропустить трафик и посмотреть, что в
статус-карточке вместо `↑ 0 B ↓ 0 B` появились ненулевые значения и что они
увеличиваются.

**Шаг 3. Погасить только свой процесс**

Гасить строго по записанному PID, предварительно сверив, что это свой
экземпляр, а не приложение владельца:

```bash
PID=$(cat $SP/gui.pid)
cfg=$(tr '\0' '\n' < /proc/$PID/environ | grep "^TENGA_CONFIG_DIR=" | cut -d= -f2)
case "$cfg" in "$SP"/*) kill "$PID" ;; *) echo "ПРОПУСК $PID" ;; esac
```

**Шаг 4. Коммит документации, если что-то уточнилось**

---

## Критерии приёмки

- В статус-карточке при активном подключении видны ненулевые значения
  отправленного и принятого трафика, и они растут по мере использования.
- `uv run pytest` зелёный; новые тесты не требуют ни запущенного ядра, ни сети.
- `uv run ruff check` и `uv run ruff format --check` без замечаний.
- Остановленное ядро, недоступный API и испорченный ответ не роняют интерфейс
  и не сыплют ошибками в лог: счётчик просто показывает нули.
- Свойство `stats_api_url` удалено, поле `connection_statistics` либо работает,
  либо удалено — мёртвых настроек по итогу не остаётся.

## Что за рамками задачи

- Отображение мгновенной скорости (КБ/с) вместо накопленного объёма.
- Статистика по отдельным профилям и её хранение между запусками.
- Страница мониторинга: задача трогает только статус-карточку.
- Переход на gRPC со сгенерированными protobuf-стабами. Вызов CLI укладывается
  в 25 мс, и пока этого достаточно; переходить есть смысл, если опрос станет
  заметно чаще.

## Смежная находка

`~/.config/tenga-proxy/logs/tenga_gui.log` не пополняется со 2026-09-02 22:02,
хотя приложение работает. К счётчику трафика отношения не имеет, но
затрудняет разбор любых жалоб на поведение приложения. Стоит отдельной задачи.
