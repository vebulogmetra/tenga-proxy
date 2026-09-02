# Этап 2: страницы профилей, подписок и мониторинга — детальный план

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Наполнить три страницы GTK4-оболочки настоящим содержимым: дерево
профилей с фильтром и сортировкой, список подписок и панель мониторинга.

**Architecture:** Вся логика без GTK (фильтрация, сортировка, форматирование
строк, свод состояния мониторинга) живёт в `src/ui/logic/` и покрывается
обычным pytest. Виджеты в `src/ui/pages/` только раскладывают готовые
структуры по `Gtk.ColumnView` / `Adw.PreferencesPage`. Дерево профилей строится
на `Gtk.TreeListModel` поверх `Gio.ListStore` с обёрткой `ProfileItem`
(`GObject.Object`), потому что `Gtk.TreeStore` в GTK4 не работает с
`Gtk.ColumnView`.

**Tech Stack:** GTK 4.14, libadwaita 1.5, PyGObject, pytest.

---

## Уточнения после разведки кода

1. **`logic/formatting.py` и `logic/latency.py` уже существуют** (созданы на
   этапе 0): `format_bytes()` и `LatencyRunner` с ограниченным параллелизмом и
   доставкой результатов через `dispatch`. Этап 2 их переиспользует, не
   переписывая.

2. **GTK3 кодирует состояние в текст модели**: префиксы `📡 `/`📁 ` для групп,
   `✓ ` для активного профиля, `(N)` со счётчиком, `—` для неизвестного пинга.
   В GTK4 это разносится: значок группы — отдельная колонка `icon_name`,
   активность — CSS-класс строки, счётчик — суффикс через `Adw`-стиль.

3. **Фильтр в GTK3 ищет по четырём полям профиля** (`name`, `proxy_type`,
   `bean.display_address`, плюс совпадение по имени группы показывает всю
   группу целиком) и по трём полям подписки (`name`, `subscription_url`,
   отформатированная дата). Это поведение сохраняется дословно и переносится
   в `logic/filtering.py`.

4. **Сортировка по пингу в GTK3 ставит непроверенные профили в конец**
   (`latency_ms < 0` → ключ `(1, 0)`). Правило переносится как есть.

5. **`RoutingMode` — это класс с константами, а не `Enum`**
   (`src/db/config.py:267`), значения `proxy_all` и `custom`. Свод правил
   маршрутизации в GTK3 (`_update_routing_indicators`, 2072-строчный
   `main_window.py`) даёт четыре строки: режим, DIRECT, PROXY, VPN.

6. **`is_vpn_active()` делает системный вызов** через NetworkManager. В логике
   мониторинга он не вызывается: функция принимает уже готовый признак
   `vpn_is_up` параметром, иначе тесты полезут в систему.

7. **Тест задержки живёт в `TengaApp.test_profile_latency`** (GTK3-класс).
   GTK4-страница не может его импортировать. Проба передаётся в страницу
   колбэком; `TengaApplication` подставляет функцию, которая на этапе 2
   вызывает `src.core`-уровень напрямую.

8. **`get_profiles_in_group()` возвращает список**, `groups` — словарь
   `{id: ProfileGroup}`. Порядок групп в GTK3: сначала подписки, потом
   обычные, внутри — по имени без учёта регистра.

---

## Task 2.1: Логика фильтрации и сортировки профилей

**Files:**
- Create: `src/ui/logic/profiles_view.py`, `tests/test_ui_logic_profiles_view.py`

**Шаг 1. Написать падающий тест.**

```python
def test_group_name_match_keeps_all_profiles():
    rows = build_profile_rows(groups, profiles_by_group, query="работа")
    assert [r.title for r in rows[0].children] == ["A", "B"]
```

**Шаг 2.** Запустить, убедиться, что падает с `ModuleNotFoundError`.

**Шаг 3. Реализовать минимум.**

```python
@dataclass(frozen=True)
class ProfileRow:
    profile_id: int
    title: str
    proxy_type: str
    address: str
    latency_ms: int
    is_active: bool

@dataclass(frozen=True)
class GroupRow:
    group_id: int
    title: str
    icon_name: str
    is_subscription: bool
    children: tuple[ProfileRow, ...]

class SortKey(StrEnum):
    NAME = "name"
    TYPE = "type"
    PING = "ping"

def build_profile_rows(groups, profiles_by_group, *, query="",
                       sort_key=SortKey.NAME, ascending=True,
                       active_profile_id=-1) -> list[GroupRow]
def ping_text(latency_ms: int) -> str
```

`build_profile_rows` повторяет правила GTK3 (уточнения 3, 4, 8): группы
сортируются «подписки первыми, затем по имени»; при совпадении запроса с
именем группы показываются все её профили; группа без видимых профилей
скрывается целиком; `latency_ms < 0` уходит в конец при сортировке по пингу.

**Тесты (12):** пустой запрос отдаёт всё; фильтр по имени профиля; по типу;
по адресу; по имени группы; пустая группа исчезает; порядок групп; сортировка
по типу в обе стороны; сортировка по пингу ставит `-1` в конец; активный
профиль помечен; `ping_text(-1) == "—"`; `ping_text(42) == "42 ms"`.

**Commit:** `feat: add profile list filtering and sorting logic`

---

## Task 2.2: Логика списка подписок

**Files:**
- Create: `src/ui/logic/subscriptions_view.py`, `tests/test_ui_logic_subscriptions_view.py`

```python
@dataclass(frozen=True)
class SubscriptionRow:
    group_id: int
    name: str
    url: str
    updated_text: str
    profile_count: int

def format_updated(timestamp: int) -> str   # 0 -> "Никогда", иначе "%d.%m.%Y %H:%M"
def build_subscription_rows(groups, counts, *, query="") -> list[SubscriptionRow]
```

Полный URL сохраняется в `url` — обрезка до 50 символов была нужна GTK3
из-за фиксированной колонки; в GTK4 текст обрезает сам виджет через
`Pango.EllipsizeMode.END`, поэтому логика отдаёт URL целиком, а фильтр ищет
по полному значению.

**Тесты (8):** `format_updated(0)`; `format_updated` для известной метки
времени; фильтр по имени, по URL, по дате; обычные группы отброшены;
счётчик профилей; пустой запрос.

**Commit:** `feat: add subscription list logic`

---

## Task 2.3: Логика сводки мониторинга

**Files:**
- Create: `src/ui/logic/monitoring_view.py`, `tests/test_ui_logic_monitoring_view.py`

```python
@dataclass(frozen=True)
class MonitoringRow:
    title: str
    value: str
    css_class: str   # "" | "status-connected" | "status-error" | "dim-label"

@dataclass(frozen=True)
class MonitoringView:
    connection: tuple[MonitoringRow, ...]
    routing: tuple[MonitoringRow, ...]
    last_check: str

def routing_rows(routing, *, vpn_enabled=False, vpn_is_up=False) -> tuple[MonitoringRow, ...]
def monitoring_view(status, routing, *, is_running, profile_found=True,
                    vpn_enabled=False, vpn_is_up=False) -> MonitoringView
```

`routing_rows` дословно повторяет ветвление GTK3 (уточнение 5), а признак
активности VPN приходит параметром (уточнение 6).

**Тесты (11):** отключено → все прочерки; профиль не найден; `PROXY_ALL` с
обходом локальных сетей и без; `CUSTOM` со счётчиками правил; VPN не задан /
активен / правила есть, но VPN лежит / VPN выключен; `last_check` для нуля и
для метки времени; ошибка прокси даёт класс `status-error`.

**Commit:** `feat: add monitoring summary logic`

---

## Task 2.4: Страница профилей

**Files:**
- Create: `src/ui/pages/__init__.py`, `src/ui/pages/profiles.py`,
  `tests/test_ui_pages_profiles.py`
- Modify: `src/ui/style.css`

`ProfilesPage(Gtk.Box)` содержит `Gtk.SearchBar` с `Gtk.SearchEntry`,
`Gtk.ColumnView` внутри `Gtk.ScrolledWindow` и `Adw.StatusPage` для пустого
состояния, переключаемые через `Gtk.Stack`.

Модель: `Gio.ListStore` из `RowItem(GObject.Object)` (обёртка над `GroupRow`
или `ProfileRow`) → `Gtk.TreeListModel` с `create_func`, возвращающей детей
только для групп → `Gtk.SingleSelection`. Первая колонка использует
`Gtk.TreeExpander`, остальные — обычные `Gtk.Label`.

Колонки: Имя (расширяемая, с раскрывателем), Тип, Сервер, Пинг.
Сигналы: `profile-activated(int)`, `profile-context(int)`.
Публичный метод `refresh()` перестраивает модель через `build_profile_rows`.

**Тесты (gtk, 8):** страница строится; пустой набор показывает
`Adw.StatusPage`; непустой показывает список; фильтр сокращает число строк;
раскрытие группы даёт детей; `profile-activated` эмитируется; сортировка по
клику меняет порядок; текст пинга берётся из `ping_text`.

**Commit:** `feat: add GTK4 profiles page`

---

## Task 2.5: Страница подписок

**Files:**
- Create: `src/ui/pages/subscriptions.py`, `tests/test_ui_pages_subscriptions.py`

`SubscriptionsPage(Gtk.Box)`: `Gtk.SearchBar` + `Adw.PreferencesGroup` со
списком `Adw.ActionRow` (заголовок — имя, подзаголовок — URL, суффикс — число
профилей и кнопка обновления), пустое состояние через `Adw.StatusPage`.

Сигналы: `subscription-activated(int)`, `subscription-update(int)`.

**Тесты (gtk, 6):** строится; пусто → `StatusPage`; строки создаются по числу
подписок; фильтр сокращает список; кнопка обновления эмитирует сигнал;
подзаголовок содержит полный URL.

**Commit:** `feat: add GTK4 subscriptions page`

---

## Task 2.6: Страница мониторинга

**Files:**
- Create: `src/ui/pages/monitoring.py`, `tests/test_ui_pages_monitoring.py`

`MonitoringPage(Adw.PreferencesPage)` с двумя `Adw.PreferencesGroup`
(«Соединение», «Маршрутизация») из `Adw.ActionRow`, строкой последней проверки
и кнопкой «Обновить сейчас» (сигнал `refresh-requested`).

Строки создаются один раз и обновляются на месте: пересоздание групп при
каждом тике мониторинга (раз в 10 секунд по умолчанию) сбрасывало бы прокрутку.

**Тесты (gtk, 6):** строится; число строк соответствует `MonitoringView`;
`update()` меняет значение; CSS-класс переставляется; кнопка эмитирует сигнал;
последняя проверка отображается.

**Commit:** `feat: add GTK4 monitoring page`

---

## Task 2.7: Подключение страниц к окну

**Files:**
- Modify: `src/ui/window.py`, `tests/test_ui_window.py`

Заменить три `Adw.StatusPage`-заглушки на настоящие страницы. Кнопка поиска
переключает `Gtk.SearchBar` активной страницы; `Ctrl+F` работает через уже
существующее действие. Обновление страниц при смене состояния прокси.

**Тесты (gtk, +5):** `view_stack` содержит три настоящие страницы; поиск
раскрывает панель на активной странице; смена страницы переносит фокус поиска;
`refresh_pages()` не падает на пустом хранилище; активный профиль отмечен.

**Commit:** `feat: wire pages into the GTK4 window`

---

## Task 2.8: Действия страниц в приложении

**Files:**
- Modify: `src/ui/application.py`, `tests/test_ui_application.py`

Действия `refresh-subscriptions`, `test-latency` и обновление одной подписки
перестают быть заглушками: они запускают работу в фоне через
`run_in_background` / `LatencyRunner` и показывают результат тостом.
Проба задержки приходит колбэком (уточнение 7).

**Тесты (gtk, +4):** действие теста задержки вызывает пробу; результат
попадает в модель; ошибка пробы не роняет приложение; повторный запуск во
время работы игнорируется.

**Commit:** `feat: implement page-level actions`

---

## Проверка этапа

- `uv run pytest -q` — все тесты без дисплея проходят.
- `make test-gtk` — тесты виджетов проходят.
- `uv run python gui.py --gtk4` на копии реального конфига (600 профилей):
  дерево строится, фильтр работает, сортировка меняет порядок, мониторинг
  показывает состояние. Подключение/отключение не проверяется.
- Скриншоты в тёмной и светлой теме.
