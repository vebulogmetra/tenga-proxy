# Linux: GTK под дизайн Windows — план реализации

> **Для исполнителя:** использовать навык `superpowers:executing-plans`, выполнять задачи последовательно, TDD: сначала падающий тест. Дизайн: `docs/plans/2026-11-07-linux-ui-parity-design.md`, эталон — снимки `docs/design/windows-ui/*.png` и код `src/ui/qt/`.

**Цель:** GTK-интерфейс повторяет компоновку, состав и состояния Qt-интерфейса: панель подключения слева с голубем, двухстрочный список серверов и диагностика справа, окно настроек с разделами и списком подписок. Название «Veblock» и голубь остаются.

**Архитектура:** цвета состояний и размеры панели описываются один раз в `src/ui/logic/appearance.py`, тексты — в `src/ui/logic/`; оба тулкита их читают. В GTK меняются только `src/ui/window.py`, `src/ui/widgets/`, `src/ui/pages/`, `src/ui/dialogs/settings.py`, `src/ui/style.css` и их тесты. Контроллер, формы, трей и хранилище не трогаются, кроме чтения `close_to_tray`.

**Стек:** Python 3.11+, GTK 4 + libadwaita 1.5, PySide6 (только там, где выносится общее), pytest, ruff.

**База:** `a6f57b4`, 07.11.2026.

**Команды проверки:** `uv run pytest <файлы> -q` для логики, `make test-gtk` для виджетов (нужен дисплей или `xvfb-run`, и `dbus-run-session` — цель сама его поднимает), `make test-qt` там, где задето общее, `python cli.py lint-all` перед каждым коммитом. Сообщения коммитов — короткие, императивные, одной строкой, без trailer'ов (`~/.claude/CLAUDE.md`). Живую TUN-сессию на машине не трогать: тесты интерфейса используют подмены и в сеть не ходят.

**Что уже есть и не переписывается:** `StatusView`, `ConnectionPresentation`, `health_text`, `action_hint` (`src/ui/logic/status.py`); `build_profile_rows`, `SortKey`, `ping_text` (`profiles_view.py`); `monitoring_view` и `routing_rows`; `build_subscription_rows`; `PingProgress`; `RowItem` и восстановление раскрытия, выделения и прокрутки в `ProfilesPage`; `KeyedCombo`, все `_build_*_page` и `save()` в `SettingsDialog`; `AppController`; действия `app.*` и `win.*`; трей.

**Правила, которые проверяют тесты и нельзя сломать:** `tests/test_ui_platform_branches.py` — `IS_WINDOWS` только в `platform_texts.py`; `tests/test_branding.py` — «Tenga Proxy» в интерфейсе нет; `tests/test_sys_facades.py` не затрагивается. Монолит (`assets/icons/win`) в GTK не импортируется.

---

## Этап 1. Контракт без тулкита

### Задача 1: цвета состояний и размеры панели в `appearance.py`

**Файлы:**
- Изменить: `src/ui/logic/appearance.py`
- Тест: `tests/test_ui_logic_appearance.py`

**Шаг 1: падающий тест**

Добавить в конец `tests/test_ui_logic_appearance.py`:

```python
# --- цвета состояний и размеры ------------------------------------------------


def test_state_colors_match_the_qt_palette():
    from src.ui.logic.appearance import ACCENT, GLOW_COLORS, STATE_COLORS, glow_color

    assert ACCENT == "#36c9b5"
    assert STATE_COLORS["status-connected"] == "#36c9b5"
    assert STATE_COLORS["status-connecting"] == "#ffa64d"
    assert STATE_COLORS["status-error"] == STATE_COLORS["status-blocked"] == "#e07078"
    assert STATE_COLORS["status-disconnected"] == "#8a969d"
    # Свечение: бирюзовое у подключения, оранжевое у операции, красное у ошибки,
    # нет — у отключения и пустого хранилища.
    assert GLOW_COLORS["status-connected"] == "#5ed3c7"
    assert glow_color("status-connecting") == "#ffa64d"
    assert glow_color("status-disconnected") is None
    assert glow_color("status-empty") is None
    assert glow_color("unknown-class") is None


def test_panel_sizes_are_shared():
    from src.ui.logic.appearance import (
        COMPACT_HEIGHT,
        LOGO_SIZE,
        LOGO_SIZE_COMPACT,
        PANEL_MAX_WIDTH,
        PANEL_MIN_WIDTH,
    )

    assert (PANEL_MIN_WIDTH, PANEL_MAX_WIDTH) == (280, 360)
    assert LOGO_SIZE > LOGO_SIZE_COMPACT > 0
    assert COMPACT_HEIGHT == 680
```

**Шаг 2: убедиться, что падает**

Run: `uv run pytest tests/test_ui_logic_appearance.py -q`
Expected: FAIL, `ImportError: cannot import name 'ACCENT'`

**Шаг 3: реализация**

Дописать в `src/ui/logic/appearance.py`:

```python
# Цвета состояний общие для GTK и Qt. Всё остальное — системная палитра.
ACCENT = "#36c9b5"
ERROR_TEXT = "#d13438"

STATE_COLORS = {
    "status-connected": ACCENT,
    "status-connecting": "#ffa64d",
    "status-disconnecting": "#ffa64d",
    "status-error": "#e07078",
    "status-blocked": "#e07078",
    "status-disconnected": "#8a969d",
    "status-empty": "#8a969d",
}

# Свечение под логотипом: его нет при отключении и пустом хранилище.
GLOW_COLORS = {
    "status-connected": "#5ed3c7",
    "status-connecting": "#ffa64d",
    "status-disconnecting": "#ffa64d",
    "status-error": "#e07078",
    "status-blocked": "#e07078",
}

PANEL_MIN_WIDTH = 280
PANEL_MAX_WIDTH = 360
LOGO_SIZE = 240
LOGO_SIZE_COMPACT = 140
# Ниже этой высоты окна панель переходит в компактный режим.
COMPACT_HEIGHT = 680


def glow_color(css_class: str) -> str | None:
    """Colour of the halo under the logo, or None when there is no halo."""
    return GLOW_COLORS.get(css_class)
```

**Шаг 4: проверить**

Run: `uv run pytest tests/test_ui_logic_appearance.py -q`
Expected: PASS

**Шаг 5: коммит**

```bash
git add src/ui/logic/appearance.py tests/test_ui_logic_appearance.py
git commit -m "ui: общие цвета состояний и размеры панели"
```

### Задача 2: Qt читает цвета из `appearance.py`

Чтобы значения не разъехались, Qt берёт их из общего модуля; QSS остаётся файлом, но тест сверяет его с константами.

**Файлы:**
- Изменить: `src/ui/qt/widgets/status_card.py:47-60`, `src/ui/qt/widgets/profile_delegate.py:110,135`, `src/ui/qt/dialogs/settings.py:96`
- Тест: `tests/test_ui_qt_theme.py`

**Шаг 1: падающий тест** (без маркера `qt`: читает только файлы)

```python
def test_qss_uses_the_shared_state_colors():
    from pathlib import Path

    from src.ui.logic.appearance import ACCENT, STATE_COLORS

    qss = Path("src/ui/qt/style.qss").read_text(encoding="utf-8")
    assert ACCENT in qss
    for css_class in ("status-connected", "status-connecting", "status-error"):
        assert STATE_COLORS[css_class] in qss


def test_qt_monolith_glow_comes_from_appearance():
    import inspect

    from src.ui.qt.widgets import status_card

    source = inspect.getsource(status_card)
    assert "GLOW_COLORS" in source or "glow_color" in source
    assert "#ffa64d" not in source
```

Второй тест пропускать через `pytest.importorskip("PySide6")`.

**Шаг 2–4:** в `status_card.py` заменить словарь `{...}.get(css_class, b"#5ed3c7")` на `(glow_color(css_class) or STATE_COLORS["status-disconnected"]).encode()`, сохранив текущее поведение для `status-disconnected` (цвет `#8a969d`, прозрачность гало 0) и `status-empty`. В делегате и настройках — `QColor(ACCENT)` и f-строка с `ACCENT`.

Run: `make test-qt` — всё зелёное, включая `test_ui_qt_widgets.py::test_disabled_button_keeps_the_orange_glow` (имя проверить в файле).

**Шаг 5: коммит** — `qt: цвета состояний из appearance`

### Задача 3: общие тексты и пункт «Журнал…»

**Файлы:**
- Изменить: `src/ui/logic/profiles_view.py`, `src/ui/logic/monitoring_view.py`, `src/ui/logic/menus.py`, `src/ui/logic/settings_form.py`
- Изменить: `src/ui/qt/window.py:188-189, 272-274, 375-377, 545-549, 594-598`, `src/ui/qt/dialogs/settings.py:215, 248-255, 700-717`, `src/ui/qt/application.py` (обработчик `show-log`)
- Тест: `tests/test_ui_logic_profiles_view.py`, `tests/test_ui_logic_monitoring_view.py`, `tests/test_ui_menus.py`, `tests/test_ui_logic_settings_form.py`

**Шаг 1: падающие тесты**

```python
# tests/test_ui_logic_profiles_view.py
def test_no_results_text_is_shared():
    from src.ui.logic.profiles_view import NO_RESULTS_TEXT, SELECTED_NONE, selected_text

    assert NO_RESULTS_TEXT == "Ничего не найдено. Измените запрос."
    assert SELECTED_NONE == "Сервер не выбран"
    assert selected_text("🇩🇪 Берлин") == "Выбран: Берлин"
    assert selected_text("") == SELECTED_NONE


# tests/test_ui_logic_monitoring_view.py
def test_check_pending_texts_are_shared():
    from src.ui.logic.monitoring_view import LAST_CHECK_PENDING, NOT_CHECKED, last_check_text

    assert NOT_CHECKED == "Проверка ещё не выполнена"
    assert LAST_CHECK_PENDING == "Ожидается проверка соединения"
    assert last_check_text(0.0) == LAST_CHECK_PENDING
    assert last_check_text(1_700_000_000.0).startswith("Последняя проверка: ")


# tests/test_ui_menus.py
def test_main_menu_has_the_log_item_after_settings():
    from src.ui.logic.menus import MAIN_MENU

    names = [name for name, _label in MAIN_MENU]
    assert names.index("show-log") == names.index("settings") + 1
    assert dict(MAIN_MENU)["show-log"] == "Журнал…"


# tests/test_ui_logic_settings_form.py
def test_save_status_texts():
    from src.ui.logic.settings_form import (
        SAVE_DONE,
        SAVE_FAILED,
        SAVE_IDLE,
        SAVE_PENDING,
        SAVE_RECONNECT,
        save_status_text,
    )

    assert SAVE_IDLE == "Изменения сохраняются автоматически"
    assert SAVE_PENDING == "Ожидание сохранения…"
    assert SAVE_FAILED == "Не удалось сохранить настройки. Повторите изменение."
    assert save_status_text(saved=True, reconnect=False) == SAVE_DONE == "Изменения сохранены"
    assert save_status_text(saved=True, reconnect=True) == f"{SAVE_DONE} · {SAVE_RECONNECT}"
    assert save_status_text(saved=False, reconnect=False) == SAVE_FAILED
```

Для `selected_text` использовать уже существующее отделение флага: в Qt это `flagged()` из `src/ui/qt/icons.py`; если общего помощника без тулкита нет, добавить `split_flag(text) -> tuple[str, str]` в `src/ui/logic/country_flags.py` и покрыть тестом.

**Шаг 2: убедиться, что падают** — `uv run pytest tests/test_ui_logic_profiles_view.py tests/test_ui_logic_monitoring_view.py tests/test_ui_menus.py tests/test_ui_logic_settings_form.py -q`

**Шаг 3: реализация**

- `profiles_view.py`: `NO_RESULTS_TEXT`, `SELECTED_NONE`, `SELECTED_PREFIX = "Выбран: "`, `selected_text(name)`.
- `monitoring_view.py`: `NOT_CHECKED`, `LAST_CHECK_PENDING`, `LAST_CHECK_PREFIX = "Последняя проверка: "`, `last_check_text(timestamp)`.
- `menus.py`: `("show-log", "Журнал…")` после `settings`; убрать комментарий «добавляет Qt». 
- `settings_form.py`: пять констант и `save_status_text`.
- Qt: в `window.py` убрать ручную вставку «Журнал…» и подставить константы вместо строк; `show-log` в `src/ui/qt/application.py` ведёт на `window.show_diagnostics()`; в `dialogs/settings.py` строки статуса — из констант.

**Шаг 4: проверить** — логика зелёная; `make test-qt` зелёный (поправить `test_ui_qt_monolith.py::…меню…`, если он сравнивает список подписей вручную).

**Шаг 5: коммит** — `ui: общие тексты диагностики, выделения и статуса сохранения`

### Задача 4: геометрия окна

**Файлы:**
- Изменить: `src/ui/logic/geometry.py:13-14, 29`
- Тест: `tests/test_ui_logic_geometry.py`

**Шаг 1: падающий тест**

```python
def test_window_minimum_and_default_match_qt():
    from src.ui.logic.geometry import DEFAULT_GEOMETRY, MIN_HEIGHT, MIN_WIDTH, parse_geometry

    assert (MIN_WIDTH, MIN_HEIGHT) == (900, 540)
    assert (DEFAULT_GEOMETRY.width, DEFAULT_GEOMETRY.height) == (1180, 760)
    # Сохранённый размер старого окна поднимается до нового минимума.
    saved = parse_geometry("640,760,0,0,0")
    assert (saved.width, saved.height) == (900, 760)
```

**Шаг 2–4:** поменять константы, исправить комментарий о брейкпоинте (его больше нет), прогнать `uv run pytest tests/test_ui_logic_geometry.py -q` и поправить старые ожидания в нём.

**Шаг 5: коммит** — `ui: минимум окна 900×540, обычный 1180×760`

### Задача 5: общий дизайн-документ

**Файлы:** `docs/plans/2026-11-02-shared-ui-design.md`

Без теста. Переписать: «Намеренных отличий в дизайне два» → одно (логотип); раздел «Намеренное отличие: навигация» переименовать в «Окно» и описать общую компоновку (панель слева, серверы и диагностика справа, подписки в настройках, «Журнал…» в меню на обоих); таблицу «Главное окно» и «Метрики и режим» привести к Qt (столбики метрик везде); убрать оговорки «только Windows» у «Обновить подписку», «Журнал…», кнопки «Пинг» и сортировки; добавить таблицу «Что есть только на одной ОС» (kill switch, проверка TUN, NetworkManager, трей SNI — Linux; служба, установщик — Windows); в «Расхождения» оставить только то, что останется после этого плана. Цвета сослать на `appearance.py`.

**Коммит** — `docs: общий дизайн после переноса компоновки на Linux`

---

## Этап 2. Панель состояния

### Задача 6: свечение под логотипом

**Файлы:**
- Создать: `src/ui/widgets/logo_glow.py`
- Тест: `tests/test_ui_widgets_status_card.py`

**Шаг 1: падающий тест** (маркер `gtk`)

```python
def test_glow_follows_the_state_colour(gtk_ready):
    from src.ui.widgets.logo_glow import LogoGlow

    glow = LogoGlow()
    assert glow.get_color_for_test() is None

    glow.set_color("#5ed3c7")
    assert glow.get_color_for_test() == "#5ed3c7"
    assert glow.get_visible() is True

    glow.set_color(None)
    assert glow.get_visible() is False
```

**Шаг 2: падает** — `make test-gtk` (или `uv run pytest -m gtk tests/test_ui_widgets_status_card.py -q` внутри `dbus-run-session`), `ModuleNotFoundError`.

**Шаг 3: реализация**

```python
"""Soft halo drawn under the logo button; its colour names the connection state."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gdk, Gtk


class LogoGlow(Gtk.DrawingArea):
    """Radial gradient that fades from the state colour to transparent.

    Отдельный виджет, а не CSS box-shadow у кнопки: тень в Adwaita не
    масштабируется вместе с картинкой и режется рамкой кнопки.
    """

    __gtype_name__ = "TengaLogoGlow"

    def __init__(self) -> None:
        super().__init__(visible=False, can_target=False)
        self._color: str | None = None
        self.set_draw_func(self._draw)

    def set_color(self, color: str | None) -> None:
        """Set the halo colour; None hides the halo entirely."""
        if color == self._color:
            return
        self._color = color
        self.set_visible(color is not None)
        self.queue_draw()

    def _draw(self, _area, cr, width: int, height: int) -> None:
        if self._color is None:
            return
        rgba = Gdk.RGBA()
        rgba.parse(self._color)
        cx, cy = width / 2, height * 0.62
        radius = min(width, height) * 0.48
        import cairo

        pattern = cairo.RadialGradient(cx, cy, radius * 0.15, cx, cy, radius)
        pattern.add_color_stop_rgba(0.0, rgba.red, rgba.green, rgba.blue, 0.45)
        pattern.add_color_stop_rgba(0.55, rgba.red, rgba.green, rgba.blue, 0.18)
        pattern.add_color_stop_rgba(1.0, rgba.red, rgba.green, rgba.blue, 0.0)
        cr.set_source(pattern)
        cr.rectangle(0, 0, width, height)
        cr.fill()

    def get_color_for_test(self) -> str | None:
        return self._color
```

`cairo` импортировать на уровне модуля (`import cairo` — пакет `pycairo` уже зависимость PyGObject). Свечение перерисовывается только при смене цвета, не на тиках трафика.

**Шаг 4: проходит.** **Шаг 5: коммит** — `ui: виджет свечения под логотипом`

### Задача 7: вертикальная карточка состояния

**Файлы:**
- Изменить: `src/ui/widgets/status_card.py` (переписать компоновку), `src/ui/style.css`
- Тест: `tests/test_ui_widgets_status_card.py`

**Шаг 1: падающие тесты.** Заменить тесты спиннера, предупреждения, `get_summary` и `switch_button` на:

```python
def test_card_is_a_vertical_panel_with_glow(card):
    from gi.repository import Gtk

    from src.ui.logic.status import ConnectionState
    from src.ui.widgets.logo_glow import LogoGlow

    assert card.get_orientation() == Gtk.Orientation.VERTICAL
    assert isinstance(card.glow, LogoGlow)

    card.update(_view(ConnectionState.CONNECTED, profile_name="X"))
    assert card.glow.get_color_for_test() == "#5ed3c7"
    card.update(_view(ConnectionState.CONNECTING, profile_name="X"))
    assert card.glow.get_color_for_test() == "#ffa64d"
    card.update(_view(ConnectionState.ERROR, profile_name="X"))
    assert card.glow.get_color_for_test() == "#e07078"
    card.update(_view(ConnectionState.DISCONNECTED))
    assert card.glow.get_color_for_test() is None


def test_card_has_no_badges_over_the_logo(card):
    assert not hasattr(card, "_spinner")
    assert not hasattr(card, "_warning")


def test_instruction_and_dot_follow_the_state(card):
    from src.ui.logic.status import ConnectionState, action_hint

    view = _view(ConnectionState.CONNECTED, profile_name="X")
    card.update(view)
    assert card.get_instruction() == action_hint(view)
    assert "status-connected" in card.dot.get_css_classes()
    assert card.get_server_caption() == "Активный сервер"

    card.update(_view(ConnectionState.DISCONNECTED, profile_name="X"))
    assert card.get_server_caption() == "Сервер"


def test_metrics_are_columns_and_empty_ones_hide(card):
    from src.ui.logic.status import ConnectionState

    card.update(_view(ConnectionState.CONNECTED, profile_name="X", latency_ms=42))
    assert card.get_metrics() == [("Задержка", "42 мс")]

    card.update(
        _view(ConnectionState.CONNECTED, profile_name="X", upload_bytes=12, download_bytes=128)
    )
    assert [caption for caption, _ in card.get_metrics()] == ["↓ Получено", "↑ Отправлено"]
    assert card.get_mode() == ""

    card.update(_view(ConnectionState.CONNECTED, profile_name="X", mode="Режим TUN"))
    assert card.get_mode() == "Режим TUN"


def test_compact_mode_shrinks_the_logo(card):
    from src.ui.logic.appearance import LOGO_SIZE, LOGO_SIZE_COMPACT

    assert card.logo_image.get_pixel_size() == LOGO_SIZE
    card.set_property("compact", True)
    assert card.logo_image.get_pixel_size() == LOGO_SIZE_COMPACT
    assert "compact" in card.get_css_classes()


def test_card_no_longer_owns_the_switch_button(card):
    assert not hasattr(card, "switch_button")
```

Оставить и адаптировать: заголовок и подпись, `button_label`, замена CSS-класса, подсказка и доступное имя кнопки, `set_health`, `shows_logo`, логотип обесцвечен вне `connected`.

**Шаг 2: падает.**

**Шаг 3: реализация.** Переписать `StatusCard(Gtk.Box)` вертикальной, `halign=FILL`, `set_size_request(PANEL_MIN_WIDTH, -1)`, в окне ограничивать `PANEL_MAX_WIDTH` через `Adw.Clamp(maximum_size=PANEL_MAX_WIDTH, tightening_threshold=PANEL_MIN_WIDTH)`. Состав сверху вниз, все по центру (`halign=CENTER`):

```python
compact = GObject.Property(type=bool, default=False)  # сеттер брейкпоинта

overlay = Gtk.Overlay(child=self.logo_image)          # pixel_size=LOGO_SIZE
self.glow = LogoGlow()
overlay.add_overlay(self.glow); overlay.set_measure_overlay(self.glow, False)
# свечение ПОД картинкой: overlay рисует детей поверх child, поэтому child —
# пустой Gtk.Box нужного размера, а overlays: glow, затем logo_image.
self.logo_button = Gtk.Button(child=overlay); classes "flat", "logo-button"

self._instruction = Gtk.Label(wrap=True, justify=CENTER); classes "caption", "dim-label"
dot_row = Gtk.Box(spacing=6, halign=CENTER)
self.dot = Gtk.Label(label="●"); class "connection-dot"
self._title = Gtk.Label(); classes "title-2"
self._server_caption = Gtk.Label(); classes "caption", "dim-label"
name_row: self._flag (Gtk.Image 16px, из src/ui/logic/country_flags) + self._subtitle (ellipsize END, tooltip = полное имя)
Gtk.Separator(margin 8)
self._mode = Gtk.Label(); classes "caption", "dim-label"
self._metrics = Gtk.Box(spacing=16, halign=CENTER, homogeneous=True)  # три колонки: value (class "metric-value") над caption
Gtk.Box(vexpand=True)  # растяжка
Gtk.Separator
self._health = Gtk.Label(wrap=True, justify=CENTER); classes "caption"
```

`update(view)`:
- `self.glow.set_color(glow_color(view.css_class))`;
- `self._instruction.set_text(action_hint(view))`;
- классы состояния переставлять и на карточке, и на `self.dot` (`_STATE_CLASSES` плюс `status-empty`, если `status_view` его выдаёт — проверить в `status.py:255-284`);
- `self._server_caption`: «Активный сервер» при `status-connected`, иначе «Сервер»; скрыть вместе с именем, если `subtitle` пустой;
- `self._mode.set_text(view.mode)`, видимость по непустому;
- метрики: пересоздавать три колонки только при смене набора подписей, иначе обновлять текст значений (тики трафика раз в секунду);
- флаг: `split_flag(view.subtitle)`; без флага виджет скрыт.

`compact` через `notify::compact`: `pixel_size` = `LOGO_SIZE_COMPACT`, класс `compact` на карточке (CSS уменьшает заголовок и отступы). `LOGO_LOAD_SIZE = LOGO_SIZE * 2`, грузить из `logo_inner.png` (1024), а не `logo-inner-256.png`; `build_deb.sh:61` сейчас удаляет `logo_inner.png` из пакета — убрать его из списка удаляемых и добавить проверку наличия в строках 73-80.

Аксессоры для тестов: `get_instruction`, `get_server_caption`, `get_mode`, `get_metrics() -> list[tuple[str, str]]`. Удалить `get_summary`, `is_spinning`, `set_switch_target`, сигнал `switch-clicked`.

CSS (`src/ui/style.css`): убрать правила `.status-icon`, `.status-warning`, `.status-summary`, `.metrics`; добавить

```css
.status-card { padding: 20px 20px 12px; }
.status-card .logo-button { padding: 8px; border-radius: 16px; }
.status-card .status-logo { opacity: 0.55; }
.status-card.status-connected .status-logo { opacity: 1; }
.status-card .connection-dot { color: #8a969d; font-size: 1.3em; }
.status-card .connection-dot.status-connected { color: #36c9b5; }
.status-card .connection-dot.status-connecting { color: #ffa64d; }
.status-card .connection-dot.status-error,
.status-card .connection-dot.status-blocked { color: #e07078; }
.status-card .metric-value { color: #36c9b5; font-size: 1.25em; font-weight: 600; font-feature-settings: "tnum"; }
.status-card.compact .title-2 { font-size: 1.2em; }
```

Hex-значения в CSS — те же, что в `appearance.py`; добавить в `tests/test_ui_styles.py` тест без дисплея, который читает `style.css` и проверяет наличие `ACCENT` и `STATE_COLORS["status-connecting"]`, `["status-error"]`, `["status-disconnected"]`.

**Шаг 4:** `make test-gtk` по `tests/test_ui_widgets_status_card.py tests/test_ui_styles.py`. Остальные GTK-тесты пока падают (окно ещё зовёт `set_switch_target`) — это нормально до задачи 9; в коммит не включать красный прогон всего набора, но назвать его в сообщении этапа.

**Шаг 5: коммит** — `ui: вертикальная карточка состояния с голубем и свечением`

---

## Этап 3. Главное окно и список серверов

### Задача 8: двухстрочная строка сервера

**Файлы:**
- Создать: `src/ui/widgets/profile_row.py`
- Изменить: `src/ui/pages/profiles.py` (ListView вместо ColumnView), `src/ui/style.css`
- Тест: `tests/test_ui_pages_profiles.py`

**Шаг 1: падающие тесты** (к существующим; удалить те, что читают колонки `column_view`)

```python
def test_tree_is_a_list_view_with_two_line_rows(page):
    from gi.repository import Gtk

    assert isinstance(page.list_view, Gtk.ListView)
    assert not hasattr(page, "column_view")


def test_profile_row_shows_type_address_latency_and_badge(page, two_groups):
    page.set_active_profile(profile_id=2)
    page.set_data(*two_groups)
    page.expand_all()

    row = page.row_widget_for_test(profile_id=2)
    assert row.get_title() == "Берлин"
    assert row.get_details() == "VLESS · de.example.org:443"
    assert row.get_latency() == "42 мс"
    assert row.get_badge() == "Подключён"
    assert "profile-active" in row.get_css_classes()

    other = page.row_widget_for_test(profile_id=1)
    assert other.get_badge() == ""
    assert "profile-active" not in other.get_css_classes()


def test_ping_button_tests_only_its_server(page, two_groups):
    page.set_data(*two_groups)
    page.expand_all()
    seen = []
    page.connect("profile-ping", lambda _p, pid: seen.append(pid))

    page.row_widget_for_test(profile_id=1).ping_button.emit("clicked")
    assert seen == [1]


def test_menu_button_opens_the_same_context_menu(page, two_groups):
    page.set_data(*two_groups)
    page.expand_all()

    row = page.row_widget_for_test(profile_id=1)
    assert row.menu_button.get_tooltip_text() == "Действия"
    assert page.context_menu_labels_for_test(profile_id=1) == [
        "Подключить", "VPN и маршруты…", "Тест задержки", "Редактировать", "Удалить"
    ]


def test_group_row_summary_and_progress(page, two_groups):
    from src.ui.logic.latency import PingProgress

    page.set_data(*two_groups)
    group = page.row_widget_for_test(group_id=10)
    assert group.get_title() == "Default"
    assert group.get_summary() == "Серверов: 2"

    progress = PingProgress({10: 2}); progress.record(10)
    page.set_ping_progress(progress)
    page.update_group_progress(10)
    assert group.get_summary() == "Серверов: 2 · Проверено: 1 / 2"
    assert group.progress.get_visible() is True
```

Фикстура `two_groups` — две группы (подписка и обычная) с двумя серверами, профиль 2 с `latency_ms=42`, `bean.display_address="de.example.org:443"`, `proxy_type="vless"`; посмотреть, как собирают данные существующие тесты файла, и переиспользовать их помощник. Сводку группы брать из общей функции: вынести из `src/ui/qt/models.py:51-55` `group_summary(row, progress, details)` в `src/ui/logic/profiles_view.py` и покрыть тестом в `test_ui_logic_profiles_view.py`; Qt переключить на неё.

**Шаг 2: падают.**

**Шаг 3: реализация.**

`src/ui/widgets/profile_row.py`:

```python
class ProfileRowWidget(Gtk.Box):
    """Two-line server row: name; type · address; latency, badge, ping, menu."""
    __gsignals__ = {"ping-clicked": ..., "menu-clicked": ...}
    # layout: [marker 3px] [text_box: title(bold, ellipsize) / details(dim, ellipsize)]
    #         [right_box: latency(top, tnum) / badge(bottom, class accent-text)] [ping_button "Пинг"] [menu_button ⋮ "Действия"]
    def bind(self, row: ProfileRow) -> None: ...
    def get_title/get_details/get_latency/get_badge(self) -> str

class GroupRowWidget(Gtk.Box):
    """Group header: icon, title, summary, progress bar underneath."""
    def bind(self, row: GroupRow, summary: str, fraction: float | None) -> None: ...
    def get_title/get_summary(self) -> str
```

`ProfilesPage`:
- `Gtk.ListView(model=SingleSelection(TreeListModel))`, одна фабрика: в `setup` создаётся `Gtk.TreeExpander` с пустым дочерним; в `bind` по `item.is_group` ставится `GroupRowWidget` или `ProfileRowWidget` (кэшировать по `list_item`, чтобы не пересоздавать при повторном bind одного типа);
- сигналы `ping-clicked` → `self.emit("profile-ping", profile_id)`; `menu-clicked` → `self._popup_menu_at(widget, item)` — тот же `Gtk.PopoverMenu`, что у правого клика, с `set_parent(menu_button)`;
- `row_widget_for_test(profile_id=…|group_id=…)` обходит `list_view` через `get_first_child()`/`get_next_sibling()`;
- `_ACTIVE_CLASS` ставить на строку целиком; маркер — `Gtk.Box` 3 px с классом `active-marker`, видим по `is_active`;
- `set_sort`, восстановление раскрытия/выделения/прокрутки, жесты правого клика и долгого нажатия — без изменений (жесты перевесить на `list_view`).

CSS:

```css
.profiles-list > row { min-height: 64px; padding: 0; }
.profiles-list > row:selected { border-radius: 6px; }
.profile-row { padding: 8px 12px 8px 8px; }
.profile-row .active-marker { background: #36c9b5; border-radius: 2px; min-width: 3px; margin: 8px 8px 8px 0; }
.profile-row .accent-text { color: #36c9b5; }
.profile-row .details { font-size: 0.9em; }
.group-row { padding: 10px 12px; font-weight: bold; }
```

Правило `.profile-active` оставить только для цвета имени; `.profiles-tree` → `.profiles-list`.

**Шаг 4:** `make test-gtk` по `tests/test_ui_pages_profiles.py` и `tests/test_ui_logic_profiles_view.py` через `uv run pytest`. **Шаг 5: коммит** — `ui: двухстрочные строки серверов на Gtk.ListView`

### Задача 9: страница серверов — инструменты, сортировка, строка выделения

**Файлы:**
- Изменить: `src/ui/pages/profiles.py`
- Тест: `tests/test_ui_pages_profiles.py`

**Шаг 1: падающие тесты**

```python
def test_search_entry_is_always_visible(page):
    from src.ui.logic.profiles_view import SEARCH_PLACEHOLDER

    assert not hasattr(page, "search_bar")
    assert page.search_entry.get_visible() is True
    assert page.search_entry.get_placeholder_text() == SEARCH_PLACEHOLDER


def test_tools_row_has_add_and_sort_menus(page):
    from src.ui.logic.menus import ADD_MENU

    assert page.add_button.get_label() == "Добавить…"
    assert page.menu_labels_for_test(page.add_button) == [label for _n, label in ADD_MENU]
    assert page.sort_button.get_label() == "Сортировка"
    assert page.menu_labels_for_test(page.sort_button) == ["По имени", "По типу", "По задержке"]


def test_choosing_the_same_sort_key_flips_the_direction(page, two_groups):
    from src.ui.logic.profiles_view import SortKey

    page.set_data(*two_groups)
    page.activate_sort_for_test("type")
    assert page.get_sort_for_test() == (SortKey.TYPE, True)
    page.activate_sort_for_test("type")
    assert page.get_sort_for_test() == (SortKey.TYPE, False)
    page.activate_sort_for_test("name")
    assert page.get_sort_for_test() == (SortKey.NAME, True)


def test_no_results_text_when_search_matches_nothing(page, two_groups):
    from src.ui.logic.profiles_view import NO_RESULTS_TEXT

    page.set_data(*two_groups)
    page.set_query("нет такого")
    assert page.get_visible_state() == "empty"
    assert page.get_empty_title() == NO_RESULTS_TEXT


def test_selection_row_names_the_target_and_offers_the_switch(page, two_groups):
    from src.ui.logic.profiles_view import SELECTED_NONE
    from src.ui.logic.status import SWITCH_LABEL

    page.set_data(*two_groups)
    assert page.get_selection_text() == SELECTED_NONE
    assert page.switch_button.get_visible() is False

    page.expand_all()
    page.select_profile(1)
    assert page.get_selection_text() == "Выбран: Амстердам"

    page.set_switch_target("Амстердам", enabled=True)
    assert page.switch_button.get_visible() is True
    assert page.switch_button.get_label() == SWITCH_LABEL
    assert page.switch_button.get_tooltip_text() == "Подключить: Амстердам"
```

**Шаг 2: падают.**

**Шаг 3: реализация.** Внешний контейнер страницы — `Gtk.Box` с классом `card` и `library-card`, отступы 12/16; внутри:

1. `tools = Gtk.Box(spacing=8)`: `self.search_entry` (`hexpand`), `self.add_button = Gtk.MenuButton(label="Добавить…", menu_model=ADD_MENU)` (перенести `_build_add_button` из окна), `self.sort_button = Gtk.MenuButton(label="Сортировка")` с `Gio.Menu` из пунктов `win.sort-profiles('name'|'type'|'ping')` — действие окна с параметром `s`; проще — `Gio.SimpleActionGroup` на странице под префиксом `page` (`insert_action_group("page", group)`), тогда тесты страницы не зависят от окна.
2. `self._stack` (`empty`/`list`), `_empty_page` получает `set_title(NO_RESULTS_TEXT)` и пустое описание при непустом запросе, иначе `EMPTY_TITLE`/`EMPTY_DESCRIPTION`.
3. `selection = Gtk.Box(spacing=8)`: `self._selection_label` (`xalign=0`, ellipsize, tooltip `TYPE · адрес`), `self.switch_button` (`halign=END`, `hexpand`), сигнал `switch-clicked` переезжает сюда из карточки; `set_switch_target(name, *, enabled)` — тот же контракт, что был у `StatusCard`.

Дополнительно: `focus_search()` — `grab_focus` + выделить текст; `set_search_enabled` удалить; `menu_labels_for_test(button)` читает `Gio.Menu` кнопки; `activate_sort_for_test(key)`, `get_sort_for_test()`, `get_empty_title()`, `get_selection_text()`.

**Шаг 4:** зелёный `tests/test_ui_pages_profiles.py`. **Шаг 5: коммит** — `ui: поиск, сортировка и строка выделения на странице серверов`

### Задача 10: каркас окна — шапка, две колонки, стек

**Файлы:**
- Изменить: `src/ui/window.py`, `src/ui/application.py` (действие `search`, `show-log`, кнопка-переключатель)
- Тест: `tests/test_ui_window.py`, `tests/test_ui_application.py`

**Шаг 1: падающие тесты.** Заменить `test_window_has_three_pages`, `test_narrow_window_moves_the_switcher_down`, тесты поиска по страницам на:

```python
def test_window_has_a_side_panel_and_two_right_pages(window):
    from gi.repository import Gtk

    from src.ui.widgets.status_card import StatusCard

    assert isinstance(window.status_card, StatusCard)
    assert not hasattr(window, "view_stack")
    assert not hasattr(window, "view_switcher")
    assert [window.right_stack.get_child_by_name(n) is not None for n in ("servers", "monitoring")] == [True, True]
    assert window.right_stack.get_visible_child_name() == "servers"
    assert isinstance(window.columns, Gtk.Box)
    assert window.columns.get_first_child() is window.panel_clamp


def test_header_shows_the_page_title_and_actions(window):
    assert window.page_title.get_text() == "Серверы"
    assert window.back_button.get_visible() is False
    assert window.settings_button.get_label() == "Настройки"
    assert window.menu_button.get_tooltip_text() == "Главное меню"
    assert not hasattr(window, "search_button")


def test_main_menu_follows_the_shared_list(window):
    from src.ui.logic.menus import MAIN_MENU

    labels = _menu_labels(window.menu_button.get_menu_model())
    assert labels == [label for _n, label in MAIN_MENU]


def test_search_action_focuses_the_entry_and_returns_to_servers(window, adw_app):
    window.diagnostics_toggle.set_active(True)
    adw_app.activate_action("search", None)
    assert window.right_stack.get_visible_child_name() == "servers"
    assert window.profiles_page.search_entry.has_focus() or window.profiles_page.search_entry.is_focus()


def test_short_window_makes_the_panel_compact(window):
    from gi.repository import GLib

    window.set_default_size(900, 560)
    window.present()
    context = GLib.MainContext.default()
    deadline = GLib.get_monotonic_time() + 5_000_000
    while window.get_current_breakpoint() is None and GLib.get_monotonic_time() < deadline:
        context.iteration(True)

    assert window.status_card.get_property("compact") is True


def test_switch_button_lives_on_the_servers_page(window, adw_app):
    _two_profiles(adw_app)
    adw_app.context.proxy_state.is_running = True
    adw_app.context.proxy_state.started_profile_id = 1
    window.refresh_pages()
    window.profiles_page.expand_all()
    window.profiles_page.select_profile(2)
    window.refresh_status()

    assert window.profiles_page.switch_button.get_visible() is True
    assert not hasattr(window.status_card, "switch_button")
```

Помощник `_menu_labels(model)` — рекурсивно читает `Gio.MenuModel` (атрибут `label`).

**Шаг 2: падают.**

**Шаг 3: реализация `MainWindow._build_ui`.**

```python
header = Adw.HeaderBar()
self.back_button = Gtk.Button(label="← Серверы", visible=False)
self.back_button.connect("clicked", lambda _b: self.diagnostics_toggle.set_active(False))
header.pack_start(self.back_button)
self.page_title = Gtk.Label(label="Серверы"); classes "title"
header.set_title_widget(self.page_title)
self.settings_button = Gtk.Button(label="Настройки", action_name="app.settings")
self.menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=main_menu, tooltip_text="Главное меню")
header.pack_end(self.menu_button); header.pack_end(self.settings_button)

self.columns = Gtk.Box(orientation=HORIZONTAL)
self.panel_clamp = Adw.Clamp(child=self.status_card, maximum_size=PANEL_MAX_WIDTH, tightening_threshold=PANEL_MIN_WIDTH, hexpand=False)
self.columns.append(self.panel_clamp)
self.columns.append(Gtk.Separator(orientation=VERTICAL))

right = Gtk.Box(orientation=VERTICAL, hexpand=True); margins 8
right.append(self.pending_banner); right.append(self.blocked_banner)
self.right_stack = Gtk.Stack(vexpand=True)
servers = Gtk.Box(orientation=VERTICAL, spacing=8)
servers.append(self.profiles_page)                      # vexpand
footer = Gtk.Box(); self.diagnostics_toggle = Gtk.ToggleButton(label="Диагностика"); spacer; self.latency_button = Gtk.Button(label="Проверить задержку", action_name="app.test-latency")
servers.append(footer)
self.right_stack.add_named(servers, "servers")
self.right_stack.add_named(self.monitoring_page, "monitoring")
right.append(self.right_stack)
self.columns.append(right)
toolbar.set_content(self.columns)
```

Ширина панели: `Adw.Clamp` не задаёт минимум — `status_card.set_size_request(PANEL_MIN_WIDTH, -1)` (уже в задаче 7). Брейкпоинт один: `MAX_HEIGHT COMPACT_HEIGHT sp` → сеттер `status_card.compact = True`. Удалить `NARROW_WIDTH`, `COMPACT_HEIGHT` из окна (брать из `appearance`), `view_switcher_bar`, `_build_add_button`, `_build_search_button`, `SEARCHABLE_PAGES`, `_visible_search_page`, `_on_page_changed`, `set_search_enabled`, `subscriptions_page` (временно оставить объект без вкладки до задачи 15 — проще: удалить сразу и в задаче 15 перенести; до неё тесты подписок помечены `xfail(strict=False)` одним коммитом — нет: лучше выполнить задачу 15 до удаления; см. порядок ниже).

**Порядок внутри задачи:** сначала перенести `SubscriptionsPage` в диалог настроек (задача 15 выполняется до задачи 10, если удобнее; иначе в этой задаче оставить `self.subscriptions_page = SubscriptionsPage()` вне дерева виджетов, чтобы `refresh_pages` и тесты подписок не падали, и удалить в задаче 15). Выбрать второй вариант: меньше одновременных изменений.

`refresh_status`: `switch_to` → `self.profiles_page.set_switch_target(...)`; `_on_switch_clicked` подписывается на `profiles_page`. `profile-ping` → `win.test-profile`. `search` в `application.py` → `window.show_servers(); window.profiles_page.focus_search()`. `show-log` → `window.show_log()` (задача 12). Переключатель и стек — задача 12; здесь `diagnostics_toggle.toggled` уже переключает `right_stack`, заголовок и `back_button`.

**Шаг 4:** `make test-gtk` по `test_ui_window.py`, `test_ui_application.py`; поправить ожидания про `search_button`, `view_stack`. **Шаг 5: коммит** — `ui: панель слева, серверы и диагностика справа`

### Задача 11: «Обновить подписку» в меню группы и действие `sort-profiles`

**Файлы:** `src/ui/pages/profiles.py:293-330`, `tests/test_ui_pages_profiles.py`

**Шаг 1: тест**

```python
def test_subscription_group_menu_offers_an_update(page, two_groups):
    page.set_data(*two_groups)
    assert page.context_menu_labels_for_test(group_id=10) == [
        "Свернуть группу", "Обновить подписку", "Тест задержки", "Оставить рабочие…", "Редактировать", "Удалить"
    ]
    assert "Обновить подписку" not in page.context_menu_labels_for_test(group_id=11)
```

(группа 10 — подписка, 11 — обычная). **Шаг 3:** пункт `win.update-subscription(group_id)` после «Свернуть/Развернуть», только если `row.is_subscription`. Сверить с `src/ui/qt/window.py:85-101`. **Коммит** — `ui: обновить подписку из меню группы`

---

## Этап 4. Диагностика внутри окна

### Задача 12: страница диагностики по образцу Qt

**Файлы:**
- Изменить: `src/ui/pages/monitoring.py`
- Тест: `tests/test_ui_pages_monitoring.py`

**Шаг 1: падающие тесты**

```python
def test_page_layout_matches_qt(page):
    from gi.repository import Gtk

    assert isinstance(page, Gtk.Box)
    assert page.get_group_titles() == ["Состояние соединения", "Маршрутизация", "Журнал"]
    assert page.check_button.get_label() == "Проверить сейчас"
    assert page.diagnostics_button.get_label() == "Диагностика сети…"
    assert page.wrap_check.get_label() == "Перенос строк"
    assert [b.get_label() for b in page.log_buttons] == ["Обновить", "Экспорт…", "Очистить"]


def test_first_row_says_not_checked_until_the_monitor_ran(page, view_factory):
    from src.ui.logic.monitoring_view import LAST_CHECK_PENDING, NOT_CHECKED

    page.update(view_factory(last_check_time=0.0))
    assert page.get_value("Прокси") == NOT_CHECKED
    assert page.get_last_check_text() == LAST_CHECK_PENDING


def test_wrap_toggle_changes_the_text_view(page):
    from gi.repository import Gtk

    assert page.log_view.get_wrap_mode() == Gtk.WrapMode.NONE
    page.wrap_check.set_active(True)
    assert page.log_view.get_wrap_mode() == Gtk.WrapMode.WORD_CHAR


def test_log_timer_runs_only_while_active(page):
    page.set_active(True)
    assert page.log_timer_running_for_test() is True
    page.set_active(False)
    assert page.log_timer_running_for_test() is False
```

Подмена «Прокси → Проверка ещё не выполнена»: в `monitoring_view()` (логика) первая строка соединения получает `NOT_CHECKED`, когда `is_running and not last_check_time`; покрыть в `tests/test_ui_logic_monitoring_view.py`; Qt-подмену в `window.py:594-598` удалить.

**Шаг 3: реализация.** `MonitoringPage(Gtk.Box, VERTICAL, spacing=12)` с классом `card`, отступы 16/12:

- `top = Gtk.Box(spacing=16, homogeneous=True)` — две `Adw.PreferencesGroup` (заголовки «Состояние соединения», «Маршрутизация») с теми же `Adw.ActionRow`, что сейчас, и тем же кэшем строк;
- `self._last_check = Gtk.Label(xalign=0)`;
- `buttons = Gtk.Box(spacing=8, homogeneous=True)`: `self.check_button`, `self.diagnostics_button` (сигналы `refresh-requested`, `diagnostics-requested` остаются);
- `log_group = Adw.PreferencesGroup(title="Журнал", description="Последние записи. Хранение — 3 дня; секреты маскируются.")`, внутри `ScrolledWindow(vexpand=True)` с `log_view` без ограничения высоты; строка снизу: `self.wrap_check = Gtk.CheckButton(label="Перенос строк")`, растяжка, `self.log_buttons`;
- `set_active(bool)` заменяет `map`/`unmap` как источник таймера: окно зовёт его при переключении стека и в `hide`/`close`; таймер 2 с, `log_timer_running_for_test`.

**Коммит** — `ui: страница диагностики по общему дизайну`

### Задача 13: переключение серверы ↔ диагностика

**Файлы:** `src/ui/window.py`, `src/ui/application.py`, `tests/test_ui_window.py`

**Шаг 1: тесты**

```python
def test_toggle_switches_the_right_page_and_header(window):
    window.diagnostics_toggle.set_active(True)
    assert window.right_stack.get_visible_child_name() == "monitoring"
    assert window.page_title.get_text() == "Диагностика"
    assert window.back_button.get_visible() is True
    assert window.monitoring_page.log_timer_running_for_test() is True

    window.back_button.emit("clicked")
    assert window.right_stack.get_visible_child_name() == "servers"
    assert window.diagnostics_toggle.get_active() is False
    assert window.monitoring_page.log_timer_running_for_test() is False


def test_show_log_action_opens_diagnostics_and_focuses_the_log(window, adw_app):
    adw_app.activate_action("show-log", None)
    assert window.right_stack.get_visible_child_name() == "monitoring"
    assert window.monitoring_page.log_view.is_focus()


def test_switching_pages_keeps_query_and_selection(window, adw_app):
    _two_profiles(adw_app)
    window.refresh_pages()
    window.profiles_page.expand_all()
    window.profiles_page.set_query("а")
    window.profiles_page.select_profile(1)
    window.diagnostics_toggle.set_active(True)
    window.diagnostics_toggle.set_active(False)
    assert window.profiles_page.search_entry.get_text() == "а"
    assert window.profiles_page.get_selected_profile_id() == 1


def test_hiding_the_window_stops_the_log_timer(window):
    window.diagnostics_toggle.set_active(True)
    window.hide()
    assert window.monitoring_page.log_timer_running_for_test() is False
```

**Шаг 3:** `_on_diagnostics_toggled`: стек, заголовок, `back_button`, `monitoring_page.set_active(active and self.get_visible())`, при возврате `list_view.grab_focus()`. `show_servers()`, `show_log()`. Подписаться на `notify::visible` и `close-request` для `set_active(False)`. Действие `show-log` зарегистрировать в `application.py` рядом с `search`; добавить в `tests/test_ui_application.py::…все действия…`. Пункт `app.network-diagnostics` с Ctrl+W: оставить как есть.

**Коммит** — `ui: диагностика внутри окна и пункт «Журнал…»`

---

## Этап 5. Настройки

### Задача 14: каркас диалога с разделами и статусом сохранения

**Файлы:**
- Изменить: `src/ui/dialogs/settings.py` (класс и `__init__`), `src/ui/style.css`
- Тест: `tests/test_ui_dialogs_settings.py`

**Шаг 1: падающие тесты**

```python
def test_dialog_has_a_section_list_with_icons(dialog):
    from gi.repository import Adw

    assert isinstance(dialog, Adw.Dialog)
    assert dialog.get_title() == "Настройки"
    assert dialog.section_titles_for_test() == [
        "Общие", "Мониторинг", "DNS", "Маршрутизация", "Обход блокировок", "Подписки", "О программе"
    ]
    assert all(dialog.section_icon_for_test(i).endswith(".svg") for i in range(7))
    assert dialog.close_button.get_label() == "Закрыть"


def test_selecting_a_section_shows_its_page(dialog):
    dialog.select_section_for_test("DNS")
    assert dialog.get_section_title() == "DNS"
    assert dialog.get_visible_page() is dialog.dns_page


def test_status_line_tracks_autosave(dialog, run_main_loop):
    from src.ui.logic.settings_form import SAVE_DONE, SAVE_IDLE, SAVE_PENDING

    assert dialog.get_status_text() == SAVE_IDLE
    dialog.inbound_address.set_text("127.0.0.2")
    assert dialog.get_status_text() == SAVE_PENDING
    run_main_loop(0.7)
    assert dialog.get_status_text().startswith(SAVE_DONE)


def test_invalid_field_is_reported_in_the_status_line(dialog, run_main_loop):
    dialog.inbound_address.set_text("не адрес")
    run_main_loop(0.7)
    assert dialog.get_status_text().startswith("Исправьте настройки")
    assert "error" in dialog.inbound_address.get_css_classes()


def test_save_result_from_controller(dialog):
    from src.ui.logic.settings_form import SAVE_FAILED

    dialog.set_save_result(False)
    assert dialog.get_status_text() == SAVE_FAILED
    dialog.set_save_result(True, reconnect=True)
    assert dialog.get_status_text().endswith("Требуется переподключение")
```

`run_main_loop` — есть ли такая фикстура, проверить в `tests/conftest.py`; если нет, крутить `GLib.MainContext.default().iteration(False)` до истечения времени, как в `test_ui_window.py`.

**Шаг 3: реализация.** `SettingsDialog(Adw.Dialog)`, `set_content_width(960)`, `set_content_height(700)`, `set_title("Настройки")`:

```python
split = Adw.NavigationSplitView(min_sidebar_width=200, max_sidebar_width=220, sidebar_width_fraction=0.22)
sidebar: Adw.NavigationPage(title="Настройки") → Adw.ToolbarView(top: Adw.HeaderBar(show_end_title_buttons=False)) → Gtk.ListBox(selection SINGLE, class "navigation-sidebar")
   строки: Gtk.Box(icon Gtk.Image.new_from_file(assets/icons/ui/<name>.svg) 20px + Gtk.Label)
content: Adw.NavigationPage → Adw.ToolbarView(top: Adw.HeaderBar(title_widget = self._section_title, show_start_title_buttons=False)) → Gtk.Stack с семью Adw.PreferencesPage
bottom bar (на content ToolbarView): Gtk.Box: self._status (xalign 0, hexpand), self.close_button
```

`SECTIONS = (("general", "Общие", "general"), ("monitoring", "Мониторинг", "monitor"), ("dns", "DNS", "dns"), ("routing", "Маршрутизация", "routing"), ("bypass", "Обход блокировок", "bypass"), ("subscriptions", "Подписки", "subscriptions"), ("about", "О программе", "about"))` — вынести в `src/ui/logic/settings_form.py` и заставить `src/ui/qt/dialogs/settings.py:60-68` читать оттуда же (с тестом в `test_ui_logic_settings_form.py`). Значки: `get_asset_path("icons/ui/<name>.svg")`; на `Gtk.Image.set_from_file` с SVG работает через gdk-pixbuf (`librsvg` есть в зависимостях GTK).

Существующие `_build_*_page` возвращают `Adw.PreferencesPage` вместо `self.add(page)`; `show_dns_page()` выбирает строку «DNS». Автосохранение: `_queue_save` ставит `SAVE_PENDING`; `save()` при ошибке проверки — «Исправьте настройки: …» в статусе (заголовок диалога не трогать); после успешной записи эмитировать `settings-saved`, а приложение зовёт `dialog.set_save_result(controller.apply_settings(), reconnect=pending_settings(context))` — посмотреть, что возвращает `apply_settings` в `application.py:485` и `controller.py`, и привести к Qt (`src/ui/qt/application.py:377-379`).

CSS: `.settings-sidebar row:selected { box-shadow: inset 3px 0 0 #36c9b5; }`.

**Коммит** — `ui: окно настроек с разделами и строкой статуса`

### Задача 15: «Общие» в порядке Qt и группа «Окно»

**Файлы:** `src/ui/dialogs/settings.py:139-202`, `src/ui/window.py:_on_close_request`, `src/ui/application.py`, `tests/test_ui_dialogs_settings.py`, `tests/test_ui_window.py`

**Шаг 1: тесты**

```python
def test_general_groups_follow_the_qt_order(dialog):
    assert dialog.group_titles_for_test(dialog.general_page) == [
        "Режим работы", "Входящее соединение", "Окно", "Журнал"
    ]


def test_tun_rows_hide_for_system_proxy_without_losing_values(dialog, run_main_loop):
    dialog.tun_name.set_text("tun7")
    dialog.proxy_mode.select("system")
    assert dialog.tun_name.get_visible() is False
    assert dialog.mtu.get_visible() is False
    dialog.proxy_mode.select("tun")
    assert dialog.tun_name.get_visible() is True
    assert dialog.tun_name.get_text() == "tun7"


def test_close_to_tray_switch_round_trips(dialog, config, run_main_loop):
    assert dialog.close_to_tray.get_title() == "Сворачивать в трей при закрытии окна"
    assert dialog.close_to_tray.get_subtitle() == "Без трея закрытие окна всегда завершает приложение"
    dialog.close_to_tray.set_active(False)
    run_main_loop(0.7)
    assert config.close_to_tray is False


# tests/test_ui_window.py
def test_close_quits_when_close_to_tray_is_off(window, adw_app, monkeypatch):
    adw_app.context.config.close_to_tray = False
    quits = []
    monkeypatch.setattr(adw_app, "quit", lambda: quits.append(True))
    window.emit("close-request")
    assert quits == [True]
```

**Шаг 3:** порядок групп; «Оформление» → «Окно» с `Adw.SwitchRow` `close_to_tray`; `_sync_mode` прячет строки TUN (`set_visible`) вместо `set_sensitive`; kill switch и строка проверки TUN — только в TUN. В `_on_close_request`: если `not config.close_to_tray` или трей недоступен (`app.tray` — проверить имя атрибута `TrayController` в `application.py` и признак его регистрации), сохранить геометрию и `app.quit()`. Проверить, что `hide-window` (Ctrl+W) ведёт себя как закрытие. Загрузка/сохранение поля в `_load`/`save` рядом с `theme`.

**Коммит** — `ui: группа «Окно» и скрытие полей TUN в настройках`

### Задача 16: список подписок в разделе «Подписки»

**Файлы:**
- Создать: `src/ui/widgets/subscriptions_list.py` (из `src/ui/pages/subscriptions.py` без `SearchBar` и `Gtk.Stack`-состояния поиска)
- Изменить: `src/ui/dialogs/settings.py:374-403`, `src/ui/window.py`, `src/ui/application.py` (обновлять список после `update_subscription`/CRUD)
- Удалить: `src/ui/pages/subscriptions.py`
- Тест: `tests/test_ui_dialogs_settings.py` (перенести сюда `tests/test_ui_pages_subscriptions.py`, затем удалить его)

**Шаг 1: тесты.** Перенести тесты страницы, заменив фикстуру на `dialog.subscriptions_list`; добавить:

```python
def test_subscriptions_section_has_list_and_buttons(dialog):
    assert dialog.group_titles_for_test(dialog.subscriptions_page) == ["Подписки", "Запрос к провайдеру"]
    assert [b.get_label() for b in dialog.subscription_buttons] == ["Добавить…", "Обновить", "Изменить…", "Удалить"]
    assert dialog.subscriptions_list.get_empty_text() == "Подписок нет. Добавьте ссылку от провайдера."


def test_subscription_buttons_target_the_selected_row(dialog, adw_app, two_subscriptions):
    dialog.subscriptions_list.select_for_test(group_id=10)
    assert dialog.subscription_buttons[1].get_action_target_value().get_int32() == 10
    assert dialog.subscription_buttons[0].get_action_name() == "app.add-subscription"
```

**Шаг 3:** `SubscriptionsList(Adw.PreferencesGroup)` со строками `Adw.ActionRow` как сейчас (кнопка объявления, метаданные, «Обновить подписку», меню `win.*`), плюс `activatable` строки с выделением (`Gtk.ListBox` внутри `Adw.PreferencesGroup` — `set_selection_mode(SINGLE)` на внутреннем списке; если недоступно, хранить выбранный `group_id` по клику); кнопки под списком: `app.add-subscription`, `win.update-subscription(id)`, `win.edit-subscription(id)`, `win.delete-subscription(id)` — `Adw.Dialog` внутри окна разрешает `win.`-действия через иерархию виджетов; проверить тестом `get_menu_target_for_test`. Диалог получает `context` (уже передаётся) и строит список из `context.profiles`; окно зовёт `dialog.refresh_subscriptions()` из `refresh_pages()`, если диалог открыт (у приложения есть слот текущего диалога — `application.py:426-443`). Пустое состояние — `Adw.ActionRow` с текстом вместо `Adw.StatusPage`.

Из окна убрать `subscriptions_page`, импорты и сигналы; `_row_edit_subscription`/`_row_delete_subscription` остаются. `tests/test_ui_application.py` — проверить, что сценарии обновления подписок ссылаются не на вкладку.

**Коммит** — `ui: подписки в настройках вместо вкладки`

### Задача 17: пакет и значки разделов

**Файлы:** `core/scripts/build_deb.sh:61, 73-80`, `tests/test_packaging_spec.py` (если проверяет состав deb; иначе `tests/test_build_deb*.py` — найти по `grep -rn "logo-inner-256" tests`)

Тест: список файлов пакета содержит `assets/icons/ui/general.svg` и `assets/logo_inner.png`, не содержит `assets/icons/win`. Реализация: убрать `logo_inner.png` из удаляемых, добавить проверки `[ -f …/icons/ui/general.svg ]`. Если `logo-inner-256.png` больше нигде не используется (`grep -rn "logo-inner-256" src`), оставить его для Qt-«О программе»/совместимости только если он там нужен, иначе удалить из репозитория.

**Коммит** — `build: значки разделов и логотип 1024 в deb`

---

## Этап 6. Проверка и выпуск

### Задача 18: полный прогон и чистка

1. `make test-gtk`, `make test-tray`, `make test-qt`, `uv run pytest -q`, `python cli.py lint-all` — все зелёные. Удалить мёртвый код: `LOGO_SIZE_COMPACT` в `status_card.py`, `NARROW_WIDTH`, `summary_line` (если Qt её не использует — `grep -rn summary_line src`), правила CSS без потребителей.
2. Проверить `tests/test_ui_platform_branches.py`, `tests/test_branding.py`; добавить в `test_branding.py`:

```python
def test_gtk_never_imports_the_monolith():
    import pathlib

    gtk = [p for p in pathlib.Path("src/ui").rglob("*.py") if "qt" not in p.parts]
    assert not [p for p in gtk if "monolith" in p.read_text(encoding="utf-8")]
```

3. Ручные сценарии (`python gui.py` без подключения, подмены через `TENGA_CONFIG_DIR` на временный каталог с синтетическими серверами; живой TUN не трогать): пустое хранилище; поиск без результатов; имя сервера из 60 символов; десять групп; все состояния голубя (`show_connecting`, `show_error`, блокировка через `proxy_state`); активный и выбранный разные; переход в диагностику во время «Подключение…»; окно 900×540 и 1180×760; светлая и тёмная тема (`Adw.StyleManager`); `GDK_SCALE=2`. Каждый пункт — одной строкой в отчёте, с результатом.

**Коммит** — `ui: чистка после переноса компоновки`

### Задача 19: снимки и документация

1. Снять `assets/screen-profiles.png`, `assets/screen-monitoring.png`, `assets/screen-add-profile.png` заново на синтетических данных (1180×760, тёмная и светлая — хотя бы одна); `assets/screen-subscriptions.png` заменить на снимок раздела настроек или удалить вместе со ссылками (`grep -rn screen-subscriptions docs README*`).
2. `docs/ru/gui.md` и `docs/en/gui.md`: описать панель, список, диагностику, настройки; убрать вкладки. `docs/ru/overview.md`, `README` — проверить упоминания «вкладка».
3. `docs/plans/2026-11-02-shared-ui-design.md`: раздел «Расхождения» — только то, что осталось; «Выполнено» — пункт про Linux.
4. `CLAUDE.md`: абзац «Общий дизайн GTK и Qt» — «Намеренное отличие одно: логотип»; абзац «Диагностика сети» — ссылку на `pages/monitoring.py` сверить; абзац про GTK-интерфейс («Создаёт MainWindow…») — без вкладок.

**Коммит** — `docs: интерфейс Linux после переноса компоновки`

---

## Порядок и контрольные точки

| Этап | Задачи | Готово, когда |
| --- | --- | --- |
| 1 | 1–5 | `uv run pytest -q` и `make test-qt` зелёные, дизайн-документ обновлён |
| 2 | 6–7 | `test_ui_widgets_status_card.py`, `test_ui_styles.py` зелёные |
| 3 | 8–11 | `test_ui_pages_profiles.py`, `test_ui_window.py`, `test_ui_application.py` зелёные; окно открывается и выглядит как `main-dark-1180.png` с голубем |
| 4 | 12–13 | `test_ui_pages_monitoring.py` зелёный, таймер журнала один |
| 5 | 14–17 | `test_ui_dialogs_settings.py` зелёный, `pages/subscriptions.py` удалён, deb собирается (`python cli.py build`) |
| 6 | 18–19 | весь набор зелёный, снимки и документация обновлены |

Между этапами 2 и 3 часть GTK-тестов красная (окно ещё зовёт старую карточку): это допустимо только внутри одной ветки, в `develop` сливать после этапа 3. Риски и где их проверять: высота панели на 540 px — задача 10 (компактный режим), стоимость свечения — задача 6 (перерисовка только по смене цвета), потеря поведения дерева — задача 8 (существующие тесты раскрытия, выделения и прокрутки обязаны пройти без изменений), двойной таймер — задача 13.
