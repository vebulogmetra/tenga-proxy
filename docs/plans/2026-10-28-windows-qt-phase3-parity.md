# Фаза 3: паритет Qt-интерфейса с GTK — план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Довести Qt-интерфейс до паритета с GTK. Появляются формы профиля, группы и подписки; подтверждения; импорт маршрутизации; «VPN и маршруты» профиля; окно настроек со списком подписок и страницей «О программе»; сочетания клавиш; контекстные меню дерева; кнопка «Добавить»; журнал в панели мониторинга. После фазы ни одно действие не отвечает «Раздел появится в следующей сборке».

**Architecture:** Диалоги лежат в `src/ui/qt/dialogs/`. Проверку полей они берут из `src/ui/logic/` (`forms.py`, `settings_form.py`, `routing_form.py`, `routing_import.py`) — той же, что у GTK. Результат форм уходит в `AppController` теми же вызовами, что из GTK-сигналов. `QtApplication` открывает формы, держит действия над строками с адресатом (`edit-profile`, `delete-group`…) и единый слот диалога. Формы, открытые из окна настроек, кладутся поверх него и слот не занимают.

**Tech Stack:** Python 3.11+, PySide6-Essentials ≥ 6.8 (проверено на 6.12), `QIcon.ThemeIcon` (Qt ≥ 6.7), `QT_QPA_PLATFORM=offscreen` для тестов, pytest, ruff.

**Дизайн:** `docs/plans/2026-10-28-windows-qt-frontend-design.md`, разделы «Главное окно», «Окно настроек», «Диалоги», «Тема, шрифт, иконки», фаза 3.
**Предыдущая фаза:** `docs/plans/2026-10-28-windows-qt-phase2-skeleton.md`.

---

## Правила фазы

- **Критерий приёмки:** зелёные `uv run pytest`, `make test-gtk`, `make test-tray`, `make test-qt` и `python cli.py lint-all`. Ожидания существующих тестов не правятся; исключение — один тест фазы 2 про временный тост, см. «Решения». `python gui.py --ui qt` на Linux проходит список задачи 10, на VM Windows 10 и 11 — тоже.
- **GTK-интерфейс и поведение на Linux не меняются.** Единственная правка GTK-кода — задача 1. Константы `ORDER_PRESETS`, `ORDER_LABELS`, `LOG_LEVELS`, `DEFAULT_LOG_LEVEL` и `DEFAULT_TUN_NAME` переезжают в `src/ui/logic/`, а GTK-модули импортируют их оттуда. Значения те же; `make test-gtk` это подтверждает.
- Qt-модули не импортируют `gi` и не читают `IS_WINDOWS`. Тексты, зависящие от ОС, берутся из `platform_texts.py`.
- Каждый Qt-тестовый файл начинается с `pytest.importorskip("PySide6")` и `pytestmark = pytest.mark.qt`.
- Фоновые задачи диалогов доставляют ответ через `QtLoop.dispatch`. Перед вызовом колбэк проверяет `shiboken6.isValid(виджет)`: окно могли закрыть, пока шла сеть.
- Один коммит на задачу, сообщения на русском в стиле репозитория. Перед коммитом запускать `uv run pytest -q --no-cov -p no:cacheprovider`, `make test-qt` и `python cli.py lint-all`. Задача 1 трогает GTK-модули, поэтому там ещё и `make test-gtk`.
- Не запускать xray с TUN-конфигами на машине разработчика: интерфейс `xray0` занят рабочим подключением.
- Код плана проверен. Каждая задача собрана отдельным коммитом во временной ветке (Qt 6.12, offscreen), и после каждой зелёные Qt-тесты, обычный pytest и lint.

## Решения фазы (уточняют дизайн)

| Вопрос | Решение | Почему |
|---|---|---|
| Модальность окна настроек | модальное к главному окну (`open()`), как `Adw.PreferencesDialog` в GTK; формы, открытые из настроек (правка и удаление подписки, очистка журналов, вопрос о смене адреса), кладутся поверх него и слот не занимают | дизайн предлагал немодальное, но тогда трей и сочетания открывали бы формы рядом с настройками, а правило «один диалог за раз» пришлось бы ломать |
| Подписки | список в настройках: таблица «Название · Профилей · Обновлено · Трафик и срок», кнопки «Добавить… / Обновить / Изменить… / Удалить / Ещё», контекстное меню, двойной клик — правка. В строке группы-подписки в дереве — трафик и срок (красным, если истекла), в меню группы — «Обновить подписку» | раздел 3 дизайна; на главном экране Qt нет вкладки подписок, поэтому обновить одну подписку можно и из дерева |
| Иконки действий | `QIcon.fromTheme(QIcon.ThemeIcon.…)`; без темы — короткая подпись («Вставить», «Копировать») | на Windows Qt ≥ 6.7 сам берёт глифы Segoe Fluent Icons (Segoe MDL2 на 10): свой словарь кодов в `icons.py` из дизайна не нужен |
| Сворачивание в трей | новое поле `DataStore.close_to_tray` (по умолчанию да), флажок на странице «Общие». Без трея закрытие окна завершает приложение | раздел «Трей» дизайна; GTK поле не читает |
| Панель мониторинга | видимость в `DataStore.monitoring_panel`, сохраняется вместе с геометрией окна | раздел «Главное окно» дизайна |
| Журнал (диагностика) | в панели мониторинга под «Проверить сейчас»: последние записи (`read_diagnostics`), «Обновить», «Экспорт…», «Очистить»; чтение раз в 2 с, только пока панель видна | паритет со страницей «Мониторинг» GTK |
| Справка по сочетаниям | `SHORTCUTS` переезжает в `src/ui/qt/dialogs/shortcuts.py` вместе со своим списком описаний; тест проверяет, что каждое сочетание описано ровно один раз | GTK-список живёт в модуле с `gi` и записан в формате ускорителей GTK |
| «О программе» | свой `QDialog`: логотип, версия, ядро, ссылка, «Копировать сведения» (`Veblock … / xray-core …`); подпись без ОС — «Клиент прокси на базе xray-core» | у `QMessageBox.about` нет кнопки копирования сведений для отчёта об ошибке, как `set_debug_info` в GTK; Qt-модули не читают `IS_WINDOWS` |
| Файлы диалогов | `profile.py` (добавление и правка), `group.py`, `subscription.py`, `confirm.py`, `routing_import.py`, `profile_routing.py`, `settings.py`, `settings_pages.py`, `shortcuts.py`, `about.py` | у двух форм профиля общие поле ссылки и разбор; список подписок и «О программе» со своим поведением вынесены из `settings.py` |
| Флаг в карточке состояния | картинка рядом с именем, полное имя — во всплывающей подсказке | эмодзи-флагов в шрифтах Windows нет |
| Тест фазы 2 `test_dialog_actions_say_they_are_not_there_yet` | удаляется в задаче 6; вместо него — `test_actions_open_their_dialogs` и `test_settings_action_opens_the_settings_window` | заглушку «Раздел появится в следующей сборке» фаза 2 вводила как временную |
| Windows-установщик из CI | по-прежнему нерабочий | spec и CI — фаза 4 |

## Что уже есть и переиспользуется без изменений

- `AppController`: `add_profile_from_bean`, `delete_profile`, `add_group`, `update_group`, `delete_group`, `save_profiles`, `apply_settings`, `restore_routing`, `sync_restore_routing`, `add_subscription`, `update_subscription`, `test_latency_for`, `test_latency_for_group`, `keep_working_profiles`, константы `CONFIRM_DELETE` и `CONFIRM_URL_CHANGE` — `src/ui/controller.py`.
- Проверка форм: `validate_profile_link`, `validate_subscription`, `validate_group_name`, `parse_host_list` — `src/ui/logic/forms.py`; `validate_settings` — `settings_form.py`; `ImportRow` и `REST_LABEL` — `routing_import.py`; `build_subscription_rows`, `format_updated` — `subscriptions_view.py`; `core_version`, `core_update_text`, `app_version` — `version.py`; `geo_summary`, `current_catalog`, `ru_direct_subtitle` — `routing_form.py`; `THEMES` и `THEME_LABELS` — `appearance.py`; `run_in_background(dispatch=…)` — `async_utils.py`.
- `read_diagnostics` — `src/core/diagnostics_export.py`; `LogManager.clear_all_logs` — `src/core/log_manager.py` (открытые `.log` обрезает, а не удаляет).
- Qt из фазы 2: `QtLoop`, `QtApplication.present_dialog` (один слот), `MainWindow`, `ProfileTreeModel`, `StatusCard`, `flagged`.

---

### Task 0: Сверка с кодом

**Files:** только чтение.

**Step 1:** Фаза 2 на месте:

```bash
grep -n "NOT_YET\b\|def present_dialog\|def activate_action" src/ui/qt/application.py
grep -n "def set_rows" src/ui/qt/models.py
grep -n "ORDER_PRESETS\|^LOG_LEVELS" src/ui/dialogs/profile_routing.py src/ui/dialogs/settings.py
QT_QPA_PLATFORM=offscreen uv run python -c "from PySide6.QtGui import QIcon; print(QIcon.ThemeIcon.EditPaste)"
```

Expected: `NOT_YET`, `present_dialog` и `activate_action` найдены; константы ещё определены в GTK-модулях; `QIcon.ThemeIcon` существует.

**Step 2:** Числа (ориентир на 28.10.2026 после фазы 2):

```bash
uv run pytest -q --no-cov -p no:cacheprovider 2>&1 | tail -1   # 1587 passed, 10 skipped
make test-gtk 2>&1 | grep -E "passed|failed" | tail -1          # 279 passed
make test-tray 2>&1 | tail -1                                    # 146 passed, 5 skipped
make test-qt 2>&1 | tail -1                                      # 50 passed
```

---

### Task 1: Константы форм в `src/ui/logic`, поля окна в настройках

Qt-окнам нужны пресеты порядка правил и уровни журнала, а GTK-модули с ними импортируют `gi`. Константы переезжают в модули логики без GTK; GTK-диалоги импортируют их оттуда.

**Files:**
- Modify: `src/ui/logic/routing_form.py`, `src/ui/logic/settings_form.py`
- Modify: `src/ui/dialogs/profile_routing.py`, `src/ui/dialogs/settings.py` (только импорт вместо определения)
- Modify: `src/db/data_store.py`
- Test: `tests/test_ui_logic_routing_form.py`, `tests/test_db_data_store.py` (новые тесты в конец)

**Step 1: Write the failing tests:**

```diff
diff --git a/tests/test_ui_logic_routing_form.py b/tests/test_ui_logic_routing_form.py
index b3789f4..fb8bfaa 100644
--- a/tests/test_ui_logic_routing_form.py
+++ b/tests/test_ui_logic_routing_form.py
@@ -66,3 +66,19 @@ def test_domain_rules_match_the_name_the_core_compares(raw, expected):
 def test_malformed_domain_rules_are_rejected(raw):
     with pytest.raises(ValueError, match="Некорректн"):
         normalize_routing_entry(raw)
+
+
+# --- порядок групп правил (общий для GTK и Qt) ---
+
+
+def test_order_key_finds_the_preset():
+    from src.ui.logic.routing_form import ORDER_LABELS, ORDER_PRESETS, order_key
+
+    assert order_key(["vpn", "proxy", "direct"]) == "vpn_proxy_direct"
+    assert set(ORDER_PRESETS) == set(ORDER_LABELS)
+
+
+def test_unknown_order_falls_back_to_the_first_preset():
+    from src.ui.logic.routing_form import order_key
+
+    assert order_key(["proxy"]) == "direct_vpn_proxy"
```

```diff
diff --git a/tests/test_db_data_store.py b/tests/test_db_data_store.py
index 7978fde..083d0b5 100644
--- a/tests/test_db_data_store.py
+++ b/tests/test_db_data_store.py
@@ -128,3 +128,10 @@ def test_failed_atomic_settings_save_preserves_previous_file(tmp_path, monkeypat
     assert config.save(path) is False
     assert path.read_bytes() == before
     assert [item.name for item in tmp_path.iterdir()] == [path.name]
+
+
+def test_qt_window_preferences_default_on():
+    store = DataStore()
+
+    assert store.close_to_tray is True
+    assert store.monitoring_panel is True
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_ui_logic_routing_form.py tests/test_db_data_store.py -q --no-cov -p no:cacheprovider`
Expected: FAIL: `ImportError: cannot import name 'ORDER_LABELS'` и `AttributeError: 'DataStore' object has no attribute 'close_to_tray'`.

**Step 3: Implementation**

```diff
diff --git a/src/ui/logic/routing_form.py b/src/ui/logic/routing_form.py
index 447741f..c9770a6 100644
--- a/src/ui/logic/routing_form.py
+++ b/src/ui/logic/routing_form.py
@@ -8,6 +8,37 @@ from src.core.geo import RU_DIRECT_GEOIP, RU_DIRECT_GEOSITES, GeoCatalog, asset_
 LIST_HINT = "По одной записи в строке: домен, подсеть, geosite:категория, geoip:страна"
 BLOCK_HINT = "Соединения обрываются, имена не резолвятся. Применяется раньше остальных списков"
 
+# Порядок групп правил маршрутизации профиля: ключ настройки → порядок.
+ORDER_PRESETS: dict[str, list[str]] = {
+    "direct_vpn_proxy": ["direct", "vpn", "proxy"],
+    "direct_proxy_vpn": ["direct", "proxy", "vpn"],
+    "vpn_direct_proxy": ["vpn", "direct", "proxy"],
+    "vpn_proxy_direct": ["vpn", "proxy", "direct"],
+    "proxy_direct_vpn": ["proxy", "direct", "vpn"],
+    "proxy_vpn_direct": ["proxy", "vpn", "direct"],
+}
+
+ORDER_LABELS = {
+    "direct_vpn_proxy": "Напрямую → VPN → Прокси",
+    "direct_proxy_vpn": "Напрямую → Прокси → VPN",
+    "vpn_direct_proxy": "VPN → Напрямую → Прокси",
+    "vpn_proxy_direct": "VPN → Прокси → Напрямую",
+    "proxy_direct_vpn": "Прокси → Напрямую → VPN",
+    "proxy_vpn_direct": "Прокси → VPN → Напрямую",
+}
+
+
+def order_key(order: list[str]) -> str:
+    """Ключ пресета для сохранённого порядка; незнакомый — первый пресет.
+
+    Порядок мог прийти из другой версии или из испорченного файла.
+    """
+    for key, preset in ORDER_PRESETS.items():
+        if preset == list(order):
+            return key
+    return next(iter(ORDER_PRESETS))
+
+
 _RU_DIRECT_RULES = (*RU_DIRECT_GEOSITES, RU_DIRECT_GEOIP)
 
 
```

```diff
diff --git a/src/ui/logic/settings_form.py b/src/ui/logic/settings_form.py
index eacffdd..39ef431 100644
--- a/src/ui/logic/settings_form.py
+++ b/src/ui/logic/settings_form.py
@@ -9,6 +9,10 @@ from urllib.parse import urlsplit
 from src.db.config import TlsFragmentSettings
 from src.sub.url_policy import SubscriptionPolicyError, validate_url
 
+LOG_LEVELS = ["debug", "info", "warning", "error", "none"]
+DEFAULT_LOG_LEVEL = "info"
+DEFAULT_TUN_NAME = "xray0"
+
 
 def valid_dns_address(value: str) -> bool:
     if not value or value == "local":
```

```diff
diff --git a/src/ui/dialogs/profile_routing.py b/src/ui/dialogs/profile_routing.py
index 809b604..7e43162 100644
--- a/src/ui/dialogs/profile_routing.py
+++ b/src/ui/dialogs/profile_routing.py
@@ -13,25 +13,14 @@ from src.db.config import RoutingMode, RoutingSettings, VpnSettings
 from src.ui.dialogs.settings import KeyedCombo
 from src.ui.logic import platform_texts
 from src.ui.logic.forms import parse_host_list
-from src.ui.logic.routing_form import BLOCK_HINT, LIST_HINT, current_catalog, ru_direct_subtitle
-
-ORDER_PRESETS: dict[str, list[str]] = {
-    "direct_vpn_proxy": ["direct", "vpn", "proxy"],
-    "direct_proxy_vpn": ["direct", "proxy", "vpn"],
-    "vpn_direct_proxy": ["vpn", "direct", "proxy"],
-    "vpn_proxy_direct": ["vpn", "proxy", "direct"],
-    "proxy_direct_vpn": ["proxy", "direct", "vpn"],
-    "proxy_vpn_direct": ["proxy", "vpn", "direct"],
-}
-
-ORDER_LABELS = {
-    "direct_vpn_proxy": "Напрямую → VPN → Прокси",
-    "direct_proxy_vpn": "Напрямую → Прокси → VPN",
-    "vpn_direct_proxy": "VPN → Напрямую → Прокси",
-    "vpn_proxy_direct": "VPN → Прокси → Напрямую",
-    "proxy_direct_vpn": "Прокси → Напрямую → VPN",
-    "proxy_vpn_direct": "Прокси → VPN → Напрямую",
-}
+from src.ui.logic.routing_form import (
+    BLOCK_HINT,
+    LIST_HINT,
+    ORDER_LABELS,
+    ORDER_PRESETS,
+    current_catalog,
+    ru_direct_subtitle,
+)
 
 
 def _list_view(title: str, subtitle: str) -> tuple[Adw.PreferencesGroup, Gtk.TextView]:
```

```diff
diff --git a/src/ui/dialogs/settings.py b/src/ui/dialogs/settings.py
index 97bf3a1..614424d 100644
--- a/src/ui/dialogs/settings.py
+++ b/src/ui/dialogs/settings.py
@@ -23,14 +23,15 @@ from src.ui.logic import platform_layout, platform_texts
 from src.ui.logic.appearance import THEME_LABELS, THEMES, normalize_theme
 from src.ui.logic.async_utils import run_in_background
 from src.ui.logic.routing_form import current_catalog, geo_summary
-from src.ui.logic.settings_form import validate_settings
+from src.ui.logic.settings_form import (
+    DEFAULT_LOG_LEVEL,
+    DEFAULT_TUN_NAME,
+    LOG_LEVELS,
+    validate_settings,
+)
 from src.ui.logic.version import UNKNOWN, app_version, core_update_text, core_version
 from src.ui.window import apply_theme
 
-LOG_LEVELS = ["debug", "info", "warning", "error", "none"]
-DEFAULT_LOG_LEVEL = "info"
-DEFAULT_TUN_NAME = "xray0"
-
 
 class KeyedCombo:
     """An Adw.ComboRow addressed by string keys instead of indices.
```

```diff
diff --git a/src/db/data_store.py b/src/db/data_store.py
index d3747a6..4d1deef 100644
--- a/src/db/data_store.py
+++ b/src/db/data_store.py
@@ -57,6 +57,9 @@ class DataStore(ConfigBase):
     window_size: str = ""
     splitter_state: str = ""
     start_minimal: bool = False
+    # Qt-интерфейс: закрытие окна прячет его в трей; панель мониторинга видна.
+    close_to_tray: bool = True
+    monitoring_panel: bool = True
     # Subscriptions
     user_agent: str = ""
     # HWID создаётся при включении флага и скрыт из repr настроек.
```

Новые поля `DataStore` не входят в `_RUNTIME_KEYS` (`settings_state.py`), поэтому их смена не вызывает плашку «Изменения применятся после переподключения».

**Step 4: Run to verify it passes**

```bash
uv run pytest tests/test_ui_logic_routing_form.py tests/test_db_data_store.py -q --no-cov -p no:cacheprovider
make test-gtk 2>&1 | grep -E "passed|failed" | tail -1
```

Expected: всё зелёное, GTK — 279 passed.

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/logic src/ui/dialogs/profile_routing.py src/ui/dialogs/settings.py src/db/data_store.py tests/test_ui_logic_routing_form.py tests/test_db_data_store.py
git commit -m "refactor(ui): константы форм маршрутизации и настроек — в src/ui/logic"
```

---

### Task 2: Каркас Qt-диалогов и модуль темы

`FormDialog` — форма с «Отмена» и кнопкой подтверждения. `KeyedCombo` — выпадающий список, адресуемый ключами настроек. `Debounce` — автосохранение через 500 мс. `watch` подписывает сохранение на правку любого поля, `mark_error` подсвечивает поле с ошибкой, `icon_button` — кнопка с системной иконкой. `apply_theme` переезжает из `application.py` в `theme.py`: окно настроек меняет тему сразу и не должно импортировать приложение.

**Files:**
- Create: `src/ui/qt/dialogs/__init__.py`, `src/ui/qt/dialogs/base.py`, `src/ui/qt/theme.py`
- Modify: `src/ui/qt/application.py`
- Test: `tests/test_ui_qt_dialogs_base.py`

**Step 1: Write the failing test** — `tests/test_ui_qt_dialogs_base.py`:

```python
"""Каркас Qt-диалогов: форма, выбор по ключу, автосохранение, ошибки полей."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QCheckBox, QLineEdit

from src.ui.qt.dialogs.base import Debounce, FormDialog, KeyedCombo, mark_error, watch
from tests.support.qt import process_events, wait_until

pytestmark = pytest.mark.qt


def test_form_buttons_and_status(qapp):
    dialog = FormDialog("Заголовок", "Готово")

    assert dialog.windowTitle() == "Заголовок"
    assert dialog.confirm_button.text() == "Готово"
    assert dialog.confirm_button.isDefault()
    dialog.set_status("Ошибка", error=True)
    assert not dialog.status.isHidden()
    assert dialog.status.property("error") is True
    dialog.set_status("")
    assert dialog.status.isHidden()


def test_keyed_combo_falls_back_to_the_first_key(qapp):
    combo = KeyedCombo(["a", "b"], {"a": "Альфа", "b": "Бета"})

    combo.select("b")
    assert combo.selected() == "b" and combo.currentText() == "Бета"
    combo.select("из другой версии")
    assert combo.selected() == "a"


def test_debounce_runs_once_and_flushes(qapp):
    calls = []
    debounce = Debounce(lambda: calls.append(1), delay_ms=10)

    debounce.queue()
    debounce.queue()
    wait_until(lambda: calls)
    for _ in range(5):
        process_events()
    assert calls == [1]

    debounce.queue()
    debounce.flush()
    assert calls == [1, 1] and not debounce.pending
    debounce.flush()
    assert calls == [1, 1]


def test_watch_connects_every_field(qapp):
    seen = []
    edit, box = QLineEdit(), QCheckBox()
    watch([edit, box], lambda *_: seen.append(1))

    edit.setText("x")
    box.setChecked(True)

    assert seen == [1, 1]


def test_mark_error_sets_tooltip(qapp):
    edit = QLineEdit()

    mark_error(edit, "Плохо")
    assert edit.property("error") is True and edit.toolTip() == "Плохо"
    mark_error(edit, None)
    assert edit.property("error") is False and edit.toolTip() == ""
```

**Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -m qt tests/test_ui_qt_dialogs_base.py -q --no-cov -p no:cacheprovider`
Expected: FAIL, `ModuleNotFoundError: No module named 'src.ui.qt.dialogs'`

**Step 3: Implementation**

`src/ui/qt/dialogs/__init__.py`:

```python
"""Диалоги Qt-интерфейса: формы, подтверждения, настройки."""
```

`src/ui/qt/dialogs/base.py`:

```python
"""Общий каркас диалогов Qt: форма с кнопками, выбор по ключу, автосохранение.

Проверка полей — в `src/ui/logic/forms.py` и `settings_form.py`, общих с GTK;
здесь только то, что нужно виджетам Qt.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PySide6.QtCore import QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

DEFAULT_WIDTH = 520
AUTOSAVE_DELAY_MS = 500

# Свои правила только для ошибок: поле в обычном состоянии остаётся системным.
FORM_STYLE = """
QLabel[error="true"] { color: #d13438; }
QLineEdit[error="true"], QPlainTextEdit[error="true"] { border: 1px solid #d13438; }
"""


def mark_error(widget: QWidget, message: str | None) -> None:
    """Подсветить поле с ошибкой и объяснить её во всплывающей подсказке."""
    widget.setProperty("error", bool(message))
    widget.setToolTip(message or "")
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def icon_button(theme_icon: str, text: str, tooltip: str) -> QToolButton:
    """Кнопка с системной иконкой (`QIcon.ThemeIcon`), без неё — с подписью.

    На Windows иконки даёт шрифт Segoe Fluent Icons (Segoe MDL2 на 10), на
    Linux — тема рабочего стола; где темы нет, остаётся короткий текст.
    """
    button = QToolButton()
    icon = QIcon.fromTheme(getattr(QIcon.ThemeIcon, theme_icon))
    if icon.isNull():
        button.setText(text)
    else:
        button.setIcon(icon)
    button.setToolTip(tooltip)
    button.setAutoRaise(True)
    return button


def row(*widgets: QWidget) -> QWidget:
    """Поле с кнопками справа — одна строка формы."""
    box = QWidget()
    layout = QHBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    for index, widget in enumerate(widgets):
        layout.addWidget(widget, 1 if index == 0 else 0)
    return box


def clipboard_text() -> str:
    return QGuiApplication.clipboard().text().strip()


def copy_text(text: str) -> None:
    QGuiApplication.clipboard().setText(text)


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


class FormDialog(QDialog):
    """Модальная форма: поля, строка состояния, «Отмена» и кнопка подтверждения.

    Кнопка подтверждения — кнопка по умолчанию: Enter в последнем поле
    отправляет форму, как в обычных диалогах Windows.
    """

    def __init__(self, title: str, confirm_label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(DEFAULT_WIDTH)
        self.setStyleSheet(FORM_STYLE)

        self.form = QFormLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        # Текст приходит из ссылок и от провайдеров: не разметка.
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.hide()

        self.buttons = QDialogButtonBox()
        self.confirm_button = self.buttons.addButton(
            confirm_label, QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.confirm_button.setDefault(True)
        self.cancel_button = self.buttons.addButton(
            "Отмена", QDialogButtonBox.ButtonRole.RejectRole
        )
        self.buttons.accepted.connect(self._on_confirm)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.status)
        layout.addStretch(1)
        layout.addWidget(self.buttons)

    def set_status(self, text: str, *, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))
        self.status.setProperty("error", error)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)

    def _on_confirm(self) -> None:
        """Для наследников; по умолчанию просто закрывает форму."""
        self.accept()


class KeyedCombo(QComboBox):
    """Выпадающий список, адресуемый строковыми ключами настроек."""

    def __init__(self, keys: Iterable[str], labels: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.keys = list(keys)
        for key in self.keys:
            self.addItem(labels.get(key, key), key)

    def select(self, key: str) -> None:
        """Выбрать ключ; незнакомый (настройка другой версии) — первый."""
        index = self.findData(key)
        self.setCurrentIndex(index if index >= 0 else 0)

    def selected(self) -> str:
        key = self.currentData()
        return key if key is not None else self.keys[0]


class Debounce(QObject):
    """Отложенный вызов: серия правок сохраняется один раз, через полсекунды."""

    def __init__(
        self, fn: Callable[[], object], delay_ms: int = AUTOSAVE_DELAY_MS, parent=None
    ) -> None:
        super().__init__(parent)
        self._fn = fn
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(fn)

    def queue(self, *_args: object) -> None:
        self._timer.start()

    @property
    def pending(self) -> bool:
        return self._timer.isActive()

    def flush(self) -> None:
        """Сохранить отложенное сейчас: окно закрывается."""
        if self._timer.isActive():
            self._timer.stop()
            self._fn()


def watch(widgets: Iterable[QWidget], callback: Callable[..., object]) -> None:
    """Подписать callback на изменение каждого поля формы."""
    for widget in widgets:
        if isinstance(widget, QLineEdit | QPlainTextEdit):
            widget.textChanged.connect(callback)
        elif isinstance(widget, QCheckBox):
            widget.toggled.connect(callback)
        elif isinstance(widget, QSpinBox):
            widget.valueChanged.connect(callback)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(callback)
        else:
            raise TypeError(f"Неизвестное поле формы: {type(widget).__name__}")
```

`src/ui/qt/theme.py`:

```python
"""Цветовая схема Qt-интерфейса по настройке «Тема»."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from src.ui.logic.appearance import normalize_theme


def apply_theme(theme: str | None) -> None:
    """Светлая или тёмная схема; в «Системной» Qt сам следит за ОС."""
    scheme = {
        "light": Qt.ColorScheme.Light,
        "dark": Qt.ColorScheme.Dark,
    }.get(normalize_theme(theme), Qt.ColorScheme.Unknown)
    QGuiApplication.styleHints().setColorScheme(scheme)
```

`src/ui/qt/application.py` — `apply_theme` теперь из `theme.py`:

```diff
diff --git a/src/ui/qt/application.py b/src/ui/qt/application.py
index 9c0d565..be9ef66 100644
--- a/src/ui/qt/application.py
+++ b/src/ui/qt/application.py
@@ -13,15 +13,15 @@ from collections.abc import Callable
 from typing import TYPE_CHECKING
 
 from PySide6.QtCore import Qt, QTimer
-from PySide6.QtGui import QAction, QGuiApplication, QIcon, QKeySequence
+from PySide6.QtGui import QAction, QIcon, QKeySequence
 from PySide6.QtNetwork import QNetworkInformation
 from PySide6.QtWidgets import QApplication, QMessageBox
 
 from src.core.config import get_asset_path
 from src.ui.controller import CONFIRM_URL_CHANGE, AppController, resume_monitoring
-from src.ui.logic.appearance import normalize_theme
 from src.ui.logic.version import app_version
 from src.ui.qt.dispatch import QtLoop
+from src.ui.qt.theme import apply_theme
 from src.ui.qt.window import MainWindow
 
 if TYPE_CHECKING:
@@ -69,15 +69,6 @@ def network_available() -> bool:
     return info.reachability() != QNetworkInformation.Reachability.Disconnected
 
 
-def apply_theme(theme: str | None) -> None:
-    """Светлая или тёмная схема; в «Системной» Qt сам следит за ОС."""
-    scheme = {
-        "light": Qt.ColorScheme.Light,
-        "dark": Qt.ColorScheme.Dark,
-    }.get(normalize_theme(theme), Qt.ColorScheme.Unknown)
-    QGuiApplication.styleHints().setColorScheme(scheme)
-
-
 class _QtShell:
     """`Shell` контроллера поверх `QtApplication`; без окна — ничего не делает."""
 
```

Замечания:
- QSS формы трогает только поля с `error=true`: в обычном состоянии поле остаётся системным (`windows11`/`windowsvista`).
- В offscreen и на Linux без темы иконок `QIcon.fromTheme` пуст, поэтому кнопка показывает короткий текст. На Windows иконки даёт платформенная тема Qt.

**Step 4: Run to verify it passes** — Expected: 5 passed; `make test-qt` — 55 passed.

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/qt/dialogs src/ui/qt/theme.py src/ui/qt/application.py tests/test_ui_qt_dialogs_base.py
git commit -m "feat(qt): каркас диалогов — форма, выбор по ключу, автосохранение"
```

---

### Task 3: Формы профиля, группы и подписки

**Files:**
- Create: `src/ui/qt/dialogs/profile.py`, `src/ui/qt/dialogs/group.py`, `src/ui/qt/dialogs/subscription.py`
- Test: `tests/test_ui_qt_forms.py`

**Step 1: Write the failing test** — `tests/test_ui_qt_forms.py`:

```python
"""Формы Qt: профиль, группа, подписка."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from src.fmt import parse_link
from src.ui.qt.dialogs.group import GroupDialog
from src.ui.qt.dialogs.profile import AddProfileDialog, EditProfileDialog
from src.ui.qt.dialogs.subscription import SubscriptionDialog

pytestmark = pytest.mark.qt

LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#FromLink"
OTHER = "vless://22222222-2222-2222-2222-222222222222@new.example:8443?type=tcp#New"


# --- добавление профиля ---


def test_add_profile_starts_disabled_and_accepts_a_link(qapp):
    dialog = AddProfileDialog()
    assert not dialog.confirm_button.isEnabled()

    dialog.link_edit.setText(f"  {LINK}  ")

    assert dialog.confirm_button.isEnabled()
    assert dialog.status.text().startswith("VLESS: host.example")
    assert dialog.name_edit.text() == "FromLink"


def test_add_profile_explains_a_broken_link(qapp):
    dialog = AddProfileDialog()

    dialog.link_edit.setText("vless://")

    assert not dialog.confirm_button.isEnabled()
    assert dialog.status.text() == "Не удалось разобрать ссылку"
    assert dialog.status.property("error") is True


def test_add_profile_keeps_a_typed_name(qapp):
    dialog = AddProfileDialog()
    dialog.name_edit.setText("Мой")
    dialog.name_edit.textEdited.emit("Мой")

    dialog.link_edit.setText(LINK)

    assert dialog.name_edit.text() == "Мой"
    assert dialog.get_profile().name == "Мой"


def test_add_profile_reports_the_bean_and_closes(qapp):
    dialog = AddProfileDialog(link=LINK)
    seen = []
    dialog.profile_ready.connect(seen.append)

    dialog.confirm_button.click()

    assert [bean.name for bean in seen] == ["FromLink"]
    assert dialog.result() == dialog.DialogCode.Accepted


def test_paste_takes_the_clipboard(qapp):
    QApplication.clipboard().setText(f"{LINK}\n")
    dialog = AddProfileDialog()

    dialog.paste_button.click()

    assert dialog.link_edit.text() == LINK


# --- правка профиля ---


def _profile():
    return SimpleNamespace(id=1, bean=parse_link(LINK))


def test_edit_profile_is_prefilled(qapp):
    dialog = EditProfileDialog(_profile())

    assert dialog.name_edit.text() == "FromLink"
    assert dialog.address_edit.text() == "host.example"
    assert dialog.port_spin.value() == 443
    assert dialog.link_edit.text().startswith("vless://")


def test_applied_link_waits_for_save(qapp):
    profile = _profile()
    dialog = EditProfileDialog(profile)
    dialog.link_edit.setText(OTHER)

    assert dialog.apply_link()
    assert profile.bean.server_address == "host.example"
    assert dialog.address_edit.text() == "new.example"

    dialog.confirm_button.click()
    assert profile.bean.server_address == "new.example"
    assert profile.bean.server_port == 8443


def test_broken_link_changes_nothing(qapp):
    dialog = EditProfileDialog(_profile())
    dialog.link_edit.setText("garbage")

    assert not dialog.apply_link()
    assert dialog.status.property("error") is True
    assert dialog.address_edit.text() == "host.example"


def test_empty_address_keeps_the_old_one(qapp):
    profile = _profile()
    dialog = EditProfileDialog(profile)
    saved = []
    dialog.profile_saved.connect(lambda: saved.append(1))
    dialog.address_edit.setText(" ")
    dialog.name_edit.setText(" Новое ")

    dialog.confirm_button.click()

    assert saved == [1]
    assert profile.bean.server_address == "host.example"
    assert profile.bean.name == "Новое"


def test_copy_puts_the_link_on_the_clipboard(qapp):
    dialog = EditProfileDialog(_profile())

    dialog.copy_button.click()

    assert QApplication.clipboard().text() == dialog.link_edit.text()
    assert dialog.status.text() == "Ссылка скопирована"


# --- группа ---


def test_group_dialog_titles_and_saving(qapp):
    assert GroupDialog().windowTitle() == "Новая группа"
    plain = SimpleNamespace(name="Дом", is_subscription=False)
    assert GroupDialog(plain).windowTitle() == "Редактировать группу"

    dialog = GroupDialog()
    assert not dialog.confirm_button.isEnabled()
    dialog.name_edit.setText("  Работа ")
    seen = []
    dialog.group_ready.connect(seen.append)
    dialog.confirm_button.click()

    assert seen == ["Работа"]


# --- подписка ---


def _group(**kwargs):
    return SimpleNamespace(
        id=1,
        name=kwargs.get("name", "Sub"),
        subscription_url=kwargs.get("url", "https://e.com/s"),
        last_updated=kwargs.get("last_updated", 0),
    )


def test_new_subscription_is_empty_and_quiet(qapp):
    dialog = SubscriptionDialog()

    assert dialog.windowTitle() == "Добавить подписку"
    assert not dialog.confirm_button.isEnabled()
    assert dialog.status.isHidden()
    assert dialog.form.rowCount() == 2  # «Обновлено» только у существующей


def test_bad_url_is_explained(qapp):
    dialog = SubscriptionDialog()

    dialog.url_edit.setText("ftp://e.com")

    assert not dialog.confirm_button.isEnabled()
    assert dialog.status.text() == "URL должен начинаться с http:// или https://"


def test_missing_name_falls_back_to_the_host(qapp):
    dialog = SubscriptionDialog()
    seen = []
    dialog.subscription_ready.connect(lambda name, url: seen.append((name, url)))

    dialog.url_edit.setText(" https://sub.example.org/x ")
    dialog.confirm_button.click()

    assert seen and seen[0][1] == "https://sub.example.org/x"
    assert seen[0][0]


def test_existing_subscription_is_prefilled(qapp):
    dialog = SubscriptionDialog(_group(name="Провайдер"))

    assert dialog.windowTitle() == "Редактировать подписку"
    assert dialog.name_edit.text() == "Провайдер"
    assert dialog.url_edit.text() == "https://e.com/s"
    assert dialog.updated_label.text() == "Никогда"
```

**Step 2: Run to verify it fails** — `ModuleNotFoundError: No module named 'src.ui.qt.dialogs.group'`.

**Step 3: Implementation**

`src/ui/qt/dialogs/profile.py`:

```python
"""Добавление профиля по ссылке и правка его основных полей."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QSpinBox, QWidget

from src.ui.logic.forms import validate_profile_link
from src.ui.qt.dialogs.base import FormDialog, clipboard_text, copy_text, icon_button, row

PLACEHOLDER = "vless://… trojan://… hysteria2://…"
APPLIED = "Параметры обновлены из ссылки"


class AddProfileDialog(FormDialog):
    """Ссылка подключения и необязательное имя; сообщает разобранный профиль."""

    profile_ready = Signal(object)

    def __init__(self, parent: QWidget | None = None, *, link: str = "") -> None:
        super().__init__("Добавить профиль", "Добавить", parent)
        # Имя, введённое вручную, не затирается именем из ссылки.
        self._name_touched = False

        self.link_edit = QLineEdit()
        self.link_edit.setPlaceholderText(PLACEHOLDER)
        self.link_edit.textChanged.connect(self._on_link_changed)
        self.paste_button = icon_button("EditPaste", "Вставить", "Вставить из буфера обмена")
        self.paste_button.clicked.connect(lambda: self.link_edit.setText(clipboard_text()))
        self.form.addRow("Ссылка", row(self.link_edit, self.paste_button))

        self.name_edit = QLineEdit()
        self.name_edit.textEdited.connect(self._on_name_edited)
        self.form.addRow("Имя", self.name_edit)

        self.confirm_button.setEnabled(False)
        if link:
            self.link_edit.setText(link)

    def _on_name_edited(self, text: str) -> None:
        # textEdited, а не textChanged: подстановка имени из ссылки ручным
        # вводом не считается.
        self._name_touched = bool(text.strip())

    def _on_link_changed(self, text: str) -> None:
        if not text.strip():
            self.set_status("")
            self.confirm_button.setEnabled(False)
            return
        result = validate_profile_link(text, name=self.name_edit.text())
        self.set_status("\n".join((result.message, *result.warnings)), error=not result.ok)
        self.confirm_button.setEnabled(result.ok)
        if result.ok and not self._name_touched and result.bean.name:
            self.name_edit.setText(result.bean.name)

    def get_profile(self):
        """Разобранный профиль с введённым именем; None — ссылка не разбирается."""
        result = validate_profile_link(self.link_edit.text(), name=self.name_edit.text())
        return result.bean if result.ok else None

    def _on_confirm(self) -> None:
        bean = self.get_profile()
        if bean is None:
            return
        self.profile_ready.emit(bean)
        self.accept()


class EditProfileDialog(FormDialog):
    """Имя, сервер, порт и строка подключения одного профиля."""

    profile_saved = Signal()

    def __init__(self, profile, parent: QWidget | None = None) -> None:
        super().__init__("Редактировать профиль", "Сохранить", parent)
        self._profile = profile
        # Профиль из применённой ссылки ждёт «Сохранить»: форма правит живой
        # объект хранилища, и подмена сразу пережила бы «Отмену».
        self._pending_bean = None
        bean = profile.bean

        self.name_edit = QLineEdit(bean.display_name)
        self.form.addRow("Имя", self.name_edit)
        self.address_edit = QLineEdit(str(bean.server_address))
        self.form.addRow("Сервер", self.address_edit)
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(int(bean.server_port))
        self.form.addRow("Порт", self.port_spin)

        self.link_edit = QLineEdit(bean.to_share_link())
        self.copy_button = icon_button("EditCopy", "Копировать", "Копировать ссылку")
        self.copy_button.clicked.connect(self._on_copy)
        self.apply_button = QPushButton("Применить")
        self.apply_button.setToolTip("Разобрать строку и обновить поля")
        self.apply_button.setAutoDefault(False)
        self.apply_button.clicked.connect(self.apply_link)
        self.form.addRow("Ссылка", row(self.link_edit, self.copy_button, self.apply_button))
        hint = QLabel("Вставьте новую строку, чтобы заменить параметры профиля")
        hint.setWordWrap(True)
        self.form.addRow("", hint)

    def _on_copy(self) -> None:
        copy_text(self.link_edit.text())
        self.set_status("Ссылка скопирована")

    def apply_link(self) -> bool:
        """Разобрать строку и перенести её параметры в поля."""
        result = validate_profile_link(self.link_edit.text())
        if not result.ok:
            self.set_status(result.message, error=True)
            return False
        bean = result.bean
        self._pending_bean = bean
        self.name_edit.setText(bean.display_name)
        self.address_edit.setText(str(bean.server_address))
        self.port_spin.setValue(int(bean.server_port))
        self.link_edit.setText(bean.to_share_link())
        self.set_status("\n".join((APPLIED, *result.warnings)))
        return True

    def apply_changes(self) -> None:
        if self._pending_bean is not None:
            self._profile.bean = self._pending_bean
            self._pending_bean = None
        bean = self._profile.bean
        bean.name = self.name_edit.text().strip()
        address = self.address_edit.text().strip()
        if address:
            # Пустой адрес молча сломал бы профиль — тогда остаётся прежний.
            bean.server_address = address
        bean.server_port = self.port_spin.value()

    def _on_confirm(self) -> None:
        self.apply_changes()
        self.profile_saved.emit()
        self.accept()
```

`src/ui/qt/dialogs/group.py`:

```python
"""Создание и переименование группы."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLineEdit, QWidget

from src.ui.logic.forms import validate_group_name
from src.ui.qt.dialogs.base import FormDialog


def title_for(group) -> str:
    if group is None:
        return "Новая группа"
    if getattr(group, "is_subscription", False):
        return "Редактировать подписку"
    return "Редактировать группу"


class GroupDialog(FormDialog):
    group_ready = Signal(str)

    def __init__(self, group=None, parent: QWidget | None = None) -> None:
        super().__init__(title_for(group), "Сохранить", parent)
        self.name_edit = QLineEdit(group.name if group is not None else "")
        self.name_edit.textChanged.connect(self._on_changed)
        self.form.addRow("Название", self.name_edit)
        self._on_changed()

    def _on_changed(self, *_args) -> None:
        self.confirm_button.setEnabled(validate_group_name(self.name_edit.text()).ok)

    def get_name(self) -> str | None:
        result = validate_group_name(self.name_edit.text())
        return result.value if result.ok else None

    def _on_confirm(self) -> None:
        name = self.get_name()
        if name is None:
            return
        self.group_ready.emit(name)
        self.accept()
```

`src/ui/qt/dialogs/subscription.py`:

```python
"""Добавление и правка подписки."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QLineEdit, QWidget

from src.ui.logic.forms import validate_subscription
from src.ui.logic.subscriptions_view import format_updated
from src.ui.qt.dialogs.base import FormDialog, clipboard_text, icon_button, row


class SubscriptionDialog(FormDialog):
    """Название и адрес подписки; сообщает пару (название, адрес)."""

    subscription_ready = Signal(str, str)

    def __init__(self, group=None, parent: QWidget | None = None) -> None:
        title = "Редактировать подписку" if group is not None else "Добавить подписку"
        super().__init__(title, "Сохранить", parent)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("По адресу, если не указать")
        self.form.addRow("Название", self.name_edit)
        self.url_edit = QLineEdit()
        self.paste_button = icon_button("EditPaste", "Вставить", "Вставить из буфера обмена")
        self.paste_button.clicked.connect(lambda: self.url_edit.setText(clipboard_text()))
        self.form.addRow("Адрес", row(self.url_edit, self.paste_button))
        self.updated_label = QLabel(format_updated(getattr(group, "last_updated", 0)))
        if group is not None:
            self.form.addRow("Обновлено", self.updated_label)
            self.name_edit.setText(group.name)
            self.url_edit.setText(group.subscription_url)

        self.name_edit.textChanged.connect(self._on_changed)
        self.url_edit.textChanged.connect(self._on_changed)
        self._on_changed()

    def _on_changed(self, *_args) -> None:
        result = validate_subscription(self.name_edit.text(), self.url_edit.text())
        self.confirm_button.setEnabled(result.ok)
        # Пустая форма только что открыта — говорить об ошибке рано.
        blank = not self.name_edit.text().strip() and not self.url_edit.text().strip()
        self.set_status("" if result.ok or blank else result.message, error=True)

    def get_data(self) -> tuple[str, str] | None:
        result = validate_subscription(self.name_edit.text(), self.url_edit.text())
        return result.value if result.ok else None

    def _on_confirm(self) -> None:
        data = self.get_data()
        if data is None:
            return
        self.subscription_ready.emit(*data)
        self.accept()
```

Отличие от GTK: имя, введённое вручную, отслеживает `textEdited`, а не флаг вокруг `set_text`. `textEdited` срабатывает только на ввод пользователя, поэтому подстановка имени из ссылки ручным вводом не считается.

**Step 4: Run to verify it passes** — Expected: 15 passed; `make test-qt` — 70 passed.

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/qt/dialogs/profile.py src/ui/qt/dialogs/group.py src/ui/qt/dialogs/subscription.py tests/test_ui_qt_forms.py
git commit -m "feat(qt): формы профиля, группы и подписки"
```

---

### Task 4: Подтверждения, импорт маршрутизации, сочетания клавиш, «О программе»

**Files:**
- Create: `src/ui/qt/dialogs/confirm.py`, `src/ui/qt/dialogs/routing_import.py`, `src/ui/qt/dialogs/shortcuts.py`, `src/ui/qt/dialogs/about.py`
- Test: `tests/test_ui_qt_messages.py`

**Step 1: Write the failing test** — `tests/test_ui_qt_messages.py`:

```python
"""Подтверждения, импорт маршрутизации, сочетания клавиш, «О программе»."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.qt


def test_confirmation_defaults_to_cancel(qapp):
    from src.ui.controller import CONFIRM_DELETE
    from src.ui.qt.dialogs.confirm import build_confirmation

    confirmed = []
    box = build_confirmation(
        CONFIRM_DELETE, "Удалить?", "Текст", lambda: confirmed.append(1), confirm_label="Очистить"
    )

    assert box.defaultButton().text() == "Отмена"
    assert box.escapeButton().text() == "Отмена"
    next(b for b in box.buttons() if b.text() == "Очистить").click()
    assert confirmed == [1]


def test_url_change_buttons(qapp):
    from src.ui.controller import CONFIRM_URL_CHANGE
    from src.ui.qt.dialogs.confirm import build_confirmation

    box = build_confirmation(CONFIRM_URL_CHANGE, "Сменить?", "https://x", lambda: None)

    assert sorted(b.text() for b in box.buttons()) == ["Оставить", "Сменить"]


def test_routing_import_lists_rows_and_confirms_only_on_import(qapp):
    from src.ui.logic.routing_import import REST_LABEL, ImportRow
    from src.ui.qt.dialogs.routing_import import RoutingImportDialog

    rows = [
        ImportRow("Профиль", "Дом"),
        ImportRow("Через прокси", "2 правила: +2, −0", ("+ a.example", "+ b.example")),
        ImportRow(REST_LABEL, "через прокси", warning=True),
    ]
    confirmed = []
    dialog = RoutingImportDialog(rows, lambda: confirmed.append(1))

    assert dialog.row_titles() == ["Профиль", "Через прокси", REST_LABEL]
    assert dialog.tree.topLevelItem(1).childCount() == 2
    assert dialog.cancel_button.isDefault()
    dialog.reject()
    assert confirmed == []
    dialog.import_button.click()
    assert confirmed == [1]


def test_shortcuts_cover_every_action_once(qapp):
    from src.ui.qt.dialogs.shortcuts import SECTIONS, SHORTCUTS, ShortcutsDialog, native_text

    listed = [action for _title, entries in SECTIONS for action, _text in entries]
    assert sorted(listed) == sorted(SHORTCUTS)
    assert native_text("add-profile") == "Ctrl+N"
    ShortcutsDialog()


def test_about_copies_both_versions(qapp):
    from src.ui.qt.dialogs.about import AboutDialog

    dialog = AboutDialog("0.20.0", "25.1.1")
    dialog.copy_button.click()

    assert QApplication.clipboard().text() == "Veblock 0.20.0\nxray-core 25.1.1"
    assert dialog.version_label.text() == "Версия 0.20.0"
```

**Step 2: Run to verify it fails** — `ModuleNotFoundError: No module named 'src.ui.qt.dialogs.confirm'`.

**Step 3: Implementation**

`src/ui/qt/dialogs/confirm.py` — то же, что `_QtShell.confirm` фазы 2, но вынесено, чтобы подтверждения строили и приложение, и окно настроек, и журнал:

```python
"""Подтверждения: удаление, смена адреса подписки, очистка журналов."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget

from src.ui.controller import CONFIRM_URL_CHANGE


def build_confirmation(
    kind: str,
    heading: str,
    body: str,
    on_confirm: Callable[[], None],
    *,
    confirm_label: str | None = None,
    parent: QWidget | None = None,
) -> QMessageBox:
    """Вопрос с двумя кнопками; показ — за вызывающим (слот диалога приложения)."""
    if kind == CONFIRM_URL_CHANGE:
        accept, reject = "Сменить", "Оставить"
    else:
        accept, reject = confirm_label or "Удалить", "Отмена"
    box = QMessageBox(QMessageBox.Icon.Question, heading, body, parent=parent)
    # Текст не разметка: имена и адреса приходят от провайдера.
    box.setTextFormat(Qt.TextFormat.PlainText)
    accept_button = box.addButton(accept, QMessageBox.ButtonRole.AcceptRole)
    cancel_button = box.addButton(reject, QMessageBox.ButtonRole.RejectRole)
    # Enter и Escape не подтверждают: удалить или сменить можно только явно.
    box.setDefaultButton(cancel_button)
    box.setEscapeButton(cancel_button)

    def finished(_result: int) -> None:
        if box.clickedButton() is accept_button:
            on_confirm()

    box.finished.connect(finished)
    return box
```

`src/ui/qt/dialogs/routing_import.py`:

```python
"""Подтверждение импорта общей маршрутизации ссылкой."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.logic.routing_import import ImportRow

BODY = (
    "Текущие списки будут заменены. Вернуть их можно в настройках: «О программе» → «Обслуживание»."
)
WARNING_COLOR = QColor("#d13438")


class RoutingImportDialog(QDialog):
    """Строки «подпись — значение» с раскрываемыми изменениями списков."""

    def __init__(
        self,
        rows: list[ImportRow],
        on_confirm: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Импорт маршрутизации")
        self.setModal(True)
        self.setMinimumWidth(560)

        body = QLabel(BODY)
        body.setWordWrap(True)

        # Значения приходят из ссылки: только текст, без разметки (у
        # QTreeWidgetItem её и нет).
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(any(row.details for row in rows))
        for row in rows:
            item = QTreeWidgetItem([row.label, row.value])
            item.setToolTip(1, row.value)
            for line in row.details:
                item.addChild(QTreeWidgetItem(["", line]))
            if row.warning:
                for column in (0, 1):
                    item.setForeground(column, QBrush(WARNING_COLOR))
            self.tree.addTopLevelItem(item)
        self.tree.resizeColumnToContents(0)

        buttons = QDialogButtonBox()
        self.import_button = buttons.addButton(
            "Импортировать", QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.cancel_button = buttons.addButton("Отмена", QDialogButtonBox.ButtonRole.RejectRole)
        # Импорт обратим откатом, но по умолчанию — всё равно «Отмена».
        self.cancel_button.setDefault(True)
        self.import_button.setAutoDefault(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.accepted.connect(on_confirm)

        layout = QVBoxLayout(self)
        layout.addWidget(body)
        layout.addWidget(self.tree, 1)
        layout.addWidget(buttons)

    def row_titles(self) -> list[str]:
        return [self.tree.topLevelItem(i).text(0) for i in range(self.tree.topLevelItemCount())]
```

`src/ui/qt/dialogs/shortcuts.py` — `SHORTCUTS` переезжает сюда из `application.py` (в задаче 6 приложение импортирует его отсюда):

```python
"""Сочетания клавиш: таблица действий и справка по ним."""

from __future__ import annotations

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

# Те же сочетания, что в GTK (`_ACCELS` в src/ui/application.py).
SHORTCUTS: dict[str, str] = {
    "add-profile": "Ctrl+N",
    "add-subscription": "Ctrl+Shift+N",
    "settings": "Ctrl+,",
    "refresh-subscriptions": "F5",
    "quit": "Ctrl+Q",
    "hide-window": "Ctrl+W",
    "toggle-connection": "Ctrl+Return",
    "test-latency": "Ctrl+T",
    "search": "Ctrl+F",
}

# Порядок справки смысловой, как в GTK-справке (src/ui/shortcuts.py).
SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Соединение",
        [
            ("toggle-connection", "Подключить или отключить"),
            ("test-latency", "Проверить задержку"),
        ],
    ),
    (
        "Профили и подписки",
        [
            ("add-profile", "Добавить профиль"),
            ("add-subscription", "Добавить подписку"),
            ("refresh-subscriptions", "Обновить подписки"),
            ("search", "Поиск"),
        ],
    ),
    (
        "Приложение",
        [
            ("settings", "Настройки"),
            ("hide-window", "Скрыть окно"),
            ("quit", "Выход"),
        ],
    ),
]


def native_text(action: str) -> str:
    """Сочетание так, как его пишет система: на macOS — значками, иначе Ctrl+…"""
    return QKeySequence(SHORTCUTS[action]).toString(QKeySequence.SequenceFormat.NativeText)


class ShortcutsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Сочетания клавиш")
        self.setModal(True)
        layout = QVBoxLayout(self)
        for title, entries in SECTIONS:
            box = QGroupBox(title)
            form = QFormLayout(box)
            for action, description in entries:
                form.addRow(description, QLabel(native_text(action)))
            layout.addWidget(box)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Закрыть")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
```

`src/ui/qt/dialogs/about.py`:

```python
"""О программе: версии приложения и ядра, ссылка на проект."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.core.config import get_asset_path
from src.ui.qt.dialogs.base import copy_text

WEBSITE = "https://github.com/vebulogmetra/tenga-proxy"
DEVELOPER = "Artem G."
LOGO_SIZE = 96


def debug_info(version: str, core: str) -> str:
    """Строка для отчёта об ошибке: обе версии рядом, как в GTK."""
    return f"Veblock {version}\nxray-core {core}"


class AboutDialog(QDialog):
    def __init__(self, version: str, core: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("О программе")
        self.setModal(True)
        self._debug_info = debug_info(version, core)

        logo = QLabel()
        pixmap = QPixmap(str(get_asset_path("tenga-proxy.png")))
        if not pixmap.isNull():
            logo.setPixmap(
                pixmap.scaled(
                    LOGO_SIZE,
                    LOGO_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        name = QLabel("Veblock")
        name.setObjectName("aboutName")
        font = name.font()
        font.setPointSizeF(font.pointSizeF() * 1.6)
        font.setBold(True)
        name.setFont(font)
        self.version_label = QLabel(f"Версия {version}")
        self.version_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        comment = QLabel(f"Клиент прокси на базе xray-core {core}")
        comment.setWordWrap(True)
        link = QLabel(f'<a href="{WEBSITE}">{WEBSITE}</a>')
        link.setOpenExternalLinks(True)
        credits = QLabel(f"Разработчик: {DEVELOPER} · Лицензия MIT")

        texts = QVBoxLayout()
        for widget in (name, self.version_label, comment, link, credits):
            texts.addWidget(widget)
        head = QHBoxLayout()
        head.addWidget(logo, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(texts, 1)

        buttons = QDialogButtonBox()
        self.copy_button = buttons.addButton(
            "Копировать сведения", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.copy_button.clicked.connect(lambda: copy_text(self._debug_info))
        close = buttons.addButton("Закрыть", QDialogButtonBox.ButtonRole.RejectRole)
        close.setDefault(True)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(buttons)
```

**Step 4: Run to verify it passes** — Expected: 5 passed; `make test-qt` — 75 passed.

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/qt/dialogs/confirm.py src/ui/qt/dialogs/routing_import.py src/ui/qt/dialogs/shortcuts.py src/ui/qt/dialogs/about.py tests/test_ui_qt_messages.py
git commit -m "feat(qt): подтверждения, импорт маршрутизации, сочетания клавиш, о программе"
```

---

### Task 5: «VPN и маршруты» профиля

Две вкладки, как две страницы `Adw.PreferencesDialog` в GTK. На вкладке «Маршрутизация» прокрутка, иначе четыре списка сжимают блок «Режим». Ошибка в списке подсвечивает именно этот список: GTK писал её в заголовок, не называя поле.

**Files:**
- Create: `src/ui/qt/dialogs/profile_routing.py`
- Test: `tests/test_ui_qt_profile_routing.py`

**Step 1: Write the failing test** — `tests/test_ui_qt_profile_routing.py`:

```python
"""Qt-окно «VPN и маршруты» профиля."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from src.db.config import RoutingMode, RoutingSettings, VpnSettings
from src.fmt import parse_link
from src.ui.qt.dialogs.profile_routing import ProfileRoutingDialog
from tests.support.qt import wait_until

pytestmark = pytest.mark.qt

LINK = "vless://11111111-1111-1111-1111-111111111111@host.example:443?type=tcp#P"


def _profile(vpn=None, routing=None):
    return SimpleNamespace(
        id=1,
        bean=parse_link(LINK),
        vpn_settings=vpn if vpn is not None else VpnSettings(),
        routing_settings=routing if routing is not None else RoutingSettings(),
    )


def test_fields_are_loaded(qapp):
    profile = _profile(
        vpn=VpnSettings(enabled=True, connection_name="work"),
        routing=RoutingSettings(mode=RoutingMode.CUSTOM, proxy_list=["a.com", "b.com"]),
    )

    dialog = ProfileRoutingDialog(profile)

    assert dialog.name_edit.text() == "P"
    assert dialog.address_label.text() == "host.example:443"
    assert dialog.vpn_check.isChecked() and dialog.vpn_name_edit.text() == "work"
    assert dialog.lists["proxy"].toPlainText() == "a.com\nb.com"
    assert dialog.mode_combo.selected() == RoutingMode.CUSTOM


def test_vpn_fields_follow_the_switch(qapp):
    dialog = ProfileRoutingDialog(_profile())
    assert not dialog.vpn_name_edit.isEnabled()

    dialog.vpn_check.setChecked(True)

    assert dialog.vpn_name_edit.isEnabled()


def test_lists_sleep_in_proxy_all(qapp):
    dialog = ProfileRoutingDialog(_profile())

    dialog.mode_combo.select(RoutingMode.PROXY_ALL)
    assert not dialog.lists["proxy"].isEnabled()
    assert dialog.bypass_check.isEnabled()
    dialog.mode_combo.select(RoutingMode.CUSTOM)
    assert dialog.lists["proxy"].isEnabled()


def test_save_writes_everything(qapp):
    profile = _profile()
    dialog = ProfileRoutingDialog(profile)
    saved = []
    dialog.routing_saved.connect(lambda: saved.append(1))
    dialog.vpn_check.setChecked(True)
    dialog.vpn_name_edit.setText("work")
    dialog.mode_combo.select(RoutingMode.CUSTOM)
    dialog.order_combo.select("vpn_proxy_direct")
    dialog.lists["proxy"].setPlainText("a.com\n\n b.com , a.com \n")
    dialog.lists["block"].setPlainText("ads.example")

    assert dialog.save()

    assert saved
    assert profile.vpn_settings.enabled and profile.vpn_settings.connection_name == "work"
    assert profile.routing_settings.proxy_list == ["a.com", "b.com"]
    assert profile.routing_settings.block_list == ["ads.example"]
    assert profile.routing_settings.rule_order == ["vpn", "proxy", "direct"]


def test_bad_entry_marks_its_list_and_keeps_the_profile(qapp):
    profile = _profile(routing=RoutingSettings(mode=RoutingMode.CUSTOM, direct_list=["x.com"]))
    dialog = ProfileRoutingDialog(profile)
    dialog.lists["direct"].setPlainText("http://user:pw@x.com")

    assert not dialog.save()

    assert dialog.lists["direct"].property("error") is True
    assert not dialog.status.isHidden()
    assert profile.routing_settings.direct_list == ["x.com"]


def test_blank_vpn_name_keeps_the_previous_one(qapp):
    profile = _profile(vpn=VpnSettings(enabled=True, connection_name="old"))
    dialog = ProfileRoutingDialog(profile)
    dialog.vpn_name_edit.setText("  ")

    dialog.save()

    assert profile.vpn_settings.connection_name == "old"


def test_unknown_order_falls_back_to_the_first(qapp):
    dialog = ProfileRoutingDialog(_profile(routing=RoutingSettings(rule_order=["nonsense"])))

    assert dialog.order_combo.currentIndex() == 0


def test_edits_autosave_and_closing_flushes(qapp):
    profile = _profile()
    dialog = ProfileRoutingDialog(profile)
    saved = []
    dialog.routing_saved.connect(lambda: saved.append(1))

    dialog.name_edit.setText("Новое")
    assert dialog.autosave.pending
    dialog.reject()

    assert saved == [1]
    assert profile.bean.name == "Новое"

    dialog = ProfileRoutingDialog(profile)
    dialog.routing_saved.connect(lambda: saved.append(2))
    dialog.bypass_check.toggle()
    wait_until(lambda: 2 in saved, timeout=2)
```

**Step 2: Run to verify it fails** — `ModuleNotFoundError: No module named 'src.ui.qt.dialogs.profile_routing'`.

**Step 3: Implementation** — `src/ui/qt/dialogs/profile_routing.py`:

```python
"""VPN и маршрутизация одного профиля.

Как в GTK: кнопки «Сохранить» нет, правки сохраняются через полсекунды
после последней и при закрытии окна.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.db.config import RoutingMode, RoutingSettings, VpnSettings
from src.ui.logic import platform_texts
from src.ui.logic.forms import parse_host_list
from src.ui.logic.routing_form import (
    BLOCK_HINT,
    LIST_HINT,
    ORDER_LABELS,
    ORDER_PRESETS,
    current_catalog,
    order_key,
    ru_direct_subtitle,
)
from src.ui.qt.dialogs.base import FORM_STYLE, Debounce, KeyedCombo, mark_error, watch

LISTS = (
    ("block", "Блокировать", BLOCK_HINT),
    ("proxy", "Через прокси", LIST_HINT),
    ("direct", "Напрямую", LIST_HINT),
    ("vpn", "Через VPN", LIST_HINT),
)


def _check(text: str, subtitle: str = "") -> QCheckBox:
    box = QCheckBox(text)
    box.setToolTip(subtitle)
    return box


class ProfileRoutingDialog(QDialog):
    routing_saved = Signal()

    def __init__(self, profile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VPN и маршруты")
        self.setModal(True)
        self.setMinimumSize(560, 600)
        self.setStyleSheet(FORM_STYLE)
        self._profile = profile
        self.lists: dict[str, QPlainTextEdit] = {}

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_vpn_page(), "VPN")
        self.tabs.addTab(self._scrolled(self._build_routing_page()), "Маршрутизация")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("error", True)
        self.status.hide()
        buttons = QDialogButtonBox()
        close = buttons.addButton("Закрыть", QDialogButtonBox.ButtonRole.RejectRole)
        close.setDefault(True)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(self.status)
        layout.addWidget(buttons)

        self._load()
        self.autosave = Debounce(self.save, parent=self)
        watch(
            [
                self.name_edit,
                self.vpn_check,
                self.vpn_name_edit,
                self.vpn_auto_check,
                self.vpn_interface_edit,
                self.direct_interface_edit,
                self.mode_combo,
                self.order_combo,
                self.bypass_check,
                self.ru_direct_check,
                *self.lists.values(),
            ],
            self.autosave.queue,
        )
        self.finished.connect(lambda _result: self.autosave.flush())

    # --- страницы ---

    @staticmethod
    def _scrolled(body: QWidget) -> QScrollArea:
        # Четыре списка не помещаются в окно целиком: прокрутка вместо сжатия.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body)
        return scroll

    def _build_vpn_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)

        profile = QGroupBox("Профиль")
        form = QFormLayout(profile)
        self.name_edit = QLineEdit()
        form.addRow("Имя", self.name_edit)
        self.address_label = QLabel()
        self.address_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("Сервер", self.address_label)
        column.addWidget(profile)

        vpn = QGroupBox(platform_texts.vpn_group_title())
        form = QFormLayout(vpn)
        description = QLabel(platform_texts.vpn_group_description())
        description.setWordWrap(True)
        form.addRow(description)
        self.vpn_check = QCheckBox("Использовать VPN")
        self.vpn_check.toggled.connect(self._sync_vpn)
        form.addRow(self.vpn_check)
        self.vpn_name_edit = QLineEdit()
        form.addRow("Имя подключения", self.vpn_name_edit)
        self.vpn_auto_check = _check(
            "Подключать автоматически",
            "Поднимать VPN при запуске профиля и опускать при остановке",
        )
        form.addRow(self.vpn_auto_check)
        column.addWidget(vpn)

        interfaces = QGroupBox("Интерфейсы")
        form = QFormLayout(interfaces)
        self.vpn_interface_edit = QLineEdit()
        self.vpn_interface_edit.setPlaceholderText("Определять автоматически")
        form.addRow("Интерфейс VPN", self.vpn_interface_edit)
        self.direct_interface_edit = QLineEdit()
        self.direct_interface_edit.setPlaceholderText("Определять автоматически")
        form.addRow("Интерфейс прямого выхода", self.direct_interface_edit)
        column.addWidget(interfaces)
        column.addStretch(1)
        return page

    def _build_routing_page(self) -> QWidget:
        page = QWidget()
        column = QVBoxLayout(page)

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

        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        for key, title, hint in LISTS:
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
        return page

    # --- состояние ---

    def _sync_vpn(self) -> None:
        enabled = self.vpn_check.isChecked()
        for widget in (
            self.vpn_name_edit,
            self.vpn_auto_check,
            self.vpn_interface_edit,
            self.direct_interface_edit,
        ):
            widget.setEnabled(enabled)

    def _sync_mode(self) -> None:
        # В режиме «всё через прокси» списки не применяются: активными они
        # обещали бы несуществующий эффект. «Локальные сети» действуют всегда.
        custom = self.mode_combo.selected() == RoutingMode.CUSTOM
        for widget in (*self.lists.values(), self.order_combo, self.ru_direct_check):
            widget.setEnabled(custom)

    def _load(self) -> None:
        profile = self._profile
        bean = profile.bean
        self.name_edit.setText(bean.display_name)
        self.address_label.setText(f"{bean.server_address}:{bean.server_port}")

        vpn = getattr(profile, "vpn_settings", None) or VpnSettings()
        self.vpn_check.setChecked(vpn.enabled)
        self.vpn_name_edit.setText(vpn.connection_name)
        self.vpn_auto_check.setChecked(getattr(vpn, "auto_connect", False))
        self.vpn_interface_edit.setText(getattr(vpn, "interface_name", "") or "")
        self.direct_interface_edit.setText(getattr(vpn, "direct_interface", "") or "")
        self._sync_vpn()

        routing = getattr(profile, "routing_settings", None) or RoutingSettings()
        self.mode_combo.select(routing.mode)
        self.bypass_check.setChecked(routing.bypass_local_networks)
        self.ru_direct_check.setChecked(getattr(routing, "ru_direct", False))
        try:
            order = routing.get_rule_order()
        except AttributeError:
            order = []
        self.order_combo.select(order_key(order))
        for key, edit in self.lists.items():
            edit.setPlainText("\n".join(getattr(routing, f"{key}_list", None) or []))
        self._sync_mode()

    def save(self) -> bool:
        """Записать форму в профиль; ошибка в списке — ничего не меняется."""
        lists: dict[str, list[str]] = {}
        first_error = ""
        for key, edit in self.lists.items():
            try:
                lists[key] = parse_host_list(edit.toPlainText())
                mark_error(edit, None)
            except ValueError as error:
                mark_error(edit, str(error))
                first_error = first_error or str(error)
        self.status.setText(first_error)
        self.status.setVisible(bool(first_error))
        if first_error:
            return False

        profile = self._profile
        name = self.name_edit.text().strip()
        if name:
            profile.bean.name = name

        if getattr(profile, "vpn_settings", None) is None:
            profile.vpn_settings = VpnSettings()
        vpn = profile.vpn_settings
        vpn.enabled = self.vpn_check.isChecked()
        # Безымянное подключение система не найдёт — остаётся прежнее.
        connection_name = self.vpn_name_edit.text().strip()
        if connection_name:
            vpn.connection_name = connection_name
        vpn.auto_connect = self.vpn_auto_check.isChecked()
        vpn.interface_name = self.vpn_interface_edit.text().strip()
        vpn.direct_interface = self.direct_interface_edit.text().strip()

        if getattr(profile, "routing_settings", None) is None:
            profile.routing_settings = RoutingSettings()
        routing = profile.routing_settings
        routing.mode = self.mode_combo.selected()
        routing.bypass_local_networks = self.bypass_check.isChecked()
        routing.ru_direct = self.ru_direct_check.isChecked()
        routing.rule_order = list(ORDER_PRESETS[self.order_combo.selected()])
        for key, values in lists.items():
            setattr(routing, f"{key}_list", values)

        self.routing_saved.emit()
        return True
```

**Step 4: Run to verify it passes** — Expected: 8 passed; `make test-qt` — 83 passed.

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/qt/dialogs/profile_routing.py tests/test_ui_qt_profile_routing.py
git commit -m "feat(qt): окно «VPN и маршруты» профиля"
```

---

### Task 6: Приложение открывает формы; действия над строками

`NOT_YET` уходит. Каждое действие открывает своё окно, а результат передаётся контроллеру. Добавляются действия над строкой с адресатом, по именам `win.*`-действий GTK-окна (`src/ui/window.py`, `_ROW_ACTIONS`). `show_dialog(dialog, parent)` — общий путь показа: из окна настроек форма открывается поверх него, иначе идёт через слот. Обработчики, которые ведут в контроллер, — лямбды: метод берётся в момент действия, как в GTK, и подмена в тестах действует.

**Files:**
- Modify: `src/ui/qt/application.py`
- Modify: `tests/test_ui_qt_application.py` (снимается тест временного тоста)
- Test: `tests/test_ui_qt_actions.py`

**Step 1: Write the failing test** — `tests/test_ui_qt_actions.py`:

```python
"""Действия Qt-приложения открывают формы и передают результат контроллеру."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox

from src.core.context import AppContext
from src.fmt import parse_link
from src.ui.logic.routing_import import ImportRow
from src.ui.qt.application import QtApplication
from src.ui.qt.dialogs.about import AboutDialog
from src.ui.qt.dialogs.group import GroupDialog
from src.ui.qt.dialogs.profile import AddProfileDialog, EditProfileDialog
from src.ui.qt.dialogs.profile_routing import ProfileRoutingDialog
from src.ui.qt.dialogs.routing_import import RoutingImportDialog
from src.ui.qt.dialogs.shortcuts import ShortcutsDialog
from src.ui.qt.dialogs.subscription import SubscriptionDialog
from tests.support.qt import process_events

pytestmark = pytest.mark.qt

LINK = "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба"


@pytest.fixture
def app(qapp, tmp_path):
    context = AppContext(config_dir=tmp_path)
    assert context.config is not None
    app = QtApplication(context, with_tray=False)
    app.activate()
    yield app
    while app.current_dialog is not None:
        app.current_dialog.reject()
        process_events()
    app.window.detach()
    app.window.deleteLater()
    process_events()


def _profile(app, name="Проба", group_id=None):
    return app.controller.add_profile_from_bean(
        parse_link(LINK.replace("Проба", name)), group_id=group_id
    )


def _click(box: QMessageBox, text: str) -> None:
    next(b for b in box.buttons() if b.text() == text).click()
    process_events()


@pytest.mark.parametrize(
    ("action", "kind"),
    [
        ("add-profile", AddProfileDialog),
        ("add-subscription", SubscriptionDialog),
        ("add-group", GroupDialog),
        ("about", AboutDialog),
        ("shortcuts", ShortcutsDialog),
    ],
)
def test_actions_open_their_dialogs(app, action, kind):
    app.actions[action].trigger()

    assert isinstance(app.current_dialog, kind)
    assert app.current_dialog.parent() is app.window


def test_added_profile_reaches_the_store(app):
    app.actions["add-profile"].trigger()
    dialog = app.current_dialog
    dialog.link_edit.setText(LINK)

    dialog.confirm_button.click()
    process_events()

    assert [p.name for p in app.context.profiles.profiles.values()] == ["Проба"]
    assert app.last_toast_for_test == "Профиль добавлен: Проба"
    assert app.current_dialog is None


def test_clipboard_action_prefills_the_link(app):
    QApplication.clipboard().setText(LINK)

    app.actions["add-profile-from-clipboard"].trigger()

    assert app.current_dialog.link_edit.text() == LINK
    assert app.current_dialog.confirm_button.isEnabled()


def test_subscription_link_opens_a_prefilled_form(app, monkeypatch):
    seen = []
    monkeypatch.setattr(app.controller, "add_subscription", lambda n, u: seen.append((n, u)))

    app.controller._shell.open_subscription_form("Провайдер", "https://sub.example.org/s")
    dialog = app.current_dialog
    assert isinstance(dialog, SubscriptionDialog)
    assert dialog.name_edit.text() == "Провайдер"
    dialog.confirm_button.click()

    assert seen == [("Провайдер", "https://sub.example.org/s")]


def test_routing_import_is_a_dialog(app):
    confirmed = []

    app.controller._shell.open_routing_import(
        [ImportRow("Режим", "a → b")], lambda: confirmed.append(1)
    )

    dialog = app.current_dialog
    assert isinstance(dialog, RoutingImportDialog)
    dialog.import_button.click()
    assert confirmed == [1]


def test_edit_profile_saves_through_the_controller(app):
    entry = _profile(app)

    app.activate_action("edit-profile", entry.id)
    dialog = app.current_dialog
    assert isinstance(dialog, EditProfileDialog)
    dialog.name_edit.setText("Другое")
    dialog.confirm_button.click()
    process_events()

    assert app.context.profiles.get_profile(entry.id).name == "Другое"
    group = app.window.model.item(0, 0)
    assert group.child(0, 0).text() == "Другое"


def test_delete_profile_asks_first(app):
    entry = _profile(app)

    app.activate_action("delete-profile", entry.id)
    box = app.current_dialog
    assert box.text() == "«Проба» будет удалён безвозвратно."
    _click(box, "Удалить")

    assert app.context.profiles.get_profile(entry.id) is None


def test_missing_profile_is_reported(app):
    app.activate_action("edit-profile", 999)

    assert app.current_dialog is None
    assert app.last_toast_for_test == "Профиль не найден"


def test_profile_routing_opens(app):
    entry = _profile(app)

    app.activate_action("profile-routing", entry.id)

    assert isinstance(app.current_dialog, ProfileRoutingDialog)


def test_edit_group_picks_the_form_by_kind(app):
    plain = app.controller.add_group("Дом")
    subscription = app.context.profiles.add_group("Подписка", is_subscription=True)

    app.activate_action("edit-group", plain.id)
    assert isinstance(app.current_dialog, GroupDialog)
    app.current_dialog.name_edit.setText("Работа")
    app.current_dialog.confirm_button.click()
    process_events()
    assert app.context.profiles.get_group(plain.id).name == "Работа"

    app.activate_action("edit-group", subscription.id)
    assert isinstance(app.current_dialog, SubscriptionDialog)


def test_delete_group_counts_its_profiles(app):
    group = app.controller.add_group("Дом")
    _profile(app, group_id=group.id)

    app.activate_action("delete-group", group.id)

    assert app.current_dialog.text() == "«Дом» и 1 профилей внутри будут удалены безвозвратно."
    _click(app.current_dialog, "Удалить")
    assert app.context.profiles.get_group(group.id) is None


def test_row_actions_reach_the_controller(app, monkeypatch):
    seen = []
    monkeypatch.setattr(app.controller, "test_latency_for", lambda pid: seen.append(("p", pid)))
    monkeypatch.setattr(
        app.controller, "test_latency_for_group", lambda gid: seen.append(("g", gid))
    )

    app.activate_action("test-profile", 5)
    app.activate_action("test-group", "7")

    assert seen == [("p", 5), ("g", 7)]


def test_provider_links_are_checked_before_opening(app, monkeypatch):
    opened = []
    monkeypatch.setattr("src.ui.qt.application.open_url", opened.append)
    group = app.context.profiles.add_group("Подписка", is_subscription=True)
    group.sub_web_page_url = "javascript:alert(1)"

    app.activate_action("open-subscription-page", group.id)
    assert opened == []
    assert app.last_toast_for_test == "Ссылка недоступна"

    group.sub_support_url = "https://t.me/provider"
    app.activate_action("open-subscription-support", group.id)
    assert opened == ["https://t.me/provider"]


def test_a_second_dialog_waits_for_the_first(app):
    app.actions["about"].trigger()

    app.actions["add-profile"].trigger()

    assert isinstance(app.current_dialog, AboutDialog)
```

и снять тест заглушки фазы 2:

```diff
diff --git a/tests/test_ui_qt_application.py b/tests/test_ui_qt_application.py
index 3b72871..d7610f8 100644
--- a/tests/test_ui_qt_application.py
+++ b/tests/test_ui_qt_application.py
@@ -13,7 +13,7 @@ from src.core.context import AppContext
 from src.fmt import parse_link
 from src.ui.controller import CONFIRM_DELETE, CONFIRM_URL_CHANGE
 from src.ui.logic.profiles_view import SortKey
-from src.ui.qt.application import NOT_YET_TEXT, QtApplication
+from src.ui.qt.application import QtApplication
 from src.ui.qt.models import PING_COLUMN
 from tests.support.qt import process_events, wait_until
 
@@ -165,15 +165,6 @@ def test_unknown_action_is_ignored(made):
     app.activate_action("no-such-action")
 
 
-def test_dialog_actions_say_they_are_not_there_yet(made):
-    app, _service = made
-    app.activate()
-
-    app.actions["settings"].trigger()
-
-    assert app.last_toast_for_test == NOT_YET_TEXT
-
-
 def test_restore_routing_follows_the_backup(made):
     app, _service = made
 
```

**Step 2: Run to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen uv run pytest -m qt tests/test_ui_qt_actions.py -q --no-cov -p no:cacheprovider`
Expected: FAIL. Действия показывают тост вместо окна: `test_actions_open_their_dialogs` падает на `isinstance(None, …)`, а у приложения нет `open_add_subscription` и обработчика `edit-profile`.

**Step 3: Implementation** — применить к `src/ui/qt/application.py`:

```diff
diff --git a/src/ui/qt/application.py b/src/ui/qt/application.py
index be9ef66..99c739f 100644
--- a/src/ui/qt/application.py
+++ b/src/ui/qt/application.py
@@ -15,11 +15,14 @@ from typing import TYPE_CHECKING
 from PySide6.QtCore import Qt, QTimer
 from PySide6.QtGui import QAction, QIcon, QKeySequence
 from PySide6.QtNetwork import QNetworkInformation
-from PySide6.QtWidgets import QApplication, QMessageBox
+from PySide6.QtWidgets import QApplication, QWidget
 
 from src.core.config import get_asset_path
-from src.ui.controller import CONFIRM_URL_CHANGE, AppController, resume_monitoring
-from src.ui.logic.version import app_version
+from src.ui.controller import CONFIRM_DELETE, AppController, resume_monitoring
+from src.ui.logic.version import app_version, core_version
+from src.ui.qt.dialogs.base import clipboard_text, open_url
+from src.ui.qt.dialogs.confirm import build_confirmation
+from src.ui.qt.dialogs.shortcuts import SHORTCUTS
 from src.ui.qt.dispatch import QtLoop
 from src.ui.qt.theme import apply_theme
 from src.ui.qt.window import MainWindow
@@ -29,32 +32,23 @@ if TYPE_CHECKING:
 
 logger = logging.getLogger("tenga.ui.qt.application")
 
-# Сочетания клавиш — те же, что в GTK (`_ACCELS` в src/ui/application.py).
-SHORTCUTS: dict[str, str] = {
-    "add-profile": "Ctrl+N",
-    "add-subscription": "Ctrl+Shift+N",
-    "settings": "Ctrl+,",
-    "refresh-subscriptions": "F5",
-    "quit": "Ctrl+Q",
-    "hide-window": "Ctrl+W",
-    "toggle-connection": "Ctrl+Return",
-    "test-latency": "Ctrl+T",
-    "search": "Ctrl+F",
-}
-
-# Действия, у которых в Qt-интерфейсе ещё нет окна: диалоги приходят в
-# фазе 3 (docs/plans/2026-10-28-windows-qt-frontend-design.md). Имена
-# зарегистрированы, чтобы трей и сочетания не попадали в «неизвестное действие».
-NOT_YET = (
-    "add-profile",
-    "add-profile-from-clipboard",
-    "add-subscription",
-    "add-group",
-    "settings",
-    "about",
-    "shortcuts",
+# Действия над строкой дерева: адресат — id профиля или группы, как у
+# `win.*`-действий GTK-окна (src/ui/window.py).
+ROW_ACTIONS = (
+    "connect-profile",
+    "edit-profile",
+    "delete-profile",
+    "profile-routing",
+    "test-profile",
+    "toggle-group",
+    "test-group",
+    "keep-working",
+    "edit-group",
+    "delete-group",
+    "update-subscription",
+    "open-subscription-page",
+    "open-subscription-support",
 )
-NOT_YET_TEXT = "Раздел появится в следующей сборке"
 
 
 def network_available() -> bool:
@@ -99,6 +93,7 @@ class _QtShell:
     def refresh_pages(self) -> None:
         if (window := self._window()) is not None:
             window.refresh_pages()
+        self._app.refresh_dialog()
 
     def show_connecting(self, profile_name: str) -> None:
         if (window := self._window()) is not None:
@@ -134,33 +129,24 @@ class _QtShell:
         action = self._app.actions.get(name)
         if action is not None:
             action.setEnabled(enabled)
+        self._app.refresh_dialog()
 
     def confirm(self, kind, heading, body, on_confirm, *, confirm_label=None) -> None:
-        if kind == CONFIRM_URL_CHANGE:
-            accept, reject = "Сменить", "Оставить"
-        else:
-            accept, reject = confirm_label or "Удалить", "Отмена"
-        box = QMessageBox(QMessageBox.Icon.Question, heading, body, parent=self._window())
-        # Текст не разметка: адрес подписки приходит от провайдера.
-        box.setTextFormat(Qt.TextFormat.PlainText)
-        accept_button = box.addButton(accept, QMessageBox.ButtonRole.AcceptRole)
-        cancel_button = box.addButton(reject, QMessageBox.ButtonRole.RejectRole)
-        # Enter и Escape не подтверждают: удалить или сменить можно только явно.
-        box.setDefaultButton(cancel_button)
-        box.setEscapeButton(cancel_button)
-
-        def finished(_result: int) -> None:
-            if box.clickedButton() is accept_button:
-                on_confirm()
-
-        box.finished.connect(finished)
-        self._app.present_dialog(box)
+        # Вопрос о смене адреса приходит и при открытых настройках: тогда поверх них.
+        parent = self._app.dialog_parent()
+        box = build_confirmation(
+            kind, heading, body, on_confirm, confirm_label=confirm_label, parent=parent
+        )
+        self._app.show_dialog(box, parent)
 
     def open_subscription_form(self, name: str, url: str) -> None:
-        self.toast(NOT_YET_TEXT)
+        self._app.open_add_subscription(name=name, url=url)
 
     def open_routing_import(self, rows, on_confirm) -> None:
-        self.toast(NOT_YET_TEXT)
+        from src.ui.qt.dialogs.routing_import import RoutingImportDialog
+
+        parent = self._app.dialog_parent()
+        self._app.show_dialog(RoutingImportDialog(rows, on_confirm, parent), parent)
 
 
 class QtApplication:
@@ -211,17 +197,21 @@ class QtApplication:
             "connect": lambda: self.controller.connect_selected(),
             "disconnect": lambda: self.controller.disconnect_proxy(),
             "toggle-connection": lambda: self.controller.toggle_connection(),
+            "add-profile": self.open_add_profile,
+            "add-profile-from-clipboard": self.add_profile_from_clipboard,
+            "add-subscription": self.open_add_subscription,
+            "add-group": self.open_add_group,
             "refresh-subscriptions": lambda: self.controller.refresh_subscriptions(),
             "test-latency": lambda: self.controller.test_latency(),
             "search": self._focus_search,
+            "settings": self.open_settings,
+            "about": self.open_about,
+            "shortcuts": self.open_shortcuts,
             "quit": self.quit,
             "hide-window": self._hide_window,
             "activate-window": self.activate,
             "restore-routing": lambda: self.controller.restore_routing(),
         }
-        for name in NOT_YET:
-            handlers[name] = lambda: self.controller.toast(NOT_YET_TEXT)
-
         for name, handler in handlers.items():
             action = QAction(name, self.qt)
             if name in SHORTCUTS:
@@ -229,10 +219,29 @@ class QtApplication:
             action.triggered.connect(lambda _checked=False, fn=handler: fn())
             self.actions[name] = action
             self._handlers[name] = lambda _target, fn=handler: fn()
-        # Профиль трей адресует числом, как строчные действия окна.
-        self._handlers["connect-profile"] = lambda target: self.controller.connect_profile(
-            int(target)
-        )
+
+        row_handlers: dict[str, Callable[[int], None]] = {
+            "connect-profile": lambda target: self.controller.connect_profile(target),
+            "edit-profile": self.edit_profile,
+            "delete-profile": self.delete_profile,
+            "profile-routing": self.profile_routing,
+            "test-profile": lambda target: self.controller.test_latency_for(target),
+            "toggle-group": self._toggle_group,
+            "test-group": lambda target: self.controller.test_latency_for_group(target),
+            "keep-working": lambda target: self.controller.keep_working_profiles(target),
+            "edit-group": self.edit_group,
+            "delete-group": self.delete_group,
+            "update-subscription": lambda target: self.controller.update_subscription(target),
+            "open-subscription-page": lambda gid: self.open_subscription_link(
+                gid, "sub_web_page_url"
+            ),
+            "open-subscription-support": lambda gid: self.open_subscription_link(
+                gid, "sub_support_url"
+            ),
+        }
+        # Трей и меню строк адресуют профиль или группу числом.
+        for name in ROW_ACTIONS:
+            self._handlers[name] = lambda target, fn=row_handlers[name]: fn(int(target))
         self.controller.sync_restore_routing()
 
     def activate_action(self, name: str, target=None) -> None:
@@ -271,6 +280,173 @@ class QtApplication:
     def current_dialog(self):
         return self._dialog
 
+    def dialog_parent(self) -> QWidget | None:
+        """Над чем открывать вопрос: над окном настроек, если оно открыто."""
+        return self._dialog if self._dialog is not None else self.window
+
+    def show_dialog(self, dialog, parent: QWidget | None = None) -> bool:
+        """Показать диалог: из окна настроек — поверх него, иначе через слот.
+
+        Формы, открытые из настроек (правка подписки, очистка журналов),
+        принадлежат настройкам и слот не занимают; всё остальное — по
+        одному, чтобы трей и сочетания не громоздили окна друг на друга.
+        """
+        if parent is not None and parent is self._dialog:
+            dialog.setParent(parent, dialog.windowFlags())
+            dialog.open()
+            return True
+        if dialog.parent() is None and self.window is not None:
+            dialog.setParent(self.window, dialog.windowFlags())
+        return self.present_dialog(dialog)
+
+    def refresh_dialog(self) -> None:
+        refresh = getattr(self._dialog, "refresh", None)
+        if refresh is not None:
+            refresh()
+
+    # Формы. Результат уходит в контроллер теми же вызовами, что из GTK.
+
+    def open_add_profile(self, link: str = "") -> None:
+        from src.ui.qt.dialogs.profile import AddProfileDialog
+
+        dialog = AddProfileDialog(link=link)
+        dialog.profile_ready.connect(self.controller.add_profile_from_bean)
+        self.show_dialog(dialog)
+
+    def add_profile_from_clipboard(self) -> None:
+        """Форма добавления со ссылкой из буфера обмена."""
+        self.open_add_profile(clipboard_text())
+
+    def open_add_subscription(
+        self, *, name: str = "", url: str = "", parent: QWidget | None = None
+    ) -> None:
+        from src.ui.qt.dialogs.subscription import SubscriptionDialog
+
+        dialog = SubscriptionDialog()
+        dialog.name_edit.setText(name)
+        dialog.url_edit.setText(url)
+        dialog.subscription_ready.connect(self.controller.add_subscription)
+        self.show_dialog(dialog, parent)
+
+    def open_add_group(self) -> None:
+        from src.ui.qt.dialogs.group import GroupDialog
+
+        dialog = GroupDialog()
+        dialog.group_ready.connect(self.controller.add_group)
+        self.show_dialog(dialog)
+
+    def open_settings(self) -> None:
+        from src.ui.qt.dialogs.settings import SettingsDialog
+
+        dialog = SettingsDialog(self, dispatch=self.loop.dispatch)
+        # Кнопки «Сохранить» нет: правки уходят в контроллер по мере ввода.
+        dialog.settings_saved.connect(self.controller.apply_settings)
+        self.show_dialog(dialog)
+
+    def open_about(self) -> None:
+        from src.ui.qt.dialogs.about import AboutDialog
+
+        core = core_version(getattr(self.context, "xray_manager", None))
+        self.show_dialog(AboutDialog(app_version(), core))
+
+    def open_shortcuts(self) -> None:
+        from src.ui.qt.dialogs.shortcuts import ShortcutsDialog
+
+        self.show_dialog(ShortcutsDialog())
+
+    # Действия строк дерева и списка подписок.
+
+    def _profile_or_toast(self, profile_id: int):
+        profile = self.context.profiles.get_profile(profile_id)
+        if profile is None:
+            self.controller.toast("Профиль не найден")
+        return profile
+
+    def edit_profile(self, profile_id: int) -> None:
+        from src.ui.qt.dialogs.profile import EditProfileDialog
+
+        if (profile := self._profile_or_toast(profile_id)) is None:
+            return
+        dialog = EditProfileDialog(profile)
+        dialog.profile_saved.connect(self.controller.save_profiles)
+        self.show_dialog(dialog)
+
+    def delete_profile(self, profile_id: int) -> None:
+        if (profile := self._profile_or_toast(profile_id)) is None:
+            return
+        self.show_dialog(
+            build_confirmation(
+                CONFIRM_DELETE,
+                "Удалить профиль?",
+                f"«{profile.name}» будет удалён безвозвратно.",
+                lambda: self.controller.delete_profile(profile_id),
+                parent=self.window,
+            )
+        )
+
+    def profile_routing(self, profile_id: int) -> None:
+        from src.ui.qt.dialogs.profile_routing import ProfileRoutingDialog
+
+        if (profile := self._profile_or_toast(profile_id)) is None:
+            return
+        dialog = ProfileRoutingDialog(profile)
+        dialog.routing_saved.connect(self.controller.save_profiles)
+        self.show_dialog(dialog)
+
+    def edit_group(self, group_id: int, parent: QWidget | None = None) -> None:
+        group = self.context.profiles.get_group(group_id)
+        if group is None:
+            self.controller.toast("Группа не найдена")
+            return
+        if group.is_subscription:
+            from src.ui.qt.dialogs.subscription import SubscriptionDialog
+
+            dialog = SubscriptionDialog(group)
+            dialog.subscription_ready.connect(
+                lambda name, url: self.controller.update_group(group_id, name=name, url=url)
+            )
+        else:
+            from src.ui.qt.dialogs.group import GroupDialog
+
+            dialog = GroupDialog(group)
+            dialog.group_ready.connect(
+                lambda name: self.controller.update_group(group_id, name=name)
+            )
+        self.show_dialog(dialog, parent)
+
+    def delete_group(self, group_id: int, parent: QWidget | None = None) -> None:
+        group = self.context.profiles.get_group(group_id)
+        if group is None:
+            self.controller.toast("Группа не найдена")
+            return
+        count = len(self.context.profiles.get_profiles_in_group(group_id))
+        self.show_dialog(
+            build_confirmation(
+                CONFIRM_DELETE,
+                "Удалить группу?",
+                f"«{group.name}» и {count} профилей внутри будут удалены безвозвратно.",
+                lambda: self.controller.delete_group(group_id),
+                parent=parent or self.window,
+            ),
+            parent,
+        )
+
+    def open_subscription_link(self, group_id: int, field: str) -> None:
+        """Ссылка провайдера; проверяется заново: файл профилей правят и вручную."""
+        from src.sub.metadata import is_safe_support_url, is_safe_web_page_url
+
+        is_safe = is_safe_web_page_url if field == "sub_web_page_url" else is_safe_support_url
+        group = self.context.profiles.get_group(group_id)
+        url = getattr(group, field, "") if group is not None else ""
+        if not url or not is_safe(url):
+            self.controller.toast("Ссылка недоступна")
+            return
+        open_url(url)
+
+    def _toggle_group(self, group_id: int) -> None:
+        if self.window is not None:
+            self.window.toggle_group(group_id)
+
     def _hide_window(self) -> None:
         if self.window is not None:
             self.window.hide()
```

Ключевые решения:
- `dialog_parent()` — окно настроек, если оно открыто, иначе главное окно. Через него оболочка показывает вопрос о смене адреса подписки и импорт маршрутизации: контроллер может спросить, пока открыты настройки.
- Второе окно из трея или по сочетанию при уже открытом диалоге не показывается (`present_dialog` → False), как в GTK.
- `open_subscription_link` проверяет ссылку заново перед открытием: файл профилей можно править в обход приложения.

**Step 4: Run to verify it passes** — Expected: 18 passed; `make test-qt` — 100 passed.

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/qt/application.py tests/test_ui_qt_actions.py tests/test_ui_qt_application.py
git commit -m "feat(qt): действия приложения открывают формы, действия над строками"
```

---

### Task 7: Окно настроек

Разделы слева (`QListWidget`), страницы справа (`QStackedWidget`), как в «Параметрах» Windows. Разделы с полными названиями: Общие, Мониторинг, DNS, Обход блокировок, Подписки, О программе. Поля, проверка и сохранение — те же, что у GTK-`SettingsDialog`; плюс флажок «Сворачивать в трей при закрытии окна». Страницы «Подписки» и «О программе» со своим поведением — в `settings_pages.py`.

**Files:**
- Create: `src/ui/qt/dialogs/settings.py`, `src/ui/qt/dialogs/settings_pages.py`
- Test: `tests/test_ui_qt_settings.py`

**Step 1: Write the failing test** — `tests/test_ui_qt_settings.py`:

```python
"""Qt-окно настроек: поля, проверка, автосохранение, подписки, «О программе»."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

from src.core.context import AppContext
from src.db.config import DnsProvider, ProxyMode, RoutingSettings
from src.db.data_store import LEGACY_USER_AGENT
from src.ui.controller import CONFIRM_URL_CHANGE
from src.ui.qt.application import QtApplication
from src.ui.qt.dialogs.settings import SECTIONS, SettingsDialog
from src.ui.qt.dialogs.subscription import SubscriptionDialog
from tests.support.qt import process_events, wait_until

pytestmark = pytest.mark.qt


@pytest.fixture
def app(qapp, tmp_path):
    context = AppContext(config_dir=tmp_path)
    assert context.config is not None
    app = QtApplication(context, with_tray=False)
    yield app
    while app.current_dialog is not None:
        app.current_dialog.reject()
        process_events()


def _open(app) -> SettingsDialog:
    app.open_settings()
    dialog = app.current_dialog
    assert isinstance(dialog, SettingsDialog)
    return dialog


def _saved(app) -> dict:
    return json.loads((app.context.config_dir / "settings.json").read_text(encoding="utf-8"))


def test_settings_action_opens_the_settings_window(app):
    app.actions["settings"].trigger()

    assert isinstance(app.current_dialog, SettingsDialog)


def test_url_change_question_opens_over_settings(app):
    app.actions["settings"].trigger()
    settings = app.current_dialog
    confirmed = []

    app.controller._shell.confirm(
        CONFIRM_URL_CHANGE, "Сменить?", "https://x", lambda: confirmed.append(1)
    )

    box = settings.findChildren(QMessageBox)[-1]
    assert app.current_dialog is settings
    next(b for b in box.buttons() if b.text() == "Сменить").click()
    assert confirmed == [1]


# --- поля и сохранение ---


def test_sections_switch_pages(app):
    dialog = _open(app)

    assert [dialog.sections.item(i).text() for i in range(dialog.sections.count())] == list(
        SECTIONS
    )
    dialog.show_section("DNS")
    assert dialog.pages.currentIndex() == 2


def test_fields_come_from_the_config(app):
    config = app.context.config
    config.inbound_address = "127.0.0.2"
    config.proxy_mode = ProxyMode.SYSTEM_PROXY
    config.user_agent = LEGACY_USER_AGENT
    config.close_to_tray = False

    dialog = _open(app)

    assert dialog.address_edit.text() == "127.0.0.2"
    assert dialog.mode_combo.selected() == ProxyMode.SYSTEM_PROXY
    assert not dialog.tun_name_edit.isEnabled()
    # Старое значение по умолчанию показывается как «не задано».
    assert dialog.user_agent_edit.text() == ""
    assert not dialog.close_to_tray_check.isChecked()


def test_save_writes_the_config_and_reaches_the_controller(app):
    dialog = _open(app)
    dialog.dns_combo.select(DnsProvider.ALL[-1])
    dialog.interval_spin.setValue(30)
    dialog.close_to_tray_check.setChecked(False)

    assert dialog.save()

    config = app.context.config
    assert config.dns.provider == DnsProvider.ALL[-1]
    assert config.monitoring.check_interval_seconds == 30
    assert config.close_to_tray is False
    assert _saved(app)["monitoring"]["check_interval_seconds"] == 30


def test_invalid_field_is_marked_and_nothing_changes(app):
    dialog = _open(app)
    dialog.address_edit.setText("не адрес")
    dialog.interval_spin.setValue(42)

    assert not dialog.save()

    assert dialog.address_edit.property("error") is True
    assert dialog.address_edit.toolTip() == "Введите IP-адрес или localhost"
    assert dialog.status.text().startswith("Исправьте настройки: ")
    assert app.context.config.monitoring.check_interval_seconds != 42

    dialog.address_edit.setText("127.0.0.1")
    assert dialog.save()
    assert dialog.address_edit.property("error") is False
    assert dialog.status.isHidden()


def test_edits_autosave_and_closing_flushes(app):
    dialog = _open(app)

    dialog.interval_spin.setValue(25)
    assert dialog.autosave.pending
    dialog.reject()

    assert app.context.config.monitoring.check_interval_seconds == 25
    assert _saved(app)["monitoring"]["check_interval_seconds"] == 25


def test_monitoring_switch_dims_failover(app):
    dialog = _open(app)

    dialog.monitoring_check.setChecked(False)
    assert not dialog.interval_spin.isEnabled()
    assert not dialog.failover_check.isEnabled()
    dialog.monitoring_check.setChecked(True)
    dialog.failover_check.setChecked(False)
    assert not dialog.failover_threshold_spin.isEnabled()


def test_fragment_fields_follow_the_switch(app):
    dialog = _open(app)

    dialog.fragment_check.setChecked(False)
    assert not dialog.fragment_length_edit.isEnabled()
    dialog.fragment_check.setChecked(True)
    assert dialog.fragment_length_edit.isEnabled()


def test_device_info_creates_the_hwid(app):
    dialog = _open(app)

    dialog.device_info_check.setChecked(True)
    dialog.save()

    assert app.context.config.sub_hwid


def test_missing_tun_rights_are_shown(app, monkeypatch):
    monkeypatch.setattr("src.sys.tun_access.tun_problems", lambda _xray: ["нет правила sudoers"])
    app.context.config.proxy_mode = ProxyMode.TUN

    dialog = _open(app)

    wait_until(lambda: not dialog.tun_access_label.isHidden())
    assert "нет правила sudoers" in dialog.tun_access_label.text()
    dialog.mode_combo.select(ProxyMode.SYSTEM_PROXY)
    assert dialog.tun_access_label.isHidden()


def test_theme_applies_at_once(app, monkeypatch):
    applied = []
    monkeypatch.setattr("src.ui.qt.dialogs.settings.apply_theme", applied.append)
    dialog = _open(app)

    dialog.theme_combo.select("dark")

    assert applied == ["dark"]
    dialog.save()
    assert app.context.config.theme == "dark"


# --- подписки ---


def _subscription(app, name="Провайдер", **fields):
    group = app.context.profiles.add_group(name, is_subscription=True)
    group.subscription_url = "https://sub.example.org/s"
    for key, value in fields.items():
        setattr(group, key, value)
    return group


def test_subscriptions_are_listed_with_details(app):
    _subscription(
        app,
        sub_user_info="upload=0; download=1073741824; total=2147483648; expire=1000000000",
    )
    app.context.profiles.add_group("Обычная")

    dialog = _open(app)
    tree = dialog.subscriptions.tree

    assert tree.topLevelItemCount() == 1
    item = tree.topLevelItem(0)
    assert item.text(0) == "Провайдер"
    assert "истекла" in item.text(3)
    assert item.toolTip(0) == "https://sub.example.org/s"


def test_empty_list_shows_a_hint(app):
    dialog = _open(app)

    assert dialog.subscriptions.tree.isHidden()
    assert not dialog.subscriptions.empty_label.isHidden()


def test_buttons_follow_the_selection_and_menu_lists_provider_links(app):
    _subscription(app, sub_web_page_url="https://provider.example/account", sub_announce="Тех")
    dialog = _open(app)
    page = dialog.subscriptions
    assert not page.edit_button.isEnabled()

    page.tree.setCurrentItem(page.tree.topLevelItem(0))

    assert page.edit_button.isEnabled() and page.more_button.isEnabled()
    assert page.menu_labels() == [
        "Обновить",
        "Изменить…",
        "Страница подписки",
        "Объявление провайдера",
        "Удалить",
    ]


def test_update_goes_to_the_controller(app, monkeypatch):
    group = _subscription(app)
    seen = []
    monkeypatch.setattr(app.controller, "update_subscription", seen.append)
    dialog = _open(app)
    dialog.subscriptions.tree.setCurrentItem(dialog.subscriptions.tree.topLevelItem(0))

    dialog.subscriptions.update_button.click()

    assert seen == [group.id]


def test_edit_opens_over_settings_and_refreshes_the_list(app):
    group = _subscription(app)
    dialog = _open(app)
    page = dialog.subscriptions
    page.tree.setCurrentItem(page.tree.topLevelItem(0))

    page.edit_button.click()

    form = next(w for w in dialog.findChildren(SubscriptionDialog))
    assert app.current_dialog is dialog  # слот занят настройками, форма поверх них
    form.name_edit.setText("Новое имя")
    form.confirm_button.click()
    process_events()
    assert group.name == "Новое имя"
    assert page.tree.topLevelItem(0).text(0) == "Новое имя"


def test_delete_asks_over_settings(app):
    group = _subscription(app)
    dialog = _open(app)
    page = dialog.subscriptions
    page.tree.setCurrentItem(page.tree.topLevelItem(0))

    page.delete_button.click()

    box = dialog.findChildren(QMessageBox)[-1]
    next(b for b in box.buttons() if b.text() == "Удалить").click()
    process_events()
    assert app.context.profiles.get_group(group.id) is None
    assert page.tree.topLevelItemCount() == 0


def test_add_opens_the_subscription_form_over_settings(app):
    dialog = _open(app)

    dialog.subscriptions.add_button.click()

    assert dialog.findChildren(SubscriptionDialog)


# --- о программе ---


def test_core_update_check_updates_the_row(app):
    from src.core.core_update import KnownReleases

    dialog = _open(app)
    about = dialog.about
    about.fetch_releases = lambda: KnownReleases(stable="26.3.27", prerelease="26.9.30")

    about.check_core_update()
    about.core_update_thread.join(5)
    wait_until(lambda: about.core_update_button.isEnabled())

    assert app.context.config.core_update_checked_at > 0
    assert about.core_update_label.text() != "Проверяю…"


def test_failed_core_check_is_reported(app):
    def offline():
        raise OSError("нет сети")

    dialog = _open(app)
    about = dialog.about
    about.fetch_releases = offline

    about.check_core_update()
    about.core_update_thread.join(5)
    wait_until(lambda: about.core_update_button.isEnabled())

    assert about.core_update_label.text() == "Не удалось проверить обновления"


def test_app_update_check_without_releases(app):
    dialog = _open(app)
    about = dialog.about
    about.fetch_app_releases = list

    about.check_app_update()
    about.app_update_thread.join(5)
    wait_until(lambda: about.app_check_button.isEnabled())

    assert about.app_update_label.text() == "Новых версий нет"


def test_restore_routing_row_follows_the_backup(app):
    dialog = _open(app)
    about = dialog.about
    assert not about._maintenance.isRowVisible(about.restore_routing_row)

    app.context.config.routing_backup = RoutingSettings()
    app.controller.sync_restore_routing()

    assert about._maintenance.isRowVisible(about.restore_routing_row)


def test_clear_logs_asks_first(app, monkeypatch):
    cleared = []
    monkeypatch.setattr(
        app.context.log_manager, "clear_all_logs", lambda: cleared.append(1) or (3, 0)
    )
    dialog = _open(app)
    dialog.about._on_clear_logs()

    box = dialog.findChildren(QMessageBox)[-1]
    next(b for b in box.buttons() if b.text() == "Очистить").click()

    wait_until(lambda: dialog.about.clear_logs_label.text() == "Очищено файлов: 3")
    assert cleared == [1]
```

**Step 2: Run to verify it fails** — `ModuleNotFoundError: No module named 'src.ui.qt.dialogs.settings'`.

**Step 3: Implementation**

`src/ui/qt/dialogs/settings.py`:

```python
"""Окно настроек: разделы слева, страница справа, как в «Параметрах» Windows.

Кнопки «Сохранить» нет, как и в GTK: правки сохраняются через полсекунды
после последней и при закрытии окна. Проверка — `validate_settings`, общая
с GTK; поле с ошибкой подсвечивается, настройки не меняются, пока ошибка
не исправлена.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from src.db.config import DnsProvider, ProxyMode, TlsFragmentSettings
from src.db.data_store import DEFAULT_USER_AGENT, LEGACY_USER_AGENT
from src.sub.device import ensure_hwid
from src.sys import tun_access
from src.ui.logic.appearance import THEME_LABELS, THEMES, normalize_theme
from src.ui.logic.async_utils import run_in_background
from src.ui.logic.settings_form import (
    DEFAULT_LOG_LEVEL,
    DEFAULT_TUN_NAME,
    LOG_LEVELS,
    validate_settings,
)
from src.ui.qt.dialogs.base import FORM_STYLE, Debounce, KeyedCombo, mark_error, watch
from src.ui.qt.theme import apply_theme

if TYPE_CHECKING:
    from src.ui.qt.dialogs.settings_pages import AboutPage, SubscriptionsPage

SECTIONS = ("Общие", "Мониторинг", "DNS", "Обход блокировок", "Подписки", "О программе")

# Поле проверки (`validate_settings`) → атрибут виджета.
ERROR_FIELDS = {
    "address": "address_edit",
    "tun_name": "tun_name_edit",
    "dns_url": "dns_url_edit",
    "dns_additional": "dns_additional_edit",
    "fragment_packets": "fragment_packets_edit",
    "fragment_length": "fragment_length_edit",
    "fragment_delay": "fragment_delay_edit",
    "sub_exceptions": "sub_exceptions_edit",
}


def spin(low: int, high: int, suffix: str = "") -> QSpinBox:
    box = QSpinBox()
    box.setRange(low, high)
    box.setSuffix(suffix)
    return box


def check(text: str, hint: str = "") -> QCheckBox:
    box = QCheckBox(text)
    box.setToolTip(hint)
    return box


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setEnabled(False)  # приглушённый цвет системной палитры
    return label


def page(*groups: QWidget) -> QScrollArea:
    """Страница раздела: группы сверху вниз, прокрутка при нехватке места."""
    body = QWidget()
    column = QVBoxLayout(body)
    for group in groups:
        column.addWidget(group)
    column.addStretch(1)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)
    scroll.setWidget(body)
    return scroll


class SettingsDialog(QDialog):
    settings_saved = Signal()

    def __init__(
        self,
        app,
        *,
        dispatch: Callable[..., object],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setModal(True)
        self.resize(760, 560)
        self.setStyleSheet(FORM_STYLE)
        self._app = app
        self._context = app.context
        self._config = app.context.config
        self._dispatch = dispatch
        self.validation_errors: dict[str, str] = {}
        # None — проверка прав для TUN ещё не запускалась.
        self._tun_problems: list[str] | None = None
        self.tun_access_thread = None

        from src.ui.qt.dialogs.settings_pages import AboutPage, SubscriptionsPage

        self.subscriptions: SubscriptionsPage = SubscriptionsPage(self)
        self.about: AboutPage = AboutPage(self)

        self.sections = QListWidget()
        self.sections.addItems(list(SECTIONS))
        self.sections.setFixedWidth(180)
        self.pages = QStackedWidget()
        for widget in (
            self._general_page(),
            self._monitoring_page(),
            self._dns_page(),
            self._bypass_page(),
            page(self.subscriptions, self._request_group()),
            page(self.about),
        ):
            self.pages.addWidget(widget)
        self.sections.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sections.setCurrentRow(0)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setProperty("error", True)
        self.status.hide()
        buttons = QDialogButtonBox()
        close = buttons.addButton("Закрыть", QDialogButtonBox.ButtonRole.RejectRole)
        close.setDefault(True)
        buttons.rejected.connect(self.reject)

        body = QHBoxLayout()
        body.addWidget(self.sections)
        body.addWidget(self.pages, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(self.status)
        layout.addWidget(buttons)

        self._load()
        self.autosave = Debounce(self.save, parent=self)
        watch(self._fields(), self.autosave.queue)
        self.finished.connect(lambda _result: self.autosave.flush())

    # --- страницы ---

    def _general_page(self) -> QWidget:
        inbound = QGroupBox("Входящее соединение")
        form = QFormLayout(inbound)
        form.addRow(hint("Локальные порты SOCKS и HTTP"))
        self.address_edit = QLineEdit()
        form.addRow("Адрес", self.address_edit)
        self.port_spin = spin(1024, 65534)
        self.port_spin.setToolTip("HTTP занимает следующий порт")
        form.addRow("Порт SOCKS", self.port_spin)

        runtime = QGroupBox("Режим работы")
        form = QFormLayout(runtime)
        self.mode_combo = KeyedCombo(ProxyMode.ALL, ProxyMode.LABELS)
        self.mode_combo.currentIndexChanged.connect(self._sync_mode)
        form.addRow("Режим", self.mode_combo)
        self.tun_name_edit = QLineEdit()
        form.addRow("Имя интерфейса TUN", self.tun_name_edit)
        self.tun_mtu_spin = spin(576, 9000)
        form.addRow("MTU", self.tun_mtu_spin)
        self.tun_access_label = QLabel()
        self.tun_access_label.setWordWrap(True)
        self.tun_access_label.setProperty("error", True)
        # Подсказка с командой для исправления: её копируют в терминал.
        self.tun_access_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.tun_access_label.hide()
        form.addRow(self.tun_access_label)

        window = QGroupBox("Окно")
        form = QFormLayout(window)
        self.theme_combo = KeyedCombo(THEMES, THEME_LABELS)
        # Тема меняется сразу, чтобы выбор было видно; в настройки попадает
        # вместе с остальными полями.
        self.theme_combo.currentIndexChanged.connect(
            lambda _index: apply_theme(self.theme_combo.selected())
        )
        form.addRow("Тема", self.theme_combo)
        self.close_to_tray_check = check(
            "Сворачивать в трей при закрытии окна",
            "Без трея закрытие окна всегда завершает приложение",
        )
        form.addRow(self.close_to_tray_check)

        logs = QGroupBox("Журнал")
        form = QFormLayout(logs)
        self.log_level_combo = KeyedCombo(LOG_LEVELS, {level: level for level in LOG_LEVELS})
        form.addRow("Уровень подробности", self.log_level_combo)
        return page(inbound, runtime, window, logs)

    def _monitoring_page(self) -> QWidget:
        monitoring = QGroupBox("Проверка соединения")
        form = QFormLayout(monitoring)
        form.addRow(hint("Периодический опрос прокси и VPN"))
        self.monitoring_check = check("Включить мониторинг")
        self.monitoring_check.toggled.connect(self._sync_monitoring)
        form.addRow(self.monitoring_check)
        self.interval_spin = spin(5, 60, " с")
        self.interval_spin.setToolTip("Секунд между проверками")
        form.addRow("Интервал", self.interval_spin)

        failover = QGroupBox("Автопереключение")
        form = QFormLayout(failover)
        form.addRow(
            hint("Если сервер перестал отвечать, подключается другой профиль той же группы")
        )
        self.failover_check = check("Переключаться автоматически")
        self.failover_check.toggled.connect(self._sync_monitoring)
        form.addRow(self.failover_check)
        self.failover_threshold_spin = spin(1, 10)
        self.failover_threshold_spin.setToolTip("Неудачных проверок подряд")
        form.addRow("Порог", self.failover_threshold_spin)
        return page(monitoring, failover)

    def _dns_page(self) -> QWidget:
        provider = QGroupBox("Провайдер")
        form = QFormLayout(provider)
        self.dns_combo = KeyedCombo(DnsProvider.ALL, DnsProvider.LABELS)
        form.addRow("DNS-сервер", self.dns_combo)

        custom = QGroupBox("Свой адрес")
        form = QFormLayout(custom)
        form.addRow(
            hint(
                "Непустое поле перекрывает выбранного провайдера. "
                "Примеры: 8.8.8.8, https://dns.google/dns-query"
            )
        )
        self.dns_url_edit = QLineEdit()
        form.addRow("Адрес DNS", self.dns_url_edit)
        self.dns_additional_edit = QLineEdit()
        form.addRow("Дополнительный DNS", self.dns_additional_edit)

        options = QGroupBox("Опции")
        form = QFormLayout(options)
        self.dns_proxy_check = check(
            "Запросы через прокси", "Помогает обойти блокировки на уровне DNS"
        )
        form.addRow(self.dns_proxy_check)
        self.dns_intercept_check = check(
            "Перехватывать DNS приложений",
            "Режим TUN: запросы приложений обрабатывает ядро — "
            "действуют списки маршрутизации и блокировка",
        )
        form.addRow(self.dns_intercept_check)
        return page(provider, custom, options)

    def _bypass_page(self) -> QWidget:
        fragment = QGroupBox("Фрагментация TLS")
        form = QFormLayout(fragment)
        form.addRow(
            hint(
                "Делит начало TLS-соединения на части, чтобы фильтр не разобрал имя "
                "сервера. Действует на профили с TLS и Reality. Вступает в силу после "
                "переподключения."
            )
        )
        self.fragment_check = check("Включить фрагментацию")
        self.fragment_check.toggled.connect(self._sync_fragment)
        form.addRow(self.fragment_check)
        self.fragment_packets_edit = QLineEdit()
        self.fragment_packets_edit.setPlaceholderText("tlshello или номера, 1-3")
        form.addRow("Пакеты", self.fragment_packets_edit)
        self.fragment_length_edit = QLineEdit()
        self.fragment_length_edit.setPlaceholderText("100-200")
        form.addRow("Размер фрагмента, байт", self.fragment_length_edit)
        self.fragment_delay_edit = QLineEdit()
        self.fragment_delay_edit.setPlaceholderText("10-20")
        form.addRow("Пауза между фрагментами, мс", self.fragment_delay_edit)

        mux = QGroupBox("Мультиплексирование")
        form = QFormLayout(mux)
        self.mux_check = check(
            "Включить mux",
            "Несколько потоков в одном соединении. Только VLESS и Trojan, кроме XHTTP и Vision",
        )
        form.addRow(self.mux_check)
        return page(fragment, mux)

    def _request_group(self) -> QWidget:
        request = QGroupBox("Запрос к провайдеру")
        form = QFormLayout(request)
        form.addRow(
            hint(
                f"Пустое поле — {DEFAULT_USER_AGENT}: так представляется большинство "
                "клиентов, и провайдеры отдают ему обычный список серверов."
            )
        )
        self.user_agent_edit = QLineEdit()
        self.user_agent_edit.setPlaceholderText(DEFAULT_USER_AGENT)
        form.addRow("User-Agent", self.user_agent_edit)
        self.device_info_check = check(
            "Отправлять данные устройства",
            "Идентификатор, система и модель. Нужны провайдерам, которые считают лимит устройств",
        )
        form.addRow(self.device_info_check)
        self.sub_exceptions_edit = QLineEdit()
        self.sub_exceptions_edit.setToolTip("Через пробел")
        form.addRow("Разрешённые HTTP/LAN URL", self.sub_exceptions_edit)
        self.sub_insecure_check = check(
            "Не проверять TLS-сертификат подписок",
            "Отдельное исключение; не разрешает доступ к HTTP или локальной сети",
        )
        form.addRow(self.sub_insecure_check)
        return request

    def _fields(self) -> list[QWidget]:
        return [
            self.address_edit,
            self.port_spin,
            self.mode_combo,
            self.tun_name_edit,
            self.tun_mtu_spin,
            self.theme_combo,
            self.close_to_tray_check,
            self.log_level_combo,
            self.monitoring_check,
            self.interval_spin,
            self.failover_check,
            self.failover_threshold_spin,
            self.dns_combo,
            self.dns_url_edit,
            self.dns_additional_edit,
            self.dns_proxy_check,
            self.dns_intercept_check,
            self.fragment_check,
            self.fragment_packets_edit,
            self.fragment_length_edit,
            self.fragment_delay_edit,
            self.mux_check,
            self.user_agent_edit,
            self.device_info_check,
            self.sub_exceptions_edit,
            self.sub_insecure_check,
            *self.about.fields(),
        ]

    # --- состояние ---

    def run(self, fn, on_done=None, on_error=None, *, name: str):
        """Фоновая задача; ответ доставляется, только пока окно живо."""

        def alive(callback):
            if callback is None:
                return None
            return lambda value: callback(value) if isValid(self) else None

        return run_in_background(
            fn, alive(on_done), alive(on_error), dispatch=self._dispatch, name=name
        )

    def _sync_mode(self) -> None:
        tun = self.mode_combo.selected() == ProxyMode.TUN
        self.tun_name_edit.setEnabled(tun)
        self.tun_mtu_spin.setEnabled(tun)
        if tun and self._tun_problems is None:
            self._check_tun_access()
        self._sync_tun_access()

    def _check_tun_access(self) -> None:
        # sudo и служба отвечают не мгновенно: открытие окна ждать не должно.
        from src.core.config import find_xray_binary

        self._tun_problems = []
        self.tun_access_thread = self.run(
            lambda: tun_access.tun_problems(find_xray_binary()),
            self._on_tun_access_checked,
            name="tenga-tun-access",
        )

    def _on_tun_access_checked(self, problems: list[str]) -> None:
        self._tun_problems = list(problems)
        self._sync_tun_access()

    def _sync_tun_access(self) -> None:
        problems = self._tun_problems or []
        self.tun_access_label.setText("TUN не заработает:\n" + "\n".join(problems))
        self.tun_access_label.setVisible(
            self.mode_combo.selected() == ProxyMode.TUN and bool(problems)
        )

    def _sync_monitoring(self) -> None:
        monitoring = self.monitoring_check.isChecked()
        self.interval_spin.setEnabled(monitoring)
        # Без мониторинга проверок нет — переключаться не по чему.
        self.failover_check.setEnabled(monitoring)
        self.failover_threshold_spin.setEnabled(monitoring and self.failover_check.isChecked())

    def _sync_fragment(self) -> None:
        active = self.fragment_check.isChecked()
        for edit in (
            self.fragment_packets_edit,
            self.fragment_length_edit,
            self.fragment_delay_edit,
        ):
            edit.setEnabled(active)

    def _load(self) -> None:
        config = self._config
        self.address_edit.setText(config.inbound_address)
        self.port_spin.setValue(int(config.inbound_socks_port))
        self.mode_combo.select(getattr(config, "proxy_mode", ProxyMode.TUN))
        self.tun_name_edit.setText(getattr(config, "tun_name", DEFAULT_TUN_NAME))
        self.tun_mtu_spin.setValue(int(getattr(config, "tun_mtu", 1500)))
        self._sync_mode()
        self.theme_combo.blockSignals(True)
        self.theme_combo.select(normalize_theme(getattr(config, "theme", None)))
        self.theme_combo.blockSignals(False)
        self.close_to_tray_check.setChecked(config.close_to_tray)
        self.log_level_combo.select(getattr(config, "log_level", DEFAULT_LOG_LEVEL))

        monitoring = config.monitoring
        self.monitoring_check.setChecked(monitoring.enabled)
        self.interval_spin.setValue(int(monitoring.check_interval_seconds))
        self.failover_check.setChecked(monitoring.failover_enabled)
        self.failover_threshold_spin.setValue(int(monitoring.failover_threshold))
        self._sync_monitoring()

        dns = config.dns
        self.dns_combo.select(dns.provider)
        self.dns_url_edit.setText(dns.custom_url)
        self.dns_additional_edit.setText(dns.additional_url)
        self.dns_proxy_check.setChecked(dns.use_proxy)
        self.dns_intercept_check.setChecked(getattr(dns, "intercept", True))

        fragment = config.tls_fragment
        self.fragment_check.setChecked(fragment.enabled)
        self.fragment_packets_edit.setText(fragment.packets)
        self.fragment_length_edit.setText(fragment.length)
        self.fragment_delay_edit.setText(fragment.delay)
        self._sync_fragment()
        self.mux_check.setChecked(config.mux_default_on)

        user_agent = config.user_agent.strip()
        self.user_agent_edit.setText("" if user_agent == LEGACY_USER_AGENT else user_agent)
        self.device_info_check.setChecked(config.sub_send_device_info)
        self.sub_exceptions_edit.setText(" ".join(config.sub_source_exceptions))
        self.sub_insecure_check.setChecked(config.sub_insecure)

    def save(self) -> bool:
        """Проверить копию настроек и только тогда перенести её в живые."""
        config = copy.deepcopy(self._config)
        config.inbound_address = self.address_edit.text().strip()
        config.inbound_socks_port = self.port_spin.value()
        config.proxy_mode = self.mode_combo.selected()
        config.tun_name = self.tun_name_edit.text().strip()
        config.tun_mtu = self.tun_mtu_spin.value()
        config.log_level = self.log_level_combo.selected()
        config.theme = self.theme_combo.selected()
        config.close_to_tray = self.close_to_tray_check.isChecked()

        config.monitoring.enabled = self.monitoring_check.isChecked()
        config.monitoring.check_interval_seconds = self.interval_spin.value()
        config.monitoring.failover_enabled = self.failover_check.isChecked()
        config.monitoring.failover_threshold = self.failover_threshold_spin.value()

        config.dns.provider = self.dns_combo.selected()
        config.dns.custom_url = self.dns_url_edit.text().strip()
        config.dns.additional_url = self.dns_additional_edit.text().strip()
        config.dns.use_proxy = self.dns_proxy_check.isChecked()
        config.dns.intercept = self.dns_intercept_check.isChecked()

        config.tls_fragment = TlsFragmentSettings(
            enabled=self.fragment_check.isChecked(),
            packets=self.fragment_packets_edit.text(),
            length=self.fragment_length_edit.text(),
            delay=self.fragment_delay_edit.text(),
        )
        config.mux_default_on = self.mux_check.isChecked()

        config.user_agent = self.user_agent_edit.text().strip()
        config.sub_source_exceptions = self.sub_exceptions_edit.text().split()
        config.sub_insecure = self.sub_insecure_check.isChecked()
        config.sub_send_device_info = self.device_info_check.isChecked()
        if config.sub_send_device_info:
            # Идентификатор сохранится вместе с остальными настройками.
            ensure_hwid(config)
        self.about.store(config)

        errors = validate_settings(config)
        self.validation_errors = errors
        for field, attribute in ERROR_FIELDS.items():
            mark_error(getattr(self, attribute), errors.get(field))
        if errors:
            self.status.setText("Исправьте настройки: " + next(iter(errors.values())))
            self.status.show()
            return False
        self.status.hide()
        self._config.__dict__.update(config.__dict__)
        self.settings_saved.emit()
        return True

    # --- окно ---

    def refresh(self) -> None:
        """Данные приложения изменились: список подписок и откат маршрутизации."""
        self.subscriptions.refresh()
        self.about.refresh()

    def show_section(self, title: str) -> None:
        self.sections.setCurrentRow(SECTIONS.index(title))
```

`src/ui/qt/dialogs/settings_pages.py`:

```python
"""Страницы окна настроек со своим поведением: список подписок и «О программе»."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.core_update import evaluate, fetch_releases, known_releases, refresh_known_releases
from src.core.geo import USER_GEO_DIR
from src.core.geo_update import update_geo_bases
from src.ui.controller import CONFIRM_DELETE
from src.ui.logic import platform_texts
from src.ui.logic.routing_form import current_catalog, geo_summary
from src.ui.logic.subscriptions_view import (
    EMPTY_RESPONSE_HINT,
    EMPTY_RESPONSE_TEXT,
    SubscriptionRow,
    build_subscription_rows,
)
from src.ui.logic.version import UNKNOWN, app_version, core_update_text, core_version
from src.ui.qt.dialogs.base import open_url
from src.ui.qt.dialogs.confirm import build_confirmation

if TYPE_CHECKING:
    from src.ui.qt.dialogs.settings import SettingsDialog

ERROR_COLOR = QColor("#d13438")
COLUMNS = ("Название", "Профилей", "Обновлено", "Трафик и срок")
GROUP_ROLE = Qt.ItemDataRole.UserRole + 1


class SubscriptionsPage(QGroupBox):
    """Подписки списком с действиями; в GTK это была отдельная вкладка окна."""

    def __init__(self, dialog: SettingsDialog) -> None:
        super().__init__("Подписки")
        self._dialog = dialog
        self._app = dialog._app
        self._rows: dict[int, SubscriptionRow] = {}

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(list(COLUMNS))
        self.tree.setRootIsDecorated(False)
        self.tree.setMinimumHeight(160)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.itemDoubleClicked.connect(lambda *_: self._edit())
        self.tree.currentItemChanged.connect(lambda *_: self._sync_buttons())
        self.empty_label = QLabel("Подписок нет. Добавьте ссылку от провайдера.")
        self.empty_label.setEnabled(False)

        self.add_button = QPushButton("Добавить…")
        self.add_button.clicked.connect(
            lambda: self._app.open_add_subscription(parent=self._dialog)
        )
        self.update_button = QPushButton("Обновить")
        self.update_button.clicked.connect(self._update)
        self.edit_button = QPushButton("Изменить…")
        self.edit_button.clicked.connect(self._edit)
        self.delete_button = QPushButton("Удалить")
        self.delete_button.clicked.connect(self._delete)
        self.more_button = QPushButton("Ещё")
        self.more_menu = QMenu(self.more_button)
        self.more_button.setMenu(self.more_menu)
        self.more_menu.aboutToShow.connect(lambda: self._fill_menu(self.more_menu, more=True))

        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.update_button,
            self.edit_button,
            self.delete_button,
            self.more_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tree)
        layout.addWidget(self.empty_label)
        layout.addLayout(buttons)
        self.refresh()

    # --- данные ---

    def refresh(self) -> None:
        store = self._app.context.profiles
        selected = self.selected_group_id()
        counts = {gid: len(store.get_profiles_in_group(gid)) for gid in store.groups}
        rows = build_subscription_rows(store.groups, counts)
        self._rows = {row.group_id: row for row in rows}
        self.tree.clear()
        for row in rows:
            details = row.details_text
            if row.empty:
                details = " · ".join(part for part in (details, EMPTY_RESPONSE_TEXT) if part)
            item = QTreeWidgetItem([row.name, str(row.profile_count), row.updated_text, details])
            item.setData(0, GROUP_ROLE, row.group_id)
            item.setToolTip(0, row.url)
            if row.announce:
                item.setToolTip(1, row.announce)
            if row.empty:
                item.setToolTip(3, EMPTY_RESPONSE_HINT)
            if row.expired or row.empty:
                # Истёкшую или пустую подписку видно сразу.
                item.setForeground(3, QBrush(ERROR_COLOR))
            self.tree.addTopLevelItem(item)
            if row.group_id == selected:
                self.tree.setCurrentItem(item)
        for column in range(1, len(COLUMNS)):
            self.tree.resizeColumnToContents(column)
        self.tree.setVisible(bool(rows))
        self.empty_label.setVisible(not rows)
        self._sync_buttons()

    def selected_group_id(self) -> int | None:
        item = self.tree.currentItem()
        return None if item is None else item.data(0, GROUP_ROLE)

    def _selected_row(self) -> SubscriptionRow | None:
        group_id = self.selected_group_id()
        return None if group_id is None else self._rows.get(group_id)

    def _sync_buttons(self) -> None:
        row = self._selected_row()
        for button in (self.update_button, self.edit_button, self.delete_button):
            button.setEnabled(row is not None)
        self.more_button.setEnabled(
            row is not None and bool(row.web_page_url or row.support_url or row.announce)
        )

    # --- действия ---

    def _update(self) -> None:
        if (group_id := self.selected_group_id()) is not None:
            self._app.controller.update_subscription(group_id)

    def _edit(self) -> None:
        if (group_id := self.selected_group_id()) is not None:
            self._app.edit_group(group_id, parent=self._dialog)

    def _delete(self) -> None:
        if (group_id := self.selected_group_id()) is not None:
            self._app.delete_group(group_id, parent=self._dialog)

    def _show_announce(self) -> None:
        row = self._selected_row()
        if row is None or not row.announce:
            return
        box = QMessageBox(
            QMessageBox.Icon.Information,
            "Объявление провайдера",
            row.announce,
            parent=self._dialog,
        )
        # Текст пишет провайдер: только текст, без разметки.
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.open()

    def _fill_menu(self, menu: QMenu, *, more: bool = False) -> None:
        menu.clear()
        row = self._selected_row()
        if row is None:
            return
        if not more:
            menu.addAction("Обновить", self._update)
            menu.addAction("Изменить…", self._edit)
        group_id = row.group_id
        # Ссылки провайдера есть не у каждой подписки: пустой пункт не показываем.
        if row.web_page_url:
            menu.addAction(
                "Страница подписки",
                lambda: self._app.open_subscription_link(group_id, "sub_web_page_url"),
            )
        if row.support_url:
            menu.addAction(
                "Поддержка",
                lambda: self._app.open_subscription_link(group_id, "sub_support_url"),
            )
        if row.announce:
            menu.addAction("Объявление провайдера", self._show_announce)
        if not more:
            menu.addSeparator()
            menu.addAction("Удалить", self._delete)

    def menu_labels(self) -> list[str]:
        menu = QMenu()
        self._fill_menu(menu)
        return [action.text() for action in menu.actions() if not action.isSeparator()]

    def _on_context_menu(self, point) -> None:
        item = self.tree.itemAt(point)
        if item is None:
            return
        self.tree.setCurrentItem(item)
        menu = QMenu(self)
        self._fill_menu(menu)
        menu.exec(self.tree.viewport().mapToGlobal(point))


class AboutPage(QWidget):
    """Версии, проверка обновлений и обслуживание: журналы, геобазы, откат."""

    def __init__(self, dialog: SettingsDialog) -> None:
        super().__init__()
        self._dialog = dialog
        self._app = dialog._app
        self._config = dialog._config
        self._context = dialog._context
        self.fetch_releases = fetch_releases
        self.fetch_app_releases = None
        self.core_update_thread = None
        self.app_update_thread = None

        about = QGroupBox("Veblock")
        form = QFormLayout(about)
        form.addRow("Версия", self._value(app_version()))

        self.app_update_label = QLabel(
            self._config.app_update_target or "Нет сведений о новой версии"
        )
        self.app_check_button = QPushButton("Проверить")
        self.app_check_button.clicked.connect(self.check_app_update)
        self.app_release_button = QPushButton("Открыть релиз")
        self.app_release_button.setEnabled(bool(self._config.app_update_url))
        self.app_release_button.clicked.connect(self._open_app_release)
        form.addRow(
            "Обновление приложения",
            self._with(self.app_update_label, self.app_check_button, self.app_release_button),
        )
        self.app_updates_check = QCheckBox("Проверять обновления приложения раз в сутки")
        self.app_updates_check.setChecked(self._config.app_update_enabled)
        form.addRow(self.app_updates_check)
        self.app_prereleases_check = QCheckBox("Предлагать предварительные версии приложения")
        self.app_prereleases_check.setChecked(self._config.app_update_prerelease)
        form.addRow(self.app_prereleases_check)
        self.core_updates_check = QCheckBox("Проверять обновления ядра раз в три дня")
        self.core_updates_check.setChecked(self._config.core_update_enabled)
        form.addRow(self.core_updates_check)

        self._core_version = core_version(getattr(self._context, "xray_manager", None))
        form.addRow("Ядро xray", self._value(self._core_version))
        self.core_update_label = QLabel()
        self.core_update_button = QPushButton("Проверить")
        self.core_update_button.clicked.connect(self.check_core_update)
        form.addRow("Обновление ядра", self._with(self.core_update_label, self.core_update_button))
        self._show_core_update()
        form.addRow("Конфигурация", self._value(str(self._context.config_dir)))

        maintenance = QGroupBox("Обслуживание")
        form = self._maintenance = QFormLayout(maintenance)
        # Без подтверждения, как в Android: откат возвращает только то, что
        # пользователь сам только что заменил импортом.
        self.restore_routing_button = QPushButton("Вернуть")
        self.restore_routing_button.clicked.connect(
            lambda: self._app.activate_action("restore-routing")
        )
        self.restore_routing_row = self._with(
            QLabel("Режим и списки до последнего импорта ссылкой"), self.restore_routing_button
        )
        form.addRow("Маршрутизация до импорта", self.restore_routing_row)
        self.clear_logs_label = QLabel("Удаляет накопленные файлы логов")
        clear = QPushButton("Очистить")
        clear.clicked.connect(self._on_clear_logs)
        form.addRow("Журналы", self._with(self.clear_logs_label, clear))
        self.geo_label = QLabel(geo_summary(current_catalog()))
        self.geo_label.setTextFormat(Qt.TextFormat.PlainText)
        self.geo_update_button = QPushButton("Обновить")
        self.geo_update_button.clicked.connect(self._on_update_geo)
        form.addRow("Геобазы", self._with(self.geo_label, self.geo_update_button))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(about)
        layout.addWidget(maintenance)
        self.refresh()

    @staticmethod
    def _value(text: str) -> QLabel:
        label = QLabel(text)
        # Настоящее значение копируют в отчёт об ошибке; прочерк — незачем.
        if text != UNKNOWN:
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return label

    @staticmethod
    def _with(label: QLabel, *buttons: QPushButton) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        label.setWordWrap(True)
        row.addWidget(label, 1)
        for button in buttons:
            row.addWidget(button)
        return box

    def fields(self) -> list[QWidget]:
        return [self.app_updates_check, self.app_prereleases_check, self.core_updates_check]

    def store(self, config) -> None:
        config.app_update_enabled = self.app_updates_check.isChecked()
        config.app_update_prerelease = self.app_prereleases_check.isChecked()
        config.core_update_enabled = self.core_updates_check.isChecked()

    def refresh(self) -> None:
        # Строка видна, только когда есть что возвращать, как в GTK.
        self._maintenance.setRowVisible(
            self.restore_routing_row, self._config.routing_backup is not None
        )

    # --- обновление приложения ---

    def _open_app_release(self) -> None:
        from src.core.app_update import safe_release_url

        url = self._config.app_update_url
        if safe_release_url(url):
            open_url(url)

    def check_app_update(self) -> None:
        from src.core.app_update import check_app_update, fetch_app_releases
        from src.sub.route import local_proxy_url

        self.app_check_button.setEnabled(False)
        self.app_update_label.setText("Проверка…")
        context = self._context
        fetch = self.fetch_app_releases or (
            lambda: fetch_app_releases(lambda: local_proxy_url(context.config, context.proxy_state))
        )

        def done(release) -> None:
            self.app_check_button.setEnabled(True)
            text = f"Доступна версия {release.version}" if release else "Новых версий нет"
            if release and not release.has_asset:
                text += "; " + platform_texts.missing_release_asset()
            self.app_update_label.setText(text)
            self.app_release_button.setEnabled(bool(release))
            context.save_config()

        def failed(_error) -> None:
            self.app_check_button.setEnabled(True)
            self.app_update_label.setText("Не удалось проверить обновления")
            context.save_config()

        self.app_update_thread = self._dialog.run(
            lambda: check_app_update(self._config, app_version(), force=True, fetch=fetch),
            done,
            failed,
            name="tenga-app-update-manual",
        )

    # --- обновление ядра ---

    def _show_core_update(self) -> None:
        status = evaluate(self._core_version, known_releases(self._config))
        self.core_update_label.setText(core_update_text(status))

    def check_core_update(self) -> None:
        self.core_update_button.setEnabled(False)
        self.core_update_label.setText("Проверяю…")

        def done(_releases) -> None:
            self.core_update_button.setEnabled(True)
            self._show_core_update()
            # Время проверки — в настройках: иначе следующий запуск спросил бы снова.
            self._context.save_config()

        def failed(_error) -> None:
            self.core_update_button.setEnabled(True)
            self.core_update_label.setText("Не удалось проверить обновления")

        self.core_update_thread = self._dialog.run(
            lambda: refresh_known_releases(
                self._config, now=time.time(), fetch=self.fetch_releases
            ),
            done,
            failed,
            name="tenga-core-update",
        )

    # --- обслуживание ---

    def _on_clear_logs(self) -> None:
        def clear() -> None:
            self._dialog.run(
                self._context.log_manager.clear_all_logs,
                lambda result: self.clear_logs_label.setText(f"Очищено файлов: {result[0]}"),
                name="tenga-clear-logs",
            )

        build_confirmation(
            CONFIRM_DELETE,
            "Очистить журналы?",
            "Все сохранённые записи будут удалены.",
            clear,
            confirm_label="Очистить",
            parent=self._dialog,
        ).open()

    def _on_update_geo(self) -> None:
        # Десятки мегабайт: в главном потоке окно бы замерло.
        self.geo_update_button.setEnabled(False)
        self.geo_label.setText("Скачивание…")

        def done(catalog) -> None:
            self.geo_update_button.setEnabled(True)
            self.geo_label.setText(f"{geo_summary(catalog)} — применятся после переподключения")
            self._context.proxy_state.notify_listeners()

        def failed(error) -> None:
            self.geo_update_button.setEnabled(True)
            self.geo_label.setText(f"Не обновлены: {error}")

        self._dialog.run(
            lambda: update_geo_bases(USER_GEO_DIR), done, failed, name="tenga-geo-update"
        )
```

Замечания:
- Проверка прав TUN (`tun_access.tun_problems`) идёт в фоне, только в режиме TUN и один раз за открытие окна, как в GTK. В тестах её подменяет автофикстура `tests/conftest.py`.
- `refresh()` окна зовёт `_QtShell.refresh_pages` и `set_action_enabled`. Список подписок и строка «Маршрутизация до импорта» поэтому следят за контроллером, пока окно открыто.
- Строка «Маршрутизация до импорта» скрыта, пока возвращать нечего (`QFormLayout.setRowVisible`), как в GTK.

**Step 4: Run to verify it passes** — Expected: 24 passed; `make test-qt` — 124 passed.

**Step 5: Commit**

```bash
python cli.py lint-all
git add src/ui/qt/dialogs/settings.py src/ui/qt/dialogs/settings_pages.py tests/test_ui_qt_settings.py
git commit -m "feat(qt): окно настроек — разделы, подписки, о программе"
```

---

### Task 8: Окно — меню строк, «Добавить», подписки в дереве, журнал

**Files:**
- Create: `src/ui/qt/widgets/diagnostics.py`
- Modify: `src/ui/qt/window.py`, `src/ui/qt/models.py`, `src/ui/qt/widgets/status_card.py`
- Modify: `tests/test_ui_qt_application.py` (проверка импорта без `gi` охватывает новые модули)
- Test: `tests/test_ui_qt_window.py`

**Step 1: Write the failing test** — `tests/test_ui_qt_window.py`:

```python
"""Главное окно Qt: меню строк, «Добавить», подписки, настройки окна, журнал."""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QMessageBox

from src.core.context import AppContext
from src.fmt import parse_link
from src.ui.qt.application import QtApplication
from src.ui.qt.dialogs.profile import AddProfileDialog
from src.ui.qt.models import ADDRESS_COLUMN, EXPIRED_COLOR
from tests.support.qt import process_events, wait_until

pytestmark = pytest.mark.qt

LINK = "vless://11111111-2222-3333-4444-555555555555@example.org:443?type=tcp#Проба"


class TrayItem:
    """Трей без системы: только интерфейс элемента."""

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


@pytest.fixture
def made(qapp, tmp_path):
    context = AppContext(config_dir=tmp_path)
    assert context.config is not None
    app = QtApplication(context, with_tray=False)
    yield app
    while app.current_dialog is not None:
        app.current_dialog.reject()
        process_events()
    app.stop_tray()
    if app.window is not None:
        app.window.detach()
        app.window.deleteLater()
    process_events()


def _profile(app, name="Проба", group_id=None):
    return app.controller.add_profile_from_bean(
        parse_link(LINK.replace("Проба", name)), group_id=group_id
    )


def _labels(menu):
    return [a.text() for a in menu.actions() if not a.isSeparator()]


# --- меню строк ---


def test_profile_menu_matches_gtk(made):
    entry = _profile(made)
    made.activate()

    menu = made.window.context_menu(made.window.model.profile_index(entry.id))

    assert _labels(menu) == [
        "Подключить",
        "VPN и маршруты…",
        "Тест задержки",
        "Редактировать",
        "Удалить",
    ]


def test_group_menu_and_subscription_extra(made):
    plain = made.controller.add_group("Дом")
    _profile(made, group_id=plain.id)
    subscription = made.context.profiles.add_group("Провайдер", is_subscription=True)
    _profile(made, group_id=subscription.id)
    made.activate()
    window = made.window

    plain_menu = window.context_menu(window.model.group_index(plain.id))
    sub_menu = window.context_menu(window.model.group_index(subscription.id))

    assert _labels(plain_menu) == [
        "Свернуть группу",
        "Тест задержки",
        "Оставить рабочие…",
        "Редактировать",
        "Удалить",
    ]
    assert "Обновить подписку" in _labels(sub_menu)


def test_menu_entry_runs_the_row_action(made):
    entry = _profile(made)
    made.activate()

    menu = made.window.context_menu(made.window.model.profile_index(entry.id))
    next(a for a in menu.actions() if a.text() == "Удалить").trigger()

    assert isinstance(made.current_dialog, QMessageBox)


def test_toggle_group_flips_the_branch(made):
    group = made.controller.add_group("Дом")
    _profile(made, group_id=group.id)
    made.activate()
    index = made.window.model.group_index(group.id)
    assert made.window.tree.isExpanded(index)

    made.activate_action("toggle-group", group.id)

    assert not made.window.tree.isExpanded(made.window.model.group_index(group.id))
    menu = made.window.context_menu(made.window.model.group_index(group.id))
    assert _labels(menu)[0] == "Развернуть группу"


# --- низ окна и дерево ---


def test_add_menu_runs_the_actions(made):
    made.activate()

    assert _labels(made.window.add_menu) == [
        "Профиль по ссылке…",
        "Профиль из буфера обмена",
        "Подписка…",
        "Группа…",
    ]
    made.window.add_menu.actions()[0].trigger()
    assert isinstance(made.current_dialog, AddProfileDialog)


def test_subscription_details_are_in_the_group_row(made):
    group = made.context.profiles.add_group("Провайдер", is_subscription=True)
    group.sub_user_info = "upload=0; download=1073741824; total=2147483648; expire=1000000000"
    _profile(made, group_id=group.id)
    made.activate()

    row = made.window.model.group_index(group.id).row()
    cell = made.window.model.item(row, ADDRESS_COLUMN)

    assert " из " in cell.text()
    assert "истекла" in cell.text()
    assert cell.foreground().color() == EXPIRED_COLOR


def test_status_card_shows_the_flag_as_a_picture(made):
    entry = _profile(made, "🇩🇪 Берлин")
    made.activate()

    made.context.proxy_state.set_running(entry.id, mode="system")
    made.window.refresh_status()

    card = made.window.status_card
    assert card.subtitle.text() == "Берлин"
    assert not card.flag.isHidden()
    assert card.subtitle.toolTip() == "🇩🇪 Берлин"


# --- настройки окна ---


def test_close_to_tray_can_be_turned_off(made, monkeypatch):
    made.tray_item = TrayItem()
    made.start_tray()
    made.context.config.close_to_tray = False
    made.activate()
    quits = []
    monkeypatch.setattr(made, "quit", lambda: quits.append(1))

    made.window.close()

    assert quits == [1]


def test_monitoring_panel_visibility_is_remembered(made, qapp):
    made.context.config.monitoring_panel = False
    made.activate()
    window = made.window
    assert not window.monitoring_button.isChecked()
    assert window.monitoring_dock.isHidden()

    window.monitoring_button.setChecked(True)
    window.save_geometry()

    assert made.context.config.monitoring_panel is True
    assert not window.monitoring_dock.isHidden()


# --- журнал ---


def _diagnostics(made, tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "tenga_gui.log").write_text("строка журнала\n", encoding="utf-8")
    made.activate()
    panel = made.window.diagnostics
    panel._log_dir = lambda: logs
    return panel, logs


def test_journal_is_read_in_the_background(made, tmp_path):
    panel, _logs = _diagnostics(made, tmp_path)

    panel.refresh()

    wait_until(lambda: "строка журнала" in panel.view.toPlainText())


def test_journal_reads_only_while_visible(made, tmp_path):
    panel, _logs = _diagnostics(made, tmp_path)
    assert panel.active

    made.window.monitoring_button.setChecked(False)
    assert not panel.active


def test_export_writes_the_cleaned_journal(made, tmp_path):
    panel, _logs = _diagnostics(made, tmp_path)
    target = tmp_path / "export.txt"
    panel.ask_export_path = lambda _parent: str(target)

    panel.export()
    panel.thread.join(5)

    assert "строка журнала" in target.read_text(encoding="utf-8")


def test_clear_asks_and_removes_the_files(made, tmp_path):
    panel, logs = _diagnostics(made, tmp_path)

    panel.clear()
    box = made.current_dialog
    assert isinstance(box, QMessageBox)
    next(b for b in box.buttons() if b.text() == "Очистить").click()

    # Открытые журналы обрезаются, а не удаляются: в них пишут обработчики.
    wait_until(lambda: (logs / "tenga_gui.log").read_text(encoding="utf-8") == "")
```

и расширить проверку импорта без GTK:

```diff
diff --git a/tests/test_ui_qt_application.py b/tests/test_ui_qt_application.py
index d7610f8..327fe76 100644
--- a/tests/test_ui_qt_application.py
+++ b/tests/test_ui_qt_application.py
@@ -340,7 +340,9 @@ def test_qt_frontend_imports_without_gtk():
 
     code = (
         "import sys; sys.modules['gi'] = None; "
-        "import src.ui.qt.application, src.ui.qt.tray, src.ui.tray.controller"
+        "import src.ui.qt.application, src.ui.qt.tray, src.ui.tray.controller, "
+        "src.ui.qt.dialogs.settings, src.ui.qt.dialogs.settings_pages, "
+        "src.ui.qt.dialogs.profile_routing, src.ui.qt.widgets.diagnostics"
     )
     result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
 
```

**Step 2: Run to verify it fails** — `ImportError: cannot import name 'EXPIRED_COLOR' from 'src.ui.qt.models'`.

**Step 3: Implementation**

`src/ui/qt/widgets/diagnostics.py`:

```python
"""Журнал в панели мониторинга: последние записи, экспорт, очистка.

Текст собирает `read_diagnostics` (src/core/diagnostics_export.py), общий с
GTK: секреты замаскированы, размер ограничен. Чтение — в фоне, раз в две
секунды, пока панель видна.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from src.core.diagnostics_export import read_diagnostics
from src.ui.controller import CONFIRM_DELETE
from src.ui.logic.async_utils import run_in_background
from src.ui.qt.dialogs.confirm import build_confirmation

REFRESH_INTERVAL_MS = 2000
EXPORT_NAME = "veblock-diagnostics.txt"


def default_log_dir() -> Path:
    from src.core.config import LOG_DIR

    return LOG_DIR


def ask_export_path(parent: QWidget) -> str:
    path, _filter = QFileDialog.getSaveFileName(
        parent, "Экспорт очищенного журнала", EXPORT_NAME, "Текст (*.txt)"
    )
    return path


class DiagnosticsPanel(QGroupBox):
    def __init__(
        self,
        *,
        dispatch: Callable[..., object],
        show_dialog: Callable[[QWidget], object],
        log_dir: Callable[[], Path] = default_log_dir,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("Журнал", parent)
        self.setToolTip("Последние записи. Хранение — 3 дня; секреты маскируются.")
        self._dispatch = dispatch
        self._show_dialog = show_dialog
        self._log_dir = log_dir
        self._busy = False
        self.ask_export_path = ask_export_path
        self.thread = None

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        # Строки журнала длинные: перенос растягивал бы панель на пол-экрана.
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.view.setMinimumHeight(160)
        self.refresh_button = QPushButton("Обновить")
        self.refresh_button.clicked.connect(self.refresh)
        self.export_button = QPushButton("Экспорт…")
        self.export_button.clicked.connect(self.export)
        self.clear_button = QPushButton("Очистить")
        self.clear_button.clicked.connect(self.clear)

        buttons = QHBoxLayout()
        for button in (self.refresh_button, self.export_button, self.clear_button):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.view, 1)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)

    def _run(self, fn, on_done=None, on_error=None, *, name: str):
        def alive(callback):
            if callback is None:
                return None
            return lambda value: callback(value) if isValid(self) else None

        self.thread = run_in_background(
            fn, alive(on_done), alive(on_error), dispatch=self._dispatch, name=name
        )
        return self.thread

    def set_active(self, active: bool) -> None:
        """Читать журнал, только пока его видно."""
        if active and not self._timer.isActive():
            self.refresh()
            self._timer.start()
        elif not active:
            self._timer.stop()

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True

        def done(text: str) -> None:
            self._busy = False
            # Прокрутка не прыгает вверх, если читатель смотрит конец журнала.
            bar = self.view.verticalScrollBar()
            at_end = bar.value() == bar.maximum()
            self.view.setPlainText(text)
            if at_end:
                bar.setValue(bar.maximum())

        def failed(_error) -> None:
            self._busy = False

        self._run(lambda: read_diagnostics(self._log_dir()), done, failed, name="tenga-diag")

    def export(self) -> None:
        path = self.ask_export_path(self)
        if not path:
            return
        target = Path(path)

        def write() -> None:
            target.write_text(read_diagnostics(self._log_dir()), encoding="utf-8")

        self._run(
            write,
            on_error=lambda _error: self.view.setPlainText("Не удалось экспортировать журнал"),
            name="tenga-diag-export",
        )

    def clear(self) -> None:
        from src.core.log_manager import LogManager

        def confirmed() -> None:
            self._run(
                lambda: LogManager(self._log_dir()).clear_all_logs(),
                lambda _result: self.refresh(),
                name="tenga-diag-clear",
            )

        self._show_dialog(
            build_confirmation(
                CONFIRM_DELETE,
                "Очистить журналы?",
                "Все сохранённые записи будут удалены.",
                confirmed,
                confirm_label="Очистить",
                parent=self.window(),
            )
        )
```

`src/ui/qt/models.py` — трафик и срок подписки в строке группы:

```diff
diff --git a/src/ui/qt/models.py b/src/ui/qt/models.py
index a1ad0f5..941978a 100644
--- a/src/ui/qt/models.py
+++ b/src/ui/qt/models.py
@@ -7,8 +7,10 @@
 
 from __future__ import annotations
 
+from collections.abc import Mapping
+
 from PySide6.QtCore import QModelIndex, Qt
-from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
+from PySide6.QtGui import QBrush, QColor, QFont, QStandardItem, QStandardItemModel
 
 from src.ui.logic.latency import PingProgress
 from src.ui.logic.profiles_view import GroupRow, ProfileRow, SortKey, ping_text
@@ -24,6 +26,9 @@ KIND_ROLE = Qt.ItemDataRole.UserRole + 1
 ID_ROLE = Qt.ItemDataRole.UserRole + 2
 GROUP, PROFILE = "group", "profile"
 
+# Истёкшая подписка: тот же красный, что у ошибок в карточке.
+EXPIRED_COLOR = QColor("#d13438")
+
 
 def _cell(text: str) -> QStandardItem:
     item = QStandardItem(text)
@@ -46,15 +51,29 @@ class ProfileTreeModel(QStandardItemModel):
         self.setHorizontalHeaderLabels(list(COLUMNS))
         self._rows: list[GroupRow] = []
 
-    def set_rows(self, rows: list[GroupRow], progress: PingProgress | None = None) -> None:
+    def set_rows(
+        self,
+        rows: list[GroupRow],
+        progress: PingProgress | None = None,
+        details: Mapping[int, tuple[str, bool]] | None = None,
+    ) -> None:
+        """`details` — трафик и срок подписки по id группы: (текст, истекла ли)."""
         self._rows = rows
         self.removeRows(0, self.rowCount())
         for row in rows:
-            self.appendRow(self._group_items(row, progress))
+            text, expired = (details or {}).get(row.group_id, ("", False))
+            self.appendRow(self._group_items(row, progress, text, expired))
 
-    def _group_items(self, row: GroupRow, progress: PingProgress | None) -> list[QStandardItem]:
+    def _group_items(
+        self, row: GroupRow, progress: PingProgress | None, details: str, expired: bool
+    ) -> list[QStandardItem]:
         name = _cell(row.title)
-        cells = [name, _cell(""), _cell(""), _cell(group_count_text(row, progress))]
+        info = _cell(details)
+        info.setToolTip(details)
+        if expired:
+            # Серверов в истёкшей подписке обычно уже нет: видно сразу.
+            info.setForeground(QBrush(EXPIRED_COLOR))
+        cells = [name, _cell(""), info, _cell(group_count_text(row, progress))]
         for cell in cells:
             cell.setData(GROUP, KIND_ROLE)
             cell.setData(row.group_id, ID_ROLE)
```

`src/ui/qt/widgets/status_card.py` — флаг картинкой:

```diff
diff --git a/src/ui/qt/widgets/status_card.py b/src/ui/qt/widgets/status_card.py
index 9d7d91d..6a1272e 100644
--- a/src/ui/qt/widgets/status_card.py
+++ b/src/ui/qt/widgets/status_card.py
@@ -14,8 +14,10 @@ from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLay
 
 from src.core.config import get_asset_path
 from src.ui.logic.status import StatusView
+from src.ui.qt.icons import flagged
 
 LOGO_SIZE = 48
+FLAG_SIZE = 16
 
 
 @cache
@@ -43,17 +45,26 @@ class StatusCard(QFrame):
         self.logo.setFixedSize(LOGO_SIZE, LOGO_SIZE)
         self.title = QLabel()
         self.title.setObjectName("statusTitle")
+        # Имя профиля с флагом картинкой: эмодзи-флагов в шрифтах Windows нет.
+        self.flag = QLabel()
+        self.flag.hide()
         self.subtitle = QLabel()
         self.metrics = QLabel()
         self.metrics.setObjectName("statusMetrics")
         self.button = QPushButton()
         self.button.clicked.connect(self.action_clicked)
 
+        name = QHBoxLayout()
+        name.setSpacing(6)
+        name.addWidget(self.flag)
+        name.addWidget(self.subtitle, 1)
         texts = QVBoxLayout()
         texts.setSpacing(2)
         for label in (self.title, self.subtitle, self.metrics):
             label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
-            texts.addWidget(label)
+        texts.addWidget(self.title)
+        texts.addLayout(name)
+        texts.addWidget(self.metrics)
 
         self._tools = QHBoxLayout()
         layout = QHBoxLayout(self)
@@ -68,7 +79,12 @@ class StatusCard(QFrame):
 
     def update_view(self, view: StatusView) -> None:
         self.title.setText(view.title)
-        self.subtitle.setText(view.subtitle)
+        icon, name = flagged(view.subtitle)
+        self.flag.setVisible(icon is not None)
+        if icon is not None:
+            self.flag.setPixmap(icon.pixmap(FLAG_SIZE, FLAG_SIZE))
+        self.subtitle.setText(name)
+        self.subtitle.setToolTip(view.subtitle)
         self.subtitle.setVisible(bool(view.subtitle))
         self.metrics.setText(view.metrics)
         self.metrics.setVisible(bool(view.metrics))
```

`src/ui/qt/window.py`:

```diff
diff --git a/src/ui/qt/window.py b/src/ui/qt/window.py
index 3846740..d0ac8dd 100644
--- a/src/ui/qt/window.py
+++ b/src/ui/qt/window.py
@@ -33,6 +33,7 @@ from src.ui.logic.geometry import MIN_HEIGHT, MIN_WIDTH, Geometry, format_geomet
 from src.ui.logic.monitoring_view import monitoring_view
 from src.ui.logic.profiles_view import SortKey, build_profile_rows
 from src.ui.logic.status import ConnectionState, status_view
+from src.ui.logic.subscriptions_view import build_subscription_rows
 from src.ui.qt.models import (
     GROUP,
     NAME_COLUMN,
@@ -40,6 +41,7 @@ from src.ui.qt.models import (
     SORT_KEYS,
     ProfileTreeModel,
 )
+from src.ui.qt.widgets.diagnostics import DiagnosticsPanel
 from src.ui.qt.widgets.status_card import StatusCard
 from src.ui.qt.widgets.toast import Toast
 
@@ -60,6 +62,35 @@ MAIN_MENU = (
     ("quit", "Выход"),
 )
 
+# Меню кнопки «Добавить» внизу окна.
+ADD_MENU = (
+    ("add-profile", "Профиль по ссылке…"),
+    ("add-profile-from-clipboard", "Профиль из буфера обмена"),
+    ("add-subscription", "Подписка…"),
+    ("add-group", "Группа…"),
+)
+
+# Меню строк дерева: (действие, подпись); None — разделитель. Как в GTK
+# (src/ui/pages/profiles.py), у подписки ещё «Обновить подписку»: списка
+# подписок на главном экране Qt нет.
+PROFILE_MENU = (
+    ("connect-profile", "Подключить"),
+    ("profile-routing", "VPN и маршруты…"),
+    ("test-profile", "Тест задержки"),
+    None,
+    ("edit-profile", "Редактировать"),
+    ("delete-profile", "Удалить"),
+)
+GROUP_MENU = (
+    ("toggle-group", ""),  # подпись зависит от того, раскрыта ли группа
+    ("update-subscription", "Обновить подписку"),
+    ("test-group", "Тест задержки"),
+    ("keep-working", "Оставить рабочие…"),
+    None,
+    ("edit-group", "Редактировать"),
+    ("delete-group", "Удалить"),
+)
+
 
 STYLE_SHEET = Path(__file__).with_name("style.qss")
 
@@ -115,7 +146,7 @@ class MainWindow(QMainWindow):
         self.monitoring_button = QToolButton()
         self.monitoring_button.setText("Мониторинг")
         self.monitoring_button.setCheckable(True)
-        self.monitoring_button.setChecked(True)
+        self.monitoring_button.setChecked(self._context.config.monitoring_panel)
         self.status_card.add_tool(self.monitoring_button)
         self.menu_button = QToolButton()
         self.menu_button.setText("☰")
@@ -153,6 +184,8 @@ class MainWindow(QMainWindow):
         self.tree.header().setSectionResizeMode(NAME_COLUMN, self.tree.header().ResizeMode.Stretch)
         self.tree.header().sectionClicked.connect(self._on_header_clicked)
         self.tree.activated.connect(self._on_activated)
+        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
+        self.tree.customContextMenuRequested.connect(self._on_context_menu)
         self.tree.collapsed.connect(lambda index: self._remember_collapsed(index, True))
         self.tree.expanded.connect(lambda index: self._remember_collapsed(index, False))
         layout.addWidget(self.tree, 1)
@@ -166,6 +199,14 @@ class MainWindow(QMainWindow):
         self.search.setClearButtonEnabled(True)
         self.search.textChanged.connect(lambda _text: self.refresh_pages())
         bottom.addWidget(self.search, 1)
+        self.add_button = QToolButton()
+        self.add_button.setText("Добавить")
+        self.add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
+        self.add_menu = QMenu(self.add_button)
+        for name, label in ADD_MENU:
+            self.add_menu.addAction(label).triggered.connect(self._app.actions[name].trigger)
+        self.add_button.setMenu(self.add_menu)
+        bottom.addWidget(self.add_button)
         layout.addLayout(bottom)
 
         self.setCentralWidget(central)
@@ -184,10 +225,14 @@ class MainWindow(QMainWindow):
         self.check_button = QPushButton("Проверить сейчас")
         self.check_button.clicked.connect(self._on_check_now)
         column.addWidget(self.check_button)
-        column.addStretch(1)
+        self.diagnostics = DiagnosticsPanel(
+            dispatch=self._app.loop.dispatch, show_dialog=self._app.show_dialog
+        )
+        column.addWidget(self.diagnostics, 1)
         self.monitoring_dock.setWidget(body)
         self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.monitoring_dock)
-        self.monitoring_button.toggled.connect(self.monitoring_dock.setVisible)
+        self.monitoring_dock.setVisible(self._context.config.monitoring_panel)
+        self.monitoring_button.toggled.connect(self._on_monitoring_toggled)
         self.monitoring_dock.visibilityChanged.connect(self._on_dock_visibility)
 
     # --- состояние ---
@@ -233,7 +278,11 @@ class MainWindow(QMainWindow):
             ascending=self._ascending,
             active_profile_id=state.started_profile_id if state.is_running else -1,
         )
-        self.model.set_rows(rows, self._ping_progress)
+        details = {
+            row.group_id: (row.details_text, row.expired)
+            for row in build_subscription_rows(groups, {})
+        }
+        self.model.set_rows(rows, self._ping_progress, details)
         for position in range(self.model.rowCount()):
             index = self.model.index(position, NAME_COLUMN)
             group_id = self.model.target(index)[1]
@@ -350,10 +399,53 @@ class MainWindow(QMainWindow):
             monitor.check_now()
         self.refresh_monitoring()
 
+    def _on_monitoring_toggled(self, visible: bool) -> None:
+        self.monitoring_dock.setVisible(visible)
+        # Видимость запоминается вместе с геометрией окна.
+        self._context.config.monitoring_panel = visible
+
     def _on_dock_visibility(self, visible: bool) -> None:
         # Свёрнутое окно прячет и панель: кнопка следит только за явным закрытием.
         if not self.isMinimized() and self.isVisible():
             self.monitoring_button.setChecked(visible)
+        self.diagnostics.set_active(visible and self.isVisible())
+
+    def toggle_group(self, group_id: int) -> None:
+        index = self.model.group_index(group_id)
+        if index.isValid():
+            self.tree.setExpanded(index, not self.tree.isExpanded(index))
+
+    def context_menu(self, index) -> QMenu:
+        """Меню строки; пункты зовут действия приложения с id строки."""
+        menu = QMenu(self)
+        target = self.model.target(index)
+        if target is None:
+            return menu
+        kind, row_id = target
+        entries = PROFILE_MENU if kind == PROFILE else GROUP_MENU
+        group = self._context.profiles.get_group(row_id) if kind == GROUP else None
+        for entry in entries:
+            if entry is None:
+                menu.addSeparator()
+                continue
+            name, label = entry
+            if name == "toggle-group":
+                expanded = self.tree.isExpanded(self.model.index(index.row(), NAME_COLUMN))
+                label = "Свернуть группу" if expanded else "Развернуть группу"
+            if name == "update-subscription" and not getattr(group, "is_subscription", False):
+                continue
+            action = menu.addAction(label)
+            action.triggered.connect(
+                lambda _checked=False, n=name: self._app.activate_action(n, row_id)
+            )
+        return menu
+
+    def _on_context_menu(self, point) -> None:
+        index = self.tree.indexAt(point)
+        if not index.isValid():
+            return
+        self.tree.setCurrentIndex(index)
+        self.context_menu(index).exec(self.tree.viewport().mapToGlobal(point))
 
     def _on_proxy_state_changed(self, _state) -> None:
         # Состояние меняет поток подключения; виджеты — только из главного.
@@ -373,13 +465,15 @@ class MainWindow(QMainWindow):
             self.show()
         self.raise_()
         self.activateWindow()
+        self.diagnostics.set_active(self.monitoring_dock.isVisible())
 
     def closeEvent(self, event) -> None:
         """С треем окно прячется, без него закрытие завершает приложение."""
         self.save_geometry()
-        if self._app.tray is not None:
+        if self._app.tray is not None and self._context.config.close_to_tray:
             event.ignore()
             self.hide()
+            self.diagnostics.set_active(False)
             return
         event.accept()
         self._app.quit()
@@ -387,6 +481,7 @@ class MainWindow(QMainWindow):
     def detach(self) -> None:
         """Перестать слушать состояние прокси, как `MainWindow.detach()` в GTK."""
         self._context.proxy_state.remove_listener(self._on_proxy_state_changed)
+        self.diagnostics.set_active(False)
 
     def save_geometry(self) -> None:
         size = self.normalGeometry().size() if self.isMaximized() else self.size()
```

Замечания:
- Пустые группы в дереве не показываются (`build_profile_rows`), поэтому в тестах у подписки есть профиль.
- Журнал без переноса строк: длинные строки растягивали бы панель на пол-окна.
- `detach()` и закрытие в трей останавливают таймер журнала.

**Step 4: Run to verify it passes** — Expected: 13 passed; `make test-qt` — 137 passed.

**Step 5: Проверить компоновку глазами.** Снимки в offscreen:

```bash
SHOT="$(mktemp -d)"
cat > "$SHOT/shot.py" <<'PY'
import sys, tempfile
from pathlib import Path
from PySide6.QtWidgets import QApplication
app = QApplication([])
from src.core.context import AppContext
from src.fmt import parse_link
from src.ui.qt.application import QtApplication
out = Path(sys.argv[1])
ctx = AppContext(config_dir=Path(tempfile.mkdtemp())); ctx.config
qa = QtApplication(ctx, with_tray=False)
g = ctx.profiles.add_group("Провайдер", is_subscription=True)
g.subscription_url = "https://sub.example.org/s"
g.sub_user_info = "upload=0; download=1073741824; total=53687091200; expire=4102444800"
for i, n in enumerate(["🇩🇪 Берлин", "🇳🇱 Амстердам", "🇫🇮 Хельсинки"]):
    e = qa.controller.add_profile_from_bean(parse_link(
        f"vless://11111111-2222-3333-4444-555555555555@s{i}.example.org:443?type=tcp#{n}"), group_id=g.id)
qa.activate()
ctx.proxy_state.set_running(e.id - 2, mode="system")
qa.window.refresh_status(); qa.window.refresh_pages(); qa.window.resize(1000, 620)
def pump():
    for _ in range(40): app.processEvents()
pump(); qa.window.grab().save(str(out / "main.png"))
qa.open_settings(); d = qa.current_dialog
for idx, name in [(0, "general"), (4, "subs"), (5, "about")]:
    d.sections.setCurrentRow(idx); pump(); d.grab().save(str(out / f"settings-{name}.png"))
d.reject(); pump()
qa.activate_action("profile-routing", e.id); d = qa.current_dialog
d.tabs.setCurrentIndex(1); pump(); d.grab().save(str(out / "routing.png"))
PY
QT_QPA_PLATFORM=offscreen PYTHONPATH=. uv run python "$SHOT/shot.py" "$SHOT"
ls "$SHOT"/*.png
```

Expected:
- Главное окно: в строке «Провайдер» колонка «Сервер» показывает «1.00 GB из 50.00 GB · до 01.01.2100»; в карточке флаг картинкой и «Берлин»; внизу «Поиск» и «Добавить ▾»; справа «Мониторинг» и под ним «Журнал» с кнопками «Обновить / Экспорт… / Очистить».
- Настройки: разделы слева; на «Подписках» таблица и под ней параметры запроса; на «О программе» версии и «Обслуживание».
- «Маршрутизация»: блок «Режим» не сжат, списки прокручиваются.

**Step 6: Commit**

```bash
python cli.py lint-all
git add src/ui/qt/window.py src/ui/qt/models.py src/ui/qt/widgets tests/test_ui_qt_window.py tests/test_ui_qt_application.py
git commit -m "feat(qt): меню строк, кнопка «Добавить», подписки в дереве, журнал в панели"
```

---

### Task 9: Документация

**Files:**
- Modify: `CLAUDE.md`, `AGENTS.md`
- Modify: `docs/ru/development.md`, `docs/en/development.md`
- Modify: `docs/plans/2026-10-28-windows-qt-frontend-design.md`
- Modify: этот план (раздел «Статус»)

**Step 1:** `CLAUDE.md`, абзац **Qt-интерфейс** в «GUI Architecture» дополнить:

```markdown
Диалоги — `src/ui/qt/dialogs/` (формы, подтверждения, «VPN и маршруты»,
окно настроек со списком подписок); проверка полей — та же
`src/ui/logic/`, что у GTK. Действия над строками дерева (`edit-profile`,
`delete-group`…) адресуют профиль или группу числом. Диалоги идут по
одному через `QtApplication.show_dialog`; формы, открытые из настроек,
кладутся поверх них
```

**Step 2:** `AGENTS.md`, строку про `src/ui/qt/` заменить на:

```markdown
- `src/ui/qt/` — интерфейс PySide6 (Windows; на Linux — `gui.py --ui qt`);
  `src/ui/qt/dialogs/` — формы и окно настроек.
```

**Step 3:** `docs/ru/development.md`, в раздел «Интерфейс Qt» перед абзацем про Windows:

```markdown
Формы и окно настроек — в `src/ui/qt/dialogs/`; правила проверки полей
общие с GTK и лежат в `src/ui/logic/`. Новое поле настроек добавляется в
обе реализации окна настроек.
```

`docs/en/development.md`, в «Qt Interface»:

```markdown
Forms and the settings window live in `src/ui/qt/dialogs/`; field
validation is shared with GTK in `src/ui/logic/`. A new setting goes into
both settings windows.
```

**Step 4:** Дизайн-документ: после «Уточнение по итогам фазы 1» добавить абзац «Уточнение по итогам фазы 3» и кратко перечислить в нём решения фазы:
- окно настроек модальное, формы из него открываются поверх;
- иконки — `QIcon.ThemeIcon`, а не свой словарь глифов;
- `SHORTCUTS` живёт в `src/ui/qt/dialogs/shortcuts.py`;
- файлы диалогов называются по таблице «Решения фазы».

В структуре `src/ui/qt/` из раздела «Фронтенд Qt» заменить список `dialogs/` на фактический.

**Step 5:** В конец этого плана — раздел «Статус» с датой, числами тестов до и после и отклонениями.

**Step 6: Commit**

```bash
python cli.py lint-all
uv run pytest -q --no-cov -p no:cacheprovider
git add CLAUDE.md AGENTS.md docs/
git commit -m "docs: диалоги и окно настроек Qt-интерфейса, статус фазы 3"
```

---

### Task 10: Проверка на Linux и на VM Windows 10 и 11

Проверка руками; результат — в раздел «Статус».

**Linux (`python gui.py --ui qt`, режим системного прокси, не TUN):**

1. Ctrl+N — «Добавить профиль»: ссылка из буфера кнопкой «Вставить», имя подставляется, «Добавить» — профиль в дереве, тост.
2. «Добавить ▾» → «Профиль из буфера обмена», «Подписка…», «Группа…».
3. Правый клик по профилю: «Редактировать» (применить другую ссылку, «Отмена» — профиль прежний), «VPN и маршруты…» (правка списков, закрыть — сохранено, неверная запись подсвечена), «Тест задержки», «Удалить» (Enter — отмена).
4. Правый клик по группе: «Свернуть группу» и «Развернуть группу», «Тест задержки» (прогресс «готово / всего»), «Оставить рабочие…», «Редактировать», «Удалить».
5. Ctrl+, — настройки. Пройти все разделы; неверный адрес DNS подсвечен и не сохраняется; тема «Тёмная» применяется сразу; «Закрыть» — правки в `settings.json`.
6. «Подписки» в настройках: «Добавить…», «Обновить» (тост «Обновляю: …»), «Изменить…» поверх настроек, «Удалить», «Ещё» — страница провайдера и объявление.
7. «О программе» в настройках: «Проверить» для приложения и ядра, «Обновить» геобазы, «Очистить» журналы.
8. ☰ → «Сочетания клавиш», «О программе» → «Копировать сведения».
9. Панель «Мониторинг»: журнал обновляется, «Экспорт…» сохраняет файл без секретов; скрыть панель, перезапустить — панель скрыта.
10. Снять «Сворачивать в трей», закрыть окно — приложение завершается.
11. Импорт маршрутизации ссылкой: `python gui.py --ui qt 'veblock://…'` (на Windows — вторым запуском при открытом приложении). Открывается окно «Импорт маршрутизации», «Импортировать», тост «Вернуть»; «Вернуть» откатывает списки.

**VM Windows 10 и 11 (из исходников, как в задаче 11 фазы 2):**

1. Пункты 1–10 выше.
2. Иконки кнопок «Вставить» и «Копировать» — системные глифы, а не текст.
3. Диалоги в стиле системы, тёмная тема распространяется и на них.
4. DPI 150 %: флаг в карточке и в дереве не размыт.
5. «Экспорт…» — системное окно сохранения файла.
6. Открытые вопросы фазы 2 (AppUserModelID, перезапуск Проводника) — если не закрыты.

---

## Что намеренно не делается в этой фазе

- PyInstaller spec, Inno Setup, `windows.yml`, удаление Win32-трея, `style-windows.css`, `assets/flags/win/*.bmp` и Windows-веток `platform_layout.py` — фаза 4.
- AppUserModelID — по итогам проверки на VM.
- Перевод GTK-окна настроек и GTK-справки сочетаний на общие с Qt списки: GTK не трогается, кроме переноса констант в задаче 1.

## Статус

**28.10.2026 — задачи 0–9 выполнены, задача 10 частично.**

Код взят из плана без отступлений; коммиты `71c591e`…`fb1aaf4` и
документация.

| Прогон | До фазы | После |
|---|---|---|
| `uv run pytest` | 1587 passed, 10 skipped | 1590 passed, 10 skipped (+3 теста задачи 1) |
| `make test-gtk` | 279 passed | 279 passed |
| `make test-tray` | 146 passed, 5 skipped | 146 passed, 5 skipped |
| `make test-qt` | 50 passed | 137 passed |
| `python cli.py lint-all` | чисто | чисто |

Задача 10, сделано в offscreen на Linux:
- `gui.py --ui qt --no-tray` с отдельным каталогом настроек стартует и
  завершается по SIGINT: в журнале `Frontend: qt` и `Lock released`,
  предупреждений и ошибок нет;
- пункт 11: ссылка `veblock://routing/add/…` открывает «Импорт
  маршрутизации» (строки «Профиль», «Через прокси», «Напрямую»,
  «Блокировать», «Остальное», «Не переносится»), «Импортировать» заменяет
  списки и показывает тост «Вернуть», «Вернуть» возвращает прежние списки;
- снимки главного окна, настроек («Общие», «Подписки», «О программе») и
  «VPN и маршруты» совпадают с ожидаемыми в шаге 5 задачи 8.

Не сделано, остаётся за разработчиком:
- Linux, пункты 1–10 на живом дисплее. Подключение не проверялось: на машине
  разработчика работает TUN-сессия, системный прокси не менялся;
- проверка на VM Windows 10 и 11 целиком, вместе с ручной частью задачи 11
  фазы 2.
