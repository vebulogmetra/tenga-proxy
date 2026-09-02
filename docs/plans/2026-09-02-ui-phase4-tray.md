# Этап 4. Трей StatusNotifierItem — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Контекст: `docs/plans/2026-09-02-ui-redesign-design.md` (раздел «Трей»), `docs/plans/2026-09-02-ui-redesign-plan.md` (этап 4).
> Предыдущий этап: `docs/plans/2026-09-02-ui-phase3-dialogs.md`.

**Goal:** Дать GTK4-интерфейсу собственную иконку в системном трее с рабочим меню — без библиотеки AppIndicator3, поверх `Gio.DBusConnection`.

**Architecture:** Три слоя. `dbusmenu.py` — чистое Python-дерево пунктов меню и его сериализация в варианты `com.canonical.dbusmenu` (тестируется без D-Bus и без дисплея). `sni.py` — экспорт объектов `org.kde.StatusNotifierItem` и `com.canonical.dbusmenu` на шине сессии плюс регистрация у watcher с переподключением (тестируется на приватной шине `Gio.TestDBus`). `tray.py` — `TrayController`, который подписывается на `proxy_state`, пересобирает меню и вызывает те же `Gio.Action`, что окно и клавиатура. Отсутствие watcher — не ошибка: приложение работает без трея.

**Tech Stack:** Python 3.11, PyGObject, `Gio.DBusConnection`, `GLib.Variant`, `Gio.TestDBus`, pytest, ruff, uv.

---

## Уточнения после разведки кода

Проверено на живой системе и в коде до написания плана. Эти находки меняют
детали, описанные в общем плане этапа 4.

1. **Watcher в целевом окружении есть.** `org.kde.StatusNotifierWatcher`
   присутствует на шине сессии (GNOME + расширение AppIndicator),
   `IsStatusNotifierHostRegistered = true`. Значит трей проверяется не только на
   приватной шине, но и вживую.

2. **Формат `GetLayout` подтверждён на работающем приложении пользователя.**
   Ответ имеет сигнатуру `(u(ia{sv}av))`; разделители задаются свойством
   `type: "separator"`, подменю — `children-display: "submenu"`. Реальный ответ
   GTK3-версии:
   ```
   (uint32 14, (0, {'children-display': <'submenu'>}, [
     <(2, {'enabled': <false>, 'label': <'Статус: …'>}, @av [])>,
     <(3, {'enabled': <true>, 'type': <'separator'>}, @av [])>,
     <(4, {'label': <'Отключить'>}, @av [])>, …]))
   ```
   Плановое дерево обязано давать ту же форму.

3. **`GLib.Variant` не собирает вложенные узлы из кортежей.** Ни
   `GLib.Variant("(ia{sv}av)", (...))` с кортежами внутри `av`, ни
   `GLib.Variant("v", other_variant)` не работают — оверрайд PyGObject падает с
   `TypeError: Expected GLib.Variant, but got tuple/str`. Рабочий путь —
   `GLib.VariantBuilder` плюс `GLib.Variant.new_variant(child)` на каждый
   вложенный узел. Проверено экспериментально, итог совпадает с образцом из п. 2.

4. **`call_sync` из теста в собственный экспортированный объект зависает.**
   Сервер обслуживается главным циклом того же потока, а `call_sync` этот поток
   блокирует — вызов упирается в таймаут даже с двух разных соединений.
   В тестах нужен асинхронный `conn.call(...)` с прокруткой
   `GLib.MainContext.iteration(True)` до готовности результата. Помощник
   выносится в фикстуру `dbus_call` (задача 4.3).

5. **Интерфейс dbusmenu версии 3** требует свойств `Version` (u), `TextDirection`
   (s), `Status` (s), `IconThemePath` (as) — иначе панель считает объект
   неполным.

6. **Иконок трея в проекте нет.** В `assets/` только `tenga-proxy.png`,
   `tray.png`, `tenga-proxy.svg`. GTK3-версия кладёт один и тот же файл в три
   константы `ICON_DISCONNECTED/CONNECTED/CONNECTING` (`src/ui/tray.py:37-39`) —
   это и есть дефект B17. Нужны три реальных SVG плюс `IconThemePath`,
   указывающий на каталог с ними, потому что имена вне системной темы иначе не
   разрешаются.

7. **Имя на шине должно быть уникальным.** Спецификация требует
   `org.kde.StatusNotifierItem-<pid>-<nr>`. Одинаковое имя у GTK3- и
   GTK4-версии привело бы к тому, что вторая не смогла бы его занять, а у
   пользователя сейчас работает GTK3-версия.

8. **`ProxyState` даёт `is_running` и `started_profile_id`,** а промежуточного
   «подключается» в нём нет (`src/core/context.py:19-64`). Оно приходит из
   `ConnectionState` в `src/ui/logic/status.py`. Трей получает состояние тем же
   способом, что статус-карточка: `TrayController.set_state(...)`.

9. **Список профилей берётся из всего хранилища, а не из текущей группы.**
   GTK3-трей показывает `get_current_group_profiles()`, но в GTK4-интерфейсе
   понятия «текущая группа» уже нет — страница профилей показывает дерево целиком.
   Меню строится из `context.profiles.profiles`, ограничение — 20 пунктов.

10. **Действия приложения уже зарегистрированы** в `src/ui/application.py:94-119`:
    `connect`, `disconnect`, `toggle-connection`, `add-profile`, `settings`,
    `quit` и другие. Трей не заводит собственных обработчиков, а активирует
    существующие действия по имени — иначе поведение окна и трея разъедется.

11. **Флаг `--no-tray` в `gui.py:37` разбирается, но нигде не используется.**
    Этап 4 даёт ему смысл в GTK4-ветке.

12. **`GLib.idle_add` обязателен для смены состояния.** `proxy_state` уведомляет
    слушателей из фонового потока подключения (`src/core/connection.py`), а
    отправка сигналов D-Bus должна идти из главного цикла — как это сделано в
    `src/ui/tray.py:150-152`.

---

## Ограничения этапа

- **Подключение и отключение не проверяются вживую.** У пользователя работает
  установленная в систему GTK3-версия; её нельзя закрывать, а запуск второго
  ядра сломал бы ей маршруты. Меню трея проверяется на пунктах, не трогающих
  соединение (открыть окно, настройки, список профилей), плюс на фиктивном
  сервисе подключения в тестах.
- **GTK3-трей (`src/ui/tray.py`) не трогаем.** Он удаляется на этапе 5 вместе с
  остальным GTK3-кодом.
- **Уведомления (`Notify`) в этот этап не входят.** GTK4 даёт
  `Gio.Notification` через `Gio.Application.send_notification`; это отдельный
  вопрос, к трею не относящийся.

---

## Task 4.1: Дерево пунктов меню

**Files:**
- Create: `src/ui/tray/__init__.py`
- Create: `src/ui/tray/dbusmenu.py`
- Test: `tests/test_ui_tray_dbusmenu.py`

Чистый Python: ни GTK, ни D-Bus. Дерево пунктов, присвоение идентификаторов и
словари свойств в том виде, в каком их ждёт `com.canonical.dbusmenu`.

**Step 1: Write the failing test**

```python
# tests/test_ui_tray_dbusmenu.py
"""Дерево пунктов меню трея: идентификаторы, свойства, поиск по id."""

from __future__ import annotations

import pytest

from src.ui.tray.dbusmenu import MenuItem, MenuModel, separator


def test_root_children_get_sequential_ids():
    model = MenuModel([MenuItem("Первый"), MenuItem("Второй")])

    assert [item.id for item in model.root.children] == [1, 2]


def test_root_itself_has_id_zero():
    model = MenuModel([MenuItem("Первый")])

    assert model.root.id == 0


def test_nested_items_continue_the_same_numbering():
    model = MenuModel(
        [
            MenuItem("Профили", children=[MenuItem("A"), MenuItem("B")]),
            MenuItem("Выход"),
        ]
    )
    profiles = model.root.children[0]

    assert profiles.id == 1
    assert [item.id for item in profiles.children] == [2, 3]
    assert model.root.children[1].id == 4


def test_properties_of_a_plain_item():
    model = MenuModel([MenuItem("Подключить")])

    assert model.properties(1) == {"label": "Подключить", "enabled": True, "visible": True}


def test_a_disabled_item_reports_enabled_false():
    model = MenuModel([MenuItem("Статус: Отключено", enabled=False)])

    assert model.properties(1)["enabled"] is False


def test_a_separator_carries_the_type_property():
    model = MenuModel([separator()])

    assert model.properties(1) == {"type": "separator", "enabled": True, "visible": True}


def test_a_parent_declares_a_submenu():
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A")])])

    assert model.properties(1)["children-display"] == "submenu"


def test_a_checked_item_reports_a_radio_toggle():
    model = MenuModel([MenuItem("Профиль", checked=True)])
    props = model.properties(1)

    assert props["toggle-type"] == "radio"
    assert props["toggle-state"] == 1


def test_an_unchecked_toggle_reports_state_zero():
    model = MenuModel([MenuItem("Профиль", checked=False)])

    # checked=False — это «переключатель, который выключен», а не «пункт без
    # переключателя»: у второго checked=None.
    assert model.properties(1)["toggle-state"] == 0


def test_an_item_without_a_toggle_has_no_toggle_properties():
    props = MenuModel([MenuItem("Выход")]).properties(1)

    assert "toggle-type" not in props
    assert "toggle-state" not in props


def test_an_icon_name_is_reported_when_given():
    model = MenuModel([MenuItem("Настройки", icon_name="preferences-system-symbolic")])

    assert model.properties(1)["icon-name"] == "preferences-system-symbolic"


def test_properties_of_an_unknown_id_are_empty():
    assert MenuModel([MenuItem("Один")]).properties(99) == {}


def test_find_returns_the_item_with_that_id():
    child = MenuItem("Вложенный")
    model = MenuModel([MenuItem("Родитель", children=[child])])

    assert model.find(2) is child


def test_find_returns_none_for_an_unknown_id():
    assert MenuModel([MenuItem("Один")]).find(42) is None


def test_the_action_of_an_item_is_kept():
    model = MenuModel([MenuItem("Выход", action="app.quit")])

    assert model.find(1).action == "app.quit"


def test_the_target_of_an_item_is_kept():
    model = MenuModel([MenuItem("Профиль", action="app.select-profile", target=17)])

    assert model.find(1).target == 17


def test_layout_lists_the_children_of_the_requested_parent():
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A")]), MenuItem("Выход")])

    root_id, root_props, children = model.layout(0)

    assert root_id == 0
    assert root_props["children-display"] == "submenu"
    assert [child[0] for child in children] == [1, 2]


def test_layout_of_a_leaf_has_no_children():
    model = MenuModel([MenuItem("Выход")])

    _id, _props, children = model.layout(1)

    assert children == []


def test_layout_depth_one_stops_before_grandchildren():
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A")])])

    _id, _props, children = model.layout(0, depth=1)
    _child_id, _child_props, grandchildren = children[0]

    # Глубина 1 — только прямые потомки: панель запрашивает подменю отдельно.
    assert grandchildren == []


def test_layout_depth_minus_one_returns_the_whole_tree():
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A")])])

    _id, _props, children = model.layout(0, depth=-1)
    _child_id, _child_props, grandchildren = children[0]

    assert [item[0] for item in grandchildren] == [2]


def test_layout_of_an_unknown_parent_is_none():
    assert MenuModel([MenuItem("Один")]).layout(99) is None


def test_group_properties_returns_a_pair_per_requested_id():
    model = MenuModel([MenuItem("Первый"), MenuItem("Второй")])

    result = model.group_properties([1, 2])

    assert [item_id for item_id, _props in result] == [1, 2]
    assert result[0][1]["label"] == "Первый"


def test_group_properties_with_no_ids_returns_every_item():
    model = MenuModel([MenuItem("Первый"), MenuItem("Второй")])

    # Пустой список означает «все пункты» — так его толкует спецификация.
    assert len(model.group_properties([])) == 3  # корень и два пункта


def test_group_properties_filters_by_the_requested_names():
    model = MenuModel([MenuItem("Первый")])

    result = model.group_properties([1], names=["label"])

    assert result[0][1] == {"label": "Первый"}


def test_group_properties_skips_unknown_ids():
    model = MenuModel([MenuItem("Первый")])

    assert model.group_properties([1, 99]) == [(1, model.properties(1))]


def test_a_hidden_item_reports_visible_false():
    model = MenuModel([MenuItem("Скрытый", visible=False)])

    assert model.properties(1)["visible"] is False


@pytest.mark.parametrize("depth", [0, 1, 5, -1])
def test_layout_never_raises_for_any_depth(depth):
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A")])])

    assert model.layout(0, depth=depth) is not None
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_tray_dbusmenu.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ui.tray'`

**Step 3: Write minimal implementation**

```python
# src/ui/tray/__init__.py
"""System tray over StatusNotifierItem."""
```

```python
# src/ui/tray/dbusmenu.py
"""Menu tree for com.canonical.dbusmenu.

Модуль не импортирует ни GTK, ни Gio: дерево и его свойства — обычные Python-
объекты, поэтому проверяются без шины и без дисплея. Превращением в
`GLib.Variant` занимается `sni.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Идентификатор корня зафиксирован спецификацией: панель всегда запрашивает
# раскладку начиная с нуля.
ROOT_ID = 0


@dataclass
class MenuItem:
    """One entry of the tray menu."""

    label: str = ""
    action: str = ""
    target: int | None = None
    enabled: bool = True
    visible: bool = True
    checked: bool | None = None
    icon_name: str = ""
    is_separator: bool = False
    children: list[MenuItem] = field(default_factory=list)
    id: int = -1


def separator() -> MenuItem:
    """A horizontal rule between groups of entries."""
    return MenuItem(is_separator=True)


class MenuModel:
    """A tree of `MenuItem` addressed by the integer ids dbusmenu uses."""

    def __init__(self, items: list[MenuItem]) -> None:
        self.root = MenuItem(children=list(items), id=ROOT_ID)
        self._by_id: dict[int, MenuItem] = {ROOT_ID: self.root}
        self._number(self.root.children, start=ROOT_ID + 1)

    def _number(self, items: list[MenuItem], start: int) -> int:
        """Give every item a unique id, depth first."""
        next_id = start
        for item in items:
            item.id = next_id
            self._by_id[next_id] = item
            next_id = self._number(item.children, next_id + 1)
        return next_id

    def find(self, item_id: int) -> MenuItem | None:
        """Return the item with that id, or None."""
        return self._by_id.get(item_id)

    def properties(self, item_id: int) -> dict:
        """Describe one item the way dbusmenu expects it."""
        item = self._by_id.get(item_id)
        if item is None:
            return {}

        props: dict = {"enabled": item.enabled, "visible": item.visible}

        if item.is_separator:
            props["type"] = "separator"
            return props

        props["label"] = item.label

        if item.children:
            props["children-display"] = "submenu"

        if item.checked is not None:
            # radio, а не checkmark: активен ровно один профиль, и панель
            # рисует такой набор как переключатель с единственным выбором.
            props["toggle-type"] = "radio"
            props["toggle-state"] = 1 if item.checked else 0

        if item.icon_name:
            props["icon-name"] = item.icon_name

        return props

    def layout(self, parent_id: int, depth: int = -1) -> tuple | None:
        """Build the nested (id, props, children) triple for one subtree."""
        item = self._by_id.get(parent_id)
        if item is None:
            return None
        return self._layout_of(item, depth)

    def _layout_of(self, item: MenuItem, depth: int) -> tuple:
        if depth == 0:
            children: list = []
        else:
            children = [self._layout_of(child, depth - 1) for child in item.children]
        return (item.id, self.properties(item.id), children)

    def group_properties(self, ids: list[int], names: list[str] | None = None) -> list[tuple]:
        """Return (id, props) for the requested ids; an empty list means all."""
        wanted = ids or list(self._by_id)
        result = []
        for item_id in wanted:
            if item_id not in self._by_id:
                continue
            props = self.properties(item_id)
            if names:
                props = {k: v for k, v in props.items() if k in names}
            result.append((item_id, props))
        return result
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_tray_dbusmenu.py -q`
Expected: 26 passed

**Step 5: Lint and commit**

```bash
uv run ruff check src/ui/tray tests/test_ui_tray_dbusmenu.py
uv run ruff format src/ui/tray tests/test_ui_tray_dbusmenu.py
git add src/ui/tray tests/test_ui_tray_dbusmenu.py
git commit -m "feat: add the tray menu tree and its dbusmenu properties"
```

---

## Task 4.2: Сборка вариантов D-Bus

**Files:**
- Create: `src/ui/tray/variants.py`
- Test: `tests/test_ui_tray_variants.py`

Отдельный модуль, потому что здесь начинается `GLib`, и потому что сборка
рекурсивного `av` — самое хрупкое место этапа (находка 3).

**Step 1: Write the failing test**

```python
# tests/test_ui_tray_variants.py
"""Перевод дерева меню в варианты D-Bus."""

from __future__ import annotations

from gi.repository import GLib

from src.ui.tray.dbusmenu import MenuItem, MenuModel, separator
from src.ui.tray.variants import layout_variant, pack_properties, properties_variant


def test_a_string_property_becomes_a_string_variant():
    packed = pack_properties({"label": "Выход"})

    assert packed["label"].get_type_string() == "s"
    assert packed["label"].get_string() == "Выход"


def test_a_boolean_property_becomes_a_boolean_variant():
    packed = pack_properties({"enabled": False})

    assert packed["enabled"].get_type_string() == "b"
    assert packed["enabled"].get_boolean() is False


def test_an_integer_property_becomes_an_int32_variant():
    packed = pack_properties({"toggle-state": 1})

    assert packed["toggle-state"].get_type_string() == "i"


def test_layout_variant_has_the_signature_the_panel_expects():
    model = MenuModel([MenuItem("Выход")])

    variant = layout_variant(model, 0, revision=7)

    # Ровно та сигнатура, что отдаёт работающее приложение: (u(ia{sv}av)).
    assert variant.get_type_string() == "(u(ia{sv}av))"


def test_layout_variant_carries_the_revision():
    model = MenuModel([MenuItem("Выход")])

    assert layout_variant(model, 0, revision=7).unpack()[0] == 7


def test_layout_variant_unpacks_to_the_expected_tree():
    model = MenuModel([MenuItem("Подключить"), separator(), MenuItem("Выход")])

    _revision, root = layout_variant(model, 0, revision=1).unpack()
    root_id, root_props, children = root

    assert root_id == 0
    assert root_props["children-display"] == "submenu"
    assert [child[1].get("label", "") for child in children] == ["Подключить", "", "Выход"]
    assert children[1][1]["type"] == "separator"


def test_layout_variant_nests_submenus():
    model = MenuModel([MenuItem("Профили", children=[MenuItem("A"), MenuItem("B")])])

    _revision, root = layout_variant(model, 0, revision=1).unpack()
    _child_id, _child_props, grandchildren = root[2][0]

    assert [item[1]["label"] for item in grandchildren] == ["A", "B"]


def test_layout_variant_of_an_unknown_parent_is_an_empty_tree():
    model = MenuModel([MenuItem("Выход")])

    _revision, root = layout_variant(model, 99, revision=1).unpack()

    # Панель не должна получить ошибку за несуществующий узел — ей отдаётся
    # пустое поддерево с тем же идентификатором.
    assert root == (99, {}, [])


def test_properties_variant_has_the_group_signature():
    model = MenuModel([MenuItem("Первый"), MenuItem("Второй")])

    variant = properties_variant(model, [1, 2], [])

    assert variant.get_type_string() == "(a(ia{sv}))"


def test_properties_variant_unpacks_to_id_and_properties():
    model = MenuModel([MenuItem("Первый")])

    (pairs,) = properties_variant(model, [1], []).unpack()

    assert pairs == [(1, {"enabled": True, "visible": True, "label": "Первый"})]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_tray_variants.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ui.tray.variants'`

**Step 3: Write minimal implementation**

```python
# src/ui/tray/variants.py
"""Turn the menu tree into the GLib variants dbusmenu speaks.

Вынесено из `sni.py`: сборка рекурсивного `av` требует `VariantBuilder` и
`new_variant` на каждом уровне — оверрайд PyGObject не умеет собирать такой тип
из вложенных кортежей. Отдельный модуль позволяет проверить форму без шины.
"""

from __future__ import annotations

from gi.repository import GLib

from src.ui.tray.dbusmenu import MenuModel

ITEM_TYPE = GLib.VariantType.new("(ia{sv}av)")
AV_TYPE = GLib.VariantType.new("av")
LAYOUT_TYPE = GLib.VariantType.new("(u(ia{sv}av))")
GROUP_TYPE = GLib.VariantType.new("(a(ia{sv}))")


def pack_properties(props: dict) -> dict:
    """Wrap plain Python values into the variants a{sv} needs."""
    packed = {}
    for key, value in props.items():
        if isinstance(value, bool):
            packed[key] = GLib.Variant("b", value)
        elif isinstance(value, int):
            packed[key] = GLib.Variant("i", value)
        else:
            packed[key] = GLib.Variant("s", str(value))
    return packed


def _item_variant(node: tuple) -> GLib.Variant:
    """Build one (ia{sv}av) node, recursing into its children."""
    item_id, props, children = node

    builder = GLib.VariantBuilder.new(ITEM_TYPE)
    builder.add_value(GLib.Variant("i", item_id))
    builder.add_value(GLib.Variant("a{sv}", pack_properties(props)))

    kids = GLib.VariantBuilder.new(AV_TYPE)
    for child in children:
        # new_variant, а не GLib.Variant("v", …): второй вариант в PyGObject
        # принимает только простые значения и падает на готовом Variant.
        kids.add_value(GLib.Variant.new_variant(_item_variant(child)))
    builder.add_value(kids.end())

    return builder.end()


def layout_variant(model: MenuModel, parent_id: int, revision: int, depth: int = -1):
    """Build the reply of com.canonical.dbusmenu.GetLayout."""
    node = model.layout(parent_id, depth=depth)
    if node is None:
        node = (parent_id, {}, [])

    builder = GLib.VariantBuilder.new(LAYOUT_TYPE)
    builder.add_value(GLib.Variant("u", revision))
    builder.add_value(_item_variant(node))
    return builder.end()


def properties_variant(model: MenuModel, ids: list[int], names: list[str]):
    """Build the reply of com.canonical.dbusmenu.GetGroupProperties."""
    pairs = [
        GLib.Variant("(ia{sv})", (item_id, pack_properties(props)))
        for item_id, props in model.group_properties(ids, names)
    ]

    builder = GLib.VariantBuilder.new(GROUP_TYPE)
    builder.add_value(GLib.Variant("a(ia{sv})", pairs))
    return builder.end()
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_tray_variants.py -q`
Expected: 10 passed

**Step 5: Lint and commit**

```bash
uv run ruff check src/ui/tray tests/test_ui_tray_variants.py
uv run ruff format src/ui/tray tests/test_ui_tray_variants.py
git add src/ui/tray/variants.py tests/test_ui_tray_variants.py
git commit -m "feat: serialise the tray menu into dbusmenu variants"
```

---

## Task 4.3: Фикстура приватной шины

**Files:**
- Modify: `tests/conftest.py`

Без неё задачу 4.4 не проверить. Отдельная задача, потому что помощник
`dbus_call` — это находка 4, и ошибка в нём выглядит как зависший тест.

**Step 1: Add the fixtures**

```python
# в конец tests/conftest.py

@pytest.fixture
def private_bus():
    """A throwaway session bus for the tray tests.

    Свой экземпляр шины на тест: элемент трея занимает уникальное имя и
    регистрируется у watcher, а делать это на живой шине пользователя нельзя —
    там работает установленное приложение.
    """
    gi = pytest.importorskip("gi")
    from gi.repository import Gio

    bus = Gio.TestDBus.new(Gio.TestDBusFlags.NONE)
    bus.up()
    try:
        yield bus.get_bus_address()
    finally:
        bus.down()


@pytest.fixture
def bus_connection(private_bus):
    """A client connection to the private bus."""
    from gi.repository import Gio

    flags = (
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    )
    return Gio.DBusConnection.new_for_address_sync(private_bus, flags, None, None)


@pytest.fixture
def dbus_call():
    """Call a D-Bus method while still driving the main loop.

    `call_sync` здесь непригоден: объект обслуживается главным циклом того же
    потока, и синхронный вызов блокирует его до таймаута. Поэтому вызов
    асинхронный, а цикл крутится вручную до готовности ответа.
    """
    from gi.repository import Gio, GLib

    def call(connection, name, path, interface, method, params=None, timeout=5.0):
        box: dict = {}

        def done(source, result):
            try:
                box["value"] = source.call_finish(result)
            except Exception as e:  # noqa: BLE001 - ошибка возвращается вызывающему
                box["error"] = e

        connection.call(
            name, path, interface, method, params, None, Gio.DBusCallFlags.NONE, 2000, None, done
        )

        context = GLib.MainContext.default()
        deadline = GLib.get_monotonic_time() + int(timeout * 1_000_000)
        while not box and GLib.get_monotonic_time() < deadline:
            context.iteration(True)

        if "error" in box:
            raise box["error"]
        if "value" not in box:
            raise TimeoutError(f"{interface}.{method} did not answer in {timeout}s")
        return box["value"]

    return call


@pytest.fixture
def pump():
    """Drive the main loop for a short while."""
    from gi.repository import GLib

    def run(seconds: float = 0.2) -> None:
        context = GLib.MainContext.default()
        deadline = GLib.get_monotonic_time() + int(seconds * 1_000_000)
        while GLib.get_monotonic_time() < deadline:
            context.iteration(False)

    return run
```

**Step 2: Verify the fixtures load**

Run: `uv run pytest tests/ -q --collect-only 2>&1 | tail -3`
Expected: коллекция проходит без ошибок.

**Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test: add private D-Bus fixtures for the tray tests"
```

---

## Task 4.4: StatusNotifierItem на шине

**Files:**
- Create: `src/ui/tray/sni.py`
- Test: `tests/test_ui_tray_sni.py`

Экспорт двух интерфейсов и регистрация у watcher. Тесты идут без маркера `gtk`:
дисплей не нужен, нужна только шина.

**Step 1: Write the failing test**

```python
# tests/test_ui_tray_sni.py
"""Элемент трея на приватной шине: свойства, меню, события, watcher."""

from __future__ import annotations

import pytest
from gi.repository import Gio, GLib

from src.ui.tray.dbusmenu import MenuItem, separator
from src.ui.tray.sni import StatusNotifierItem

WATCHER_XML = """
<node>
  <interface name='org.kde.StatusNotifierWatcher'>
    <method name='RegisterStatusNotifierItem'>
      <arg type='s' name='service' direction='in'/>
    </method>
    <property name='IsStatusNotifierHostRegistered' type='b' access='read'/>
  </interface>
</node>
"""


class FakeWatcher:
    """Minimal org.kde.StatusNotifierWatcher for the tests."""

    def __init__(self, connection):
        self.registered: list[str] = []
        info = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML)
        connection.register_object(
            "/StatusNotifierWatcher",
            info.interfaces[0],
            self._on_call,
            self._on_get,
            None,
        )
        Gio.bus_own_name_on_connection(
            connection,
            "org.kde.StatusNotifierWatcher",
            Gio.BusNameOwnerFlags.NONE,
            None,
            None,
        )

    def _on_call(self, _c, _sender, _path, _iface, method, params, invocation):
        if method == "RegisterStatusNotifierItem":
            self.registered.append(params.unpack()[0])
        invocation.return_value(None)

    def _on_get(self, _c, _sender, _path, _iface, _prop):
        return GLib.Variant("b", True)


@pytest.fixture
def menu_items():
    return [
        MenuItem("Статус: Отключено", enabled=False),
        separator(),
        MenuItem("Подключить", action="app.connect"),
        MenuItem("Выход", action="app.quit"),
    ]


@pytest.fixture
def item(bus_connection, menu_items, pump):
    """A published tray item on the private bus."""
    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-proxy-test")
    sni.set_menu(menu_items)
    sni.publish()
    pump()
    yield sni
    sni.shutdown()


def _get(dbus_call, connection, bus_name, path, interface, prop):
    return dbus_call(
        connection,
        bus_name,
        path,
        "org.freedesktop.DBus.Properties",
        "Get",
        GLib.Variant("(ss)", (interface, prop)),
    ).unpack()[0]


def test_the_bus_name_follows_the_specification(item):
    # org.kde.StatusNotifierItem-<pid>-<nr> — иначе панель имя не распознает.
    assert item.bus_name.startswith("org.kde.StatusNotifierItem-")


def test_the_item_owns_its_bus_name(item, bus_connection, dbus_call):
    owned = dbus_call(
        bus_connection,
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "NameHasOwner",
        GLib.Variant("(s)", (item.bus_name,)),
    ).unpack()[0]

    assert owned is True


def test_the_id_property_is_exported(item, bus_connection, dbus_call):
    value = _get(
        dbus_call, bus_connection, item.bus_name, "/StatusNotifierItem",
        "org.kde.StatusNotifierItem", "Id",
    )

    assert value == "tenga-proxy-test"


def test_the_category_is_application_status(item, bus_connection, dbus_call):
    value = _get(
        dbus_call, bus_connection, item.bus_name, "/StatusNotifierItem",
        "org.kde.StatusNotifierItem", "Category",
    )

    assert value == "ApplicationStatus"


def test_the_menu_property_points_at_the_menu_object(item, bus_connection, dbus_call):
    value = _get(
        dbus_call, bus_connection, item.bus_name, "/StatusNotifierItem",
        "org.kde.StatusNotifierItem", "Menu",
    )

    assert value == "/MenuBar"


def test_the_status_property_starts_active(item, bus_connection, dbus_call):
    value = _get(
        dbus_call, bus_connection, item.bus_name, "/StatusNotifierItem",
        "org.kde.StatusNotifierItem", "Status",
    )

    assert value == "Active"


def test_set_icon_changes_the_exported_icon_name(item, bus_connection, dbus_call, pump):
    item.set_icon("tenga-proxy-connected")
    pump()

    value = _get(
        dbus_call, bus_connection, item.bus_name, "/StatusNotifierItem",
        "org.kde.StatusNotifierItem", "IconName",
    )

    assert value == "tenga-proxy-connected"


def test_set_tooltip_is_exported_as_the_tooltip_tuple(item, bus_connection, dbus_call, pump):
    item.set_tooltip("Подключено: Работа")
    pump()

    value = _get(
        dbus_call, bus_connection, item.bus_name, "/StatusNotifierItem",
        "org.kde.StatusNotifierItem", "ToolTip",
    )

    # Формат ToolTip: (icon, pixmaps, title, description).
    assert value[2] == "Подключено: Работа"


def test_get_layout_returns_the_menu_tree(item, bus_connection, dbus_call):
    revision, root = dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "GetLayout",
        GLib.Variant("(iias)", (0, -1, [])),
    ).unpack()

    labels = [child[1].get("label", "") for child in root[2]]

    assert revision >= 1
    assert labels == ["Статус: Отключено", "", "Подключить", "Выход"]


def test_get_group_properties_answers_for_one_item(item, bus_connection, dbus_call):
    (pairs,) = dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "GetGroupProperties",
        GLib.Variant("(aias)", ([3], [])),
    ).unpack()

    assert pairs[0][1]["label"] == "Подключить"


def test_the_dbusmenu_version_property_is_three(item, bus_connection, dbus_call):
    value = _get(
        dbus_call, bus_connection, item.bus_name, "/MenuBar",
        "com.canonical.dbusmenu", "Version",
    )

    assert value == 3


def test_a_clicked_event_invokes_the_handler(item, bus_connection, dbus_call, menu_items):
    fired: list[tuple] = []
    item.set_on_activate(lambda action, target: fired.append((action, target)))

    dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "Event",
        GLib.Variant("(isvu)", (3, "clicked", GLib.Variant("s", ""), 0)),
    )

    assert fired == [("app.connect", None)]


def test_an_event_on_an_item_without_an_action_is_ignored(item, bus_connection, dbus_call):
    fired: list = []
    item.set_on_activate(lambda action, target: fired.append(action))

    dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "Event",
        GLib.Variant("(isvu)", (1, "clicked", GLib.Variant("s", ""), 0)),
    )

    assert fired == []


def test_an_event_on_an_unknown_id_does_not_raise(item, bus_connection, dbus_call):
    dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "Event",
        GLib.Variant("(isvu)", (999, "clicked", GLib.Variant("s", ""), 0)),
    )


def test_a_menu_event_carries_the_target(bus_connection, dbus_call, pump):
    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-target")
    sni.set_menu([MenuItem("Профиль", action="app.select-profile", target=17)])
    sni.publish()
    pump()

    fired: list[tuple] = []
    sni.set_on_activate(lambda action, target: fired.append((action, target)))
    try:
        dbus_call(
            bus_connection,
            sni.bus_name,
            "/MenuBar",
            "com.canonical.dbusmenu",
            "Event",
            GLib.Variant("(isvu)", (1, "clicked", GLib.Variant("s", ""), 0)),
        )
    finally:
        sni.shutdown()

    assert fired == [("app.select-profile", 17)]


def test_about_to_show_reports_no_update_needed(item, bus_connection, dbus_call):
    (needs_update,) = dbus_call(
        bus_connection,
        item.bus_name,
        "/MenuBar",
        "com.canonical.dbusmenu",
        "AboutToShow",
        GLib.Variant("(i)", (0,)),
    ).unpack()

    # Меню перестраивается по состоянию, а не по запросу панели.
    assert needs_update is False


def test_activate_invokes_the_primary_handler(item, bus_connection, dbus_call):
    fired: list = []
    item.set_on_primary(lambda: fired.append(True))

    dbus_call(
        bus_connection,
        item.bus_name,
        "/StatusNotifierItem",
        "org.kde.StatusNotifierItem",
        "Activate",
        GLib.Variant("(ii)", (0, 0)),
    )

    assert fired == [True]


def test_setting_a_new_menu_bumps_the_revision(item, bus_connection, dbus_call, pump):
    before = dbus_call(
        bus_connection, item.bus_name, "/MenuBar", "com.canonical.dbusmenu",
        "GetLayout", GLib.Variant("(iias)", (0, -1, [])),
    ).unpack()[0]

    item.set_menu([MenuItem("Другое")])
    pump()

    after = dbus_call(
        bus_connection, item.bus_name, "/MenuBar", "com.canonical.dbusmenu",
        "GetLayout", GLib.Variant("(iias)", (0, -1, [])),
    ).unpack()[0]

    # Панель перечитывает меню, только когда номер ревизии вырос.
    assert after > before


def test_the_item_registers_with_a_watcher_that_is_already_there(
    bus_connection, private_bus, pump
):
    from gi.repository import Gio

    flags = (
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    )
    watcher_connection = Gio.DBusConnection.new_for_address_sync(private_bus, flags, None, None)
    watcher = FakeWatcher(watcher_connection)
    pump()

    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-registered")
    sni.publish()
    pump(0.5)
    try:
        assert sni.bus_name in watcher.registered
    finally:
        sni.shutdown()


def test_the_item_registers_when_the_watcher_appears_later(bus_connection, private_bus, pump):
    from gi.repository import Gio

    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-late")
    sni.publish()
    pump()

    assert sni.is_registered is False

    flags = (
        Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT
        | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION
    )
    watcher_connection = Gio.DBusConnection.new_for_address_sync(private_bus, flags, None, None)
    watcher = FakeWatcher(watcher_connection)
    pump(0.5)
    try:
        # Переподключение важнее всего при перезапуске панели: элемент обязан
        # вернуться в трей сам.
        assert sni.bus_name in watcher.registered
    finally:
        sni.shutdown()


def test_publishing_without_a_watcher_does_not_raise(bus_connection, pump):
    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-nowatcher")
    sni.publish()
    pump()
    try:
        assert sni.is_registered is False
    finally:
        sni.shutdown()


def test_shutdown_releases_the_bus_name(bus_connection, dbus_call, pump):
    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-gone")
    sni.publish()
    pump()
    name = sni.bus_name

    sni.shutdown()
    pump()

    owned = dbus_call(
        bus_connection,
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "NameHasOwner",
        GLib.Variant("(s)", (name,)),
    ).unpack()[0]

    assert owned is False


def test_shutdown_twice_is_safe(bus_connection, pump):
    sni = StatusNotifierItem(connection=bus_connection, item_id="tenga-twice")
    sni.publish()
    pump()

    sni.shutdown()
    sni.shutdown()
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_tray_sni.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ui.tray.sni'`

**Step 3: Write minimal implementation**

```python
# src/ui/tray/sni.py
"""org.kde.StatusNotifierItem and com.canonical.dbusmenu over Gio.DBus.

Своя реализация вместо AppIndicator3: та библиотека собрана против GTK3 и в
одном процессе с GTK4 не живёт. Здесь используется только `Gio`, так что модуль
работает и без дисплея.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

import gi

from gi.repository import Gio, GLib

from src.ui.tray.dbusmenu import MenuItem, MenuModel
from src.ui.tray.variants import layout_variant, properties_variant

logger = logging.getLogger("tenga.ui.tray.sni")

WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
WATCHER_INTERFACE = "org.kde.StatusNotifierWatcher"

ITEM_PATH = "/StatusNotifierItem"
ITEM_INTERFACE = "org.kde.StatusNotifierItem"
MENU_PATH = "/MenuBar"
MENU_INTERFACE = "com.canonical.dbusmenu"

# Счётчик в имени: спецификация требует org.kde.StatusNotifierItem-<pid>-<nr>,
# а в одном процессе теоретически может жить несколько элементов.
_instance_counter = 0

ITEM_XML = """
<node>
  <interface name='org.kde.StatusNotifierItem'>
    <property name='Category' type='s' access='read'/>
    <property name='Id' type='s' access='read'/>
    <property name='Title' type='s' access='read'/>
    <property name='Status' type='s' access='read'/>
    <property name='IconName' type='s' access='read'/>
    <property name='IconThemePath' type='s' access='read'/>
    <property name='AttentionIconName' type='s' access='read'/>
    <property name='OverlayIconName' type='s' access='read'/>
    <property name='Menu' type='o' access='read'/>
    <property name='ItemIsMenu' type='b' access='read'/>
    <property name='ToolTip' type='(sa(iiay)ss)' access='read'/>
    <method name='Activate'>
      <arg type='i' name='x' direction='in'/>
      <arg type='i' name='y' direction='in'/>
    </method>
    <method name='SecondaryActivate'>
      <arg type='i' name='x' direction='in'/>
      <arg type='i' name='y' direction='in'/>
    </method>
    <method name='Scroll'>
      <arg type='i' name='delta' direction='in'/>
      <arg type='s' name='orientation' direction='in'/>
    </method>
    <signal name='NewIcon'/>
    <signal name='NewStatus'><arg type='s' name='status'/></signal>
    <signal name='NewTitle'/>
    <signal name='NewToolTip'/>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name='com.canonical.dbusmenu'>
    <property name='Version' type='u' access='read'/>
    <property name='TextDirection' type='s' access='read'/>
    <property name='Status' type='s' access='read'/>
    <property name='IconThemePath' type='as' access='read'/>
    <method name='GetLayout'>
      <arg type='i' name='parentId' direction='in'/>
      <arg type='i' name='recursionDepth' direction='in'/>
      <arg type='as' name='propertyNames' direction='in'/>
      <arg type='u' name='revision' direction='out'/>
      <arg type='(ia{sv}av)' name='layout' direction='out'/>
    </method>
    <method name='GetGroupProperties'>
      <arg type='ai' name='ids' direction='in'/>
      <arg type='as' name='propertyNames' direction='in'/>
      <arg type='a(ia{sv})' name='properties' direction='out'/>
    </method>
    <method name='GetProperty'>
      <arg type='i' name='id' direction='in'/>
      <arg type='s' name='name' direction='in'/>
      <arg type='v' name='value' direction='out'/>
    </method>
    <method name='Event'>
      <arg type='i' name='id' direction='in'/>
      <arg type='s' name='eventId' direction='in'/>
      <arg type='v' name='data' direction='in'/>
      <arg type='u' name='timestamp' direction='in'/>
    </method>
    <method name='AboutToShow'>
      <arg type='i' name='id' direction='in'/>
      <arg type='b' name='needUpdate' direction='out'/>
    </method>
    <signal name='LayoutUpdated'>
      <arg type='u' name='revision'/>
      <arg type='i' name='parent'/>
    </signal>
    <signal name='ItemsPropertiesUpdated'>
      <arg type='a(ia{sv})' name='updatedProps'/>
      <arg type='a(ias)' name='removedProps'/>
    </signal>
  </interface>
</node>
"""


class StatusNotifierItem:
    """A tray item published on the session bus."""

    def __init__(
        self,
        connection: Gio.DBusConnection | None = None,
        *,
        item_id: str = "tenga-proxy",
        title: str = "Tenga Proxy",
    ) -> None:
        global _instance_counter
        _instance_counter += 1

        self._connection = connection
        self.item_id = item_id
        self.title = title
        self.bus_name = f"org.kde.StatusNotifierItem-{os.getpid()}-{_instance_counter}"

        self._icon_name = ""
        self._icon_theme_path = ""
        self._status = "Active"
        self._tooltip = ""
        self._menu = MenuModel([])
        self._revision = 1

        self._on_activate: Callable[[str, int | None], None] | None = None
        self._on_primary: Callable[[], None] | None = None

        self._name_id = 0
        self._item_reg = 0
        self._menu_reg = 0
        self._watch_id = 0
        self.is_registered = False

    # --- публикация ---

    def publish(self) -> None:
        """Export both objects, take the bus name and look for a watcher."""
        if self._connection is None:
            self._connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)

        item_info = Gio.DBusNodeInfo.new_for_xml(ITEM_XML)
        self._item_reg = self._connection.register_object(
            ITEM_PATH, item_info.interfaces[0], self._on_item_call, self._on_item_get, None
        )

        menu_info = Gio.DBusNodeInfo.new_for_xml(MENU_XML)
        self._menu_reg = self._connection.register_object(
            MENU_PATH, menu_info.interfaces[0], self._on_menu_call, self._on_menu_get, None
        )

        self._name_id = Gio.bus_own_name_on_connection(
            self._connection, self.bus_name, Gio.BusNameOwnerFlags.NONE, None, None
        )

        # Watcher может появиться позже нас (перезапуск панели, вход в сессию),
        # поэтому не одна попытка регистрации, а наблюдение за именем.
        self._watch_id = Gio.bus_watch_name_on_connection(
            self._connection,
            WATCHER_NAME,
            Gio.BusNameWatcherFlags.NONE,
            self._on_watcher_appeared,
            self._on_watcher_vanished,
        )

    def shutdown(self) -> None:
        """Remove the item from the bus."""
        if self._watch_id:
            Gio.bus_unwatch_name(self._watch_id)
            self._watch_id = 0
        if self._name_id:
            Gio.bus_unown_name(self._name_id)
            self._name_id = 0
        if self._connection is not None:
            for reg in (self._item_reg, self._menu_reg):
                if reg:
                    self._connection.unregister_object(reg)
            self._item_reg = 0
            self._menu_reg = 0
        self.is_registered = False

    def _on_watcher_appeared(self, connection, _name, _owner) -> None:
        connection.call(
            WATCHER_NAME,
            WATCHER_PATH,
            WATCHER_INTERFACE,
            "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (self.bus_name,)),
            None,
            Gio.DBusCallFlags.NONE,
            5000,
            None,
            self._on_registered,
        )

    def _on_registered(self, source, result) -> None:
        try:
            source.call_finish(result)
        except Exception as e:  # noqa: BLE001 - без трея приложение работает дальше
            logger.info("Tray watcher refused the item: %s", e)
            return
        self.is_registered = True
        logger.info("Tray item registered as %s", self.bus_name)

    def _on_watcher_vanished(self, _connection, _name) -> None:
        self.is_registered = False

    # --- свойства ---

    def set_icon(self, icon_name: str, theme_path: str = "") -> None:
        """Change the icon and tell the panel to re-read it."""
        self._icon_name = icon_name
        if theme_path:
            self._icon_theme_path = theme_path
        self._emit_item_signal("NewIcon", None)

    def set_status(self, status: str) -> None:
        self._status = status
        self._emit_item_signal("NewStatus", GLib.Variant("(s)", (status,)))

    def set_tooltip(self, text: str) -> None:
        self._tooltip = text
        self._emit_item_signal("NewToolTip", None)

    def set_menu(self, items: list[MenuItem]) -> None:
        """Replace the whole menu and bump the revision."""
        self._menu = MenuModel(items)
        self._revision += 1
        self._emit_menu_signal("LayoutUpdated", GLib.Variant("(ui)", (self._revision, 0)))

    def set_on_activate(self, handler: Callable[[str, int | None], None]) -> None:
        """Install what runs when a menu entry is clicked."""
        self._on_activate = handler

    def set_on_primary(self, handler: Callable[[], None]) -> None:
        """Install what runs on a left click on the icon."""
        self._on_primary = handler

    def _emit_item_signal(self, name: str, params) -> None:
        if self._connection is None or not self._item_reg:
            return
        self._connection.emit_signal(None, ITEM_PATH, ITEM_INTERFACE, name, params)

    def _emit_menu_signal(self, name: str, params) -> None:
        if self._connection is None or not self._menu_reg:
            return
        self._connection.emit_signal(None, MENU_PATH, MENU_INTERFACE, name, params)

    # --- обработчики org.kde.StatusNotifierItem ---

    def _on_item_get(self, _connection, _sender, _path, _interface, prop):
        if prop == "Category":
            return GLib.Variant("s", "ApplicationStatus")
        if prop == "Id":
            return GLib.Variant("s", self.item_id)
        if prop == "Title":
            return GLib.Variant("s", self.title)
        if prop == "Status":
            return GLib.Variant("s", self._status)
        if prop == "IconName":
            return GLib.Variant("s", self._icon_name)
        if prop == "IconThemePath":
            return GLib.Variant("s", self._icon_theme_path)
        if prop in ("AttentionIconName", "OverlayIconName"):
            return GLib.Variant("s", "")
        if prop == "Menu":
            return GLib.Variant("o", MENU_PATH)
        if prop == "ItemIsMenu":
            # False: левый клик обязан открывать окно, а не меню.
            return GLib.Variant("b", False)
        if prop == "ToolTip":
            return GLib.Variant("(sa(iiay)ss)", ("", [], self.title, self._tooltip))
        return None

    def _on_item_call(self, _connection, _sender, _path, _interface, method, _params, invocation):
        if method == "Activate" and self._on_primary is not None:
            self._on_primary()
        invocation.return_value(None)

    # --- обработчики com.canonical.dbusmenu ---

    def _on_menu_get(self, _connection, _sender, _path, _interface, prop):
        if prop == "Version":
            return GLib.Variant("u", 3)
        if prop == "TextDirection":
            return GLib.Variant("s", "ltr")
        if prop == "Status":
            return GLib.Variant("s", "normal")
        if prop == "IconThemePath":
            return GLib.Variant("as", [self._icon_theme_path] if self._icon_theme_path else [])
        return None

    def _on_menu_call(self, _connection, _sender, _path, _interface, method, params, invocation):
        if method == "GetLayout":
            parent_id, depth, _names = params.unpack()
            invocation.return_value(layout_variant(self._menu, parent_id, self._revision, depth))
            return

        if method == "GetGroupProperties":
            ids, names = params.unpack()
            invocation.return_value(properties_variant(self._menu, list(ids), list(names)))
            return

        if method == "GetProperty":
            item_id, name = params.unpack()
            value = self._menu.properties(item_id).get(name, "")
            invocation.return_value(GLib.Variant("(v)", (GLib.Variant("s", str(value)),)))
            return

        if method == "Event":
            item_id, event_id, _data, _timestamp = params.unpack()
            if event_id == "clicked":
                self._activate_item(item_id)
            invocation.return_value(None)
            return

        if method == "AboutToShow":
            # Меню перестраивается при смене состояния, панели ничего
            # перечитывать не нужно.
            invocation.return_value(GLib.Variant("(b)", (False,)))
            return

        invocation.return_value(None)

    def _activate_item(self, item_id: int) -> None:
        item = self._menu.find(item_id)
        if item is None or not item.action or self._on_activate is None:
            return
        self._on_activate(item.action, item.target)
```

Импорт `gi` без `require_version` намеренный: модуль работает и без GTK,
версию фиксирует вызывающий (`gui.py` или `application.py`).

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_tray_sni.py -q`
Expected: 23 passed

Если тест зависает — причина в `call_sync` где-то в коде теста (находка 4).

**Step 5: Lint and commit**

```bash
uv run ruff check src/ui/tray tests/test_ui_tray_sni.py
uv run ruff format src/ui/tray tests/test_ui_tray_sni.py
git add src/ui/tray/sni.py tests/test_ui_tray_sni.py
git commit -m "feat: implement StatusNotifierItem tray over D-Bus"
```

---

## Task 4.5: Иконки трея

**Files:**
- Create: `assets/icons/tenga-proxy-disconnected.svg`
- Create: `assets/icons/tenga-proxy-connected.svg`
- Create: `assets/icons/tenga-proxy-connecting.svg`
- Create: `src/ui/tray/icons.py`
- Test: `tests/test_ui_tray_icons.py`

Закрывает B17: три состояния должны различаться на панели. Иконки монохромные,
16×16 в единицах пользователя, чтобы панель могла перекрасить их под свою тему.

**Step 1: Write the failing test**

```python
# tests/test_ui_tray_icons.py
"""Иконки трея: файлы существуют, имена соответствуют состояниям."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from src.ui.logic.status import ConnectionState
from src.ui.tray.icons import ICON_NAMES, icon_name_for, icons_directory


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (ConnectionState.DISCONNECTED, "tenga-proxy-disconnected"),
        (ConnectionState.CONNECTING, "tenga-proxy-connecting"),
        (ConnectionState.CONNECTED, "tenga-proxy-connected"),
        (ConnectionState.ERROR, "tenga-proxy-disconnected"),
    ],
)
def test_every_state_maps_to_an_icon(state, expected):
    assert icon_name_for(state) == expected


def test_the_three_names_are_distinct():
    # Дефект B17: в GTK3-версии все три состояния указывали на один файл.
    assert len(set(ICON_NAMES)) == 3


def test_the_icons_directory_exists():
    assert icons_directory().is_dir()


@pytest.mark.parametrize("name", ICON_NAMES)
def test_each_icon_file_is_present(name):
    assert (icons_directory() / f"{name}.svg").is_file()


@pytest.mark.parametrize("name", ICON_NAMES)
def test_each_icon_is_valid_svg(name):
    tree = ET.parse(icons_directory() / f"{name}.svg")

    assert tree.getroot().tag.endswith("svg")


@pytest.mark.parametrize("name", ICON_NAMES)
def test_each_icon_is_sixteen_units_square(name):
    root = ET.parse(icons_directory() / f"{name}.svg").getroot()

    # Панель масштабирует по viewBox; 16×16 — стандарт символьных иконок GNOME.
    assert root.get("viewBox") == "0 0 16 16"


def test_the_icons_differ_from_each_other():
    contents = {(icons_directory() / f"{name}.svg").read_text() for name in ICON_NAMES}

    assert len(contents) == 3
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_tray_icons.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ui.tray.icons'`

**Step 3: Create the icons**

`assets/icons/tenga-proxy-disconnected.svg` — разорванная связь:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
  <path fill="currentColor" d="M8 1a7 7 0 0 0-7 7 7 7 0 0 0 7 7 7 7 0 0 0 7-7 7 7 0 0 0-7-7zm0 1.5a5.5 5.5 0 0 1 5.5 5.5 5.5 5.5 0 0 1-5.5 5.5A5.5 5.5 0 0 1 2.5 8 5.5 5.5 0 0 1 8 2.5z"/>
  <path fill="currentColor" d="M5.2 4.5 4.5 5.2 10.8 11.5 11.5 10.8z"/>
</svg>
```

`assets/icons/tenga-proxy-connected.svg` — замкнутый круг с точкой:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
  <path fill="currentColor" d="M8 1a7 7 0 0 0-7 7 7 7 0 0 0 7 7 7 7 0 0 0 7-7 7 7 0 0 0-7-7zm0 1.5a5.5 5.5 0 0 1 5.5 5.5 5.5 5.5 0 0 1-5.5 5.5A5.5 5.5 0 0 1 2.5 8 5.5 5.5 0 0 1 8 2.5z"/>
  <circle fill="currentColor" cx="8" cy="8" r="2.75"/>
</svg>
```

`assets/icons/tenga-proxy-connecting.svg` — незамкнутая дуга:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">
  <path fill="currentColor" d="M8 1a7 7 0 0 0-7 7h1.5A5.5 5.5 0 0 1 8 2.5 5.5 5.5 0 0 1 13.5 8 5.5 5.5 0 0 1 8 13.5V15a7 7 0 0 0 7-7 7 7 0 0 0-7-7z"/>
  <circle fill="currentColor" cx="8" cy="8" r="1.75"/>
</svg>
```

**Step 4: Write the module**

```python
# src/ui/tray/icons.py
"""Tray icon names and where their files live.

Иконки лежат в собственном каталоге, а не в системной теме: приложение ставится
как AppImage, и в теме пользователя его имён нет. Каталог отдаётся панели через
свойство `IconThemePath`.
"""

from __future__ import annotations

from pathlib import Path

from src.core.config import BUNDLE_DIR
from src.ui.logic.status import ConnectionState

ICON_DISCONNECTED = "tenga-proxy-disconnected"
ICON_CONNECTING = "tenga-proxy-connecting"
ICON_CONNECTED = "tenga-proxy-connected"

ICON_NAMES = (ICON_DISCONNECTED, ICON_CONNECTING, ICON_CONNECTED)

_BY_STATE = {
    ConnectionState.DISCONNECTED: ICON_DISCONNECTED,
    ConnectionState.CONNECTING: ICON_CONNECTING,
    ConnectionState.CONNECTED: ICON_CONNECTED,
    # У ошибки своей иконки нет: состояние «не подключено», а причина видна
    # в подсказке и в окне.
    ConnectionState.ERROR: ICON_DISCONNECTED,
}


def icons_directory() -> Path:
    """Directory holding the tray icons."""
    return BUNDLE_DIR / "assets" / "icons"


def icon_name_for(state: ConnectionState) -> str:
    """Icon name for one connection state."""
    return _BY_STATE.get(state, ICON_DISCONNECTED)
```

**Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_tray_icons.py -q`
Expected: 20 passed

**Step 6: Look at the icons**

Отрисовать все три в один PNG и посмотреть, различимы ли они в размере панели:

```bash
for n in disconnected connecting connected; do
  rsvg-convert -w 22 -h 22 "assets/icons/tenga-proxy-$n.svg" -o "/tmp/tray-$n.png"
done
```

Если `rsvg-convert` нет — `python cli.py` не нужен, годится любой просмотрщик SVG.
Критерий: три силуэта различаются при 22 px, без цвета.

**Step 7: Commit**

```bash
git add assets/icons src/ui/tray/icons.py tests/test_ui_tray_icons.py
git commit -m "feat: add three distinct tray icons (B17)"
```

---

## Task 4.6: Построение меню из состояния

**Files:**
- Create: `src/ui/tray/menu.py`
- Test: `tests/test_ui_tray_menu.py`

Чистая функция: состояние и список профилей на входе, дерево `MenuItem` на
выходе. Проверяется без шины.

**Step 1: Write the failing test**

```python
# tests/test_ui_tray_menu.py
"""Состав меню трея для разных состояний."""

from __future__ import annotations

from dataclasses import dataclass

from src.ui.logic.status import ConnectionState
from src.ui.tray.menu import MAX_PROFILES, build_menu


@dataclass
class FakeProfile:
    id: int
    name: str


def _labels(items):
    return [item.label for item in items]


def _find(items, label):
    for item in items:
        if item.label == label:
            return item
        found = _find(item.children, label)
        if found is not None:
            return found
    return None


def test_the_first_entry_shows_the_disconnected_status():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert items[0].label == "Статус: Отключено"


def test_the_status_entry_is_not_clickable():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert items[0].enabled is False


def test_the_status_entry_names_the_connected_profile():
    items = build_menu(ConnectionState.CONNECTED, [], profile_name="Работа")

    assert items[0].label == "Статус: Работа"


def test_the_connecting_state_has_its_own_status_line():
    items = build_menu(ConnectionState.CONNECTING, [], profile_name="Работа")

    assert items[0].label == "Статус: подключение…"


def test_disconnected_offers_to_connect():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert _find(items, "Подключить") is not None


def test_connected_offers_to_disconnect():
    items = build_menu(ConnectionState.CONNECTED, [], profile_name="Работа")

    assert _find(items, "Отключить") is not None
    assert _find(items, "Подключить") is None


def test_the_connect_entry_triggers_the_application_action():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert _find(items, "Подключить").action == "app.connect"


def test_the_disconnect_entry_triggers_the_application_action():
    items = build_menu(ConnectionState.CONNECTED, [], profile_name="Р")

    assert _find(items, "Отключить").action == "app.disconnect"


def test_connecting_offers_to_cancel():
    items = build_menu(ConnectionState.CONNECTING, [], profile_name="Работа")

    # Во время подключения ни «Подключить», ни «Отключить» не имеют смысла:
    # единственное осмысленное действие — прервать.
    assert _find(items, "Отменить") is not None


def test_the_profiles_submenu_lists_the_profiles():
    profiles = [FakeProfile(1, "Первый"), FakeProfile(2, "Второй")]

    items = build_menu(ConnectionState.DISCONNECTED, profiles, profile_name="")

    assert _labels(_find(items, "Профили").children) == ["Первый", "Второй"]


def test_a_profile_entry_carries_its_id_as_the_target():
    profiles = [FakeProfile(7, "Седьмой")]

    items = build_menu(ConnectionState.DISCONNECTED, profiles, profile_name="")
    entry = _find(items, "Седьмой")

    assert entry.action == "app.connect-profile"
    assert entry.target == 7


def test_the_running_profile_is_marked_as_checked():
    profiles = [FakeProfile(1, "Первый"), FakeProfile(2, "Второй")]

    items = build_menu(
        ConnectionState.CONNECTED, profiles, profile_name="Второй", active_profile_id=2
    )

    assert _find(items, "Второй").checked is True
    assert _find(items, "Первый").checked is False


def test_no_profile_is_checked_when_nothing_runs():
    profiles = [FakeProfile(1, "Первый")]

    items = build_menu(ConnectionState.DISCONNECTED, profiles, profile_name="")

    assert _find(items, "Первый").checked is False


def test_the_submenu_says_so_when_there_are_no_profiles():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")
    children = _find(items, "Профили").children

    assert _labels(children) == ["(нет профилей)"]
    assert children[0].enabled is False


def test_the_profile_list_is_capped():
    profiles = [FakeProfile(i, f"P{i}") for i in range(1, MAX_PROFILES + 10)]

    children = _find(build_menu(ConnectionState.DISCONNECTED, profiles, ""), "Профили").children

    # Меню в 130 пунктов панель растягивает на весь экран, поэтому список
    # обрезается, а полный остаётся в окне.
    assert len(children) == MAX_PROFILES + 1


def test_the_capped_list_ends_with_a_link_to_the_window():
    profiles = [FakeProfile(i, f"P{i}") for i in range(1, MAX_PROFILES + 10)]

    children = _find(build_menu(ConnectionState.DISCONNECTED, profiles, ""), "Профили").children

    assert children[-1].label == "Показать все…"
    assert children[-1].action == "app.activate-window"


def test_a_short_list_has_no_link_to_the_window():
    profiles = [FakeProfile(1, "Один")]

    children = _find(build_menu(ConnectionState.DISCONNECTED, profiles, ""), "Профили").children

    assert _labels(children) == ["Один"]


def test_the_running_profile_stays_visible_beyond_the_cap():
    profiles = [FakeProfile(i, f"P{i}") for i in range(1, MAX_PROFILES + 10)]
    last_id = profiles[-1].id

    children = _find(
        build_menu(ConnectionState.CONNECTED, profiles, "P99", active_profile_id=last_id),
        "Профили",
    ).children

    # Иначе подключённый профиль пропал бы из меню ровно тогда, когда он важнее
    # всего.
    assert any(child.target == last_id for child in children)


def test_the_menu_offers_the_standard_application_entries():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    for label in ("Добавить профиль…", "Открыть окно", "Настройки…", "Выход"):
        assert _find(items, label) is not None, label


def test_the_quit_entry_triggers_the_quit_action():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert _find(items, "Выход").action == "app.quit"


def test_the_window_entry_triggers_the_activate_action():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert _find(items, "Открыть окно").action == "app.activate-window"


def test_the_menu_is_split_by_separators():
    items = build_menu(ConnectionState.DISCONNECTED, [], profile_name="")

    assert sum(1 for item in items if item.is_separator) >= 3


def test_a_long_profile_name_is_shortened():
    profiles = [FakeProfile(1, "О" * 80)]

    entry = _find(build_menu(ConnectionState.DISCONNECTED, profiles, ""), "Профили").children[0]

    # Панель не переносит строки: длинное имя растянуло бы меню на весь экран.
    assert len(entry.label) <= 40
    assert entry.label.endswith("…")


def test_a_short_profile_name_is_untouched():
    profiles = [FakeProfile(1, "Работа")]

    entry = _find(build_menu(ConnectionState.DISCONNECTED, profiles, ""), "Профили").children[0]

    assert entry.label == "Работа"
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_tray_menu.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ui.tray.menu'`

**Step 3: Write minimal implementation**

```python
# src/ui/tray/menu.py
"""Build the tray menu out of the current state.

Чистая функция без GTK и без D-Bus: состав меню — это решение о содержании, и
проверять его удобнее обычным тестом, чем через шину.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.ui.logic.status import ConnectionState
from src.ui.tray.dbusmenu import MenuItem, separator

# Больше двух десятков пунктов панель растягивает на весь экран; полный список
# всегда доступен в окне.
MAX_PROFILES = 20
MAX_LABEL = 40


def shorten(name: str, limit: int = MAX_LABEL) -> str:
    """Cut a long profile name down to a size the panel can show."""
    if len(name) <= limit:
        return name
    return name[: limit - 1] + "…"


def _status_label(state: ConnectionState, profile_name: str) -> str:
    if state is ConnectionState.CONNECTED:
        return f"Статус: {profile_name}" if profile_name else "Статус: подключено"
    if state is ConnectionState.CONNECTING:
        return "Статус: подключение…"
    if state is ConnectionState.ERROR:
        return "Статус: ошибка"
    return "Статус: Отключено"


def _connection_entry(state: ConnectionState) -> MenuItem:
    if state is ConnectionState.CONNECTED:
        return MenuItem("Отключить", action="app.disconnect")
    if state is ConnectionState.CONNECTING:
        return MenuItem("Отменить", action="app.disconnect")
    return MenuItem("Подключить", action="app.connect")


def _profile_entries(profiles: Sequence, active_profile_id: int | None) -> list[MenuItem]:
    if not profiles:
        return [MenuItem("(нет профилей)", enabled=False)]

    shown = list(profiles[:MAX_PROFILES])
    truncated = len(profiles) > MAX_PROFILES

    if truncated and active_profile_id is not None:
        # Подключённый профиль обязан оставаться в списке, даже если по
        # порядку он не попал в первые двадцать.
        if not any(p.id == active_profile_id for p in shown):
            active = next((p for p in profiles if p.id == active_profile_id), None)
            if active is not None:
                shown = shown[: MAX_PROFILES - 1] + [active]

    entries = [
        MenuItem(
            shorten(profile.name),
            action="app.connect-profile",
            target=profile.id,
            checked=profile.id == active_profile_id,
        )
        for profile in shown
    ]

    if truncated:
        entries.append(MenuItem("Показать все…", action="app.activate-window"))

    return entries


def build_menu(
    state: ConnectionState,
    profiles: Sequence,
    profile_name: str = "",
    active_profile_id: int | None = None,
) -> list[MenuItem]:
    """Describe the whole tray menu for the current state."""
    return [
        MenuItem(_status_label(state, profile_name), enabled=False),
        separator(),
        _connection_entry(state),
        separator(),
        MenuItem("Профили", children=_profile_entries(profiles, active_profile_id)),
        MenuItem("Добавить профиль…", action="app.add-profile"),
        separator(),
        MenuItem("Открыть окно", action="app.activate-window"),
        MenuItem("Настройки…", action="app.settings"),
        separator(),
        MenuItem("Выход", action="app.quit"),
    ]
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_tray_menu.py -q`
Expected: 24 passed

**Step 5: Commit**

```bash
uv run ruff check src/ui/tray tests/test_ui_tray_menu.py
uv run ruff format src/ui/tray tests/test_ui_tray_menu.py
git add src/ui/tray/menu.py tests/test_ui_tray_menu.py
git commit -m "feat: build the tray menu from the connection state"
```

---

## Task 4.7: TrayController

**Files:**
- Create: `src/ui/tray/controller.py`
- Test: `tests/test_ui_tray_controller.py`

Связывает состояние приложения с элементом трея. Тест подставляет фиктивный
`StatusNotifierItem`, поэтому шина не нужна.

**Step 1: Write the failing test**

```python
# tests/test_ui_tray_controller.py
"""TrayController: состояние приложения → иконка, подсказка и меню."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from src.core.context import AppContext
from src.ui.logic.status import ConnectionState
from src.ui.tray.controller import TrayController


@dataclass
class FakeItem:
    """Stand-in for StatusNotifierItem, recording what it was told."""

    icons: list = field(default_factory=list)
    tooltips: list = field(default_factory=list)
    menus: list = field(default_factory=list)
    published: bool = False
    stopped: bool = False
    on_activate: object = None
    on_primary: object = None
    is_registered: bool = False

    def publish(self):
        self.published = True

    def shutdown(self):
        self.stopped = True

    def set_icon(self, name, theme_path=""):
        self.icons.append(name)

    def set_tooltip(self, text):
        self.tooltips.append(text)

    def set_menu(self, items):
        self.menus.append(items)

    def set_on_activate(self, handler):
        self.on_activate = handler

    def set_on_primary(self, handler):
        self.on_primary = handler


@dataclass
class FakeApp:
    """Records the actions the tray asks the application to run."""

    activated: list = field(default_factory=list)

    def activate_action(self, name, target=None):
        self.activated.append((name, target))


def _labels(items):
    return [item.label for item in items]


def _find(items, label):
    for item in items:
        if item.label == label:
            return item
        found = _find(item.children, label)
        if found is not None:
            return found
    return None


@pytest.fixture
def context(tmp_path):
    return AppContext(config_dir=tmp_path)


@pytest.fixture
def controller(context):
    item = FakeItem()
    app = FakeApp()
    tray = TrayController(app, context, item=item, dispatch=lambda fn, *a: fn(*a))
    tray.start()
    return tray, item, app


def test_start_publishes_the_item(controller):
    _tray, item, _app = controller

    assert item.published is True


def test_start_installs_the_initial_menu(controller):
    _tray, item, _app = controller

    assert _find(item.menus[-1], "Подключить") is not None


def test_start_sets_the_disconnected_icon(controller):
    _tray, item, _app = controller

    assert item.icons[-1] == "tenga-proxy-disconnected"


def test_the_tooltip_starts_as_disconnected(controller):
    _tray, item, _app = controller

    assert item.tooltips[-1] == "Tenga Proxy: отключено"


def test_setting_the_connected_state_changes_the_icon(controller):
    tray, item, _app = controller

    tray.set_state(ConnectionState.CONNECTED, profile_name="Работа")

    assert item.icons[-1] == "tenga-proxy-connected"


def test_setting_the_connecting_state_changes_the_icon(controller):
    tray, item, _app = controller

    tray.set_state(ConnectionState.CONNECTING, profile_name="Работа")

    assert item.icons[-1] == "tenga-proxy-connecting"


def test_the_connected_tooltip_names_the_profile(controller):
    tray, item, _app = controller

    tray.set_state(ConnectionState.CONNECTED, profile_name="Работа")

    assert item.tooltips[-1] == "Tenga Proxy: Работа"


def test_the_connected_menu_offers_to_disconnect(controller):
    tray, item, _app = controller

    tray.set_state(ConnectionState.CONNECTED, profile_name="Работа")

    assert _find(item.menus[-1], "Отключить") is not None


def test_the_menu_lists_the_profiles_of_the_store(controller, context):
    tray, item, _app = controller
    from src.fmt import parse_link

    bean = parse_link("socks://127.0.0.1:1080#Локальный")
    context.profiles.add_profile(bean)

    tray.refresh()

    assert "Локальный" in _labels(_find(item.menus[-1], "Профили").children)


def test_clicking_an_entry_activates_the_application_action(controller):
    _tray, item, app = controller

    item.on_activate("app.quit", None)

    assert app.activated == [("quit", None)]


def test_clicking_a_profile_entry_passes_the_profile_id(controller):
    _tray, item, app = controller

    item.on_activate("app.connect-profile", 7)

    assert app.activated == [("connect-profile", 7)]


def test_a_left_click_on_the_icon_activates_the_window(controller):
    _tray, item, app = controller

    item.on_primary()

    assert app.activated == [("activate-window", None)]


def test_a_state_change_of_the_proxy_updates_the_tray(controller, context):
    tray, item, _app = controller
    before = len(item.menus)

    context.proxy_state.set_running(profile_id=1)

    # Трей слушает состояние прокси: подключение из окна обязано отразиться
    # на иконке без участия окна.
    assert len(item.menus) > before
    assert item.icons[-1] == "tenga-proxy-connected"


def test_stopping_the_proxy_returns_the_disconnected_icon(controller, context):
    _tray, item, _app = controller
    context.proxy_state.set_running(profile_id=1)

    context.proxy_state.set_stopped()

    assert item.icons[-1] == "tenga-proxy-disconnected"


def test_stop_shuts_the_item_down(controller):
    tray, item, _app = controller

    tray.stop()

    assert item.stopped is True


def test_stop_unsubscribes_from_the_proxy_state(controller, context):
    tray, item, _app = controller
    tray.stop()
    before = len(item.icons)

    context.proxy_state.set_running(profile_id=1)

    # Слушатель на уничтоженном элементе привёл бы к вызовам на закрытой шине.
    assert len(item.icons) == before


def test_stop_twice_is_safe(controller):
    tray, _item, _app = controller

    tray.stop()
    tray.stop()


def test_a_state_change_is_delivered_through_the_dispatcher(context):
    """Смена состояния приходит из потока подключения, а D-Bus требует главного."""
    item = FakeItem()
    delivered: list = []
    tray = TrayController(
        FakeApp(), context, item=item, dispatch=lambda fn, *a: delivered.append((fn, a))
    )
    tray.start()
    delivered.clear()

    context.proxy_state.set_running(profile_id=1)

    assert len(delivered) == 1
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_tray_controller.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ui.tray.controller'`

**Step 3: Write minimal implementation**

```python
# src/ui/tray/controller.py
"""Connect the tray item to the application state.

Иконка, подсказка и меню — производные от состояния прокси; действия меню
переадресуются существующим `Gio.Action` приложения, чтобы поведение трея и
окна не разъезжалось.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.ui.logic.status import ConnectionState
from src.ui.tray.icons import icon_name_for, icons_directory
from src.ui.tray.menu import build_menu

if TYPE_CHECKING:
    from src.core.context import AppContext

logger = logging.getLogger("tenga.ui.tray")


def _default_dispatch(fn: Callable[..., object], *args: object) -> None:
    from gi.repository import GLib

    def _once() -> bool:
        fn(*args)
        return GLib.SOURCE_REMOVE

    GLib.idle_add(_once)


class TrayController:
    """Keeps the tray item in step with the proxy state."""

    def __init__(
        self,
        application,
        context: AppContext,
        *,
        item=None,
        dispatch: Callable[..., object] = _default_dispatch,
    ) -> None:
        self._app = application
        self._context = context
        self._dispatch = dispatch
        self._state = ConnectionState.DISCONNECTED
        self._profile_name = ""
        self._running = False

        if item is None:
            from src.ui.tray.sni import StatusNotifierItem

            item = StatusNotifierItem()
        self._item = item

    def start(self) -> None:
        """Publish the item and start following the proxy state."""
        self._item.set_on_activate(self._on_menu_action)
        self._item.set_on_primary(lambda: self._activate("activate-window"))
        self._item.publish()
        self._context.proxy_state.add_listener(self._on_proxy_state)
        self._running = True
        self.refresh()

    def stop(self) -> None:
        """Remove the item and stop following the state."""
        if not self._running:
            return
        self._running = False
        try:
            self._context.proxy_state.remove_listener(self._on_proxy_state)
        except Exception:
            logger.debug("Tray listener was already gone", exc_info=True)
        self._item.shutdown()

    def set_state(self, state: ConnectionState, profile_name: str = "") -> None:
        """Change what the tray shows."""
        self._state = state
        self._profile_name = profile_name
        self.refresh()

    def refresh(self) -> None:
        """Rebuild the icon, the tooltip and the menu."""
        self._item.set_icon(icon_name_for(self._state), str(icons_directory()))
        self._item.set_tooltip(self._tooltip())
        self._item.set_menu(
            build_menu(
                self._state,
                self._profiles(),
                profile_name=self._profile_name,
                active_profile_id=self._active_profile_id(),
            )
        )

    def _tooltip(self) -> str:
        if self._state is ConnectionState.CONNECTED:
            return f"Tenga Proxy: {self._profile_name or 'подключено'}"
        if self._state is ConnectionState.CONNECTING:
            return "Tenga Proxy: подключение…"
        if self._state is ConnectionState.ERROR:
            return "Tenga Proxy: ошибка"
        return "Tenga Proxy: отключено"

    def _profiles(self) -> list:
        return list(self._context.profiles.profiles.values())

    def _active_profile_id(self) -> int | None:
        state = self._context.proxy_state
        if not state.is_running or state.started_profile_id < 0:
            return None
        return state.started_profile_id

    def _on_proxy_state(self, state) -> None:
        # Состояние меняет поток подключения, а работа с D-Bus должна идти из
        # главного цикла.
        self._dispatch(self._apply_proxy_state, state.is_running, state.started_profile_id)

    def _apply_proxy_state(self, is_running: bool, profile_id: int) -> None:
        if is_running:
            profile = self._context.profiles.get_profile(profile_id)
            self.set_state(ConnectionState.CONNECTED, profile.name if profile else "")
        else:
            self.set_state(ConnectionState.DISCONNECTED, "")

    def _on_menu_action(self, action: str, target: int | None) -> None:
        self._activate(action.removeprefix("app."), target)

    def _activate(self, name: str, target: int | None = None) -> None:
        try:
            self._app.activate_action(name, target)
        except Exception as e:  # noqa: BLE001 - клик из трея не должен ронять процесс
            logger.warning("Tray action %s failed: %s", name, e)
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ui_tray_controller.py -q`
Expected: 18 passed

**Step 5: Commit**

```bash
uv run ruff check src/ui/tray tests/test_ui_tray_controller.py
uv run ruff format src/ui/tray tests/test_ui_tray_controller.py
git add src/ui/tray/controller.py tests/test_ui_tray_controller.py
git commit -m "feat: keep the tray in step with the proxy state"
```

---

## Task 4.8: Действия приложения для трея

**Files:**
- Modify: `src/ui/application.py:94-119` (`_register_actions`)
- Modify: `src/ui/application.py` (новые обработчики)
- Test: `tests/test_ui_application.py` (дописать)

Трею нужны два действия, которых у приложения ещё нет: `connect-profile(i)` и
`activate-window`. Первое параметризовано целым — как строчные действия окна из
этапа 3.

**Step 1: Write the failing test**

```python
# в конец tests/test_ui_application.py

@pytest.mark.gtk
def test_the_connect_profile_action_takes_a_profile_id(adw_app):
    """Трей адресует профиль числом: у пунктов меню общий обработчик."""
    from gi.repository import GLib

    service = FakeConnectionService()
    adw_app.set_connection_service(service)
    profile = _add_profile(adw_app, "Работа")

    adw_app.lookup_action("connect-profile").activate(GLib.Variant("i", profile.id))
    adw_app.wait_for_connection_for_test()

    assert service.calls == [("connect", profile.id)]


@pytest.mark.gtk
def test_the_activate_window_action_shows_the_window(adw_app):
    adw_app.activate()
    adw_app._window.set_visible(False)

    adw_app.lookup_action("activate-window").activate(None)

    assert adw_app._window.get_visible() is True


@pytest.mark.gtk
def test_activate_action_accepts_a_target_for_parameterised_actions(adw_app):
    """TrayController зовёт activate_action(name, target) одинаково для всех."""
    service = FakeConnectionService()
    adw_app.set_connection_service(service)
    profile = _add_profile(adw_app, "Работа")

    adw_app.activate_action("connect-profile", profile.id)
    adw_app.wait_for_connection_for_test()

    assert service.calls == [("connect", profile.id)]


@pytest.mark.gtk
def test_activate_action_works_for_actions_without_a_parameter(adw_app):
    adw_app.activate()
    adw_app._window.set_visible(False)

    adw_app.activate_action("activate-window", None)

    assert adw_app._window.get_visible() is True
```

Если `FakeConnectionService` и `_add_profile` в файле ещё не описаны, взять их
из существующих тестов подключения того же файла.

**Step 2: Run test to verify it fails**

Run: `xvfb-run -a uv run pytest tests/test_ui_application.py -q -m gtk -k "connect_profile_action or activate_window"`
Expected: FAIL — действие не найдено.

**Step 3: Write minimal implementation**

В `src/ui/application.py`, в `_register_actions`, после цикла по `handlers`
добавить регистрацию параметризованного действия и `activate-window`:

```python
        handlers["activate-window"] = self._activate_window

        for name, handler in handlers.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", lambda _action, _param, fn=handler: fn())
            self.add_action(action)

        # Действие с параметром: трей адресует конкретный профиль числом, как
        # это делают строчные действия окна.
        connect_profile = Gio.SimpleAction.new("connect-profile", GLib.VariantType.new("i"))
        connect_profile.connect(
            "activate", lambda _action, param: self.connect_profile(param.get_int32())
        )
        self.add_action(connect_profile)
```

И новый обработчик рядом с `_hide_window`:

```python
    def _activate_window(self) -> None:
        """Show the window, creating it if the application ran headless."""
        self.activate()
        if self._window is not None:
            self._window.set_visible(True)
            self._window.present()
```

Плюс совместимый со всеми действиями вызов — `Gio.Application.activate_action`
принимает `GLib.Variant`, а трей передаёт обычное число:

```python
    def activate_action(self, name: str, target=None) -> None:
        """Run one of the application actions, wrapping an integer target.

        `Gio.Action` требует `GLib.Variant`, а трей адресует профиль обычным
        числом: приведение живёт здесь, чтобы вызывающие о нём не знали.
        """
        parameter = GLib.Variant("i", target) if isinstance(target, int) else None
        action = self.lookup_action(name)
        if action is None:
            logger.warning("Unknown action %s", name)
            return
        # Синхронно, а не через Gio.Application.activate_action: тому нужен
        # прогон главного цикла, и результат в тестах не виден сразу.
        action.activate(parameter)
```

**Step 4: Run test to verify it passes**

Run: `xvfb-run -a uv run pytest tests/test_ui_application.py -q -m gtk`
Expected: все тесты файла проходят.

**Step 5: Commit**

```bash
uv run ruff check src tests
uv run ruff format --check src tests
git add src/ui/application.py tests/test_ui_application.py
git commit -m "feat: add the profile and window actions the tray needs"
```

---

## Task 4.9: Трей в приложении

**Files:**
- Modify: `src/ui/application.py` (`__init__`, `do_startup`, `do_shutdown`, `connect_profile`, `_on_connection_done`, `run_app`)
- Modify: `gui.py:166-171` (передать `--no-tray`)
- Test: `tests/test_ui_application.py` (дописать)

**Step 1: Write the failing test**

```python
# в конец tests/test_ui_application.py

@pytest.mark.gtk
def test_the_tray_is_off_unless_asked_for(adw_app):
    assert adw_app.tray is None


@pytest.mark.gtk
def test_start_tray_creates_a_controller(adw_app):
    """Своя реализация SNI не требует дисплея, но требует шины сессии."""
    tray_item = FakeTrayItem()
    adw_app.start_tray(item=tray_item)

    assert adw_app.tray is not None
    assert tray_item.published is True

    adw_app.stop_tray()


@pytest.mark.gtk
def test_connecting_moves_the_tray_into_the_connecting_state(adw_app):
    tray_item = FakeTrayItem()
    adw_app.start_tray(item=tray_item)
    service = FakeConnectionService()
    adw_app.set_connection_service(service)
    profile = _add_profile(adw_app, "Работа")

    adw_app.connect_profile(profile.id)

    # Промежуточное состояние есть только в UI, из proxy_state его не видно.
    assert tray_item.icons[-1] == "tenga-proxy-connecting"

    adw_app.wait_for_connection_for_test()
    adw_app.stop_tray()


@pytest.mark.gtk
def test_stop_tray_removes_the_controller(adw_app):
    tray_item = FakeTrayItem()
    adw_app.start_tray(item=tray_item)

    adw_app.stop_tray()

    assert adw_app.tray is None
    assert tray_item.stopped is True


@pytest.mark.gtk
def test_stop_tray_without_a_tray_is_safe(adw_app):
    adw_app.stop_tray()
```

`FakeTrayItem` — та же заглушка, что в `tests/test_ui_tray_controller.py`;
чтобы не дублировать, вынести её в `tests/support/tray.py` и импортировать в
обоих файлах.

**Step 2: Run test to verify it fails**

Run: `xvfb-run -a uv run pytest tests/test_ui_application.py -q -m gtk -k tray`
Expected: FAIL — `AttributeError: 'TengaApplication' object has no attribute 'tray'`

**Step 3: Write minimal implementation**

В `src/ui/application.py`:

```python
    def __init__(self, context=None, lock=None, *, with_tray: bool = False) -> None:
        ...
        self.tray = None
        self._with_tray = with_tray
```

```python
    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        load_css()
        self._register_actions()
        self._setup_signal_handlers()
        if self._with_tray:
            self.start_tray()
```

```python
    def start_tray(self, item=None) -> None:
        """Publish the tray icon."""
        from src.ui.tray.controller import TrayController

        if self.tray is not None:
            return
        try:
            self.tray = TrayController(self, self.context, item=item)
            self.tray.start()
        except Exception as e:  # noqa: BLE001 - трей необязателен
            # Без панели, поддерживающей StatusNotifierItem, приложение просто
            # работает без иконки.
            logger.info("Tray is unavailable: %s", e)
            self.tray = None

    def stop_tray(self) -> None:
        """Remove the tray icon."""
        if self.tray is None:
            return
        self.tray.stop()
        self.tray = None
```

В `do_shutdown` перед освобождением блокировки:

```python
        self.stop_tray()
```

В `connect_profile`, рядом с `self._window.show_connecting(profile.name)`:

```python
        if self.tray is not None:
            self.tray.set_state(ConnectionState.CONNECTING, profile.name)
```

(потребуется `from src.ui.logic.status import ConnectionState` в шапке модуля —
он уже импортируется в `window.py`, в `application.py` его пока нет).

В `_on_connection_failed` — вернуть трей в состояние ошибки:

```python
        if self.tray is not None:
            self.tray.set_state(ConnectionState.ERROR, "")
```

Состояния «подключено» и «отключено» трей узнаёт сам из `proxy_state`, вручную
их выставлять не нужно.

В `run_app` — прокинуть флаг:

```python
def run_app(config_dir=None, lock=None, with_tray: bool = True) -> int:
    """Entry point for the GTK4 interface."""
    from src.core.context import init_context

    context = init_context(config_dir=config_dir)
    app = TengaApplication(context=context, lock=lock, with_tray=with_tray)
    return app.run([])
```

В `gui.py` заменить строку вызова:

```python
        if args.gtk4:
            from src.ui.application import run_app

            return run_app(
                config_dir=args.config_dir, lock=single_instance, with_tray=not args.no_tray
            )

        from src.ui.app import run_app

        return run_app(config_dir=args.config_dir, lock=single_instance)
```

**Step 4: Run test to verify it passes**

Run: `xvfb-run -a uv run pytest tests/test_ui_application.py -q -m gtk`
Expected: все тесты файла проходят.

**Step 5: Run the whole suite**

```bash
uv run pytest -q
make test-gtk
uv run ruff check src tests && uv run ruff format --check src tests
```

**Step 6: Commit**

```bash
git add src/ui/application.py gui.py tests/
git commit -m "feat: publish the tray icon from the GTK4 application"
```

---

## Task 4.10: Живая проверка

**Files:** нет — только наблюдение.

**ВАЖНО.** У пользователя работает установленная в систему GTK3-версия. Её
нельзя закрывать, а подключение и отключение проверять запрещено. Все проверки
идут на копии конфигурации и не трогают соединение.

**Step 1: Prepare a copy of the configuration**

```bash
SP=/tmp/claude-1000/-home-laptop-workdir-code-tenga-proxy-project-tenga-proxy/f2de5ba3-9489-4222-8d9e-cbb377c00643/scratchpad
rm -rf "$SP/cfg_p4" && cp -r ~/.config/tenga-proxy "$SP/cfg_p4"
rm -f "$SP/cfg_p4/tenga.lock"
```

**Step 2: Note what is on the bus before the test**

```bash
gdbus call --session --dest org.kde.StatusNotifierWatcher \
  --object-path /StatusNotifierWatcher \
  --method org.freedesktop.DBus.Properties.Get \
  org.kde.StatusNotifierWatcher RegisteredStatusNotifierItems
```

Запомнить список: приложение пользователя должно остаться в нём и после теста.

**Step 3: Start the GTK4 application with the tray**

```bash
cd /home/laptop/workdir/code/tenga-proxy-project/tenga-proxy
GDK_BACKEND=x11 TENGA_CONFIG_DIR="$SP/cfg_p4" uv run python gui.py --gtk4 \
  > "$SP/p4-run.log" 2>&1 &
```

**Step 4: Verify the item appeared**

```bash
gdbus call --session --dest org.kde.StatusNotifierWatcher \
  --object-path /StatusNotifierWatcher \
  --method org.freedesktop.DBus.Properties.Get \
  org.kde.StatusNotifierWatcher RegisteredStatusNotifierItems
```

Ожидается новая запись `org.kde.StatusNotifierItem-<pid>-1` **рядом** со старой
записью приложения пользователя.

**Step 5: Read the menu over the bus**

```bash
NAME=org.kde.StatusNotifierItem-<pid>-1
gdbus call --session --dest "$NAME" --object-path /MenuBar \
  --method com.canonical.dbusmenu.GetLayout 0 -1 '[]'
```

Ожидается дерево с пунктами «Статус: Отключено», «Подключить», «Профили»,
«Добавить профиль…», «Открыть окно», «Настройки…», «Выход», и подменю профилей
из 20 пунктов плюс «Показать все…».

**Step 6: Check the icon properties**

```bash
gdbus call --session --dest "$NAME" --object-path /StatusNotifierItem \
  --method org.freedesktop.DBus.Properties.GetAll org.kde.StatusNotifierItem
```

Проверить: `IconName = tenga-proxy-disconnected`, `IconThemePath` указывает на
каталог с иконками, `Menu = /MenuBar`, `Status = Active`.

**Step 7: Take a screenshot of the panel**

Иконку в панели GNOME снять целиком нельзя без захвата экрана, поэтому снимок
окна плюс проверка глазами:

```bash
xwininfo -root -tree | grep '"Tenga Proxy": ("python3"'
import -window <id> "$SP/p4-window.png"
```

Посмотреть на панель: должны быть **две** иконки Tenga — старая (приложение
пользователя, подключено) и новая (тестовая, отключено). Если они неразличимы,
B17 не закрыт и иконки надо переделать.

**Step 8: Click the menu entries that do not touch the connection**

Через меню трея открыть: «Открыть окно», «Настройки…», подменю «Профили»
(только посмотреть список, не выбирать). **Не нажимать** «Подключить» и не
выбирать профиль.

**Step 9: Verify the panel restart survives**

```bash
# Убедиться, что элемент перерегистрируется, если watcher пропадёт и вернётся.
# На GNOME это перезапуск расширения; безопасная замена — проверить лог.
grep -i "tray" "$SP/p4-run.log"
```

Ожидается строка `Tray item registered as org.kde.StatusNotifierItem-…`.

**Step 10: Stop the test application and verify the user's app is intact**

```bash
pkill -f "gui.py --gtk4"
gdbus call --session --dest org.kde.StatusNotifierWatcher \
  --object-path /StatusNotifierWatcher \
  --method org.freedesktop.DBus.Properties.Get \
  org.kde.StatusNotifierWatcher RegisteredStatusNotifierItems
ps -o pid,etime,cmd -p "$(pgrep -f 'tenga-proxy' | head -1)"
```

Приложение пользователя обязано остаться в списке и в процессах; его иконка —
на месте.

**Step 11: Record what was found**

Дописать в этот файл раздел «## Результаты»: коммиты, отклонения от плана,
найденные дефекты, метрики, что не сделано.

---

## Критерий приёмки этапа

- Иконка появляется в панели GNOME рядом с иконкой работающей GTK3-версии.
- Три состояния различимы на глаз при 22 px (B17 закрыт).
- Меню открывается, содержит те же действия, что окно, и вызывает их через
  общие `Gio.Action`.
- Без watcher приложение стартует и работает без единой ошибки в логе.
- `uv run pytest -q` и `make test-gtk` зелёные, `ruff check` и `ruff format
  --check` чистые.
- Приложение пользователя не тронуто: тот же PID, та же иконка, то же
  соединение.
