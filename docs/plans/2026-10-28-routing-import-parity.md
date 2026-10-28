# Импорт маршрутизации: откат и читаемое подтверждение — план реализации

> **Для исполнителя:** использовать навык `superpowers:executing-plans`, выполнять задачи последовательно, TDD: сначала падающий тест.

**Цель:** перенести из Android 1.4.9 то, чего нет в десктопе: откат «Вернуть настройки до импорта», окно подтверждения со строками «подпись — значение» и строкой «Остальное», точные `full:`/`domain:` для заглавных и кириллических доменов.

**Архитектура:** решения об импорте (действующие списки до импорта, строки окна, применение, резервная копия, откат) — в GTK-независимом `src/ui/logic/routing_import.py`, тестируются обычным pytest. Копия хранится в `settings.json` полем `DataStore.routing_backup` и пишется тем же атомарным сохранением, что и импорт. GTK-часть: построитель окна, действие `app.restore-routing`, toast с кнопкой «Вернуть» и строка в настройках.

**Стек:** Python 3.11+, GTK 4, libadwaita 1.5, pytest, ruff.

**База:** desktop `a62c3b2` (0.19.1), Android `59f85446` (1.4.9), 28.10.2026. Пути Android — относительно `../tenga-proxy-android/`.

---

## Что уже есть и что не переносим

- Punycode, сжатые IPv6 и `full:` в целом проходят: `classify_routing_entry` и
  `normalize_routing_entry` используют `ipaddress` и IDNA (ошибки Android 1.4.9
  здесь нет). Найдены две мелочи, их исправляет задача 1: `full:пример.рф` остаётся
  кириллицей, а `full:Example.COM` — с заглавными; ядро сравнивает правила с
  запрошенным именем в нижнем регистре и в punycode, поэтому такое правило не
  срабатывает.
- `happ://routing/off` **не переносим**: на практике он приходит заголовком `routing`
  подписки, а `src/sub/metadata.py` намеренно не читает ключи, которыми провайдер
  управлял бы настройками клиента. Ссылку `routing/off`, открытую вручную,
  по-прежнему отклоняет `parse_app_link`.
- DNS, VPN, порядок правил и геобазы из ссылки по-прежнему не импортируются.

### Найденная ошибка

Окно импорта считает «было» по `context.config.routing.*_list` в памяти. У старой
установки (`use_saved_lists = False`) списки живут в текстовых файлах и подгружаются
в память только при подключении (`src/core/config_builder.py:162`). До первого
подключения окно показывает «−0», хотя импорт удалит записи из файлов. Задача 3
считает «было» по действующим спискам; тот же снимок становится резервной копией.

---

### Задача 1. `full:` и `domain:` — в нижнем регистре и punycode

**Файлы:**
- Изменить: `src/ui/logic/routing_form.py:52-57` (`normalize_routing_entry`)
- Тест: `tests/test_ui_logic_routing_form.py`, `tests/test_fmt_app_links.py`

**Шаг 1. Падающие тесты.** В `tests/test_ui_logic_routing_form.py`:

```python
import pytest

from src.ui.logic.routing_form import normalize_routing_entry


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("full:Example.COM", "full:example.com"),
        ("domain:Пример.РФ", "domain:xn--e1afmkfd.xn--p1ai"),
        ("full:xn--e1afmkfd.xn--p1ai", "full:xn--e1afmkfd.xn--p1ai"),
        # Регистр регулярного выражения и ключевого слова — часть правила.
        ("regexp:^Api\\.", "regexp:^Api\\."),
        ("keyword:Google", "keyword:Google"),
        ("geosite:category-ru", "geosite:category-ru"),
    ],
)
def test_domain_rules_match_the_name_the_core_compares(raw, expected):
    """Ядро сравнивает правило с именем в нижнем регистре и в punycode."""
    assert normalize_routing_entry(raw) == expected


@pytest.mark.parametrize("raw", ["full:", "full:*.example.com", "domain:bad host"])
def test_malformed_domain_rules_are_rejected(raw):
    with pytest.raises(ValueError):
        normalize_routing_entry(raw)
```

В `tests/test_fmt_app_links.py` — сквозной тест разбора Happ-профиля (формат как у
`test_routing_lists_are_normalized`):

```python
def test_happ_rules_keep_exact_domains_idn_and_compressed_ipv6():
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "DirectSites": ["full:Пример.РФ", "domain:Example.org", "xn--p1ai"],
                "DirectIp": ["2001:db8::1", "2a00:1450::/32"],
            }
        ).encode()
    ).decode()
    link = parse_app_link("happ://routing/add/" + payload)
    assert link.routing.direct_list == [
        "full:xn--e1afmkfd.xn--p1ai",
        "domain:example.org",
        "xn--p1ai",
        "2001:db8::1",
        "2a00:1450::/32",
    ]
```

**Шаг 2.** `uv run pytest tests/test_ui_logic_routing_form.py tests/test_fmt_app_links.py -v` —
ожидаются падения на `full:Example.COM`, `domain:Пример.РФ`, `full:*.example.com`
и в сквозном тесте.

**Шаг 3. Реализация.** В `normalize_routing_entry` выделить `full:`/`domain:` перед
общей веткой префиксов:

```python
    prefix, _, rest = value.partition(":")
    if prefix.lower() in ("full", "domain"):
        try:
            host = rest.lower().encode("idna").decode("ascii")
        except UnicodeError:
            raise ValueError("Некорректное доменное имя") from None
        # Звёздочка — синтаксис голого суффикса, в `full:`/`domain:` она была бы буквой.
        if not re.fullmatch(r"[a-z0-9_.-]+", host) or host.startswith(".") or len(host) > 253:
            raise ValueError("Некорректное правило маршрутизации")
        return f"{prefix.lower()}:{host}"
```

`re` уже импортируется внутри функции — поднять импорт выше нового блока.
Остальные префиксы идут прежней веткой без изменений.

**Шаг 4.** Те же тесты проходят; `uv run pytest tests/test_db_config_routing_entries.py tests/test_ui_dialogs_profile_routing.py -q`
тоже зелёные (форма профиля пользуется той же нормализацией).

**Шаг 5. Коммит:** `fix(routing): full: и domain: в нижнем регистре и punycode — иначе ядро их не сопоставит`.

---

### Задача 2. Имя профиля и «остальное напрямую» в `AppLink`

Сейчас «остальное напрямую» передаётся строкой в `warnings`. Окну нужен флаг, чтобы
вывести его строкой «Остальное», и имя профиля Happ (`Name`).

**Файлы:**
- Изменить: `src/fmt/app_links.py:17-23, 61-94`
- Тест: `tests/test_fmt_app_links.py`

**Шаг 1. Падающие тесты:**

```python
def _routing(fields: dict) -> str:
    return "happ://routing/add/" + base64.urlsafe_b64encode(json.dumps(fields).encode()).decode()


def test_routing_profile_name_is_cleaned_and_bounded():
    link = parse_app_link(_routing({"Name": "RU\x07 direct" + "x" * 100}))
    assert link.name == ("RU direct" + "x" * 100)[:64]


def test_provider_direct_default_is_reported_not_applied():
    link = parse_app_link(_routing({"GlobalProxy": False, "DirectSites": ["example.org"]}))
    assert link.direct_default is True
    assert link.warnings == ()
    assert link.routing.mode == "custom"


def test_non_string_name_is_rejected():
    with pytest.raises(ValueError):
        parse_app_link(_routing({"Name": 5}))
```

В `test_global_proxy_flag_does_not_disable_imported_direct_lists` добавить
`assert link.direct_default is False`.

**Шаг 2.** Тесты падают: нет поля `direct_default`, имя не читается.

**Шаг 3. Реализация.** В `AppLink` добавить `direct_default: bool = False`. Поле
`warnings` удалить: его больше никто не заполняет (проверить
`grep -rn "\.warnings" src tests`). Вместо сборки `warnings` в `parse_app_link`:

```python
    name = fields.get("name", "")
    if not isinstance(name, str):
        raise ValueError("Некорректное имя профиля маршрутизации")
    # Тот же фильтр, что у имени подписки выше: строка придёт в окно как текст.
    name = "".join(c for c in name if ord(c) >= 32 and ord(c) != 127)[:64]
    ...
    return AppLink("routing", name=name, routing=routing, direct_default=not global_proxy)
```

Комментарий о том, что Happ `GlobalProxy` описывает catch-all, сохранить.

**Шаг 4.** `uv run pytest tests/test_fmt_app_links.py -v` — проходят.
`src/ui/application.py` ещё читает `link.warnings` — его меняет задача 4. До неё
`tests/test_ui_application.py::test_routing_import_requires_confirmation` упадёт —
поэтому коммитить задачи 2–4 одним коммитом либо временно оставить
`warnings=()` и убрать его в задаче 4. Выбрать второе: коммиты останутся зелёными.

**Шаг 5. Коммит:** `feat(app-links): имя профиля маршрутизации и флаг «остальное напрямую»`.

---

### Задача 3. Логика импорта без GTK: снимок, строки окна, применение, откат

**Файлы:**
- Создать: `src/ui/logic/routing_import.py`
- Изменить: `src/db/data_store.py:103` (поле `routing_backup`)
- Тест: создать `tests/test_ui_logic_routing_import.py`

**Шаг 1. Падающие тесты:**

```python
"""Импорт общей маршрутизации: что показать, что применить, как откатить."""

from __future__ import annotations

from src.db.config import RoutingMode, RoutingSettings
from src.db.data_store import DataStore
from src.ui.logic.routing_import import (
    ImportRow,
    apply_import,
    effective_routing,
    import_rows,
    restore_backup,
)


def _legacy(tmp_path) -> DataStore:
    """Старая установка: списки в файлах, в памяти их нет до подключения."""
    (tmp_path / "direct_list.txt").write_text("old.example\n", encoding="utf-8")
    return DataStore()


def test_effective_routing_reads_legacy_files_without_touching_config(tmp_path):
    config = _legacy(tmp_path)
    routing = effective_routing(config.routing, tmp_path)
    assert routing.direct_list == ["old.example"]
    assert config.routing.direct_list == []


def test_rows_count_removals_from_legacy_files(tmp_path):
    config = _legacy(tmp_path)
    new = RoutingSettings(direct_list=["new.example"])
    rows = import_rows(effective_routing(config.routing, tmp_path), new, name="", direct_default=False)
    direct = next(r for r in rows if r.label == "Напрямую")
    assert direct.value == "1 правило: +1, −1"
    assert direct.details == ("+ new.example", "− old.example")


def test_rows_name_profile_and_rest_of_traffic():
    rows = import_rows(RoutingSettings(), RoutingSettings(), name="RU", direct_default=False)
    assert rows[0] == ImportRow("Профиль", "RU")
    rest = next(r for r in rows if r.label == "Остальное")
    assert rest == ImportRow("Остальное", "через прокси")


def test_direct_default_request_is_flagged_on_the_rest_row():
    rows = import_rows(RoutingSettings(), RoutingSettings(), name="", direct_default=True)
    assert [r.label for r in rows][0] != "Профиль"
    rest = next(r for r in rows if r.label == "Остальное")
    assert rest.warning
    assert rest.value == (
        "через прокси. Провайдер просил пускать остальное напрямую — "
        "Veblock намеренно это не поддерживает"
    )


def test_mode_row_only_when_mode_changes():
    proxy_all = RoutingSettings(mode=RoutingMode.PROXY_ALL)
    rows = import_rows(proxy_all, RoutingSettings(), name="", direct_default=False)
    assert ImportRow("Режим", "Весь трафик через прокси → Пользовательские списки") in rows
    rows = import_rows(RoutingSettings(), RoutingSettings(), name="", direct_default=False)
    assert all(r.label != "Режим" for r in rows)


def test_details_are_bounded():
    new = RoutingSettings(proxy_list=[f"h{i}.example" for i in range(30)])
    rows = import_rows(RoutingSettings(), new, name="", direct_default=False)
    proxy = next(r for r in rows if r.label == "Через прокси")
    assert len(proxy.details) == 11
    assert proxy.details[-1] == "и ещё 20"


def test_apply_keeps_a_backup_and_restore_returns_it(tmp_path):
    config = _legacy(tmp_path)
    config.routing.ru_direct = True
    apply_import(config, RoutingSettings(direct_list=["new.example"]), tmp_path)

    assert config.routing.direct_list == ["new.example"]
    assert config.routing.use_saved_lists
    assert config.routing.ru_direct  # то, чего нет в ссылке, импорт не трогает
    assert config.routing_backup.direct_list == ["old.example"]
    assert not config.routing_backup.use_saved_lists

    assert restore_backup(config)
    assert config.routing.direct_list == ["old.example"]
    assert not config.routing.use_saved_lists  # снова читаются файлы
    assert config.routing_backup is None
    assert not restore_backup(config)


def test_second_import_keeps_only_the_latest_backup(tmp_path):
    config = DataStore()
    apply_import(config, RoutingSettings(direct_list=["a.example"]), tmp_path)
    apply_import(config, RoutingSettings(direct_list=["b.example"]), tmp_path)
    assert config.routing_backup.direct_list == ["a.example"]


def test_backup_survives_settings_round_trip(tmp_path):
    config = DataStore()
    apply_import(config, RoutingSettings(block_list=["ads.example"]), tmp_path)
    config.save(tmp_path / "settings.json")
    loaded = DataStore.load(tmp_path / "settings.json")
    assert isinstance(loaded.routing_backup, RoutingSettings)
    assert DataStore.load(tmp_path / "missing.json").routing_backup is None
```

**Шаг 2.** `uv run pytest tests/test_ui_logic_routing_import.py -v` — `ImportError`.

**Шаг 3. Реализация.**

`src/db/data_store.py`, сразу после `routing`:

```python
    # Общая маршрутизация до последнего импорта ссылкой: один уровень отката.
    routing_backup: RoutingSettings | None = None
```

`src/ui/logic/routing_import.py`:

```python
"""Импорт общей маршрутизации ссылкой: что показать, что применить, как откатить.

GTK не импортирует: окно строит `src/ui/dialogs/routing_import.py`.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from src.db.config import RoutingMode, RoutingSettings

# Из ссылки переносятся только эти списки; остальное — настройки устройства.
IMPORTED_LISTS = (("proxy_list", "Через прокси"), ("direct_list", "Напрямую"), ("block_list", "Блокировать"))
_DETAILS_LIMIT = 10


@dataclass(frozen=True)
class ImportRow:
    label: str
    value: str
    details: tuple[str, ...] = ()
    warning: bool = False


def effective_routing(routing: RoutingSettings, config_dir: Path | None) -> RoutingSettings:
    """Списки, с которыми подключилось бы ядро, — копией, без правки настроек.

    У старой установки списки живут в текстовых файлах и попадают в память
    только при подключении: без этого окно обещало бы «−0» перед удалением.
    """
    result = copy.deepcopy(routing)
    if config_dir is not None and result.mode == RoutingMode.CUSTOM and not result.use_saved_lists:
        result.load_lists_from_files(config_dir)
    return result


def _rules(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        word = "правило"
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        word = "правила"
    else:
        word = "правил"
    return f"{count} {word}"


def _list_row(label: str, before: list[str], after: list[str]) -> ImportRow:
    old, new = set(before), set(after)
    changes = [f"+ {v}" for v in after if v not in old] + [f"− {v}" for v in before if v not in new]
    added, removed = len(new - old), len(old - new)
    details = changes[:_DETAILS_LIMIT]
    if len(changes) > _DETAILS_LIMIT:
        details.append(f"и ещё {len(changes) - _DETAILS_LIMIT}")
    return ImportRow(label, f"{_rules(len(after))}: +{added}, −{removed}", tuple(details))


def import_rows(
    before: RoutingSettings, after: RoutingSettings, *, name: str, direct_default: bool
) -> list[ImportRow]:
    rows = [ImportRow("Профиль", name)] if name else []
    if before.mode != after.mode:
        labels = RoutingMode.LABELS
        rows.append(ImportRow("Режим", f"{labels[before.mode]} → {labels[after.mode]}"))
    for key, label in IMPORTED_LISTS:
        rows.append(_list_row(label, getattr(before, key), getattr(after, key)))
    if direct_default:
        rows.append(
            ImportRow(
                "Остальное",
                "через прокси. Провайдер просил пускать остальное напрямую — "
                "Veblock намеренно это не поддерживает",
                warning=True,
            )
        )
    else:
        rows.append(ImportRow("Остальное", "через прокси"))
    rows.append(ImportRow("Не переносится", "DNS, VPN, порядок правил и адреса геобаз"))
    return rows


def apply_import(config, new: RoutingSettings, config_dir: Path | None) -> None:
    """Заменить списки из ссылки, запомнив прежнюю маршрутизацию для отката."""
    config.routing_backup = effective_routing(config.routing, config_dir)
    routing = config.routing
    routing.mode = new.mode
    routing.use_saved_lists = True
    for key, _label in IMPORTED_LISTS:
        setattr(routing, key, list(getattr(new, key)))


def restore_backup(config) -> bool:
    """Вернуть маршрутизацию до последнего импорта; False — возвращать нечего."""
    backup = config.routing_backup
    if backup is None:
        return False
    config.routing = backup
    config.routing_backup = None
    return True
```

Почему копия хранит `use_saved_lists` как было: импорт не трогает текстовые файлы,
поэтому после отката старая установка снова читает их, а не замороженный снимок.
Ruff может попросить перенести длинный `IMPORTED_LISTS` на несколько строк —
`python cli.py format`.

**Шаг 4.** `uv run pytest tests/test_ui_logic_routing_import.py -v` — проходят.
Проверить, что модуль не тянет GTK:
`uv run python -c "import sys, src.ui.logic.routing_import; assert 'gi' not in sys.modules"`
из корня проекта.

**Шаг 5. Коммит:** `feat(routing): резервная копия маршрутизации перед импортом и строки окна импорта`.

---

### Задача 4. Окно импорта «подпись — значение»

**Файлы:**
- Создать: `src/ui/dialogs/routing_import.py`
- Изменить: `src/ui/application.py:196-224` (ветка `else` в `import_app_link`)
- Тест: `tests/test_ui_application.py` (маркер `gtk`)

**Шаг 1. Падающие тесты.** Заменить `test_routing_import_requires_confirmation`
и добавить новые:

```python
def _routing_link(fields):
    import base64
    import json

    return "happ://routing/add/" + base64.urlsafe_b64encode(json.dumps(fields).encode()).decode()


def test_routing_import_requires_confirmation(adw_app):
    adw_app.activate()
    before = list(adw_app.context.config.routing.direct_list)
    adw_app.import_app_link(_routing_link({"DirectSites": ["example.org"], "GlobalProxy": False}))
    assert adw_app.context.config.routing.direct_list == before
    adw_app.current_dialog.emit("response", "import")
    assert adw_app.context.config.routing.direct_list == ["example.org"]
    assert adw_app.context.config.routing_backup is not None
    assert not adw_app.context.proxy_state.is_running


def test_routing_import_dialog_lists_rows(adw_app):
    adw_app.activate()
    adw_app.import_app_link(_routing_link({"Name": "RU", "GlobalProxy": False}))
    dialog = adw_app.current_dialog
    assert dialog.row_titles() == [
        "Профиль", "Через прокси", "Напрямую", "Блокировать", "Остальное", "Не переносится"
    ]
    assert dialog.rest_row.has_css_class("error")


def test_routing_import_cancel_changes_nothing(adw_app):
    adw_app.activate()
    adw_app.import_app_link(_routing_link({"DirectSites": ["example.org"]}))
    adw_app.current_dialog.emit("response", "cancel")
    assert adw_app.context.config.routing.direct_list == []
    assert adw_app.context.config.routing_backup is None
```

**Шаг 2.** `GDK_BACKEND=x11 make test-gtk` (или
`dbus-run-session -- xvfb-run -a uv run pytest -m gtk tests/test_ui_application.py -k routing -v`) —
падает: нет ответа `import`, нет `row_titles`.

**Шаг 3. Реализация.** `src/ui/dialogs/routing_import.py`:

```python
"""Подтверждение импорта общей маршрутизации."""

from __future__ import annotations

from collections.abc import Callable

from gi.repository import Adw, Gtk

from src.ui.logic.routing_import import ImportRow

CANCEL = "cancel"
IMPORT = "import"


class RoutingImportDialog(Adw.AlertDialog):
    """Строки «подпись — значение»; применяет только ответ «Импортировать»."""

    __gtype_name__ = "TengaRoutingImportDialog"

    def __init__(self, rows: list[ImportRow], on_confirm: Callable[[], None]) -> None:
        super().__init__(
            heading="Импорт маршрутизации",
            body="Текущие списки будут заменены. Вернуть их можно в настройках, "
            "раздел «О приложении» → «Обслуживание».",
        )
        self._titles: list[str] = []
        self.rest_row = None
        box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add_css_class("boxed-list")
        for row in rows:
            box.append(self._build_row(row))
        self.set_extra_child(box)

        self.add_response(CANCEL, "Отмена")
        self.add_response(IMPORT, "Импортировать")
        self.set_response_appearance(IMPORT, Adw.ResponseAppearance.SUGGESTED)
        self.set_default_response(CANCEL)
        self.set_close_response(CANCEL)
        self.connect("response", lambda _d, response: on_confirm() if response == IMPORT else None)

    def _build_row(self, row: ImportRow) -> Adw.PreferencesRow:
        # Значения приходят из ссылки: только текст, без разметки.
        if row.details:
            widget = Adw.ExpanderRow(title=row.label, subtitle=row.value)
            widget.set_use_markup(False)
            for line in row.details:
                child = Adw.ActionRow(title=line)
                child.set_use_markup(False)
                widget.add_row(child)
        else:
            widget = Adw.ActionRow(title=row.label, subtitle=row.value)
            widget.set_use_markup(False)
            widget.set_subtitle_lines(0)
        if row.warning:
            widget.add_css_class("error")
        if row.label == "Остальное":
            self.rest_row = widget
        self._titles.append(row.label)
        return widget

    def row_titles(self) -> list[str]:
        return list(self._titles)
```

Ответ — «Импортировать» с `SUGGESTED`, а не `build_delete_confirmation` с
`DESTRUCTIVE`: импорт обратим откатом. По умолчанию по-прежнему «Отмена».

В `import_app_link` ветку `else` заменить на:

```python
        else:
            from src.ui.dialogs.routing_import import RoutingImportDialog
            from src.ui.logic.routing_import import effective_routing, import_rows

            config, config_dir = self.context.config, self.context.config_dir
            rows = import_rows(
                effective_routing(config.routing, config_dir),
                link.routing,
                name=link.name,
                direct_default=link.direct_default,
            )
            self.present_dialog(
                RoutingImportDialog(rows, lambda: self._apply_routing_import(link.routing))
            )
```

и добавить метод рядом с `apply_settings`:

```python
    def _apply_routing_import(self, routing) -> None:
        from src.ui.logic.routing_import import apply_import

        apply_import(self.context.config, routing, self.context.config_dir)
        if self.apply_settings():
            self._sync_restore_routing()
            self.toast("Маршрутизация импортирована", button="Вернуть", action="app.restore-routing")
```

`_sync_restore_routing` и `toast(..., button=, action=)` появятся в задаче 5 — до
неё вызывать `self.toast("Маршрутизация импортирована")`. Убрать `warnings=()`,
оставленное в задаче 2, и неиспользуемый импорт `build_confirmation`.
`AppContext.config_dir` уже есть (`src/core/context.py:101`).

**Шаг 4.** GTK-тесты из шага 1 проходят; `uv run pytest -q` зелёный.
Снимок окна на синтетической ссылке — в `docs/screenshots/2026-10-28-routing-import.png`
для проверки раскладки (длинное значение «Остальное» должно переноситься, а не
растягивать окно).

**Шаг 5. Коммит:** `feat(ui): окно импорта маршрутизации — строки «подпись — значение» и «Остальное»`.

---

### Задача 5. Откат: действие, toast с кнопкой, строка в настройках

**Файлы:**
- Изменить: `src/ui/application.py` (`_register_actions`, `toast`, новые методы)
- Изменить: `src/ui/window.py:586-588` (`toast`)
- Изменить: `src/ui/dialogs/settings.py:386-397` (группа «Обслуживание»)
- Тест: `tests/test_ui_application.py`, `tests/test_ui_dialogs_settings.py`

**Шаг 1. Падающие тесты.** В `tests/test_ui_application.py`:

```python
def test_restore_routing_returns_lists_before_import(adw_app):
    adw_app.activate()
    adw_app.context.config.routing.direct_list = ["old.example"]
    adw_app.context.config.routing.use_saved_lists = True
    action = adw_app.lookup_action("restore-routing")
    assert not action.get_enabled()

    adw_app.import_app_link(_routing_link({"DirectSites": ["new.example"]}))
    adw_app.current_dialog.emit("response", "import")
    assert action.get_enabled()
    assert adw_app.last_toast_for_test == "Маршрутизация импортирована"

    adw_app.activate_action("restore-routing", None)
    assert adw_app.context.config.routing.direct_list == ["old.example"]
    assert adw_app.context.config.routing_backup is None
    assert not action.get_enabled()
    assert adw_app.last_toast_for_test == "Маршрутизация до импорта возвращена"


def test_restore_routing_is_persisted(adw_app):
    from src.db.data_store import DataStore

    adw_app.activate()
    adw_app.import_app_link(_routing_link({"DirectSites": ["new.example"]}))
    adw_app.current_dialog.emit("response", "import")
    adw_app.activate_action("restore-routing", None)
    saved = DataStore.load(adw_app.context.config_dir / "settings.json")
    assert saved.routing_backup is None
    assert saved.routing.direct_list == []
```

В `tests/test_ui_dialogs_settings.py` (по образцу тестов `clear_logs_row`):

```python
def test_restore_routing_row_follows_backup(tmp_path):
    from src.core.context import AppContext
    from src.db.config import RoutingSettings
    from src.ui.dialogs.settings import SettingsDialog

    context = AppContext(config_dir=tmp_path)
    assert not SettingsDialog(context.config, context).restore_routing_row.get_visible()
    context.config.routing_backup = RoutingSettings()
    dialog = SettingsDialog(context.config, context)
    assert dialog.restore_routing_row.get_visible()
    assert dialog.restore_routing_button.get_action_name() == "app.restore-routing"
```

**Шаг 2.** Тесты падают: нет действия и строки.

**Шаг 3. Реализация.**

`_register_actions`: добавить `"restore-routing": self.restore_routing` в `handlers`;
после цикла — `self._sync_restore_routing()`.

```python
    def restore_routing(self) -> None:
        """Вернуть общую маршрутизацию до последнего импорта ссылкой."""
        from src.ui.logic.routing_import import restore_backup

        if not restore_backup(self.context.config):
            return
        if self.apply_settings():
            self.toast("Маршрутизация до импорта возвращена")
        self._sync_restore_routing()

    def _sync_restore_routing(self) -> None:
        action = self.lookup_action("restore-routing")
        if action is not None:
            action.set_enabled(self.context.config.routing_backup is not None)
```

Вызывать `_sync_restore_routing()` и в `reset_for_tests`
(`src/ui/application.py:1173`) после смены контекста, иначе состояние действия
перетечёт между тестами. Действия регистрируются, когда конфигурация уже загружена;
проверить это по месту вызова `_register_actions`.

`toast` в приложении и окне — необязательная кнопка:

```python
    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None:
        self.last_toast_for_test = text
        if self._window is not None:
            self._window.toast(text, button=button, action=action)
```

```python
    def toast(self, text: str, *, button: str | None = None, action: str | None = None) -> None:
        """Show a transient message over the content."""
        toast = Adw.Toast(title=text)
        if button and action:
            toast.set_button_label(button)
            toast.set_action_name(action)
        self.toast_overlay.add_toast(toast)
```

Кнопка toast без подтверждения — обычная отмена по HIG. Строка в настройках тоже
без подтверждения, как в Android: откат меняет только списки, которые пользователь
сам только что заменил.

`SettingsDialog._build_about_page`, в группу «Обслуживание» перед `clear_logs_row`:

```python
        self.restore_routing_row = Adw.ActionRow(
            title="Маршрутизация до импорта",
            subtitle="Вернёт режим и списки, которые были до последнего импорта ссылкой",
        )
        self.restore_routing_button = Gtk.Button(
            label="Вернуть", valign=Gtk.Align.CENTER, action_name="app.restore-routing"
        )
        self.restore_routing_row.add_suffix(self.restore_routing_button)
        self.restore_routing_row.set_visible(getattr(self._config, "routing_backup", None) is not None)
        actions.add(self.restore_routing_row)
```

После нажатия строка остаётся видимой, но кнопка гаснет вместе с действием — этого
достаточно; скрывать строку на лету не нужно.

**Шаг 4.** `GDK_BACKEND=x11 make test-gtk` — зелёные; `make test` — зелёный.

**Шаг 5. Коммит:** `feat(ui): «Вернуть» маршрутизацию до импорта — в уведомлении и в настройках`.

---

### Задача 6. Документация

**Файлы:**
- Изменить: `docs/ru/routing.md:172-190` («Импорт и проверка правил»)

Дописать абзацем, без маркетинга:

- `full:` и `domain:` приводятся к нижнему регистру и punycode — так их сравнивает ядро.
- Окно показывает имя профиля, число правил и изменения по каждому списку, строку
  «Остальное: через прокси»; при `GlobalProxy=false` в ней же сказано, что этот
  режим не поддерживается.
- Перед импортом прежняя маршрутизация сохраняется в settings.json (`routing_backup`,
  один уровень). Вернуть: кнопка «Вернуть» в уведомлении или «Настройки → О приложении →
  Обслуживание → Маршрутизация до импорта». Старая установка после отката снова
  читает текстовые файлы списков.
- `happ://routing/off` и заголовок `routing` подписки не поддерживаются.

**Коммит:** `docs(routing): откат импорта и строки окна подтверждения`.

---

## Итоговая приёмка

1. `make lint`, `make format-check`, `git diff --check`.
2. `make test` (без GTK), `GDK_BACKEND=x11 make test-gtk`, `make test-tray` — все зелёные.
3. Вручную на изолированной конфигурации, не на рабочей:
   `TENGA_CONFIG_DIR=$(mktemp -d) python gui.py`, затем открыть синтетическую
   ссылку `veblock://routing/add/<base64>` вторым запуском `python gui.py <ссылка>`.
   Проверить окно, импорт, toast «Вернуть», строку в настройках после перезапуска.
   **Не подключаться в режиме TUN**: на машине разработчика интерфейс `xray0`
   занят рабочим подключением.
4. Сверить с Android: `app/src/main/java/com/wingeon/app/ui/component/RoutingImportDialog.kt`,
   строки `routing_import_*` в `app/src/main/res/values-ru/strings.xml`.
