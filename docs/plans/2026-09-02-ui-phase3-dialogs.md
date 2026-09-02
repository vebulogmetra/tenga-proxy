# Этап 3: диалоги и подключение (GTK4 + libadwaita)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Заменить заглушки действий настоящими диалогами libadwaita и подключить профиль по двойному щелчку через GTK-независимый сервис подключения.

**Architecture:** Логика подключения/отключения переезжает из `src/ui/app.py` (GTK3) в `src/core/connection.py` — класс `ConnectionService`, не знающий о GTK и возвращающий результат структурой. `TengaApplication` вызывает сервис в фоновом потоке и отражает состояние на карточке. Диалоги пишутся заново на `Adw.Dialog` / `Adw.AlertDialog` / `Adw.PreferencesDialog` (GTK3-версии остаются нетронутыми до этапа 5); валидация каждой формы выносится в `src/ui/logic/forms.py` и покрывается тестами без дисплея.

**Tech Stack:** GTK 4.14, libadwaita 1.5 (`Adw.Dialog`, `Adw.AlertDialog`, `Adw.PreferencesDialog`, `Adw.EntryRow`, `Adw.SwitchRow`, `Adw.ComboRow`, `Adw.SpinRow`, `Gtk.PopoverMenu`, `Gtk.GestureClick`), Python 3.11, pytest, ruff.

---

## Уточнения после разведки кода

1. **Логика подключения сейчас в `src/ui/app.py:314-508`** — `_connect`, `_disconnect`, `_reload_config`. Она перемешана с трей-уведомлениями (`self._tray.show_notification`) и GTK3-окном. Переносим в сервис, оставляя `app.py` работающим: GTK3-приложение продолжает жить до этапа 5, поэтому `app.py` должен вызывать сервис, а не дублировать код.

2. **`_connect` возвращает `bool`, но причина отказа теряется** — она попадает только в лог и трей. Сервис должен возвращать `ConnectionResult(ok, error, needs_root)` — сообщение нужно карточке статуса и тосту.

3. **Порядок в `_connect` важен:** сброс `vpn_auto_connected` → авто-VPN (если `enabled and auto_connect` и VPN ещё не активен) → `build_session_config` → запись `current_config.json` → `xray_manager.start` → `proxy_state.set_running` → системный прокси **или** TUN-маршруты (при неудаче маршрутов — откат: `stop()` + `set_stopped()`) → `monitor.start()`. Порядок переносится дословно.

4. **`_disconnect` терпимо к сбоям на каждом шаге** — каждая часть в своём `try`, чтобы падение VPN-отключения не оставило xray запущенным. Это сохраняем.

5. **Подключение блокирует поток** — `xray_manager.start` запускает процесс и ждёт, `connect_vpn` вызывает `nmcli`. В GTK4 это должно идти через `run_in_background` (`src/ui/logic/async_utils.py`), иначе окно замирает.

6. **`ProfileManager.add_profile` сохраняет сам?** Нет — в `app.py:_on_add_profile` после `add_profile` идёт `profiles.save()`. Диалоги должны сохранять явно.

7. **Контекстное меню GTK3 (`main_window.py:1500-1540`)** для профиля: Подключить · VPN и маршруты… · Тест задержки · — · Редактировать · Удалить. Для группы: Развернуть/Свернуть · Тест задержки · — · Редактировать · Удалить. Для подписки (`main_window.py:1034-1046`): Обновить · Редактировать · Удалить. Этот набор воспроизводим на `Gtk.PopoverMenu`.

8. **`ProfilesPage` уже объявляет сигнал `profile-context(int)`, но его никто не эмитирует** — обработчика жеста в странице нет. Нужен `Gtk.GestureClick` с `button=3` плюс long-press, и сигнал должен нести признак «группа или профиль».

9. **`Adw.Dialog` в 1.5 асинхронный** — `dialog.present(parent)` и `choose()`/сигнал `closed`; синхронного `run()`, как в GTK3, нет. Все вызывающие места переписываются на колбэки.

10. **Диалог настроек (`settings.py`, 633 строки)** правит `DataStore`: адрес/порт inbound, режим прокси (`ProxyMode`), имя и MTU TUN, уровень лога, мониторинг (вкл + интервал), DNS (провайдер, свой URL, через прокси). Плюс страницы «Логи» и «О программе». На `Adw.PreferencesDialog` это четыре `Adw.PreferencesPage`.

11. **Диалог VPN и маршрутов (`profile_vpn_settings.py`, 892 строки)** — самый крупный: три страницы (профиль, VPN, маршрутизация) с редактированием списков доменов/сетей. Правит `profile.vpn_settings` и `profile.routing_settings`.

12. **Смена настроек на лету** — `show_settings_dialog` принимает `on_config_reload`, который вызывает `_reload_config` при активном соединении. Это поведение сохраняем.

13. **`_ACCELS` уже содержит `app.settings`, `app.add-profile`, `app.add-subscription`** — ускорители работают, заменяются только обработчики.

14. **Проверка на реальном конфиге обязательна.** Пользовательское приложение запущено: **никаких настоящих подключений/отключений**. Подключение проверяется только на фиктивном `ConnectionService` и на unit-тестах сервиса с моками `XrayManager`.

---

### Задача 3.1: Сервис подключения (без GTK)

**Files:**
- Create: `src/core/connection.py`
- Test: `tests/test_core_connection.py`

**Step 1: Написать падающие тесты**

```python
"""Tests for the GTK-free connection service."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from src.core.connection import ConnectionResult, ConnectionService


@dataclass
class FakeVpn:
    enabled: bool = False
    connection_name: str = "my-vpn"
    auto_connect: bool = False


@dataclass
class FakeProfile:
    id: int = 1
    name: str = "P"
    vpn_settings: FakeVpn | None = None
    routing_settings: object | None = None
    bean: object = field(default_factory=lambda: MagicMock(server_address="1.2.3.4"))


def make_context(tmp_path, profile):
    context = MagicMock()
    context.config_dir = tmp_path
    context.profiles.get_profile.return_value = profile
    context.xray_manager.start.return_value = (True, "")
    context.xray_manager.stop.return_value = (True, "")
    context.config.proxy_mode = "system"
    context.config.inbound_socks_port = 2080
    context.proxy_state.is_running = False
    return context


def test_connect_missing_profile_reports_the_error(tmp_path):
    context = make_context(tmp_path, None)
    service = ConnectionService(context)
    result = service.connect(7)
    assert not result.ok
    assert "не найден" in result.error


def test_connect_starts_xray_and_marks_the_state(tmp_path, monkeypatch):
    profile = FakeProfile()
    context = make_context(tmp_path, profile)
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    service = ConnectionService(context)
    result = service.connect(1)
    assert result.ok
    context.xray_manager.start.assert_called_once()
    context.proxy_state.set_running.assert_called_once()


def test_connect_writes_the_config_for_debugging(tmp_path, monkeypatch):
    profile = FakeProfile()
    context = make_context(tmp_path, profile)
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    ConnectionService(context).connect(1)
    assert (tmp_path / "current_config.json").exists()


def test_connect_reports_the_xray_error(tmp_path, monkeypatch):
    profile = FakeProfile()
    context = make_context(tmp_path, profile)
    context.xray_manager.start.return_value = (False, "binary not found")
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    result = ConnectionService(context).connect(1)
    assert not result.ok
    assert result.error == "binary not found"
    context.proxy_state.set_running.assert_not_called()


def test_connect_without_a_config_stops_early(tmp_path, monkeypatch):
    profile = FakeProfile()
    context = make_context(tmp_path, profile)
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: None)
    result = ConnectionService(context).connect(1)
    assert not result.ok
    context.xray_manager.start.assert_not_called()


def test_tun_route_failure_rolls_the_start_back(tmp_path, monkeypatch):
    """Маршруты не легли — xray не должен остаться запущенным."""
    profile = FakeProfile()
    context = make_context(tmp_path, profile)
    context.config.proxy_mode = "tun"
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr(
        "src.core.connection.apply_tun_routes", lambda *_: (False, None, "no permission")
    )
    result = ConnectionService(context).connect(1)
    assert not result.ok
    assert "no permission" in result.error
    context.xray_manager.stop.assert_called_once()
    context.proxy_state.set_stopped.assert_called_once()


def test_vpn_is_connected_before_the_proxy_when_asked(tmp_path, monkeypatch):
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    calls = []
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    monkeypatch.setattr("src.core.connection.is_vpn_active", lambda _n: False)
    monkeypatch.setattr(
        "src.core.connection.connect_vpn", lambda n: (calls.append(n), True)[1]
    )
    ConnectionService(context).connect(1)
    assert calls == ["my-vpn"]
    assert context.proxy_state.vpn_auto_connected is True


def test_an_already_active_vpn_is_not_touched(tmp_path, monkeypatch):
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    monkeypatch.setattr("src.core.connection.is_vpn_active", lambda _n: True)
    called = []
    monkeypatch.setattr("src.core.connection.connect_vpn", lambda n: called.append(n))
    ConnectionService(context).connect(1)
    assert called == []


def test_a_failing_vpn_does_not_block_the_proxy(tmp_path, monkeypatch):
    """VPN — вспомогательный шаг: прокси должен подняться и без него."""
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    monkeypatch.setattr("src.core.connection.is_vpn_active", lambda _n: False)
    monkeypatch.setattr("src.core.connection.connect_vpn", lambda _n: False)
    assert ConnectionService(context).connect(1).ok


def test_connect_while_running_disconnects_first(tmp_path, monkeypatch):
    profile = FakeProfile()
    context = make_context(tmp_path, profile)
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 5
    context.proxy_state.started_mode = "system"
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 1})
    monkeypatch.setattr("src.core.connection.set_system_proxy", lambda **_: True)
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: True)
    ConnectionService(context).connect(1)
    context.xray_manager.stop.assert_called_once()


def test_disconnect_stops_xray_and_clears_the_proxy(tmp_path, monkeypatch):
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.started_mode = "system"
    cleared = []
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: cleared.append(1))
    result = ConnectionService(context).disconnect()
    assert result.ok
    context.xray_manager.stop.assert_called_once()
    context.proxy_state.set_stopped.assert_called_once()
    assert cleared == [1]


def test_disconnect_survives_a_failing_vpn_step(tmp_path, monkeypatch):
    """Падение отключения VPN не должно оставить xray работающим."""
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    context.proxy_state.started_profile_id = 1
    context.proxy_state.started_mode = "system"
    context.proxy_state.vpn_auto_connected = True

    def boom(_name):
        raise RuntimeError("nmcli failed")

    monkeypatch.setattr("src.core.connection.disconnect_vpn", boom)
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: True)
    result = ConnectionService(context).disconnect()
    assert result.ok
    context.proxy_state.set_stopped.assert_called_once()


def test_vpn_is_left_alone_when_it_was_not_auto_connected(tmp_path, monkeypatch):
    profile = FakeProfile(vpn_settings=FakeVpn(enabled=True, auto_connect=True))
    context = make_context(tmp_path, profile)
    context.proxy_state.started_profile_id = 1
    context.proxy_state.started_mode = "system"
    context.proxy_state.vpn_auto_connected = False
    called = []
    monkeypatch.setattr("src.core.connection.disconnect_vpn", lambda n: called.append(n))
    monkeypatch.setattr("src.core.connection.clear_system_proxy", lambda: True)
    ConnectionService(context).disconnect()
    assert called == []


def test_reload_without_a_running_proxy_is_refused(tmp_path):
    context = make_context(tmp_path, FakeProfile())
    context.proxy_state.is_running = False
    assert not ConnectionService(context).reload_config().ok


def test_reload_pushes_the_new_config(tmp_path, monkeypatch):
    profile = FakeProfile()
    context = make_context(tmp_path, profile)
    context.proxy_state.is_running = True
    context.proxy_state.started_profile_id = 1
    context.xray_manager.reload_config.return_value = (True, "")
    monkeypatch.setattr("src.core.connection.build_session_config", lambda *_: {"a": 2})
    assert ConnectionService(context).reload_config().ok
    context.xray_manager.reload_config.assert_called_once()
```

**Step 2: Запустить тесты и убедиться, что они падают**

Run: `uv run pytest tests/test_core_connection.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.core.connection'`

**Step 3: Написать сервис**

`src/core/connection.py`: `ConnectionResult` (frozen dataclass: `ok: bool`, `error: str = ""`), `ConnectionService(context)` с методами `connect(profile_id) -> ConnectionResult`, `disconnect() -> ConnectionResult`, `reload_config() -> ConnectionResult`. Импорты `build_session_config`, `set_system_proxy`, `clear_system_proxy`, `connect_vpn`, `disconnect_vpn`, `is_vpn_active`, `apply_tun_routes`, `restore_tun_routes`, `normalize_proxy_mode`, `should_manage_system_proxy` — на уровне модуля, чтобы тесты могли их подменять. Состояние TUN-маршрутов держится в `self._tun_route_state`. Порядок шагов — дословно из `src/ui/app.py:314-508` (см. уточнение 3), уведомления трея выброшены.

**Step 4: Запустить тесты**

Run: `uv run pytest tests/test_core_connection.py -q`
Expected: PASS (16 тестов)

**Step 5: Коммит**

```bash
git add src/core/connection.py tests/test_core_connection.py
git commit -m "feat: extract the connection logic into a GTK-free service"
```

---

### Задача 3.2: Валидация форм (без GTK)

**Files:**
- Create: `src/ui/logic/forms.py`
- Test: `tests/test_ui_logic_forms.py`

**Step 1: Написать падающие тесты**

```python
"""Tests for the dialog form validation (no GTK needed)."""

from __future__ import annotations

import pytest

from src.ui.logic.forms import (
    parse_host_list,
    validate_group_name,
    validate_profile_link,
    validate_subscription,
)


def test_a_valid_link_is_accepted():
    result = validate_profile_link("vless://uuid@host:443?type=tcp#Name")
    assert result.ok
    assert result.bean is not None


def test_an_empty_link_asks_for_input():
    result = validate_profile_link("   ")
    assert not result.ok
    assert result.message == "Введите ссылку подключения"


def test_an_unparsable_link_is_rejected():
    result = validate_profile_link("not a link")
    assert not result.ok
    assert "разобрать" in result.message


def test_the_link_is_trimmed_before_parsing():
    """Ссылка из буфера часто приходит с переводом строки."""
    result = validate_profile_link("  vless://uuid@host:443?type=tcp#Name\n")
    assert result.ok


def test_a_custom_name_overrides_the_one_from_the_link():
    result = validate_profile_link("vless://uuid@host:443?type=tcp#FromLink", name="Mine")
    assert result.bean.name == "Mine"


def test_an_empty_custom_name_keeps_the_one_from_the_link():
    result = validate_profile_link("vless://uuid@host:443?type=tcp#FromLink", name="  ")
    assert result.bean.name == "FromLink"


def test_a_subscription_needs_a_name():
    result = validate_subscription("", "https://example.com/sub")
    assert not result.ok
    assert "название" in result.message.lower()


def test_a_subscription_needs_a_url():
    result = validate_subscription("Sub", "")
    assert not result.ok
    assert "url" in result.message.lower()


@pytest.mark.parametrize("url", ["ftp://example.com", "example.com", "//example.com"])
def test_a_subscription_url_must_be_http(url):
    result = validate_subscription("Sub", url)
    assert not result.ok
    assert "http" in result.message.lower()


@pytest.mark.parametrize("url", ["http://example.com/s", "https://example.com/s"])
def test_a_valid_subscription_is_accepted(url):
    result = validate_subscription("Sub", url)
    assert result.ok
    assert result.value == ("Sub", url)


def test_subscription_fields_are_trimmed():
    result = validate_subscription("  Sub  ", "  https://example.com  ")
    assert result.value == ("Sub", "https://example.com")


def test_a_group_needs_a_name():
    assert not validate_group_name("   ").ok


def test_a_group_name_is_trimmed():
    assert validate_group_name("  Home  ").value == "Home"


def test_a_host_list_splits_on_newlines_and_commas():
    assert parse_host_list("a.com\nb.com, c.com") == ["a.com", "b.com", "c.com"]


def test_a_host_list_drops_blanks_and_duplicates():
    """Дубликаты в правилах маршрутизации бесполезны и путают счётчик."""
    assert parse_host_list("a.com\n\n a.com \n b.com\n") == ["a.com", "b.com"]


def test_an_empty_host_list_is_empty():
    assert parse_host_list("  \n \n") == []
```

**Step 2: Запустить и убедиться в падении**

Run: `uv run pytest tests/test_ui_logic_forms.py -q`
Expected: FAIL — модуля нет

**Step 3: Реализация**

`src/ui/logic/forms.py`: frozen `FormResult(ok: bool, message: str = "", value=None, bean=None)`; функции `validate_profile_link(link, *, name="")`, `validate_subscription(name, url)`, `validate_group_name(name)`, `parse_host_list(text)`. `parse_link` импортируется внутри функции — модуль должен грузиться без GTK-зависимостей `src.fmt`.

**Step 4: Запустить тесты**

Run: `uv run pytest tests/test_ui_logic_forms.py -q`
Expected: PASS (17 тестов)

**Step 5: Коммит**

```bash
git add src/ui/logic/forms.py tests/test_ui_logic_forms.py
git commit -m "feat: add dialog form validation without GTK"
```

---

### Задача 3.3: Диалог добавления профиля

**Files:**
- Create: `src/ui/dialogs4/__init__.py`, `src/ui/dialogs4/add_profile.py`
- Test: `tests/test_ui_dialogs_add_profile.py` (маркер `gtk`)

**Step 1: Тест**

```python
"""GTK4 add-profile dialog."""

import pytest

pytestmark = pytest.mark.gtk

from src.ui.dialogs4.add_profile import AddProfileDialog  # noqa: E402


def test_a_valid_link_enables_the_add_button(gtk_ready):
    dialog = AddProfileDialog()
    dialog.link_row.set_text("vless://uuid@host:443?type=tcp#Name")
    assert dialog.add_button.get_sensitive()


def test_an_invalid_link_disables_it(gtk_ready):
    dialog = AddProfileDialog()
    dialog.link_row.set_text("garbage")
    assert not dialog.add_button.get_sensitive()


def test_an_empty_link_leaves_the_hint_blank(gtk_ready):
    """Пустое поле — не ошибка: диалог только что открыли."""
    dialog = AddProfileDialog()
    dialog.link_row.set_text("")
    assert dialog.status_label.get_text() == ""


def test_the_hint_names_the_parsed_protocol(gtk_ready):
    dialog = AddProfileDialog()
    dialog.link_row.set_text("vless://uuid@host:443?type=tcp#Name")
    assert "VLESS" in dialog.status_label.get_text()


def test_the_name_is_prefilled_from_the_link(gtk_ready):
    dialog = AddProfileDialog()
    dialog.link_row.set_text("vless://uuid@host:443?type=tcp#FromLink")
    assert dialog.name_row.get_text() == "FromLink"


def test_a_typed_name_is_not_overwritten(gtk_ready):
    dialog = AddProfileDialog()
    dialog.name_row.set_text("Mine")
    dialog.link_row.set_text("vless://uuid@host:443?type=tcp#FromLink")
    assert dialog.name_row.get_text() == "Mine"


def test_get_profile_returns_the_bean(gtk_ready):
    dialog = AddProfileDialog()
    dialog.link_row.set_text("vless://uuid@host:443?type=tcp#Name")
    bean = dialog.get_profile()
    assert bean is not None and bean.name == "Name"


def test_get_profile_is_none_without_a_link(gtk_ready):
    assert AddProfileDialog().get_profile() is None
```

**Step 2: Запустить, убедиться в падении**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_dialogs_add_profile.py -q -m gtk`
Expected: FAIL — модуля нет

**Step 3: Реализация**

`AddProfileDialog(Adw.Dialog)`, `__gtype_name__ = "TengaAddProfileDialog"`. Содержимое: `Adw.ToolbarView` с `Adw.HeaderBar` (кнопки «Отмена» и «Добавить», у второй `suggested-action`), `Adw.PreferencesPage` → `Adw.PreferencesGroup` со строками `Adw.EntryRow` («Ссылка», «Имя») и `Gtk.Label` подсказки под ними. Кнопка вставки из буфера — `Gtk.Button` с `edit-paste-symbolic` в суффиксе строки ссылки, читает `Gdk.Display.get_default().get_clipboard()` асинхронно (`read_text_async`). Валидация — через `validate_profile_link` на `notify::text`. Сигнал `profile-added` с `ProxyBean` в `GObject.Property`, либо метод `get_profile()` + сигнал `closed`. Кнопка «Добавить» деактивна, пока ссылка не разобрана.

**Step 4: Тесты**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_dialogs_add_profile.py -q -m gtk`
Expected: PASS (8)

**Step 5: Коммит**

```bash
git add src/ui/dialogs4/ tests/test_ui_dialogs_add_profile.py
git commit -m "feat: add the GTK4 add-profile dialog"
```

---

### Задача 3.4: Диалоги подписки и группы, подтверждение удаления

**Files:**
- Create: `src/ui/dialogs4/subscription.py`, `src/ui/dialogs4/group.py`, `src/ui/dialogs4/confirm.py`
- Test: `tests/test_ui_dialogs_subscription.py`, `tests/test_ui_dialogs_group.py` (маркер `gtk`)

**Step 1: Тесты**

```python
# tests/test_ui_dialogs_subscription.py
import pytest

pytestmark = pytest.mark.gtk

from types import SimpleNamespace  # noqa: E402

from src.ui.dialogs4.subscription import SubscriptionDialog  # noqa: E402


def test_the_new_dialog_starts_empty(gtk_ready):
    dialog = SubscriptionDialog()
    assert dialog.name_row.get_text() == ""
    assert dialog.url_row.get_text() == ""


def test_an_existing_group_prefills_the_fields(gtk_ready):
    group = SimpleNamespace(name="Sub", subscription_url="https://e.com/s", last_updated=0)
    dialog = SubscriptionDialog(group=group)
    assert dialog.name_row.get_text() == "Sub"
    assert dialog.url_row.get_text() == "https://e.com/s"


def test_a_valid_url_enables_saving(gtk_ready):
    dialog = SubscriptionDialog()
    dialog.name_row.set_text("Sub")
    dialog.url_row.set_text("https://e.com/s")
    assert dialog.save_button.get_sensitive()


def test_a_non_http_url_blocks_saving(gtk_ready):
    dialog = SubscriptionDialog()
    dialog.name_row.set_text("Sub")
    dialog.url_row.set_text("ftp://e.com")
    assert not dialog.save_button.get_sensitive()


def test_a_missing_name_blocks_saving(gtk_ready):
    dialog = SubscriptionDialog()
    dialog.url_row.set_text("https://e.com/s")
    assert not dialog.save_button.get_sensitive()


def test_get_data_returns_the_trimmed_pair(gtk_ready):
    dialog = SubscriptionDialog()
    dialog.name_row.set_text("  Sub  ")
    dialog.url_row.set_text("  https://e.com/s  ")
    assert dialog.get_data() == ("Sub", "https://e.com/s")


def test_the_last_update_is_shown_when_known(gtk_ready):
    group = SimpleNamespace(name="S", subscription_url="https://e.com", last_updated=1_700_000_000)
    dialog = SubscriptionDialog(group=group)
    assert "2023" in dialog.updated_row.get_subtitle()


def test_a_never_updated_subscription_says_so(gtk_ready):
    group = SimpleNamespace(name="S", subscription_url="https://e.com", last_updated=0)
    assert SubscriptionDialog(group=group).updated_row.get_subtitle() == "Никогда"
```

```python
# tests/test_ui_dialogs_group.py
import pytest

pytestmark = pytest.mark.gtk

from types import SimpleNamespace  # noqa: E402

from src.ui.dialogs4.group import GroupDialog  # noqa: E402


def test_a_new_group_starts_empty(gtk_ready):
    assert GroupDialog().name_row.get_text() == ""


def test_an_existing_group_is_prefilled(gtk_ready):
    group = SimpleNamespace(name="Home", is_subscription=False)
    assert GroupDialog(group=group).name_row.get_text() == "Home"


def test_a_name_enables_saving(gtk_ready):
    dialog = GroupDialog()
    dialog.name_row.set_text("Home")
    assert dialog.save_button.get_sensitive()


def test_a_blank_name_blocks_saving(gtk_ready):
    dialog = GroupDialog()
    dialog.name_row.set_text("   ")
    assert not dialog.save_button.get_sensitive()


def test_get_name_is_trimmed(gtk_ready):
    dialog = GroupDialog()
    dialog.name_row.set_text("  Home  ")
    assert dialog.get_name() == "Home"
```

**Step 2: Запустить, убедиться в падении**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_dialogs_subscription.py tests/test_ui_dialogs_group.py -q -m gtk`
Expected: FAIL

**Step 3: Реализация**

`SubscriptionDialog(Adw.Dialog)` — строки `Adw.EntryRow` «Название» и «Адрес» (с кнопкой вставки), `Adw.ActionRow` «Обновлено» с подзаголовком (создаётся всегда, чтобы тест не зависел от наличия группы; текст — через `format_updated` из `src/ui/logic/subscriptions_view.py`). `GroupDialog(Adw.Dialog)` — одна строка имени; заголовок «Новая группа»/«Редактировать группу»/«Редактировать подписку» по признаку `is_subscription`. `confirm.py`: функция `confirm_delete(parent, title, body, on_confirm)` на `Adw.AlertDialog` с ответами `cancel`/`delete`, у `delete` — `Adw.ResponseAppearance.DESTRUCTIVE` и `set_default_response("cancel")`.

**Step 4: Тесты**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_dialogs_subscription.py tests/test_ui_dialogs_group.py -q -m gtk`
Expected: PASS (13)

**Step 5: Коммит**

```bash
git add src/ui/dialogs4/subscription.py src/ui/dialogs4/group.py src/ui/dialogs4/confirm.py tests/test_ui_dialogs_subscription.py tests/test_ui_dialogs_group.py
git commit -m "feat: add the GTK4 subscription, group and confirmation dialogs"
```

---

### Задача 3.5: Диалог редактирования профиля

**Files:**
- Create: `src/ui/dialogs4/edit_profile.py`
- Test: `tests/test_ui_dialogs_edit_profile.py` (маркер `gtk`)

**Step 1: Тест**

```python
import pytest

pytestmark = pytest.mark.gtk

from types import SimpleNamespace  # noqa: E402

from src.fmt import parse_link  # noqa: E402
from src.ui.dialogs4.edit_profile import EditProfileDialog  # noqa: E402

LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#Old"
OTHER = "vless://22222222-2222-2222-2222-222222222222@new.example:8443?type=tcp#New"


def make_profile():
    return SimpleNamespace(id=1, bean=parse_link(LINK))


def test_the_fields_are_prefilled_from_the_bean(gtk_ready):
    dialog = EditProfileDialog(make_profile())
    assert dialog.name_row.get_text() == "Old"
    assert dialog.address_row.get_text() == "host.example"
    assert dialog.port_row.get_value() == 443


def test_the_share_link_is_shown(gtk_ready):
    assert "vless://" in EditProfileDialog(make_profile()).link_row.get_text()


def test_applying_a_new_link_refreshes_the_fields(gtk_ready):
    dialog = EditProfileDialog(make_profile())
    dialog.link_row.set_text(OTHER)
    dialog.apply_link()
    assert dialog.name_row.get_text() == "New"
    assert dialog.address_row.get_text() == "new.example"
    assert dialog.port_row.get_value() == 8443


def test_a_broken_link_is_rejected_and_changes_nothing(gtk_ready):
    dialog = EditProfileDialog(make_profile())
    dialog.link_row.set_text("garbage")
    dialog.apply_link()
    assert dialog.name_row.get_text() == "Old"
    assert "разобрать" in dialog.status_label.get_text()


def test_a_pending_bean_is_not_written_before_saving(gtk_ready):
    """Диалог правит живой объект хранилища — Отмена должна ничего не менять."""
    profile = make_profile()
    dialog = EditProfileDialog(profile)
    dialog.link_row.set_text(OTHER)
    dialog.apply_link()
    assert profile.bean.server_address == "host.example"


def test_saving_applies_the_pending_bean(gtk_ready):
    profile = make_profile()
    dialog = EditProfileDialog(profile)
    dialog.link_row.set_text(OTHER)
    dialog.apply_link()
    dialog.apply_changes()
    assert profile.bean.server_address == "new.example"


def test_saving_applies_the_typed_fields(gtk_ready):
    profile = make_profile()
    dialog = EditProfileDialog(profile)
    dialog.name_row.set_text("Renamed")
    dialog.address_row.set_text("other.example")
    dialog.port_row.set_value(9443)
    dialog.apply_changes()
    assert profile.bean.name == "Renamed"
    assert profile.bean.server_address == "other.example"
    assert profile.bean.server_port == 9443


def test_an_empty_address_is_ignored_on_save(gtk_ready):
    """Пустой адрес сделал бы профиль неработоспособным без предупреждения."""
    profile = make_profile()
    dialog = EditProfileDialog(profile)
    dialog.address_row.set_text("")
    dialog.apply_changes()
    assert profile.bean.server_address == "host.example"
```

**Step 2: Запустить, убедиться в падении**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_dialogs_edit_profile.py -q -m gtk`
Expected: FAIL

**Step 3: Реализация**

`EditProfileDialog(Adw.Dialog)`: группа «Основное» — `Adw.EntryRow` имя, `Adw.EntryRow` адрес, `Adw.SpinRow` порт (1–65535). Группа «Строка подключения» — `Adw.EntryRow` со ссылкой, кнопки «Копировать» и «Применить», `Gtk.Label` статуса. Метод `apply_link()` разбирает ссылку через `validate_profile_link` и держит `_pending_bean` до `apply_changes()` (то же поведение, что и в GTK3 — см. комментарий в `src/ui/dialogs/edit_profile.py`). Копирование — `Gdk.Display.get_default().get_clipboard().set(text)`.

**Step 4: Тесты**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_dialogs_edit_profile.py -q -m gtk`
Expected: PASS (8)

**Step 5: Коммит**

```bash
git add src/ui/dialogs4/edit_profile.py tests/test_ui_dialogs_edit_profile.py
git commit -m "feat: add the GTK4 edit-profile dialog"
```

---

### Задача 3.6: Диалог настроек

**Files:**
- Create: `src/ui/dialogs4/settings.py`
- Test: `tests/test_ui_dialogs_settings.py` (маркер `gtk`)

**Step 1: Тест**

```python
import pytest

pytestmark = pytest.mark.gtk

from src.db.config import DataStore  # noqa: E402
from src.ui.dialogs4.settings import SettingsDialog  # noqa: E402


def make_config():
    config = DataStore()
    config.inbound_address = "127.0.0.1"
    config.inbound_socks_port = 2080
    config.proxy_mode = "system"
    config.log_level = "info"
    return config


def test_the_fields_are_loaded_from_the_config(gtk_ready):
    dialog = SettingsDialog(make_config())
    assert dialog.address_row.get_text() == "127.0.0.1"
    assert dialog.port_row.get_value() == 2080


def test_the_proxy_mode_is_preselected(gtk_ready):
    config = make_config()
    config.proxy_mode = "tun"
    dialog = SettingsDialog(config)
    assert dialog.mode_row.get_selected_item().get_string() != ""
    assert dialog.selected_mode() == "tun"


def test_an_unknown_mode_falls_back_to_the_first(gtk_ready):
    """Конфиг мог прийти от другой версии — диалог не должен падать."""
    config = make_config()
    config.proxy_mode = "nonsense"
    assert SettingsDialog(config).mode_row.get_selected() == 0


def test_tun_rows_are_insensitive_in_system_mode(gtk_ready):
    dialog = SettingsDialog(make_config())
    assert not dialog.tun_name_row.get_sensitive()


def test_switching_to_tun_enables_its_rows(gtk_ready):
    dialog = SettingsDialog(make_config())
    dialog.select_mode("tun")
    assert dialog.tun_name_row.get_sensitive()


def test_saving_writes_the_config_back(gtk_ready):
    config = make_config()
    dialog = SettingsDialog(config)
    dialog.address_row.set_text("0.0.0.0")
    dialog.port_row.set_value(3080)
    dialog.save()
    assert config.inbound_address == "0.0.0.0"
    assert config.inbound_socks_port == 3080


def test_saving_writes_the_selected_mode(gtk_ready):
    config = make_config()
    dialog = SettingsDialog(config)
    dialog.select_mode("tun")
    dialog.save()
    assert config.proxy_mode == "tun"


def test_the_monitoring_interval_round_trips(gtk_ready):
    config = make_config()
    dialog = SettingsDialog(config)
    dialog.monitoring_switch.set_active(True)
    dialog.interval_row.set_value(30)
    dialog.save()
    assert config.monitoring.enabled
    assert config.monitoring.check_interval_seconds == 30


def test_the_dns_provider_round_trips(gtk_ready):
    config = make_config()
    dialog = SettingsDialog(config)
    dialog.select_dns("cloudflare")
    dialog.save()
    assert config.dns.provider == "cloudflare"


def test_an_empty_tun_name_falls_back_to_the_default(gtk_ready):
    config = make_config()
    dialog = SettingsDialog(config)
    dialog.select_mode("tun")
    dialog.tun_name_row.set_text("")
    dialog.save()
    assert config.tun_name == "xray0"
```

**Step 2: Запустить, убедиться в падении**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_dialogs_settings.py -q -m gtk`
Expected: FAIL

**Step 3: Реализация**

`SettingsDialog(Adw.PreferencesDialog)`, страницы:
- **Общие** — группа «Входящее соединение» (`Adw.EntryRow` адрес, `Adw.SpinRow` порт 1024–65535), группа «Режим работы» (`Adw.ComboRow` из `ProxyMode.LABELS`, `Adw.EntryRow` имя TUN, `Adw.SpinRow` MTU 576–9000; последние две гаснут вне TUN).
- **Мониторинг** — `Adw.SwitchRow` включения, `Adw.SpinRow` интервала 5–60.
- **DNS** — `Adw.ComboRow` провайдера, `Adw.EntryRow` своего URL (чувствительна только для `custom`), `Adw.SwitchRow` «через прокси».
- **О программе** — `Adw.ActionRow` версии, путей конфигурации и логов, кнопка «Очистить логи».

Публичные методы для тестов: `selected_mode()`, `select_mode(key)`, `select_dns(key)`, `save()`. Соответствие индекса и ключа держится списком `self._mode_keys` — `Adw.ComboRow` работает индексами.

**Step 4: Тесты**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_dialogs_settings.py -q -m gtk`
Expected: PASS (10)

**Step 5: Коммит**

```bash
git add src/ui/dialogs4/settings.py tests/test_ui_dialogs_settings.py
git commit -m "feat: add the GTK4 settings dialog"
```

---

### Задача 3.7: Диалог VPN и маршрутизации профиля

**Files:**
- Create: `src/ui/dialogs4/profile_routing.py`
- Test: `tests/test_ui_dialogs_profile_routing.py` (маркер `gtk`)

**Step 1: Тест**

```python
import pytest

pytestmark = pytest.mark.gtk

from types import SimpleNamespace  # noqa: E402

from src.db.config import RoutingSettings, VpnSettings  # noqa: E402
from src.fmt import parse_link  # noqa: E402
from src.ui.dialogs4.profile_routing import ProfileRoutingDialog  # noqa: E402

LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#P"


def make_profile(**kwargs):
    return SimpleNamespace(
        id=1,
        bean=parse_link(LINK),
        vpn_settings=kwargs.get("vpn", VpnSettings()),
        routing_settings=kwargs.get("routing", RoutingSettings()),
    )


def test_vpn_fields_are_loaded(gtk_ready):
    vpn = VpnSettings(enabled=True, connection_name="work", auto_connect=True)
    dialog = ProfileRoutingDialog(make_profile(vpn=vpn))
    assert dialog.vpn_switch.get_active()
    assert dialog.vpn_name_row.get_text() == "work"
    assert dialog.vpn_auto_switch.get_active()


def test_vpn_rows_are_insensitive_while_disabled(gtk_ready):
    dialog = ProfileRoutingDialog(make_profile())
    assert not dialog.vpn_name_row.get_sensitive()


def test_enabling_vpn_wakes_its_rows(gtk_ready):
    dialog = ProfileRoutingDialog(make_profile())
    dialog.vpn_switch.set_active(True)
    assert dialog.vpn_name_row.get_sensitive()


def test_routing_lists_are_loaded(gtk_ready):
    routing = RoutingSettings(mode="custom", proxy_list=["a.com", "b.com"])
    dialog = ProfileRoutingDialog(make_profile(routing=routing))
    assert dialog.proxy_text() == "a.com\nb.com"


def test_the_routing_mode_is_preselected(gtk_ready):
    routing = RoutingSettings(mode="proxy_all")
    assert ProfileRoutingDialog(make_profile(routing=routing)).selected_mode() == "proxy_all"


def test_routing_lists_are_insensitive_in_proxy_all(gtk_ready):
    """В режиме «весь трафик» списки ни на что не влияют."""
    routing = RoutingSettings(mode="proxy_all")
    dialog = ProfileRoutingDialog(make_profile(routing=routing))
    assert not dialog.proxy_view.get_sensitive()


def test_saving_writes_the_vpn_settings(gtk_ready):
    profile = make_profile()
    dialog = ProfileRoutingDialog(profile)
    dialog.vpn_switch.set_active(True)
    dialog.vpn_name_row.set_text("work")
    dialog.save()
    assert profile.vpn_settings.enabled
    assert profile.vpn_settings.connection_name == "work"


def test_saving_parses_the_routing_lists(gtk_ready):
    profile = make_profile()
    dialog = ProfileRoutingDialog(profile)
    dialog.select_mode("custom")
    dialog.set_proxy_text("a.com\n\n b.com , a.com \n")
    dialog.save()
    assert profile.routing_settings.proxy_list == ["a.com", "b.com"]


def test_saving_writes_the_mode(gtk_ready):
    profile = make_profile()
    dialog = ProfileRoutingDialog(profile)
    dialog.select_mode("proxy_all")
    dialog.save()
    assert profile.routing_settings.mode == "proxy_all"


def test_the_bypass_switch_round_trips(gtk_ready):
    profile = make_profile()
    dialog = ProfileRoutingDialog(profile)
    dialog.bypass_switch.set_active(True)
    dialog.save()
    assert profile.routing_settings.bypass_local_networks
```

**Step 2: Запустить, убедиться в падении**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_dialogs_profile_routing.py -q -m gtk`
Expected: FAIL

**Step 3: Реализация**

`ProfileRoutingDialog(Adw.PreferencesDialog)`, две страницы:
- **VPN** — `Adw.SwitchRow` «Использовать VPN», `Adw.EntryRow` имя подключения NetworkManager, `Adw.SwitchRow` автоподключение, `Adw.EntryRow` интерфейса. Строки ниже переключателя гаснут, когда VPN выключен.
- **Маршрутизация** — `Adw.ComboRow` режима (`RoutingMode`), `Adw.SwitchRow` обхода локальных сетей, три `Gtk.TextView` в `Gtk.Frame` под заголовками PROXY / DIRECT / VPN, по домену или подсети на строку. В режиме `proxy_all` списки гаснут.

Списки читаются и пишутся через `parse_host_list` из задачи 3.2. Публичные методы: `selected_mode()`, `select_mode(key)`, `proxy_text()`, `set_proxy_text(text)`, `save()`. Список VPN-подключений системы **не запрашивается** — `nmcli` из тестов дёргать нельзя; имя вводится текстом, кнопка «Проверить» появится позже.

**Step 4: Тесты**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_dialogs_profile_routing.py -q -m gtk`
Expected: PASS (10)

**Step 5: Коммит**

```bash
git add src/ui/dialogs4/profile_routing.py tests/test_ui_dialogs_profile_routing.py
git commit -m "feat: add the GTK4 profile VPN and routing dialog"
```

---

### Задача 3.8: Контекстные меню строк

**Files:**
- Modify: `src/ui/pages/profiles.py`, `src/ui/pages/subscriptions.py`
- Test: `tests/test_ui_pages_profiles.py`, `tests/test_ui_pages_subscriptions.py`

**Step 1: Тесты (дописать к существующим файлам)**

```python
# tests/test_ui_pages_profiles.py — добавить
def test_a_right_click_emits_the_context_signal(gtk_ready):
    page = ProfilesPage()
    page.set_data(*sample_data())
    page.expand_all()
    seen = []
    page.connect("profile-context", lambda _p, pid, is_group: seen.append((pid, is_group)))
    page.emit_context_for_test(row_index=1)
    assert seen and seen[0][1] is False


def test_the_context_signal_reports_a_group(gtk_ready):
    page = ProfilesPage()
    page.set_data(*sample_data())
    seen = []
    page.connect("profile-context", lambda _p, pid, is_group: seen.append((pid, is_group)))
    page.emit_context_for_test(row_index=0)
    assert seen[0][1] is True


def test_the_context_menu_selects_the_row_it_was_opened_on(gtk_ready):
    """Действие меню работает с выделением — щелчок должен его перенести."""
    page = ProfilesPage()
    page.set_data(*sample_data())
    page.expand_all()
    page.emit_context_for_test(row_index=2)
    assert page.get_selected_index() == 2
```

```python
# tests/test_ui_pages_subscriptions.py — добавить
def test_a_subscription_row_carries_a_menu_button(gtk_ready):
    page = SubscriptionsPage()
    page.set_data(*sample_data())
    assert page.get_menu_button(0) is not None


def test_the_menu_targets_the_row_group(gtk_ready):
    page = SubscriptionsPage()
    page.set_data(*sample_data())
    assert page.get_row_group_id(0) > 0
```

**Step 2: Запустить, убедиться в падении**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_pages_profiles.py tests/test_ui_pages_subscriptions.py -q -m gtk`
Expected: FAIL — методов нет

**Step 3: Реализация**

В `ProfilesPage`: `Gtk.GestureClick(button=3)` и `Gtk.GestureLongPress` на `Gtk.ColumnView`; по нажатию — определить строку через `Gtk.ColumnView.get_...`/сравнение координат, перенести выделение, эмитировать `profile-context(int, bool)` (сигнатура сигнала меняется — добавляется признак группы) и показать `Gtk.PopoverMenu` из `Gio.Menu`, собранного под тип строки. Пункты ссылаются на действия `win.*`, которые регистрирует окно (задача 3.9). Метод `emit_context_for_test(row_index)` — тонкая обёртка над той же внутренней функцией, чтобы тест не имитировал события мыши.

В `SubscriptionsPage`: у каждой `Adw.ActionRow` рядом с кнопкой обновления — `Gtk.MenuButton` с меню «Обновить · Редактировать · Удалить»; методы `get_menu_button(index)` и `get_row_group_id(index)` для тестов.

**Step 4: Тесты**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_pages_profiles.py tests/test_ui_pages_subscriptions.py -q -m gtk`
Expected: PASS

**Step 5: Коммит**

```bash
git add src/ui/pages/profiles.py src/ui/pages/subscriptions.py tests/test_ui_pages_profiles.py tests/test_ui_pages_subscriptions.py
git commit -m "feat: add context menus to the profile and subscription rows"
```

---

### Задача 3.9: Подключение диалогов и действий к приложению

**Files:**
- Modify: `src/ui/application.py`, `src/ui/window.py`
- Test: `tests/test_ui_application.py`, `tests/test_ui_window.py`

**Step 1: Тесты (дописать)**

```python
# tests/test_ui_application.py — добавить
def test_toggle_connection_connects_through_the_service(gtk_ready, app_with_context):
    app, context = app_with_context
    calls = []
    app.set_connection_service(FakeService(calls))
    app.select_profile(1)
    app.wait_for_connection_for_test()
    assert calls == [("connect", 1)]


def test_toggle_connection_disconnects_a_running_proxy(gtk_ready, app_with_context):
    app, context = app_with_context
    context.proxy_state.is_running = True
    calls = []
    app.set_connection_service(FakeService(calls))
    app.activate_action("toggle-connection", None)
    app.wait_for_connection_for_test()
    assert calls == [("disconnect",)]


def test_a_failed_connection_is_reported(gtk_ready, app_with_context):
    app, _ = app_with_context
    app.set_connection_service(FakeService([], ok=False, error="нет бинарника"))
    app.select_profile(1)
    app.wait_for_connection_for_test()
    assert "нет бинарника" in app.last_toast_for_test


def test_a_second_connect_while_one_runs_is_refused(gtk_ready, app_with_context):
    """Два запуска xray подряд оставили бы висящий процесс."""
    app, _ = app_with_context
    app.set_connection_service(SlowService())
    app.select_profile(1)
    app.select_profile(2)
    app.wait_for_connection_for_test()
    assert "уже" in app.last_toast_for_test


def test_add_profile_stores_and_saves(gtk_ready, app_with_context):
    app, context = app_with_context
    before = len(context.profiles.profiles)
    app.add_profile_from_bean(parse_link(LINK))
    assert len(context.profiles.profiles) == before + 1


def test_delete_profile_removes_it(gtk_ready, app_with_context):
    app, context = app_with_context
    profile_id = next(iter(context.profiles.profiles))
    app.delete_profile(profile_id, confirmed=True)
    assert profile_id not in context.profiles.profiles


def test_delete_profile_does_nothing_without_confirmation(gtk_ready, app_with_context):
    app, context = app_with_context
    profile_id = next(iter(context.profiles.profiles))
    app.delete_profile(profile_id, confirmed=False)
    assert profile_id in context.profiles.profiles


def test_add_subscription_creates_a_group(gtk_ready, app_with_context):
    app, context = app_with_context
    group = app.add_subscription("Sub", "https://example.com/s")
    assert group.is_subscription
    assert context.profiles.get_group(group.id) is not None
```

```python
# tests/test_ui_window.py — добавить
def test_the_window_registers_the_row_actions(gtk_ready, window):
    for name in ("edit-profile", "delete-profile", "profile-routing", "edit-group"):
        assert window.has_action(name)


def test_connecting_shows_the_intermediate_state(gtk_ready, window):
    window.show_connecting("P")
    assert "P" in window.status_card.title_label.get_text()
```

**Step 2: Запустить, убедиться в падении**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_application.py tests/test_ui_window.py -q -m gtk`
Expected: FAIL

**Step 3: Реализация**

В `TengaApplication`:
- `set_connection_service(service)` и ленивое создание `ConnectionService(self.context)` по умолчанию — по образцу `set_latency_probe`.
- `select_profile(profile_id)` теперь подключает: показывает промежуточное состояние карточки, запускает `run_in_background(service.connect)`, по завершении обновляет карточку и страницы. Повторный запуск при живом потоке отклоняется тостом.
- `toggle-connection`: если `proxy_state.is_running` — `disconnect`, иначе — подключение к выделенному профилю (`window.profiles_page.get_selected_profile_id()`), а при отсутствии выделения — тост.
- `connect` / `disconnect` — отдельные действия поверх той же машинерии.
- `add-profile`, `add-profile-from-clipboard`, `add-subscription`, `add-group`, `settings`, `about`, `shortcuts` открывают соответствующие диалоги; после сохранения — `context.save_profiles()` / `save_config()` и `window.refresh_pages()`.
- `settings` при активном соединении вызывает `service.reload_config()` (уточнение 12).
- Вспомогательные методы, вызываемые и из диалогов, и из тестов: `add_profile_from_bean(bean, group_id=None)`, `delete_profile(profile_id, confirmed)`, `add_subscription(name, url)`, `update_group(group_id, name, url)`, `delete_group(group_id, confirmed)`.
- `wait_for_connection_for_test()` и `last_toast_for_test` — по образцу существующих тестовых хвостов.

В `MainWindow`: регистрация `Gio.SimpleAction` уровня окна — `edit-profile`, `delete-profile`, `profile-routing`, `test-latency-one`, `edit-group`, `delete-group`, `expand-group`, `edit-subscription`, `delete-subscription`, `update-subscription`. Они принимают `Gio.VariantType("i")` (идентификатор строки) и обращаются к приложению. `about` — `Adw.AboutDialog`; `shortcuts` — `Gtk.ShortcutsWindow` со всеми ускорителями из `_ACCELS`.

**Step 4: Тесты**

Run: `GDK_BACKEND=x11 uv run pytest tests/test_ui_application.py tests/test_ui_window.py -q -m gtk`
Expected: PASS

**Step 5: Коммит**

```bash
git add src/ui/application.py src/ui/window.py tests/test_ui_application.py tests/test_ui_window.py
git commit -m "feat: wire the dialogs and connection actions into the application"
```

---

### Задача 3.10: GTK3-приложение через тот же сервис

**Files:**
- Modify: `src/ui/app.py`
- Test: `tests/test_ui_app.py` (если существует) либо ручная проверка импорта

**Step 1: Проверить, что тесты GTK3 сейчас зелёные**

Run: `uv run pytest -q`
Expected: PASS — фиксируем базу до изменения

**Step 2: Заменить тело `_connect` / `_disconnect` / `_reload_config`**

Методы становятся тонкими обёртками над `ConnectionService`: вызывают сервис, а трей-уведомления показывают по `ConnectionResult`. Логика дублироваться не должна — иначе две реализации разойдутся к этапу 5.

**Step 3: Тесты**

Run: `uv run pytest -q`
Expected: столько же пройденных, сколько на шаге 1

**Step 4: Коммит**

```bash
git add src/ui/app.py
git commit -m "refactor: route the GTK3 application through the connection service"
```

---

### Задача 3.11: Живая проверка и документирование

**Files:**
- Modify: `docs/plans/2026-09-02-ui-phase3-dialogs.md` (раздел «Результаты»)

**Step 1: Полный прогон**

Run: `uv run pytest -q` и `make test-gtk`
Expected: обе команды зелёные

**Step 2: Линтер**

Run: `python cli.py lint` и `python cli.py format --check`
Expected: без замечаний

**Step 3: Живая проверка на копии реального конфига**

Запустить GTK4-приложение на копии конфига пользователя в песочнице с **фиктивным** `ConnectionService` (реальные подключения запрещены — рабочее приложение не трогаем). Проверить: открытие каждого диалога, контекстные меню профиля/группы/подписки, добавление профиля из ссылки, редактирование, удаление с подтверждением, сохранение настроек, диалог VPN и маршрутов. Снять скриншоты.

**Step 4: Записать результаты**

Дописать в этот документ раздел «Результаты»: список коммитов, отклонения от плана с обоснованием, найденные дефекты, метрики тестов, раздел «Не сделано».

**Step 5: Коммит**

```bash
git add docs/plans/2026-09-02-ui-phase3-dialogs.md
git commit -m "docs: record the phase 3 results"
```

---

## Ограничения этапа

- **Рабочее приложение пользователя запущено.** Никаких настоящих подключений, отключений и правки `~/.config/tenga-proxy/`. Проверка идёт на копии конфига в песочнице и с фиктивным сервисом подключения.
- **Реальный конфиг не коммитится** — 600 профилей с личными ссылками подписки остаются в песочнице.
- **GTK3-код не удаляется** — новые диалоги живут в `src/ui/dialogs4/`, старые продолжают обслуживать `app.py` до этапа 5. Пакет переименуется в `dialogs/` при удалении GTK3.
- **Трей не трогаем** — это этап 4.

---

## Результаты

Этап выполнен целиком. 12 коммитов поверх этапа 2, все задачи 3.1–3.11 закрыты.

### Коммиты

| Коммит | Что сделано |
|---|---|
| `877a338` | План этапа |
| `6ff89e5` | `ConnectionService` — подключение без GTK |
| `036426b` | Валидация форм (`src/ui/logic/forms.py`) |
| `fa113e0` | Диалог добавления профиля |
| `284739f` | Диалоги подписки, группы, подтверждения |
| `6e8e31d` | Диалог редактирования профиля |
| `dbf0329` | Диалог настроек |
| `2814db7` | Диалог VPN и маршрутизации |
| `c27338b` | Контекстные меню строк |
| `61fc6bc` | Подключение диалогов и действий к приложению |
| `4db8d74` | GTK3-приложение переведено на общий сервис |
| `3371e0e` | Четыре правки оформления по снимкам |

### Отклонения от плана

1. **`ProxyMode.SYSTEM_PROXY` — это `"system_proxy"`, не `"system"`.** План опирался на догадку; тесты сервиса исправлены на фактическое значение.

2. **Провайдер DNS `custom` не существует.** В GTK3 «свой адрес» — не пункт списка, а отдельное поле, перекрывающее выбранного провайдера, если оно непустое. Тест переписан под фактическую модель, поле активно всегда.

3. **Диалог VPN и маршрутов получил две страницы вместо трёх.** Отдельная страница «Профиль» с двумя строками не оправдывала вкладки — на снимке она выглядела пустой. Группа перенесена в начало страницы VPN.

4. **В диалог маршрутов добавлены поля, которых не было в плане:** приоритет групп правил (`rule_order`, шесть пресетов) и имена интерфейсов VPN и прямого выхода. Они есть в GTK3-версии и влияют на маршрутизацию — потерять их значило бы сломать существующие профили.

5. **Список VPN-подключений системы не запрашивается.** GTK3 при сохранении дёргает `list_vpn_connections()` и отказывает, если имени нет в NetworkManager. Новый диалог принимает имя текстом: `nmcli` из тестов вызывать нельзя, а проверка при подключении всё равно происходит в сервисе.

6. **`_new_row_store` был определён в `profiles.py` дважды** — второе определение (с локальным импортом `Gio`) перекрывало первое. Дубликат удалён.

7. **Тестовые ожидания порядка строк были неверны.** Группы сортируются по имени, поэтому «Подписка» идёт раньше «Работы», а позиция 1 после раскрытия — ребёнок первой группы. Ожидания исправлены на фактический порядок с пояснением в тесте.

8. **`window.activate_action()` асинхронен** и в тесте не срабатывает даже после прокрутки `MainContext`. Тест вызывает `lookup_action(...).activate(...)` напрямую.

9. **Версия вынесена в `src/ui/logic/version.py`.** Она нужна и настройкам, и окну «О программе»; две копии одной обработки ошибок разъехались бы.

### Дефекты, найденные на живой проверке

Проверка шла на копии реального конфига (130 профилей, 3 группы) с фиктивным сервисом подключения. Ни одного настоящего подключения не выполнялось.

1. **Segfault при открытии контекстного меню вне окна.** `Gtk.PopoverMenu.popup()` на неотрисованном виджете роняет GTK — тест страницы падал целиком, а не с ошибкой. Показ теперь пропускается, если `column_view` не реализован; выбор строки и сигнал происходят в любом случае.

2. **Подсказка под полем ссылки стояла вне карточки** — читалась как подпись ко всей странице, а не к введённой ссылке. Перенесена в `Adw.ActionRow` внутри группы, скрыта при пустом поле.

3. **Диалоги были на 200–400 px выше содержимого.** Форма из двух полей занимала пол-экрана пустотой. Включён `follows-content-size`.

4. **`follows-content-size` сжимает и ширину.** После пункта 3 «Добавить подписку» в справке рассыпалось по одной букве в строке, а диалог добавления сузился до 395 px. Ширина задана через `size_request` содержимого — `content-width` в этом режиме игнорируется.

### Проверено на живых данных

- 130 профилей, 132 строки в дереве после раскрытия
- Меню группы: Свернуть · Тест задержки · Редактировать · Удалить
- Меню профиля: Подключить · VPN и маршруты… · Тест задержки · Редактировать · Удалить
- Меню подписки: Обновить · Редактировать · Удалить
- 11 действий уровня окна зарегистрированы и принимают целый параметр
- Подключение идёт через сервис: `[('connect', 8671)]`, тост «Подключено: 🇩🇪 Германия (XHTTP)»
- Отложенное применение ссылки: адрес профиля не меняется до подтверждения
- Настройки читают реальный конфиг (TUN, `xray0`, MTU 1450)
- Диалог маршрутов читает реальные настройки профиля (VPN включён, `aiso-new`, автоподключение)
- Снимки в светлой и тёмной теме

### Метрики

| | До этапа | После |
|---|---|---|
| Тесты без дисплея | 333 | 375 |
| Тесты GTK4 | 67 | 96 |
| Строк изменено | — | +3636 / −231 в 30 файлах |
| `_connect` + `_disconnect` в `app.py` | ~200 строк | 24 строки |

### Не сделано

- **Трей** — этап 4 (собственный StatusNotifierItem поверх D-Bus).
- **Удаление GTK3-кода** и переименование `dialogs4` → `dialogs` — этап 5.
- **Проверка имени VPN-подключения через NetworkManager** при сохранении — в GTK3 она есть, здесь отложена, чтобы диалог не ходил в систему (см. отклонение 5).
- **Кнопка замера времени отклика до youtube.com** из `TASK/TASK.md` — отдельная задача, не входит в редизайн.
- **Настоящее подключение не проверялось** — запрет пользователя: рабочее приложение запущено. Проверены только вызовы сервиса на фиктивной реализации и 20 unit-тестов сервиса с моками.
