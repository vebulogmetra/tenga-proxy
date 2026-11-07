# Общая маршрутизация — план реализации

> **Для исполнителя:** использовать навык `superpowers:executing-plans`, выполнять задачи последовательно, TDD: сначала падающий тест.

**Цель:** общая маршрутизация редактируется на новой странице настроек «Маршрутизация» (GTK и Qt), у сервера есть переключатель «Свои правила маршрутизации», набор маршрутов из заголовка `routing` подписки предлагается с подтверждением.

**Архитектура:** `DataStore.routing` — общие правила, `ProfileEntry.routing_settings is None` — «сервер использует общие». Форма маршрутизации выносится в общий виджет в каждом тулките (`src/ui/widgets/routing_form.py`, `src/ui/qt/widgets/routing_form.py`), преобразования — в `src/ui/logic/routing_form.py` без тулкита. Заголовок подписки читает `src/sub/metadata.py`, разбирает `src/fmt/app_links.py`, предлагает `AppController` той же очередью, что смену адреса. Дизайн: `docs/plans/2026-11-07-global-routing-design.md`.

**Стек:** Python 3.11+, GTK 4 + libadwaita 1.5, PySide6, pytest, ruff.

**База:** `53d44cc` (0.27.0), 07.11.2026.

**Команды проверки:** `uv run pytest <файлы> -q` для логики, `make test-gtk`, `make test-qt`, `python cli.py lint-all` перед каждым коммитом. Сообщения коммитов — короткие, императивные, одной строкой, без trailer'ов (`~/.claude/CLAUDE.md`).

**Что уже есть и не переписывается:** `RoutingSettings`, `config_builder` (выбор серверных или общих правил), `effective_routing`/`apply_import`/`restore_backup` в `src/ui/logic/routing_import.py`, очередь `_url_proposals` в контроллере, окна `RoutingImportDialog` в обоих тулкитах, `runtime_snapshot`.

---

## Этап 1. Логика без тулкита

### Задача 1: значения формы ↔ `RoutingSettings`

**Файлы:**
- Изменить: `src/ui/logic/routing_form.py`
- Тест: `tests/test_ui_logic_routing_form.py`

**Шаг 1: падающий тест**

Добавить в конец `tests/test_ui_logic_routing_form.py`:

```python
# --- значения формы -----------------------------------------------------------


def test_form_values_round_trip_through_routing_settings():
    from src.db.config import RoutingMode, RoutingSettings
    from src.ui.logic.routing_form import FormValues, apply_form_values, form_values

    routing = RoutingSettings(
        mode=RoutingMode.CUSTOM,
        rule_order=["vpn", "proxy", "direct"],
        bypass_local_networks=False,
        ru_direct=True,
        block_list=["ads.example"],
        proxy_list=["a.com", "b.com"],
        direct_list=["d.com"],
        vpn_list=["v.com"],
    )

    values = form_values(routing)

    assert values == FormValues(
        mode="custom",
        order="vpn_proxy_direct",
        bypass_local_networks=False,
        ru_direct=True,
        lists={
            "block": "ads.example",
            "proxy": "a.com\nb.com",
            "direct": "d.com",
            "vpn": "v.com",
        },
    )
    target = RoutingSettings()
    apply_form_values(target, values)
    assert target.to_dict() == routing.to_dict()


def test_apply_form_values_parses_lists_and_rejects_bad_entries():
    from src.db.config import RoutingSettings
    from src.ui.logic.routing_form import FormValues, apply_form_values

    target = RoutingSettings(direct_list=["keep.example"])
    values = FormValues(
        mode="custom",
        order="direct_vpn_proxy",
        bypass_local_networks=True,
        ru_direct=False,
        lists={"block": "", "proxy": "a.com\n\n b.com , a.com \n", "direct": "", "vpn": ""},
    )
    apply_form_values(target, values)
    assert target.proxy_list == ["a.com", "b.com"]
    assert target.direct_list == []

    bad = FormValues(
        mode="custom",
        order="direct_vpn_proxy",
        bypass_local_networks=True,
        ru_direct=False,
        lists={"block": "", "proxy": "", "direct": "http://user:pw@x.com", "vpn": ""},
    )
    with pytest.raises(ValueError, match="credentials"):
        apply_form_values(target, bad)
    # Ошибка — ничего не изменилось.
    assert target.proxy_list == ["a.com", "b.com"]


def test_form_values_of_an_unknown_order_fall_back_to_the_first_preset():
    from src.db.config import RoutingSettings
    from src.ui.logic.routing_form import form_values

    assert form_values(RoutingSettings(rule_order=["nonsense"])).order == "direct_vpn_proxy"
```

**Шаг 2: убедиться, что падает**

Run: `uv run pytest tests/test_ui_logic_routing_form.py -q`
Expected: FAIL, `ImportError: cannot import name 'FormValues'`

**Шаг 3: реализация**

Добавить в `src/ui/logic/routing_form.py` после `order_key`:

```python
# Ключ списка → заголовок и подсказка; порядок — порядок на экране.
LISTS: tuple[tuple[str, str, str], ...] = (
    ("block", "Блокировать", BLOCK_HINT),
    ("proxy", "Через прокси", LIST_HINT),
    ("direct", "Напрямую", LIST_HINT),
    ("vpn", "Через VPN", LIST_HINT),
)

OWN_RULES_TITLE = "Свои правила маршрутизации"
OWN_RULES_HINT = "Выключено: действуют общие правила из настроек приложения"
GLOBAL_PAGE_HINT = "Действует для серверов без своих правил"
VPN_LIST_HINT = LIST_HINT + ". Действует только для серверов с включённым VPN"


@dataclass(frozen=True)
class FormValues:
    """Поля формы маршрутизации: то, что виджет показывает и читает."""

    mode: str
    order: str  # ключ ORDER_PRESETS
    bypass_local_networks: bool
    ru_direct: bool
    lists: dict[str, str]  # ключ LISTS → текст, одна запись в строке


def form_values(routing) -> FormValues:
    """Значения формы для настроек; незнакомый порядок — первый пресет."""
    try:
        order = routing.get_rule_order()
    except AttributeError:
        order = []
    return FormValues(
        mode=routing.mode,
        order=order_key(order),
        bypass_local_networks=routing.bypass_local_networks,
        ru_direct=getattr(routing, "ru_direct", False),
        lists={
            key: "\n".join(getattr(routing, f"{key}_list", None) or []) for key, _t, _h in LISTS
        },
    )


def apply_form_values(routing, values: FormValues) -> None:
    """Записать форму в настройки; негодная запись — ValueError, настройки не тронуты."""
    from src.ui.logic.forms import parse_host_list

    parsed = {key: parse_host_list(values.lists.get(key, "")) for key, _t, _h in LISTS}
    routing.mode = values.mode
    routing.rule_order = list(ORDER_PRESETS[values.order])
    routing.bypass_local_networks = values.bypass_local_networks
    routing.ru_direct = values.ru_direct
    for key, entries in parsed.items():
        setattr(routing, f"{key}_list", entries)
```

В начало модуля добавить `from dataclasses import dataclass`. Подсказку `BLOCK_HINT`/`LIST_HINT` и `ORDER_PRESETS` модуль уже содержит.

**Шаг 4: тесты проходят**

Run: `uv run pytest tests/test_ui_logic_routing_form.py -q`
Expected: PASS

**Шаг 5: коммит**

```bash
git add src/ui/logic/routing_form.py tests/test_ui_logic_routing_form.py
git commit -m "ui: значения формы маршрутизации без тулкита"
```

### Задача 2: строка «Правила» в мониторинге

**Файлы:**
- Изменить: `src/ui/logic/monitoring_view.py:50-100`, `src/ui/window.py:522-535`, `src/ui/qt/window.py:566-580`
- Тест: `tests/test_ui_logic_monitoring_view.py`

**Шаг 1: падающий тест**

Добавить в `tests/test_ui_logic_monitoring_view.py`:

```python
def test_routing_rows_name_whose_rules_apply():
    assert values(routing_rows(FakeRouting(), own_rules=False))["Правила"] == "Общие"
    assert values(routing_rows(FakeRouting(), own_rules=True))["Правила"] == "Сервера"
    assert values(routing_rows(FakeRouting(mode="proxy_all"), own_rules=True))["Правила"] == (
        "Сервера"
    )


def test_monitoring_view_passes_own_rules_through():
    view = monitoring_view(
        FakeStatus(proxy_ok=True), FakeRouting(), is_running=True, own_rules=True
    )
    assert values(view.routing)["Правила"] == "Сервера"
    blank = monitoring_view(FakeStatus(), FakeRouting(), is_running=False, own_rules=True)
    assert values(blank.routing)["Правила"] == UNKNOWN
```

**Шаг 2: убедиться, что падает**

Run: `uv run pytest tests/test_ui_logic_monitoring_view.py -q`
Expected: FAIL, `TypeError: ... unexpected keyword argument 'own_rules'`

**Шаг 3: реализация**

В `src/ui/logic/monitoring_view.py`:

```python
RULES_GLOBAL = "Общие"
RULES_OWN = "Сервера"


def _rules_row(own_rules: bool) -> MonitoringRow:
    return MonitoringRow("Правила", RULES_OWN if own_rules else RULES_GLOBAL)


def _blank_routing() -> tuple[MonitoringRow, ...]:
    return tuple(
        MonitoringRow(title=title, value=UNKNOWN, css_class=CLASS_DIM)
        for title in ("Правила", "Режим", "DIRECT", "PROXY", "VPN")
    )


def routing_rows(
    routing: Any,
    *,
    own_rules: bool = False,
    vpn_enabled: bool = False,
    vpn_is_up: bool = False,
) -> tuple[MonitoringRow, ...]:
    """Describe the routing rules of the active profile."""
    rules = _rules_row(own_rules)
    if routing.mode == _PROXY_ALL:
        direct = "активен (bypass local)" if routing.bypass_local_networks else NOT_SET
        return (
            rules,
            MonitoringRow("Режим", "PROXY_ALL"),
            ...  # как раньше
        )
    ...
    return (
        rules,
        MonitoringRow("Режим", "CUSTOM"),
        ...  # как раньше
    )
```

В `monitoring_view` добавить параметр `own_rules: bool = False`, передать в `routing_rows`, а в ветке «сервер не найден» первым элементом поставить `MonitoringRow("Правила", UNKNOWN, CLASS_DIM)`.

В `src/ui/window.py` и `src/ui/qt/window.py` рядом с `routing = getattr(profile, "routing_settings", None) or self._context.config.routing`:

```python
own_rules = getattr(profile, "routing_settings", None) is not None
```

и передать `own_rules=own_rules` в `monitoring_view(...)`.

**Шаг 4: тесты проходят**

Run: `uv run pytest tests/test_ui_logic_monitoring_view.py -q`
Expected: PASS. Затем `make test-gtk ARGS="-k monitoring"` и `make test-qt` — страницы мониторинга рисуют на одну строку больше, существующие проверки заголовков могут требовать правки (искать `"Режим"` в `tests/test_ui_pages_monitoring*.py`, `tests/test_ui_qt_window*.py`).

**Шаг 5: коммит**

```bash
git add src/ui/logic/monitoring_view.py src/ui/window.py src/ui/qt/window.py tests/
git commit -m "ui: строка «Правила» на странице мониторинга"
```

### Задача 3: снимок настроек замечает общие правила только без своих

**Файлы:**
- Тест: `tests/test_ui_logic_settings_state.py`

Поведение уже реализовано (`_RUNTIME_KEYS` содержит `routing`, снимок включает `profile.routing_settings`); задача закрепляет его тестом, потому что на него опирается баннер «переподключитесь».

**Шаг 1: тест**

```python
def test_global_routing_change_is_noticed_only_without_own_rules():
    from src.db.config import RoutingSettings

    config = DataStore()
    shared = ProfileEntry(id=1, group_id=1, bean=VLESSBean())
    own = ProfileEntry(id=2, group_id=1, bean=VLESSBean(), routing_settings=RoutingSettings())
    before_shared = runtime_snapshot(config, shared, geo_paths=[])
    before_own = runtime_snapshot(config, own, geo_paths=[])

    config.routing.proxy_list = ["a.com"]
    config.routing.use_saved_lists = True

    assert runtime_snapshot(config, shared, geo_paths=[]) != before_shared
    # Снимок меняется и у сервера со своими правилами: ключ `routing` общий.
    # Это известное огрубление; баннер лишний раз попросит переподключиться.
    assert runtime_snapshot(config, own, geo_paths=[]) != before_own
```

**Шаг 2: прогнать**

Run: `uv run pytest tests/test_ui_logic_settings_state.py -q`
Expected: PASS (если второй `assert` падает, значит снимок точнее, чем ожидалось — поменять на `==` и оставить комментарий).

**Шаг 3: коммит**

```bash
git add tests/test_ui_logic_settings_state.py
git commit -m "test: снимок настроек и общая маршрутизация"
```

### Задача 4: конфиг сессии — свои пустые списки не падают в общие

**Файлы:**
- Тест: `tests/test_core_routing_rules.py`

**Шаг 1: тест**

```python
def test_own_rules_replace_the_shared_ones_even_when_empty(context, profile):
    """Пустые свои списки — тоже свои: общие при этом не действуют."""
    use_custom_lists(context, proxy=["shared.example"])
    profile.routing_settings = RoutingSettings(mode=RoutingMode.CUSTOM)

    config = build_session_config(context, profile)

    assert "domain:shared.example" not in rule_values(config, "proxy", "domain")


def test_shared_rules_apply_without_own_rules(context, profile):
    use_custom_lists(context, proxy=["shared.example"])
    profile.routing_settings = None

    config = build_session_config(context, profile)

    assert "domain:shared.example" in rule_values(config, "proxy", "domain")
```

**Шаг 2: прогнать**

Run: `uv run pytest tests/test_core_routing_rules.py -q -k "own_rules or shared_rules"`
Expected: PASS (поведение уже есть). Если `rule_values` для домена даёт другой префикс, посмотреть соседние тесты файла и взять их форму.

**Шаг 3: коммит**

```bash
git add tests/test_core_routing_rules.py
git commit -m "test: выбор общих и серверных правил в конфиге сессии"
```

### Задача 5: сохранение общих правил из настроек

**Файлы:**
- Изменить: `src/ui/logic/routing_import.py`
- Тест: `tests/test_ui_logic_routing_import.py`

Общая точка для обоих тулкитов: прочитать действующие общие правила в форму и записать их обратно с `use_saved_lists`.

**Шаг 1: падающий тест**

```python
def test_store_shared_routing_switches_to_saved_lists(tmp_path):
    from src.ui.logic.routing_import import store_shared_routing

    config = _legacy(tmp_path)
    edited = effective_routing(config.routing, tmp_path)
    edited.proxy_list = ["new.example"]

    store_shared_routing(config, edited)

    assert config.routing.use_saved_lists is True
    assert config.routing.proxy_list == ["new.example"]
    # Списки из файлов, которых форма не касалась, не теряются.
    assert config.routing.direct_list == ["old.example"]
    assert config.routing_backup is None
```

**Шаг 2: убедиться, что падает**

Run: `uv run pytest tests/test_ui_logic_routing_import.py -q -k store_shared`
Expected: FAIL, `ImportError`

**Шаг 3: реализация**

В `src/ui/logic/routing_import.py`:

```python
def store_shared_routing(config, routing: RoutingSettings) -> None:
    """Записать общие правила из формы настроек.

    Форма заполняется через `effective_routing`, поэтому списки из текстовых
    файлов старой установки уже внутри. После записи файлы не читаются.
    """
    routing = copy.deepcopy(routing)
    routing.use_saved_lists = True
    config.routing = routing
```

**Шаг 4: тесты проходят**

Run: `uv run pytest tests/test_ui_logic_routing_import.py -q`
Expected: PASS

**Шаг 5: коммит**

```bash
git add src/ui/logic/routing_import.py tests/test_ui_logic_routing_import.py
git commit -m "ui: запись общих правил из настроек"
```

---

## Этап 2. GTK

### Задача 6: общий виджет формы (GTK)

**Файлы:**
- Создать: `src/ui/widgets/routing_form.py`
- Тест: `tests/test_ui_widgets_routing_form.py` (маркер `gtk`)

**Шаг 1: падающий тест**

```python
"""Общий виджет формы маршрутизации (GTK4)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gtk


def make_form():
    from gi.repository import Adw

    from src.ui.widgets.routing_form import RoutingForm

    page = Adw.PreferencesPage()
    return RoutingForm(page)


def routing_settings(**kwargs):
    from src.db.config import RoutingSettings

    return RoutingSettings(**kwargs)


def test_load_and_read_round_trip(gtk_ready):
    form = make_form()
    source = routing_settings(
        mode="custom", proxy_list=["a.com"], rule_order=["vpn", "proxy", "direct"], ru_direct=True
    )
    form.load(source)
    target = routing_settings()
    form.read(target)
    assert target.to_dict() == source.to_dict()


def test_lists_sleep_in_proxy_all_and_wake_in_custom(gtk_ready):
    form = make_form()
    form.load(routing_settings(mode="proxy_all"))
    assert not form.views["proxy"].get_sensitive()
    assert form.bypass_row.get_sensitive()
    form.select_mode("custom")
    assert form.views["proxy"].get_sensitive()


def test_set_enabled_dims_everything(gtk_ready):
    form = make_form()
    form.load(routing_settings(mode="custom"))
    form.set_enabled(False)
    assert not form.mode_row.get_sensitive()
    assert not form.views["proxy"].get_sensitive()
    form.set_enabled(True)
    assert form.mode_row.get_sensitive()
    assert form.views["proxy"].get_sensitive()


def test_bad_entry_raises_and_keeps_the_target(gtk_ready):
    form = make_form()
    form.load(routing_settings(mode="custom", direct_list=["x.com"]))
    form.set_text("direct", "http://user:pw@x.com")
    target = routing_settings(direct_list=["x.com"])
    with pytest.raises(ValueError):
        form.read(target)
    assert target.direct_list == ["x.com"]


def test_changed_callback_fires_on_edits(gtk_ready):
    form = make_form()
    form.load(routing_settings(mode="custom"))
    seen = []
    form.connect_changed(lambda: seen.append(1))
    form.set_text("proxy", "a.com")
    form.bypass_row.set_active(not form.bypass_row.get_active())
    assert len(seen) >= 2
```

**Шаг 2: убедиться, что падает**

Run: `make test-gtk ARGS="tests/test_ui_widgets_routing_form.py"`
Expected: FAIL, `ModuleNotFoundError: src.ui.widgets.routing_form`

**Шаг 3: реализация**

`src/ui/widgets/routing_form.py`:

```python
"""Форма маршрутизации: режим, порядок, готовые правила, четыре списка.

Одна и та же форма — в настройках приложения (общие правила) и в диалоге
сервера (свои правила). Значения ходят через `src/ui/logic/routing_form.py`.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk

from src.db.config import RoutingMode
from src.ui.dialogs.settings import KeyedCombo
from src.ui.logic.routing_form import (
    LISTS,
    ORDER_LABELS,
    ORDER_PRESETS,
    VPN_LIST_HINT,
    FormValues,
    apply_form_values,
    current_catalog,
    form_values,
    ru_direct_subtitle,
)


def _list_view(title: str, subtitle: str) -> tuple[Adw.PreferencesGroup, Gtk.TextView]:
    group = Adw.PreferencesGroup(title=title, description=subtitle)
    view = Gtk.TextView()
    view.set_monospace(True)
    for setter in (view.set_top_margin, view.set_bottom_margin, view.set_left_margin, view.set_right_margin):
        setter(8)
    scrolled = Gtk.ScrolledWindow(min_content_height=120)
    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scrolled.set_child(view)
    scrolled.add_css_class("card")
    group.add(scrolled)
    return group, view


def _read(view: Gtk.TextView) -> str:
    buffer = view.get_buffer()
    start, end = buffer.get_bounds()
    return buffer.get_text(start, end, True)


class RoutingForm:
    """Группы формы, добавленные на `Adw.PreferencesPage`."""

    def __init__(self, page: Adw.PreferencesPage, *, vpn_hint: str | None = None) -> None:
        self.groups: list[Adw.PreferencesGroup] = []
        mode_group = Adw.PreferencesGroup(title="Режим")
        page.add(mode_group)
        self.groups.append(mode_group)

        self._mode = KeyedCombo("Правила", RoutingMode.ALL, RoutingMode.LABELS)
        self.mode_row = self._mode.row
        self.mode_row.connect("notify::selected", lambda *_: self._sync_mode())
        mode_group.add(self.mode_row)

        self._order = KeyedCombo("Приоритет групп", list(ORDER_PRESETS.keys()), ORDER_LABELS)
        self.order_row = self._order.row
        mode_group.add(self.order_row)

        self.bypass_row = Adw.SwitchRow(
            title="Локальные сети напрямую",
            subtitle="127.0.0.0/8, 10.0.0.0/8, 192.168.0.0/16 и другие — после ваших списков",
        )
        mode_group.add(self.bypass_row)

        self.ru_direct_row = Adw.SwitchRow(
            title="Российские сайты и IP напрямую",
            subtitle=ru_direct_subtitle(current_catalog()),
        )
        mode_group.add(self.ru_direct_row)

        self.views: dict[str, Gtk.TextView] = {}
        for key, title, hint in LISTS:
            if key == "vpn" and vpn_hint is not None:
                hint = vpn_hint
            group, view = _list_view(title, hint)
            page.add(group)
            self.groups.append(group)
            self.views[key] = view
        self._enabled = True

    # --- состояние ---

    def _sync_mode(self) -> None:
        # В режиме «весь трафик через прокси» списки не применяются: активными
        # они обещали бы несуществующий эффект. «Локальные сети» действуют всегда.
        custom = self._enabled and self._mode.selected() == RoutingMode.CUSTOM
        for widget in (*self.views.values(), self.order_row, self.ru_direct_row):
            widget.set_sensitive(custom)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.mode_row.set_sensitive(enabled)
        self.bypass_row.set_sensitive(enabled)
        self._sync_mode()

    def load(self, routing) -> None:
        values = form_values(routing)
        self._mode.select(values.mode)
        self._order.select(values.order)
        self.bypass_row.set_active(values.bypass_local_networks)
        self.ru_direct_row.set_active(values.ru_direct)
        for key, text in values.lists.items():
            self.set_text(key, text)
        self._sync_mode()

    def values(self) -> FormValues:
        return FormValues(
            mode=self._mode.selected(),
            order=self._order.selected(),
            bypass_local_networks=self.bypass_row.get_active(),
            ru_direct=self.ru_direct_row.get_active(),
            lists={key: _read(view) for key, view in self.views.items()},
        )

    def read(self, routing) -> None:
        """Записать форму в `routing`; негодная запись — ValueError, цель не тронута."""
        apply_form_values(routing, self.values())

    def connect_changed(self, callback: Callable[[], None]) -> None:
        for row in (self.mode_row, self.order_row):
            row.connect("notify::selected", lambda *_: callback())
        for row in (self.bypass_row, self.ru_direct_row):
            row.connect("notify::active", lambda *_: callback())
        for view in self.views.values():
            view.get_buffer().connect("changed", lambda *_: callback())

    # --- доступ для тестов и диалогов ---

    def select_mode(self, key: str) -> None:
        self._mode.select(key)
        self._sync_mode()

    def selected_mode(self) -> str:
        return self._mode.selected()

    def select_order(self, order: list[str]) -> None:
        from src.ui.logic.routing_form import order_key

        self._order.select(order_key(order))

    def selected_order(self) -> list[str]:
        return list(ORDER_PRESETS[self._order.selected()])

    def text(self, key: str) -> str:
        return _read(self.views[key])

    def set_text(self, key: str, text: str) -> None:
        self.views[key].get_buffer().set_text(text)
```

Если `src/ui/widgets/__init__.py` нет — создать пустой (проверить `ls src/ui/widgets`). Импорт `KeyedCombo` из `src.ui.dialogs.settings` — так уже делает диалог сервера; если это даст цикл импорта после задачи 8, перенести `KeyedCombo` в `src/ui/widgets/keyed_combo.py` и импортировать оттуда в обоих местах.

**Шаг 4: тесты проходят**

Run: `make test-gtk ARGS="tests/test_ui_widgets_routing_form.py"`
Expected: PASS

**Шаг 5: коммит**

```bash
git add src/ui/widgets/routing_form.py tests/test_ui_widgets_routing_form.py
git commit -m "ui: общий виджет формы маршрутизации (GTK)"
```

### Задача 7: диалог сервера на общем виджете с переключателем (GTK)

**Файлы:**
- Изменить: `src/ui/dialogs/profile_routing.py` (страница маршрутизации, `_load`, `save`, аксессоры)
- Тест: `tests/test_ui_dialogs_profile_routing.py`

**Шаг 1: падающие тесты**

Конструктор получает второй параметр `shared_routing` — действующие общие правила (копия). Добавить в тест:

```python
def make_dialog(profile, shared=None):
    from src.db.config import RoutingSettings
    from src.ui.dialogs.profile_routing import ProfileRoutingDialog

    return ProfileRoutingDialog(profile, shared if shared is not None else RoutingSettings())


def test_a_server_without_own_rules_shows_the_shared_ones_dimmed(gtk_ready):
    profile = make_profile()
    profile.routing_settings = None
    dialog = make_dialog(profile, shared=routing_settings(mode="custom", proxy_list=["s.com"]))
    assert not dialog.own_rules_row.get_active()
    assert dialog.proxy_text() == "s.com"
    assert not dialog.proxy_view.get_sensitive()
    assert not dialog.mode_row.get_sensitive()


def test_enabling_own_rules_starts_from_a_copy_of_the_shared_ones(gtk_ready):
    profile = make_profile()
    profile.routing_settings = None
    shared = routing_settings(mode="custom", proxy_list=["s.com"])
    dialog = make_dialog(profile, shared=shared)
    dialog.own_rules_row.set_active(True)
    dialog.save()
    assert profile.routing_settings is not None
    assert profile.routing_settings is not shared
    assert profile.routing_settings.proxy_list == ["s.com"]
    assert dialog.proxy_view.get_sensitive()


def test_disabling_own_rules_drops_them_and_keeps_the_shared_untouched(gtk_ready):
    shared = routing_settings(mode="custom", proxy_list=["s.com"])
    profile = make_profile(routing=routing_settings(mode="custom", proxy_list=["own.com"]))
    dialog = make_dialog(profile, shared=shared)
    assert dialog.own_rules_row.get_active()
    dialog.own_rules_row.set_active(False)
    dialog.save()
    assert profile.routing_settings is None
    assert shared.proxy_list == ["s.com"]
    # Поля сохраняют введённое: повторное включение ничего не теряет.
    assert dialog.proxy_text() == "own.com"
```

Существующие тесты создают профиль с `routing_settings=RoutingSettings()` — переключатель у них включён, они проходят без правок.

**Шаг 2: убедиться, что падают**

Run: `make test-gtk ARGS="tests/test_ui_dialogs_profile_routing.py"`
Expected: FAIL, `TypeError: __init__() takes 2 positional arguments`

**Шаг 3: реализация**

В `src/ui/dialogs/profile_routing.py`:

- удалить `_list_view`, `_read`, импорты `RoutingMode`, `BLOCK_HINT`, `LIST_HINT`, `ORDER_LABELS`, `ORDER_PRESETS`, `current_catalog`, `ru_direct_subtitle`, `parse_host_list`, `_current_order`;
- `__init__(self, profile, shared_routing)`: сохранить `self._shared = shared_routing`;
- `_build_routing_page`:

```python
    def _build_routing_page(self) -> None:
        from src.ui.logic.routing_form import OWN_RULES_HINT, OWN_RULES_TITLE
        from src.ui.widgets.routing_form import RoutingForm

        page = Adw.PreferencesPage(title="Маршрутизация", icon_name="network-workgroup-symbolic")
        self.add(page)

        own = Adw.PreferencesGroup()
        page.add(own)
        self.own_rules_row = Adw.SwitchRow(title=OWN_RULES_TITLE, subtitle=OWN_RULES_HINT)
        self.own_rules_row.connect("notify::active", lambda *_: self._sync_own_rules())
        own.add(self.own_rules_row)

        self.form = RoutingForm(page)
        # Прямые имена оставлены для тестов и старого кода.
        self.mode_row = self.form.mode_row
        self.order_row = self.form.order_row
        self.bypass_row = self.form.bypass_row
        self.ru_direct_row = self.form.ru_direct_row
        self.block_view = self.form.views["block"]
        self.proxy_view = self.form.views["proxy"]
        self.direct_view = self.form.views["direct"]
        self.vpn_view = self.form.views["vpn"]
```

- `_sync_own_rules`: `self.form.set_enabled(self.own_rules_row.get_active())`;
- в `_load` вместо блока про routing:

```python
        routing = getattr(profile, "routing_settings", None)
        self.own_rules_row.set_active(routing is not None)
        # Без своих правил форма показывает общие: включение начнётся с их копии.
        self.form.load(routing if routing is not None else self._shared)
        self._sync_own_rules()
```

- в `save` вместо блока про routing:

```python
        if not self.own_rules_row.get_active():
            profile.routing_settings = None
        else:
            routing = copy.deepcopy(getattr(profile, "routing_settings", None) or RoutingSettings())
            try:
                self.form.read(routing)
            except ValueError as error:
                self.set_title(str(error))
                return False
            profile.routing_settings = routing
```

(проверку списков в начале `save` убрать: её делает `form.read`; `import copy` добавить; `set_title("VPN и маршруты")` при успехе);

- подписка на автосохранение: цикл по `vars(self)` оставить (он ловит `own_rules_row` и строки VPN), плюс `self.form.connect_changed(self._queue_save)`; из цикла исключить `Gtk.TextView` (их теперь нет в `vars`);
- аксессоры `selected_mode`, `select_mode`, `selected_order`, `select_order`, `*_text`, `set_*_text` — делегировать в `self.form` (`select_mode` → `self.form.select_mode`, `proxy_text` → `self.form.text("proxy")` и так далее).

В `src/ui/window.py:354-366` (`_row_profile_routing`):

```python
        from src.ui.logic.routing_import import effective_routing

        shared = effective_routing(self._context.config.routing, self._context.config_dir)
        dialog = ProfileRoutingDialog(profile, shared)
```

**Шаг 4: тесты проходят**

Run: `make test-gtk ARGS="tests/test_ui_dialogs_profile_routing.py tests/test_ui_widgets_routing_form.py"`
Expected: PASS

**Шаг 5: коммит**

```bash
git add src/ui/dialogs/profile_routing.py src/ui/window.py tests/test_ui_dialogs_profile_routing.py
git commit -m "ui: переключатель «Свои правила маршрутизации» в диалоге сервера (GTK)"
```

### Задача 8: страница настроек «Маршрутизация» (GTK)

**Файлы:**
- Изменить: `src/ui/dialogs/settings.py` (`__init__`, новый `_build_routing_page`, `_build_about_page`, `_load`, `save`), `src/ui/logic/platform_texts.py:39-43`
- Изменить: `src/ui/application.py:473-482` (обновление строки «Вернуть» после отката)
- Тест: `tests/test_ui_dialogs_settings.py`, `tests/test_ui_logic_platform_texts.py`

**Шаг 1: падающие тесты**

В `tests/test_ui_dialogs_settings.py` заменить `test_restore_routing_row_follows_backup` и добавить:

```python
def test_the_routing_page_loads_the_shared_rules(gtk_ready, tmp_path):
    config = make_config()
    config.routing.mode = "custom"
    config.routing.proxy_list = ["s.com"]
    config.routing.use_saved_lists = True
    dialog, _context = make_about_dialog(config)
    assert dialog.routing.text("proxy") == "s.com"
    assert dialog.routing_page.get_title() == "Маршрутизация"


def test_the_routing_page_reads_legacy_list_files(gtk_ready, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from src.ui.dialogs.settings import SettingsDialog

    (tmp_path / "direct_list.txt").write_text("old.example\n", encoding="utf-8")
    config = make_config()
    context = SimpleNamespace(
        xray_manager=SimpleNamespace(get_version=lambda: {"version": "1"}),
        config_dir=tmp_path,
        save_config=Mock(return_value=True),
    )
    dialog = SettingsDialog(config, context)
    assert dialog.routing.text("direct") == "old.example"


def test_saving_writes_the_shared_rules_and_switches_to_saved_lists(gtk_ready):
    config = make_config()
    dialog, _context = make_about_dialog(config)
    dialog.routing.select_mode("custom")
    dialog.routing.set_text("proxy", "a.com\nb.com")
    assert dialog.save()
    assert config.routing.proxy_list == ["a.com", "b.com"]
    assert config.routing.use_saved_lists is True


def test_a_bad_routing_entry_blocks_saving(gtk_ready):
    config = make_config()
    dialog, _context = make_about_dialog(config)
    dialog.routing.select_mode("custom")
    dialog.routing.set_text("direct", "http://user:pw@x.com")
    assert not dialog.save()
    assert config.routing.direct_list == []
    assert "credentials" in dialog.get_title()


def test_restore_routing_row_lives_on_the_routing_page(gtk_ready):
    from src.db.config import RoutingSettings

    dialog, _context = make_about_dialog()
    assert not dialog.restore_routing_row.get_visible()

    config = make_config()
    config.routing_backup = RoutingSettings()
    dialog, _context = make_about_dialog(config)
    assert dialog.restore_routing_row.get_visible()
    assert dialog.restore_routing_row.get_parent().get_ancestor(type(dialog.routing_page)) is (
        dialog.routing_page
    )
    assert dialog.restore_routing_button.get_action_name() == "app.restore-routing"
    dialog.sync_restore_routing(False)
    assert not dialog.restore_routing_row.get_visible()
```

В `tests/test_ui_logic_platform_texts.py` расширить ожидание: кортеж `("routing", "bypass", "subscriptions", "about")` даёт `["Маршрутизация", "Обход блокировок", "Подписки", "О программе"]` для обеих ОС.

**Шаг 2: убедиться, что падают**

Run: `make test-gtk ARGS="tests/test_ui_dialogs_settings.py -k routing"` и `uv run pytest tests/test_ui_logic_platform_texts.py -q`
Expected: FAIL, `AttributeError: 'SettingsDialog' object has no attribute 'routing'` и `KeyError: 'routing'`

**Шаг 3: реализация**

`src/ui/logic/platform_texts.py`: добавить `"routing": "Маршрутизация"` в `_SETTINGS_PAGE_TITLES`.

`src/ui/dialogs/settings.py`:

- в `__init__` после `_build_dns_page()` вызвать `self._build_routing_page()`;
- новая страница:

```python
    def _build_routing_page(self) -> None:
        from src.ui.logic.routing_form import GLOBAL_PAGE_HINT, VPN_LIST_HINT
        from src.ui.widgets.routing_form import RoutingForm

        page = Adw.PreferencesPage(
            title=platform_texts.settings_page_title("routing"),
            icon_name="network-workgroup-symbolic",
            description=GLOBAL_PAGE_HINT,
        )
        self.routing_page = page
        self.add(page)

        self.routing = RoutingForm(page, vpn_hint=VPN_LIST_HINT)

        extra = Adw.PreferencesGroup(title="Дополнительно")
        page.add(extra)
        # Без подтверждения, как в Android: откат меняет только списки,
        # которые пользователь сам только что заменил импортом.
        self.restore_routing_row = Adw.ActionRow(
            title="Маршрутизация до импорта",
            subtitle="Вернёт режим и списки, которые были до последнего импорта",
        )
        self.restore_routing_button = Gtk.Button(
            label="Вернуть", valign=Gtk.Align.CENTER, action_name="app.restore-routing"
        )
        self.restore_routing_row.add_suffix(self.restore_routing_button)
        self.restore_routing_row.set_visible(
            getattr(self._config, "routing_backup", None) is not None
        )
        extra.add(self.restore_routing_row)

    def sync_restore_routing(self, available: bool) -> None:
        self.restore_routing_row.set_visible(available)
        if available:
            # Списки после отката другие: показать их, не дожидаясь закрытия.
            self.routing.load(self._shared_routing())

    def _shared_routing(self):
        from src.ui.logic.routing_import import effective_routing

        config_dir = getattr(self._context, "config_dir", None) if self._context else None
        return effective_routing(self._config.routing, config_dir)
```

- из `_build_about_page` удалить строку и кнопку «Маршрутизация до импорта» (группа «Обслуживание» остаётся с журналами и геобазами);
- в `_load`: `self.routing.load(self._shared_routing())`;
- в `save` перед `errors = validate_settings(config)`:

```python
        from src.ui.logic.routing_import import store_shared_routing

        routing = copy.deepcopy(config.routing)
        try:
            self.routing.read(routing)
        except ValueError as error:
            self.set_title(f"Исправьте настройки: {error}")
            return False
        store_shared_routing(config, routing)
```

(`config` здесь — копия, `store_shared_routing` ставит `use_saved_lists` на копии, живые настройки обновляются существующим `self._config.__dict__.update`);

- в `__init__` после цикла подписки: `self.routing.connect_changed(self._queue_save)`.

Важно: `sync_restore_routing(True)` вызывает `self.routing.load(...)`, что запускает автосохранение. Это безвредно: форма сохранит то же, что только что загрузила. Чтобы не плодить запись, в `sync_restore_routing` обернуть загрузку в флаг `self._loading = True` и в `_queue_save` выходить при нём (так же сделать в `_load`).

`src/ui/application.py`, `restore_routing` (строка 379) и там, где создаётся `SettingsDialog`: после `self.controller.restore_routing()` найти открытый диалог настроек (`self._dialog`/слот диалога — посмотреть, как хранится текущий диалог в `present_dialog`) и, если это `SettingsDialog`, вызвать `dialog.sync_restore_routing(self.context.config.routing_backup is not None)`. Та же синхронизация после `apply_routing_import` (импорт ссылкой при открытых настройках). Если в `TengaApplication` нет доступа к текущему диалогу, добавить атрибут при `present_dialog`.

**Шаг 4: тесты проходят**

Run: `make test-gtk ARGS="tests/test_ui_dialogs_settings.py tests/test_ui_dialogs_profile_routing.py"` и `uv run pytest tests/test_ui_logic_platform_texts.py -q`
Expected: PASS. Проверить руками: `python gui.py`, Настройки → Маршрутизация, правка списка, закрытие, повторное открытие показывает сохранённое; `settings.json` содержит `"use_saved_lists": true`.

**Шаг 5: коммит**

```bash
git add src/ui/dialogs/settings.py src/ui/application.py src/ui/logic/platform_texts.py tests/
git commit -m "ui: страница настроек «Маршрутизация» (GTK)"
```

---

## Этап 3. Qt

### Задача 9: общий виджет формы (Qt)

**Файлы:**
- Создать: `src/ui/qt/widgets/routing_form.py` (каталог `src/ui/qt/widgets/` проверить, создать с `__init__.py` при отсутствии)
- Тест: `tests/test_ui_qt_routing_form.py` (маркер `qt`)

**Шаг 1: падающий тест**

```python
"""Общий виджет формы маршрутизации (Qt)."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from src.db.config import RoutingMode, RoutingSettings
from src.ui.qt.widgets.routing_form import RoutingForm

pytestmark = pytest.mark.qt


def test_load_and_read_round_trip(qapp):
    form = RoutingForm()
    source = RoutingSettings(
        mode=RoutingMode.CUSTOM,
        proxy_list=["a.com"],
        rule_order=["vpn", "proxy", "direct"],
        ru_direct=True,
    )
    form.load(source)
    target = RoutingSettings()
    form.read(target)
    assert target.to_dict() == source.to_dict()


def test_lists_sleep_in_proxy_all(qapp):
    form = RoutingForm()
    form.load(RoutingSettings(mode=RoutingMode.PROXY_ALL))
    assert not form.lists["proxy"].isEnabled()
    assert form.bypass_check.isEnabled()
    form.mode_combo.select(RoutingMode.CUSTOM)
    assert form.lists["proxy"].isEnabled()


def test_set_enabled_dims_everything(qapp):
    form = RoutingForm()
    form.load(RoutingSettings(mode=RoutingMode.CUSTOM))
    form.set_enabled(False)
    assert not form.mode_combo.isEnabled()
    assert not form.lists["proxy"].isEnabled()
    form.set_enabled(True)
    assert form.lists["proxy"].isEnabled()


def test_bad_entry_marks_its_list_and_raises(qapp):
    form = RoutingForm()
    form.load(RoutingSettings(mode=RoutingMode.CUSTOM))
    form.lists["direct"].setPlainText("http://user:pw@x.com")
    target = RoutingSettings(direct_list=["x.com"])
    with pytest.raises(ValueError):
        form.read(target)
    assert form.lists["direct"].property("error") is True
    assert target.direct_list == ["x.com"]
    form.lists["direct"].setPlainText("ok.com")
    form.read(target)
    assert form.lists["direct"].property("error") in (None, False)


def test_fields_cover_every_control(qapp):
    form = RoutingForm()
    fields = form.fields()
    assert form.mode_combo in fields and form.order_combo in fields
    assert form.bypass_check in fields and form.ru_direct_check in fields
    assert all(edit in fields for edit in form.lists.values())
```

**Шаг 2: убедиться, что падает**

Run: `make test-qt ARGS="tests/test_ui_qt_routing_form.py"`
Expected: FAIL, `ModuleNotFoundError`

**Шаг 3: реализация**

`src/ui/qt/widgets/routing_form.py`:

```python
"""Форма маршрутизации (Qt): та же, что в GTK `src/ui/widgets/routing_form.py`."""

from __future__ import annotations

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QPlainTextEdit, QVBoxLayout, QWidget

from src.db.config import RoutingMode
from src.ui.logic.routing_form import (
    LISTS,
    ORDER_LABELS,
    ORDER_PRESETS,
    FormValues,
    apply_form_values,
    current_catalog,
    form_values,
    ru_direct_subtitle,
)
from src.ui.qt.dialogs.base import KeyedCombo, mark_error


def _check(text: str, subtitle: str = "") -> QCheckBox:
    box = QCheckBox(text)
    box.setToolTip(subtitle)
    return box


class RoutingForm(QWidget):
    """Группа «Режим» и четыре списка в одной колонке."""

    def __init__(self, *, vpn_hint: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)

        mode = QGroupBox("Режим")
        form = QFormLayout(mode)
        self.mode_combo = KeyedCombo(RoutingMode.ALL, RoutingMode.LABELS)
        self.mode_combo.currentIndexChanged.connect(self._sync_mode)
        form.addRow("Правила", self.mode_combo)
        self.order_combo = KeyedCombo(ORDER_PRESETS, ORDER_LABELS)
        form.addRow("Приоритет групп", self.order_combo)
        self.bypass_check = _check(
            "Локальные сети напрямую",
            "127.0.0.0/8, 10.0.0.0/8, 192.168.0.0/16 и другие — после ваших списков",
        )
        form.addRow(self.bypass_check)
        self.ru_direct_check = _check(
            "Российские сайты и IP напрямую", ru_direct_subtitle(current_catalog())
        )
        form.addRow(self.ru_direct_check)
        column.addWidget(mode)

        self.lists: dict[str, QPlainTextEdit] = {}
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        for key, title, hint in LISTS:
            if key == "vpn" and vpn_hint is not None:
                hint = vpn_hint
            box = QGroupBox(title)
            box.setToolTip(hint)
            inner = QVBoxLayout(box)
            edit = QPlainTextEdit()
            edit.setFont(font)
            edit.setPlaceholderText(hint)
            edit.setMinimumHeight(110)
            inner.addWidget(edit)
            self.lists[key] = edit
            column.addWidget(box)
        self._enabled = True

    def _sync_mode(self) -> None:
        custom = self._enabled and self.mode_combo.selected() == RoutingMode.CUSTOM
        for widget in (*self.lists.values(), self.order_combo, self.ru_direct_check):
            widget.setEnabled(custom)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.mode_combo.setEnabled(enabled)
        self.bypass_check.setEnabled(enabled)
        self._sync_mode()

    def fields(self) -> list[QWidget]:
        return [
            self.mode_combo,
            self.order_combo,
            self.bypass_check,
            self.ru_direct_check,
            *self.lists.values(),
        ]

    def load(self, routing) -> None:
        values = form_values(routing)
        self.mode_combo.select(values.mode)
        self.order_combo.select(values.order)
        self.bypass_check.setChecked(values.bypass_local_networks)
        self.ru_direct_check.setChecked(values.ru_direct)
        for key, text in values.lists.items():
            self.lists[key].setPlainText(text)
        self._sync_mode()

    def values(self) -> FormValues:
        return FormValues(
            mode=self.mode_combo.selected(),
            order=self.order_combo.selected(),
            bypass_local_networks=self.bypass_check.isChecked(),
            ru_direct=self.ru_direct_check.isChecked(),
            lists={key: edit.toPlainText() for key, edit in self.lists.items()},
        )

    def read(self, routing) -> None:
        """Записать форму в `routing`; список с ошибкой подсвечен, ValueError наружу."""
        from src.ui.logic.forms import parse_host_list

        first_error: ValueError | None = None
        for key, edit in self.lists.items():
            try:
                parse_host_list(edit.toPlainText())
                mark_error(edit, None)
            except ValueError as error:
                mark_error(edit, str(error))
                first_error = first_error or error
        if first_error is not None:
            raise first_error
        apply_form_values(routing, self.values())
```

**Шаг 4: тесты проходят**

Run: `make test-qt ARGS="tests/test_ui_qt_routing_form.py"`
Expected: PASS

**Шаг 5: коммит**

```bash
git add src/ui/qt/widgets tests/test_ui_qt_routing_form.py
git commit -m "ui: общий виджет формы маршрутизации (Qt)"
```

### Задача 10: диалог сервера на общем виджете с переключателем (Qt)

**Файлы:**
- Изменить: `src/ui/qt/dialogs/profile_routing.py`, `src/ui/qt/application.py:447-453`
- Тест: `tests/test_ui_qt_profile_routing.py`

**Шаг 1: падающие тесты**

В `tests/test_ui_qt_profile_routing.py` заменить вызовы `ProfileRoutingDialog(profile)` на `ProfileRoutingDialog(profile, RoutingSettings())` (помощник `_dialog(profile, shared=None)`), добавить:

```python
def test_server_without_own_rules_shows_shared_dimmed(qapp):
    profile = _profile()
    profile.routing_settings = None
    dialog = _dialog(profile, RoutingSettings(mode=RoutingMode.CUSTOM, proxy_list=["s.com"]))
    assert not dialog.own_rules_check.isChecked()
    assert dialog.lists["proxy"].toPlainText() == "s.com"
    assert not dialog.lists["proxy"].isEnabled()
    assert not dialog.mode_combo.isEnabled()


def test_enabling_own_rules_copies_the_shared_ones(qapp):
    profile = _profile()
    profile.routing_settings = None
    shared = RoutingSettings(mode=RoutingMode.CUSTOM, proxy_list=["s.com"])
    dialog = _dialog(profile, shared)
    dialog.own_rules_check.setChecked(True)
    assert dialog.save()
    assert profile.routing_settings is not None and profile.routing_settings is not shared
    assert profile.routing_settings.proxy_list == ["s.com"]


def test_disabling_own_rules_drops_them_and_keeps_the_text(qapp):
    profile = _profile(routing=RoutingSettings(mode=RoutingMode.CUSTOM, proxy_list=["own.com"]))
    dialog = _dialog(profile)
    dialog.own_rules_check.setChecked(False)
    assert dialog.save()
    assert profile.routing_settings is None
    assert dialog.lists["proxy"].toPlainText() == "own.com"
```

**Шаг 2: убедиться, что падают**

Run: `make test-qt ARGS="tests/test_ui_qt_profile_routing.py"`
Expected: FAIL, `TypeError`

**Шаг 3: реализация**

В `src/ui/qt/dialogs/profile_routing.py`:

- удалить `LISTS`, `_check` (если не нужен для VPN — он нужен для `vpn_auto_check`, оставить), импорты `RoutingMode`, `BLOCK_HINT`, `LIST_HINT`, `ORDER_*`, `current_catalog`, `order_key`, `ru_direct_subtitle`, `parse_host_list`, `mark_error`, `QFontDatabase`, `QPlainTextEdit`;
- `__init__(self, profile, shared_routing, parent=None)`, `self._shared = shared_routing`;
- `_build_routing_page`:

```python
    def _build_routing_page(self) -> QWidget:
        from src.ui.logic.routing_form import OWN_RULES_HINT, OWN_RULES_TITLE
        from src.ui.qt.widgets.routing_form import RoutingForm

        page = QWidget()
        column = QVBoxLayout(page)
        self.own_rules_check = _check(OWN_RULES_TITLE, OWN_RULES_HINT)
        self.own_rules_check.toggled.connect(self._sync_own_rules)
        column.addWidget(self.own_rules_check)
        hint = QLabel(OWN_RULES_HINT)
        hint.setWordWrap(True)
        column.addWidget(hint)
        self.form = RoutingForm()
        column.addWidget(self.form)
        self.mode_combo = self.form.mode_combo
        self.order_combo = self.form.order_combo
        self.bypass_check = self.form.bypass_check
        self.ru_direct_check = self.form.ru_direct_check
        self.lists = self.form.lists
        return page

    def _sync_own_rules(self) -> None:
        self.form.set_enabled(self.own_rules_check.isChecked())
```

- `_load`: `routing = getattr(profile, "routing_settings", None)`; `self.own_rules_check.setChecked(routing is not None)`; `self.form.load(routing if routing is not None else self._shared)`; `self._sync_own_rules()`;
- `save`: вместо проверки списков и блока routing:

```python
        if not self.own_rules_check.isChecked():
            profile.routing_settings = None
            self.status.hide()
        else:
            routing = copy.deepcopy(getattr(profile, "routing_settings", None) or RoutingSettings())
            try:
                self.form.read(routing)
            except ValueError as error:
                self.status.setText(str(error))
                self.status.show()
                return False
            self.status.hide()
            profile.routing_settings = routing
```

(VPN-часть `save` остаётся до этого блока; `import copy`);

- `watch([...])`: заменить перечисление полей маршрутизации на `self.own_rules_check, *self.form.fields()`.

В `src/ui/qt/application.py:447-453`:

```python
        from src.ui.logic.routing_import import effective_routing

        shared = effective_routing(self.context.config.routing, self.context.config_dir)
        dialog = ProfileRoutingDialog(profile, shared)
```

**Шаг 4: тесты проходят**

Run: `make test-qt ARGS="tests/test_ui_qt_profile_routing.py tests/test_ui_qt_routing_form.py"`
Expected: PASS

**Шаг 5: коммит**

```bash
git add src/ui/qt/dialogs/profile_routing.py src/ui/qt/application.py tests/test_ui_qt_profile_routing.py
git commit -m "ui: переключатель «Свои правила маршрутизации» в диалоге сервера (Qt)"
```

### Задача 11: страница настроек «Маршрутизация» (Qt)

**Файлы:**
- Создать: `assets/icons/ui/routing.svg` (в стиле соседних `dns.svg`, `bypass.svg`: монохромный 24×24, `currentColor`; взять контур «узлы и связи» или стрелки-развилку)
- Изменить: `src/ui/qt/dialogs/settings.py` (`SECTIONS`, список иконок, страницы, `_fields`, `_load`, `save`, `refresh`), `src/ui/qt/dialogs/settings_pages.py:221-345` (убрать строку «Маршрутизация до импорта» из `AboutPage`, `refresh` сделать пустым или убрать)
- Тест: `tests/test_ui_qt_settings.py`, `tests/test_packaging_spec.py` (если он перечисляет иконки — проверить `grep -n "icons/ui" tests/test_packaging_spec.py packaging/`)

**Шаг 1: падающие тесты**

В `tests/test_ui_qt_settings.py` заменить `test_restore_routing_row_follows_the_backup` и `test_sections_switch_pages` (индекс «DNS» остаётся 2, «Маршрутизация» — 3):

```python
def test_routing_page_round_trips_the_shared_rules(app):
    dialog = _open(app)
    dialog.show_section("Маршрутизация")
    assert dialog.pages.currentIndex() == 3
    dialog.routing.mode_combo.select(RoutingMode.CUSTOM)
    dialog.routing.lists["proxy"].setPlainText("a.com\nb.com")

    assert dialog.save()

    assert app.context.config.routing.proxy_list == ["a.com", "b.com"]
    assert app.context.config.routing.use_saved_lists is True
    assert _saved(app)["routing"]["proxy_list"] == ["a.com", "b.com"]


def test_bad_routing_entry_blocks_saving(app):
    dialog = _open(app)
    dialog.routing.mode_combo.select(RoutingMode.CUSTOM)
    dialog.routing.lists["direct"].setPlainText("http://user:pw@x.com")
    assert not dialog.save()
    assert dialog.routing.lists["direct"].property("error") is True
    assert app.context.config.routing.direct_list == []


def test_restore_routing_row_follows_the_backup_on_the_routing_page(app):
    dialog = _open(app)
    assert not dialog.routing_extra.isRowVisible(dialog.restore_routing_row)

    app.context.config.routing_backup = RoutingSettings()
    app.controller.sync_restore_routing()

    assert dialog.routing_extra.isRowVisible(dialog.restore_routing_row)
    assert not hasattr(dialog.about, "restore_routing_row")
```

Импортировать `RoutingMode` в тесте.

**Шаг 2: убедиться, что падают**

Run: `make test-qt ARGS="tests/test_ui_qt_settings.py -k routing or sections"`
Expected: FAIL

**Шаг 3: реализация**

`src/ui/qt/dialogs/settings.py`:

- `SECTIONS = ("Общие", "Мониторинг", "DNS", "Маршрутизация", "Обход блокировок", "Подписки", "О программе")`; в цикл иконок добавить `"routing"` после `"dns"`; в `QStackedWidget` вставить `self._routing_page()` после `self._dns_page()`;
- страница:

```python
    def _routing_page(self) -> QWidget:
        from src.ui.logic.routing_form import GLOBAL_PAGE_HINT, VPN_LIST_HINT
        from src.ui.qt.widgets.routing_form import RoutingForm

        self.routing = RoutingForm(vpn_hint=VPN_LIST_HINT)

        extra = QGroupBox("Дополнительно")
        self.routing_extra = QFormLayout(extra)
        self.restore_routing_button = QPushButton("Вернуть")
        self.restore_routing_button.clicked.connect(
            lambda: self._app.activate_action("restore-routing")
        )
        label = QLabel("Режим и списки до последнего импорта")
        label.setWordWrap(True)
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(label, 1)
        row_layout.addWidget(self.restore_routing_button)
        self.restore_routing_row = row_widget
        self.routing_extra.addRow("Маршрутизация до импорта", self.restore_routing_row)
        self.routing_extra.setRowVisible(
            self.restore_routing_row, self._config.routing_backup is not None
        )
        return page(hint(GLOBAL_PAGE_HINT), self.routing, extra)
```

(`QPushButton` добавить в импорты; `page(...)` принимает виджеты — проверить, что `hint()` возвращает `QLabel` и `page()` его принимает; иначе обернуть в `QGroupBox` без заголовка);

- `_fields`: добавить `*self.routing.fields()`;
- `_load`: `self.routing.load(self._shared_routing())`, где

```python
    def _shared_routing(self):
        from src.ui.logic.routing_import import effective_routing

        return effective_routing(self._config.routing, self._context.config_dir)
```

- `save` перед `errors = validate_settings(config)`:

```python
        from src.ui.logic.routing_import import store_shared_routing

        routing = copy.deepcopy(config.routing)
        try:
            self.routing.read(routing)
        except ValueError as error:
            self.status.setProperty("error", True)
            self.status.setText(f"Исправьте настройки: {error}")
            mark_error(self.status, self.status.text())
            self.status.show()
            return False
        store_shared_routing(config, routing)
```

- `refresh`: вместо `self.about.refresh()`:

```python
        available = self._config.routing_backup is not None
        self.routing_extra.setRowVisible(self.restore_routing_row, available)
```

и после отката перезагружать форму без автосохранения: обернуть `self.routing.load(...)` в блокировку сигналов (`for w in self.routing.fields(): w.blockSignals(True)` … `False`) или завести флаг `self._loading`, который `_queue_save` уважает. Сделать то же в `_load`, если `watch` подключается до него (сейчас — после, флаг нужен только в `refresh`).

`src/ui/qt/dialogs/settings_pages.py`: убрать `restore_routing_button`, `restore_routing_row`, строку формы и `refresh` из `AboutPage`; из `__init__` убрать `self.refresh()`. Поиск других вызовов: `grep -rn "about.refresh\|restore_routing" src/ui/qt`.

`src/ui/qt/application.py`: `refresh_dialog` уже зовёт `dialog.refresh()` после `sync_restore_routing` — проверить, что `restore-routing` и `apply_routing_import` ведут к `refresh_dialog` (строки 104, 140); иначе добавить вызов.

**Шаг 4: тесты проходят**

Run: `make test-qt`
Expected: PASS. Руками: `python gui.py --ui qt`, Настройки → Маршрутизация, строка «Вернуть» появляется после импорта ссылкой.

**Шаг 5: коммит**

```bash
git add assets/icons/ui/routing.svg src/ui/qt/dialogs/settings.py src/ui/qt/dialogs/settings_pages.py tests/test_ui_qt_settings.py
git commit -m "ui: страница настроек «Маршрутизация» (Qt)"
```

### Задача 12: проверка границ тулкитов

**Файлы:**
- Тест: `tests/test_ui_platform_branches.py` (без правок: новые виджеты не читают `IS_WINDOWS`), `tests/test_branding.py`, `tests/test_packaging_spec.py`

**Шаг 1: прогнать**

Run: `uv run pytest tests/test_ui_platform_branches.py tests/test_branding.py tests/test_packaging_spec.py -q`
Expected: PASS. Если `test_packaging_spec` или `packaging/windows/*.spec` перечисляют `assets/icons/ui` поимённо — добавить `routing.svg`.

**Шаг 2: lint**

Run: `python cli.py lint-all`
Expected: без ошибок. Коммит только при правках.

---

## Этап 4. Заголовок подписки

### Задача 13: разбор голого base64 и `routing/off`

**Файлы:**
- Изменить: `src/fmt/app_links.py`
- Тест: `tests/test_fmt_app_links.py`

**Шаг 1: падающие тесты**

```python
def test_subscription_routing_value_accepts_bare_base64_and_links():
    from src.fmt.app_links import parse_subscription_routing

    payload = base64.urlsafe_b64encode(json.dumps({"ProxySites": ["x.com"]}).encode()).decode()
    bare = parse_subscription_routing(payload)
    linked = parse_subscription_routing("happ://routing/add/" + payload)
    assert bare.operation == linked.operation == "routing"
    assert bare.routing.proxy_list == linked.routing.proxy_list == ["x.com"]
    assert bare.payload_hash == linked.payload_hash
    assert len(bare.payload_hash) == 64


def test_subscription_routing_off_is_a_reset_offer():
    from src.fmt.app_links import ROUTING_OFF_HASH, parse_subscription_routing

    link = parse_subscription_routing("happ://routing/off")
    assert link.operation == "routing_off"
    assert link.payload_hash == ROUTING_OFF_HASH
    assert parse_subscription_routing("HAPP://routing/off/").operation == "routing_off"


def test_manual_links_still_reject_bare_payloads_and_off():
    payload = base64.urlsafe_b64encode(b"{}").decode()
    with pytest.raises(ValueError):
        parse_app_link(payload)
    with pytest.raises(ValueError):
        parse_app_link("happ://routing/off")


def test_subscription_routing_rejects_garbage():
    from src.fmt.app_links import parse_subscription_routing

    with pytest.raises(ValueError):
        parse_subscription_routing("not base64 at all!!")
    with pytest.raises(ValueError):
        parse_subscription_routing("x" * 350_001)
```

**Шаг 2: убедиться, что падают**

Run: `uv run pytest tests/test_fmt_app_links.py -q`
Expected: FAIL, `ImportError`

**Шаг 3: реализация**

В `src/fmt/app_links.py`:

- в `AppLink` добавить поле `payload_hash: str = ""`;
- вынести разбор JSON набора из `parse_app_link` в `_parse_routing_payload(encoded: str) -> AppLink` (тело от `try: data = base64.b64decode(...)` до `return AppLink("routing", ...)`), который считает `payload_hash = hashlib.sha256(data).hexdigest()` от декодированных байтов и кладёт в `AppLink`; `parse_app_link` зовёт его после `encoded = _decode(...)`;
- добавить:

```python
import hashlib

MAX_LINK_LENGTH = 350000
ROUTING_OFF_HASH = hashlib.sha256(b"happ://routing/off").hexdigest()
_ROUTING_PREFIXES = (
    "happ://routing/add/",
    "happ://routing/onadd/",
    "veblock://routing/add/",
    "wingeon://routing/add/",
)


def parse_subscription_routing(raw: str) -> AppLink:
    """Значение заголовка `routing` подписки: ссылка, `off` или голый base64.

    Ручная ссылка (`parse_app_link`) требует схему и отвергает `off`: сброс
    имеет смысл только от подписки, которая и предлагала набор.
    """
    value = raw.strip()
    if not value or len(value) > MAX_LINK_LENGTH:
        raise ValueError("Некорректный набор маршрутов подписки")
    if value.lower().rstrip("/") == "happ://routing/off":
        return AppLink("routing_off", payload_hash=ROUTING_OFF_HASH)
    lower = value.lower()
    prefix = next((p for p in _ROUTING_PREFIXES if lower.startswith(p)), None)
    encoded = value[len(prefix) :] if prefix else value
    encoded = encoded.split("?", 1)[0].split("#", 1)[0]
    return _parse_routing_payload(_decode(encoded))
```

`len(raw) > 350000` в `parse_app_link` уже есть; вынести число в `MAX_LINK_LENGTH`.

**Шаг 4: тесты проходят**

Run: `uv run pytest tests/test_fmt_app_links.py -q`
Expected: PASS

**Шаг 5: коммит**

```bash
git add src/fmt/app_links.py tests/test_fmt_app_links.py
git commit -m "fmt: набор маршрутов из заголовка подписки и routing/off"
```

### Задача 14: метаданные подписки читают `routing`

**Файлы:**
- Изменить: `src/sub/metadata.py` (докстринг, `KEY_ROUTING`, `KNOWN_KEYS`, `SubscriptionMetadata.routing_link`, `parse_metadata`), `src/sub/updater.py:58-62, 306-312`
- Тест: `tests/test_sub_metadata.py`, `tests/test_sub_updater.py` (найти по `new_url`: `grep -ln "new_url" tests/test_sub_*.py`)

**Шаг 1: падающие тесты**

```python
# --- routing ------------------------------------------------------------------


def test_routing_is_read_from_headers_and_the_body_wins():
    headers = metadata_from_headers({"Routing": "happ://routing/add/AAA"})
    assert headers.routing_link == "happ://routing/add/AAA"

    merged = read_metadata(
        {"routing": "happ://routing/add/AAA"}, "#routing: happ://routing/off\n" + "vless://x"
    )
    assert merged.routing_link == "happ://routing/off"


def test_routing_value_is_not_decoded_as_base64_text():
    """Значение — ссылка или base64 набора: `base64:` префикс тут не ожидается."""
    payload = b64('{"ProxySites":["x.com"]}')
    assert metadata_from_headers({"routing": payload}).routing_link == payload


def test_too_long_routing_value_is_dropped():
    assert metadata_from_headers({"routing": "x" * 350_001}).routing_link == ""


def test_routing_is_not_stored_on_the_group():
    from src.db.profiles import ProfileGroup
    from src.sub.metadata import apply_metadata

    group = ProfileGroup(id=1, is_subscription=True, subscription_url="https://a/b")
    apply_metadata(group, SubscriptionMetadata(routing_link="happ://routing/off"))
    assert "routing" not in {k for k in group.to_dict() if group.to_dict()[k] == "happ://routing/off"}
```

И в тесте обновления (`tests/test_sub_updater.py` или где проверяется `updater.new_url`): после `update()` с ответом, в заголовках которого `routing: happ://routing/off`, `updater.routing_link == "happ://routing/off"`; без заголовка — пустая строка; ответ берётся так же, как в соседнем тесте про `new-url`.

**Шаг 2: убедиться, что падают**

Run: `uv run pytest tests/test_sub_metadata.py -q`
Expected: FAIL, `AttributeError: routing_link`

**Шаг 3: реализация**

`src/sub/metadata.py`:

- докстринг модуля: «Ключ ``routing`` читается только как предложение набора маршрутов: применяется после подтверждения (`AppController`). ``hide-settings``, mux, per-app по-прежнему не распознаются»;
- `KEY_ROUTING = "routing"`, добавить в `KNOWN_KEYS`; `MAX_ROUTING_LENGTH = 350000`;
- в `SubscriptionMetadata`: `routing_link: str = ""  # предложение набора маршрутов; в группу не пишется`;
- в `parse_metadata`: `routing_link=_bounded(raw(KEY_ROUTING), MAX_ROUTING_LENGTH)`, где `raw(key)` — как `text`, но без `decode_value` (значение само может быть base64), а `_bounded` возвращает `""` при превышении длины.

`src/sub/updater.py`: поле `self.routing_link = ""` рядом с `new_url` (комментарий: «набор маршрутов из заголовка; предлагает контроллер»), сброс в начале `update()`, `self.routing_link = metadata.routing_link` после `read_metadata`.

`apply_metadata` не трогает `routing_link` — ничего менять не нужно.

**Шаг 4: тесты проходят**

Run: `uv run pytest tests/test_sub_metadata.py tests/test_sub_updater.py -q`
Expected: PASS

**Шаг 5: коммит**

```bash
git add src/sub/metadata.py src/sub/updater.py tests/
git commit -m "sub: читать заголовок routing подписки как предложение"
```

### Задача 15: строки окна и план сброса для подписки

**Файлы:**
- Изменить: `src/ui/logic/routing_import.py`, `src/db/profiles.py:95-102`
- Тест: `tests/test_ui_logic_routing_import.py`, `tests/test_db_profiles.py`

**Шаг 1: падающие тесты**

```python
def test_subscription_rows_start_with_the_subscription_name():
    from src.ui.logic.routing_import import import_rows

    rows = import_rows(
        RoutingSettings(), RoutingSettings(), name="RU", direct_default=False, subscription="Мой VPN"
    )
    assert rows[0] == ImportRow("Подписка", "Мой VPN")
    assert rows[1] == ImportRow("Набор маршрутов", "RU")


def test_reset_routing_clears_lists_and_mode_but_keeps_device_settings():
    from src.ui.logic.routing_import import reset_routing

    current = RoutingSettings(
        mode=RoutingMode.PROXY_ALL,
        proxy_list=["p"], direct_list=["d"], block_list=["b"], vpn_list=["v"],
        rule_order=["vpn", "proxy", "direct"], bypass_local_networks=False, ru_direct=True,
        use_saved_lists=False,
    )
    result = reset_routing(current)
    assert result.mode == RoutingSettings().mode
    assert result.proxy_list == result.direct_list == result.block_list == []
    assert result.vpn_list == ["v"]
    assert result.rule_order == ["vpn", "proxy", "direct"]
    assert result.bypass_local_networks is False and result.ru_direct is True
    assert current.proxy_list == ["p"]


def test_reset_is_a_no_op_when_already_default():
    from src.ui.logic.routing_import import reset_routing, routing_differs

    current = RoutingSettings(vpn_list=["v"])
    assert not routing_differs(current, reset_routing(current))
    assert routing_differs(RoutingSettings(proxy_list=["p"]), reset_routing(current))


def test_reset_rows_describe_the_provider_request():
    from src.ui.logic.routing_import import reset_rows

    rows = reset_rows(RoutingSettings(proxy_list=["p"]), subscription="Мой VPN")
    assert rows[0] == ImportRow("Подписка", "Мой VPN")
    assert any(r.label == "Через прокси" and r.value.startswith("0 правил: +0, −1") for r in rows)
    assert rows[-1].label == "Не переносится"
```

В `tests/test_db_profiles.py`: `ProfileGroup(sub_routing_handled="abc")` переживает `to_dict`/`from_dict` (посмотреть соседний тест про `sub_fallback_url` и повторить его).

**Шаг 2: убедиться, что падают**

Run: `uv run pytest tests/test_ui_logic_routing_import.py tests/test_db_profiles.py -q`
Expected: FAIL

**Шаг 3: реализация**

`src/db/profiles.py`, `ProfileGroup`:

```python
    # SHA-256 последнего набора маршрутов из заголовка `routing`, который
    # пользователь принял или отклонил: тот же набор повторно не предлагается.
    sub_routing_handled: str = ""
```

`src/ui/logic/routing_import.py`:

- `import_rows(..., subscription: str = "")`: если `subscription`, первой строкой `ImportRow("Подписка", subscription)`;
- добавить:

```python
SUBSCRIPTION_LABEL = "Подписка"
# `routing/off`: провайдер просит вернуть стандартные списки. Списки «Через VPN»,
# порядок и готовые правила — настройки устройства, их сброс не трогает.
RESET_FIELDS = ("mode", "proxy_list", "direct_list", "block_list")


def reset_routing(current: RoutingSettings) -> RoutingSettings:
    """Общие правила после `routing/off`; `current` не меняется."""
    result = copy.deepcopy(current)
    defaults = RoutingSettings()
    for name in RESET_FIELDS:
        setattr(result, name, copy.deepcopy(getattr(defaults, name)))
    return result


def routing_differs(before: RoutingSettings, after: RoutingSettings) -> bool:
    return any(getattr(before, name) != getattr(after, name) for name in RESET_FIELDS)


def reset_rows(before: RoutingSettings, *, subscription: str) -> list[ImportRow]:
    rows = import_rows(before, reset_routing(before), name="", direct_default=False,
                       subscription=subscription)
    return rows
```

(`import_rows` для сброса даёт строки «Режим» при смене, три списка с «−N», «Остальное: через прокси», «Не переносится» — этого достаточно; заголовок окна для сброса задаёт контроллер через `rows`, см. задачу 16).

**Шаг 4: тесты проходят**

Run: `uv run pytest tests/test_ui_logic_routing_import.py tests/test_db_profiles.py -q`
Expected: PASS

**Шаг 5: коммит**

```bash
git add src/ui/logic/routing_import.py src/db/profiles.py tests/
git commit -m "routing: строки окна и сброс для набора из подписки"
```

### Задача 16: контроллер предлагает набор из подписки

**Файлы:**
- Изменить: `src/ui/controller.py` (`Shell.open_routing_import`, `_update_one_group` ≈ 685-704, `_offer_url_change` → общая очередь, новые методы), `src/ui/application.py:157-160`, `src/ui/qt/application.py:153-157`, `src/ui/dialogs/routing_import.py`, `src/ui/qt/dialogs/routing_import.py` (параметр `on_dismiss`)
- Тест: `tests/test_ui_controller.py`

**Шаг 1: падающие тесты**

В `FakeShell.open_routing_import(self, rows, on_confirm, on_dismiss=None)` сохранять `("routing-import", rows, on_confirm, on_dismiss)`. Тесты:

```python
# --- набор маршрутов из подписки ---

ROUTING_PAYLOAD = base64.urlsafe_b64encode(json.dumps({"ProxySites": ["x.com"]}).encode()).decode()


def _subscription(controller, link: str, *, new_url: str = ""):
    """Подписка, чьё обновление приносит заголовок routing (и, возможно, new-url).

    Обновление идёт в фоновом потоке: после каждого `update_subscription`
    нужен `_wait_subscriptions(controller)`, как в соседних тестах.
    """
    from src.ui.controller import UpdateOutcome

    outcome = {"link": link, "new_url": new_url}
    controller.set_subscription_updater(
        lambda _gid, _url: UpdateOutcome(1, new_url=outcome["new_url"], routing_link=outcome["link"])
    )
    group = controller.add_subscription("Мой VPN", "https://sub.example/a")
    _wait_subscriptions(controller)
    return group.id, outcome


def _routing_forms(shell):
    return [form for form in shell.forms if form[0] == "routing-import"]


def test_subscription_routing_header_opens_the_import_window(made):
    controller, shell, _loop = made
    group_id, _outcome = _subscription(controller, ROUTING_PAYLOAD)

    kind, rows, on_confirm, _on_dismiss = _routing_forms(shell)[-1]
    assert rows[0].label == "Подписка" and rows[0].value == "Мой VPN"
    on_confirm()
    assert controller.context.config.routing.proxy_list == ["x.com"]
    assert controller.context.config.routing_backup is not None
    assert controller.context.profiles.get_group(group_id).sub_routing_handled


def test_the_same_header_is_not_offered_twice(made):
    controller, shell, _loop = made
    group_id, _outcome = _subscription(controller, ROUTING_PAYLOAD)
    _routing_forms(shell)[-1][3]()  # закрыть без применения
    shown = len(_routing_forms(shell))

    controller.update_subscription(group_id)
    _wait_subscriptions(controller)

    assert len(_routing_forms(shell)) == shown


def test_a_new_payload_is_offered_again(made):
    controller, shell, _loop = made
    group_id, outcome = _subscription(controller, ROUTING_PAYLOAD)
    _routing_forms(shell)[-1][2]()
    outcome["link"] = base64.urlsafe_b64encode(
        json.dumps({"ProxySites": ["y.com"]}).encode()
    ).decode()

    controller.update_subscription(group_id)
    _wait_subscriptions(controller)

    assert len(_routing_forms(shell)) == 2


def test_routing_off_is_offered_only_when_something_would_change(made):
    controller, shell, _loop = made
    group_id, _outcome = _subscription(controller, "happ://routing/off")
    assert not _routing_forms(shell)
    # Нечего возвращать — заголовок считается обработанным.
    assert controller.context.profiles.get_group(group_id).sub_routing_handled

    controller.context.config.routing.proxy_list = ["p.com"]
    controller.context.config.routing.use_saved_lists = True
    controller.context.profiles.get_group(group_id).sub_routing_handled = ""
    controller.update_subscription(group_id)
    _wait_subscriptions(controller)

    _kind, _rows, on_confirm, _dismiss = _routing_forms(shell)[-1]
    on_confirm()
    assert controller.context.config.routing.proxy_list == []
    assert controller.context.config.routing_backup.proxy_list == ["p.com"]


def test_without_a_window_the_offer_waits_for_the_next_update(made):
    controller, shell, _loop = made
    shell.window = False
    group_id, _outcome = _subscription(controller, ROUTING_PAYLOAD)
    assert not _routing_forms(shell)
    assert not controller.context.profiles.get_group(group_id).sub_routing_handled

    shell.window = True
    controller.update_subscription(group_id)
    _wait_subscriptions(controller)
    assert _routing_forms(shell)


def test_address_change_is_offered_before_routing(made):
    controller, shell, _loop = made
    group_id, outcome = _subscription(controller, ROUTING_PAYLOAD, new_url="https://new.example/b")

    assert shell.confirms[-1].kind == CONFIRM_URL_CHANGE
    assert not _routing_forms(shell)

    outcome["new_url"] = ""
    controller.update_subscription(group_id)
    _wait_subscriptions(controller)
    assert _routing_forms(shell)
```

Добавить `import base64, json` и импорт `CONFIRM_URL_CHANGE` в тест (если его ещё нет).

**Шаг 2: убедиться, что падают**

Run: `uv run pytest tests/test_ui_controller.py -q -k "routing or header or payload or window_the_offer"`
Expected: FAIL

**Шаг 3: реализация**

`src/ui/controller.py`:

1. Результат обновления одной группы:

```python
@dataclass(frozen=True)
class UpdateOutcome:
    count: int
    new_url: str = ""
    fallback_used: str = ""
    routing_link: str = ""
```

`default_subscription_updater` (сейчас возвращает `len(beans)`) возвращает `UpdateOutcome(len(beans), updater.new_url, updater.used_fallback_url, updater.routing_link)`. В `work()` обеих веток (`update_subscription`, `refresh_subscriptions`): `outcome = updater(group_id, url)`; если `isinstance(outcome, int)` — `outcome = UpdateOutcome(outcome)`; `total += outcome.count`; предложения адреса строятся из `outcome.new_url`/`outcome.fallback_used`; и:

```python
                if outcome.routing_link:
                    self._propose_routing(group_id, outcome.routing_link)
```

2. Очередь предложений: `self._routing_proposals: list[tuple[int, AppLink]] = []`.

```python
    def _propose_routing(self, group_id: int, raw: str) -> None:
        """Запомнить набор маршрутов из заголовка; показ — в главном потоке."""
        from src.fmt.app_links import parse_subscription_routing

        try:
            link = parse_subscription_routing(raw)
        except ValueError as error:
            logger.warning("Subscription %s routing header rejected: %s", group_id, error)
            return
        group = self.context.profiles.get_group(group_id)
        if group is None or group.sub_routing_handled == link.payload_hash:
            return
        self._routing_proposals.append((group_id, link))
```

3. `_offer_url_change` переименовать в `_offer_proposals`: сначала адрес (как сейчас), и только если адресных предложений не было — маршрутизация:

```python
    def _offer_proposals(self) -> None:
        if self._url_proposals:
            self._offer_url_change()
            self._routing_proposals.clear()  # вернётся со следующим обновлением
            return
        self._offer_routing()

    def _offer_routing(self) -> None:
        if not self._routing_proposals:
            return
        group_id, link = self._routing_proposals[0]
        self._routing_proposals.clear()
        group = self.context.profiles.get_group(group_id)
        if group is None or not self._shell.has_window():
            return
        from src.ui.logic.routing_import import (
            effective_routing, import_rows, reset_rows, reset_routing, routing_differs,
        )

        config, config_dir = self.context.config, self.context.config_dir
        current = effective_routing(config.routing, config_dir)
        if link.operation == "routing_off":
            target = reset_routing(current)
            if not routing_differs(current, target):
                # Провайдер шлёт off на каждое обновление; возвращать нечего — не спрашиваем.
                self._mark_routing_handled(group_id, link.payload_hash)
                return
            rows = reset_rows(current, subscription=group.name)
        else:
            target = link.routing
            rows = import_rows(current, target, name=link.name,
                               direct_default=link.direct_default, subscription=group.name)

        def confirm() -> None:
            self.apply_routing_import(target)
            self._mark_routing_handled(group_id, link.payload_hash)

        self._shell.open_routing_import(
            rows, confirm, on_dismiss=lambda: self._mark_routing_handled(group_id, link.payload_hash)
        )

    def _mark_routing_handled(self, group_id: int, payload_hash: str) -> None:
        group = self.context.profiles.get_group(group_id)
        if group is None:
            return
        group.sub_routing_handled = payload_hash
        try:
            self.context.save_profiles()
        except Exception as error:
            logger.warning("Could not persist routing mark: %s", error)
```

`_on_subscriptions_updated` и `_on_subscriptions_failed` зовут `_offer_proposals()`.

4. `Shell.open_routing_import(self, rows, on_confirm, on_dismiss=None)`. Для `apply_routing_import` при сбросе: `apply_import(config, new, config_dir)` берёт из `new` только `mode` и три списка — ровно `RESET_FIELDS`, поэтому `reset_routing(current)` подходит как `new` без изменений в `apply_import`.

`src/ui/dialogs/routing_import.py`: `__init__(self, rows, on_confirm, on_dismiss=None)`; в обработчике `response`: `on_confirm()` при `IMPORT`, иначе `on_dismiss()` если задан. `src/ui/application.py:157`: прокинуть `on_dismiss`. `src/ui/qt/dialogs/routing_import.py`: `self.rejected.connect(on_dismiss)` при наличии; `src/ui/qt/application.py:153`: прокинуть.

**Шаг 4: тесты проходят**

Run: `uv run pytest tests/test_ui_controller.py -q`, затем `make test-gtk ARGS="-k routing_import"` и `make test-qt ARGS="-k routing_import"` (если есть тесты окон импорта — `grep -rln RoutingImportDialog tests/`).
Expected: PASS

**Шаг 5: коммит**

```bash
git add src/ui/controller.py src/ui/application.py src/ui/qt/application.py src/ui/dialogs/routing_import.py src/ui/qt/dialogs/routing_import.py tests/test_ui_controller.py
git commit -m "ui: предлагать набор маршрутов из заголовка подписки"
```

### Задача 17: текст окна импорта про место отката

**Файлы:**
- Изменить: `src/ui/dialogs/routing_import.py:27-30`, `src/ui/qt/dialogs/routing_import.py` (`BODY`)

Тело окна говорит «Вернуть их можно в настройках: «О приложении» → «Обслуживание»». Теперь строка живёт на странице «Маршрутизация»: заменить на «Вернуть их можно в настройках: «Маршрутизация» → «Дополнительно»» в обоих тулкитах. Проверить тестами окон (`grep -rn "Обслуживание" tests/`), прогнать `make test-gtk ARGS="-k import"`, `make test-qt ARGS="-k import"`.

```bash
git add src/ui/dialogs/routing_import.py src/ui/qt/dialogs/routing_import.py tests/
git commit -m "ui: окно импорта указывает на страницу «Маршрутизация»"
```

---

## Этап 5. Документация

### Задача 18: документы

**Файлы:**
- Изменить: `docs/ru/routing.md` (раздел «Настройка в GUI»; новый раздел «Набор маршрутов из подписки»), `docs/ru/gui.md` (список страниц настроек), `docs/plans/2026-11-02-shared-ui-design.md:218` (список страниц), `docs/plans/2026-10-28-routing-import-parity.md:23-26, 753` (пометка «снято дизайном 2026-11-07»), `CLAUDE.md` (абзац в Architecture)

`docs/ru/routing.md`, «Настройка в GUI» заменить на:

```markdown
## Настройка в GUI

**Общие правила** — «Настройки → Маршрутизация»: режим, приоритет групп, готовые
правила и четыре списка. Действуют для всех серверов, у которых нет своих правил.
Там же строка «Маршрутизация до импорта» → «Вернуть», если был импорт.

**Свои правила сервера** — «VPN и маршруты…» в меню сервера, переключатель
«Свои правила маршрутизации». Выключен — сервер использует общие. При включении
форма начинается с копии общих правил; дальше правка общих на этот сервер не
влияет. Выключение возвращает сервер к общим, его собственные списки не хранятся.

На странице мониторинга строка «Правила» показывает, что применено: «Общие» или
«Сервера».

## Набор маршрутов из подписки

Провайдер может передать набор маршрутов заголовком ответа `routing` (ссылка
`happ://routing/add/…`, `veblock://routing/add/…` или base64 того же JSON). После
обновления подписки Veblock показывает то же окно, что при открытии ссылки
вручную: что меняется в списках, что не переносится. Ничего не применяется без
кнопки «Импортировать». Отклонённый или принятый набор повторно не предлагается,
пока провайдер не пришлёт другой. `happ://routing/off` предлагает вернуть
стандартные списки, если текущие от них отличаются. Серверы со своими правилами
заголовок не затрагивает.
```

`CLAUDE.md`, после абзаца про `ProfileStore`:

```markdown
**Маршрутизация** - общие правила в `DataStore.routing` (страница настроек
«Маршрутизация», общий виджет `src/ui/widgets/routing_form.py` и
`src/ui/qt/widgets/routing_form.py`, значения — `src/ui/logic/routing_form.py`);
`ProfileEntry.routing_settings is None` означает «сервер использует общие»,
объект — свои правила целиком. Заголовок `routing` подписки читается как
предложение и проходит через то же окно импорта с подтверждением; хеш
обработанного набора — `ProfileGroup.sub_routing_handled`.
```

```bash
git add docs CLAUDE.md
git commit -m "docs: общая маршрутизация и набор маршрутов из подписки"
```

### Задача 19: финальная проверка

1. `python cli.py lint-all` — чисто.
2. `uv run pytest -q` — все обычные тесты.
3. `make test-gtk`, `make test-qt`.
4. Руками в GTK и Qt: страница «Маршрутизация», переключатель в диалоге сервера, импорт ссылкой при открытых настройках обновляет строку «Вернуть», подписка с заголовком `routing` показывает окно один раз.
5. `tests/test_branding.py` проходит: в новых текстах нет «Tenga Proxy».

Не делать в этом плане: автоприменение `onadd`, бейдж отложенного предложения, per-app, «через другой профиль», перенос строки геобаз (см. «За рамками» дизайна).
