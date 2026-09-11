# Этап 5: удаление GTK3, сборка, документация, слияние

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
> Дизайн: `docs/plans/2026-09-02-ui-redesign-design.md`. Общий план: `docs/plans/2026-09-02-ui-redesign-plan.md` (раздел «Этап 5»).

**Goal:** Сделать GTK4-интерфейс единственным: удалить GTK3-код и флаг `--gtk4`, вернуть пакетам исторические имена (`dialogs4` → `dialogs`, `tray4` → `tray`), обновить сборку AppImage и документацию под GTK4/libadwaita, закрыть перенесённые дефекты и слить ветку.

**Architecture:** Удаление идёт снизу вверх: сначала уходят зависящие от GTK3 тесты и модули, затем `gui.py` перестаёт выбирать версию, затем переименовываются пакеты. Единственность экземпляра переходит на `Gio.Application` (D-Bus), а самописный Unix-сокет удаляется — файловая блокировка остаётся страховкой от двух xray. Сборка и документация правятся последними, когда состав `src/ui` окончателен.

**Tech Stack:** Python 3.11, PyGObject, GTK 4.14, libadwaita 1.5, Gio.DBus, pytest, ruff, uv, appimagetool.

---

## Уточнения после разведки кода

Проверено чтением кода 2026-09-02, до начала работ:

1. **GTK3 остался ровно в 10 файлах:** `src/ui/app.py`, `src/ui/main_window.py`,
   `src/ui/style.py`, `src/ui/tray.py` и шесть модулей `src/ui/dialogs/`
   (`add_profile`, `edit_group`, `edit_profile`, `settings`, `subscription`,
   `profile_vpn_settings`). Плюс ветка `else` в `gui.py:97-101`.

2. **Пять тестовых файлов импортируют GTK3-модули:**
   `test_ui_app_latency_flow.py`, `test_ui_app_signals.py`,
   `test_ui_dialog_validation_loops.py`, `test_ui_profile_edit_link.py`,
   `test_ui_subscription_flow.py`. Все пять удаляются вместе с кодом, но
   **перед удалением надо проверить, что покрытие не теряется** — разбор ниже.

3. **Покрытие удаляемых тестов уже есть в GTK4-тестах:**
   - `test_ui_profile_edit_link.py` (14 тестов замены ссылки) →
     `test_ui_dialogs_edit_profile.py` покрывает те же сценарии
     (`test_applying_a_new_link_refreshes_the_fields`,
     `test_a_broken_link_is_rejected_and_changes_nothing`,
     `test_a_pending_bean_is_not_written_before_saving`,
     `test_saving_applies_the_pending_bean`,
     `test_applying_a_link_twice_keeps_the_last_one`).
   - `test_ui_dialog_validation_loops.py` (B7: диалог не закрывается при
     ошибке) → `test_ui_logic_forms.py` + `test_ui_dialogs_add_profile.py`
     (кнопка неактивна, пока ссылка не разобрана — сильнее старого требования).
   - `test_ui_app_signals.py` → `test_ui_application.py` уже проверяет
     `GLib.unix_signal_add` для GTK4-приложения.
   - `test_ui_subscription_flow.py`, часть про фоновую ошибку →
     `test_sub_updater*.py` покрывает `SubscriptionUpdater`; часть про
     диалог → `test_ui_dialogs_subscription.py`.
   - `test_ui_app_latency_flow.py`: три теста из четырёх проверяют
     `_create_latency_test_config` и `test_profile_latency` **из GTK3-класса
     `TengaApp`**. У GTK4 своя реализация — `build_latency_probe_config`
     (`src/core/config_builder.py:665`) плюс `_default_latency_probe`
     (`src/ui/application.py:482`). Первая покрыта `test_core_config_builder.py`,
     вторая — **нет**. Перед удалением файла нужен тест на
     `_default_latency_probe` (задача 5.2), иначе покрытие реально теряется.

4. **Единственность экземпляра уже дублируется.** `TengaApplication`
   создаётся с `application_id="ru.tenga.Proxy"` и `DEFAULT_FLAGS`, то есть
   `Gio.Application` сам делает D-Bus-единственность и вызывает `activate`
   у первого процесса. Параллельно `gui.py:152` зовёт
   `single_instance.send_activation_signal()` через Unix-сокет, а сокет-сервер
   обслуживается только в GTK3-`app.py:108-114`. После удаления GTK3 сокет
   становится мёртвым кодом: сервер никто не поднимает, клиент всегда получает
   отказ. Удаляется (закрывает B20 окончательно).

5. **`src/ui/__init__.py` содержит ленивый реэкспорт GTK3** (`__getattr__` →
   `src.ui.app`) с комментарием, что это временно, пока сосуществуют два
   интерфейса. После удаления файл сводится к докстроке.

6. **libnotify нигде не используется.** `grep -n "Notify" src/ui/*.py` даёт
   единственное совпадение — `notify::visible-child-name`, это сигнал GObject,
   не libnotify. Значит `gir1.2-notify-0.7` можно убрать из всех списков
   зависимостей, а не только заменить appindicator на adw.

7. **Зависимости прописаны в шести местах:** `README.md:319-321`,
   `docs/ru/installation.md:114-116`, `docs/en/installation.md:114-116`,
   `core/scripts/install_dev.sh:127-138`, лаунчер внутри
   `core/scripts/build_appimage.sh` (проверка `check_deps`, строки с
   `gir1.2-gtk-3.0`), и текст ошибки импорта в `gui.py:174`.

8. **`build_appimage.sh` не копирует `assets/icons/`.** Он копирует `assets`
   целиком (`cp -r "$PROJECT_ROOT/assets"`), так что SVG трея попадают в
   бандл — но по пути `usr/share/tenga-proxy/assets/icons`, который и
   возвращает `icons_directory()` (`BUNDLE_DIR / "assets" / "icons"`).
   Отдельное копирование в `hicolor/symbolic/apps` **не нужно**: трей отдаёт
   панели `IconThemePath`, а не полагается на системную тему. Отклонение от
   задачи 5.2 общего плана — записать в результатах.

9. **`APP_VERSION` в `build_appimage.sh` захардкожен** (`0.12.1`) и совпадает
   с `src/__init__.py`. `bump_version.sh` его обновляет — проверить, что
   обновит и после правок.

10. **`assets/main-screen.png` — скриншот старого GTK3-окна.** Замена требует
    запуска нового окна; снимать через `import -window <id>`, найденный
    `xwininfo -root -tree` (под XWayland `import -window root` не работает).

11. **Дефект наложения диалогов, отложенный с этапа 4:** шесть методов
    `_open_*` в `src/ui/application.py:372-428` и пять `_row_*` в
    `src/ui/window.py:236-334` создают диалог и зовут `present()` без
    проверки, открыт ли уже другой. Повторное нажатие Ctrl+N кладёт второй
    диалог поверх первого. Чинится в задаче 5.7.

12. **`docs/ru/gui.md` и `docs/en/gui.md` описывают вкладки и трей в общих
    словах** и почти не расходятся с новым UI. Правки точечные: раздел
    настроек, сочетания клавиш, состояния иконки трея.

## Ограничения этапа

- **Основное приложение пользователя работает.** Его нельзя закрывать,
  отключать, а также нельзя проверять подключение и отключение профилей.
  Всё живое тестирование — только на копии конфигурации в скретчпаде через
  `TENGA_CONFIG_DIR`, и только на чтение.
- **AppImage собирается, но не устанавливается в систему** (`cli.py install`
  заменил бы работающее приложение). Проверка — запуск собранного AppImage с
  отдельным `TENGA_CONFIG_DIR`, окно открывается и закрывается.
- Реальный конфиг пользователя (130 профилей, реальные ссылки подписок)
  в коммиты не попадает.
- Слияние в `develop` — только после явного согласия владельца.

---

## Порядок задач

| Задача | Содержание | Коммит |
|--------|------------|--------|
| 5.1 | Тест на `_default_latency_probe` (закрыть дыру покрытия) | `test:` |
| 5.2 | Удаление GTK3-кода и его тестов | `refactor!:` |
| 5.3 | `gui.py` без `--gtk4` | `refactor!:` |
| 5.4 | Единственность экземпляра через Gio | `refactor:` |
| 5.5 | `dialogs4` → `dialogs`, `tray4` → `tray` | `refactor:` |
| 5.6 | Сборка AppImage под GTK4 | `build:` |
| 5.7 | Один диалог за раз | `fix:` |
| 5.8 | Документация | `docs:` |
| 5.9 | Скриншот главного окна | `docs:` |
| 5.10 | Паритет, версия 0.13.0, результаты | `chore:` |

---

### Task 5.1: Тест на `_default_latency_probe`

Закрывает дыру покрытия из находки 3: единственная непокрытая часть
GTK3-теста `test_ui_app_latency_flow.py`.

**Files:**
- Modify: `tests/test_ui_application.py`

**Step 1: Write the failing test**

Фикстура приложения в этом файле называется `adw_app`, весь файл идёт под
`pytestmark = pytest.mark.gtk`. `XrayManager` импортируется внутри
`_default_latency_probe`, поэтому патчится по месту определения.

В конец `tests/test_ui_application.py`:

```python
class _FakeManager:
    """Стоит вместо XrayManager: замер не должен поднимать настоящий процесс."""

    instances: list[_FakeManager] = []

    def __init__(self, binary_path=None):
        self.binary_path = binary_path
        self.stopped = False
        self.started_with = None
        _FakeManager.instances.append(self)

    def start(self, config):
        self.started_with = config
        return True, ""

    def test_delay_realistic(self, proxy_address, proxy_port, **kwargs):
        return 42

    def stop(self):
        self.stopped = True


@pytest.fixture
def fake_xray(monkeypatch):
    _FakeManager.instances = []
    monkeypatch.setattr("src.core.xray_manager.XrayManager", _FakeManager)
    return _FakeManager


def _first_profile_id(adw_app) -> int:
    ids = list(adw_app.context.profiles.profiles)
    assert ids, "фикстура приложения должна давать хотя бы один профиль"
    return ids[0]


def test_default_latency_probe_measures_through_a_temporary_xray(adw_app, fake_xray):
    profile_id = _first_profile_id(adw_app)

    assert adw_app._default_latency_probe(profile_id) == 42
    assert len(fake_xray.instances) == 1
    assert fake_xray.instances[0].stopped is True


def test_default_latency_probe_returns_minus_one_for_a_missing_profile(adw_app, fake_xray):
    assert adw_app._default_latency_probe(999999) == -1
    assert fake_xray.instances == []


def test_default_latency_probe_returns_minus_one_when_xray_does_not_start(adw_app, monkeypatch):
    class Failing(_FakeManager):
        def start(self, config):
            return False, "port busy"

    _FakeManager.instances = []
    monkeypatch.setattr("src.core.xray_manager.XrayManager", Failing)

    assert adw_app._default_latency_probe(_first_profile_id(adw_app)) == -1
    assert _FakeManager.instances[0].stopped is True


def test_default_latency_probe_stops_xray_when_the_probe_raises(adw_app, monkeypatch):
    """Временный процесс гасится и на ошибке: иначе он останется висеть."""

    class Raising(_FakeManager):
        def test_delay_realistic(self, proxy_address, proxy_port, **kwargs):
            raise RuntimeError("boom")

    _FakeManager.instances = []
    monkeypatch.setattr("src.core.xray_manager.XrayManager", Raising)

    with pytest.raises(RuntimeError):
        adw_app._default_latency_probe(_first_profile_id(adw_app))
    assert _FakeManager.instances[0].stopped is True
```

**Step 2: Run the tests**

Run: `DISPLAY=:0 uv run pytest tests/test_ui_application.py -m gtk -k latency_probe -v`

Тесты фиксируют уже верное поведение перед удалением GTK3-аналога, поэтому
они должны пройти сразу. Если падает последний — значит `finally` в
`_default_latency_probe` не срабатывает; чинить код, а не тест.

Замечание о последнем тесте: исключение из `test_delay_realistic`
пробрасывается наружу, а не превращается в `-1` — в отличие от старого
GTK3-метода, который глотал всё. Это не дефект: `LatencyRunner._safe_probe`
ловит исключение и возвращает `-1` сам, а логирование там подробнее.

**Step 3: Проверить фикстуру**

Если у `adw_app` нет ни одного профиля, добавить его в фикстуру (рядом с
тем, как это делают тесты подключения в том же файле).

**Step 4: Commit**

```bash
git add tests/test_ui_application.py
git commit -m "test: cover the default latency probe of the GTK4 application"
```

---

### Task 5.2: Удаление GTK3-кода

**Files:**
- Delete: `src/ui/app.py`, `src/ui/main_window.py`, `src/ui/style.py`, `src/ui/tray.py`
- Delete: `src/ui/dialogs/` целиком (6 модулей + `__init__.py`)
- Delete: `tests/test_ui_app_latency_flow.py`, `tests/test_ui_app_signals.py`,
  `tests/test_ui_dialog_validation_loops.py`, `tests/test_ui_profile_edit_link.py`,
  `tests/test_ui_subscription_flow.py`
- Modify: `src/ui/__init__.py`

**Step 1: Убедиться, что ничего живое не импортирует удаляемое**

```bash
grep -rn "from src.ui.app\|from src.ui import app\|src\.ui\.main_window\|src\.ui\.style\|from src.ui.tray import\|src\.ui\.dialogs\." src tests cli.py gui.py \
  | grep -v "dialogs4\|tray4"
```

Ожидается: только строки внутри самих удаляемых файлов, `gui.py:169`
(ветка `else`, уходит в 5.3) и пять удаляемых тестов.

**Step 2: Удалить файлы**

```bash
git rm src/ui/app.py src/ui/main_window.py src/ui/style.py src/ui/tray.py
git rm -r src/ui/dialogs
git rm tests/test_ui_app_latency_flow.py tests/test_ui_app_signals.py \
       tests/test_ui_dialog_validation_loops.py tests/test_ui_profile_edit_link.py \
       tests/test_ui_subscription_flow.py
```

**Step 3: Свести `src/ui/__init__.py` к докстроке**

```python
"""UI package (GTK4 + libadwaita)."""
```

Ленивый `__getattr__` больше не нужен: он существовал ровно для того, чтобы
импорт `src.ui` не фиксировал `Gtk 3.0` в процессе.

**Step 4: Проверить, что GTK3 исчез**

```bash
grep -rn 'require_version("Gtk", "3.0")\|require_version("Gdk", "3.0")\|AppIndicator' src tests
```
Ожидается: единственное совпадение — комментарий в `src/ui/tray4/sni.py:3`,
объясняющий, почему AppIndicator3 не используется. Он остаётся.

**Step 5: Прогнать тесты**

```bash
uv run pytest -q
```
Ожидается: зелено, число тестов уменьшилось примерно на 26 (14 + 4 + 4 + 2 + 2).

**Step 6: Commit**

```bash
git add -A
git commit -m "refactor!: remove the GTK3 UI in favour of GTK4 and libadwaita"
```

---

### Task 5.3: `gui.py` без `--gtk4`

**Files:**
- Modify: `gui.py`
- Modify: `tests/test_gui_entrypoint.py`

**Step 1: Обновить тесты точки входа**

В `tests/test_gui_entrypoint.py` удалить `test_gtk4_flag_defaults_to_false` и
`test_gtk4_flag_is_accepted`, добавить:

```python
def test_the_gtk4_flag_is_gone(entry):
    """Версия интерфейса больше не выбирается: GTK4 единственный."""
    args, rest = entry.parse_args(["--gtk4"])
    assert not hasattr(args, "gtk4")
    assert "--gtk4" in rest
```

`test_existing_flags_still_parse`, `test_unknown_args_are_passed_through` и
`test_libadwaita_version_gate` оставить.

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_gui_entrypoint.py -v`
Expected: FAIL — `--gtk4` пока разбирается.

**Step 3: Правки в `gui.py`**

Убрать `parser.add_argument("--gtk4", …)`.

Блок бутстрапа сводится к безусловному GTK4:

```python
try:
    import gi

    gi.require_version("Gdk", "4.0")
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    if not adwaita_is_supported(Adw.MAJOR_VERSION, Adw.MINOR_VERSION):
        print(
            f"Нужна libadwaita {MIN_ADWAITA[0]}.{MIN_ADWAITA[1]} или новее, "
            f"установлена {Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}."
        )
        print("Установите пакеты: sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1")
        sys.exit(1)

    logger.info("GTK4 imported successfully")
    ...
except ImportError as e:
    logger.exception(f"Error importing GTK: {e}")
    print(f"Ошибка импорта GTK: {e}")
    print("Установите пакеты: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1")
    sys.exit(1)
```

В `main()`:

```python
        from src.ui.application import run_app

        return run_app(
            config_dir=args.config_dir, lock=single_instance, with_tray=not args.no_tray
        )
```

В обработчике `ImportError` внутри `main()` заменить подсказку:

```python
        print("  sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1")
```

Комментарий у `parse_args` про выбор версии GTK устарел — заменить на:
«Разбор до импорта GTK: `--config-dir` нужен раньше, чем инициализируется
логирование и конфигурация».

**Step 4: Run tests**

```bash
uv run pytest tests/test_gui_entrypoint.py -v && uv run pytest -q
```

**Step 5: Живая проверка запуска**

```bash
TENGA_CONFIG_DIR=<скретчпад>/config python3 gui.py --no-tray
```
Окно открывается, профили из копии конфигурации видны. Закрыть окно.
**Ни одного действия подключения не выполнять.**

**Step 6: Commit**

```bash
git add gui.py tests/test_gui_entrypoint.py
git commit -m "refactor!: drop the --gtk4 flag, GTK4 is the only interface"
```

---

### Task 5.4: Единственность экземпляра через Gio

Находка 4: сокет-сервер поднимался только GTK3-кодом, после 5.2 клиент
всегда получает отказ. `Gio.Application` делает то же через D-Bus.

**Files:**
- Modify: `src/sys/single_instance.py`
- Modify: `gui.py`
- Modify: `tests/test_sys_single_instance.py`

**Step 1: Обновить тесты**

В `tests/test_sys_single_instance.py` удалить тесты сокета (те, что трогают
`_socket_file`, `_socket_path_for`, `setup_socket_server`,
`send_activation_signal` — строки ~185-240). Добавить:

```python
def test_the_lock_has_no_socket_activation_any_more():
    """Активация окна — дело Gio.Application, у блокировки её больше нет."""
    instance = SingleInstance(Path("/tmp/x.lock"))
    assert not hasattr(instance, "send_activation_signal")
    assert not hasattr(instance, "setup_socket_server")
```

**Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_sys_single_instance.py -v`
Expected: FAIL — методы ещё есть.

**Step 3: Удалить сокет из `single_instance.py`**

Удалить: `_MAX_UNIX_SOCKET_PATH`, `_socket_path_for`, `send_activation_signal`,
`setup_socket_server`, `close_socket_server`, поле `self._socket_file`,
вызовы `setup_socket_server()` в `acquire()` и `close_socket_server()` в
`release()`, попытки `self._socket_file.unlink()` в `is_running()`.
Удалить импорты `hashlib`, `socket`, `tempfile`.

Обновить докстроку класса:

```python
class SingleInstance:
    """File lock keeping a second xray from starting.

    Активацию окна второго запуска берёт на себя `Gio.Application` через
    D-Bus (`application_id`); блокировка нужна лишь как страховка от двух
    ядер xray там, где D-Bus недоступен.
    """
```

**Step 4: Убрать вызов активации из `gui.py`**

```python
    lock_file = get_lock_file(args.config_dir)
    single_instance = SingleInstance(lock_file)

    # Второй запуск не падает: Gio.Application увидит уже занятое имя на шине
    # и активирует окно первого процесса, а лишний xray не поднимется.
    if not single_instance.acquire():
        logger.info("Another instance holds the lock, handing over to it")
```

Здесь важна деталь: при живом первом процессе `acquire()` вернёт `False`, и
запускать `run_app` всё равно надо — именно он через D-Bus разбудит окно.
Правильный вид:

```python
    lock_file = get_lock_file(args.config_dir)
    single_instance = SingleInstance(lock_file)
    holds_lock = single_instance.acquire()
    if not holds_lock:
        # Первый процесс жив: xray уже под ним, второй запускать нельзя.
        # Приложение всё равно стартует — Gio.Application увидит занятое имя
        # на шине, активирует окно первого и немедленно завершится.
        logger.info("Another instance holds the lock, activating its window")

    try:
        from src.ui.application import run_app

        return run_app(
            config_dir=args.config_dir, lock=single_instance if holds_lock else None,
            with_tray=not args.no_tray,
        )
    ...
    finally:
        if holds_lock:
            single_instance.release()
```

**Step 5: Run tests**

```bash
uv run pytest -q
```

**Step 6: Живая проверка**

Запустить два процесса подряд с одним `TENGA_CONFIG_DIR` (скретчпад,
не системный!), убедиться, что второй завершается, а окно первого
поднимается наверх. Оба закрыть.

**Step 7: Commit**

```bash
git add src/sys/single_instance.py gui.py tests/test_sys_single_instance.py
git commit -m "refactor: leave window activation to Gio.Application (B20)"
```

---

### Task 5.5: Возврат исторических имён пакетов

`dialogs4` и `tray4` назывались так только чтобы не перекрыть GTK3-модули.
Тех больше нет.

**Files:**
- Rename: `src/ui/dialogs4/` → `src/ui/dialogs/`
- Rename: `src/ui/tray4/` → `src/ui/tray/`
- Modify: все импортирующие файлы

**Step 1: Переименовать**

```bash
git mv src/ui/dialogs4 src/ui/dialogs
git mv src/ui/tray4 src/ui/tray
```

**Step 2: Обновить импорты**

```bash
grep -rln "dialogs4\|tray4" src tests | xargs sed -i 's/dialogs4/dialogs/g; s/tray4/tray/g'
```

**Step 3: Убрать устаревшую докстроку `src/ui/tray/__init__.py`**

Она объясняет, почему пакет назван `tray4`. Заменить на:

```python
"""System tray over StatusNotifierItem and com.canonical.dbusmenu."""
```

**Step 4: Проверить, что старые имена исчезли**

```bash
grep -rn "dialogs4\|tray4" src tests docs
```
Ожидается: только упоминания в планах этапов 3 и 4 (историческая запись,
их не трогать) — то есть в `docs/plans/`.

**Step 5: Прогнать оба набора тестов**

```bash
uv run pytest -q && make test-gtk
```

**Step 6: Commit**

```bash
git add -A
git commit -m "refactor: restore the dialogs and tray package names"
```

---

### Task 5.6: Сборка AppImage под GTK4

**Files:**
- Modify: `core/scripts/build_appimage.sh`
- Modify: `core/scripts/install_dev.sh`

**Step 1: Заменить проверки зависимостей в лаунчере**

В `build_appimage.sh`, внутри heredoc `LAUNCHER`, функция `check_deps`:

```bash
        if ! python3 -c "import gi" 2>/dev/null; then
            missing+=("python3-gi")
        fi
        if ! python3 -c "import gi; gi.require_version('Gtk','4.0'); from gi.repository import Gtk" 2>/dev/null; then
            missing+=("gir1.2-gtk-4.0")
        fi
        if ! python3 -c "import gi; gi.require_version('Adw','1'); from gi.repository import Adw" 2>/dev/null; then
            missing+=("gir1.2-adw-1")
        fi
```

и текст установки:

```bash
        echo "  sudo apt install -y python3 python3-gi python3-pip \\" >&2
        echo "    gir1.2-gtk-4.0 gir1.2-adw-1" >&2
```

`gir1.2-appindicator3-0.1` и `gir1.2-notify-0.7` удалить: трей теперь свой,
libnotify не используется (находка 6).

**Step 2: Убрать GDK_BACKEND=x11 из лаунчера**

Строки

```bash
if [ -n "$WAYLAND_DISPLAY" ] && [ -n "$DISPLAY" ]; then
    export GDK_BACKEND=x11
fi
```

существовали ради GTK3, у которого Wayland-бэкенд был проблемным. GTK4
работает на Wayland нативно, а принудительный XWayland ухудшает
масштабирование на HiDPI. Заменить на поддержку программного рендеринга,
описанную в дизайн-документе:

```bash
# Программный рендеринг по требованию: на некоторых виртуальных машинах
# GL-рендерер GTK4 не инициализируется.
if [ -n "$TENGA_SOFTWARE_RENDER" ]; then
    export GSK_RENDERER=cairo
fi
```

**Step 3: Проверить, что иконки трея попадают в бандл**

`cp -r "$PROJECT_ROOT/assets"` уже копирует `assets/icons/*.svg`, а
`icons_directory()` ищет ровно там (`BUNDLE_DIR / "assets" / "icons"`).
Добавить в скрипт явную проверку после копирования:

```bash
    for icon in tenga-proxy-disconnected tenga-proxy-connecting tenga-proxy-connected; do
        [ -f "$APPDIR/usr/share/tenga-proxy/assets/icons/${icon}.svg" ] \
            || error "Иконка трея ${icon}.svg не попала в бандл"
    done
```

**Step 4: Обновить `install_dev.sh`**

Заменить блоки appindicator и notify на:

```bash
    if ! dpkg -l | grep -q "^ii.*gir1.2-gtk-4.0 "; then
        MISSING_DEPS+=("gir1.2-gtk-4.0")
    fi

    if ! dpkg -l | grep -q "^ii.*gir1.2-adw-1 "; then
        MISSING_DEPS+=("gir1.2-adw-1")
    fi
```

**Step 5: Собрать**

```bash
python cli.py build
```
Ожидается: AppImage в `dist/`. **Не устанавливать в систему.**

**Step 6: Запустить собранный AppImage на копии конфигурации**

```bash
TENGA_CONFIG_DIR=<скретчпад>/appimage-config ./dist/tenga-proxy-*.AppImage --no-tray
```
Окно открывается, интерфейс адвайтовский. Закрыть.
**Никаких подключений.**

**Step 7: Commit**

```bash
git add core/scripts/build_appimage.sh core/scripts/install_dev.sh
git commit -m "build: require GTK4 and libadwaita instead of GTK3 and AppIndicator"
```

---

### Task 5.7: Один диалог за раз

Дефект из находки 11, отложенный с этапа 4.

**Files:**
- Modify: `src/ui/application.py`
- Modify: `src/ui/window.py`
- Modify: `tests/test_ui_application.py`

**Step 1: Write the failing test**

```python
@pytest.mark.gtk
def test_a_second_dialog_does_not_stack_on_the_first(app, gtk_ready):
    """Повторное действие не кладёт второй диалог поверх первого."""
    app.activate_action("add-profile")
    first = app.current_dialog
    assert first is not None

    app.activate_action("add-profile")
    assert app.current_dialog is first


@pytest.mark.gtk
def test_closing_a_dialog_frees_the_slot(app, gtk_ready):
    app.activate_action("add-profile")
    first = app.current_dialog
    first.close()
    _pump()

    app.activate_action("settings")
    assert app.current_dialog is not first
```

**Step 2: Run to verify it fails**

Run: `make test-gtk` (или `DISPLAY=:0 uv run pytest -m gtk -k dialog -v`)
Expected: FAIL — атрибута `current_dialog` нет.

**Step 3: Реализация**

В `TengaApplication` завести один слот и общий метод показа:

```python
    def present_dialog(self, dialog) -> bool:
        """Show a dialog unless another one is already open.

        Диалоги приложения не складываются стопкой: повторное нажатие
        Ctrl+N или клик по пункту меню при открытой форме ничего не делает.
        Слот освобождается по сигналу `closed`, а не вручную: диалог
        закрывается и кнопкой, и Esc, и щелчком мимо.
        """
        if self._dialog is not None:
            return False
        self._dialog = dialog
        dialog.connect("closed", self._on_dialog_closed)
        dialog.present(self._window)
        return True

    def _on_dialog_closed(self, dialog) -> None:
        if self._dialog is dialog:
            self._dialog = None

    @property
    def current_dialog(self):
        """The dialog on screen, if any (tests and the window use it)."""
        return self._dialog
```

В `__init__` добавить `self._dialog = None`.

Все шесть `_open_*` в `application.py` переводятся с `dialog.present(self._window)`
на `self.present_dialog(dialog)`.

В `window.py` пять методов `_row_*`, открывающих диалоги
(`_row_edit_profile`, `_row_profile_routing`, `_row_edit_group`,
`_row_edit_subscription`, и `confirm_delete` в `_row_delete_profile` /
`_row_delete_group`) идут через приложение:

```python
        app = self.get_application()
        if app is not None:
            app.present_dialog(dialog)
```

`confirm_delete` возвращает `Adw.AlertDialog`; если сейчас он презентует
сам — изменить его так, чтобы он возвращал диалог, а показывал вызывающий.

**Step 4: Run tests**

```bash
make test-gtk && uv run pytest -q
```

**Step 5: Живая проверка**

Запустить окно на копии конфигурации, нажать Ctrl+N дважды — второй формы
не появляется. Esc, затем Ctrl+, — открываются настройки.

**Step 6: Commit**

```bash
git add src/ui/application.py src/ui/window.py tests/test_ui_application.py
git commit -m "fix: keep only one dialog open at a time"
```

---

### Task 5.8: Документация

**Files:**
- Modify: `README.md`
- Modify: `docs/ru/gui.md`, `docs/en/gui.md`
- Modify: `docs/ru/installation.md`, `docs/en/installation.md`
- Modify: `docs/ru/development.md`, `docs/en/development.md` (если упоминают GTK3)
- Modify: `CLAUDE.md`, `AGENTS.md` (раздел структуры и GUI)

**Step 1: Зависимости**

Везде, где перечислены пакеты, заменить

```
gir1.2-gtk-3.0 gir1.2-appindicator3-0.1 gir1.2-notify-0.7
```

на

```
gir1.2-gtk-4.0 gir1.2-adw-1
```

и добавить строку о минимальной версии: libadwaita 1.5 (Ubuntu 24.04,
Fedora 40, Debian 13 и новее).

**Step 2: `docs/*/gui.md`**

Дописать разделы, которых не было:

- **Сочетания клавиш** — таблица из `src/ui/shortcuts.py`
  (Ctrl+Return, Ctrl+T, Ctrl+N, Ctrl+Shift+N, F5, Ctrl+F, Ctrl+, Ctrl+W, Ctrl+Q).
- **Трей** — три состояния иконки (отключено, подключение, подключено) и
  оговорка: в GNOME нужен работающий StatusNotifierItem (обычно расширение
  AppIndicator/Tray Icons); без него приложение работает без иконки.
- **Тема** — светлая и тёмная приходят из системы, своей темы больше нет.
- **Адаптивность** — при узком окне переключатель вкладок уезжает вниз.

**Step 3: `CLAUDE.md` и `AGENTS.md`**

Обновить дерево `src/ui/` под фактическое состояние: `application.py`,
`window.py`, `pages/`, `widgets/`, `dialogs/`, `tray/`, `logic/`, `models/`.
Заменить абзац «**TengaApp** (`src/ui/app.py`) - главный класс» на
`TengaApplication` (`src/ui/application.py`), упомянуть единый набор
`Gio.SimpleAction`, обслуживающий меню, ускорители и трей.
В разделе Testing добавить `make test-gtk` и маркер `gtk`.

**Step 4: Проверить сборку документации**

```bash
uv run --extra docs mkdocs build --strict 2>&1 | tail -20
```
Если `mkdocs` не установлен — пропустить, отметить в результатах.

**Step 5: Commit**

```bash
git add README.md docs CLAUDE.md AGENTS.md
git commit -m "docs: describe the Adwaita interface and its dependencies"
```

---

### Task 5.9: Скриншот главного окна

**Files:**
- Replace: `assets/main-screen.png`

**Step 1: Запустить окно на копии конфигурации**

```bash
TENGA_CONFIG_DIR=<скретчпад>/config python3 gui.py --no-tray &
```

**Step 2: Снять окно**

Под XWayland `import -window root` не работает, поэтому по id:

```bash
WID=$(xwininfo -root -tree | grep '"Tenga Proxy": ("python3"' | head -1 | awk '{print $1}')
import -window "$WID" <скретчпад>/main-screen.png
```

**Step 3: Проверить, что на снимке нет личных данных**

На скриншоте видны имена профилей из копии реального конфига — **это личные
данные пользователя**. Перед заменой файла: либо снимать на подготовленной
тестовой конфигурации с выдуманными именами, либо получить согласие
владельца на публикацию имён. По умолчанию — тестовая конфигурация из
3-4 выдуманных профилей и одной группы.

**Step 4: Заменить и закрыть окно**

```bash
cp <скретчпад>/main-screen.png assets/main-screen.png
```

**Step 5: Commit**

```bash
git add assets/main-screen.png
git commit -m "docs: replace the main window screenshot"
```

---

### Task 5.10: Паритет, версия, результаты

**Step 1: Чек-лист паритета из дизайн-документа**

Пройти по разделу «Критерии готовности» и проверить каждый пункт на живом
окне (копия конфигурации, **без подключений**):

- [ ] добавить/редактировать/удалить профиль
- [ ] добавить/редактировать/удалить группу
- [ ] добавить/редактировать/удалить подписку, обновить подписку
- [ ] тест задержки одного профиля и группы
- [ ] настройки, мониторинг
- [ ] трей: меню, выбор профиля, три иконки
- [ ] ни одного `subprocess`/сети/диска из главного потока:
      `grep -rn "subprocess\.\|requests\." src/ui/ | grep -v logic/`
- [ ] один язык надписей: `grep -rn '"\(Cancel\|Apply\|OK\|Add\|Save\)"' src/ui/`
- [ ] окно от 360×500 до полноэкранного, светлая и тёмная тема
- [ ] `uv run pytest -q`, `make test-gtk`, `python cli.py lint-all`

Подключение и отключение — **единственные пункты, которые не проверяются**
(ограничение владельца); отметить это в результатах.

**Step 2: Версия**

```bash
python cli.py bump-version 0.13.0
```
Проверить, что обновились `src/__init__.py`, `pyproject.toml` и
`core/scripts/build_appimage.sh` (`APP_VERSION`).

**Step 3: Записать результаты в план**

Дописать в этот файл раздел «Результаты» по образцу этапов 1-4: коммиты,
отклонения с номерами, что не сделано, метрики (тесты до/после, строки).

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: release 0.13.0 with the Adwaita interface"
```

**Step 5: Обзор кода**

`superpowers:requesting-code-review` по всей ветке
(`git diff develop...feature/ui-adwaita`).

**Step 6: Слияние — только по явному согласию владельца**

Ветка на ~60 коммитов впереди `develop`. Предложить варианты (PR или
прямое слияние), дождаться ответа. Не сливать самостоятельно.

---

## Критерии приёмки этапа

1. `grep -rn 'require_version("Gtk", "3.0")' src tests` — пусто.
2. `src/ui/` не содержит `app.py`, `main_window.py`, `style.py`, `tray.py`;
   пакеты называются `dialogs` и `tray`.
3. `gui.py --gtk4` больше не флаг; запуск без аргументов даёт GTK4-окно.
4. `uv run pytest -q` и `make test-gtk` зелёные; `python cli.py lint-all` чист.
5. AppImage собирается и запускается; иконки трея внутри бандла.
6. Повторный вызов действия при открытом диалоге не создаёт второй.
7. Второй запуск активирует окно первого и не поднимает второй xray.
8. Документация не упоминает GTK3, AppIndicator и libnotify.
9. Версия 0.13.0 во всех трёх местах.
10. Приложение пользователя за всё время работ не остановлено и не
    переподключено.

---

## Результаты

Выполнено 2026-09-02. Ветка `feature/ui-adwaita`, 11 коммитов этапа
(`bd54dec` … `d80b498` плюс `chore` с версией).

### Коммиты

| Коммит | Задача |
|--------|--------|
| `bd54dec` | план этапа |
| `7b98da8` | 5.1 тест на `_default_latency_probe` |
| `fbd1081` | 5.2 удаление GTK3 |
| `ee8e9e9` | 5.3 `gui.py` без `--gtk4` |
| `3933a21` | 5.4 единственность через `Gio.Application` |
| `23848aa` | 5.5 `dialogs4` → `dialogs`, `tray4` → `tray` |
| `f6ff10e` | 5.6 сборка AppImage |
| `a91a20e` | 5.7 один диалог за раз |
| `2fce34b` | 5.8 документация |
| `d80b498` | 5.9 скриншот |

### Отклонения от плана

1. **Задача 5.1: патч `XrayManager` ловит два экземпляра, а не один.**
   `_default_latency_probe` читает `self.context.xray_manager.binary_path`,
   и ленивое свойство контекста создаёт подменённый класс первым. Тесты
   берут последний экземпляр (`instances[-1]`), а не единственный.

2. **Задача 5.1: исключение замера пробрасывается, а не гасится в `-1`.**
   В отличие от старого GTK3-метода, глотавшего всё, `_default_latency_probe`
   ловит только незапуск xray. Это не дефект: `LatencyRunner._safe_probe`
   ловит исключение сам и логирует подробнее. Тест зафиксировал фактическое
   поведение.

3. **Задача 5.4: второй запуск не забирает блокировку и не падает.**
   План предполагал ветвление вокруг `is_running()`. Фактически проще:
   `acquire()` вызывается один раз, и при неудаче приложение всё равно
   стартует — `Gio.Application` упрётся в занятое имя, разбудит окно первого
   и завершится. Блокировку второй процесс не трогает, `release()` вызывается
   только владельцем.

4. **Задача 5.6: копирование иконок в `hicolor/symbolic/apps` не сделано.**
   Общий план требовал этого, но `cp -r assets` уже кладёт SVG туда, где их
   ищет `icons_directory()` (`BUNDLE_DIR/assets/icons`), а трей отдаёт панели
   `IconThemePath` и не полагается на системную тему. Вместо копирования
   добавлена проверка: сборка падает, если иконок нет в бандле.

5. **Задача 5.6: сверх плана исправлен лаунчер AppImage.**
   `export TENGA_CONFIG_DIR=...` затирал переменную безусловно, из-за чего
   AppImage невозможно было запустить на отдельной конфигурации — любой
   запуск шёл в рабочую. Стало `${TENGA_CONFIG_DIR:-...}`.
   Обнаружено ценой инцидента, см. ниже.

6. **Задача 5.6: убран `GDK_BACKEND=x11`.**
   Форсирование XWayland существовало ради GTK3; GTK4 работает на Wayland
   нативно, а принудительный X11 портит масштабирование на HiDPI. Заменено
   на `GSK_RENDERER=cairo` по `TENGA_SOFTWARE_RENDER`, как описано в
   дизайн-документе.

7. **Задача 5.7: `closed` у `Adw.Dialog` в тестах недостижим.**
   Проверено экспериментально: ни `close()`, ни `force_close()` не снимают
   диалог, пока окно не отрисовано композитором — родитель остаётся
   `AdwDialogHost`, `unmap` не приходит, `notify::parent` тоже (свойство
   меняется без уведомления). Освобождение слота проверяется вызовом
   `_on_dialog_closed` напрямую; сам сигнал в приложении работает.

8. **Задача 5.7: `confirm_delete` разделён на построение и показ**
   (`build_delete_confirmation`). Иначе диалог подтверждения проходил бы мимо
   слота — он презентовал себя сам.

9. **Задача 5.9: скриншот снят на выдуманной конфигурации.**
   Как и предполагал план, снимок с реальными профилями публиковать нельзя.
   Создана демо-конфигурация из четырёх вымышленных профилей в двух группах.

### Инцидент: запуск AppImage прочитал рабочую конфигурацию

При проверке сборки (5.6) AppImage был запущен с `TENGA_CONFIG_DIR`,
указывающим на тестовую директорию, но лаунчер внутри образа перезаписывал
переменную (отклонение 5). Окно открылось на рабочей конфигурации
пользователя. Процесс закрыт сразу, как только это стало видно на скриншоте.

Задето одно поле: `window_size` в `~/.config/tenga-proxy/settings.json`
затёрлось при закрытии окна. Профили, подписки, маршруты, VPN и DNS не
изменялись (`profiles.json` не трогался). Соединение не прерывалось.
Восстановить значение не удалось — запись в рабочую конфигурацию
заблокирована; владелец решил оставить как есть, приложение перезаписало
поле само.

Причина устранена в самой сборке: лаунчер больше не затирает переменную.

### Второй инцидент: закрыто приложение пользователя

При уборке тестовых окон шаблон `pgrep`/`kill` по `[g]ui.py` совпал не только
с тестовым процессом: AppImage пользователя внутри тоже исполняет `gui.py`.
Приложение было закрыто и перезапущено владельцем.

Правило на будущее: завершать только по PID, записанному при запуске, и
сверять `TENGA_CONFIG_DIR` процесса через `/proc/<pid>/environ` перед `kill`.

### Живая проверка (демо-конфигурация, без подключений)

- запуск без `--gtk4`, окно открывается;
- второй запуск возвращает 0, окна остаётся одно, блокировка не тронута;
  имя `ru.tenga.Proxy` занято, `org.gtk.Application.Activate` отвечает;
- собранный AppImage читает переданный `TENGA_CONFIG_DIR` и показывает
  демо-профили;
- 17 действий приложения и 11 действий окна на месте (`org.gtk.Actions.List`);
- диалоги настроек, редактирования профиля, маршрутов и подтверждения
  удаления открываются, заполнены, надписи русские;
- двойной вызов `add-profile` даёт один диалог, `settings` поверх него не
  открывается;
- трей регистрируется у настоящего watcher: `IconName` =
  `tenga-proxy-disconnected`, `ItemIsMenu` = false, `IconThemePath` указывает
  в бандл, меню содержит все 11 пунктов включая подменю профилей.

### Не проверено

- **Подключение и отключение профилей** — прямой запрет владельца:
  у него работает установленное приложение.
- **Установка AppImage в систему** (`cli.py install`) — заменила бы
  работающее приложение.
- **Чистая Ubuntu 24.04** — нет VM или контейнера с X11.
- **Переключение вкладок в живом окне** — это свойство `ViewStack`, а не
  действие, через D-Bus не вызывается. Покрыто тестами страниц (41 тест).
- **KDE** — нет такого окружения.

### Метрики

| | до этапа | после |
|---|---|---|
| тестов без дисплея | 502 | 472 |
| тестов GTK | 110 | 120 |
| строк в `src/ui` | 10 565 | 5 131 |
| ошибок ruff в `src`/`tests` | 20 | 7 |

Тестов стало меньше на 30: удалены 26 GTK3-тестов, покрытие которых перешло
к GTK4-аналогам (разбор в находке 3), и добавлены 4 новых на замер задержки.
Оставшиеся 7 ошибок ruff — унаследованные, в файлах вне этапа
(`core/performance.py`, `core/xray_manager.py`, `db/__init__.py`,
`test_core_latency_probe.py`, `test_core_log_manager.py`,
`test_core_performance.py`).

Диффа этапа: 66 файлов, +1970 / −6868.
Диффа ветки от `develop`: 104 файла, +16 535 / −6 305, 59 коммитов.

### Завершение

Ветка слита в `develop` (PR #49), затем в `master` (PR #50) владельцем
2026-09-02. Выпущен релиз
[v0.13.0](https://github.com/vebulogmetra/tenga-proxy/releases/tag/v0.13.0)
с приложенным AppImage; описание охватывает версии 0.10.6–0.13.0, поскольку
предыдущий релиз на GitHub был 0.10.5.

Задача о замере отклика до youtube.com (`TASK/TASK.md`) снята владельцем
как неактуальная, файл удалён.
