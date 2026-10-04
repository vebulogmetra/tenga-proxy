# Сетевой слой, этап 4: проверка профилей и устойчивость — план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Мерить задержку группы одним процессом ядра, проверять рабочее
соединение настоящим запросом через сервер профиля, по желанию переключаться на
другой профиль при молчащем сервере и сообщать о новых версиях ядра.

**Architecture:** Вся проверка идёт через HTTP-inbound'ы ядра на `127.0.0.1` с
одноразовыми учётными данными (`src/core/http_probe.py`). Замер задержки — отдельный
модуль `src/core/batch_probe.py`: он сам собирает пробный конфиг из outbound'ов
профилей и сам запускает временный процесс ядра, рабочий билдер
(`src/core/config_builder.py`) и `XrayManager` в нём не участвуют. Проверка
соединения — служебный inbound `health-in` в рабочем конфиге с правилом
`health-in → proxy` первым в списке; его добавляет `ConnectionService`, а не
билдер. Решение о переключении профиля (`src/core/failover.py`) и сравнение
версий ядра (`src/core/core_update.py`) — чистая логика без GTK; интерфейсу
остаются подписка, уведомление и две строки настроек.

**Tech Stack:** Python 3.11, xray-core 26.9.9, `requests`, pytest, ruff,
GTK 4 + libadwaita (задачи 5, 9, 11).

Дорожная карта всех этапов — `2026-10-03-network-parity-roadmap.md`.

**Зависимости.** План предполагает, что **этап 1 выполнен** (ядро 26.9.9,
`src/core/transport_tweaks.py`, закреплённая версия в `core/scripts/install_dev.sh`).
Этапы 2 и 3 писались параллельно с этим на той же базе — состоянии после
этапа 1. Этап 2 меняет обновление подписок (id профилей сохраняются) и кода
этого плана не касается. Этап 3 переписывает блок DNS и правила в
`src/core/config_builder.py`; этот план трогает билдер только в задаче 12
(удаление двух функций в конце файла), а всё остальное держит в отдельных
модулях. Общие с другими этапами файлы: `src/db/config.py`,
`src/db/data_store.py`, `src/ui/dialogs/settings.py`, `src/ui/application.py`,
`src/core/connection.py` — правки в них добавляющие.

---

## Принятые решения

Владелец проекта на вопросы дорожной карты не отвечал — взяты решения по
умолчанию. Каждое можно поменять до начала работ.

1. **Проверка соединения идёт через отдельный inbound `health-in`** — в обоих
   режимах, TUN и системного прокси. Исходное намерение было обойтись без
   него: в TUN запрос приложения и так уходит в туннель. Не вышло, и это
   проверено на настоящем ядре (тест
   `test_check_through_an_ordinary_inbound_misses_a_dead_proxy`): запрос,
   идущий обычным путём, подчиняется правилам маршрутизации. Если проверочный
   адрес попал под direct-правило пользователя — а этап 3 добавляет готовые
   правила «напрямую», — запрос проходит мимо прокси, и мёртвый сервер выглядит
   живым. На таком сигнале нельзя строить автопереключение. Обойти это без
   inbound'а можно только разбором правил вместе с геобазами, что сложнее самого
   inbound'а. Цена решения: один слушающий порт на `127.0.0.1` с паролем на
   сессию и одно правило в начале списка.
2. **Автопереключение (P5) включено в план, по умолчанию выключено**, о
   переключении сообщает тост и уведомление рабочего стола. Задачи 8 и 9
   необязательные: их можно вычеркнуть без последствий для остальных.
3. **Когда кандидатов не осталось, подключение не разрывается.** В Android в
   этом случае VPN отключается. На настольной системе отключение значило бы,
   что трафик молча пойдёт напрямую, поэтому приложение только сообщает.
4. **Обновления ядра (P6) — только сообщение**, бинарник не скачивается и не
   заменяется. Список релизов запрашивается у GitHub раз в три дня при запуске
   и по кнопке; результат виден на странице «О программе», всплывающих
   сообщений нет. В запросе нет данных пользователя: только `Accept` и
   `User-Agent: tenga-proxy`. Пререлиз предлагается, только если установленная
   версия сама новее последнего стабильного релиза. Чтобы оставить проверку
   только по кнопке, достаточно убрать вызов `set_release_fetcher` из `run_app`
   (задача 11).
5. **Ручная проверка («Обновить сейчас») в сеть из главного цикла не ходит.**
   Запрос через мёртвый сервер длится до пяти секунд — окно на это время
   зависло бы. Ручная проверка показывает прошлый вердикт и запускает фоновую;
   новый статус приходит через слушателей состояния прокси.
6. **Замер задержки сохраняет прежний смысл числа:** медиана трёх HEAD-запросов
   к `http://www.google.com/generate_204`, таймаут 3 с. Новое: одновременно
   меряются 16 профилей (было 4), а первый же неудачный запрос без единого
   успешного прекращает замер профиля — мёртвый сервер стоит 3 с, а не 9.

## Что проверено до написания плана

Проверено 2026-10-03 запуском, а не предположено.

1. **Весь код плана прототипирован по TDD** в копии проекта (состояние после
   этапа 1), по коммиту на задачу, и затем применён из этого файла к чистой
   копии. Обычный набор и GTK-тесты проходят, `ruff check` и `ruff format`
   чистые; точные числа — в разделе «Итог воспроизведения» в конце. Фрагменты
   ниже — выгрузка из прототипа, а не набросок.
2. **GTK-тесты выполнялись**, хотя `xvfb-run` на машине нет: через
   Broadway-бэкенд GTK 4 и отдельную шину D-Bus (команда — в «Соглашениях»).
   Экран и шина пользователя не затрагиваются. Под Broadway падают два теста
   геометрии окна (`test_narrow_window_moves_the_switcher_down`,
   `test_default_size_comes_from_saved_geometry`) — они падают и на базе без
   этого плана: бэкенд не меняет размер окна.
3. **Ядро, пакетный конфиг** (26.9.9, только HTTP-inbound'ы на свободных
   портах `127.0.0.1`, без TUN):

   | Что | Результат |
   |---|---|
   | `xray -test` на 1000 outbound'ов | 0,14 с |
   | Запуск с 1500 inbound'ами до готовности всех портов | 0,2 с |
   | Запрос без учётных данных или с неверными | 407 |
   | Запрос через outbound, который не достучался до сервера | 503 |
   | Один плохой outbound в пакете | ядро отвергает конфиг целиком |

4. **Сборка пропускает профили, которые ядро отвергает.** Ключ REALITY не той
   длины (`invalid "password"`), неизвестный `fp`, неверный UUID, неизвестный
   `flow` — `build_core_obj_xray()` ошибки не даёт, а `xray -test` падает. В
   поштучном замере такой профиль получал `-1`; в пакетном без отсева он уронил
   бы всю группу.
5. **Порядок запуска inbound'ов ядро не обещает.** Первая версия прототипа
   ждала готовности первого и последнего порта и изредка записывала живому
   профилю `-1`: проба попадала в ещё закрытый порт. Теперь ожидается каждый
   порт.
6. **Нынешний поштучный замер мешает рабочему подключению.** `XrayManager`
   добавляет в любой конфиг Stats API на `127.0.0.1:10085`. Ядро открывает порты
   с `SO_REUSEPORT`, поэтому пробный процесс не падает на занятом порту, а делит
   его с рабочим: при проверке запрос статистики работающего приложения пришёл в
   пробный процесс. К тому же `XrayManager.start()` всегда ждёт 2 с — это 2 с на
   каждый профиль. Пакетный замер запускает ядро сам, без `XrayManager`.
7. **Ответ GitHub** (`/repos/XTLS/Xray-core/releases?per_page=30`) на
   2026-10-03: новейший пререлиз `v26.9.30`, новейший стабильный `v26.3.27`;
   поля `tag_name`, `prerelease`, `draft` на месте.

**Не проверено** (в чек-листе ручной проверки, задача 13):

- замер на живых серверах и сравнение времени со старым;
- проверка соединения и автопереключение в бою, в том числе в режиме TUN:
  настоящему ядру TUN-конфиги не давались — на машине разработчика интерфейс
  `xray0` занят рабочим подключением;
- показ уведомления рабочего стола (в изолированной шине его некому показать);
- `Gio.NetworkMonitor` как признак «сети нет» при поднятом TUN.

## Сознательно не делаем

- **Замер мимо действующего туннеля.** В режиме TUN при активном подключении
  пробный процесс ядра ходит к серверам через `xray0`, то есть через текущий
  профиль: числа завышены на его задержку, а при мёртвом текущем профиле все
  получают `-1`. Так было и до этого плана. Лечится привязкой пробных
  outbound'ов к физическому интерфейсу (`sockopt.interface`); пробный запуск
  показал, что привязка без привилегий работает, но прямой путь на машине
  разработчика нестабилен, и довести проверку до конца не удалось. Отдельная
  задача после этапа.
- Очередь замеров нескольких групп и кнопка «Остановить» (в Android есть).
- Несколько проверочных адресов на профиль.
- Показ ошибки монитора на карточке состояния и в трее: статус по-прежнему
  виден на странице «Мониторинг».
- Скачивание и замена ядра.

## Соглашения

- Рабочая ветка: `feature/network-phase4` от `develop`, после слияния этапов
  1–3.
- Тесты: `uv run pytest <путь> -q`. Полный набор: `uv run pytest -q`.
- GTK-тесты: `make test-gtk`. Без `xvfb-run` их можно запускать, не трогая
  экран:

  ```bash
  gtk4-broadwayd :7 &
  env -u DISPLAY -u WAYLAND_DISPLAY GDK_BACKEND=broadway BROADWAY_DISPLAY=:7 \
      GDK_DEBUG=no-portals ADW_DISABLE_PORTAL=1 \
      dbus-run-session -- uv run pytest -m gtk <путь> -p no:cacheprovider --no-cov -q
  kill %1
  ```

  Ниже такие запуски записаны короче: `uv run pytest -m gtk <путь> -q`.
- Перед каждым коммитом: `python cli.py lint-all`.
- Сообщения коммитов — как в истории: `feat(core): …`, `feat(ui): …`, по-русски.
- Фрагменты `diff` сняты с состояния после этапа 1. К моменту исполнения файлы
  изменят этапы 2 и 3, поэтому **ориентир — содержимое, а не номера строк**: имя
  функции в заголовке фрагмента и строки контекста. Если контекст не совпал —
  найди то же место по смыслу и внеси правку руками.
- Настоящему ядру в тестах даются только HTTP-inbound'ы на `127.0.0.1`.
  **Никаких TUN-конфигов**: `xray -test` на них трогает интерфейсы.
- Учётные данные inbound'ов не пишутся ни в журнал, ни на диск.

---

### Task 0: Сверка с кодом

План написан до исполнения этапов 1–3. Прежде чем что-либо менять, убедись, что
опорные места на месте.

**Step 1: Создать ветку**

```bash
git switch develop
git switch -c feature/network-phase4
```

**Step 2: Проверить предпосылки этапа 1**

```bash
core/bin/xray version | head -1
grep -n 'XRAY_VERSION=' core/scripts/install_dev.sh
ls src/core/transport_tweaks.py
```

Expected: `Xray 26.9.9`, строка `XRAY_VERSION="26.9.9"`, файл существует. Если
версия ядра другая — поправь `PINNED_CORE_VERSION` в задаче 10 на ту, что
закреплена в скрипте.

**Step 3: Найти опорные места**

```bash
grep -n "_default_latency_probe\|LatencyRunner(" src/ui/application.py
grep -n "def _check_proxy_status\|def _run_check\|def check_now\|def _check_connections" src/core/monitor.py
grep -n "build_session_config(\|_write_debug_config(" src/core/connection.py
grep -n "class MonitoringSettings" -A 6 src/db/config.py
grep -n "def build_latency_probe_config\|def reserve_latency_port_pair" src/core/config_builder.py
grep -n "def test_delay" src/core/xray_manager.py
```

Expected: всё находится. `build_session_config(` в `connection.py` вызывается в
двух местах — `connect` и `reload_config`.

**Step 4: Свериться с этапами 2 и 3**

- Этап 3 мог добавить проверку готового конфига (`src/core/config_validator.py`).
  Если она вызывается в `ConnectionService`, inbound `health-in` (задача 6)
  должен добавляться **до** неё, и она должна его принимать: это HTTP-inbound на
  `127.0.0.1`, а его правило ведёт в `outbounds[0]`.
- Этап 3 мог добавить правило перехвата DNS «первым в списке». Правило
  `health-in → proxy` тоже встаёт первым; взаимный порядок этих двух не важен —
  у них разные `inboundTag`.
- Этап 2 мог использовать для загрузки подписок локальный inbound. После
  задачи 6 готовый вход «всегда через прокси» — `context.proxy_state.health_endpoint`.

**Step 5: Убедиться, что набор зелёный**

Run: `uv run pytest -q`
Expected: PASS — все тесты проходят. Запиши число: с ним сверяются итоги.

---

### Task 1: HTTP-проба через inbound с учётными данными

Общий кирпич для замера задержки и для проверки соединения: описание входа
(порт на `127.0.0.1` + логин и пароль), сборка такого inbound'а и сам замер.

Что важно в замере:

- `requests.Session` с `trust_env = False`: системный прокси и переменные
  окружения не должны увести запрос мимо проверяемого inbound'а.
- 407 — отказ: его отдаёт сам inbound при неверных учётных данных. В старом
  замере любой ответ 2xx–4xx считался успехом.
- 5xx — отказ: ядро отвечает 503, когда не достучалось до сервера профиля.
- В журнал попадает только имя исключения: в тексте ошибки `requests` бывает
  адрес прокси вместе с паролем.

**Files:**
- Create: `src/core/http_probe.py`
- Test: `tests/test_core_http_probe.py`

**Step 1: Написать падающие тесты**

Создать `tests/test_core_http_probe.py`:

```python
"""HTTP-проба через локальный inbound ядра: учётные данные и замер."""

from __future__ import annotations

import pytest
import requests

from src.core import http_probe
from src.core.http_probe import (
    ProbeCredentials,
    ProbeEndpoint,
    build_probe_inbound,
    measure_latency,
)

ENDPOINT = ProbeEndpoint(port=41001, credentials=ProbeCredentials("user", "p@ss/word"))


class FakeSession:
    """Отвечает по сценарию: код ответа или исключение на каждый запрос."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[tuple[str, dict]] = []
        self.trust_env = True

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def head(self, url, **kwargs):
        self.calls.append((url, kwargs))
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        response = requests.Response()
        response.status_code = step
        return response


@pytest.fixture
def session(monkeypatch):
    def install(script):
        fake = FakeSession(script)
        monkeypatch.setattr(http_probe.requests, "Session", lambda: fake)
        return fake

    return install


def test_generated_credentials_are_unique_and_non_empty():
    first = ProbeCredentials.generate()
    second = ProbeCredentials.generate()

    assert first.user and first.password
    assert first != second


def test_proxy_url_escapes_credentials():
    assert ENDPOINT.proxy_url == "http://user:p%40ss%2Fword@127.0.0.1:41001"


def test_probe_inbound_requires_accounts_and_listens_on_loopback():
    inbound = build_probe_inbound("probe-in-1", ENDPOINT)

    assert inbound == {
        "tag": "probe-in-1",
        "listen": "127.0.0.1",
        "port": 41001,
        "protocol": "http",
        "settings": {"accounts": [{"user": "user", "pass": "p@ss/word"}]},
    }


@pytest.mark.parametrize("credentials", [ProbeCredentials("", "x"), ProbeCredentials("x", "")])
def test_probe_inbound_is_not_built_without_credentials(credentials):
    with pytest.raises(ValueError, match="учётных данных"):
        build_probe_inbound("probe-in-1", ProbeEndpoint(port=41001, credentials=credentials))


def test_measure_latency_goes_through_the_endpoint_ignoring_environment(session):
    fake = session([204])

    latency = measure_latency(ENDPOINT, "http://example.com/generate_204", probes=1)

    assert latency >= 0
    assert fake.trust_env is False
    url, kwargs = fake.calls[0]
    assert url.startswith("http://example.com/generate_204?cb=")
    assert kwargs["proxies"] == {"http": ENDPOINT.proxy_url, "https": ENDPOINT.proxy_url}
    assert kwargs["allow_redirects"] is False


def test_measure_latency_appends_cache_buster_to_existing_query(session):
    fake = session([204])

    measure_latency(ENDPOINT, "http://example.com/?a=1", probes=1)

    assert fake.calls[0][0].startswith("http://example.com/?a=1&cb=")


def test_measure_latency_returns_median_of_successful_probes(session, monkeypatch):
    session([204, 204, 204])
    # Три замера: 10, 500 и 20 мс. Медиана отбрасывает выброс.
    ticks = iter([0, 10, 0, 500, 0, 20])
    monkeypatch.setattr(http_probe.time, "perf_counter_ns", lambda: next(ticks) * 1_000_000)

    assert measure_latency(ENDPOINT, "http://example.com/", probes=3) == 20


@pytest.mark.parametrize("status", [407, 500, 502, 503])
def test_measure_latency_treats_proxy_errors_as_failure(session, status):
    # 407 — неверные учётные данные inbound'а, 5xx — ядро не достучалось до сервера.
    session([status])

    assert measure_latency(ENDPOINT, "http://example.com/", probes=1) == -1


def test_measure_latency_accepts_client_errors_from_the_target(session):
    # 403 от целевого сайта означает, что туннель работает.
    session([403])

    assert measure_latency(ENDPOINT, "http://example.com/", probes=1) >= 0


def test_measure_latency_gives_up_after_the_first_failed_probe(session):
    # Мёртвый сервер не должен съедать таймаут трижды.
    fake = session([requests.exceptions.ConnectTimeout("timeout"), 204, 204])

    assert measure_latency(ENDPOINT, "http://example.com/", probes=3) == -1
    assert len(fake.calls) == 1


def test_measure_latency_keeps_earlier_samples_when_a_later_probe_fails(session):
    fake = session([204, requests.exceptions.ReadTimeout("timeout"), 204])

    assert measure_latency(ENDPOINT, "http://example.com/", probes=3) >= 0
    assert len(fake.calls) == 3
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_http_probe.py -q`
Expected: FAIL — ошибка сбора, `cannot import name 'http_probe' from 'src.core'`.

**Step 3: Реализовать**

Создать `src/core/http_probe.py`:

```python
"""HTTP-проба через локальный inbound ядра.

Общая для пакетного замера задержки и для проверки рабочего соединения: оба
ходят через HTTP-inbound на 127.0.0.1, закрытый одноразовыми учётными данными.
Без них любой процесс на машине мог бы пользоваться проверяемыми профилями.
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass
from statistics import median
from typing import Any
from urllib.parse import quote

import requests

logger = logging.getLogger("tenga.core.http_probe")

LOOPBACK = "127.0.0.1"
PROXY_AUTH_REQUIRED = 407


@dataclass(frozen=True)
class ProbeCredentials:
    """Логин и пароль HTTP-inbound'а, живут одну сессию ядра."""

    user: str
    password: str

    @classmethod
    def generate(cls) -> ProbeCredentials:
        return cls(user=secrets.token_hex(8), password=secrets.token_urlsafe(24))


@dataclass(frozen=True)
class ProbeEndpoint:
    """Куда стучаться пробе: порт на loopback и учётные данные."""

    port: int
    credentials: ProbeCredentials
    host: str = LOOPBACK

    @property
    def proxy_url(self) -> str:
        user = quote(self.credentials.user, safe="")
        password = quote(self.credentials.password, safe="")
        return f"http://{user}:{password}@{self.host}:{self.port}"


def build_probe_inbound(tag: str, endpoint: ProbeEndpoint) -> dict[str, Any]:
    """HTTP-inbound для пробы. Без учётных данных не создаётся."""
    credentials = endpoint.credentials
    if not credentials.user or not credentials.password:
        raise ValueError(f"inbound {tag} не создаётся без учётных данных")

    return {
        "tag": tag,
        "listen": endpoint.host,
        "port": endpoint.port,
        "protocol": "http",
        "settings": {
            "accounts": [{"user": credentials.user, "pass": credentials.password}],
        },
    }


def _is_success(status_code: int) -> bool:
    # 4xx отдаёт целевой сайт — значит, туннель до него дошёл. Исключение — 407:
    # его отдаёт сам inbound при неверных учётных данных. 5xx ядро возвращает,
    # когда не достучалось до сервера профиля.
    return 200 <= status_code < 500 and status_code != PROXY_AUTH_REQUIRED


def measure_latency(
    endpoint: ProbeEndpoint,
    url: str,
    *,
    timeout: float = 3.0,
    probes: int = 3,
) -> int:
    """Медиана задержки HEAD-запросов через inbound в миллисекундах, -1 при отказе.

    Первый же неудачный запрос без единого успешного прекращает замер: мёртвый
    сервер иначе съедал бы таймаут `probes` раз.
    """
    proxies = {"http": endpoint.proxy_url, "https": endpoint.proxy_url}
    samples: list[int] = []

    with requests.Session() as session:
        # Переменные окружения и системный прокси не должны увести запрос мимо
        # проверяемого inbound'а.
        session.trust_env = False

        for index in range(max(1, probes)):
            started_ns = time.perf_counter_ns()
            separator = "&" if "?" in url else "?"
            probe_url = f"{url}{separator}cb={started_ns}_{index}"
            try:
                response = session.head(
                    probe_url,
                    proxies=proxies,
                    timeout=timeout,
                    allow_redirects=False,
                )
            except requests.exceptions.RequestException as e:
                logger.debug("Probe via port %s failed: %s", endpoint.port, type(e).__name__)
                if not samples:
                    return -1
                continue

            elapsed_ms = (time.perf_counter_ns() - started_ns) // 1_000_000
            if _is_success(response.status_code):
                samples.append(int(elapsed_ms))
            elif not samples:
                logger.debug("Probe via port %s got status %s", endpoint.port, response.status_code)
                return -1

    return int(median(samples)) if samples else -1
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_http_probe.py -q`
Expected: PASS — `15 passed`.

**Step 5: Commit**

```bash
git add src/core/http_probe.py tests/test_core_http_probe.py
git commit -m "feat(core): HTTP-проба через inbound с одноразовыми учётными данными"
```

---

### Task 2: Пакетный пробный конфиг

Один конфиг на весь набор: у профиля номер N свой inbound `probe-in-N`, свой
outbound `proxy-N` и правило `inboundTag: [probe-in-N] → proxy-N`. Ни DNS, ни
пользовательских правил, ни TUN в нём нет — замеру они не нужны, а рабочий
билдер меняет этап 3.

Outbound профиля строится так же, как в рабочей сессии: `build_core_obj_xray()`
плюс `apply_transport_tweaks` (фрагментация и mux из этапа 1) — иначе замер и
подключение расходились бы. Профиль с ошибкой сборки даёт `None` и в пакет не
попадает.

Inbound без учётных данных не создаётся: `build_probe_inbound` бросает
`ValueError` (приёмка P3).

**Files:**
- Create: `src/core/batch_probe.py`
- Test: `tests/test_core_batch_probe.py`

**Step 1: Написать падающие тесты**

Создать `tests/test_core_batch_probe.py`:

```python
"""Пакетный замер задержки: один процесс ядра на весь набор профилей."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.core.batch_probe import (
    ProbeTarget,
    build_batch_probe_config,
    build_probe_outbound,
    core_accepts,
)
from src.core.http_probe import ProbeCredentials
from src.db.config import TlsFragmentSettings
from src.db.data_store import DataStore
from src.db.profiles import ProfileEntry
from src.fmt import parse_link

XRAY = Path("core/bin/xray")
needs_xray = pytest.mark.skipif(
    not XRAY.exists() or not shutil.which(str(XRAY)),
    reason="бинарник xray недоступен (core/bin/xray)",
)

UUID = "11111111-1111-1111-1111-111111111111"
VLESS_WS = f"vless://{UUID}@127.0.0.1:443?type=ws&path=%2Fws&security=tls&sni=a.example.com#W"
TROJAN = "trojan://pass123@127.0.0.1:443?type=tcp&sni=a.example.com#TR"
HYSTERIA2 = "hysteria2://pass123@127.0.0.1:8443?sni=a.example.com#H"
# Транспорт h2 ядро удалило: bean сам сообщает об ошибке сборки.
VLESS_H2 = f"vless://{UUID}@127.0.0.1:443?type=h2&security=tls&sni=a.example.com#H2"
CREDENTIALS = ProbeCredentials("probe", "secret")


def entry(profile_id: int, link: str) -> ProfileEntry:
    bean = parse_link(link)
    assert bean is not None, link
    return ProfileEntry(id=profile_id, group_id=0, bean=bean)


def target(profile_id: int, link: str) -> ProbeTarget:
    outbound = build_probe_outbound(entry(profile_id, link), DataStore())
    assert outbound is not None, link
    return ProbeTarget(profile_id, outbound)


# --- outbound одного профиля ---


def test_probe_outbound_applies_the_same_tweaks_as_a_session():
    settings = DataStore()
    settings.tls_fragment = TlsFragmentSettings(enabled=True)

    outbound = build_probe_outbound(entry(1, VLESS_WS), settings)

    masks = outbound["streamSettings"]["finalmask"]["tcp"]
    assert masks[0]["type"] == "fragment"


def test_probe_outbound_is_none_for_a_profile_with_a_build_error():
    assert build_probe_outbound(entry(1, VLESS_H2), DataStore()) is None


def test_probe_outbound_is_none_when_the_bean_raises():
    class Broken:
        def build_core_obj_xray(self):
            raise RuntimeError("boom")

    profile = ProfileEntry(id=1, group_id=0, bean=Broken())  # type: ignore[arg-type]

    assert build_probe_outbound(profile, DataStore()) is None


# --- пакетный конфиг ---


def test_batch_config_pairs_every_inbound_with_its_own_outbound():
    targets = [target(7, VLESS_WS), target(9, TROJAN)]

    config = build_batch_probe_config(targets, [41001, 41002], CREDENTIALS)

    assert [i["tag"] for i in config["inbounds"]] == ["probe-in-1", "probe-in-2"]
    assert [i["port"] for i in config["inbounds"]] == [41001, 41002]
    assert [o["tag"] for o in config["outbounds"]] == ["proxy-1", "proxy-2"]
    assert [o["protocol"] for o in config["outbounds"]] == ["vless", "trojan"]
    assert config["routing"]["rules"] == [
        {"type": "field", "inboundTag": ["probe-in-1"], "outboundTag": "proxy-1"},
        {"type": "field", "inboundTag": ["probe-in-2"], "outboundTag": "proxy-2"},
    ]


def test_every_probe_inbound_is_an_authenticated_http_proxy_on_loopback():
    targets = [target(1, VLESS_WS), target(2, TROJAN), target(3, HYSTERIA2)]

    config = build_batch_probe_config(targets, [41001, 41002, 41003], CREDENTIALS)

    for inbound in config["inbounds"]:
        assert inbound["protocol"] == "http"
        assert inbound["listen"] == "127.0.0.1"
        assert inbound["settings"]["accounts"] == [{"user": "probe", "pass": "secret"}]


def test_batch_config_is_not_built_without_credentials():
    with pytest.raises(ValueError, match="учётных данных"):
        build_batch_probe_config([target(1, TROJAN)], [41001], ProbeCredentials("", ""))


def test_batch_config_does_not_touch_the_source_outbounds():
    source = target(1, TROJAN)
    before = dict(source.outbound)

    build_batch_probe_config([source], [41001], CREDENTIALS)

    assert source.outbound == before


def test_batch_config_requires_a_port_for_every_target():
    with pytest.raises(ValueError, match="портов"):
        build_batch_probe_config([target(1, TROJAN), target(2, TROJAN)], [41001], CREDENTIALS)


# --- схему знает только ядро ---


@needs_xray
def test_core_accepts_a_batch_of_mixed_protocols():
    targets = [target(1, VLESS_WS), target(2, TROJAN), target(3, HYSTERIA2)]
    config = build_batch_probe_config(targets, [41001, 41002, 41003], CREDENTIALS)

    assert core_accepts(str(XRAY), config) is True


@needs_xray
def test_core_rejects_a_batch_with_an_unknown_protocol():
    broken = ProbeTarget(1, {"protocol": "no-such-protocol", "settings": {}})
    config = build_batch_probe_config([broken], [41001], CREDENTIALS)

    assert core_accepts(str(XRAY), config) is False
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_batch_probe.py -q`
Expected: FAIL — ошибка сбора, `No module named 'src.core.batch_probe'`.

**Step 3: Реализовать**

Создать `src/core/batch_probe.py`:

```python
"""Пакетный замер задержки: один процесс ядра на весь набор профилей.

У каждого профиля свой HTTP-inbound `probe-in-N` на 127.0.0.1 и свой outbound
`proxy-N`; правило по `inboundTag` связывает пару. Рабочий билдер конфигурации
здесь не участвует: замеру не нужны ни пользовательские правила, ни DNS, ни TUN.
"""

from __future__ import annotations

import copy
import json
import logging
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.core.http_probe import ProbeCredentials, ProbeEndpoint, build_probe_inbound
from src.core.transport_tweaks import apply_transport_tweaks

if TYPE_CHECKING:
    from src.db.data_store import DataStore
    from src.db.profiles import ProfileEntry

logger = logging.getLogger("tenga.core.batch_probe")

PROBE_INBOUND_PREFIX = "probe-in-"
PROBE_OUTBOUND_PREFIX = "proxy-"
CORE_TEST_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class ProbeTarget:
    """Профиль, готовый к замеру: его id и собранный outbound."""

    profile_id: int
    outbound: dict[str, Any]


def build_probe_outbound(profile: ProfileEntry, settings: DataStore) -> dict[str, Any] | None:
    """Outbound профиля с теми же надстройками транспорта, что и в рабочей сессии.

    None — профиль собрать нельзя: в пакет он не попадает и сразу получает -1.
    """
    try:
        result = profile.bean.build_core_obj_xray()
    except Exception as e:
        logger.warning("Profile %s cannot be built for probing: %s", profile.id, e)
        return None

    if result.get("error") or not result.get("outbound"):
        logger.info("Profile %s skipped by probe: %s", profile.id, result.get("error"))
        return None

    outbound = result["outbound"]
    apply_transport_tweaks(outbound, settings)
    return outbound


def build_batch_probe_config(
    targets: Sequence[ProbeTarget],
    ports: Sequence[int],
    credentials: ProbeCredentials,
    *,
    log_level: str = "warning",
) -> dict[str, Any]:
    """Конфиг ядра для замера: N inbound'ов, N outbound'ов, N правил."""
    if len(ports) != len(targets):
        raise ValueError(f"портов {len(ports)}, а профилей {len(targets)}")

    inbounds: list[dict[str, Any]] = []
    outbounds: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []

    for index, (target, port) in enumerate(zip(targets, ports, strict=True), start=1):
        inbound_tag = f"{PROBE_INBOUND_PREFIX}{index}"
        outbound_tag = f"{PROBE_OUTBOUND_PREFIX}{index}"

        inbounds.append(build_probe_inbound(inbound_tag, ProbeEndpoint(port, credentials)))

        outbound = copy.deepcopy(target.outbound)
        outbound["tag"] = outbound_tag
        outbounds.append(outbound)

        rules.append({"type": "field", "inboundTag": [inbound_tag], "outboundTag": outbound_tag})

    return {
        "log": {"loglevel": log_level},
        "inbounds": inbounds,
        "outbounds": outbounds,
        "routing": {"rules": rules},
    }


def _write_config(config: dict[str, Any]) -> Path:
    # NamedTemporaryFile создаёт файл с правами 0600: в конфиге лежат ключи
    # профилей и учётные данные inbound'ов.
    with tempfile.NamedTemporaryFile(
        mode="w", prefix="tenga-probe-", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(config, f, ensure_ascii=False)
        return Path(f.name)


def core_accepts(binary_path: str, config: dict[str, Any]) -> bool:
    """Спросить у ядра, примет ли оно конфиг (`xray -test`). Портов не занимает."""
    path = _write_config(config)
    try:
        result = subprocess.run(
            [binary_path, "-test", "-config", str(path)],
            capture_output=True,
            timeout=CORE_TEST_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("Core could not check the probe config: %s", e)
        return False
    finally:
        path.unlink(missing_ok=True)

    return result.returncode == 0
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_batch_probe.py -q`
Expected: PASS — `10 passed`. Два последних теста спрашивают настоящее ядро.

**Step 5: Commit**

```bash
git add src/core/batch_probe.py tests/test_core_batch_probe.py
git commit -m "feat(core): пакетный конфиг замера с учётными данными на inbound'ах"
```

---

### Task 3: Отсев профилей, которые отвергает ядро

Ядро отвергает конфиг целиком из-за одного outbound'а, а сборка такие профили
пропускает (см. «Что проверено», пункт 4). Без отсева пакетный замер хуже
поштучного: один битый профиль из подписки оставил бы без результата всю
группу.

`split_accepted` спрашивает у ядра (`xray -test`) весь пакет; при отказе делит
его пополам и повторяет, пока виновные не останутся по одному. На один плохой
профиль уходит около 2·log2(N) проверок: для 64 профилей — 13, а не 64.
Проверка портов не открывает и занимает сотые доли секунды.

Имя тега из сообщения ядра (`failed to build outbound config with tag proxy-7`)
намеренно не разбирается: формат сообщений меняется от версии к версии, а
деление пополам от него не зависит.

**Files:**
- Modify: `src/core/batch_probe.py`
- Test: `tests/test_core_batch_probe.py`

**Step 1: Написать падающие тесты**

Изменить `tests/test_core_batch_probe.py`:

```diff
--- a/tests/test_core_batch_probe.py
+++ b/tests/test_core_batch_probe.py
@@ -12,6 +12,7 @@ from src.core.batch_probe import (
     build_batch_probe_config,
     build_probe_outbound,
     core_accepts,
+    split_accepted,
 )
 from src.core.http_probe import ProbeCredentials
 from src.db.config import TlsFragmentSettings
@@ -31,6 +32,13 @@ TROJAN = "trojan://pass123@127.0.0.1:443?type=tcp&sni=a.example.com#TR"
 HYSTERIA2 = "hysteria2://pass123@127.0.0.1:8443?sni=a.example.com#H"
 # Транспорт h2 ядро удалило: bean сам сообщает об ошибке сборки.
 VLESS_H2 = f"vless://{UUID}@127.0.0.1:443?type=h2&security=tls&sni=a.example.com#H2"
+# Сборку проходят, а ядро отвергает: короткий ключ REALITY и неизвестный fingerprint.
+VLESS_BAD_REALITY = (
+    f"vless://{UUID}@127.0.0.1:443?type=tcp&security=reality&pbk=abc&sni=a.example.com#BR"
+)
+VLESS_BAD_FINGERPRINT = (
+    f"vless://{UUID}@127.0.0.1:443?type=tcp&security=tls&sni=a.example.com&fp=nosuchfp#BF"
+)
 CREDENTIALS = ProbeCredentials("probe", "secret")
 
 
@@ -138,3 +146,88 @@ def test_core_rejects_a_batch_with_an_unknown_protocol():
     config = build_batch_probe_config([broken], [41001], CREDENTIALS)
 
     assert core_accepts(str(XRAY), config) is False
+
+
+# --- отсев: один плохой профиль не должен ронять весь пакет ---
+
+
+def fake_accepts(bad_ids: set[int], calls: list[int] | None = None):
+    def accepts(chunk) -> bool:
+        if calls is not None:
+            calls.append(len(chunk))
+        return not any(t.profile_id in bad_ids for t in chunk)
+
+    return accepts
+
+
+def numbered_targets(count: int) -> list[ProbeTarget]:
+    return [ProbeTarget(i, {"protocol": "freedom"}) for i in range(1, count + 1)]
+
+
+def test_split_accepted_keeps_everything_when_the_core_agrees():
+    targets = numbered_targets(8)
+    calls: list[int] = []
+
+    accepted, rejected = split_accepted(targets, fake_accepts(set(), calls))
+
+    assert accepted == targets
+    assert rejected == []
+    assert calls == [8]
+
+
+def test_split_accepted_isolates_the_rejected_profiles_and_keeps_order():
+    targets = numbered_targets(9)
+
+    accepted, rejected = split_accepted(targets, fake_accepts({3, 8}))
+
+    assert [t.profile_id for t in accepted] == [1, 2, 4, 5, 6, 7, 9]
+    assert [t.profile_id for t in rejected] == [3, 8]
+
+
+def test_split_accepted_halves_instead_of_checking_one_by_one():
+    targets = numbered_targets(64)
+    calls: list[int] = []
+
+    split_accepted(targets, fake_accepts({40}, calls))
+
+    # 1 проверка целого пакета и по две на каждом из 6 уровней деления.
+    assert len(calls) == 13
+
+
+def test_split_accepted_handles_an_empty_and_a_fully_rejected_batch():
+    assert split_accepted([], fake_accepts(set())) == ([], [])
+
+    targets = numbered_targets(3)
+    accepted, rejected = split_accepted(targets, fake_accepts({1, 2, 3}))
+    assert accepted == []
+    assert rejected == targets
+
+
+@needs_xray
+@pytest.mark.parametrize("bad_link", [VLESS_BAD_REALITY, VLESS_BAD_FINGERPRINT])
+def test_core_rejects_the_whole_batch_because_of_one_profile(bad_link):
+    """Причина отсева: такой профиль проходит сборку, а ядро из-за него не стартует."""
+    targets = [target(1, VLESS_WS), target(2, bad_link), target(3, TROJAN)]
+    config = build_batch_probe_config(targets, [41001, 41002, 41003], CREDENTIALS)
+
+    assert core_accepts(str(XRAY), config) is False
+
+
+@needs_xray
+def test_split_accepted_finds_what_the_real_core_rejects():
+    targets = [
+        target(1, VLESS_WS),
+        target(2, VLESS_BAD_REALITY),
+        target(3, TROJAN),
+        target(4, VLESS_BAD_FINGERPRINT),
+        target(5, HYSTERIA2),
+    ]
+
+    def accepts(chunk) -> bool:
+        ports = list(range(41001, 41001 + len(chunk)))
+        return core_accepts(str(XRAY), build_batch_probe_config(chunk, ports, CREDENTIALS))
+
+    accepted, rejected = split_accepted(targets, accepts)
+
+    assert [t.profile_id for t in accepted] == [1, 3, 5]
+    assert [t.profile_id for t in rejected] == [2, 4]
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_batch_probe.py -q`
Expected: FAIL — ошибка сбора, `cannot import name 'split_accepted'`.

**Step 3: Реализовать**

Изменить `src/core/batch_probe.py`:

```diff
--- a/src/core/batch_probe.py
+++ b/src/core/batch_probe.py
@@ -12,7 +12,7 @@ import json
 import logging
 import subprocess
 import tempfile
-from collections.abc import Sequence
+from collections.abc import Callable, Sequence
 from dataclasses import dataclass
 from pathlib import Path
 from typing import TYPE_CHECKING, Any
@@ -121,3 +121,28 @@ def core_accepts(binary_path: str, config: dict[str, Any]) -> bool:
         path.unlink(missing_ok=True)
 
     return result.returncode == 0
+
+
+def split_accepted(
+    targets: Sequence[ProbeTarget],
+    accepts: Callable[[Sequence[ProbeTarget]], bool],
+) -> tuple[list[ProbeTarget], list[ProbeTarget]]:
+    """Разделить профили на принятые ядром и отвергнутые, сохраняя порядок.
+
+    Ядро отвергает конфиг целиком из-за одного outbound'а, а сборка такие
+    профили пропускает: ключ REALITY не той длины, неизвестный fingerprint,
+    неверный UUID. Пакет делится пополам, пока виновные не останутся по одному:
+    на один плохой профиль уходит около 2·log2(N) проверок вместо N.
+    """
+    batch = list(targets)
+    if not batch:
+        return [], []
+    if accepts(batch):
+        return batch, []
+    if len(batch) == 1:
+        return [], batch
+
+    middle = len(batch) // 2
+    left_accepted, left_rejected = split_accepted(batch[:middle], accepts)
+    right_accepted, right_rejected = split_accepted(batch[middle:], accepts)
+    return left_accepted + right_accepted, left_rejected + right_rejected
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_batch_probe.py -q`
Expected: PASS — `17 passed`.

**Step 5: Commit**

```bash
git add src/core/batch_probe.py tests/test_core_batch_probe.py
git commit -m "feat(core): отсев профилей, которые ядро отвергает, делением пакета пополам"
```

---

### Task 4: Запуск ядра и потоковый замер

Последовательность `probe_targets`:

1. одноразовые учётные данные на весь пакет;
2. отсев через `split_accepted` — отвергнутые сразу получают `-1`;
3. свободные порты (`reserve_ports` держит все сокеты открытыми до конца,
   поэтому порты разные);
4. запуск ядра (`BatchCore`) и ожидание **каждого** порта;
5. замер в пуле из 16 потоков, результат каждого профиля уходит в `on_result`
   сразу по готовности;
6. если ядро не запустилось — до трёх попыток с новыми портами, затем `-1` всем.

`BatchCore` — не `XrayManager`: тот добавляет Stats API на общем порту и ждёт
2 с на старте (см. «Что проверено», пункт 6). Вывод ядра уходит во временный
файл, а не в pipe: непрочитанный pipe переполнился бы предупреждениями о мёртвых
серверах и остановил бы ядро. Конфиг пишется во временный файл с правами 0600 и
удаляется при выходе.

Тесты с настоящим ядром не ходят в интернет: outbound — `freedom` или
`blackhole`, цель — локальный HTTP-сервер.

**Files:**
- Modify: `src/core/batch_probe.py`
- Test: `tests/test_core_batch_probe.py`

**Step 1: Написать падающие тесты**

Изменить `tests/test_core_batch_probe.py`:

```diff
--- a/tests/test_core_batch_probe.py
+++ b/tests/test_core_batch_probe.py
@@ -2,16 +2,27 @@
 
 from __future__ import annotations
 
+import http.server
 import shutil
+import socket
+import threading
+import time
 from pathlib import Path
 
 import pytest
+import requests
 
+from src.core import batch_probe
 from src.core.batch_probe import (
+    BatchCore,
     ProbeTarget,
     build_batch_probe_config,
     build_probe_outbound,
     core_accepts,
+    measure_targets,
+    probe_profiles,
+    probe_targets,
+    reserve_ports,
     split_accepted,
 )
 from src.core.http_probe import ProbeCredentials
@@ -231,3 +242,228 @@ def test_split_accepted_finds_what_the_real_core_rejects():
 
     assert [t.profile_id for t in accepted] == [1, 3, 5]
     assert [t.profile_id for t in rejected] == [2, 4]
+
+
+# --- запуск ядра и замер ---
+
+FREEDOM = {"protocol": "freedom"}
+BLACKHOLE = {"protocol": "blackhole"}
+
+
+class _Site(http.server.BaseHTTPRequestHandler):
+    def do_HEAD(self):
+        self.send_response(204)
+        self.end_headers()
+
+    def log_message(self, *_args):
+        pass
+
+
+@pytest.fixture
+def local_site():
+    """Локальный сайт вместо интернета: замер идёт ядро → freedom → 127.0.0.1."""
+    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
+    thread = threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True)
+    thread.start()
+    yield f"http://127.0.0.1:{server.server_address[1]}/generate_204"
+    server.shutdown()
+    server.server_close()
+
+
+@pytest.fixture
+def core_starts(monkeypatch):
+    """Сколько раз запускался процесс ядра (проверки `-test` не в счёт)."""
+    starts: list[list[str]] = []
+    real_popen = batch_probe.subprocess.Popen
+
+    def counting_popen(args, **kwargs):
+        # subprocess.run тоже идёт через Popen: проверки `-test` отсеиваем.
+        if "run" in args:
+            starts.append(list(args))
+        return real_popen(args, **kwargs)
+
+    monkeypatch.setattr(batch_probe.subprocess, "Popen", counting_popen)
+    return starts
+
+
+def test_reserve_ports_returns_distinct_free_ports():
+    ports = reserve_ports(20)
+
+    assert len(set(ports)) == 20
+    for port in ports:
+        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
+            sock.bind(("127.0.0.1", port))
+
+
+def test_measure_targets_reports_results_as_they_arrive(monkeypatch):
+    delays = {41001: 0.3, 41002: 0.0, 41003: 0.1}
+
+    def fake_measure(endpoint, url, **_kwargs):
+        time.sleep(delays[endpoint.port])
+        return endpoint.port
+
+    monkeypatch.setattr(batch_probe, "measure_latency", fake_measure)
+    order: list[int] = []
+
+    measure_targets(
+        numbered_targets(3),
+        [41001, 41002, 41003],
+        CREDENTIALS,
+        url="http://example.com/",
+        on_result=lambda profile_id, _latency: order.append(profile_id),
+    )
+
+    assert order == [2, 3, 1]
+
+
+def test_measure_targets_turns_an_unexpected_error_into_minus_one(monkeypatch):
+    def broken(endpoint, url, **_kwargs):
+        raise RuntimeError("boom")
+
+    monkeypatch.setattr(batch_probe, "measure_latency", broken)
+    results: dict[int, int] = {}
+
+    measure_targets(
+        numbered_targets(2),
+        [41001, 41002],
+        CREDENTIALS,
+        url="http://example.com/",
+        on_result=results.__setitem__,
+    )
+
+    assert results == {1: -1, 2: -1}
+
+
+@needs_xray
+def test_one_core_process_measures_the_whole_batch(local_site, core_starts):
+    targets = [ProbeTarget(i, FREEDOM) for i in range(1, 101)]
+    results: dict[int, int] = {}
+
+    probe_targets(
+        targets,
+        binary_path=str(XRAY),
+        on_result=results.__setitem__,
+        url=local_site,
+        probes=1,
+    )
+
+    assert len(core_starts) == 1
+    assert sorted(results) == list(range(1, 101))
+    assert all(latency >= 0 for latency in results.values())
+
+
+@needs_xray
+def test_dead_and_rejected_profiles_get_minus_one_and_the_rest_are_measured(
+    local_site, core_starts
+):
+    targets = [
+        ProbeTarget(1, FREEDOM),
+        target(2, VLESS_BAD_REALITY),
+        ProbeTarget(3, BLACKHOLE),
+        ProbeTarget(4, FREEDOM),
+    ]
+    results: dict[int, int] = {}
+
+    probe_targets(
+        targets,
+        binary_path=str(XRAY),
+        on_result=results.__setitem__,
+        url=local_site,
+        probes=1,
+    )
+
+    assert results[2] == -1  # ядро отвергло профиль
+    assert results[3] == -1  # ядро приняло, но сервер не отвечает
+    assert results[1] >= 0
+    assert results[4] >= 0
+    assert len(core_starts) == 1
+
+
+@needs_xray
+def test_probe_inbound_answers_407_without_valid_credentials(local_site):
+    ports = reserve_ports(1)
+    config = build_batch_probe_config([ProbeTarget(1, FREEDOM)], ports, CREDENTIALS)
+
+    with BatchCore(str(XRAY), config) as core:
+        assert core.wait_ready(ports)
+        statuses = []
+        for proxy in (
+            f"http://127.0.0.1:{ports[0]}",
+            f"http://probe:wrong@127.0.0.1:{ports[0]}",
+            f"http://probe:secret@127.0.0.1:{ports[0]}",
+        ):
+            with requests.Session() as session:
+                session.trust_env = False
+                response = session.head(local_site, proxies={"http": proxy}, timeout=5)
+                statuses.append(response.status_code)
+
+    assert statuses == [407, 407, 204]
+
+
+def test_batch_core_cleans_up_its_config_file(monkeypatch):
+    written: list[Path] = []
+    real_write = batch_probe._write_config
+
+    def spy(config):
+        path = real_write(config)
+        written.append(path)
+        return path
+
+    monkeypatch.setattr(batch_probe, "_write_config", spy)
+
+    with BatchCore("/nonexistent/xray", {"inbounds": []}) as core:
+        assert written[0].exists()
+        assert core.wait_ready([41001], timeout=0.2) is False
+
+    assert not written[0].exists()
+
+
+def test_every_profile_gets_minus_one_when_the_core_does_not_start(monkeypatch):
+    # Проверку `-test` ядро «прошло», а процесс завершается сразу после запуска.
+    monkeypatch.setattr(batch_probe, "core_accepts", lambda *_: True)
+    results: dict[int, int] = {}
+
+    probe_targets(
+        numbered_targets(3),
+        binary_path="false",
+        on_result=results.__setitem__,
+        url="http://example.com/",
+    )
+
+    assert results == {1: -1, 2: -1, 3: -1}
+
+
+def test_large_sets_are_measured_in_several_batches(monkeypatch):
+    batches: list[list[int]] = []
+    monkeypatch.setattr(batch_probe, "MAX_BATCH_SIZE", 2)
+    monkeypatch.setattr(
+        batch_probe,
+        "_probe_batch",
+        lambda targets, **_kwargs: batches.append([t.profile_id for t in targets]),
+    )
+
+    probe_targets(numbered_targets(5), binary_path="xray", on_result=lambda *_: None)
+
+    assert batches == [[1, 2], [3, 4], [5]]
+
+
+def test_probe_profiles_reports_unbuildable_profiles_and_measures_the_rest(monkeypatch):
+    measured: list[int] = []
+
+    def fake_probe_targets(targets, *, on_result, **_kwargs):
+        for item in targets:
+            measured.append(item.profile_id)
+            on_result(item.profile_id, 42)
+
+    monkeypatch.setattr(batch_probe, "probe_targets", fake_probe_targets)
+    results: dict[int, int] = {}
+
+    probe_profiles(
+        [entry(1, VLESS_WS), entry(2, VLESS_H2), entry(3, TROJAN)],
+        settings=DataStore(),
+        binary_path="xray",
+        on_result=results.__setitem__,
+    )
+
+    assert measured == [1, 3]
+    assert results == {1: 42, 2: -1, 3: 42}
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_batch_probe.py -q`
Expected: FAIL — ошибка сбора, `cannot import name 'BatchCore'`.

**Step 3: Реализовать**

Изменить `src/core/batch_probe.py`:

```diff
--- a/src/core/batch_probe.py
+++ b/src/core/batch_probe.py
@@ -10,14 +10,23 @@ from __future__ import annotations
 import copy
 import json
 import logging
+import socket
 import subprocess
 import tempfile
-from collections.abc import Callable, Sequence
+import time
+from collections.abc import Callable, Iterable, Sequence
+from concurrent.futures import ThreadPoolExecutor, as_completed
 from dataclasses import dataclass
 from pathlib import Path
-from typing import TYPE_CHECKING, Any
-
-from src.core.http_probe import ProbeCredentials, ProbeEndpoint, build_probe_inbound
+from typing import IO, TYPE_CHECKING, Any
+
+from src.core.http_probe import (
+    LOOPBACK,
+    ProbeCredentials,
+    ProbeEndpoint,
+    build_probe_inbound,
+    measure_latency,
+)
 from src.core.transport_tweaks import apply_transport_tweaks
 
 if TYPE_CHECKING:
@@ -30,6 +39,16 @@ PROBE_INBOUND_PREFIX = "probe-in-"
 PROBE_OUTBOUND_PREFIX = "proxy-"
 CORE_TEST_TIMEOUT_SECONDS = 60
 
+LATENCY_TEST_URL = "http://www.google.com/generate_204"
+DEFAULT_MAX_WORKERS = 16
+# Ядро поднимает полторы тысячи inbound'ов за доли секунды; предел нужен только
+# затем, чтобы свободных портов хватило при любом числе профилей.
+MAX_BATCH_SIZE = 500
+START_ATTEMPTS = 3
+START_TIMEOUT_SECONDS = 5.0
+
+ResultFn = Callable[[int, int], None]
+
 
 @dataclass(frozen=True)
 class ProbeTarget:
@@ -146,3 +165,218 @@ def split_accepted(
     left_accepted, left_rejected = split_accepted(batch[:middle], accepts)
     right_accepted, right_rejected = split_accepted(batch[middle:], accepts)
     return left_accepted + right_accepted, left_rejected + right_rejected
+
+
+def reserve_ports(count: int, host: str = LOOPBACK) -> list[int]:
+    """Свободные TCP-порты, все разные: сокеты закрываются только в конце."""
+    sockets: list[socket.socket] = []
+    try:
+        for _ in range(count):
+            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
+            sockets.append(sock)
+            sock.bind((host, 0))
+        return [sock.getsockname()[1] for sock in sockets]
+    finally:
+        for sock in sockets:
+            sock.close()
+
+
+def _port_open(port: int) -> bool:
+    try:
+        socket.create_connection((LOOPBACK, port), timeout=0.2).close()
+    except OSError:
+        return False
+    return True
+
+
+class BatchCore:
+    """Временный процесс ядра на один замер.
+
+    Отдельно от `XrayManager`: тот добавляет в конфиг Stats API на общем порту
+    10085. Ядро открывает порты с SO_REUSEPORT, поэтому второй процесс молча
+    делил бы этот порт с рабочим и перехватывал часть запросов статистики.
+    """
+
+    def __init__(self, binary_path: str, config: dict[str, Any]) -> None:
+        self._binary_path = binary_path
+        self._config = config
+        self._config_path: Path | None = None
+        self._process: subprocess.Popen | None = None
+        self._output: IO[bytes] | None = None
+
+    def __enter__(self) -> BatchCore:
+        self._config_path = _write_config(self._config)
+        # Вывод уходит в файл, а не в pipe: непрочитанный pipe переполнился бы
+        # предупреждениями о мёртвых серверах и остановил бы ядро посреди замера.
+        self._output = tempfile.TemporaryFile()
+        try:
+            self._process = subprocess.Popen(
+                [self._binary_path, "run", "-c", str(self._config_path)],
+                stdout=self._output,
+                stderr=subprocess.STDOUT,
+            )
+        except OSError as e:
+            logger.warning("Probe core could not be started: %s", e)
+        return self
+
+    def wait_ready(self, ports: Sequence[int], timeout: float = START_TIMEOUT_SECONDS) -> bool:
+        """Дождаться, пока ядро откроет inbound'ы. False — не запустилось."""
+        if self._process is None or not ports:
+            return False
+
+        # Проверяется каждый порт: порядок запуска inbound'ов ядро не обещает,
+        # и проба в ещё не открытый порт записала бы живому профилю -1.
+        pending = set(ports)
+        deadline = time.monotonic() + timeout
+        while time.monotonic() < deadline:
+            if self._process.poll() is not None:
+                return False
+            pending = {port for port in pending if not _port_open(port)}
+            if not pending:
+                return True
+            time.sleep(0.05)
+        return False
+
+    def __exit__(self, *_exc: object) -> None:
+        if self._process is not None:
+            if self._process.poll() is None:
+                self._process.terminate()
+                try:
+                    self._process.wait(timeout=5)
+                except subprocess.TimeoutExpired:
+                    self._process.kill()
+                    self._process.wait(timeout=2)
+            self._process = None
+        if self._output is not None:
+            self._output.close()
+            self._output = None
+        if self._config_path is not None:
+            self._config_path.unlink(missing_ok=True)
+            self._config_path = None
+
+
+def measure_targets(
+    targets: Sequence[ProbeTarget],
+    ports: Sequence[int],
+    credentials: ProbeCredentials,
+    *,
+    url: str,
+    on_result: ResultFn,
+    max_workers: int = DEFAULT_MAX_WORKERS,
+    timeout: float = 3.0,
+    probes: int = 3,
+) -> None:
+    """Замерить профили параллельно, отдавая каждый результат сразу по готовности."""
+
+    def measure(port: int) -> int:
+        endpoint = ProbeEndpoint(port, credentials)
+        return measure_latency(endpoint, url, timeout=timeout, probes=probes)
+
+    workers = max(1, min(max_workers, len(targets)))
+    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tenga-probe") as pool:
+        futures = {
+            pool.submit(measure, port): target.profile_id
+            for target, port in zip(targets, ports, strict=True)
+        }
+        for future in as_completed(futures):
+            try:
+                latency = int(future.result())
+            except Exception as e:
+                logger.warning("Probe of profile %s failed: %s", futures[future], e)
+                latency = -1
+            on_result(futures[future], latency)
+
+
+def _probe_batch(
+    targets: Sequence[ProbeTarget],
+    *,
+    binary_path: str,
+    on_result: ResultFn,
+    url: str,
+    max_workers: int,
+    timeout: float,
+    probes: int,
+) -> None:
+    credentials = ProbeCredentials.generate()
+
+    def accepts(chunk: Sequence[ProbeTarget]) -> bool:
+        # `-test` портов не открывает, поэтому настоящие здесь не нужны.
+        ports = range(1024, 1024 + len(chunk))
+        return core_accepts(binary_path, build_batch_probe_config(chunk, ports, credentials))
+
+    accepted, rejected = split_accepted(targets, accepts)
+    for target in rejected:
+        logger.info("Profile %s rejected by the core, not probed", target.profile_id)
+        on_result(target.profile_id, -1)
+    if not accepted:
+        return
+
+    for attempt in range(1, START_ATTEMPTS + 1):
+        ports = reserve_ports(len(accepted))
+        config = build_batch_probe_config(accepted, ports, credentials)
+        with BatchCore(binary_path, config) as core:
+            if not core.wait_ready(ports):
+                logger.warning("Probe core did not start (attempt %d/%d)", attempt, START_ATTEMPTS)
+                continue
+            measure_targets(
+                accepted,
+                ports,
+                credentials,
+                url=url,
+                on_result=on_result,
+                max_workers=max_workers,
+                timeout=timeout,
+                probes=probes,
+            )
+            return
+
+    for target in accepted:
+        on_result(target.profile_id, -1)
+
+
+def probe_targets(
+    targets: Sequence[ProbeTarget],
+    *,
+    binary_path: str,
+    on_result: ResultFn,
+    url: str = LATENCY_TEST_URL,
+    max_workers: int = DEFAULT_MAX_WORKERS,
+    timeout: float = 3.0,
+    probes: int = 3,
+) -> None:
+    """Замерить готовые outbound'ы. Каждый профиль получает ровно один результат."""
+    for start in range(0, len(targets), MAX_BATCH_SIZE):
+        _probe_batch(
+            targets[start : start + MAX_BATCH_SIZE],
+            binary_path=binary_path,
+            on_result=on_result,
+            url=url,
+            max_workers=max_workers,
+            timeout=timeout,
+            probes=probes,
+        )
+
+
+def probe_profiles(
+    profiles: Iterable[ProfileEntry],
+    *,
+    settings: DataStore,
+    binary_path: str,
+    on_result: ResultFn,
+    **options: Any,
+) -> None:
+    """Замерить задержку профилей одним процессом ядра.
+
+    `on_result(profile_id, latency_ms)` вызывается по мере готовности, из
+    потока вызывающего; -1 — профиль не собрался, отвергнут ядром или не ответил.
+    """
+    targets: list[ProbeTarget] = []
+    for profile in profiles:
+        outbound = build_probe_outbound(profile, settings)
+        if outbound is None:
+            on_result(profile.id, -1)
+            continue
+        targets.append(ProbeTarget(profile.id, outbound))
+
+    if targets:
+        probe_targets(targets, binary_path=binary_path, on_result=on_result, **options)
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_batch_probe.py -q`
Expected: PASS — `27 passed`.

Тест `test_one_core_process_measures_the_whole_batch` — приёмка P1: сто профилей,
один запуск ядра. Прогони файл несколько раз подряд: тесты с настоящим ядром не
должны мигать.

**Step 5: Commit**

```bash
git add src/core/batch_probe.py tests/test_core_batch_probe.py
git commit -m "feat(core): замер пакета профилей одним процессом ядра с потоковой выдачей"
```

---

### Task 5: Подключить пакетный замер к приложению

`LatencyRunner` получает второй режим: `batch_probe(ids, emit)` принимает весь
набор разом и сам отдаёт результаты. Прежний режим `probe(id)` остаётся — им
пользуются тесты через `set_latency_probe`. Что бы ни случилось с пакетным
замером, каждый профиль получает результат: недоложенным runner сам дописывает
`-1`, иначе строка навсегда осталась бы с заглушкой «проверяется».

`make_batch_probe(context)` связывает runner с `probe_profiles`; контекст
читается в момент замера. Из `TengaApplication` уходит `_default_latency_probe`.

**Files:**
- Modify: `src/ui/logic/latency.py`
- Modify: `src/ui/application.py` (`_ensure_latency_runner`, удаляется `_default_latency_probe`)
- Test: `tests/test_ui_logic_latency.py`, `tests/test_ui_application.py` (GTK)

**Step 1: Написать падающие тесты**

Изменить `tests/test_ui_application.py`:

```diff
--- a/tests/test_ui_application.py
+++ b/tests/test_ui_application.py
@@ -2,6 +2,8 @@
 
 from __future__ import annotations
 
+from types import SimpleNamespace
+
 import pytest
 
 pytestmark = pytest.mark.gtk
@@ -550,83 +552,31 @@ def test_a_tray_that_cannot_start_does_not_break_the_application(adw_app, monkey
     assert adw_app.tray is None
 
 
-class _FakeManager:
-    """Стоит вместо XrayManager: замер не должен поднимать настоящий процесс."""
-
-    instances: list = []
-
-    def __init__(self, binary_path=None):
-        self.binary_path = binary_path
-        self.stopped = False
-        self.started_with = None
-        _FakeManager.instances.append(self)
-
-    def start(self, config):
-        self.started_with = config
-        return True, ""
-
-    def test_delay_realistic(self, proxy_address, proxy_port, **kwargs):
-        return 42
-
-    def stop(self):
-        self.stopped = True
-
-
-def _install_fake_xray(monkeypatch, cls=None):
-    """Replace XrayManager and return the probe's own instance afterwards.
-
-    Экземпляров создаётся два: один лениво заводит `AppContext` ради
-    `binary_path`, второй — сам замер. Замеру принадлежит последний.
-    """
-    _FakeManager.instances = []
-    monkeypatch.setattr("src.core.xray_manager.XrayManager", cls or _FakeManager)
-
-
-def _probe_manager():
-    assert _FakeManager.instances, "замер обязан был создать экземпляр"
-    return _FakeManager.instances[-1]
-
-
-def test_default_latency_probe_measures_through_a_temporary_xray(adw_app, monkeypatch):
-    _install_fake_xray(monkeypatch)
-    entry = add_profile(adw_app)
+def test_default_latency_run_measures_the_whole_set_with_one_batch_call(adw_app, monkeypatch):
+    """Без подменённой пробы замер идёт пакетом: один вызов на все профили."""
+    first = add_profile(adw_app)
+    second = add_profile(adw_app)
+    calls: list[list[int]] = []
 
-    assert adw_app._default_latency_probe(entry.id) == 42
-    assert _probe_manager().stopped is True
+    def fake_probe_profiles(profiles, *, settings, binary_path, on_result):
+        calls.append([profile.id for profile in profiles])
+        for profile in profiles:
+            on_result(profile.id, 42)
 
+    monkeypatch.setattr("src.core.batch_probe.probe_profiles", fake_probe_profiles)
+    monkeypatch.setattr(
+        type(adw_app.context),
+        "xray_manager",
+        property(lambda _self: SimpleNamespace(binary_path="xray")),
+    )
 
-def test_default_latency_probe_returns_minus_one_for_a_missing_profile(adw_app, monkeypatch):
-    _install_fake_xray(monkeypatch)
-
-    assert adw_app._default_latency_probe(999999) == -1
-    assert _FakeManager.instances == []
-
-
-def test_default_latency_probe_returns_minus_one_when_xray_does_not_start(adw_app, monkeypatch):
-    class Failing(_FakeManager):
-        def start(self, config):
-            return False, "port busy"
-
-    _install_fake_xray(monkeypatch, Failing)
-    entry = add_profile(adw_app)
-
-    assert adw_app._default_latency_probe(entry.id) == -1
-    assert _probe_manager().stopped is True
-
-
-def test_default_latency_probe_stops_xray_when_the_probe_raises(adw_app, monkeypatch):
-    """Временный процесс гасится и на ошибке: иначе он останется висеть."""
-
-    class Raising(_FakeManager):
-        def test_delay_realistic(self, proxy_address, proxy_port, **kwargs):
-            raise RuntimeError("boom")
-
-    _install_fake_xray(monkeypatch, Raising)
-    entry = add_profile(adw_app)
+    adw_app.activate_action("test-latency", None)
+    adw_app.wait_for_latency_for_test()
 
-    with pytest.raises(RuntimeError):
-        adw_app._default_latency_probe(entry.id)
-    assert _probe_manager().stopped is True
+    store = adw_app.context.profiles
+    assert calls == [[first.id, second.id]]
+    assert store.get_profile(first.id).latency_ms == 42
+    assert store.get_profile(second.id).latency_ms == 42
 
 
 def _simulate_close(app, dialog) -> None:
```

Изменить `tests/test_ui_logic_latency.py`:

```diff
--- a/tests/test_ui_logic_latency.py
+++ b/tests/test_ui_logic_latency.py
@@ -2,8 +2,11 @@ from __future__ import annotations
 
 import threading
 import time
+from types import SimpleNamespace
 
-from src.ui.logic.latency import LatencyRunner
+import pytest
+
+from src.ui.logic.latency import LatencyRunner, make_batch_probe
 
 
 def _collect(results: dict, done: list):
@@ -135,3 +138,95 @@ def test_runner_delivers_every_result_when_probe_raises_base_exception():
 
     assert results == {1: 10, 2: -1, 3: 30, 4: 40, 5: 50}
     assert done == [True]
+
+
+# --- пакетный режим: один вызов на весь набор ---
+
+
+def test_batch_runner_hands_every_id_to_one_probe_call_and_streams_results():
+    calls: list[list[int]] = []
+
+    def batch_probe(profile_ids, emit) -> None:
+        calls.append(list(profile_ids))
+        for profile_id in reversed(profile_ids):
+            emit(profile_id, profile_id * 10)
+
+    delivered: list = []
+    runner = LatencyRunner(batch_probe=batch_probe, dispatch=lambda _fn, *a: delivered.append(a))
+
+    runner.run([1, 2, 3], on_result=lambda *_: None, on_done=lambda: None)
+    runner.wait(timeout=5)
+
+    assert calls == [[1, 2, 3]]
+    # Результаты уходят в том порядке, в каком их отдал замер; последним — on_done.
+    assert delivered[:3] == [(3, 30), (2, 20), (1, 10)]
+    assert len(delivered) == 4
+
+
+def test_batch_runner_reports_minus_one_for_everything_the_probe_left_out():
+    def batch_probe(profile_ids, emit) -> None:
+        emit(1, 10)
+        raise RuntimeError("ядро не запустилось")
+
+    delivered: list = []
+    runner = LatencyRunner(
+        batch_probe=batch_probe, dispatch=lambda fn, *a: delivered.append((fn, a))
+    )
+    results: dict = {}
+    done: list = []
+    on_result, on_done = _collect(results, done)
+
+    runner.run([1, 2, 3], on_result=on_result, on_done=on_done)
+    runner.wait(timeout=5)
+    for fn, args in delivered:
+        fn(*args)
+
+    assert results == {1: 10, 2: -1, 3: -1}
+    assert done == [True]
+    assert runner.is_busy is False
+
+
+def test_batch_runner_ignores_a_second_result_for_the_same_profile():
+    def batch_probe(profile_ids, emit) -> None:
+        emit(1, 10)
+        emit(1, 99)
+
+    delivered: list = []
+    runner = LatencyRunner(batch_probe=batch_probe, dispatch=lambda _fn, *a: delivered.append(a))
+
+    runner.run([1], on_result=lambda *_: None, on_done=lambda: None)
+    runner.wait(timeout=5)
+
+    assert delivered[0] == (1, 10)
+    assert len(delivered) == 2
+
+
+def test_runner_requires_one_of_the_two_probes():
+    with pytest.raises(ValueError, match="ровно один"):
+        LatencyRunner()
+
+
+def test_make_batch_probe_measures_known_profiles_with_the_app_settings(monkeypatch):
+    seen: dict = {}
+
+    def fake_probe_profiles(profiles, *, settings, binary_path, on_result):
+        seen["ids"] = [profile.id for profile in profiles]
+        seen["settings"] = settings
+        seen["binary"] = binary_path
+        for profile in profiles:
+            on_result(profile.id, 42)
+
+    monkeypatch.setattr("src.core.batch_probe.probe_profiles", fake_probe_profiles)
+    known = {1: SimpleNamespace(id=1), 3: SimpleNamespace(id=3)}
+    context = SimpleNamespace(
+        profiles=SimpleNamespace(get_profile=known.get),
+        config="настройки",
+        xray_manager=SimpleNamespace(binary_path="/opt/xray"),
+    )
+    results: dict = {}
+
+    make_batch_probe(context)([1, 2, 3], results.__setitem__)
+
+    # Профиля 2 уже нет: в замер он не идёт, а -1 ему допишет сам runner.
+    assert seen == {"ids": [1, 3], "settings": "настройки", "binary": "/opt/xray"}
+    assert results == {1: 42, 3: 42}
```

В `tests/test_ui_application.py` четыре теста `_default_latency_probe` и класс
`_FakeManager` заменяются одним тестом пакетного пути.

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_ui_logic_latency.py -q`
Expected: FAIL — ошибка сбора, `cannot import name 'make_batch_probe'`.

**Step 3: Реализовать**

Изменить `src/ui/application.py`:

```diff
--- a/src/ui/application.py
+++ b/src/ui/application.py
@@ -15,7 +15,7 @@ from gi.repository import Adw, Gio, GLib, Gtk
 
 from src.core.context import AppContext, get_context
 from src.ui.logic.async_utils import run_in_background
-from src.ui.logic.latency import LatencyRunner
+from src.ui.logic.latency import LatencyRunner, make_batch_probe
 from src.ui.logic.profiles_view import SortKey
 from src.ui.logic.status import ConnectionState
 from src.ui.logic.version import app_version, core_version
@@ -533,35 +533,6 @@ class TengaApplication(Adw.Application):
             name="tenga-subscription",
         )
 
-    def _default_latency_probe(self, profile_id: int) -> int:
-        from src.core.config_builder import build_latency_probe_config
-        from src.core.xray_manager import XrayManager
-
-        profile = self.context.profiles.get_profile(profile_id)
-        if profile is None:
-            return -1
-
-        built = build_latency_probe_config(self.context, profile)
-        if built is None:
-            return -1
-
-        config, socks_port = built
-        manager = XrayManager(binary_path=self.context.xray_manager.binary_path)
-        try:
-            started, error = manager.start(config)
-            if not started:
-                logger.warning("Latency probe could not start xray: %s", error)
-                return -1
-            return manager.test_delay_realistic(
-                proxy_address=self.context.config.inbound_address,
-                proxy_port=socks_port,
-            )
-        finally:
-            try:
-                manager.stop()
-            except Exception:
-                logger.debug("Latency probe cleanup failed", exc_info=True)
-
     def _default_subscription_updater(self, group_id: int, url: str) -> int:
         from src.sub.updater import update_subscription
 
@@ -575,7 +546,11 @@ class TengaApplication(Adw.Application):
 
     def _ensure_latency_runner(self) -> LatencyRunner:
         if self._latency_runner is None:
-            self._latency_runner = LatencyRunner(self._latency_probe or self._default_latency_probe)
+            if self._latency_probe is not None:
+                self._latency_runner = LatencyRunner(self._latency_probe)
+            else:
+                # Весь набор меряет один временный процесс ядра.
+                self._latency_runner = LatencyRunner(batch_probe=make_batch_probe(self.context))
         return self._latency_runner
 
     def _test_latency(self) -> None:
```

Изменить `src/ui/logic/latency.py`:

```diff
--- a/src/ui/logic/latency.py
+++ b/src/ui/logic/latency.py
@@ -10,11 +10,13 @@ import logging
 import threading
 from collections.abc import Callable, Iterable
 from concurrent.futures import ThreadPoolExecutor
+from typing import Any
 
 logger = logging.getLogger("tenga.ui.latency")
 
 ProbeFn = Callable[[int], int]
 ResultFn = Callable[[int, int], None]
+BatchProbeFn = Callable[[list[int], ResultFn], None]
 DispatchFn = Callable[..., object]
 
 
@@ -28,17 +30,48 @@ def _default_dispatch(fn: Callable[..., object], *args: object) -> None:
     GLib.idle_add(_once)
 
 
+def make_batch_probe(context: Any) -> BatchProbeFn:
+    """Batch probe bound to the application context.
+
+    Контекст читается в момент замера, а не при создании: список профилей и
+    настройки транспорта к этому времени могли измениться.
+    """
+
+    def batch_probe(profile_ids: list[int], emit: ResultFn) -> None:
+        from src.core.batch_probe import probe_profiles
+
+        found = (context.profiles.get_profile(profile_id) for profile_id in profile_ids)
+        probe_profiles(
+            [profile for profile in found if profile is not None],
+            settings=context.config,
+            binary_path=context.xray_manager.binary_path,
+            on_result=emit,
+        )
+
+    return batch_probe
+
+
 class LatencyRunner:
-    """Run latency probes for many profiles with bounded parallelism."""
+    """Run latency probes for many profiles in the background.
+
+    Два режима. `batch_probe` получает весь набор сразу и сам отдаёт результаты
+    по мере готовности — так работает замер одним процессом ядра. `probe`
+    меряет по одному профилю в пуле потоков; он остался для подмены в тестах.
+    """
 
     def __init__(
         self,
-        probe: ProbeFn,
+        probe: ProbeFn | None = None,
         *,
+        batch_probe: BatchProbeFn | None = None,
         max_workers: int = 4,
         dispatch: DispatchFn = _default_dispatch,
     ) -> None:
+        if (probe is None) == (batch_probe is None):
+            raise ValueError("нужен ровно один из probe и batch_probe")
+
         self._probe = probe
+        self._batch_probe = batch_probe
         self._max_workers = max_workers
         self._dispatch = dispatch
         self._lock = threading.Lock()
@@ -82,12 +115,38 @@ class LatencyRunner:
                 self._busy = False
             on_done()
 
+        def _run_batch() -> None:
+            reported: set[int] = set()
+
+            def emit(profile_id: int, latency_ms: int) -> None:
+                if profile_id in reported:
+                    return
+                reported.add(profile_id)
+                self._dispatch(on_result, profile_id, int(latency_ms))
+
+            try:
+                self._batch_probe(ids, emit)
+            except BaseException as e:
+                logger.exception("Batch latency probe failed: %s", e)
+            finally:
+                # Что бы ни случилось с замером, ни один профиль не должен
+                # остаться с заглушкой «проверяется».
+                for profile_id in ids:
+                    if profile_id not in reported:
+                        self._dispatch(on_result, profile_id, -1)
+
+        def _run_pool() -> None:
+            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
+                probes = pool.map(_safe_probe, ids)
+                for profile_id, latency in zip(ids, probes, strict=True):
+                    self._dispatch(on_result, profile_id, latency)
+
         def _worker() -> None:
             try:
-                with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
-                    probes = pool.map(_safe_probe, ids)
-                    for profile_id, latency in zip(ids, probes, strict=True):
-                        self._dispatch(on_result, profile_id, latency)
+                if self._batch_probe is not None:
+                    _run_batch()
+                else:
+                    _run_pool()
             finally:
                 self._dispatch(_finished)
 
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_ui_logic_latency.py -q`
Expected: PASS — `10 passed`.

Run: `uv run pytest -m gtk tests/test_ui_application.py -q`
Expected: PASS — все тесты файла проходят.

**Step 5: Commit**

```bash
git add src/ui/application.py src/ui/logic/latency.py tests/test_ui_application.py \
        tests/test_ui_logic_latency.py
git commit -m "feat(ui): мерить задержку пакетом вместо процесса ядра на профиль"
```

---

### Task 6: Служебный inbound проверки соединения

В рабочий конфиг добавляется HTTP-inbound `health-in` на `127.0.0.1` со
свежими учётными данными и правило `inboundTag: [health-in] → <тег первого
outbound'а>` в начало списка. Почему без него нельзя — «Принятые решения»,
пункт 1; тест `test_check_through_an_ordinary_inbound_misses_a_dead_proxy`
показывает это на настоящем ядре.

Добавляет его `ConnectionService` после `build_session_config` — в `connect` и в
`reload_config` (перезагрузка перезапускает процесс, поэтому порт и пароль
новые). Билдер не меняется. Куда стучаться, монитор узнаёт из
`proxy_state.health_endpoint`; `set_stopped()` его сбрасывает.

Отладочный `current_config.json` пишется с затёртыми учётными данными.

**Files:**
- Create: `src/core/health_probe.py`
- Modify: `src/core/context.py` (`ProxyState`)
- Modify: `src/core/connection.py` (`connect`, `reload_config`, `_write_debug_config`)
- Test: `tests/test_core_health_probe.py`, `tests/test_core_connection.py`, `tests/test_core_context.py`

**Step 1: Написать падающие тесты**

Изменить `tests/test_core_connection.py`:

```diff
--- a/tests/test_core_connection.py
+++ b/tests/test_core_connection.py
@@ -6,6 +6,7 @@ from dataclasses import dataclass, field
 from unittest.mock import MagicMock
 
 from src.core.connection import ConnectionService
+from src.core.http_probe import ProbeEndpoint
 
 
 @dataclass
@@ -257,3 +258,68 @@ def test_the_monitor_is_stopped_on_disconnect(tmp_path, monkeypatch):
     monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: True)
     ConnectionService(context).disconnect()
     context.monitor.stop.assert_called_once()
+
+
+# --- служебный inbound проверки соединения ---
+
+
+def _session_config(*_args):
+    return {"inbounds": [], "outbounds": [{"protocol": "vless", "tag": "proxy"}]}
+
+
+def test_connect_adds_the_health_inbound_and_remembers_its_endpoint(tmp_path, monkeypatch):
+    context = make_context(tmp_path, FakeProfile())
+    monkeypatch.setattr("src.core.connection.build_session_config", _session_config)
+    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
+
+    assert ConnectionService(context).connect(1).ok
+
+    started = context.xray_manager.start.call_args.args[0]
+    inbound = started["inbounds"][-1]
+    endpoint = context.proxy_state.health_endpoint
+    assert isinstance(endpoint, ProbeEndpoint)
+    assert inbound["tag"] == "health-in"
+    assert inbound["port"] == endpoint.port
+    assert inbound["settings"]["accounts"] == [
+        {"user": endpoint.credentials.user, "pass": endpoint.credentials.password}
+    ]
+    assert started["routing"]["rules"][0]["inboundTag"] == ["health-in"]
+
+
+def test_health_credentials_do_not_reach_the_debug_config(tmp_path, monkeypatch):
+    context = make_context(tmp_path, FakeProfile())
+    monkeypatch.setattr("src.core.connection.build_session_config", _session_config)
+    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
+
+    ConnectionService(context).connect(1)
+
+    written = (tmp_path / "current_config.json").read_text(encoding="utf-8")
+    endpoint = context.proxy_state.health_endpoint
+    assert "health-in" in written
+    assert endpoint.credentials.password not in written
+    assert endpoint.credentials.user not in written
+
+
+def test_failed_start_does_not_publish_a_health_endpoint(tmp_path, monkeypatch):
+    context = make_context(tmp_path, FakeProfile())
+    context.xray_manager.start.return_value = (False, "binary not found")
+    monkeypatch.setattr("src.core.connection.build_session_config", _session_config)
+
+    ConnectionService(context).connect(1)
+
+    assert not isinstance(context.proxy_state.health_endpoint, ProbeEndpoint)
+
+
+def test_reload_renews_the_health_endpoint(tmp_path, monkeypatch):
+    context = make_context(tmp_path, FakeProfile())
+    context.proxy_state.is_running = True
+    context.proxy_state.started_profile_id = 1
+    context.xray_manager.reload_config.return_value = (True, "")
+    monkeypatch.setattr("src.core.connection.build_session_config", _session_config)
+
+    assert ConnectionService(context).reload_config().ok
+
+    reloaded = context.xray_manager.reload_config.call_args.args[0]
+    endpoint = context.proxy_state.health_endpoint
+    assert isinstance(endpoint, ProbeEndpoint)
+    assert reloaded["inbounds"][-1]["port"] == endpoint.port
```

Изменить `tests/test_core_context.py`:

```diff
--- a/tests/test_core_context.py
+++ b/tests/test_core_context.py
@@ -7,6 +7,7 @@ from src.core.context import (
     init_context,
     reset_context,
 )
+from src.core.http_probe import ProbeCredentials, ProbeEndpoint
 
 
 def test_proxy_state_listeners_called():
@@ -24,6 +25,17 @@ def test_proxy_state_listeners_called():
     assert calls == [(True, 42), (False, -1)]
 
 
+def test_proxy_state_forgets_the_health_endpoint_when_stopped():
+    state = ProxyState()
+    state.health_endpoint = ProbeEndpoint(port=41500, credentials=ProbeCredentials("u", "p"))
+    state.set_running(1)
+    assert state.health_endpoint is not None
+
+    state.set_stopped()
+
+    assert state.health_endpoint is None
+
+
 def test_proxy_state_remove_listener():
     state = ProxyState()
     calls = []
```

Создать `tests/test_core_health_probe.py`:

```python
"""Служебный inbound проверки соединения в рабочем конфиге."""

from __future__ import annotations

import http.server
import shutil
import threading
from pathlib import Path

import pytest
import requests

from src.core.batch_probe import BatchCore, core_accepts, reserve_ports
from src.core.config_builder import build_session_config
from src.core.context import init_context
from src.core.health_probe import (
    HEALTH_INBOUND_TAG,
    attach_health_inbound,
    new_health_endpoint,
    redact_health_credentials,
)
from src.core.http_probe import ProbeCredentials, ProbeEndpoint, measure_latency
from src.db.config import ProxyMode
from src.db.profiles import ProfileEntry
from src.fmt import parse_link

XRAY = Path("core/bin/xray")
needs_xray = pytest.mark.skipif(
    not XRAY.exists() or not shutil.which(str(XRAY)),
    reason="бинарник xray недоступен (core/bin/xray)",
)

ENDPOINT = ProbeEndpoint(port=41500, credentials=ProbeCredentials("health", "secret"))


def session_config(proxy: dict | None = None) -> dict:
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"tag": "tun-in", "protocol": "tun"}],
        "outbounds": [
            proxy or {"protocol": "vless", "tag": "proxy"},
            {"protocol": "freedom", "tag": "direct"},
        ],
        "routing": {
            "domainStrategy": "IPOnDemand",
            "rules": [{"type": "field", "domain": ["example.com"], "outboundTag": "direct"}],
        },
    }


def test_health_endpoint_gets_a_free_loopback_port_and_fresh_credentials():
    first = new_health_endpoint()
    second = new_health_endpoint()

    assert first.host == "127.0.0.1"
    assert first.port > 0
    assert first.credentials != second.credentials


def test_health_inbound_is_an_authenticated_http_proxy_on_loopback():
    config = attach_health_inbound(session_config(), ENDPOINT)

    inbound = config["inbounds"][-1]
    assert inbound == {
        "tag": HEALTH_INBOUND_TAG,
        "listen": "127.0.0.1",
        "port": 41500,
        "protocol": "http",
        "settings": {"accounts": [{"user": "health", "pass": "secret"}]},
    }
    assert config["inbounds"][0]["tag"] == "tun-in"


def test_health_rule_goes_first_and_points_at_the_profile_outbound():
    config = attach_health_inbound(
        session_config({"protocol": "trojan", "tag": "my-proxy"}), ENDPOINT
    )

    rules = config["routing"]["rules"]
    assert rules[0] == {
        "type": "field",
        "inboundTag": [HEALTH_INBOUND_TAG],
        "outboundTag": "my-proxy",
    }
    # Пользовательские правила остаются, но идут после.
    assert rules[1]["domain"] == ["example.com"]


def test_health_inbound_tolerates_a_config_without_routing():
    config = attach_health_inbound({"outbounds": [{"protocol": "vless", "tag": "proxy"}]}, ENDPOINT)

    assert config["inbounds"][0]["tag"] == HEALTH_INBOUND_TAG
    assert config["routing"]["rules"][0]["outboundTag"] == "proxy"


def test_redacted_copy_hides_credentials_and_leaves_the_config_intact():
    config = attach_health_inbound(session_config(), ENDPOINT)

    redacted = redact_health_credentials(config)

    assert redacted["inbounds"][-1]["settings"]["accounts"] == [{"user": "***", "pass": "***"}]
    assert redacted["inbounds"][-1]["port"] == 41500
    assert config["inbounds"][-1]["settings"]["accounts"] == [{"user": "health", "pass": "secret"}]


# --- настоящее ядро: проверка не должна обходить прокси по direct-правилам ---


class _Site(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, *_args):
        pass


@pytest.fixture
def local_site():
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/generate_204"
    server.shutdown()
    server.server_close()


def running_config(proxy: dict, plain_port: int, health: ProbeEndpoint) -> dict:
    """Рабочий конфиг в миниатюре: сайт проверки попадает под direct-правило."""
    config = {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {"tag": "http-plain", "listen": "127.0.0.1", "port": plain_port, "protocol": "http"}
        ],
        "outbounds": [proxy, {"protocol": "freedom", "tag": "direct"}],
        "routing": {
            "rules": [{"type": "field", "ip": ["127.0.0.0/8"], "outboundTag": "direct"}],
        },
    }
    return attach_health_inbound(config, health)


@needs_xray
def test_check_through_an_ordinary_inbound_misses_a_dead_proxy(local_site):
    """Зачем нужен отдельный inbound: обычный путь подчиняется правилам пользователя.

    Прокси мёртв (blackhole), но адрес проверки попадает под direct-правило —
    запрос через обычный inbound проходит, и проверка ошибочно говорит «всё хорошо».
    """
    plain_port, health_port = reserve_ports(2)
    health = ProbeEndpoint(health_port, ProbeCredentials.generate())
    config = running_config({"protocol": "blackhole", "tag": "proxy"}, plain_port, health)

    with BatchCore(str(XRAY), config) as core:
        assert core.wait_ready([plain_port, health_port])
        with requests.Session() as session:
            session.trust_env = False
            plain = session.head(
                local_site, proxies={"http": f"http://127.0.0.1:{plain_port}"}, timeout=5
            )
        through_health = measure_latency(health, local_site, probes=1)

    assert plain.status_code == 204
    assert through_health == -1


@needs_xray
def test_check_through_the_health_inbound_passes_when_the_proxy_works(local_site):
    plain_port, health_port = reserve_ports(2)
    health = ProbeEndpoint(health_port, ProbeCredentials.generate())
    config = running_config({"protocol": "freedom", "tag": "proxy"}, plain_port, health)

    with BatchCore(str(XRAY), config) as core:
        assert core.wait_ready([plain_port, health_port])
        through_health = measure_latency(health, local_site, probes=1)

    assert through_health >= 0


@needs_xray
def test_core_accepts_a_real_session_config_with_the_health_inbound(tmp_path):
    """Конфиг из рабочего билдера с добавленным inbound'ом ядро принимает."""
    context = init_context(config_dir=tmp_path)
    # Только системный прокси: `xray -test` на TUN-конфиге трогает интерфейсы.
    context.config.proxy_mode = ProxyMode.SYSTEM_PROXY
    bean = parse_link(
        "vless://11111111-1111-1111-1111-111111111111@127.0.0.1:443"
        "?type=ws&path=%2Fws&security=tls&sni=a.example.com#W"
    )
    config = build_session_config(context, ProfileEntry(id=1, group_id=0, bean=bean))
    assert config is not None

    attach_health_inbound(config, new_health_endpoint())

    assert all(inbound["protocol"] != "tun" for inbound in config["inbounds"])
    assert core_accepts(str(XRAY), config) is True
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_health_probe.py tests/test_core_connection.py tests/test_core_context.py -q`
Expected: FAIL — ошибка сбора, `No module named 'src.core.health_probe'`.

**Step 3: Реализовать**

Изменить `src/core/connection.py`:

```diff
--- a/src/core/connection.py
+++ b/src/core/connection.py
@@ -14,6 +14,11 @@ from dataclasses import dataclass
 from typing import TYPE_CHECKING
 
 from src.core.config_builder import build_session_config
+from src.core.health_probe import (
+    attach_health_inbound,
+    new_health_endpoint,
+    redact_health_credentials,
+)
 from src.core.proxy_mode import normalize_proxy_mode, should_manage_system_proxy
 from src.db.config import ProxyMode
 from src.sys.proxy import clear_system_proxy, set_system_proxy
@@ -69,6 +74,8 @@ class ConnectionService:
             logger.error("Could not build a configuration for profile %s", profile_id)
             return ConnectionResult(False, NO_CONFIG)
 
+        health_endpoint = new_health_endpoint()
+        attach_health_inbound(config, health_endpoint)
         self._write_debug_config(config, profile_id)
 
         try:
@@ -81,6 +88,7 @@ class ConnectionService:
             logger.error("Error starting xray-core: %s", error)
             return ConnectionResult(False, error or "Не удалось запустить xray-core")
 
+        context.proxy_state.health_endpoint = health_endpoint
         context.proxy_state.set_running(profile_id, mode=runtime_mode)
 
         routed = self._apply_runtime_mode(runtime_mode, profile)
@@ -131,7 +139,9 @@ class ConnectionService:
     def _write_debug_config(self, config: dict, profile_id: int) -> None:
         try:
             path = self._context.config_dir / "current_config.json"
-            path.write_text(json.dumps(config, indent=2), encoding="utf-8")
+            # Учётные данные служебного inbound'а на диск не пишутся.
+            safe_config = redact_health_credentials(config)
+            path.write_text(json.dumps(safe_config, indent=2), encoding="utf-8")
             logger.info("Configured profile id=%s, file: %s", profile_id, path)
         except OSError as e:
             # Конфигурация нужна только для разбора проблем: не пишется —
@@ -250,6 +260,9 @@ class ConnectionService:
             logger.error("Failed to create configuration for reload")
             return ConnectionResult(False, NO_CONFIG)
 
+        # Перезагрузка — это перезапуск процесса: порт и учётные данные новые.
+        health_endpoint = new_health_endpoint()
+        attach_health_inbound(config, health_endpoint)
         self._write_debug_config(config, profile_id)
 
         try:
@@ -262,5 +275,6 @@ class ConnectionService:
             logger.error("Error reloading xray-core: %s", error)
             return ConnectionResult(False, error or "Не удалось перезагрузить конфигурацию")
 
+        context.proxy_state.health_endpoint = health_endpoint
         logger.info("Configuration reloaded successfully")
         return ConnectionResult(True)
```

Изменить `src/core/context.py`:

```diff
--- a/src/core/context.py
+++ b/src/core/context.py
@@ -8,6 +8,7 @@ from typing import TYPE_CHECKING
 from src.core.config import CORE_DIR, LOG_DIR, find_xray_binary
 
 if TYPE_CHECKING:
+    from src.core.http_probe import ProbeEndpoint
     from src.core.log_manager import LogManager
     from src.core.monitor import ConnectionMonitor
     from src.core.xray_manager import XrayManager
@@ -25,6 +26,8 @@ class ProxyState:
     download_bytes: int = 0
     vpn_auto_connected: bool = False
     started_mode: str = "tun"
+    # Служебный inbound работающего ядра: через него монитор проверяет сервер.
+    health_endpoint: ProbeEndpoint | None = None
 
     # Listeners
     _state_listeners: list[Callable[[ProxyState], None]] = field(default_factory=list)
@@ -61,6 +64,7 @@ class ProxyState:
         self.upload_bytes = 0
         self.download_bytes = 0
         self.started_mode = "tun"
+        self.health_endpoint = None
         self.notify_listeners()
 
 
```

Создать `src/core/health_probe.py`:

```python
"""Служебный inbound проверки соединения в рабочем конфиге.

Монитор проверяет прокси запросом через этот inbound. Обычным путём — через
TUN или пользовательский SOCKS/HTTP-inbound — проверять нельзя: запрос
подчинился бы правилам маршрутизации и, попав под direct-правило, прошёл бы
мимо прокси. Мёртвый сервер тогда выглядел бы живым. Правило
`health-in → proxy` стоит первым, поэтому проверка всегда идёт через сервер
профиля.
"""

from __future__ import annotations

import copy
from typing import Any

from src.core.batch_probe import reserve_ports
from src.core.http_probe import ProbeCredentials, ProbeEndpoint, build_probe_inbound

HEALTH_INBOUND_TAG = "health-in"
DEFAULT_PROXY_TAG = "proxy"
REDACTED = "***"


def new_health_endpoint() -> ProbeEndpoint:
    """Свободный порт на loopback и учётные данные на одну сессию ядра."""
    return ProbeEndpoint(port=reserve_ports(1)[0], credentials=ProbeCredentials.generate())


def attach_health_inbound(config: dict[str, Any], endpoint: ProbeEndpoint) -> dict[str, Any]:
    """Добавить в конфиг сессии inbound проверки и правило для него. Меняет `config`."""
    outbounds = config.get("outbounds") or []
    proxy_tag = (outbounds[0].get("tag") if outbounds else None) or DEFAULT_PROXY_TAG

    config.setdefault("inbounds", []).append(build_probe_inbound(HEALTH_INBOUND_TAG, endpoint))
    config.setdefault("routing", {}).setdefault("rules", []).insert(
        0,
        {"type": "field", "inboundTag": [HEALTH_INBOUND_TAG], "outboundTag": proxy_tag},
    )
    return config


def redact_health_credentials(config: dict[str, Any]) -> dict[str, Any]:
    """Копия конфига без учётных данных inbound'а проверки — для записи на диск."""
    redacted = copy.deepcopy(config)
    for inbound in redacted.get("inbounds", []):
        if inbound.get("tag") == HEALTH_INBOUND_TAG:
            inbound["settings"]["accounts"] = [{"user": REDACTED, "pass": REDACTED}]
    return redacted
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_health_probe.py tests/test_core_connection.py tests/test_core_context.py -q`
Expected: PASS — все passed, в том числе три теста с настоящим ядром.

**Step 5: Commit**

```bash
git add src/core/connection.py src/core/context.py src/core/health_probe.py \
        tests/test_core_connection.py tests/test_core_context.py \
        tests/test_core_health_probe.py
git commit -m "feat(core): служебный inbound проверки соединения в рабочем конфиге"
```

---

### Task 7: Монитор проверяет сервер, а не процесс

`_check_proxy_status` остаётся проверкой процесса. После неё фоновая проверка
делает один запрос к `monitoring.test_url` через `health-in` (таймаут 5 с):
ответа нет — статус «Сервер не отвечает». Это приёмка P4: процесс жив, сервер
молчит, статус — ошибка.

Тонкости:

- **Ручная проверка в сеть не ходит** (`_run_check(defer=False)`): она идёт из
  главного цикла. Она берёт прошлый вердикт (`_server_ok`) и запускает фоновую
  проверку через `_start_background_check()`.
- `ConnectionStatus.server_probed` отличает свежий ответ сервера от повторённого
  вердикта — по нему автопереключение (задача 8) не считает одну неудачу дважды.
- При смене статуса монитор будит слушателей `proxy_state`: окно перерисовывает
  страницу «Мониторинг» по ним. Раньше новый статус появлялся на странице только
  с очередным изменением счётчика трафика.
- Без `health_endpoint` (прокси поднят не через `ConnectionService`) поведение
  прежнее: проверяется только процесс.

**Files:**
- Modify: `src/core/monitor.py`
- Test: `tests/test_core_monitor.py`

**Step 1: Написать падающие тесты**

Изменить `tests/test_core_monitor.py`:

```diff
--- a/tests/test_core_monitor.py
+++ b/tests/test_core_monitor.py
@@ -5,7 +5,12 @@ from types import SimpleNamespace
 from unittest.mock import MagicMock, Mock, patch
 
 from src.core.context import AppContext
-from src.core.monitor import ConnectionMonitor, ConnectionStatus
+from src.core.http_probe import ProbeCredentials, ProbeEndpoint
+from src.core.monitor import (
+    HEALTH_PROBE_TIMEOUT_SECONDS,
+    ConnectionMonitor,
+    ConnectionStatus,
+)
 from src.core.xray_manager import TrafficStats
 
 
@@ -731,3 +736,150 @@ def test_resume_monitoring_leaves_a_stopped_proxy_alone(tmp_path):
     TengaApplication.resume_monitoring(SimpleNamespace(context=context))
 
     monitor.start.assert_not_called()
+
+
+# --- настоящая проверка соединения: запрос через служебный inbound ---
+
+HEALTH = ProbeEndpoint(port=41500, credentials=ProbeCredentials("health", "secret"))
+
+
+def _running_context(tmp_path, *, endpoint=HEALTH):
+    """Прокси запущен, процесс ядра жив; сервер — как ответит подменённая проба."""
+    context = AppContext(config_dir=tmp_path)
+    context.config.monitoring.enabled = True
+    context.proxy_state.is_running = True
+    context.proxy_state.health_endpoint = endpoint
+
+    manager = MagicMock()
+    manager._check_process_alive.return_value = True
+    manager.get_version.return_value = {"version": "26.9.9"}
+    context._xray_manager = manager
+    return context
+
+
+def _background_check(monitor, monkeypatch):
+    """Фоновая проверка целиком, с доставкой результата как из главного цикла."""
+    monkeypatch.setattr("gi.repository.GLib.idle_add", lambda callback, *args: callback(*args))
+    monkeypatch.setattr(monitor, "_check_vpn_status", lambda: (True, ""))
+    monitor._run_check()
+
+
+def test_status_is_error_when_the_process_is_alive_but_the_server_is_silent(tmp_path, monkeypatch):
+    monitor = ConnectionMonitor(_running_context(tmp_path))
+    monkeypatch.setattr("src.core.monitor.measure_latency", lambda *_a, **_k: -1)
+
+    _background_check(monitor, monkeypatch)
+
+    assert monitor.status.proxy_ok is False
+    assert monitor.status.proxy_error == "Сервер не отвечает"
+    assert monitor.status.server_probed is True
+
+
+def test_server_probe_requests_the_configured_url_through_the_health_inbound(tmp_path, monkeypatch):
+    context = _running_context(tmp_path)
+    context.config.monitoring.test_url = "https://example.com/ping"
+    monitor = ConnectionMonitor(context)
+    seen: dict = {}
+
+    def fake_measure(endpoint, url, **kwargs):
+        seen.update(endpoint=endpoint, url=url, **kwargs)
+        return 120
+
+    monkeypatch.setattr("src.core.monitor.measure_latency", fake_measure)
+
+    _background_check(monitor, monkeypatch)
+
+    assert monitor.status.proxy_ok is True
+    assert seen == {
+        "endpoint": HEALTH,
+        "url": "https://example.com/ping",
+        "timeout": HEALTH_PROBE_TIMEOUT_SECONDS,
+        "probes": 1,
+    }
+
+
+def test_dead_process_is_reported_without_probing_the_server(tmp_path, monkeypatch):
+    context = _running_context(tmp_path)
+    context._xray_manager._check_process_alive.return_value = False
+    monitor = ConnectionMonitor(context)
+    probe = Mock(return_value=120)
+    monkeypatch.setattr("src.core.monitor.measure_latency", probe)
+
+    _background_check(monitor, monkeypatch)
+
+    assert monitor.status.proxy_ok is False
+    assert monitor.status.proxy_error == "Процесс xray-core не запущен"
+    assert monitor.status.server_probed is False
+    probe.assert_not_called()
+
+
+def test_without_a_health_endpoint_only_the_process_is_checked(tmp_path, monkeypatch):
+    monitor = ConnectionMonitor(_running_context(tmp_path, endpoint=None))
+    probe = Mock(return_value=-1)
+    monkeypatch.setattr("src.core.monitor.measure_latency", probe)
+
+    _background_check(monitor, monkeypatch)
+
+    assert monitor.status.proxy_ok is True
+    assert monitor.status.server_probed is False
+    probe.assert_not_called()
+
+
+def test_manual_check_does_not_send_requests_from_the_main_loop(tmp_path, monkeypatch):
+    """«Обновить сейчас» не должна замораживать окно на время сетевого запроса."""
+    monitor = ConnectionMonitor(_running_context(tmp_path))
+    probe = Mock(return_value=120)
+    background = Mock()
+    monkeypatch.setattr("src.core.monitor.measure_latency", probe)
+    monkeypatch.setattr(monitor, "_start_background_check", background)
+    monkeypatch.setattr(monitor, "_check_vpn_status", lambda: (True, ""))
+
+    monitor.check_now()
+
+    probe.assert_not_called()
+    background.assert_called_once()
+    assert monitor.status.proxy_ok is True
+    assert monitor.status.server_probed is False
+
+
+def test_manual_check_keeps_the_last_server_verdict(tmp_path, monkeypatch):
+    monitor = ConnectionMonitor(_running_context(tmp_path))
+    monkeypatch.setattr("src.core.monitor.measure_latency", lambda *_a, **_k: -1)
+    _background_check(monitor, monkeypatch)
+    monkeypatch.setattr(monitor, "_start_background_check", Mock())
+
+    monitor.check_now()
+
+    assert monitor.status.proxy_ok is False
+    assert monitor.status.proxy_error == "Сервер не отвечает"
+
+
+def test_stop_forgets_the_server_verdict(tmp_path, monkeypatch):
+    monitor = ConnectionMonitor(_running_context(tmp_path))
+    monkeypatch.setattr("src.core.monitor.measure_latency", lambda *_a, **_k: -1)
+    _background_check(monitor, monkeypatch)
+
+    monitor.stop()
+    monkeypatch.setattr(monitor, "_start_background_check", Mock())
+    monitor.check_now()
+
+    assert monitor.status.proxy_ok is True
+
+
+def test_status_change_wakes_up_the_state_listeners(tmp_path, monkeypatch):
+    """Окно перерисовывается по слушателям состояния: без этого новый статус
+
+    появился бы на странице только со следующим изменением счётчика трафика.
+    """
+    context = _running_context(tmp_path)
+    monitor = ConnectionMonitor(context)
+    woken: list = []
+    context.proxy_state.add_listener(lambda _state: woken.append(True))
+    answers = iter([120, 120, -1])
+    monkeypatch.setattr("src.core.monitor.measure_latency", lambda *_a, **_k: next(answers))
+
+    _background_check(monitor, monkeypatch)  # недоступен → доступен
+    _background_check(monitor, monkeypatch)  # без изменений
+    _background_check(monitor, monkeypatch)  # доступен → сервер молчит
+
+    assert len(woken) == 2
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_monitor.py -q`
Expected: FAIL — ошибка сбора, `cannot import name 'HEALTH_PROBE_TIMEOUT_SECONDS'`.

**Step 3: Реализовать**

Изменить `src/core/monitor.py`:

```diff
--- a/src/core/monitor.py
+++ b/src/core/monitor.py
@@ -7,13 +7,18 @@ from collections.abc import Callable
 from dataclasses import dataclass
 from typing import TYPE_CHECKING
 
+from src.core.http_probe import measure_latency
 from src.core.performance import measure_time
 
 if TYPE_CHECKING:
     from src.core.context import AppContext
+    from src.core.http_probe import ProbeEndpoint
 
 logger = logging.getLogger("tenga.core.monitor")
 
+HEALTH_PROBE_TIMEOUT_SECONDS = 5.0
+SERVER_SILENT = "Сервер не отвечает"
+
 
 @dataclass
 class ConnectionStatus:
@@ -24,6 +29,8 @@ class ConnectionStatus:
     last_check_time: float = 0.0
     proxy_error: str = ""
     vpn_error: str = ""
+    # True — в этой проверке сервер опрашивался запросом, а не взят прошлый вердикт.
+    server_probed: bool = False
 
 
 class ConnectionMonitor:
@@ -31,7 +38,7 @@ class ConnectionMonitor:
     Monitor proxy and VPN connection status.
 
     Periodically checks:
-    - Proxy: xray-core process status + version check
+    - Proxy: xray-core process status, then a request through the health inbound
     - VPN: NetworkManager connection status (if VPN integration enabled)
     """
 
@@ -48,6 +55,9 @@ class ConnectionMonitor:
         self._traffic_in_progress = False
         self._check_in_progress = False
         self._check_generation = 0
+        # Последний вердикт сетевой пробы: ручная проверка идёт из главного
+        # цикла и сама в сеть не ходит.
+        self._server_ok = True
         self._status = ConnectionStatus()
         self._previous_status = ConnectionStatus()
         self._on_status_changed: Callable[[ConnectionStatus, ConnectionStatus], None] | None = None
@@ -99,6 +109,7 @@ class ConnectionMonitor:
         # skip forever.
         self._check_in_progress = False
         self._traffic_in_progress = False
+        self._server_ok = True
 
         # Таймер трафика снимается до раннего возврата: он заводится вместе с
         # основным, но пережил бы его, если выйти раньше.
@@ -146,14 +157,19 @@ class ConnectionMonitor:
                 logger.debug("Previous connection check still running, skipping tick")
             return True
 
-        # Run checks in background thread
+        self._start_background_check()
+        return True
+
+    def _start_background_check(self) -> None:
+        """Run one full check, with the server probe, off the main loop."""
+        if self._check_in_progress:
+            return
+
         self._check_in_progress = True
         self._check_generation += 1
         generation = self._check_generation
         threading.Thread(target=self._do_check_async, args=(generation,), daemon=True).start()
 
-        return True
-
     def refresh_traffic(self) -> None:
         """Pull the traffic counters into the shared state.
 
@@ -258,6 +274,17 @@ class ConnectionMonitor:
         logger.info("Proxy check: SUCCESS (xray-core running)")
         return True, ""
 
+    def _probe_server(self, endpoint: ProbeEndpoint) -> bool:
+        """Ask the server through the health inbound. Blocks: background thread only."""
+        url = self._context.config.monitoring.test_url
+        latency = measure_latency(endpoint, url, timeout=HEALTH_PROBE_TIMEOUT_SECONDS, probes=1)
+        if latency < 0:
+            logger.warning("Proxy check: no answer from the server through the proxy")
+            return False
+
+        logger.debug("Proxy check: server answered in %d ms", latency)
+        return True
+
     def _check_vpn_status(self) -> tuple[bool, str]:
         """
         Check VPN connection status.
@@ -334,6 +361,9 @@ class ConnectionMonitor:
         отдавать его главному циклу, а ручная идёт из него самого и должна
         применить результат сразу — иначе нажатие «Обновить сейчас» оставляет
         страницу нетронутой до следующего тика.
+
+        Сервер опрашивает только фоновая проверка: запрос может длиться до
+        таймаута, а главный цикл ждать не должен. Ручная берёт прошлый вердикт.
         """
         # Save previous status
         previous_status = ConnectionStatus(
@@ -342,9 +372,18 @@ class ConnectionMonitor:
             last_check_time=self._status.last_check_time,
             proxy_error=self._status.proxy_error,
             vpn_error=self._status.vpn_error,
+            server_probed=self._status.server_probed,
         )
 
         proxy_ok, proxy_error = self._check_proxy_status()
+        server_probed = False
+        endpoint = self._context.proxy_state.health_endpoint
+        if proxy_ok and endpoint is not None:
+            if defer:
+                self._server_ok = self._probe_server(endpoint)
+                server_probed = True
+            if not self._server_ok:
+                proxy_ok, proxy_error = False, SERVER_SILENT
         if logger.isEnabledFor(logging.DEBUG):
             logger.debug(
                 "Proxy status: %s (%s)", "OK" if proxy_ok else "FAIL", proxy_error or "no error"
@@ -365,6 +404,7 @@ class ConnectionMonitor:
             last_check_time=time.time(),
             proxy_error=proxy_error,
             vpn_error=vpn_error,
+            server_probed=server_probed,
         )
 
         if not defer:
@@ -391,6 +431,9 @@ class ConnectionMonitor:
         self._previous_status = previous_status
         self._status = new_status
         self._notify_status_changed()
+        if self._status_changed():
+            # Окно и трей перерисовываются по слушателям состояния прокси.
+            self._context.proxy_state.notify_listeners()
         if logger.isEnabledFor(logging.DEBUG):
             logger.debug("Status updated and UI notified")
         return False  # Remove from idle queue
@@ -446,6 +489,9 @@ class ConnectionMonitor:
             # нажатие «Обновить сейчас» не делало бы ничего.
             self._run_check(defer=False)
             self._notify_ui_update()
+            if self._context.proxy_state.health_endpoint is not None:
+                # Свежий ответ сервера придёт из фонового потока.
+                self._start_background_check()
         finally:
             if not was_enabled:
                 self._context.config.monitoring.enabled = False
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_monitor.py -q`
Expected: PASS — все passed, включая прежние тесты монитора.

**Step 5: Commit**

```bash
git add src/core/monitor.py tests/test_core_monitor.py
git commit -m "feat(core): проверять соединение запросом через прокси, а не по живости процесса"
```

---

### Task 8: Автопереключение — решение и выбор профиля

> **Необязательная:** задачи 8 и 9 можно вычеркнуть без последствий для
> остальных.

`FailoverController.handle_status` получает каждый статус монитора и решает,
переключать ли профиль. Правила:

- считаются только статусы со свежим ответом сервера (`server_probed`);
- успешная проверка обнуляет счётчик;
- если сети нет вовсе (`network_available()` — ложь), неудача не засчитывается:
  сервер тут ни при чём;
- по достижении порога текущий профиль запоминается как «недавно упавший» на
  15 минут, и выбирается кандидат **из той же группы**: сначала профили с
  измеренной задержкой, по возрастанию, затем остальные в порядке списка;
- кандидатов нет — одно сообщение, подключение остаётся («Принятые решения»,
  пункт 3);
- смена профиля — вручную или самим переключением — начинает счёт заново.

Отличие от Android: там недавно упавшие профили определяются по записанному
времени замера (`lastLatencyAt`), здесь — по памяти контроллера. В
`ProfileEntry` нет времени замера, а `latency_ms == -1` означает и «не
мерили», и «не ответил»; заводить поле ради этого незачем.

Известное ограничение: если кандидат таков, что ядро отвергает его конфиг,
подключение к нему не состоится и прокси останется выключенным — как при любой
неудачной ручной смене профиля. Профили с измеренной задержкой идут первыми как
раз поэтому: их ядро уже принимало.

**Files:**
- Create: `src/core/failover.py`
- Modify: `src/db/config.py` (`MonitoringSettings`)
- Test: `tests/test_core_failover.py`, `tests/test_db_config_monitoring.py`

**Step 1: Написать падающие тесты**

Создать `tests/test_core_failover.py`:

```python
"""Автопереключение на другой профиль группы, когда сервер перестал отвечать."""

from __future__ import annotations

from types import SimpleNamespace

from src.core.failover import RECENT_FAILURE_TTL_SECONDS, FailoverController, pick_candidate
from src.core.monitor import ConnectionStatus

SILENT = ConnectionStatus(proxy_ok=False, proxy_error="Сервер не отвечает", server_probed=True)
ALIVE = ConnectionStatus(proxy_ok=True, server_probed=True)


def profile(profile_id: int, latency_ms: int = -1, group_id: int = 1):
    return SimpleNamespace(
        id=profile_id, group_id=group_id, latency_ms=latency_ms, name=f"P{profile_id}"
    )


# --- выбор кандидата ---


def test_candidate_with_the_lowest_known_latency_wins():
    profiles = [profile(1, 50), profile(2, 300), profile(3, 120), profile(4, -1)]

    assert pick_candidate(profiles, excluded={1}).id == 3


def test_unmeasured_profiles_come_after_measured_ones_in_list_order():
    profiles = [profile(1, 50), profile(2, -1), profile(3, -1), profile(4, 900)]

    assert pick_candidate(profiles, excluded={1}).id == 4
    assert pick_candidate(profiles, excluded={1, 4}).id == 2


def test_no_candidate_when_everything_is_excluded():
    profiles = [profile(1, 50), profile(2, 80)]

    assert pick_candidate(profiles, excluded={1, 2}) is None
    assert pick_candidate([], excluded=set()) is None


# --- решение «переключать или нет» ---


class Harness:
    """Контроллер с подменённым окружением: профили, время, сеть, действия."""

    def __init__(self, profiles, *, enabled=True, threshold=3, current=1):
        self.profiles = {item.id: item for item in profiles}
        self.switched: list[int] = []
        self.messages: list[str] = []
        self.clock = 1000.0
        self.online = True
        self.state = SimpleNamespace(is_running=True, started_profile_id=current)
        self.monitoring = SimpleNamespace(failover_enabled=enabled, failover_threshold=threshold)
        context = SimpleNamespace(
            proxy_state=self.state,
            config=SimpleNamespace(monitoring=self.monitoring),
            profiles=SimpleNamespace(
                get_profile=self.profiles.get,
                get_profiles_in_group=lambda group_id: [
                    item for item in self.profiles.values() if item.group_id == group_id
                ],
            ),
        )
        self.controller = FailoverController(
            context,
            switch_to=self._switch,
            notify=self.messages.append,
            network_available=lambda: self.online,
            now=lambda: self.clock,
        )

    def _switch(self, profile_id: int) -> None:
        self.switched.append(profile_id)
        self.state.started_profile_id = profile_id

    def feed(self, *statuses: ConnectionStatus) -> None:
        for status in statuses:
            self.controller.handle_status(status, status)


def test_switches_after_the_threshold_of_consecutive_failures():
    harness = Harness([profile(1, 50), profile(2, 80)])

    harness.feed(SILENT, SILENT)
    assert harness.switched == []

    harness.feed(SILENT)
    assert harness.switched == [2]


def test_switch_is_announced_with_both_profile_names():
    harness = Harness([profile(1, 50), profile(2, 80)])

    harness.feed(SILENT, SILENT, SILENT)

    assert len(harness.messages) == 1
    assert "P1" in harness.messages[0]
    assert "P2" in harness.messages[0]


def test_a_successful_check_resets_the_counter():
    harness = Harness([profile(1, 50), profile(2, 80)])

    harness.feed(SILENT, SILENT, ALIVE, SILENT, SILENT)

    assert harness.switched == []


def test_nothing_happens_while_failover_is_disabled():
    harness = Harness([profile(1, 50), profile(2, 80)], enabled=False)

    harness.feed(SILENT, SILENT, SILENT, SILENT)

    assert harness.switched == []
    assert harness.messages == []


def test_statuses_without_a_fresh_server_probe_are_not_counted():
    """Ручная проверка повторяет прошлый вердикт: считать её — значит считать дважды."""
    harness = Harness([profile(1, 50), profile(2, 80)])
    stale = ConnectionStatus(proxy_ok=False, proxy_error="Сервер не отвечает", server_probed=False)

    harness.feed(stale, stale, stale, stale)

    assert harness.switched == []


def test_failures_without_network_are_not_blamed_on_the_server():
    harness = Harness([profile(1, 50), profile(2, 80)])
    harness.online = False

    harness.feed(SILENT, SILENT, SILENT, SILENT)

    assert harness.switched == []


def test_candidates_come_only_from_the_group_of_the_active_profile():
    harness = Harness([profile(1, 50), profile(2, 10, group_id=2), profile(3, 400)])

    harness.feed(SILENT, SILENT, SILENT)

    assert harness.switched == [3]


def test_recently_failed_profiles_are_skipped():
    harness = Harness([profile(1, 50), profile(2, 80), profile(3, 200)])

    harness.feed(SILENT, SILENT, SILENT)  # 1 → 2
    harness.feed(SILENT, SILENT, SILENT)  # 2 → 3, а не обратно на 1

    assert harness.switched == [2, 3]


def test_failed_profile_becomes_a_candidate_again_after_the_ttl():
    harness = Harness([profile(1, 50), profile(2, 80)])

    harness.feed(SILENT, SILENT, SILENT)  # 1 → 2
    harness.clock += RECENT_FAILURE_TTL_SECONDS + 1
    harness.feed(SILENT, SILENT, SILENT)  # 2 → 1

    assert harness.switched == [2, 1]


def test_exhausted_group_is_reported_once_and_the_connection_is_kept():
    harness = Harness([profile(1, 50), profile(2, 80)])

    harness.feed(SILENT, SILENT, SILENT)  # 1 → 2
    harness.feed(SILENT, SILENT, SILENT)  # кандидатов нет
    harness.feed(SILENT, SILENT, SILENT)  # и снова нет — без повторного сообщения

    assert harness.switched == [2]
    assert len(harness.messages) == 2
    assert "нет" in harness.messages[1]
    assert harness.state.is_running is True


def test_manual_switch_to_another_profile_restarts_the_count():
    harness = Harness([profile(1, 50), profile(2, 80), profile(3, 90)])

    harness.feed(SILENT, SILENT)
    harness.state.started_profile_id = 3  # пользователь подключился сам
    harness.feed(SILENT, SILENT)

    assert harness.switched == []


def test_stopped_proxy_resets_the_count():
    harness = Harness([profile(1, 50), profile(2, 80)])

    harness.feed(SILENT, SILENT)
    harness.state.is_running = False
    harness.feed(SILENT)
    harness.state.is_running = True
    harness.feed(SILENT, SILENT)

    assert harness.switched == []
```

Изменить `tests/test_db_config_monitoring.py`:

```diff
--- a/tests/test_db_config_monitoring.py
+++ b/tests/test_db_config_monitoring.py
@@ -101,3 +101,26 @@ def test_monitoring_settings_in_data_store(tmp_path):
     assert loaded.monitoring.enabled is True
     assert loaded.monitoring.check_interval_seconds == 30
     assert loaded.monitoring.test_url == "https://www.google.com/generate_204"
+
+
+def test_failover_is_off_by_default():
+    settings = MonitoringSettings()
+
+    assert settings.failover_enabled is False
+    assert settings.failover_threshold == 3
+
+
+def test_failover_settings_survive_serialization():
+    settings = MonitoringSettings(failover_enabled=True, failover_threshold=5)
+
+    restored = MonitoringSettings.from_dict(settings.to_dict())
+
+    assert restored.failover_enabled is True
+    assert restored.failover_threshold == 5
+
+
+def test_settings_saved_before_failover_existed_still_load():
+    restored = MonitoringSettings.from_dict({"enabled": True, "check_interval_seconds": 15})
+
+    assert restored.failover_enabled is False
+    assert restored.failover_threshold == 3
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_failover.py tests/test_db_config_monitoring.py -q`
Expected: FAIL — ошибка сбора, `No module named 'src.core.failover'`.

**Step 3: Реализовать**

Создать `src/core/failover.py`:

```python
"""Автопереключение на другой профиль группы, когда сервер перестал отвечать.

Без GTK: решение принимается по статусам монитора, а подключение и уведомление
передаются снаружи. Источник вердикта — сетевая проба через служебный inbound,
поэтому «сервер молчит» здесь значит именно сервер, а не правила маршрутизации.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Collection, Sequence
from typing import Any

logger = logging.getLogger("tenga.core.failover")

# Сколько не возвращаться к профилю, который только что перестал отвечать.
RECENT_FAILURE_TTL_SECONDS = 15 * 60


def pick_candidate(profiles: Sequence[Any], *, excluded: Collection[int]) -> Any | None:
    """Профиль, на который переключаться: сначала с известной задержкой, по возрастанию.

    Профили без замера идут после измеренных, в порядке списка: про них ничего
    не известно, а измеренный хотя бы отвечал.
    """
    candidates = [profile for profile in profiles if profile.id not in excluded]
    measured = sorted(
        (profile for profile in candidates if profile.latency_ms > 0),
        key=lambda profile: profile.latency_ms,
    )
    unmeasured = [profile for profile in candidates if profile.latency_ms <= 0]
    ordered = measured + unmeasured
    return ordered[0] if ordered else None


class FailoverController:
    """Считает неудачные проверки подряд и переключает профиль по порогу."""

    def __init__(
        self,
        context: Any,
        *,
        switch_to: Callable[[int], None],
        notify: Callable[[str], None],
        network_available: Callable[[], bool] = lambda: True,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._context = context
        self._switch_to = switch_to
        self._notify = notify
        self._network_available = network_available
        self._now = now
        self._profile_id = -1
        self._failures = 0
        self._exhausted = False
        self._failed_at: dict[int, float] = {}

    def handle_status(self, _previous: Any, status: Any) -> None:
        """Принять результат очередной проверки монитора (главный цикл)."""
        settings = self._context.config.monitoring
        state = self._context.proxy_state

        if not settings.failover_enabled or not state.is_running:
            self._reset(-1)
            return

        # Ручная проверка повторяет прошлый вердикт без запроса к серверу.
        if not status.server_probed:
            return

        current = state.started_profile_id
        if current != self._profile_id:
            # Подключён другой профиль — вручную или нашим же переключением.
            self._reset(current)

        if status.proxy_ok:
            self._failures = 0
            self._exhausted = False
            return

        if not self._network_available():
            # Сети нет вовсе: сервер тут ни при чём, перебирать профили незачем.
            self._failures = 0
            return

        self._failures += 1
        if self._failures < max(1, settings.failover_threshold):
            return

        self._failures = 0
        self._switch_from(current)

    def _reset(self, profile_id: int) -> None:
        self._profile_id = profile_id
        self._failures = 0
        self._exhausted = False

    def _switch_from(self, failed_id: int) -> None:
        profiles = self._context.profiles
        failed = profiles.get_profile(failed_id)
        if failed is None:
            return

        now = self._now()
        self._failed_at[failed_id] = now
        recent = {
            profile_id
            for profile_id, failed_at in self._failed_at.items()
            if now - failed_at < RECENT_FAILURE_TTL_SECONDS
        }

        candidate = pick_candidate(profiles.get_profiles_in_group(failed.group_id), excluded=recent)
        if candidate is None:
            if not self._exhausted:
                self._exhausted = True
                logger.warning("Failover: no candidates left in group %s", failed.group_id)
                self._notify(f"«{failed.name}» не отвечает, других рабочих профилей в группе нет")
            return

        logger.warning("Failover: switching from profile %s to %s", failed_id, candidate.id)
        self._notify(f"«{failed.name}» не отвечает — переключаюсь на «{candidate.name}»")
        self._switch_to(candidate.id)
```

Изменить `src/db/config.py`:

```diff
--- a/src/db/config.py
+++ b/src/db/config.py
@@ -520,3 +520,7 @@ class MonitoringSettings(ConfigBase):
     enabled: bool = True
     check_interval_seconds: int = 10
     test_url: str = "https://www.google.com/generate_204"
+    # Автопереключение: после стольких неудачных проверок подряд подключается
+    # другой профиль той же группы. Выключено, пока пользователь не включит сам.
+    failover_enabled: bool = False
+    failover_threshold: int = 3
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_failover.py tests/test_db_config_monitoring.py -q`
Expected: PASS — все passed.

**Step 5: Commit**

```bash
git add src/core/failover.py src/db/config.py tests/test_core_failover.py \
        tests/test_db_config_monitoring.py
git commit -m "feat(core): автопереключение на другой профиль группы при молчащем сервере"
```

---

### Task 9: Автопереключение — настройки и уведомление

> **Необязательная**, вместе с задачей 8.

- `TengaApplication.watch_monitor()` подписывает контроллер на монитор
  (`set_on_status_changed` до этого никто не использовал). Подписка
  безусловная: при выключенной настройке контроллер ничего не делает.
- Переключение — обычный `connect_profile`, тот же путь, что у ручного.
- `notify_user()` — тост и `Gio.Notification`: окно обычно свёрнуто в трей, и
  один тост пользователь не увидит.
- Признак «сеть есть» — `Gio.NetworkMonitor`.
- В «Настройки» → «Мониторинг» — группа «Автопереключение»: тумблер и порог
  (1–10 неудачных проверок подряд). Без мониторинга обе строки гаснут.

**Files:**
- Modify: `src/ui/application.py`
- Modify: `src/ui/dialogs/settings.py` (`_build_monitoring_page`, `_sync_monitoring`, `_load`, `save`)
- Test: `tests/test_ui_application.py`, `tests/test_ui_dialogs_settings.py` (GTK)

**Step 1: Написать падающие тесты**

Изменить `tests/test_ui_application.py`:

```diff
--- a/tests/test_ui_application.py
+++ b/tests/test_ui_application.py
@@ -579,6 +579,55 @@ def test_default_latency_run_measures_the_whole_set_with_one_batch_call(adw_app,
     assert store.get_profile(second.id).latency_ms == 42
 
 
+def _silent_server_status():
+    from src.core.monitor import ConnectionStatus
+
+    return ConnectionStatus(proxy_ok=False, proxy_error="Сервер не отвечает", server_probed=True)
+
+
+def _watched_monitor(app, *, failover_enabled: bool):
+    from src.core.monitor import attach_monitor
+
+    context = app.context
+    context.config.monitoring.failover_enabled = failover_enabled
+    context.config.monitoring.failover_threshold = 1
+    monitor = attach_monitor(context)
+    app.watch_monitor()
+    return monitor
+
+
+def test_failover_connects_the_next_profile_of_the_group_and_says_so(adw_app):
+    first = add_profile(adw_app)
+    second = add_profile(adw_app)
+    calls = []
+    adw_app.set_connection_service(FakeService(calls))
+    adw_app.context.proxy_state.set_running(first.id)
+    monitor = _watched_monitor(adw_app, failover_enabled=True)
+
+    monitor._status = _silent_server_status()
+    monitor._notify_status_changed()
+    adw_app.wait_for_connection_for_test()
+
+    assert calls == [("connect", second.id)]
+    assert "переключаюсь" in adw_app.last_notification_for_test
+
+
+def test_failover_stays_out_of_the_way_when_disabled(adw_app):
+    first = add_profile(adw_app)
+    add_profile(adw_app)
+    calls = []
+    adw_app.set_connection_service(FakeService(calls))
+    adw_app.context.proxy_state.set_running(first.id)
+    monitor = _watched_monitor(adw_app, failover_enabled=False)
+
+    monitor._status = _silent_server_status()
+    monitor._notify_status_changed()
+    adw_app.wait_for_connection_for_test()
+
+    assert calls == []
+    assert adw_app.last_notification_for_test == ""
+
+
 def _simulate_close(app, dialog) -> None:
     """Release the slot the way the `closed` signal would.
 
```

Изменить `tests/test_ui_dialogs_settings.py`:

```diff
--- a/tests/test_ui_dialogs_settings.py
+++ b/tests/test_ui_dialogs_settings.py
@@ -88,6 +88,38 @@ def test_disabled_monitoring_dims_the_interval(gtk_ready):
     assert not dialog.interval_row.get_sensitive()
 
 
+def test_failover_settings_round_trip(gtk_ready):
+    config = make_config()
+    dialog = make_dialog(config)
+    assert not dialog.failover_row.get_active()
+
+    dialog.failover_row.set_active(True)
+    dialog.failover_threshold_row.set_value(5)
+    dialog.save()
+
+    assert config.monitoring.failover_enabled
+    assert config.monitoring.failover_threshold == 5
+
+
+def test_failover_threshold_is_dimmed_until_failover_is_on(gtk_ready):
+    dialog = make_dialog()
+    dialog.monitoring_row.set_active(True)
+    assert not dialog.failover_threshold_row.get_sensitive()
+
+    dialog.failover_row.set_active(True)
+    assert dialog.failover_threshold_row.get_sensitive()
+
+
+def test_disabled_monitoring_dims_failover(gtk_ready):
+    """Без мониторинга проверок нет — переключаться не по чему."""
+    dialog = make_dialog()
+    dialog.failover_row.set_active(True)
+    dialog.monitoring_row.set_active(False)
+
+    assert not dialog.failover_row.get_sensitive()
+    assert not dialog.failover_threshold_row.get_sensitive()
+
+
 def test_the_dns_provider_round_trips(gtk_ready):
     config = make_config()
     dialog = make_dialog(config)
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest -m gtk tests/test_ui_application.py tests/test_ui_dialogs_settings.py -q`
Expected: FAIL — пять новых тестов: `AttributeError` на `failover_row` и `watch_monitor`.

**Step 3: Реализовать**

Изменить `src/ui/application.py`:

```diff
--- a/src/ui/application.py
+++ b/src/ui/application.py
@@ -14,6 +14,7 @@ gi.require_version("Adw", "1")
 from gi.repository import Adw, Gio, GLib, Gtk
 
 from src.core.context import AppContext, get_context
+from src.core.failover import FailoverController
 from src.ui.logic.async_utils import run_in_background
 from src.ui.logic.latency import LatencyRunner, make_batch_probe
 from src.ui.logic.profiles_view import SortKey
@@ -30,6 +31,13 @@ if TYPE_CHECKING:
 logger = logging.getLogger("tenga.ui.application")
 
 APP_ID = "ru.tenga.Proxy"
+FAILOVER_NOTIFICATION_ID = "failover"
+
+
+def _network_available() -> bool:
+    """Whether the machine has a network at all, as the desktop sees it."""
+    return Gio.NetworkMonitor.get_default().get_network_available()
+
 
 # Действия и их ускорители. Один набор обслуживает меню, контекстные меню,
 # клавиатуру и трей — как описано в дизайн-документе.
@@ -70,7 +78,9 @@ class TengaApplication(Adw.Application):
         self._connection_service = None
         self._connection_thread = None
         self._dialog = None
+        self._failover: FailoverController | None = None
         self.last_toast_for_test = ""
+        self.last_notification_for_test = ""
 
     # Жизненный цикл
 
@@ -80,6 +90,7 @@ class TengaApplication(Adw.Application):
         load_css()
         self._register_actions()
         self._setup_signal_handlers()
+        self.watch_monitor()
         if self._with_tray:
             self.start_tray()
 
@@ -101,6 +112,37 @@ class TengaApplication(Adw.Application):
             return
         monitor.start()
 
+    def watch_monitor(self) -> None:
+        """Hand the monitor's verdicts to the failover controller.
+
+        Контроллер сам смотрит в настройки и при выключенном автопереключении
+        ничего не делает, поэтому подписка ставится безусловно.
+        """
+        monitor = self.context.monitor
+        if monitor is None:
+            return
+
+        self._failover = FailoverController(
+            self.context,
+            switch_to=self.connect_profile,
+            notify=self.notify_user,
+            network_available=_network_available,
+        )
+        monitor.set_on_status_changed(self._failover.handle_status)
+
+    def notify_user(self, text: str) -> None:
+        """Tell the user something they must not miss.
+
+        Тост виден только в открытом окне, а приложение обычно свёрнуто в
+        трей — поэтому сообщение дублируется уведомлением рабочего стола.
+        """
+        self.last_notification_for_test = text
+        self.toast(text)
+
+        notification = Gio.Notification.new("Tenga Proxy")
+        notification.set_body(text)
+        self.send_notification(FAILOVER_NOTIFICATION_ID, notification)
+
     def do_shutdown(self) -> None:
         # Выход по SIGTERM не эмитирует close-request, поэтому геометрия
         # сохраняется здесь: этот путь общий для всех способов завершения.
@@ -781,7 +823,9 @@ class TengaApplication(Adw.Application):
         self._connection_service = None
         self._connection_thread = None
         self._dialog = None
+        self._failover = None
         self.last_toast_for_test = ""
+        self.last_notification_for_test = ""
 
     def toast(self, text: str) -> None:
         """Show a message in the window, if there is one."""
```

Изменить `src/ui/dialogs/settings.py`:

```diff
--- a/src/ui/dialogs/settings.py
+++ b/src/ui/dialogs/settings.py
@@ -134,6 +134,23 @@ class SettingsDialog(Adw.PreferencesDialog):
         self.interval_row.set_subtitle("Секунд между проверками")
         group.add(self.interval_row)
 
+        failover = Adw.PreferencesGroup(
+            title="Автопереключение",
+            description=(
+                "Если сервер перестал отвечать, подключается другой профиль той же группы"
+            ),
+        )
+        page.add(failover)
+
+        self.failover_row = Adw.SwitchRow(title="Переключаться автоматически")
+        self.failover_row.connect("notify::active", lambda *_: self._sync_monitoring())
+        failover.add(self.failover_row)
+
+        self.failover_threshold_row = Adw.SpinRow.new_with_range(1, 10, 1)
+        self.failover_threshold_row.set_title("Порог")
+        self.failover_threshold_row.set_subtitle("Неудачных проверок подряд")
+        failover.add(self.failover_threshold_row)
+
     def _build_dns_page(self) -> None:
         page = Adw.PreferencesPage(title="DNS", icon_name="network-server-symbolic")
         self.add(page)
@@ -206,7 +223,11 @@ class SettingsDialog(Adw.PreferencesDialog):
         self.tun_mtu_row.set_sensitive(tun)
 
     def _sync_monitoring(self) -> None:
-        self.interval_row.set_sensitive(self.monitoring_row.get_active())
+        monitoring = self.monitoring_row.get_active()
+        self.interval_row.set_sensitive(monitoring)
+        # Без мониторинга проверок нет — переключаться не по чему.
+        self.failover_row.set_sensitive(monitoring)
+        self.failover_threshold_row.set_sensitive(monitoring and self.failover_row.get_active())
 
     def _load(self) -> None:
         config = self._config
@@ -224,6 +245,8 @@ class SettingsDialog(Adw.PreferencesDialog):
         monitoring = config.monitoring
         self.monitoring_row.set_active(monitoring.enabled)
         self.interval_row.set_value(float(monitoring.check_interval_seconds))
+        self.failover_row.set_active(monitoring.failover_enabled)
+        self.failover_threshold_row.set_value(float(monitoring.failover_threshold))
         self._sync_monitoring()
 
         dns = config.dns
@@ -247,6 +270,8 @@ class SettingsDialog(Adw.PreferencesDialog):
 
         config.monitoring.enabled = self.monitoring_row.get_active()
         config.monitoring.check_interval_seconds = int(self.interval_row.get_value())
+        config.monitoring.failover_enabled = self.failover_row.get_active()
+        config.monitoring.failover_threshold = int(self.failover_threshold_row.get_value())
 
         config.dns.provider = self._dns.selected()
         config.dns.custom_url = self.dns_url_row.get_text().strip()
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest -m gtk tests/test_ui_application.py tests/test_ui_dialogs_settings.py -q`
Expected: PASS — все passed.

**Step 5: Commit**

```bash
git add src/ui/application.py src/ui/dialogs/settings.py tests/test_ui_application.py \
        tests/test_ui_dialogs_settings.py
git commit -m "feat(ui): настройки автопереключения и уведомление о смене профиля"
```

---

### Task 10: Обновления ядра — сравнение версий

`src/core/core_update.py` отвечает на вопрос «что сказать пользователю о версии
ядра», ничего не скачивая:

- `PINNED_CORE_VERSION` — версия, под которую написана сборка конфига. Она же
  закреплена в `core/scripts/install_dev.sh`; тест
  `test_pinned_version_matches_the_install_script` следит, чтобы они совпадали.
- `fetch_releases()` — один GET к GitHub. `/releases/latest` не годится: он
  отдаёт только стабильные релизы, а закреплённая версия — пререлиз.
- `evaluate()` — итог: ядро старее закреплённой версии; доступна новая; всё
  свежее; неизвестно. Пререлиз предлагается, только если установленная версия
  новее последнего стабильного релиза.
- В настройках хранятся новейшие известные версии и время опроса; сам итог не
  хранится — он пересчитывается, и после обновления ядра сообщение исчезает без
  нового запроса.
- Ошибка сети и пустой ответ (исчерпан лимит API) прежних сведений не стирают и
  время опроса не двигают.

**Files:**
- Create: `src/core/core_update.py`
- Modify: `src/db/data_store.py` (`DataStore`)
- Modify: `src/ui/logic/version.py`
- Test: `tests/test_core_core_update.py`, `tests/test_ui_logic_version.py`

**Step 1: Написать падающие тесты**

Создать `tests/test_core_core_update.py`:

```python
"""Проверка обновлений ядра: сравнение версий и разбор релизов GitHub."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.core.core_update import (
    AVAILABLE,
    BEHIND_PINNED,
    CHECK_INTERVAL_SECONDS,
    CURRENT,
    PINNED_CORE_VERSION,
    RELEASES_URL,
    UNKNOWN,
    KnownReleases,
    evaluate,
    fetch_releases,
    is_check_due,
    known_releases,
    newest_releases,
    parse_version,
    refresh_known_releases,
)
from src.db.data_store import DataStore

INSTALL_SCRIPT = Path("core/scripts/install_dev.sh")

# Срез настоящего ответа GitHub от 2026-10-03: только нужные поля.
PAYLOAD = [
    {"tag_name": "v26.9.30", "prerelease": True, "draft": False},
    {"tag_name": "v26.9.9", "prerelease": True, "draft": False},
    {"tag_name": "v26.7.28", "prerelease": True, "draft": False},
    {"tag_name": "v26.3.27", "prerelease": False, "draft": False},
    {"tag_name": "v26.2.6", "prerelease": False, "draft": False},
]
KNOWN = KnownReleases(stable="26.3.27", prerelease="26.9.30")


# --- версии ---


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("26.9.9", (26, 9, 9)),
        ("v26.9.30", (26, 9, 30)),
        ("Xray 26.3.27 (Xray, Penetrates Everything.) 52a412d (go1.27.1 linux/amd64)", (26, 3, 27)),
        ("1.8", (1, 8)),
        ("", None),
        ("—", None),
        ("unknown", None),
    ],
)
def test_parse_version(text, expected):
    assert parse_version(text) == expected


def test_versions_compare_by_numbers_not_by_text():
    assert parse_version("26.9.30") > parse_version("26.9.9")
    assert parse_version("26.10.1") > parse_version("26.9.30")


@pytest.mark.skipif(not INSTALL_SCRIPT.exists(), reason="скрипта установки нет в этой копии")
def test_pinned_version_matches_the_install_script():
    """Версия закреплена в двух местах: в скрипте установки и здесь."""
    match = re.search(r'^\s*XRAY_VERSION="([^"]+)"', INSTALL_SCRIPT.read_text(), re.MULTILINE)

    assert match is not None, "в install_dev.sh нет XRAY_VERSION — этап 1 не выполнен"
    assert match.group(1) == PINNED_CORE_VERSION


# --- релизы GitHub ---


def test_newest_releases_picks_the_newest_stable_and_the_newest_prerelease():
    assert newest_releases(PAYLOAD) == KNOWN


def test_newest_releases_ignores_drafts_and_garbage():
    payload = [
        {"tag_name": "v99.1.1", "prerelease": False, "draft": True},
        {"tag_name": "nightly", "prerelease": True, "draft": False},
        {"prerelease": False},
        "строка вместо объекта",
        {"tag_name": "v26.3.27", "prerelease": False, "draft": False},
    ]

    assert newest_releases(payload) == KnownReleases(stable="26.3.27", prerelease="")


def test_newest_releases_survives_an_unexpected_answer():
    assert newest_releases({"message": "API rate limit exceeded"}) == KnownReleases()


def test_fetch_asks_github_without_any_user_data():
    seen: dict = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return PAYLOAD

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen.update(kwargs)
        return Response()

    assert fetch_releases(get=fake_get) == KNOWN
    assert seen["url"] == RELEASES_URL
    assert seen["headers"] == {
        "Accept": "application/vnd.github+json",
        "User-Agent": "tenga-proxy",
    }
    assert seen["timeout"] > 0
    assert set(seen) == {"url", "headers", "timeout"}


# --- что сказать пользователю ---


def test_prerelease_is_offered_when_a_prerelease_is_installed():
    status = evaluate("26.9.9", KNOWN, pinned="26.9.9")

    assert status.kind == AVAILABLE
    assert status.target == "26.9.30"


def test_prerelease_is_not_offered_to_a_stable_core():
    status = evaluate("26.3.27", KNOWN, pinned="26.3.27")

    assert status.kind == CURRENT


def test_stable_update_is_offered_to_a_stable_core():
    status = evaluate("26.2.6", KNOWN, pinned="26.2.6")

    assert status.kind == AVAILABLE
    assert status.target == "26.3.27"


def test_newest_prerelease_installed_is_current():
    assert evaluate("26.9.30", KNOWN, pinned="26.9.9").kind == CURRENT


def test_core_older_than_the_pinned_version_is_reported_first():
    status = evaluate("26.3.27", KNOWN, pinned="26.9.9")

    assert status.kind == BEHIND_PINNED
    assert status.target == "26.9.9"


def test_nothing_is_claimed_before_the_first_check():
    assert evaluate("26.9.9", KnownReleases(), pinned="26.9.9").kind == UNKNOWN


def test_unreadable_installed_version_is_unknown():
    assert evaluate("—", KNOWN).kind == UNKNOWN


# --- расписание и хранение ---


def test_check_is_due_on_first_run_and_after_the_interval():
    config = DataStore()
    assert is_check_due(config, now=1_000_000) is True

    config.core_update_checked_at = 1_000_000
    assert is_check_due(config, now=1_000_000 + CHECK_INTERVAL_SECONDS - 1) is False
    assert is_check_due(config, now=1_000_000 + CHECK_INTERVAL_SECONDS) is True


def test_refresh_stores_what_github_said_and_when():
    config = DataStore()

    result = refresh_known_releases(config, now=1_700_000_000.9, fetch=lambda: KNOWN)

    assert result == KNOWN
    assert known_releases(config) == KNOWN
    assert config.core_update_checked_at == 1_700_000_000
    assert known_releases(DataStore.from_dict(config.to_dict())) == KNOWN


def test_failed_refresh_keeps_the_previous_knowledge_and_stays_due():
    config = DataStore()
    refresh_known_releases(config, now=1000, fetch=lambda: KNOWN)

    def offline():
        raise OSError("нет сети")

    with pytest.raises(OSError, match="нет сети"):
        refresh_known_releases(config, now=1000 + CHECK_INTERVAL_SECONDS, fetch=offline)

    assert known_releases(config) == KNOWN
    assert config.core_update_checked_at == 1000


def test_empty_answer_does_not_erase_the_previous_knowledge():
    config = DataStore()
    refresh_known_releases(config, now=1000, fetch=lambda: KNOWN)

    refresh_known_releases(config, now=2000, fetch=KnownReleases)

    assert known_releases(config) == KNOWN
    assert config.core_update_checked_at == 1000
```

Изменить `tests/test_ui_logic_version.py`:

```diff
--- a/tests/test_ui_logic_version.py
+++ b/tests/test_ui_logic_version.py
@@ -1,7 +1,9 @@
 from __future__ import annotations
 
 import src
-from src.ui.logic.version import UNKNOWN, app_version, core_version
+from src.core.core_update import AVAILABLE, BEHIND_PINNED, CURRENT, CoreUpdateStatus
+from src.core.core_update import UNKNOWN as UPDATE_UNKNOWN
+from src.ui.logic.version import UNKNOWN, app_version, core_update_text, core_version
 
 
 def test_app_version_comes_from_the_package_itself(monkeypatch):
@@ -49,3 +51,28 @@ def test_core_version_survives_a_failing_manager():
             raise RuntimeError("ядро не найдено")
 
     assert core_version(Manager()) == UNKNOWN
+
+
+# --- обновление ядра ---
+
+
+def test_core_update_text_names_the_available_version():
+    status = CoreUpdateStatus(AVAILABLE, installed="26.9.9", target="26.9.30")
+
+    assert core_update_text(status) == "Доступна версия 26.9.30"
+
+
+def test_core_update_text_warns_about_a_core_older_than_expected():
+    status = CoreUpdateStatus(BEHIND_PINNED, installed="26.3.27", target="26.9.9")
+
+    assert core_update_text(status) == "Ядро старее версии 26.9.9, на которую рассчитано приложение"
+
+
+def test_core_update_text_for_a_current_core():
+    assert core_update_text(CoreUpdateStatus(CURRENT, installed="26.9.30")) == "Обновлений нет"
+
+
+def test_core_update_text_before_the_first_check():
+    assert (
+        core_update_text(CoreUpdateStatus(UPDATE_UNKNOWN, installed="26.9.9")) == "Не проверялось"
+    )
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest tests/test_core_core_update.py tests/test_ui_logic_version.py -q`
Expected: FAIL — ошибка сбора, `No module named 'src.core.core_update'`.

**Step 3: Реализовать**

Создать `src/core/core_update.py`:

```python
"""Проверка обновлений ядра xray: только сообщить, ничего не скачивать.

Бинарник приложение не трогает: в AppImage он лежит внутри образа, а в
dev-режиме его ставит `cli.py setup-dev`. Здесь — сравнение установленной
версии с закреплённой и с релизами на GitHub.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import requests

if TYPE_CHECKING:
    from src.db.data_store import DataStore

# Версия, под которую написана сборка конфига. Она же закреплена в
# core/scripts/install_dev.sh (XRAY_VERSION) — тест следит, чтобы они совпадали.
PINNED_CORE_VERSION = "26.9.9"

# `/releases/latest` отдаёт только стабильные релизы, а закреплённая версия —
# пререлиз, поэтому нужен список.
RELEASES_URL = "https://api.github.com/repos/XTLS/Xray-core/releases?per_page=30"
REQUEST_TIMEOUT_SECONDS = 10
CHECK_INTERVAL_SECONDS = 3 * 24 * 60 * 60

UNKNOWN = "unknown"
CURRENT = "current"
AVAILABLE = "available"
BEHIND_PINNED = "behind_pinned"

Version = tuple[int, ...]
_VERSION = re.compile(r"\d+(?:\.\d+)+")


def parse_version(text: str) -> Version | None:
    """Версия из тега (`v26.9.9`) или из вывода `xray version`."""
    match = _VERSION.search(text or "")
    if match is None:
        return None
    return tuple(int(part) for part in match.group(0).split("."))


@dataclass(frozen=True)
class KnownReleases:
    """Что известно о релизах: новейший стабильный и новейший пререлиз."""

    stable: str = ""
    prerelease: str = ""


@dataclass(frozen=True)
class CoreUpdateStatus:
    """Итог сравнения: `kind` и версия, о которой идёт речь."""

    kind: str
    installed: str
    target: str = ""


def newest_releases(payload: Any) -> KnownReleases:
    """Выбрать новейшие версии из ответа GitHub. Черновики и мусор пропускаются."""
    newest: dict[bool, tuple[Version, str]] = {}
    for release in payload if isinstance(payload, list) else []:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        version = parse_version(str(release.get("tag_name") or ""))
        if version is None:
            continue
        is_prerelease = bool(release.get("prerelease"))
        text = ".".join(str(part) for part in version)
        if is_prerelease not in newest or version > newest[is_prerelease][0]:
            newest[is_prerelease] = (version, text)

    return KnownReleases(
        stable=newest[False][1] if False in newest else "",
        prerelease=newest[True][1] if True in newest else "",
    )


def fetch_releases(get: Callable[..., Any] = requests.get) -> KnownReleases:
    """Спросить GitHub о релизах. В запросе нет ничего о пользователе и установке."""
    response = get(
        RELEASES_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "tenga-proxy"},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return newest_releases(response.json())


def evaluate(
    installed: str, known: KnownReleases, pinned: str = PINNED_CORE_VERSION
) -> CoreUpdateStatus:
    """Сравнить установленное ядро с закреплённой версией и с релизами."""
    installed_version = parse_version(installed)
    if installed_version is None:
        return CoreUpdateStatus(UNKNOWN, installed)

    pinned_version = parse_version(pinned)
    if pinned_version is not None and installed_version < pinned_version:
        return CoreUpdateStatus(BEHIND_PINNED, installed, pinned)

    stable_version = parse_version(known.stable)
    prerelease_version = parse_version(known.prerelease)

    offers: list[tuple[Version, str]] = []
    if stable_version is not None:
        offers.append((stable_version, known.stable))
    # Пререлиз предлагается только тому, у кого уже стоит пререлиз, то есть
    # версия новее последнего стабильного релиза.
    runs_prerelease = stable_version is None or installed_version > stable_version
    if prerelease_version is not None and runs_prerelease:
        offers.append((prerelease_version, known.prerelease))

    if not offers:
        return CoreUpdateStatus(UNKNOWN, installed)

    newest_version, newest = max(offers)
    if newest_version > installed_version:
        return CoreUpdateStatus(AVAILABLE, installed, newest)
    return CoreUpdateStatus(CURRENT, installed)


def known_releases(config: DataStore) -> KnownReleases:
    """Релизы, запомненные с прошлой проверки."""
    return KnownReleases(
        stable=config.core_update_stable,
        prerelease=config.core_update_prerelease,
    )


def is_check_due(config: DataStore, now: float) -> bool:
    """Пора ли спросить GitHub снова."""
    return now - config.core_update_checked_at >= CHECK_INTERVAL_SECONDS


def refresh_known_releases(
    config: DataStore,
    *,
    now: float,
    fetch: Callable[[], KnownReleases] = fetch_releases,
) -> KnownReleases:
    """Обновить запомненные релизы. Сетевой вызов: только из фонового потока.

    Ошибка сети уходит наверх, а пустой ответ (например, исчерпан лимит API)
    прежних сведений не стирает; в обоих случаях проверка остаётся «не сделанной».
    """
    fetched = fetch()
    if not fetched.stable and not fetched.prerelease:
        return known_releases(config)

    config.core_update_stable = fetched.stable
    config.core_update_prerelease = fetched.prerelease
    config.core_update_checked_at = int(now)
    return fetched
```

Изменить `src/db/data_store.py`:

```diff
--- a/src/db/data_store.py
+++ b/src/db/data_store.py
@@ -102,6 +102,10 @@ class DataStore(ConfigBase):
     old_share_link_format: bool = True
     traffic_loop_interval: int = 1000
     check_include_pre: bool = False
+    # Проверка обновлений ядра: новейшие известные релизы и время опроса GitHub.
+    core_update_stable: str = ""
+    core_update_prerelease: str = ""
+    core_update_checked_at: int = 0
     system_proxy_format: str = ""
     # Runtime state (not saved)
     _core_token: str = field(default="", repr=False)
```

Изменить `src/ui/logic/version.py`:

```diff
--- a/src/ui/logic/version.py
+++ b/src/ui/logic/version.py
@@ -8,6 +8,8 @@ from __future__ import annotations
 
 from typing import Any
 
+from src.core.core_update import AVAILABLE, BEHIND_PINNED, CURRENT, CoreUpdateStatus
+
 UNKNOWN = "—"
 
 
@@ -44,3 +46,14 @@ def core_version(manager: Any | None) -> str:
     if not info:
         return UNKNOWN
     return str(info.get("version") or UNKNOWN)
+
+
+def core_update_text(status: CoreUpdateStatus) -> str:
+    """One line for the «Обновление ядра» row."""
+    if status.kind == AVAILABLE:
+        return f"Доступна версия {status.target}"
+    if status.kind == BEHIND_PINNED:
+        return f"Ядро старее версии {status.target}, на которую рассчитано приложение"
+    if status.kind == CURRENT:
+        return "Обновлений нет"
+    return "Не проверялось"
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest tests/test_core_core_update.py tests/test_ui_logic_version.py -q`
Expected: PASS — все passed, ни одного skipped: тест закреплённой версии
пропускается, только если нет `core/scripts/install_dev.sh`.

**Step 5: Commit**

```bash
git add src/core/core_update.py src/db/data_store.py src/ui/logic/version.py \
        tests/test_core_core_update.py tests/test_ui_logic_version.py
git commit -m "feat(core): сравнивать версию ядра с закреплённой и с релизами GitHub"
```

---

### Task 11: Обновления ядра — страница «О программе» и опрос при запуске

- В «Настройки» → «О программе» под версией ядра — строка «Обновление ядра» с
  кнопкой «Проверить». Запрос идёт в фоне; результат и время опроса
  сохраняются в настройки.
- При запуске приложение обновляет сведения о релизах, если с прошлого опроса
  прошло три дня. Только запоминает — всплывающих сообщений нет.
- Сеть включает лишь `run_app()`, вызывая `set_release_fetcher(fetch_releases)`.
  Без этого вызова `TengaApplication` за релизами не ходит, поэтому тесты сеть
  не трогают. Чтобы оставить проверку только по кнопке, убери этот вызов.

**Files:**
- Modify: `src/ui/dialogs/settings.py` (`__init__`, `_build_about_page`, новые методы)
- Modify: `src/ui/application.py` (`do_activate`, `run_app`, новые методы)
- Test: `tests/test_ui_dialogs_settings.py`, `tests/test_ui_application.py` (GTK)

**Step 1: Написать падающие тесты**

Изменить `tests/test_ui_application.py`:

```diff
--- a/tests/test_ui_application.py
+++ b/tests/test_ui_application.py
@@ -628,6 +628,40 @@ def test_failover_stays_out_of_the_way_when_disabled(adw_app):
     assert adw_app.last_notification_for_test == ""
 
 
+def test_core_releases_are_refreshed_on_activation_when_the_check_is_due(adw_app):
+    from src.core.core_update import KnownReleases
+
+    adw_app.set_release_fetcher(lambda: KnownReleases(stable="26.3.27", prerelease="26.9.30"))
+
+    adw_app.activate()
+    adw_app.wait_for_core_update_for_test()
+
+    config = adw_app.context.config
+    assert config.core_update_prerelease == "26.9.30"
+    assert config.core_update_checked_at > 0
+
+
+def test_core_releases_are_not_requested_before_the_interval_passes(adw_app):
+    import time
+
+    calls: list = []
+    adw_app.context.config.core_update_checked_at = int(time.time())
+    adw_app.set_release_fetcher(lambda: calls.append(True))
+
+    adw_app.activate()
+    adw_app.wait_for_core_update_for_test()
+
+    assert calls == []
+
+
+def test_core_releases_are_never_requested_without_a_fetcher(adw_app):
+    """Сеть включает только `run_app`: тесты и встраивание в неё не ходят."""
+    adw_app.activate()
+    adw_app.wait_for_core_update_for_test()
+
+    assert adw_app.context.config.core_update_checked_at == 0
+
+
 def _simulate_close(app, dialog) -> None:
     """Release the slot the way the `closed` signal would.
 
```

Изменить `tests/test_ui_dialogs_settings.py`:

```diff
--- a/tests/test_ui_dialogs_settings.py
+++ b/tests/test_ui_dialogs_settings.py
@@ -160,3 +160,75 @@ def test_the_dns_through_proxy_switch_round_trips(gtk_ready):
     dialog.dns_proxy_row.set_active(False)
     dialog.save()
     assert config.dns.use_proxy is False
+
+
+# --- обновление ядра на странице «О программе» ---
+
+
+def make_about_dialog(config=None, *, core="26.9.9"):
+    from types import SimpleNamespace
+    from unittest.mock import Mock
+
+    from src.ui.dialogs.settings import SettingsDialog
+
+    context = SimpleNamespace(
+        xray_manager=SimpleNamespace(get_version=lambda: {"version": core}),
+        config_dir="/tmp/tenga-test",
+        save_config=Mock(return_value=True),
+    )
+    return SettingsDialog(config or make_config(), context), context
+
+
+def test_about_page_shows_the_remembered_core_update(gtk_ready):
+    config = make_config()
+    config.core_update_stable = "26.3.27"
+    config.core_update_prerelease = "26.9.30"
+
+    dialog, _context = make_about_dialog(config)
+
+    assert dialog.core_update_row.get_subtitle() == "Доступна версия 26.9.30"
+
+
+def test_about_page_before_the_first_check(gtk_ready):
+    dialog, _context = make_about_dialog()
+
+    assert dialog.core_update_row.get_subtitle() == "Не проверялось"
+
+
+def test_check_button_asks_for_releases_and_updates_the_row(gtk_ready):
+    from src.core.core_update import KnownReleases
+
+    config = make_config()
+    dialog, context = make_about_dialog(config)
+    dialog.set_release_fetcher(lambda: KnownReleases(stable="26.3.27", prerelease="26.9.30"))
+
+    dialog.check_core_update()
+    dialog.wait_for_core_update_for_test()
+
+    assert dialog.core_update_row.get_subtitle() == "Доступна версия 26.9.30"
+    assert config.core_update_checked_at > 0
+    context.save_config.assert_called_once()
+    assert dialog.core_update_button.get_sensitive()
+
+
+def test_failed_check_is_reported_in_the_row(gtk_ready):
+    def offline():
+        raise OSError("нет сети")
+
+    config = make_config()
+    dialog, context = make_about_dialog(config)
+    dialog.set_release_fetcher(offline)
+
+    dialog.check_core_update()
+    dialog.wait_for_core_update_for_test()
+
+    assert dialog.core_update_row.get_subtitle() == "Не удалось проверить обновления"
+    assert config.core_update_checked_at == 0
+    context.save_config.assert_not_called()
+    assert dialog.core_update_button.get_sensitive()
+
+
+def test_core_update_cannot_be_checked_without_a_context(gtk_ready):
+    dialog = make_dialog()
+
+    assert not dialog.core_update_button.get_sensitive()
```

**Step 2: Убедиться, что падают**

Run: `uv run pytest -m gtk tests/test_ui_application.py tests/test_ui_dialogs_settings.py -q`
Expected: FAIL — восемь новых тестов: `AttributeError` на `core_update_row` и `set_release_fetcher`.

**Step 3: Реализовать**

Изменить `src/ui/application.py`:

```diff
--- a/src/ui/application.py
+++ b/src/ui/application.py
@@ -4,6 +4,7 @@ from __future__ import annotations
 
 import logging
 import signal
+import time
 from typing import TYPE_CHECKING
 
 import gi
@@ -14,6 +15,7 @@ gi.require_version("Adw", "1")
 from gi.repository import Adw, Gio, GLib, Gtk
 
 from src.core.context import AppContext, get_context
+from src.core.core_update import fetch_releases, is_check_due, refresh_known_releases
 from src.core.failover import FailoverController
 from src.ui.logic.async_utils import run_in_background
 from src.ui.logic.latency import LatencyRunner, make_batch_probe
@@ -79,6 +81,8 @@ class TengaApplication(Adw.Application):
         self._connection_thread = None
         self._dialog = None
         self._failover: FailoverController | None = None
+        self._release_fetcher: Callable[[], object] | None = None
+        self._core_update_thread = None
         self.last_toast_for_test = ""
         self.last_notification_for_test = ""
 
@@ -99,6 +103,7 @@ class TengaApplication(Adw.Application):
             self._window = MainWindow(application=self, context=self.context)
         self._window.present()
         self.resume_monitoring()
+        self._refresh_core_releases_if_due()
 
     def resume_monitoring(self) -> None:
         """Start watching a proxy that is already running.
@@ -112,6 +117,42 @@ class TengaApplication(Adw.Application):
             return
         monitor.start()
 
+    def set_release_fetcher(self, fetch: Callable[[], object] | None) -> None:
+        """Install the function asking GitHub about core releases.
+
+        Без неё приложение в сеть за релизами не ходит: её ставит только
+        `run_app`, поэтому тесты и встраивание остаются без сетевых запросов.
+        """
+        self._release_fetcher = fetch
+
+    def _refresh_core_releases_if_due(self) -> None:
+        """Remember the newest core releases, at most once in a few days.
+
+        Только запоминает: о новой версии говорит страница «О программе».
+        """
+        fetch = self._release_fetcher
+        config = self.context.config
+        if fetch is None or not is_check_due(config, time.time()):
+            return
+        if self._core_update_thread is not None and self._core_update_thread.is_alive():
+            return
+
+        self._core_update_thread = run_in_background(
+            lambda: refresh_known_releases(config, now=time.time(), fetch=fetch),
+            on_done=lambda _releases: self.context.save_config(),
+            # Нет сети — спросим при следующем запуске.
+            on_error=lambda _error: None,
+            name="tenga-core-update",
+        )
+
+    def wait_for_core_update_for_test(self, timeout: float = 10.0) -> None:
+        if self._core_update_thread is not None:
+            self._core_update_thread.join(timeout)
+
+        context = GLib.MainContext.default()
+        while context.pending():
+            context.iteration(False)
+
     def watch_monitor(self) -> None:
         """Hand the monitor's verdicts to the failover controller.
 
@@ -824,6 +865,8 @@ class TengaApplication(Adw.Application):
         self._connection_thread = None
         self._dialog = None
         self._failover = None
+        self._release_fetcher = None
+        self._core_update_thread = None
         self.last_toast_for_test = ""
         self.last_notification_for_test = ""
 
@@ -861,4 +904,5 @@ def run_app(config_dir=None, lock=None, with_tray: bool = True) -> int:
     # готовый монитор, но сам его не создаёт.
     attach_monitor(context)
     app = TengaApplication(context=context, lock=lock, with_tray=with_tray)
+    app.set_release_fetcher(fetch_releases)
     return app.run([])
```

Изменить `src/ui/dialogs/settings.py`:

```diff
--- a/src/ui/dialogs/settings.py
+++ b/src/ui/dialogs/settings.py
@@ -2,15 +2,19 @@
 
 from __future__ import annotations
 
+import time
+
 import gi
 
 gi.require_version("Gtk", "4.0")
 gi.require_version("Adw", "1")
 
-from gi.repository import Adw, GObject, Gtk
+from gi.repository import Adw, GLib, GObject, Gtk
 
+from src.core.core_update import evaluate, fetch_releases, known_releases, refresh_known_releases
 from src.db.config import DnsProvider, ProxyMode
-from src.ui.logic.version import UNKNOWN, app_version, core_version
+from src.ui.logic.async_utils import run_in_background
+from src.ui.logic.version import UNKNOWN, app_version, core_update_text, core_version
 
 LOG_LEVELS = ["debug", "info", "warning", "error", "none"]
 DEFAULT_LOG_LEVEL = "info"
@@ -61,6 +65,8 @@ class SettingsDialog(Adw.PreferencesDialog):
         self.set_title("Настройки")
         self._config = config
         self._context = context
+        self._fetch_releases = fetch_releases
+        self._core_update_thread = None
 
         self._build_general_page()
         self._build_monitoring_page()
@@ -190,7 +196,17 @@ class SettingsDialog(Adw.PreferencesDialog):
 
         group.add(self._value_row("Версия", app_version()))
         manager = getattr(self._context, "xray_manager", None) if self._context else None
-        group.add(self._value_row("Ядро xray", core_version(manager)))
+        self._core_version = core_version(manager)
+        group.add(self._value_row("Ядро xray", self._core_version))
+
+        self.core_update_row = Adw.ActionRow(title="Обновление ядра")
+        self.core_update_button = Gtk.Button(label="Проверить", valign=Gtk.Align.CENTER)
+        self.core_update_button.connect("clicked", lambda _button: self.check_core_update())
+        self.core_update_button.set_sensitive(self._context is not None)
+        self.core_update_row.add_suffix(self.core_update_button)
+        group.add(self.core_update_row)
+        self._show_core_update()
+
         if self._context is not None:
             group.add(self._value_row("Конфигурация", str(self._context.config_dir)))
 
@@ -294,6 +310,51 @@ class SettingsDialog(Adw.PreferencesDialog):
     def select_log_level(self, key: str) -> None:
         self._log_level.select(key)
 
+    # --- обновление ядра ---
+
+    def _show_core_update(self) -> None:
+        status = evaluate(self._core_version, known_releases(self._config))
+        self.core_update_row.set_subtitle(core_update_text(status))
+
+    def set_release_fetcher(self, fetch) -> None:
+        """Replace the function asking GitHub about releases (tests)."""
+        self._fetch_releases = fetch
+
+    def check_core_update(self) -> None:
+        """Ask for the releases in the background and redraw the row."""
+        if self._context is None:
+            return
+
+        self.core_update_button.set_sensitive(False)
+        self.core_update_row.set_subtitle("Проверяю…")
+        self._core_update_thread = run_in_background(
+            lambda: refresh_known_releases(
+                self._config, now=time.time(), fetch=self._fetch_releases
+            ),
+            on_done=self._on_core_update_checked,
+            on_error=self._on_core_update_failed,
+            name="tenga-core-update",
+        )
+
+    def _on_core_update_checked(self, _releases) -> None:
+        self.core_update_button.set_sensitive(True)
+        self._show_core_update()
+        # Время проверки хранится в настройках: иначе при следующем запуске
+        # приложение спросило бы GitHub снова.
+        self._context.save_config()
+
+    def _on_core_update_failed(self, _error: BaseException) -> None:
+        self.core_update_button.set_sensitive(True)
+        self.core_update_row.set_subtitle("Не удалось проверить обновления")
+
+    def wait_for_core_update_for_test(self, timeout: float = 10.0) -> None:
+        if self._core_update_thread is not None:
+            self._core_update_thread.join(timeout)
+
+        context = GLib.MainContext.default()
+        while context.pending():
+            context.iteration(False)
+
     def _on_clear_logs(self, _button: Gtk.Button) -> None:
         if self._context is None:
             return
```

**Step 4: Убедиться, что проходят**

Run: `uv run pytest -m gtk tests/test_ui_application.py tests/test_ui_dialogs_settings.py -q`
Expected: PASS — все passed.

**Step 5: Commit**

```bash
git add src/ui/application.py src/ui/dialogs/settings.py tests/test_ui_application.py \
        tests/test_ui_dialogs_settings.py
git commit -m "feat(ui): показывать обновление ядра на странице «О программе»"
```

---

### Task 12: Удалить поштучный замер

После задачи 5 никто не вызывает `build_latency_probe_config`,
`reserve_latency_port_pair` и `XrayManager.test_delay*`. Это удаление, а не
изменение поведения — отдельным коммитом.

Если этап 3 переписал конец `src/core/config_builder.py` так, что фрагмент не
ложится, — удали две функции руками и убери ставшие ненужными импорты
(`random`, `socket`, `ProxyMode`, если они больше нигде в файле не нужны; ruff
подскажет).

Тест «замер и сессия несут одинаковые надстройки транспорта» из этапа 1
переводится на `build_probe_outbound`.

**Files:**
- Modify: `src/core/config_builder.py` (удаляются две функции в конце файла)
- Modify: `src/core/xray_manager.py` (удаляются `test_delay`, `test_delay_realistic`)
- Delete: `tests/test_core_latency_probe.py`
- Modify: `tests/test_core_config_builder.py`, `tests/test_core_transport_tweaks.py`

**Step 1: Убедиться, что вызовов не осталось**

```bash
grep -rn "build_latency_probe_config\|reserve_latency_port_pair\|test_delay" src
```

Expected: только определения в `src/core/config_builder.py` и
`src/core/xray_manager.py`.

**Step 2: Удалить код и его тесты**

Изменить `src/core/config_builder.py`:

```diff
--- a/src/core/config_builder.py
+++ b/src/core/config_builder.py
@@ -8,13 +8,11 @@ AppContext explicitly instead of reading it from `self`.
 from __future__ import annotations
 
 import logging
-import random
-import socket
 
 from src.core.context import AppContext
 from src.core.proxy_mode import build_inbounds_for_mode
 from src.core.transport_tweaks import apply_transport_tweaks
-from src.db.config import DEFAULT_ROUTING_ORDER, LOCAL_NETWORKS, ProxyMode, RoutingMode
+from src.db.config import DEFAULT_ROUTING_ORDER, LOCAL_NETWORKS, RoutingMode
 from src.db.profiles import ProfileEntry
 from src.sys.vpn import (
     get_default_interface,
@@ -594,61 +592,3 @@ def build_session_config(context: AppContext, profile: ProfileEntry | None) -> d
             e,
         )
         return None
-
-
-def reserve_latency_port_pair(host: str) -> int:
-    """
-    Reserve a free consecutive TCP port pair (socks, http=socks+1).
-
-    Args:
-        host: Listen host for xray inbounds
-
-    Returns:
-        Base SOCKS port
-    """
-    start_port = random.randint(20000, 50000)
-
-    for offset in range(15000):
-        port = start_port + offset
-        if port >= 65000:
-            break
-
-        sock_one = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
-        sock_two = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
-        try:
-            sock_one.bind((host, port))
-            sock_two.bind((host, port + 1))
-            return port
-        except OSError:
-            continue
-        finally:
-            sock_one.close()
-            sock_two.close()
-
-    raise RuntimeError("No free consecutive port pair found for latency test")
-
-
-def build_latency_probe_config(
-    context: AppContext, profile: ProfileEntry | None
-) -> tuple[dict, int] | None:
-    """
-    Create temporary xray config for latency test.
-
-    Uses profile outbound/routing/dns from normal config but forces
-    SYSTEM_PROXY inbounds to avoid TUN conflicts with active session.
-    """
-    config = build_session_config(context, profile)
-    if not config:
-        return None
-
-    listen_host = context.config.inbound_address
-    socks_port = reserve_latency_port_pair(listen_host)
-    inbounds = build_inbounds_for_mode(
-        mode=ProxyMode.SYSTEM_PROXY,
-        address=listen_host,
-        socks_port=socks_port,
-        tun_name=getattr(context.config, "tun_name", "xray0"),
-        tun_mtu=getattr(context.config, "tun_mtu", 1500),
-    )
-    config["inbounds"] = inbounds
-    return config, socks_port
```

Изменить `src/core/xray_manager.py`:

```diff
--- a/src/core/xray_manager.py
+++ b/src/core/xray_manager.py
@@ -8,7 +8,6 @@ import time
 from collections.abc import Callable
 from dataclasses import dataclass
 from pathlib import Path
-from statistics import median
 from typing import IO, Any
 
 import requests
@@ -480,130 +479,6 @@ class XrayManager:
                 download += value
         return TrafficStats(upload=upload, download=download)
 
-    @measure_time("XrayManager.test_delay")
-    def test_delay(
-        self,
-        proxy_address: str | None = None,
-        proxy_port: int | None = None,
-        timeout: int = 3000,
-    ) -> int:
-        """
-        Backward-compatible single-probe latency test.
-
-        Args:
-            proxy_address: Proxy address
-            proxy_port: Proxy SOCKS5 port
-            timeout: Timeout in milliseconds
-
-        Returns:
-            Latency in milliseconds, or -1 on error
-        """
-        return self.test_delay_realistic(
-            proxy_address=proxy_address,
-            proxy_port=proxy_port,
-            timeout=timeout,
-            probes=1,
-        )
-
-    @measure_time("XrayManager.test_delay_realistic")
-    def test_delay_realistic(
-        self,
-        proxy_address: str | None = None,
-        proxy_port: int | None = None,
-        timeout: int = 3000,
-        probes: int = 3,
-        test_url: str = "http://www.google.com/generate_204",
-    ) -> int:
-        """
-        Test proxy latency with multiple probes and median aggregation.
-
-        Args:
-            proxy_address: Proxy address
-            proxy_port: Proxy SOCKS5 port
-            timeout: Timeout in milliseconds
-            probes: Number of probes to run (minimum 1)
-            test_url: Target URL for probe
-
-        Returns:
-            Median latency in milliseconds, or -1 on error
-        """
-        if not self.is_running:
-            logger.debug("xray-core is not running, cannot test delay")
-            return -1
-
-        if proxy_address is None or proxy_port is None:
-            logger.debug("Proxy address or port not provided, cannot test delay")
-            return -1
-
-        probes = max(1, probes)
-
-        try:
-            timeout_sec = timeout / 1000.0
-            http_port = proxy_port + 1
-            proxy_url = f"http://{proxy_address}:{http_port}"
-            successful_samples: list[int] = []
-
-            for probe_index in range(probes):
-                start_ns = time.perf_counter_ns()
-                cache_buster = f"cb={start_ns}_{probe_index}"
-                probe_url = (
-                    f"{test_url}&{cache_buster}"
-                    if "?" in test_url
-                    else f"{test_url}?{cache_buster}"
-                )
-
-                try:
-                    response = requests.head(
-                        probe_url,
-                        proxies={"http": proxy_url, "https": proxy_url},
-                        timeout=timeout_sec,
-                        allow_redirects=False,
-                    )
-                    elapsed_ms = int((time.perf_counter_ns() - start_ns) / 1_000_000)
-
-                    # Accept 2xx, 3xx, and some 4xx (like 403) as success
-                    if 200 <= response.status_code < 500:
-                        successful_samples.append(elapsed_ms)
-                        logger.debug(
-                            "Delay probe successful: %d ms (probe %d/%d)",
-                            elapsed_ms,
-                            probe_index + 1,
-                            probes,
-                        )
-                    else:
-                        logger.debug(
-                            "Delay probe failed with status %d (probe %d/%d)",
-                            response.status_code,
-                            probe_index + 1,
-                            probes,
-                        )
-                except requests.exceptions.Timeout:
-                    logger.debug(
-                        "Delay probe timed out after %d ms (probe %d/%d)",
-                        timeout,
-                        probe_index + 1,
-                        probes,
-                    )
-                except requests.exceptions.RequestException as e:
-                    logger.debug(
-                        "Delay probe request error (probe %d/%d): %s",
-                        probe_index + 1,
-                        probes,
-                        e,
-                    )
-
-            if not successful_samples:
-                logger.debug("No successful delay probes")
-                return -1
-
-            result = int(median(successful_samples))
-            logger.debug("Delay test realistic result (median): %d ms", result)
-            return result
-
-        except Exception as e:
-            logger.debug("Unexpected error in realistic delay test: %s", e)
-            return -1
-
     def __enter__(self) -> XrayManager:
         """Context manager entry."""
         return self
```

Изменить `tests/test_core_config_builder.py`:

```diff
--- a/tests/test_core_config_builder.py
+++ b/tests/test_core_config_builder.py
@@ -11,9 +11,7 @@ import json
 import pytest
 
 from src.core.config_builder import (
-    build_latency_probe_config,
     build_session_config,
-    reserve_latency_port_pair,
 )
 from src.core.context import init_context
 from src.db.config import LOCAL_NETWORKS, DnsProvider, ProxyMode, RoutingMode
@@ -57,33 +55,6 @@ def test_session_config_returns_none_without_profile(context):
     assert build_session_config(context, None) is None
 
 
-def test_latency_probe_config_uses_system_proxy_inbounds(context, profile):
-    result = build_latency_probe_config(context, profile)
-
-    assert result is not None
-    config, socks_port = result
-    assert isinstance(socks_port, int)
-    assert 20000 <= socks_port < 65000
-    protocols = {inbound["protocol"] for inbound in config["inbounds"]}
-    assert protocols <= {"socks", "http"}
-    assert "tun" not in protocols
-    ports = {inbound["port"] for inbound in config["inbounds"]}
-    assert ports == {socks_port, socks_port + 1}
-
-
-def test_reserve_latency_port_pair_returns_free_consecutive_ports():
-    import socket
-
-    port = reserve_latency_port_pair("127.0.0.1")
-
-    for candidate in (port, port + 1):
-        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
-        try:
-            sock.bind(("127.0.0.1", candidate))
-        finally:
-            sock.close()
-
-
 def test_custom_routing_mode_builds_direct_and_proxy_rules(context, profile):
     """RoutingMode.CUSTOM читает списки из context — путь, наиболее хрупкий при переносе."""
     context.config.routing.mode = RoutingMode.CUSTOM
```

Удалить `tests/test_core_latency_probe.py`:

```bash
git rm tests/test_core_latency_probe.py
```

Изменить `tests/test_core_transport_tweaks.py`:

```diff
--- a/tests/test_core_transport_tweaks.py
+++ b/tests/test_core_transport_tweaks.py
@@ -7,7 +7,8 @@ from pathlib import Path
 
 import pytest
 
-from src.core.config_builder import build_latency_probe_config, build_session_config
+from src.core.batch_probe import build_probe_outbound
+from src.core.config_builder import build_session_config
 from src.core.context import init_context
 from src.core.transport_tweaks import apply_mux, apply_tls_fragment, is_mux_eligible
 from src.db.config import TlsFragmentSettings
@@ -207,18 +208,17 @@ def test_session_config_has_no_tweaks_by_default(context):
     assert "finalmask" not in proxy["streamSettings"]
 
 
-def test_session_and_probe_configs_carry_the_same_tweaks(context):
+def test_session_and_probe_carry_the_same_tweaks(context):
     """Замер задержки обязан идти с теми же tweaks, что и рабочее подключение."""
     context.config.tls_fragment.enabled = True
     context.config.mux_default_on = True
     profile = entry(VLESS_WS)
 
     session = build_session_config(context, profile)
-    probe = build_latency_probe_config(context, profile)
+    probe = build_probe_outbound(profile, context.config)
 
     assert session is not None and probe is not None
-    for config in (session, probe[0]):
-        proxy = config["outbounds"][0]
+    for proxy in (session["outbounds"][0], probe):
         assert proxy["mux"]["enabled"] is True
         assert proxy["streamSettings"]["finalmask"]["tcp"][0]["type"] == "fragment"
 
```

**Step 3: Убедиться, что набор зелёный**

Run: `uv run pytest tests/test_core_config_builder.py tests/test_core_transport_tweaks.py tests/test_core_xray_manager.py -q`
Expected: PASS — все passed.

Run: `python cli.py lint-all`
Expected: PASS — замечаний нет (неиспользуемых импортов не осталось).

**Step 4: Commit**

```bash
git add -A src/core/config_builder.py src/core/xray_manager.py tests/
git commit -m "refactor(core): удалить поштучный замер задержки"
```

---

### Task 13: Документация и итоговая проверка

**Files:**
- Modify: `docs/ru/gui.md`, `docs/en/gui.md`, `docs/ru/profiles.md`, `docs/en/profiles.md`
- Modify: `docs/plans/2026-10-03-network-parity-roadmap.md`

**Step 1: Обновить описание**

Если задачи 8–9 вычеркнуты, раздел «Автопереключение» / «Failover» не добавляй.

Изменить `docs/en/gui.md`:

```diff
--- a/docs/en/gui.md
+++ b/docs/en/gui.md
@@ -46,6 +46,28 @@ The "Monitoring" tab displays:
 - Last check time
 - Manual connection check capability
 
+The proxy status is not "the core process is running" but the result of a
+request through the profile's server: the application reaches the test URL via
+a service inbound of the core on `127.0.0.1`, protected by a one-time password.
+Routing rules do not apply to this request, so "server does not respond" means
+the server itself, even when the test URL is on your direct list.
+
+### Failover
+
+Settings → Monitoring has an automatic failover switch (off by default). After
+the configured number of failed checks in a row the application connects
+another profile of the same group — the one with the lowest measured latency
+first — and tells you with a notification. It does not return to a profile that
+has just stopped responding for 15 minutes. When no suitable profile is left
+the connection is kept: traffic must not suddenly go direct.
+
+### Core updates
+
+Settings → About shows the xray core version and a "core update" row. Every
+three days, and on the "Check" button, the application asks GitHub for the
+release list and tells you when a newer version is out. It never downloads or
+replaces the core itself.
+
 ## System Tray
 
 The icon shows the connection state with three distinct glyphs: a crossed-out
```

Изменить `docs/en/profiles.md`:

```diff
--- a/docs/en/profiles.md
+++ b/docs/en/profiles.md
@@ -88,6 +88,13 @@ For each profile, you can test latency:
 - Comparing profile performance
 - Automatic result updates
 
+A group is measured by one temporary core process: every profile gets its own
+inbound on `127.0.0.1` with a one-time password, and results appear as they
+arrive. Latency is the median of three requests to the test URL through the
+profile's server. A dash instead of a number means one of three things: the
+profile could not be built, the core rejected its settings, or the server did
+not respond.
+
 ## Profile Settings
 
 Each profile can have individual settings:
```

Изменить `docs/ru/gui.md`:

```diff
--- a/docs/ru/gui.md
+++ b/docs/ru/gui.md
@@ -46,6 +46,28 @@ python gui.py
 - Время последней проверки
 - Возможность ручной проверки соединений
 
+Статус прокси — это не «процесс ядра запущен», а результат запроса через
+сервер профиля: приложение обращается к проверочному адресу через служебный
+вход ядра на `127.0.0.1`, закрытый одноразовым паролем. Правила маршрутизации
+на этот запрос не действуют, поэтому «Сервер не отвечает» означает именно
+сервер, даже если проверочный адрес у вас в списке «напрямую».
+
+### Автопереключение
+
+В «Настройки» → «Мониторинг» можно включить автопереключение (по умолчанию
+выключено). После заданного числа неудачных проверок подряд приложение
+подключает другой профиль той же группы — сначала с наименьшей измеренной
+задержкой — и сообщает об этом уведомлением. К профилю, который только что
+перестал отвечать, оно не возвращается 15 минут. Если подходящих профилей не
+осталось, подключение не разрывается: трафик не должен внезапно пойти напрямую.
+
+### Обновление ядра
+
+«Настройки» → «О программе» показывает версию ядра xray и строку «Обновление
+ядра». Раз в три дня и по кнопке «Проверить» приложение спрашивает у GitHub
+список релизов и сообщает, если вышла версия новее. Само ядро приложение не
+скачивает и не заменяет.
+
 ## Системный трей
 
 Иконка показывает состояние соединения тремя разными значками: перечёркнутый
```

Изменить `docs/ru/profiles.md`:

```diff
--- a/docs/ru/profiles.md
+++ b/docs/ru/profiles.md
@@ -88,6 +88,12 @@ python cli.py add "vless://..."
 - Сравнение производительности профилей
 - Автоматическое обновление результатов
 
+Группа меряется одним временным процессом ядра: у каждого профиля в нём свой
+вход на `127.0.0.1` с одноразовым паролем, результаты появляются по мере
+готовности. Задержка — медиана трёх запросов к проверочному адресу через
+сервер профиля. Прочерк вместо числа означает одно из трёх: профиль не удалось
+собрать, ядро отвергло его настройки или сервер не ответил.
+
 ## Настройки профиля
 
 Каждый профиль может иметь индивидуальные настройки:
```

**Step 2: Полная проверка**

Run: `uv run pytest -q`
Expected: PASS — все тесты проходят.

Run: `uv run pytest -m gtk tests -q`
Expected: все passed. Под Broadway — кроме двух тестов геометрии окна в
`tests/test_ui_window.py`, которые падают там и без этого плана.

Run: `python cli.py lint-all`
Expected: PASS — замечаний нет.

**Step 3: Ручная проверка**

Автотесты подтверждают логику и то, что ядро принимает конфиги. Остальное
проверяется только руками, на машине, где можно переподключать прокси.

Замер задержки:

- [ ] Группа из подписки (50+ профилей) меряется заметно быстрее прежнего;
      строки пересортировываются по ходу замера; в `ps` один процесс
      `xray run -c /tmp/tenga-probe-…`, после замера его нет, как и файла.
- [ ] Профиль с заведомо битой ссылкой (например, REALITY с `pbk=abc`) получает
      прочерк, остальные измерены.
- [ ] Замер при активном подключении не портит счётчик трафика на карточке.
- [ ] Числа сопоставимы со старым замером на тех же серверах. В режиме TUN при
      активном подключении они по-прежнему включают задержку текущего профиля
      (см. «Сознательно не делаем»).

Проверка соединения:

- [ ] После подключения в `ss -ltn` есть порт `health-in` на `127.0.0.1`, а в
      `current_config.json` у него `***` вместо логина и пароля.
- [ ] `curl -x http://127.0.0.1:<порт> http://example.com` без учётных данных
      получает 407.
- [ ] Рабочий сервер: «Мониторинг» показывает «Доступен» — в режиме TUN и в
      режиме системного прокси.
- [ ] Сервер недоступен (заблокировать его адрес файрволом или подключиться к
      профилю с выключенным сервером): не позже чем через интервал проверки плюс
      5 с статус сменяется на «Сервер не отвечает», страница перерисовывается
      сама.
- [ ] Проверочный адрес внесён в список «напрямую»: при мёртвом сервере статус
      всё равно «Сервер не отвечает».
- [ ] «Обновить сейчас» при мёртвом сервере не подвешивает окно.

Автопереключение (если задачи 8–9 выполнены):

- [ ] Включено, порог 3: после трёх неудачных проверок подключается другой
      профиль той же группы, приходит уведомление рабочего стола с обоими
      именами.
- [ ] Выдернутый сетевой кабель или выключенный Wi-Fi переключений не вызывает —
      отдельно в режиме TUN: там маршрут по умолчанию остаётся и при пропавшей
      сети, и `Gio.NetworkMonitor` может ответить «сеть есть». Если так —
      записать в дорожную карту.
- [ ] Когда все профили группы перебраны: одно сообщение, подключение остаётся.
- [ ] Выключено: никаких переключений и уведомлений.

Обновление ядра:

- [ ] «О программе» → «Проверить»: строка показывает «Доступна версия …» или
      «Обновлений нет»; без сети — «Не удалось проверить обновления».
- [ ] В `settings.json` появились `core_update_*`; повторный запуск в течение
      трёх дней к `api.github.com` не обращается.

Что проверить не удалось — записать в дорожную карту, в статус этапа 4.

**Step 4: Записать статус в дорожную карту и закоммитить**

```bash
git add docs/
git commit -m "docs: описать пакетный замер, проверку соединения и автопереключение"
```

Версию приложения поднимает владелец проекта: `python cli.py bump-version <версия>`.

---

## Итог воспроизведения

Воспроизведение выполнено 2026-10-03 на чистом клоне базы (состояние после
этапа 1, 634 теста) скриптом: блоки «Создать», «Изменить» и «Удалить»
применялись по порядку задач, каждая команда `Run:` выполнялась на месте, а её
итог сверялся с `Expected: FAIL` или `Expected: PASS`.

| Проверка | Результат |
|---|---|
| Фрагменты `diff` | все легли без смещения и нечёткого совпадения |
| Красные шаги (тест до реализации) | 11 из 11 упали по ожидаемой причине |
| Зелёные шаги | все прошли |
| `uv run pytest -q` в конце | 742 passed (было 634) |
| GTK-тесты под Broadway в конце | 216 passed, 2 failed — те же два теста геометрии окна, что и на базе |
| `ruff check`, `ruff format --check` | чисто |
| Итоговое дерево | совпадает с прототипом файл в файл |

Одиннадцать тестов обращаются к настоящему ядру 26.9.9: восемь в
`tests/test_core_batch_probe.py` и три в `tests/test_core_health_probe.py`.

Оговорки:

- В копии, на которой шло воспроизведение, нет `core/scripts/install_dev.sh`.
  Чтобы тест `test_pinned_version_matches_the_install_script` выполнился, туда
  был положен файл с одной строкой `XRAY_VERSION="26.9.9"` — так, как её
  оставляет задача 3 этапа 1. С другой версией в этой строке тест падает.
- Числа `passed` в шагах верны для состояния после этапа 1. После этапов 2 и 3
  в общих файлах тестов станет больше; для новых файлов этого плана числа
  останутся теми же.
- Этапы 2 и 3 при воспроизведении применены не были: совместимость трёх планов
  проверяется отдельно, слиянием веток прототипов.
