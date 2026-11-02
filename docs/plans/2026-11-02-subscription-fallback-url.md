# Запасной адрес подписки: план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** если основной адрес подписки не ответил, загрузить её один раз с `fallback-url` провайдера, не меняя `subscription_url`, и предложить постоянную смену адреса диалогом.

**Architecture:** решения — чистые функции в новом `src/sub/fallback.py`. Загрузку выполняет `SubscriptionUpdater.update()` и сообщает результат в `used_fallback_url`. `AppController` превращает его в предложение смены адреса, а `SubscriptionRow.via_fallback` показывает подпись в GTK и Qt. Дизайн: `docs/plans/2026-11-02-subscription-fallback-url-design.md`.

**Tech Stack:** Python 3.11+, requests, pytest, GTK 4/libadwaita, PySide6.

**Команды:** быстрые тесты — `uv run pytest <файл> -q --no-cov`. Все проверки — в задаче 7.

---

### Task 1: Общая нормализация адреса

**Files:**
- Modify: `src/db/profiles.py` (`find_subscription_group`, строки 195-207)
- Modify: `src/sub/url_change.py`
- Test: `tests/test_sub_url_change.py`

**Step 1: Write the failing tests**

Добавить в конец `tests/test_sub_url_change.py`:

```python
@pytest.mark.parametrize(
    "candidate",
    [
        "https://PROVIDER.example/sub/token",
        "https://provider.example:443/sub/token",
        "HTTPS://provider.example/sub/token",
    ],
)
def test_the_same_address_in_another_spelling_is_not_proposed(candidate):
    assert propose_url_change(7, CURRENT, candidate, REASON_NEW_URL) is None


def test_a_different_token_is_a_different_address():
    assert not same_subscription_url(CURRENT, "https://provider.example/sub/other")


def test_unparsable_addresses_are_compared_as_text():
    bad = "https://user:pass@provider.example/sub"

    assert same_subscription_url(bad, f" {bad} ")
    assert not same_subscription_url(bad, CURRENT)
```

В импорт из `src.sub.url_change` добавить `same_subscription_url`.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sub_url_change.py -q --no-cov`
Expected: ошибка сбора, `ImportError: cannot import name 'same_subscription_url'`.

**Step 3: Вынести ключ в `src/db/profiles.py`**

В импорты модуля добавить `from urllib.parse import urlsplit, urlunsplit`. Перед `@dataclass class ProfileGroup` добавить функцию:

```python
def subscription_url_key(url: str) -> str:
    """Normalize a subscription address for comparison.

    Raises ValueError (включая UnicodeError) для адреса, который нельзя разобрать
    или в котором есть credentials: такие адреса не считаются одинаковыми.
    """
    parts = urlsplit(url)
    if parts.username is not None or parts.password is not None:
        raise ValueError("URL с credentials нельзя объединять")
    host = (parts.hostname or "").lower().encode("idna").decode("ascii")
    host = f"[{host}]" if ":" in host else host
    port = parts.port
    if port and (parts.scheme.lower(), port) not in (("https", 443), ("http", 80)):
        host += f":{port}"
    return urlunsplit((parts.scheme.lower(), host, parts.path, parts.query, parts.fragment))
```

В `find_subscription_group` удалить локальные импорт и `key`, а вызовы `key(...)` заменить на `subscription_url_key(...)`.

**Step 4: Использовать ключ в `src/sub/url_change.py`**

Добавить функцию перед `propose_url_change` и использовать её там:

```python
def same_subscription_url(first: str, second: str) -> bool:
    """Whether two addresses lead to the same subscription."""
    from src.db.profiles import subscription_url_key

    try:
        return subscription_url_key(first.strip()) == subscription_url_key(second.strip())
    except ValueError:
        return first.strip() == second.strip()


def propose_url_change(
    group_id: int, current_url: str, candidate: str | None, reason: str
) -> UrlChangeProposal | None:
    """Build a proposal, or None when there is nothing safe and new to offer."""
    url = (candidate or "").strip()
    if not url or same_subscription_url(url, current_url):
        return None
    if not is_acceptable_subscription_url(url):
        return None
    return UrlChangeProposal(group_id=group_id, new_url=url, reason=reason)
```

**Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_sub_url_change.py tests/test_db_profiles.py -q --no-cov`
Expected: PASS.

**Step 6: Commit**

```bash
git add src/db/profiles.py src/sub/url_change.py tests/test_sub_url_change.py
git commit -m "refactor(sub): сравнивать адреса подписок по общему ключу"
```

---

### Task 2: Решения о запасном адресе

**Files:**
- Create: `src/sub/fallback.py`
- Test: `tests/test_sub_fallback.py`

**Step 1: Write the failing tests**

Создать `tests/test_sub_fallback.py`:

```python
"""Разовая загрузка подписки с запасного адреса."""

import pytest
import requests

from src.sub.errors import SubscriptionHttpError, SubscriptionTooLargeError
from src.sub.fallback import (
    FallbackExhaustedError,
    can_propose_after,
    display_error,
    is_worth_trying,
    usable_url,
)
from src.sub.url_policy import SubscriptionPolicyError

PRIMARY = "https://provider.example/sub/token"
BACKUP = "https://backup.example/sub/token"


@pytest.mark.parametrize(
    "error",
    [
        requests.ConnectionError(),
        requests.Timeout(),
        SubscriptionHttpError(500),
        SubscriptionHttpError(503),
        SubscriptionHttpError(403),
        SubscriptionHttpError(429),
    ],
)
def test_access_failures_are_worth_the_fallback(error):
    assert is_worth_trying(error)


@pytest.mark.parametrize(
    "error",
    [
        SubscriptionHttpError(404),
        SubscriptionHttpError(410),
        SubscriptionHttpError(400),
        SubscriptionHttpError(401),
        SubscriptionTooLargeError(1),
        SubscriptionPolicyError("запрещено"),
        RuntimeError("boom"),
    ],
)
def test_definitive_answers_are_not_worth_the_fallback(error):
    assert not is_worth_trying(error)


def test_a_stored_address_is_usable_after_trimming():
    assert usable_url(PRIMARY, f"  {BACKUP} ") == BACKUP


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "   ",
        "http://backup.example/sub",
        "https://192.168.1.1/sub",
        "https://localhost/sub",
        PRIMARY,
        "https://PROVIDER.example:443/sub/token",
    ],
)
def test_a_stored_address_is_not_trusted(stored):
    assert usable_url(PRIMARY, stored) is None


def test_a_server_answer_explains_more_than_a_lost_connection():
    primary = requests.ConnectionError()
    fallback = SubscriptionHttpError(403)

    assert display_error(primary, fallback) is fallback


@pytest.mark.parametrize(
    "fallback", [requests.ConnectionError(), SubscriptionHttpError(503)]
)
def test_otherwise_the_primary_error_is_shown(fallback):
    primary = SubscriptionHttpError(502)

    assert display_error(primary, fallback) is primary


@pytest.mark.parametrize(
    "error",
    [
        FallbackExhaustedError(requests.ConnectionError()),
        SubscriptionHttpError(404),
        SubscriptionHttpError(410),
    ],
)
def test_no_permanent_change_is_proposed_when_it_cannot_help(error):
    assert not can_propose_after(error)


@pytest.mark.parametrize(
    "error", [requests.ConnectionError(), SubscriptionHttpError(401), RuntimeError("boom")]
)
def test_a_permanent_change_is_proposed_after_other_failures(error):
    assert can_propose_after(error)


def test_the_exhausted_error_does_not_quote_the_address():
    inner = requests.ConnectionError(f"failed: {PRIMARY}")

    error = FallbackExhaustedError(inner)

    assert error.display_error is inner
    assert PRIMARY not in str(error)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sub_fallback.py -q --no-cov`
Expected: ошибка сбора, `ModuleNotFoundError: No module named 'src.sub.fallback'`.

**Step 3: Write the implementation**

Создать `src/sub/fallback.py`:

```python
"""Разовая загрузка подписки с запасного адреса провайдера.

Постоянно адрес подписки меняется только с подтверждения пользователя
(src/sub/url_change.py). Разовая загрузка его не меняет: следующее обновление
снова начинается с основного адреса.
"""

from __future__ import annotations

import requests

from src.sub.errors import SubscriptionHttpError, SubscriptionTooLargeError
from src.sub.url_change import is_acceptable_subscription_url, same_subscription_url

_TOKEN_REVOKED = (404, 410)


class FallbackExhaustedError(Exception):
    """Не сработали оба адреса; показывать нужно ``display_error``."""

    def __init__(self, display_error: BaseException) -> None:
        # Не str(display_error): в тексте ошибок requests лежит адрес с токеном.
        super().__init__("Не сработали основной и запасной адреса подписки")
        self.display_error = display_error


def is_worth_trying(error: BaseException) -> bool:
    """Whether the failure of the primary address justifies the fallback.

    403 и 429 может отвечать сам CDN. 404 и 410 означают отозванный токен:
    запасной адрес несёт тот же токен. Прочие коды — ответ сервера, а не сбой
    доступа к нему.
    """
    if isinstance(error, SubscriptionTooLargeError):
        return False
    if isinstance(error, SubscriptionHttpError):
        return 500 <= error.status_code <= 599 or error.is_access_denied
    return isinstance(error, requests.RequestException)


def usable_url(primary_url: str, stored: str | None) -> str | None:
    """The fallback address to request, or None.

    Проверяется при каждой загрузке: файлу профилей не доверяем. Панель отдаёт
    второй адрес всегда, поэтому после перехода на него он равен основному.
    """
    url = (stored or "").strip()
    if not is_acceptable_subscription_url(url) or same_subscription_url(url, primary_url):
        return None
    return url


def display_error(primary: BaseException, fallback: BaseException) -> BaseException:
    """Pick the error to show: a server's answer explains more than a lost connection."""
    if not isinstance(primary, SubscriptionHttpError) and isinstance(
        fallback, SubscriptionHttpError
    ):
        return fallback
    return primary


def can_propose_after(error: BaseException) -> bool:
    """Whether a permanent address change still makes sense after this failure."""
    if isinstance(error, FallbackExhaustedError):
        return False
    return not (isinstance(error, SubscriptionHttpError) and error.status_code in _TOKEN_REVOKED)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sub_fallback.py -q --no-cov`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/sub/fallback.py tests/test_sub_fallback.py
git commit -m "feat(sub): правила разовой загрузки с запасного адреса"
```

---

### Task 3: Загрузка в `SubscriptionUpdater`

**Files:**
- Modify: `src/db/profiles.py` (`ProfileGroup`, строки 77-82)
- Modify: `src/sub/metadata.py` (`apply_metadata`, строки 255-278)
- Modify: `src/sub/updater.py` (импорты, `__init__`, `update`)
- Test: `tests/test_sub_fallback.py`

**Step 1: Write the failing tests**

Добавить в начало `tests/test_sub_fallback.py` (к импортам) и в конец файла:

```python
from src.db.profiles import ProfileManager
from src.sub.updater import SubscriptionUpdater

LINK = "vless://11111111-1111-1111-1111-111111111111@nl.example.org:443?type=tcp#NL-1"
LINK_BACKUP = "vless://11111111-1111-1111-1111-111111111111@de.example.org:443?type=tcp#DE-1"


def _response(body: str = LINK, status: int = 200, headers: dict | None = None):
    response = requests.Response()
    response.status_code = status
    response._content = body.encode("utf-8")
    response._content_consumed = True
    response.headers = headers or {}
    return response


@pytest.fixture
def subscription(tmp_path, monkeypatch):
    monkeypatch.setattr(SubscriptionUpdater, "RETRY_BASE_DELAY_SEC", 0)
    profiles = ProfileManager(profiles_dir=tmp_path)
    group = profiles.add_group("Sub", is_subscription=True)
    group.subscription_url = PRIMARY
    group.sub_fallback_url = BACKUP
    return profiles, group


def _serve(routes: dict):
    """A pinned_get replacement: answers by URL and records the requests."""
    requested = []

    def pinned_get(url, **_kwargs):
        requested.append(url)
        answer = routes[url]
        if isinstance(answer, Exception):
            raise answer
        return answer

    return pinned_get, requested


def _update(profiles, group, routes, group_id="group"):
    pinned_get, requested = _serve(routes)
    updater = SubscriptionUpdater(profiles=profiles)
    target = group.id if group_id == "group" else group_id
    with patch("src.sub.updater.pinned_get", pinned_get):
        beans = updater.update(PRIMARY, group_id=target)
    return updater, beans, requested


@pytest.mark.parametrize(
    "failure",
    [
        requests.ConnectionError("primary down"),
        _response("down", status=503),
        _response("denied", status=403),
    ],
)
def test_a_failed_primary_loads_the_fallback_once(subscription, failure):
    profiles, group = subscription

    updater, beans, requested = _update(
        profiles, group, {PRIMARY: failure, BACKUP: _response(LINK_BACKUP)}
    )

    assert [bean.name for bean in beans] == ["DE-1"]
    assert requested[-1] == BACKUP
    assert requested.count(BACKUP) == 1
    assert updater.used_fallback_url == BACKUP
    assert group.subscription_url == PRIMARY
    assert group.sub_via_fallback is True
    assert [p.name for p in profiles.get_profiles_in_group(group.id)] == ["DE-1"]


def test_the_next_update_starts_with_the_primary_and_clears_the_mark(subscription):
    profiles, group = subscription
    _update(profiles, group, {PRIMARY: _response("down", 503), BACKUP: _response(LINK_BACKUP)})

    updater, _beans, requested = _update(profiles, group, {PRIMARY: _response(LINK)})

    assert requested == [PRIMARY]
    assert updater.used_fallback_url == ""
    assert group.sub_via_fallback is False


@pytest.mark.parametrize("status", [404, 410, 400])
def test_a_definitive_answer_does_not_reach_the_fallback(subscription, status):
    profiles, group = subscription

    with pytest.raises(SubscriptionHttpError):
        _update(profiles, group, {PRIMARY: _response("no", status=status)})


def test_an_empty_primary_answer_does_not_reach_the_fallback(subscription):
    profiles, group = subscription

    _updater, beans, requested = _update(profiles, group, {PRIMARY: _response("")})

    assert beans == []
    assert requested == [PRIMARY]
    assert group.sub_empty is True


def test_both_addresses_failing_keeps_the_group_and_reports_the_better_error(subscription):
    profiles, group = subscription

    with pytest.raises(FallbackExhaustedError) as caught:
        _update(
            profiles,
            group,
            {PRIMARY: requests.ConnectionError("down"), BACKUP: _response("denied", status=403)},
        )

    assert isinstance(caught.value.display_error, SubscriptionHttpError)
    assert caught.value.display_error.status_code == 403
    assert group.sub_via_fallback is False
    assert group.sub_fallback_url == BACKUP


def test_a_policy_denial_of_the_fallback_counts_as_its_failure(subscription):
    profiles, group = subscription

    with pytest.raises(FallbackExhaustedError) as caught:
        _update(
            profiles,
            group,
            {PRIMARY: _response("down", 503), BACKUP: SubscriptionPolicyError("запрещено")},
        )

    assert caught.value.display_error.status_code == 503


def test_without_a_group_id_nobody_elses_fallback_is_used(subscription):
    profiles, group = subscription
    profiles.current_group_id = group.id

    with pytest.raises(SubscriptionHttpError):
        _update(profiles, group, {PRIMARY: _response("down", 503)}, group_id=None)


@pytest.mark.parametrize("stored", ["http://192.168.1.1/sub", PRIMARY, ""])
def test_an_unusable_stored_address_is_not_requested(subscription, stored):
    profiles, group = subscription
    group.sub_fallback_url = stored

    with pytest.raises(SubscriptionHttpError):
        _update(profiles, group, {PRIMARY: _response("down", 503)})


def test_a_primary_answer_with_servers_forgets_a_withdrawn_address(subscription):
    profiles, group = subscription

    _update(profiles, group, {PRIMARY: _response(LINK)})

    assert group.sub_fallback_url == ""


def test_an_unsafe_address_in_a_primary_answer_forgets_the_old_one(subscription):
    profiles, group = subscription

    _update(
        profiles,
        group,
        {PRIMARY: _response(LINK, headers={"fallback-url": "http://192.168.1.1/sub"})},
    )

    assert group.sub_fallback_url == ""


def test_an_empty_primary_answer_keeps_the_address(subscription):
    """Страница CDN с кодом 200 разбирается как пустой список."""
    profiles, group = subscription

    _update(profiles, group, {PRIMARY: _response("<html>maintenance</html>")})

    assert group.sub_fallback_url == BACKUP


def test_a_fallback_answer_without_the_header_keeps_the_address(subscription):
    profiles, group = subscription

    _update(profiles, group, {PRIMARY: _response("down", 503), BACKUP: _response(LINK_BACKUP)})

    assert group.sub_fallback_url == BACKUP


def test_a_fallback_answer_can_update_the_address(subscription):
    profiles, group = subscription
    newer = "https://newer.example/sub/token"

    _update(
        profiles,
        group,
        {
            PRIMARY: _response("down", 503),
            BACKUP: _response(LINK_BACKUP, headers={"fallback-url": newer}),
        },
    )

    assert group.sub_fallback_url == newer


def test_the_mark_survives_saving_and_loading(subscription, tmp_path):
    profiles, group = subscription
    group.sub_via_fallback = True
    profiles.save()

    reloaded = ProfileManager(profiles_dir=tmp_path)
    reloaded.load()

    assert reloaded.get_group(group.id).sub_via_fallback is True
```

К импортам файла добавить `from unittest.mock import patch`.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sub_fallback.py -q --no-cov`
Expected: новые тесты FAIL: нет `used_fallback_url` и `sub_via_fallback`, а исключения основного адреса уходят наружу.

**Step 3: Добавить поле группы**

В `src/db/profiles.py` заменить комментарий поля и добавить новое:

```python
    sub_fallback_url: str = ""  # разовая загрузка при сбое основного адреса
```

```python
    # Последний успешный ответ не дал ни одного сервера; сохранённые оставлены.
    sub_empty: bool = False
    # Последнее успешное обновление пришло с запасного адреса.
    sub_via_fallback: bool = False
```

**Step 4: Правила очистки в `apply_metadata`**

В `src/sub/metadata.py` изменить сигнатуру и блок запасного адреса:

```python
def apply_metadata(
    group: ProfileGroup, metadata: SubscriptionMetadata, *, may_forget_fallback: bool = False
) -> None:
```

```python
    # new_url не сохраняется: это одноразовое предложение по итогам обновления.
    # Запасной адрес нужен позже — когда обновление не удастся.
    fallback_url = metadata.fallback_url.strip()
    if is_acceptable_subscription_url(fallback_url):
        group.sub_fallback_url = fallback_url
    elif may_forget_fallback:
        group.sub_fallback_url = ""
```

**Step 5: Загрузка в `src/sub/updater.py`**

Импорты:

```python
from src.sub.fallback import FallbackExhaustedError, display_error, is_worth_trying, usable_url
```

В `__init__` после `self.new_url = ""`:

```python
        # Запасной адрес, с которого загружен последний update(); пусто — основной.
        self.used_fallback_url = ""
```

В `update()` заменить начало и блок метаданных:

```python
        self.new_url = ""
        self.used_fallback_url = ""
        fetched = self._fetch_with_fallback(url, group_id)
        beans = self.parse(fetched.content)
```

```python
        if group is not None:
            # Забыть запасной адрес может только ответ основного с серверами: страница
            # CDN с кодом 200 разбирается как пустой список и стёрла бы адрес при сбое CDN.
            from_fallback = bool(self.used_fallback_url)
            apply_metadata(group, metadata, may_forget_fallback=bool(beans) and not from_fallback)
            group.sub_empty = not beans
            group.sub_via_fallback = from_fallback
```

Новый метод перед `update()`:

```python
    def _fetch_with_fallback(self, url: str, group_id: int | None) -> FetchedSubscription:
        """Fetch the primary address, then once the provider's fallback address."""
        try:
            return self.fetch_response(url)
        except (requests.RequestException, SubscriptionPolicyError) as primary_error:
            if not is_worth_trying(primary_error):
                raise
            fallback_url = usable_url(url, self._stored_fallback(group_id))
            if fallback_url is None:
                raise
            # В журнал — тип ошибки: в тексте и адресе лежит токен подписки.
            logger.warning(
                "Основной адрес подписки не сработал (%s), пробую запасной",
                type(primary_error).__name__,
            )
            try:
                fetched = self.fetch_response(fallback_url)
            except (requests.RequestException, SubscriptionPolicyError) as fallback_error:
                raise FallbackExhaustedError(
                    display_error(primary_error, fallback_error)
                ) from fallback_error
            self.used_fallback_url = fallback_url
            return fetched

    def _stored_fallback(self, group_id: int | None) -> str:
        """The stored address of this group; without a group it would be someone else's."""
        if group_id is None or not self._profiles:
            return ""
        group = self._profiles.get_group(group_id)
        return group.sub_fallback_url if group is not None else ""
```

**Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_sub_fallback.py tests/test_sub_updater.py tests/test_sub_url_change.py tests/test_sub_metadata.py -q --no-cov`
Expected: PASS.

**Step 7: Commit**

```bash
git add src/db/profiles.py src/sub/metadata.py src/sub/updater.py tests/test_sub_fallback.py
git commit -m "feat(sub): загружать подписку с запасного адреса при сбое основного"
```

---

### Task 4: Тексты ошибки и диалога

**Files:**
- Modify: `src/sub/url_change.py` (константы причин, строки 11-12)
- Modify: `src/ui/logic/subscriptions_view.py` (`describe_update_error`, `describe_url_change`)
- Test: `tests/test_ui_logic_subscriptions_view.py`

**Step 1: Write the failing tests**

Добавить в `tests/test_ui_logic_subscriptions_view.py`:

```python
def test_both_addresses_failing_is_described_by_the_chosen_error():
    from src.sub.errors import SubscriptionHttpError
    from src.sub.fallback import FallbackExhaustedError
    from src.ui.logic.subscriptions_view import describe_update_error

    error = FallbackExhaustedError(SubscriptionHttpError(503))

    assert describe_update_error(error) == "сервер ответил 503"


def test_used_fallback_question_says_the_servers_are_already_loaded():
    from src.sub.url_change import REASON_FALLBACK_USED, UrlChangeProposal
    from src.ui.logic.subscriptions_view import describe_url_change

    proposal = UrlChangeProposal(1, "https://backup.example/sub", REASON_FALLBACK_USED)
    heading, body = describe_url_change("Основная", "https://old.example/sub", proposal)

    assert heading == "Сменить адрес подписки?"
    assert "серверы загружены с запасного" in body
    assert "насовсем" in body
    assert "https://backup.example/sub" in body
    assert "https://old.example/sub" in body
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ui_logic_subscriptions_view.py -q --no-cov`
Expected: FAIL: нет `REASON_FALLBACK_USED`, а `describe_update_error` возвращает текст обёртки.

**Step 3: Write the implementation**

В `src/sub/url_change.py` после `REASON_FALLBACK_URL`:

```python
REASON_FALLBACK_USED = "fallback-used"  # серверы уже загружены с запасного адреса
```

В `describe_update_error` после импортов:

```python
    from src.sub.fallback import FallbackExhaustedError

    if isinstance(error, FallbackExhaustedError):
        error = error.display_error
```

`describe_url_change` целиком:

```python
def describe_url_change(name: str, current_url: str, proposal: Any) -> tuple[str, str]:
    """Heading and body of the "change the subscription address?" question."""
    from src.sub.url_change import REASON_FALLBACK_URL, REASON_FALLBACK_USED

    if proposal.reason == REASON_FALLBACK_USED:
        lead = (
            f"Основной адрес подписки «{name}» не ответил, серверы загружены с запасного. "
            "Перейти на него насовсем?"
        )
    elif proposal.reason == REASON_FALLBACK_URL:
        lead = f"Обновить подписку «{name}» не удалось. Провайдер оставил запасной адрес:"
    else:
        lead = f"Провайдер подписки «{name}» сообщил новый адрес:"
    body = f"{lead}\n{proposal.new_url}\n\nСейчас используется:\n{current_url}"
    return "Сменить адрес подписки?", body
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ui_logic_subscriptions_view.py -q --no-cov`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/sub/url_change.py src/ui/logic/subscriptions_view.py tests/test_ui_logic_subscriptions_view.py
git commit -m "feat(sub): тексты про загрузку с запасного адреса"
```

---

### Task 5: `AppController`

**Files:**
- Modify: `src/ui/controller.py` (`update_group`:200-212, `update_subscription`:468-473, `default_subscription_updater`:485-501, `_propose_fallback_url`:503-512, `refresh_subscriptions`:566-574)
- Test: `tests/test_ui_controller.py`

**Step 1: Write the failing tests**

Добавить в `tests/test_ui_controller.py` после `test_confirmed_url_change_switches_the_group_and_refreshes`:

```python
PRIMARY_URL = "https://sub.example/list"
BACKUP_URL = "https://backup.example/sub"


def _subscription_response(body="", status=200, headers=None):
    response = requests.Response()
    response.status_code = status
    response._content = body.encode("utf-8")
    response._content_consumed = True
    response.headers = headers or {}
    return response


def _fallback_group(controller):
    group = controller.add_group("Demo")
    group.subscription_url = PRIMARY_URL
    group.is_subscription = True
    group.sub_fallback_url = BACKUP_URL
    return group


def _run_update(controller, group, routes):
    def pinned_get(url, **_kwargs):
        return routes[url]

    with patch("src.sub.updater.pinned_get", pinned_get):
        controller.update_subscription(group.id)
        _wait_subscriptions(controller)


def test_an_update_through_the_fallback_keeps_the_address_and_asks(made):
    controller, shell, _ = made
    group = _fallback_group(controller)

    _run_update(
        controller,
        group,
        {
            PRIMARY_URL: _subscription_response("down", status=503),
            BACKUP_URL: _subscription_response(LINK),
        },
    )

    assert group.subscription_url == PRIMARY_URL
    assert group.sub_via_fallback is True
    assert shell.last_toast == "Обновлено серверов: 1"
    assert shell.confirms[-1].kind == CONFIRM_URL_CHANGE
    assert "серверы загружены с запасного" in shell.confirms[-1].body
    assert BACKUP_URL in shell.confirms[-1].body


def test_a_new_address_goes_before_the_fallback_question(made):
    controller, shell, _ = made
    group = _fallback_group(controller)

    _run_update(
        controller,
        group,
        {
            PRIMARY_URL: _subscription_response("down", status=503),
            BACKUP_URL: _subscription_response(
                LINK, headers={"new-url": "https://new.example/sub"}
            ),
        },
    )

    assert len(shell.confirms) == 1
    assert "https://new.example/sub" in shell.confirms[-1].body
    assert "сообщил новый адрес" in shell.confirms[-1].body


def test_both_addresses_failing_shows_the_error_without_a_question(made):
    controller, shell, _ = made
    group = _fallback_group(controller)

    _run_update(
        controller,
        group,
        {
            PRIMARY_URL: _subscription_response("down", status=503),
            BACKUP_URL: _subscription_response("down", status=502),
        },
    )

    assert shell.last_toast == "Не удалось обновить подписки: сервер ответил 503"
    assert shell.confirms == []


@pytest.mark.parametrize("status", [404, 410])
def test_a_revoked_token_offers_no_address_change(made, status):
    controller, shell, _ = made
    group = _fallback_group(controller)

    _run_update(controller, group, {PRIMARY_URL: _subscription_response("no", status=status)})

    assert shell.confirms == []


def test_another_failure_still_offers_the_address(made):
    controller, shell, _ = made
    group = _fallback_group(controller)

    _run_update(controller, group, {PRIMARY_URL: _subscription_response("no", status=401)})

    assert "Обновить подписку «Demo» не удалось" in shell.confirms[-1].body


def test_refreshing_all_follows_the_same_rule_for_a_revoked_token(made):
    controller, shell, _ = made
    _fallback_group(controller)
    routes = {PRIMARY_URL: _subscription_response("no", status=404)}

    with patch("src.sub.updater.pinned_get", lambda url, **_kwargs: routes[url]):
        controller.refresh_subscriptions()
        _wait_subscriptions(controller)

    assert shell.confirms == []


def test_a_changed_address_forgets_the_previous_providers_fallback(made):
    controller, _shell, _ = made
    group = _fallback_group(controller)
    group.sub_via_fallback = True

    controller.update_group(group.id, name="Demo", url="https://other.example/sub")

    assert group.sub_fallback_url == ""
    assert group.sub_via_fallback is False


def test_renaming_keeps_the_fallback(made):
    controller, _shell, _ = made
    group = _fallback_group(controller)

    controller.update_group(group.id, name="Новое", url=PRIMARY_URL)
    controller.update_group(group.id, name="Ещё новее")

    assert group.sub_fallback_url == BACKUP_URL
```

К импортам файла добавить `import requests` и `from unittest.mock import patch`: `pytest`, `LINK`, `FakeShell.confirms` и `last_toast` там уже есть.

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ui_controller.py -q --no-cov`
Expected: новые тесты FAIL. `test_another_failure_still_offers_the_address` и `test_renaming_keeps_the_fallback` могут пройти сразу: это фиксация текущего поведения.

**Step 3: Write the implementation**

`update_group`:

```python
        group.name = name
        if url is not None and url != group.subscription_url:
            group.subscription_url = url
            # Запасной адрес относился к прежнему: при смене провайдера его сбой
            # молча подтянул бы серверы старой подписки с её токеном.
            group.sub_fallback_url = ""
            group.sub_via_fallback = False
        self._save_profiles()
```

`update_subscription`, функция `work`:

```python
        def work() -> int:
            try:
                return updater(group_id, url)
            except Exception as error:
                self._propose_fallback_url(group_id, url, error)
                raise
```

Хвост `default_subscription_updater` и импорт:

```python
        from src.sub.url_change import REASON_FALLBACK_USED, REASON_NEW_URL, propose_url_change
```

```python
        beans = updater.update(url, group_id)

        # Очередь показывает одно предложение: прямое указание провайдера важнее.
        for candidate, reason in (
            (updater.new_url, REASON_NEW_URL),
            (updater.used_fallback_url, REASON_FALLBACK_USED),
        ):
            proposal = propose_url_change(group_id, url, candidate, reason)
            if proposal is not None:
                self._url_proposals.append(proposal)
        return len(beans)
```

`_propose_fallback_url`:

```python
    def _propose_fallback_url(self, group_id: int, url: str, error: BaseException) -> None:
        """Queue the provider's fallback address after a failed update."""
        from src.sub.fallback import can_propose_after
        from src.sub.url_change import REASON_FALLBACK_URL, propose_url_change

        if not can_propose_after(error):
            return
        group = self.context.profiles.get_group(group_id)
        if group is None:
            return
        proposal = propose_url_change(group_id, url, group.sub_fallback_url, REASON_FALLBACK_URL)
        if proposal is not None:
            self._url_proposals.append(proposal)
```

`refresh_subscriptions`, функция `work`: заменить вызов на `self._propose_fallback_url(group_id, url, e)`.

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ui_controller.py -q --no-cov`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/ui/controller.py tests/test_ui_controller.py
git commit -m "feat(ui): предлагать смену адреса после загрузки с запасного"
```

---

### Task 6: Подпись в строке подписки (логика, GTK, Qt)

**Files:**
- Modify: `src/ui/logic/subscriptions_view.py` (константа, `SubscriptionRow`, `build_subscription_rows`)
- Modify: `src/ui/pages/subscriptions.py` (импорты:16-17, `__init__`:45, очистка:93, строка:129-136, помощник:244)
- Modify: `src/ui/qt/dialogs/settings_pages.py` (импорты:32-33, `refresh`:112-113)
- Test: `tests/test_ui_logic_subscriptions_view.py`, `tests/test_ui_pages_subscriptions.py`, `tests/test_ui_qt_settings.py`

**Step 1: Write the failing tests**

В `FakeGroup` обоих файлов `tests/test_ui_logic_subscriptions_view.py` и `tests/test_ui_pages_subscriptions.py` после `sub_empty` добавить `sub_via_fallback: bool = False`.

В `tests/test_ui_logic_subscriptions_view.py`:

```python
def test_update_through_the_fallback_is_flagged_on_the_row():
    assert _row(sub_via_fallback=True).via_fallback is True
    assert _row().via_fallback is False
```

В `tests/test_ui_pages_subscriptions.py`:

```python
def test_an_update_through_the_fallback_is_marked_in_its_row(page, data):
    groups, counts = data
    groups[1].sub_via_fallback = True
    page.set_data(groups, counts)

    assert page.is_via_fallback_shown_for_test(group_id=1)
    assert not page.is_via_fallback_shown_for_test(group_id=2)
```

В `tests/test_ui_qt_settings.py`:

```python
def test_an_update_through_the_fallback_is_marked(app):
    _subscription(app, sub_via_fallback=True)

    dialog = _open(app)

    assert "Обновлено через запасной адрес" in dialog.subscriptions.tree.topLevelItem(0).text(3)


def test_a_normal_update_has_no_fallback_mark(app):
    _subscription(app)

    dialog = _open(app)

    assert "запасной" not in dialog.subscriptions.tree.topLevelItem(0).text(3)
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ui_logic_subscriptions_view.py -q --no-cov && make test-gtk && make test-qt`
Expected: FAIL: нет `via_fallback` и `is_via_fallback_shown_for_test`, в Qt нет подписи.

**Step 3: Логика**

В `src/ui/logic/subscriptions_view.py`:

```python
VIA_FALLBACK_TEXT = "Обновлено через запасной адрес"
```

В `SubscriptionRow` после `empty`:

```python
    # Последнее обновление пришло с запасного адреса провайдера.
    via_fallback: bool = False
```

В `build_subscription_rows` после `empty=group.sub_empty,`:

```python
                via_fallback=group.sub_via_fallback,
```

**Step 4: GTK**

В `src/ui/pages/subscriptions.py`: импортировать `VIA_FALLBACK_TEXT`, рядом с `self._empty_labels` объявить `self._via_fallback_labels: dict[int, Gtk.Label] = {}`, рядом с `self._empty_labels.clear()` добавить `self._via_fallback_labels.clear()`.

После блока `if row.empty:`:

```python
        if row.via_fallback:
            via_fallback = Gtk.Label(label=VIA_FALLBACK_TEXT, xalign=1.0)
            via_fallback.add_css_class("caption")
            via_fallback.add_css_class("dim-label")
            meta_box.append(via_fallback)
            self._via_fallback_labels[row.group_id] = via_fallback
```

После `is_empty_notice_shown_for_test`:

```python
    def is_via_fallback_shown_for_test(self, *, group_id: int) -> bool:
        return group_id in self._via_fallback_labels
```

**Step 5: Qt**

В `src/ui/qt/dialogs/settings_pages.py`: импортировать `VIA_FALLBACK_TEXT`, в `refresh` после блока `if row.empty:` с `details`:

```python
            if row.via_fallback:
                details = " · ".join(part for part in (details, VIA_FALLBACK_TEXT) if part)
```

**Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_ui_logic_subscriptions_view.py -q --no-cov && make test-gtk && make test-qt`
Expected: PASS.

**Step 7: Commit**

```bash
git add src/ui/logic/subscriptions_view.py src/ui/pages/subscriptions.py src/ui/qt/dialogs/settings_pages.py tests/test_ui_logic_subscriptions_view.py tests/test_ui_pages_subscriptions.py tests/test_ui_qt_settings.py
git commit -m "feat(ui): показывать обновление через запасной адрес в GTK и Qt"
```

---

### Task 7: Документация и полная проверка

**Files:**
- Modify: `docs/plans/2026-11-02-shared-ui-design.md` (рядом с «**Строка группы:**», строка 184)

**Step 1: Дополнить общий дизайн**

После абзаца «**Колонки:**» добавить:

```markdown
**Строка подписки:** «Пустой список серверов» и «Обновлено через запасной адрес»
показываются одинаково в GTK и Qt. Тексты — в `src/ui/logic/subscriptions_view.py`.
```

**Step 2: Запустить все проверки**

Run: `python cli.py lint-all && uv run pytest -q && make test-gtk && make test-tray && make test-qt`
Expected: всё проходит. Если упал `format --check`, выполнить `python cli.py format` и добавить изменения в коммит.

**Step 3: Проверить, что токен не попадает в журнал**

Run: `grep -n "logger\." src/sub/fallback.py src/sub/updater.py`
Expected: в новых сообщениях нет URL, только `type(error).__name__`.

**Step 4: Commit**

```bash
git add docs/plans/2026-11-02-shared-ui-design.md
git commit -m "docs: подписи строки подписки в общем дизайне"
```
