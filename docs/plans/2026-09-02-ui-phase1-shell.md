# Этап 1: оболочка GTK4 + libadwaita — детальный план

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Запустить пустую, но живую оболочку приложения на GTK4 + libadwaita
рядом со старым GTK3-интерфейсом, не ломая его.

**Architecture:** Новый код живёт в `src/ui/application.py`, `src/ui/window.py`,
`src/ui/widgets/`, `src/ui/logic/`. Точка входа — `gui.py --gtk4`, которая
выбирает версию GTK до импорта любых GTK-модулей. Старый путь запуска остаётся
по умолчанию до этапа 5. Вся логика без GTK выносится в `src/ui/logic` и
покрывается обычным pytest; виджеты проверяются тестами с маркером `gtk`
под `xvfb-run`.

**Tech Stack:** GTK 4.14, libadwaita 1.5, PyGObject, pytest, xvfb.

---

## Уточнения после разведки кода

Эти факты найдены в коде и меняют формулировки исходного плана:

1. **Выбор версии GTK делается в `gui.py` до импортов.** Текущий `gui.py`
   вызывает `gi.require_version("Gtk", "3.0")` на уровне модуля, поэтому
   `--gtk4` нельзя разобрать после импорта: `argparse` должен отработать
   раньше. Разбор аргументов переносится в начало файла.

2. **Геометрия хранится в `data_store.py:48` как `window_size: str`** в формате
   `"w,h,x,y,maximized"`. GTK4 убрал `Gtk.Window.move()`, позиционировать окно
   невозможно. Координаты `x,y` продолжают записываться как `0,0`, чтобы старый
   GTK3-код читал файл без ошибок, но новое окно их игнорирует. Парсинг и
   сериализация выносятся в `src/ui/logic/geometry.py` — это чистая логика,
   тестируется без дисплея.

3. **Состояние подключения не имеет отдельного «Подключение…».** `ProxyState`
   (`src/core/context.py:19`) хранит только `is_running`; промежуточное
   состояние в GTK3-окне держится полем `self._connecting`. В `status.py`
   вводится явное перечисление `ConnectionState` из четырёх значений, чтобы
   карточка не зависела от структуры `ProxyState`.

4. **Существующий `src/ui/style.py` — GTK3-only** (`get_style_context`,
   `Gtk.HeaderBar.set_show_close_button`). Новый `src/ui/style.css` его не
   трогает и грузится через `Gtk.CssProvider` для GTK4-дисплея.

5. **`pyproject.toml` уже задаёт `addopts` с покрытием.** Добавление
   `-m "not gtk"` к этому списку сохраняет текущее поведение `make test`.

---

## Task 1.1: Инфраструктура тестов GTK4

**Files:**
- Create: `tests/conftest.py`
- Modify: `pyproject.toml`, `Makefile`

**Шаг 1.** В `pyproject.toml` в `[tool.pytest.ini_options]` добавить
`markers = ["gtk: требует дисплея, запускается через make test-gtk"]` и
дополнить `addopts` элементом `-m "not gtk"`.

**Шаг 2.** Создать `tests/conftest.py` с фикстурой `gtk_app`: требует
`Gtk.init_check()`, иначе `pytest.skip`. Фикстура возвращает
`Adw.Application` в состоянии после `startup`.

**Шаг 3.** В `Makefile` добавить цель `test-gtk`:
`xvfb-run -a uv run pytest -m gtk -p no:cacheprovider --no-cov`.

**Критерий приёмки:** `uv run pytest -q` проходит без дисплея;
`make test-gtk` сообщает «no tests ran».

**Commit:** `test: add gtk marker and xvfb test target`

---

## Task 1.2: Логика геометрии окна

**Files:**
- Create: `src/ui/logic/geometry.py`, `tests/test_ui_logic_geometry.py`

```python
@dataclass(frozen=True)
class Geometry:
    width: int
    height: int
    maximized: bool

def parse_geometry(raw: str, *, default: Geometry = DEFAULT_GEOMETRY) -> Geometry
def format_geometry(geometry: Geometry) -> str
```

`parse_geometry` терпит пустую строку, мусор, недостаточное число полей и
значения меньше минимума (`MIN_WIDTH = 360`, `MIN_HEIGHT = 400`), возвращая
значение по умолчанию для каждого испорченного поля отдельно.
`format_geometry` пишет пять полей, координаты — нулями (см. уточнение 2).

**Тесты:** пустая строка → умолчание; корректная строка; строка с координатами
от GTK3 читается; ширина ниже минимума поднимается; мусор не выбрасывает
исключение; `parse(format(g)) == g`.

**Commit:** `feat: add window geometry parsing helpers`

---

## Task 1.3: Логика статуса

**Files:**
- Create: `src/ui/logic/status.py`, `tests/test_ui_logic_status.py`

```python
class ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"

@dataclass(frozen=True)
class StatusView:
    title: str
    subtitle: str
    icon_name: str
    css_class: str
    button_label: str
    button_class: str
    show_spinner: bool

def status_view(state, *, profile_name="", error="", latency_ms=None,
                upload_bytes=0, download_bytes=0, mode="") -> StatusView
def metrics_text(latency_ms, upload_bytes, download_bytes, mode) -> str
```

`metrics_text` собирает строку «132 ms · ↑ 1.2 MB ↓ 48.7 MB · TUN», пропуская
неизвестные части, и переиспользует `format_bytes` из
`src/ui/logic/formatting.py` (создан в этапе 0). Пустая строка, если известных
частей нет.

**Тесты:** таблица по четырём состояниям; подзаголовок при подключении = имя
профиля; при ошибке = текст ошибки; кнопка `destructive-action` только в
`CONNECTED`; спиннер только в `CONNECTING`; `metrics_text` при полном и
пустом наборе данных.

**Commit:** `feat: add status card presentation logic`

---

## Task 1.4: run_in_background

**Files:**
- Create: `src/ui/logic/async_utils.py`, `tests/test_ui_logic_async.py`

```python
def run_in_background(fn, on_done=None, on_error=None, *,
                      dispatch=_default_dispatch, name="tenga-worker") -> threading.Thread
```

Выполняет `fn()` в потоке-демоне. Успех → `dispatch(on_done, result)`,
исключение → `dispatch(on_error, exc)` с записью в лог. Если `on_error` не
задан, исключение только логируется — поток не должен падать молча.
Ловится `BaseException` по той же причине, что в `LatencyRunner`.
`_default_dispatch` повторяет реализацию из `latency.py`: обёртка возвращает
`GLib.SOURCE_REMOVE`.

**Тесты:** результат доходит до `on_done`; исключение доходит до `on_error`;
без `on_error` поток завершается и пишет лог; `on_done` не вызывается при ошибке;
поток — демон.

**Commit:** `feat: add run_in_background helper for GTK-safe threading`

---

## Task 1.5: TengaApplication

**Files:**
- Create: `src/ui/application.py`, `tests/test_ui_application.py`

`class TengaApplication(Adw.Application)` с `application_id="ru.tenga.Proxy"`.

- `do_startup`: регистрирует действия `connect`, `disconnect`,
  `toggle-connection`, `add-profile`, `add-profile-from-clipboard`,
  `add-subscription`, `add-group`, `refresh-subscriptions`, `settings`,
  `about`, `shortcuts`, `quit`, `hide-window` и ускорители из дизайн-документа.
- `do_activate`: создаёт окно один раз, иначе `present()`.
- `do_shutdown`: снимает обработчики сигналов, освобождает `lock`.
- `GLib.unix_signal_add` для SIGINT/SIGTERM (как в `app.py` этапа 0).
- `toast(text)` — прокси к `ToastOverlay` окна; молча игнорируется без окна.

Обработчики действий на этом этапе — заглушки, пишущие в лог: страницы и
диалоги появляются в этапе 2. Исключение — `quit` и `hide-window`, они
работают сразу.

**Тесты (gtk):** приложение создаётся; каждое действие из списка присутствует
в `list_actions()`; повторный `activate` не создаёт второе окно;
`toast()` без окна не падает.

**Commit:** `feat: add Adw.Application shell with global actions`

---

## Task 1.6: StatusCard

**Files:**
- Create: `src/ui/widgets/__init__.py`, `src/ui/widgets/status_card.py`,
  `src/ui/style.css`
- Create: `tests/test_ui_widgets_status_card.py`

`StatusCard(Gtk.Box)` со стилем `card`: иконка состояния, заголовок,
подзаголовок, строка метрик, кнопка действия. Единственный публичный метод —
`update(view: StatusView)`, который снимает прошлый CSS-класс состояния и
ставит новый. Кнопка эмитирует сигнал `action-clicked`.

`style.css` (≤ 60 строк) описывает `.status-connected/.connecting/.error/
.disconnected`, `.metrics`, `.latency-good/medium/bad`. Загружается в
`window.py` через `Gtk.CssProvider` и
`Gtk.StyleContext.add_provider_for_display`.

**Тесты (gtk):** после `update` заголовок совпадает с `StatusView`; при смене
состояния старый класс снят, новый добавлен; нажатие кнопки эмитирует сигнал.

**Commit:** `feat: add status card widget`

---

## Task 1.7: MainWindow

**Files:**
- Create: `src/ui/window.py`, `tests/test_ui_window.py`
- Modify: `src/ui/application.py` (создание окна)

`MainWindow(Adw.ApplicationWindow)`:
`Adw.ToastOverlay` → `Adw.ToolbarView` → `Adw.HeaderBar` с `Adw.ViewSwitcher`,
меню «☰» и «＋» (`Gio.Menu`), кнопкой поиска → `Adw.ViewStack` с тремя
страницами-заглушками (`Adw.StatusPage`): Профили, Подписки, Мониторинг.
Статус-карточка — над `ViewStack`, видна на всех страницах.

- `Adw.Breakpoint` на `max-width: 550sp` переносит переключатель в
  `Adw.ViewSwitcherBar`.
- Геометрия читается в `__init__` через `parse_geometry` и `set_default_size`,
  сохраняется в `close-request` (B12), без `move()`.
- `close-request` прячет окно вместо закрытия, если трей доступен; на этом
  этапе трея нет, поэтому окно закрывается и приложение выходит.
- Подписка на `proxy_state` обновляет карточку через `status_view`.

**Тесты (gtk):** окно строится; `ViewStack` содержит три страницы; брейкпоинт
добавлен; `close-request` записывает геометрию в конфигурацию.

**Commit:** `feat: add main window shell with view switcher`

---

## Task 1.8: Точка входа `gui.py --gtk4`

**Files:**
- Modify: `gui.py`
- Create: `tests/test_gui_entrypoint.py`

Разбор аргументов переносится в начало файла (уточнение 1). При `--gtk4`
устанавливается `gi.require_version("Gtk", "4.0")` и `Adw`, проверяется версия
libadwaita ≥ 1.5 с понятным сообщением о пакетах `gir1.2-gtk-4.0`,
`gir1.2-adw-1`. Иначе — прежний путь GTK3 без изменений.

Единственность экземпляра в режиме `--gtk4` обеспечивает `Adw.Application`,
но файловая блокировка сохраняется как страховка (см. дизайн-документ).

**Тесты:** парсер принимает `--gtk4`; парсер по умолчанию даёт `gtk4=False`;
проверка версии libadwaita отвергает 1.4 и принимает 1.5.

**Commit:** `feat: add --gtk4 entry point`

---

## Критерий приёмки этапа

`uv run python gui.py --gtk4` открывает окно с header bar, переключателем
и статус-карточкой, отражающей реальное состояние подключения; светлая и
тёмная системная тема выглядят корректно; `make test-gtk` зелёный;
`uv run pytest` остаётся зелёным и не требует дисплея; `python cli.py lint-all`
не добавляет новых ошибок.
