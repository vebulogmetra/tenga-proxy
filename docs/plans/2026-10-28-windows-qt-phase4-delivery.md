# Фаза 4: поставка Qt-интерфейса на Windows — план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Выпускать Windows-сборку с Qt-интерфейсом вместо GTK. Нужны spec PyInstaller без GTK, сборка и окружение разработки в Git Bash через uv без MSYS2, CI без MSYS2 с запуском собранного exe. Windows-ветки GTK-интерфейса, Win32-трей и BMP-флаги удаляются, документация обновляется. Завершают фазу приёмка на VM и релиз.

**Architecture:** Код приложения почти не меняется: Qt-интерфейс готов с фазы 3. Меняется поставка: `packaging/windows/tenga-proxy.spec` собирает GUI из PySide6 и исключает `gi` и неиспользуемые модули Qt; `build_windows.sh` и `install_dev.sh` работают через `uv run`/`uv sync`; `windows.yml` ставит Python через `setup-python`, а uv — через `setup-uv`. Из GTK-кода удаляется всё, что работало только на Windows: `platform_layout.py`, `style-windows.css`, `name_label.py`, сигналы и pipe активации в `application.py`. Linux-ветки остаются как есть. Win32-трей уходит целиком, кроме сборщика `.ico`: тот переезжает в `packaging/windows/`.

**Tech Stack:** Python 3.11+ (3.12 на Windows), PySide6-Essentials ≥ 6.8 (проверено на 6.12), PyInstaller 6.17 (группа `build`), uv, Inno Setup 6, GitHub Actions `windows-latest`, pytest, ruff.

**Дизайн:** `docs/plans/2026-10-28-windows-qt-frontend-design.md`, разделы «Границы» (список «Удаляется»), «Сборка и поставка», «Тестирование», фаза 4.
**Предыдущая фаза:** `docs/plans/2026-10-28-windows-qt-phase3-parity.md`.

---

## Правила фазы

- **Критерий приёмки:** зелёные `uv run pytest`, `make test-gtk`, `make test-tray`, `make test-qt` и `python cli.py lint-all`. Ожидания оставшихся тестов не правятся. Тесты удалённого Windows-кода удаляются вместе с ним, Linux-проверки в тех же файлах остаются. После push зелёный `windows.yml`. Установщик проходит приёмку задачи 8 на VM Windows 10 и 11.
- **GTK-интерфейс и поведение на Linux не меняются.** Из GTK-модулей удаляются только ветки, которые срабатывали при `IS_WINDOWS` (через `platform_layout`). Linux-ветка остаётся как была. `make test-gtk` это подтверждает. `tests/test_ui_styles.py` впервые попадает в `make test-gtk`: раньше его запускал только CI Windows.
- Linux-окружение не трогается: `install_dev.sh` на Linux работает как раньше, из `build_deb.sh` уходит только исключение удалённого каталога `assets/flags/win`. `linux.yml` не меняется.
- Один коммит на задачу, сообщения на русском в стиле репозитория. Перед коммитом — `uv run pytest -q --no-cov -p no:cacheprovider` и `python cli.py lint-all`; задачи 4 и 5 трогают GTK и трей, поэтому там ещё `make test-gtk`, `make test-tray` и `make test-qt`.
- Не запускать xray с TUN-конфигами на машине разработчика: интерфейс `xray0` занят рабочим подключением. Системный прокси на машине разработчика не менять.
- Ничего не пушить без просьбы владельца. CI Windows проверяется только после push.
- Код плана проверен. Каждая задача собрана отдельным коммитом во временной ветке, и после каждой зелёные pytest и lint; после задач 4–5 ещё GTK-, трей- и Qt-тесты. Затем план пройден по тексту на чистом `develop`, и результат совпал с временной веткой. Qt-вариант spec собран PyInstaller 6.17 на Linux (с Linux-`xray`, без `wintun`). `gi` в сборку не попал, `style.qss` и плагины Qt на месте. Собранный `--ui qt --no-tray` стартовал в offscreen и чисто вышел по SIGINT. Windows-сборку и `windows.yml` локально не проверить: это делает первый push.

## Решения фазы (уточняют дизайн)

| Вопрос | Решение | Почему |
|---|---|---|
| `platform_layout.py` | удаляется целиком вместе с `tests/test_ui_logic_platform_layout.py` | все его функции были Windows-ветками GTK; дизайн говорил «удалить Windows-ветки», а без них модуль пуст |
| `src/ui/widgets/name_label.py` | удаляется, вместо него `Gtk.Label(xalign=0.0)`, как в его Linux-ветке | виджет нужен был только для флагов-картинок на Windows |
| Сигналы и pipe активации в `src/ui/application.py` | удаляются вместе с параметром `lock_path` и `NON_UNIQUE`; `tests/test_ui_application_signals.py` удаляется | на Linux единственность даёт D-Bus, а Windows-ветка GTK больше не запускается. Pipe активации живёт в Qt-интерфейсе |
| `gui.py --ui gtk` на Windows | выход с подсказкой «Интерфейс GTK на Windows не поддерживается: запустите Veblock без --ui gtk.» | GTK на Windows больше не ставится и не собирается |
| `src/ui/tray/win32/ico.py` | переезжает в `packaging/windows/ico.py`, тест — в `tests/test_packaging_ico.py` | им `tools/make_ico.py` собирает `.ico` для exe и установщика; это сборка, а не трей. Перегенерация даёт байт-в-байт те же файлы |
| Состав сборки | `tests/test_packaging_spec.py` исполняет spec с подменными `Analysis`/`EXE`/`COLLECT` | spec — код, и без теста `gi` или забытый `style.qss` выяснились бы только на VM |
| Исключаемые модули Qt | QtConcurrent, QtDBus, QtDesigner, QtHelp, QtOpenGL, QtOpenGLWidgets, QtPdf, QtPdfWidgets, QtPrintSupport, QtQml, QtQuick, QtQuickWidgets, QtSql, QtTest, QtUiTools, QtXml; QtNetwork остаётся | `QNetworkInformation` нужен failover; тест не даёт исключить QtNetwork |
| Python в CI Windows | `setup-python` 3.12, `UV_PYTHON=3.12`, `UV_PYTHON_PREFERENCE=only-system` | `.python-version` (3.11.4) заставил бы uv скачивать свой Python; на Windows ставят CPython 3.12 с python.org |
| Группа `build` | `build_windows.sh` сам запускает `uv run --extra windows --extra build`; `install_dev.sh` ставит `--extra windows --extra dev` | разработчику PyInstaller не нужен для запуска и тестов. `uv run --extra …` добавляет группы к уже установленным, поэтому dev остаётся |
| Смоук собранного exe | запуск `tenga-proxy.exe --no-tray` с `TENGA_CONFIG_DIR` во временном каталоге и `QT_QPA_PLATFORM=offscreen`, через 10 с процесс жив, в журнале есть «Frontend: qt» и нет `Traceback`, нет `_internal\gi` | в оконном exe (`console=False`) нет stdout, поэтому `--version` упал бы; судить можно только по журналу |
| `[ERROR]` в журнале смоука | не роняет шаг | на раннере без сети проверка обновлений и замеры вправе писать ошибки; исключение (`Traceback`) — нет |
| Размер сборки | печатается шагом смоука, порога нет | цель дизайна 60–80 МБ; реальную цифру даст первый CI, порог ставится после неё |

## Что уже есть и переиспользуется без изменений

- Qt-интерфейс фаз 2–3: `src/ui/qt/` (`QtApplication`, `MainWindow`, `QtTrayItem`, диалоги), `style.qss`; `choose_frontend()` и `gtk_install_hint()` в `gui.py`.
- Единственность и активация на Windows: `src/sys/windows/activation.py`, mutex в `src/sys/single_instance.py`.
- Пути собранного приложения: `src/core/config.py`. `TENGA_CONFIG_DIR` переопределяет каталог настроек, журналы тогда лежат в `<каталог>/logs/tenga_gui.log`.
- `packaging/windows/version_info.py`, `veblock.iss`, `tests/test_packaging_version_info.py`, `cli.py build` (выбирает сценарий по ОС).
- Шаги CI Windows после сборки: проверка тега, прикрепление к релизу, установка службы, интеграционные тесты, журнал и удаление службы — без изменений, кроме `uv run`.

---

### Task 0: Сверка с кодом

**Files:** только чтение.

**Step 1:** Фаза 3 на месте, всё удаляемое существует:

```bash
git log --oneline -1 4cfbb50
ls src/ui/logic/platform_layout.py src/ui/style-windows.css src/ui/widgets/name_label.py \
   src/ui/tray/win32/ tools/make_flag_bitmaps.py
ls assets/flags/win | wc -l
grep -n "msys2\|venv-win" .github/workflows/windows.yml core/scripts/install_dev.sh | head
```

Expected: коммит найден, файлы есть, в `assets/flags/win` 257 файлов, `msys2` встречается в обоих файлах.

**Step 2:** Где ещё упоминаются удаляемые модули (после фазы список будет пуст):

```bash
git grep -l "platform_layout\|name_label\|style-windows\|tray.win32\|tray/win32\|flags/win\|make_flag_bitmaps" \
  -- '*.py' '*.spec' '*.sh' '*.yml' Makefile
```

Expected: `core/scripts/build_deb.sh`, `.github/workflows/windows.yml`, `packaging/windows/tenga-proxy.spec`, GTK-модули (`window.py`, `dialogs/base.py`, `dialogs/settings.py`, `pages/{monitoring,profiles,subscriptions}.py`, `widgets/status_card.py`), сами удаляемые модули, `src/ui/tray/controller.py`, `tools/make_ico.py` и тесты.

**Step 3:** Отправная точка тестов:

```bash
uv sync --extra windows --extra dev --extra build
uv run pytest -q --no-cov -p no:cacheprovider | tail -1   # 1590 passed, 10 skipped
make test-gtk 2>&1 | grep -E 'passed|failed' | tail -1                              # 279 passed
make test-tray 2>&1 | grep -E 'passed|failed' | tail -1                             # 146 passed, 5 skipped
make test-qt 2>&1 | grep -E 'passed|failed' | tail -1                               # 137 passed
```

Числа могут отличаться, если в `develop` появились тесты после фазы 3. Тогда сверяй разницу, а не абсолютные значения.

---

### Task 1: spec PyInstaller без GTK

Сейчас spec собирает GUI с хуками `gi`, `style.css` и `style-windows.css`. Новый spec собирает Qt: кладёт `style.qss`, исключает `gi`/`cairo` и неиспользуемые модули Qt. Служба остаётся без интерфейса.

**Files:**
- Create: `tests/test_packaging_spec.py`
- Modify: `packaging/windows/tenga-proxy.spec` (переписывается целиком)

**Step 1: Тест**

Тест исполняет spec через `exec` с подменными `Analysis`/`PYZ`/`EXE`/`COLLECT`: так проверяется то, что PyInstaller получит на самом деле.

```python
"""Состав Windows-сборки: spec PyInstaller, исполненный с подменными классами."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "windows" / "tenga-proxy.spec"


class _Recorder:
    """Запоминает аргументы вместо сборки; у Analysis есть поля, нужные PYZ/EXE."""

    calls: list[_Recorder] = []

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.pure = self.scripts = self.binaries = self.datas = ()
        _Recorder.calls.append(self)


def _run_spec() -> dict:
    _Recorder.calls = []
    names = {
        "SPECPATH": str(SPEC.parent),
        "Analysis": type("Analysis", (_Recorder,), {}),
        "PYZ": type("PYZ", (_Recorder,), {}),
        "EXE": type("EXE", (_Recorder,), {}),
        "COLLECT": type("COLLECT", (_Recorder,), {}),
    }
    exec(compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec"), names)
    return names


def _analyses() -> tuple[_Recorder, _Recorder]:
    names = _run_spec()
    return names["gui"], names["svc"]


def test_gui_bundle_has_no_gtk():
    gui, _svc = _analyses()

    assert "gi" in gui.kwargs["excludes"]
    assert not any("gi" in name for name in gui.kwargs.get("hiddenimports", []))
    assert "hooksconfig" not in gui.kwargs


def test_gui_bundle_carries_qt_resources():
    gui, _svc = _analyses()
    bundled = {Path(src).relative_to(ROOT).as_posix() for src, _dest in gui.kwargs["datas"]}

    # Всё, что Qt-интерфейс читает с диска рядом с модулями.
    resources = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src" / "ui" / "qt").rglob("*")
        if path.is_file() and path.suffix not in (".py", ".pyc")
    }
    assert resources and resources <= bundled
    assert "src/ui/style.css" not in bundled
    assert not any(name.startswith("assets/screen-") for name in bundled)


def test_qt_network_stays_in_the_bundle():
    gui, _svc = _analyses()

    # Failover слушает QNetworkInformation.
    assert "PySide6.QtNetwork" not in gui.kwargs["excludes"]
    assert "PySide6.QtQml" in gui.kwargs["excludes"]


def test_service_bundle_has_no_interface():
    _gui, svc = _analyses()

    assert {"gi", "PySide6"} <= set(svc.kwargs["excludes"])


def test_both_exes_land_in_one_directory():
    names = _run_spec()
    exes = [call for call in _Recorder.calls if type(call).__name__ == "EXE"]

    assert [exe.kwargs["name"] for exe in exes] == ["tenga-proxy", "tenga-proxy-svc"]
    assert names["coll"].kwargs["name"] == "tenga-proxy"
```

**Step 2: Тест падает на старом spec**

Run: `uv run pytest tests/test_packaging_spec.py -q --no-cov`
Expected: 4 failed, 1 passed (`test_both_exes_land_in_one_directory` проходит и сейчас).

**Step 3: Новый spec**

`packaging/windows/tenga-proxy.spec` целиком:

```python
# PyInstaller spec для Windows. Запуск: core/scripts/build_windows.sh
# Сборка onedir: onefile распаковывался бы во временный каталог при каждом
# запуске, а библиотеки Qt весят десятки мегабайт.

from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent  # noqa: F821 (SPECPATH задаёт PyInstaller)
ASSETS = ROOT / "assets"
CORE_BIN = ROOT / "core" / "bin"

# Скриншоты нужны README, а не приложению.
datas = [
    (str(path), str(Path("assets") / path.parent.relative_to(ASSETS)))
    for path in sorted(ASSETS.rglob("*"))
    if path.is_file() and not path.name.startswith("screen-")
]
datas += [
    (str(ROOT / "src" / "ui" / "qt" / "style.qss"), "src/ui/qt"),
    (str(CORE_BIN / "geoip.dat"), "core/bin"),
    (str(CORE_BIN / "geosite.dat"), "core/bin"),
]
binaries = [
    (str(CORE_BIN / "xray.exe"), "core/bin"),
    (str(CORE_BIN / "wintun.dll"), "core/bin"),
]

# Интерфейс Windows — Qt. GTK-модули gui.py импортирует только для `--ui gtk`,
# в сборке их нет. Модули Qt, которых приложение не импортирует, исключены на
# случай, если их потянет зависимость; QtNetwork нужен failover
# (QNetworkInformation).
QT_UNUSED = [
    "PySide6.QtConcurrent",
    "PySide6.QtDBus",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPrintSupport",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtUiTools",
    "PySide6.QtXml",
]

gui = Analysis(  # noqa: F821
    [str(ROOT / "gui.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    excludes=["tkinter", "gi", "cairo", *QT_UNUSED],
)
# Режим UTF-8: иначе open()/read_text() без encoding читали бы в cp1252.
PYTHON_OPTIONS = [("X utf8_mode=1", None, "OPTION")]

gui_pyz = PYZ(gui.pure)  # noqa: F821
gui_exe = EXE(  # noqa: F821
    gui_pyz,
    gui.scripts,
    PYTHON_OPTIONS,
    exclude_binaries=True,
    name="tenga-proxy",
    icon=str(ASSETS / "tenga-proxy.ico"),
    version=str(ROOT / "build" / "windows" / "version_info.txt"),
    console=False,
)

# Служба: свой exe в том же каталоге, интерфейс ей не нужен. Если анализ всё же
# находит PySide6 или gi, какой-то импорт в src.core стоит сделать ленивым.
svc = Analysis(  # noqa: F821
    [str(ROOT / "svc_main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    hiddenimports=["win32timezone", "servicemanager"],
    excludes=["tkinter", "gi", "cairo", "PySide6", "shiboken6"],
)
svc_pyz = PYZ(svc.pure)  # noqa: F821
svc_exe = EXE(  # noqa: F821
    svc_pyz,
    svc.scripts,
    PYTHON_OPTIONS,
    exclude_binaries=True,
    name="tenga-proxy-svc",
    icon=str(ASSETS / "tenga-proxy.ico"),
    version=str(ROOT / "build" / "windows" / "version_info.txt"),
    console=True,
)

coll = COLLECT(  # noqa: F821
    gui_exe,
    gui.binaries,
    gui.datas,
    svc_exe,
    svc.binaries,
    svc.datas,
    name="tenga-proxy",
)
```

**Step 4: Тест проходит**

Run: `uv run pytest tests/test_packaging_spec.py -q --no-cov`
Expected: 5 passed.

**Step 5 (необязательно, около 3 минут): сборка Qt-варианта на Linux**

Так проверяется, что PyInstaller принимает spec. Копия spec лежит вне репозитория, поэтому `ROOT` в ней задан абсолютным путём. Она берёт Linux-`xray` и не берёт `wintun`, иконку и сведения о версии. Нужен `core/bin/xray` (`python cli.py setup-dev`). Сборка — в scratchpad, не в `dist/`:

```bash
S=<scratchpad>
sed -e "s|^ROOT = .*|ROOT = Path(\"$PWD\")|" -e 's/"xray.exe"/"xray"/' -e '/wintun/d' -e '/icon=/d' -e '/version=/d' \
    -e 's/hiddenimports=\["win32timezone", "servicemanager"\]/hiddenimports=[]/' \
    packaging/windows/tenga-proxy.spec > $S/linux-probe.spec
uv run --extra windows --extra build pyinstaller --noconfirm \
    --distpath $S/p4build --workpath $S/p4build/work $S/linux-probe.spec
ls $S/p4build/tenga-proxy/_internal/gi 2>/dev/null && echo "gi в сборке!"
ls $S/p4build/tenga-proxy/_internal/src/ui/qt/style.qss
```

Если `sed` не находит строку, поправь копию руками: spec не меняется. Ожидается, что `gi` нет, а `style.qss` есть. Каталог `$S/p4build` потом удалить.

**Step 6: Commit**

```bash
uv run pytest -q --no-cov -p no:cacheprovider | tail -1   # 1595 passed, 10 skipped
python cli.py lint-all
git add packaging/windows/tenga-proxy.spec tests/test_packaging_spec.py
git commit -m "build(windows): spec PyInstaller для Qt-интерфейса — без GTK"
```

---

### Task 2: build_windows.sh в Git Bash через uv

**Files:**
- Modify: `core/scripts/build_windows.sh`

**Step 1: Правка**

Python берёт uv: группы `windows` и `build` ставятся поверх уже установленных. Inno Setup ищется как раньше. `MSYS2_ARG_CONV_EXCL` остаётся: Git Bash — тоже среда MSYS2 и без этой переменной принял бы `/DAppVersion=…` за путь.

```diff
diff --git a/core/scripts/build_windows.sh b/core/scripts/build_windows.sh
index 7a99bfd..5d2e855 100755
--- a/core/scripts/build_windows.sh
+++ b/core/scripts/build_windows.sh
@@ -1,12 +1,17 @@
 #!/bin/bash
-# Сборка установщика Veblock для Windows. Выполнять в оболочке MSYS2 UCRT64.
+# Сборка установщика Veblock для Windows. Выполнять в Git Bash: Python берёт uv
+# (группы windows и build), Inno Setup — из Program Files.
 set -euo pipefail
 
 SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
 PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
 cd "$PROJECT_ROOT"
 
-VERSION="$(python -c 'import runpy; print(runpy.run_path("packaging/windows/version_info.py")["project_version"]())')"
+command -v uv >/dev/null || { echo "[ERROR] uv не найден: bash core/scripts/install_dev.sh"; exit 1; }
+# Группы ставятся поверх уже установленных: dev для тестов остаётся.
+PY=(uv run --extra windows --extra build python)
+
+VERSION="$("${PY[@]}" -c 'import runpy; print(runpy.run_path("packaging/windows/version_info.py")["project_version"]())')"
 
 for f in xray.exe wintun.dll geoip.dat geosite.dat; do
     [ -f "core/bin/$f" ] || { echo "[ERROR] core/bin/$f не найден: bash core/scripts/install_dev.sh"; exit 1; }
@@ -16,9 +21,9 @@ for f in assets/tenga-proxy.ico assets/icons/win/tenga-proxy-connected.ico; do
 done
 
 mkdir -p build/windows
-python packaging/windows/version_info.py build/windows/version_info.txt
+"${PY[@]}" packaging/windows/version_info.py build/windows/version_info.txt
 
-python -m PyInstaller --noconfirm --clean \
+"${PY[@]}" -m PyInstaller --noconfirm --clean \
     --workpath build/windows/pyinstaller --distpath dist/windows \
     packaging/windows/tenga-proxy.spec
 
@@ -28,7 +33,7 @@ done
 
 ISCC="${ISCC:-/c/Program Files (x86)/Inno Setup 6/ISCC.exe}"
 [ -x "$ISCC" ] || { echo "[ERROR] Inno Setup 6 не найден: $ISCC (переменная ISCC задаёт путь)"; exit 1; }
-# MSYS2 принял бы «/DAppVersion=…» за путь и переписал бы его.
+# Git Bash (среда MSYS2) принял бы «/DAppVersion=…» за путь и переписал бы его.
 MSYS2_ARG_CONV_EXCL="*" "$ISCC" "/DAppVersion=$VERSION" 'packaging\windows\tenga-proxy.iss'
 
 echo "[OK] dist/windows/veblock-$VERSION-windows-x64-setup.exe"
```

**Step 2: Проверка**

```bash
bash -n core/scripts/build_windows.sh && echo ok
bash core/scripts/build_windows.sh; echo "exit $?"
```

Expected: `ok`. На Linux сценарий останавливается на «[ERROR] core/bin/xray.exe не найден» с кодом 1. Полностью он проверяется в CI (задача 6) и на Windows.

**Step 3: Commit**

```bash
git add core/scripts/build_windows.sh
git commit -m "build(windows): build_windows.sh в Git Bash через uv, без MSYS2-окружения"
```

---

### Task 3: install_dev.sh без ветки MSYS2

**Files:**
- Modify: `core/scripts/install_dev.sh`

**Step 1: Правка**

Удаляются `WINDOWS_MSYS2`, `MSYS2_PACKAGES`, `install_windows_deps` и MSYS2-ветки в `check_os`, `install_system_deps` и `install_python_deps`. На Windows остаётся путь uv, который фаза 2 уже добавила для Git Bash.

```diff
diff --git a/core/scripts/install_dev.sh b/core/scripts/install_dev.sh
index 2ac68c3..ab30340 100755
--- a/core/scripts/install_dev.sh
+++ b/core/scripts/install_dev.sh
@@ -17,13 +17,6 @@ case "$(uname -s)" in
     *) XRAY_OS="linux"; XRAY_BIN="xray" ;;
 esac
 
-# Windows: оболочка MSYS2 UCRT64 — прежняя GTK-сборка (уходит вместе с ней),
-# любая другая (Git Bash) — интерфейс Qt на обычном Python и uv.
-WINDOWS_MSYS2=0
-if [ "$XRAY_OS" = "windows" ] && [ "${MSYSTEM:-}" = "UCRT64" ]; then
-    WINDOWS_MSYS2=1
-fi
-
 SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
 PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
 cd "$PROJECT_ROOT"
@@ -96,11 +89,7 @@ check_os() {
             exit 1
             ;;
         MINGW*|MSYS*|CYGWIN*)
-            if [ "$WINDOWS_MSYS2" = "1" ]; then
-                success "Система: Windows (MSYS2 UCRT64, интерфейс GTK)"
-            else
-                success "Система: Windows (${MSYSTEM:-bash}, интерфейс Qt)"
-            fi
+            success "Система: Windows (${MSYSTEM:-bash}, интерфейс Qt)"
             return 0
             ;;
         *)
@@ -113,7 +102,7 @@ check_os() {
 
 
 check_root() {
-    # В MSYS2 EUID не означает администратора: проверка только для Linux.
+    # В Git Bash EUID не означает администратора: проверка только для Linux.
     if [ "$XRAY_OS" = "linux" ] && [ "$EUID" -eq 0 ]; then
         error "Не запускайте скрипт от имени root!"
         error "Скрипт сам запросит sudo при необходимости."
@@ -129,35 +118,10 @@ check_command() {
     return 0
 }
 
-# Windows: GTK, PyGObject и requests берутся из пакетов MSYS2, а не из pip.
-MSYS2_PACKAGES="git unzip mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-python-pip \
-mingw-w64-ucrt-x86_64-python-gobject mingw-w64-ucrt-x86_64-gtk4 \
-mingw-w64-ucrt-x86_64-libadwaita mingw-w64-ucrt-x86_64-python-requests \
-mingw-w64-ucrt-x86_64-python-pytest mingw-w64-ucrt-x86_64-python-pytest-cov \
-mingw-w64-ucrt-x86_64-python-pywin32"
-
-install_windows_deps() {
-    info "Проверка пакетов MSYS2..."
-    if python -c "import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); \
-from gi.repository import Gtk, Adw; import requests" 2>/dev/null; then
-        success "GTK 4, libadwaita и requests доступны из Python"
-        return 0
-    fi
-    info "Нужны пакеты MSYS2: $MSYS2_PACKAGES"
-    if ! confirm "Установить их через pacman? (y/n): " "y"; then
-        error "Установите вручную: pacman -S --needed $MSYS2_PACKAGES"
-        exit 1
-    fi
-    # shellcheck disable=SC2086
-    pacman -S --needed --noconfirm $MSYS2_PACKAGES
-    success "Пакеты MSYS2 установлены"
-}
-
 # System deps
 install_system_deps() {
     if [ "$XRAY_OS" = "windows" ]; then
-        # Вне MSYS2 системных пакетов нет: Python с python.org и uv.
-        [ "$WINDOWS_MSYS2" = "1" ] && install_windows_deps
+        # Системных пакетов нет: Python и зависимости ставит uv.
         return 0
     fi
     info "Проверка системных зависимостей..."
@@ -229,11 +193,6 @@ install_system_deps() {
 }
 
 install_python_deps() {
-    if [ "$WINDOWS_MSYS2" = "1" ]; then
-        # uv поставил бы PyGObject из PyPI, а его колесо без GTK не работает.
-        info "Python-зависимости на Windows приходят пакетами MSYS2, uv не нужен"
-        return 0
-    fi
     info "Проверка Python зависимостей..."
     
     if [ ! -f "$PROJECT_ROOT/pyproject.toml" ]; then
```

**Step 2: Проверка имитацией Git Bash на Linux**

Подменные `uname` и `uv` в `PATH` показывают, по какой ветке идёт сценарий; настоящий `uv sync` не запускается. Дальше сценарий захочет скачать xray для Windows — чтобы не качать, вывод обрывается на строке `uv sync` (`grep -m2` закрывает канал).

```bash
S=<scratchpad>; mkdir -p $S/shim
printf '#!/bin/sh\necho MINGW64_NT-10.0\n' > $S/shim/uname
printf '#!/bin/sh\necho "uv $*"\n' > $S/shim/uv
chmod +x $S/shim/uname $S/shim/uv
CI=true PATH="$S/shim:$PATH" bash core/scripts/install_dev.sh 2>&1 | grep -m2 -E "Система|uv sync"
uv run pytest tests/test_core_core_update.py -q --no-cov | tail -1   # 24 passed
```

Expected: `Система: Windows (bash, интерфейс Qt)` и `uv sync --extra windows --extra dev`.

**Step 3: Commit**

```bash
git add core/scripts/install_dev.sh
git commit -m "build: install_dev.sh без ветки MSYS2 — на Windows только uv и Qt"
```

---

### Task 4: GTK-интерфейс без Windows-веток

Каждое место, где GTK спрашивал `platform_layout`, сводится к ответу для Linux. Вместе с `platform_layout` уходят `style-windows.css`, `name_label.py`, картинки «Монолита» в карточке и Windows-ветка сигналов и активации в `application.py`.

**Files:**
- Delete: `src/ui/logic/platform_layout.py`, `src/ui/style-windows.css`, `src/ui/widgets/name_label.py`, `tests/test_ui_logic_platform_layout.py`, `tests/test_ui_application_signals.py`
- Modify: `src/ui/window.py`, `src/ui/dialogs/base.py`, `src/ui/dialogs/settings.py`, `src/ui/pages/monitoring.py`, `src/ui/pages/profiles.py`, `src/ui/pages/subscriptions.py`, `src/ui/widgets/status_card.py`, `src/ui/application.py`, `gui.py`, `Makefile`
- Modify (тесты): `tests/test_ui_styles.py` (переписывается), `tests/test_ui_widgets_status_card.py`, `tests/test_ui_platform_branches.py`, `tests/test_ui_tray_icons.py` (комментарий)

**Step 1: Тесты**

Сначала тесты: из них уходят проверки Windows-вида, Linux-проверки остаются. `tests/test_ui_styles.py` целиком: четыре Linux-теста, которые раньше шли параметром вместе с Windows-вариантом.

```python
"""Stylesheet loading, GTK CSS syntax and the layout it relies on."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.gtk


def test_stylesheet_is_loaded(monkeypatch):
    from src.ui import window

    loaded = []
    monkeypatch.setattr(window.Gdk.Display, "get_default", lambda: object())
    monkeypatch.setattr(
        window.Gtk.StyleContext,
        "add_provider_for_display",
        lambda _display, provider, _priority: loaded.append(provider),
    )
    window.load_css()

    assert len(loaded) == 1
    # Проверяем содержимое реально загруженного провайдера, а не только имя файла.
    assert b"Segoe UI" not in loaded[0].to_string().encode()


def test_stylesheet_parses_without_errors():
    from gi.repository import Gtk

    from src.ui import window

    errors = []
    provider = Gtk.CssProvider()
    provider.connect("parsing-error", lambda _provider, _section, error: errors.append(str(error)))
    provider.load_from_path(str(Path(window.__file__).with_name("style.css")))
    assert errors == []


def test_toast_overlay_covers_the_navigation(gtk_ready, monkeypatch):
    from types import SimpleNamespace

    from gi.repository import Adw

    from src.core.context import ProxyState
    from src.ui import window

    Adw.init()
    monkeypatch.setattr(window.MainWindow, "refresh_status", lambda _self: None)
    monkeypatch.setattr(window.MainWindow, "refresh_pages", lambda _self: None)
    context = SimpleNamespace(config=SimpleNamespace(window_size=""), proxy_state=ProxyState())
    main = window.MainWindow(application=None, context=context)
    try:
        ancestors = []
        parent = main.view_switcher_bar.get_parent()
        while parent is not None:
            ancestors.append(parent)
            parent = parent.get_parent()
        assert main.toast_overlay in ancestors
    finally:
        main.destroy()


def test_form_keeps_its_default_width(gtk_ready):
    from src.ui.dialogs.base import DEFAULT_WIDTH, FormDialog

    dialog = FormDialog("Тест", "Сохранить")
    assert dialog.page.get_size_request().width == DEFAULT_WIDTH
    assert dialog.get_follows_content_size()
```

Из `tests/test_ui_widgets_status_card.py` уходят фикстура `windows_card` и два теста на неё:

```diff
diff --git a/tests/test_ui_widgets_status_card.py b/tests/test_ui_widgets_status_card.py
index 3cd541d..4872374 100644
--- a/tests/test_ui_widgets_status_card.py
+++ b/tests/test_ui_widgets_status_card.py
@@ -113,28 +113,3 @@ def test_button_click_emits_signal(card):
     card.action_button.emit("clicked")
 
     assert seen == [True]
-
-
-@pytest.fixture
-def windows_card(gtk_ready, monkeypatch):
-    from src.core import platform_info
-    from src.ui.widgets.status_card import StatusCard
-
-    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
-    return StatusCard()
-
-
-def test_windows_card_shows_the_monolith_in_every_state(windows_card):
-    from src.ui.logic.status import ConnectionState
-
-    for state in ConnectionState:
-        windows_card.update(_view(state, error="boom"))
-        assert windows_card.shows_logo() is True
-
-
-def test_windows_card_colours_the_core_instead_of_spinning(windows_card):
-    from src.ui.logic.status import ConnectionState
-
-    windows_card.update(_view(ConnectionState.CONNECTING, profile_name="X"))
-
-    assert windows_card.is_spinning() is False
```

`tests/test_ui_platform_branches.py`: `IS_WINDOWS` в `src/ui` остаётся в `platform_texts.py` и `tray/controller.py` (последний уйдёт в задаче 5):

```diff
diff --git a/tests/test_ui_platform_branches.py b/tests/test_ui_platform_branches.py
index 695fff3..2e75849 100644
--- a/tests/test_ui_platform_branches.py
+++ b/tests/test_ui_platform_branches.py
@@ -1,9 +1,8 @@
 """Где интерфейс вправе проверять ОС напрямую.
 
-Отличия текстов собраны в `platform_texts`, компоновки — в `platform_layout`.
-Напрямую `IS_WINDOWS` читают только места, где меняется поведение, а не вид:
-флаги GApplication, сигналы и активация второго запуска, выбор трея.
-Новое отличие добавляется в один из двух модулей, а не `if` в виджете.
+Отличия текстов собраны в `platform_texts`. GTK-интерфейс работает только на
+Linux, Qt-интерфейс ОС не проверяет: Windows выбирает его в `gui.py`.
+Напрямую `IS_WINDOWS` читает только выбор трея.
 """
 
 from __future__ import annotations
@@ -14,8 +13,6 @@ UI = Path(__file__).resolve().parents[1] / "src" / "ui"
 
 ALLOWED = {
     "logic/platform_texts.py",
-    "logic/platform_layout.py",
-    "application.py",
     "tray/controller.py",
 }
 
@@ -27,4 +24,4 @@ def test_only_known_places_check_the_platform():
         if "IS_WINDOWS" in path.read_text(encoding="utf-8")
     )
 
-    assert set(offenders) <= ALLOWED, f"IS_WINDOWS вне platform_texts/platform_layout: {offenders}"
+    assert set(offenders) <= ALLOWED, f"IS_WINDOWS вне platform_texts: {offenders}"
```

```diff
diff --git a/tests/test_ui_tray_icons.py b/tests/test_ui_tray_icons.py
index 1b46bfa..9f07542 100644
--- a/tests/test_ui_tray_icons.py
+++ b/tests/test_ui_tray_icons.py
@@ -60,5 +60,5 @@ def test_the_icons_differ_from_each_other():
 
 @pytest.mark.parametrize("state", list(ConnectionState))
 def test_windows_status_card_has_a_monolith_per_state(state):
-    # Имена совпадают с MONOLITH_ASSETS карточки: виджет без дисплея не импортировать.
+    # Картинки карточки Qt-интерфейса (src/ui/qt/widgets/status_card.py).
     assert (icons_directory() / "win" / f"monolith-{state.value}.png").is_file()
```

`tests/test_ui_styles.py` в `make test-gtk`: раньше его запускал только CI Windows.

```diff
diff --git a/Makefile b/Makefile
index 6b7c99f..b4cbebb 100644
--- a/Makefile
+++ b/Makefile
@@ -91,7 +91,8 @@ test-cov:
 # Список собирается по маске, а не перечислением: забытый файл иначе молча
 # выпадает из прогона.
 GTK4_TESTS := $(wildcard tests/test_ui_application.py tests/test_ui_window.py \
-	tests/test_ui_widgets_*.py tests/test_ui_pages_*.py tests/test_ui_dialogs_*.py)
+	tests/test_ui_widgets_*.py tests/test_ui_pages_*.py tests/test_ui_dialogs_*.py \
+	tests/test_ui_styles.py)
 
 PYTEST_GTK := uv run pytest -m gtk $(GTK4_TESTS) -p no:cacheprovider --no-cov
 
```

```bash
git rm -q tests/test_ui_logic_platform_layout.py tests/test_ui_application_signals.py
```

**Step 2: Тесты до правки кода**

Run: `uv run pytest tests/test_ui_platform_branches.py -q --no-cov; make test-gtk 2>&1 | grep -E 'passed|failed' | tail -1`
Expected: `test_only_known_places_check_the_platform` падает и называет `application.py` и `logic/platform_layout.py`: эти ветки уходят на шагах 3–4. `make test-gtk` уже даёт 281 passed. Новые проверки стилей описывают Linux-вид, и он верен ещё до правки кода.

**Step 3: Удаление модулей**

```bash
git rm -q src/ui/logic/platform_layout.py src/ui/style-windows.css src/ui/widgets/name_label.py
```

**Step 4: Правки GTK-кода**

В каждом месте остаётся ветка, которая работала на Linux.

```diff
diff --git a/src/ui/window.py b/src/ui/window.py
index 3b7760c..54d9fc9 100644
--- a/src/ui/window.py
+++ b/src/ui/window.py
@@ -14,7 +14,6 @@ gi.require_version("Adw", "1")
 from gi.repository import Adw, Gdk, Gio, GLib, Gtk
 
 from src.core.config import get_asset_path
-from src.ui.logic import platform_layout
 from src.ui.logic.appearance import normalize_theme
 from src.ui.logic.geometry import (
     MIN_HEIGHT,
@@ -55,16 +54,15 @@ def load_css() -> None:
     if display is None:
         return
 
-    for name in platform_layout.stylesheets():
-        path = Path(__file__).with_name(name)
-        if not path.exists():
-            logger.warning("Stylesheet not found: %s", path)
-            continue
-        provider = Gtk.CssProvider()
-        provider.load_from_path(str(path))
-        Gtk.StyleContext.add_provider_for_display(
-            display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
-        )
+    path = Path(__file__).with_name("style.css")
+    if not path.exists():
+        logger.warning("Stylesheet not found: %s", path)
+        return
+    provider = Gtk.CssProvider()
+    provider.load_from_path(str(path))
+    Gtk.StyleContext.add_provider_for_display(
+        display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
+    )
 
 
 def apply_theme(theme: str | None) -> None:
@@ -126,12 +124,8 @@ class MainWindow(Adw.ApplicationWindow):
     def _build_ui(self) -> None:
         self.toast_overlay = Adw.ToastOverlay()
         toolbar = Adw.ToolbarView()
-        if platform_layout.toasts_above_navigation():
-            # Панели вне overlay: уведомления не закрывают нижние вкладки.
-            self.set_content(toolbar)
-        else:
-            self.set_content(self.toast_overlay)
-            self.toast_overlay.set_child(toolbar)
+        self.set_content(self.toast_overlay)
+        self.toast_overlay.set_child(toolbar)
 
         self.view_stack = Adw.ViewStack()
         self._add_pages()
@@ -168,11 +162,7 @@ class MainWindow(Adw.ApplicationWindow):
 
         self.view_stack.set_vexpand(True)
         content.append(self.view_stack)
-        if platform_layout.toasts_above_navigation():
-            self.toast_overlay.set_child(content)
-            toolbar.set_content(self.toast_overlay)
-        else:
-            toolbar.set_content(content)
+        toolbar.set_content(content)
 
     def _add_pages(self) -> None:
         self.profiles_page = ProfilesPage()
```

```diff
diff --git a/src/ui/dialogs/base.py b/src/ui/dialogs/base.py
index bee9ea9..394d8a1 100644
--- a/src/ui/dialogs/base.py
+++ b/src/ui/dialogs/base.py
@@ -9,8 +9,6 @@ gi.require_version("Adw", "1")
 
 from gi.repository import Adw, Gdk, Gtk
 
-from src.ui.logic import platform_layout
-
 DEFAULT_WIDTH = 520
 
 
@@ -49,11 +47,7 @@ class FormDialog(Adw.Dialog):
         self._toolbar.add_top_bar(header)
 
         self.page = Adw.PreferencesPage()
-        if platform_layout.adaptive_dialog_width():
-            self.set_follows_content_size(False)
-            self.set_content_width(560)
-        else:
-            self.page.set_size_request(DEFAULT_WIDTH, -1)
+        self.page.set_size_request(DEFAULT_WIDTH, -1)
         self._toolbar.set_content(self.page)
 
     def set_content_widget(self, widget: Gtk.Widget) -> None:
```

```diff
diff --git a/src/ui/dialogs/settings.py b/src/ui/dialogs/settings.py
index 614424d..1f2f2e7 100644
--- a/src/ui/dialogs/settings.py
+++ b/src/ui/dialogs/settings.py
@@ -19,7 +19,7 @@ from src.db.config import DnsProvider, ProxyMode, TlsFragmentSettings
 from src.db.data_store import DEFAULT_USER_AGENT, LEGACY_USER_AGENT
 from src.sub.device import ensure_hwid
 from src.sys import tun_access
-from src.ui.logic import platform_layout, platform_texts
+from src.ui.logic import platform_texts
 from src.ui.logic.appearance import THEME_LABELS, THEMES, normalize_theme
 from src.ui.logic.async_utils import run_in_background
 from src.ui.logic.routing_form import current_catalog, geo_summary
@@ -188,13 +188,10 @@ class SettingsDialog(Adw.PreferencesDialog):
         logs.add(self.log_level_row)
 
     def _build_monitoring_page(self) -> None:
-        if platform_layout.monitoring_on_general_settings_page():
-            page = self._general_page
-        else:
-            page = Adw.PreferencesPage(
-                title="Мониторинг", icon_name="utilities-system-monitor-symbolic"
-            )
-            self.add(page)
+        page = Adw.PreferencesPage(
+            title="Мониторинг", icon_name="utilities-system-monitor-symbolic"
+        )
+        self.add(page)
 
         group = Adw.PreferencesGroup(
             title="Проверка соединения",
```

```diff
diff --git a/src/ui/pages/monitoring.py b/src/ui/pages/monitoring.py
index 1ced1a3..d24d017 100644
--- a/src/ui/pages/monitoring.py
+++ b/src/ui/pages/monitoring.py
@@ -9,7 +9,6 @@ gi.require_version("Adw", "1")
 
 from gi.repository import Adw, GLib, GObject, Gtk, Pango
 
-from src.ui.logic import platform_layout
 from src.ui.logic.monitoring_view import (
     CLASS_DIM,
     CLASS_ERROR,
@@ -66,17 +65,7 @@ class MonitoringPage(Adw.PreferencesPage):
         scroll = Gtk.ScrolledWindow(min_content_height=160, max_content_height=260)
         scroll.set_child(self.log_view)
         group.add(scroll)
-        if platform_layout.wrapping_action_buttons():
-            buttons = Gtk.FlowBox(
-                selection_mode=Gtk.SelectionMode.NONE,
-                min_children_per_line=1,
-                max_children_per_line=3,
-                column_spacing=8,
-                row_spacing=8,
-            )
-            buttons.add_css_class("diagnostic-actions")
-        else:
-            buttons = Gtk.Box(spacing=8)
+        buttons = Gtk.Box(spacing=8)
         for label, callback in (
             ("Обновить журнал", self.refresh_diagnostics),
             ("Экспортировать", self._export_diagnostics),
```

```diff
diff --git a/src/ui/pages/profiles.py b/src/ui/pages/profiles.py
index c0fb737..3e447e5 100644
--- a/src/ui/pages/profiles.py
+++ b/src/ui/pages/profiles.py
@@ -20,7 +20,6 @@ from src.ui.logic.profiles_view import (
     build_profile_rows,
     ping_text,
 )
-from src.ui.widgets.name_label import name_label
 
 _ACTIVE_CLASS = "profile-active"
 _GROUP_CLASS = "profile-group"
@@ -336,7 +335,7 @@ class ProfilesPage(Gtk.Box):
         icon = Gtk.Image()
         box.append(icon)
 
-        label = name_label(xalign=0.0)
+        label = Gtk.Label(xalign=0.0)
         label.set_ellipsize(Pango.EllipsizeMode.END)
         label.set_hexpand(True)
         box.append(label)
```

```diff
diff --git a/src/ui/pages/subscriptions.py b/src/ui/pages/subscriptions.py
index b193bc6..b417e17 100644
--- a/src/ui/pages/subscriptions.py
+++ b/src/ui/pages/subscriptions.py
@@ -12,7 +12,6 @@ gi.require_version("Adw", "1")
 
 from gi.repository import Adw, Gio, GObject, Gtk, Pango
 
-from src.ui.logic import platform_layout
 from src.ui.logic.subscriptions_view import (
     EMPTY_RESPONSE_HINT,
     EMPTY_RESPONSE_TEXT,
@@ -105,8 +104,6 @@ class SubscriptionsPage(Gtk.Box):
         action_row = Adw.ActionRow()
         action_row.set_use_markup(False)
         action_row.set_title(row.name)
-        if platform_layout.compact_subscription_rows():
-            action_row.set_title_lines(2)
         action_row.set_subtitle(row.url)
         action_row.set_subtitle_lines(1)
         action_row.set_activatable(True)
@@ -121,18 +118,10 @@ class SubscriptionsPage(Gtk.Box):
         meta = Gtk.Label(label=f"{row.profile_count} · {row.updated_text}", xalign=1.0)
         meta.add_css_class("dim-label")
         meta.add_css_class("caption")
-        if platform_layout.compact_subscription_rows():
-            meta.set_max_width_chars(18)
-            meta.set_ellipsize(Pango.EllipsizeMode.END)
-            meta.set_tooltip_text(meta.get_text())
         meta_box.append(meta)
         if row.details_text:
             details = Gtk.Label(label=row.details_text, xalign=1.0)
             details.add_css_class("caption")
-            if platform_layout.compact_subscription_rows():
-                details.set_max_width_chars(18)
-                details.set_ellipsize(Pango.EllipsizeMode.END)
-                details.set_tooltip_text(row.details_text)
             # Истёкшую подписку видно сразу: серверов в ней обычно уже нет.
             details.add_css_class("error" if row.expired else "dim-label")
             meta_box.append(details)
@@ -143,9 +132,6 @@ class SubscriptionsPage(Gtk.Box):
             empty.add_css_class("caption")
             empty.add_css_class("error")
             empty.set_tooltip_text(EMPTY_RESPONSE_HINT)
-            if platform_layout.compact_subscription_rows():
-                empty.set_max_width_chars(18)
-                empty.set_ellipsize(Pango.EllipsizeMode.END)
             meta_box.append(empty)
             self._empty_labels[row.group_id] = empty
         action_row.add_suffix(meta_box)
```

```diff
diff --git a/src/ui/widgets/status_card.py b/src/ui/widgets/status_card.py
index 7b657c2..7dbe827 100644
--- a/src/ui/widgets/status_card.py
+++ b/src/ui/widgets/status_card.py
@@ -13,9 +13,7 @@ gi.require_version("GdkPixbuf", "2.0")
 from gi.repository import Gdk, GdkPixbuf, GLib, GObject, Gtk, Pango
 
 from src.core.config import get_asset_path
-from src.ui.logic import platform_layout
 from src.ui.logic.status import StatusView
-from src.ui.widgets.name_label import name_label
 
 logger = logging.getLogger("tenga.ui.status_card")
 
@@ -29,10 +27,6 @@ _STATE_CLASSES = (
     "status-error",
 )
 _BUTTON_CLASSES = ("suggested-action", "destructive-action")
-MONOLITH_ASSETS = {
-    css_class: f"icons/win/monolith-{css_class.removeprefix('status-')}.png"
-    for css_class in _STATE_CLASSES
-}
 
 
 def _load_logo_textures() -> tuple[Gdk.Texture, Gdk.Texture] | None:
@@ -58,24 +52,6 @@ def _load_logo_textures() -> tuple[Gdk.Texture, Gdk.Texture] | None:
     return Gdk.Texture.new_for_pixbuf(colour), Gdk.Texture.new_for_pixbuf(grey)
 
 
-def _load_monolith_textures() -> dict[str, Gdk.Texture] | None:
-    """Load the Windows logo, one picture per state class.
-
-    Возвращает None, если хоть одного файла нет: тогда карточка ведёт себя как
-    на Linux, а не показывает монолит в одних состояниях и иконку в других.
-    """
-    textures = {}
-    for css_class, asset in MONOLITH_ASSETS.items():
-        path = get_asset_path(asset)
-        try:
-            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(str(path), LOGO_SIZE, LOGO_SIZE)
-        except GLib.Error as exc:
-            logger.warning("Monolith logo %s not loaded, using the common one: %s", path, exc)
-            return None
-        textures[css_class] = Gdk.Texture.new_for_pixbuf(pixbuf)
-    return textures
-
-
 class StatusCard(Gtk.Box):
     """Card showing the connection state and the primary action button."""
 
@@ -95,9 +71,6 @@ class StatusCard(Gtk.Box):
         self.set_margin_end(12)
 
         self._logo = _load_logo_textures()
-        self._monolith = (
-            _load_monolith_textures() if platform_layout.monolith_status_logo() else None
-        )
 
         self._icon = Gtk.Image(icon_name="network-offline-symbolic", pixel_size=32)
         self._icon.add_css_class("status-icon")
@@ -115,7 +88,7 @@ class StatusCard(Gtk.Box):
         self._title.add_css_class("heading")
         text_box.append(self._title)
 
-        self._subtitle = name_label(xalign=0.0)
+        self._subtitle = Gtk.Label(xalign=0.0)
         self._subtitle.add_css_class("dim-label")
         self._subtitle.set_ellipsize(Pango.EllipsizeMode.END)
         text_box.append(self._subtitle)
@@ -143,8 +116,7 @@ class StatusCard(Gtk.Box):
         self._metrics.set_visible(bool(view.metrics))
 
         self._set_icon(view)
-        # Монолит показывает подключение янтарным ядром, спиннер рядом лишний.
-        spinning = view.show_spinner and self._monolith is None
+        spinning = view.show_spinner
         self._icon.set_visible(not spinning)
 
         self._spinner.set_visible(spinning)
@@ -164,13 +136,6 @@ class StatusCard(Gtk.Box):
 
     def _set_icon(self, view: StatusView) -> None:
         """Show the logo where the view asks for it, else a themed icon."""
-        if self._monolith is not None:
-            self._icon.set_pixel_size(LOGO_SIZE)
-            self._icon.add_css_class("status-logo")
-            self._icon.add_css_class("status-monolith")
-            self._icon.set_from_paintable(self._monolith[view.css_class])
-            return
-
         if not view.use_logo or self._logo is None:
             self._icon.set_pixel_size(32)
             self._icon.remove_css_class("status-logo")
```

`src/ui/application.py`: без `platform_info`, параметра `lock_path`, `NON_UNIQUE`, Windows-ветки сигналов и сервера активации.

```diff
diff --git a/src/ui/application.py b/src/ui/application.py
index b56fb77..8f85d5b 100644
--- a/src/ui/application.py
+++ b/src/ui/application.py
@@ -13,7 +13,6 @@ gi.require_version("Adw", "1")
 
 from gi.repository import Adw, Gio, GLib, Gtk
 
-from src.core import platform_info
 from src.core.context import AppContext, get_context
 from src.core.core_update import fetch_releases
 from src.core.main_loop import GLibLoop
@@ -166,18 +165,10 @@ class TengaApplication(Adw.Application):
         lock=None,
         *,
         with_tray: bool = False,
-        lock_path=None,
     ) -> None:
-        flags = Gio.ApplicationFlags.HANDLES_OPEN
-        if platform_info.IS_WINDOWS:
-            # Уникальность GApplication держится на D-Bus, которой на Windows нет;
-            # её обеспечивают mutex и pipe активации (src/sys/windows).
-            flags |= Gio.ApplicationFlags.NON_UNIQUE
-        super().__init__(application_id=APP_ID, flags=flags)
+        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN)
         self.context = context or get_context()
         self._lock = lock
-        self._lock_path = lock_path
-        self._activation = None
         self.tray = None
         self._with_tray = with_tray
         self._signal_source_ids: list[int] = []
@@ -206,7 +197,6 @@ class TengaApplication(Adw.Application):
         apply_theme(getattr(self.context.config, "theme", None))
         self._register_actions()
         self._setup_signal_handlers()
-        self._start_activation_server()
         self.watch_monitor()
         if self._with_tray:
             self.start_tray()
@@ -239,7 +229,6 @@ class TengaApplication(Adw.Application):
         for source_id in self._signal_source_ids:
             GLib.source_remove(source_id)
         self._signal_source_ids.clear()
-        self._stop_activation_server()
 
         if self._lock is not None:
             self._lock.release()
@@ -591,54 +580,19 @@ class TengaApplication(Adw.Application):
     # Сигналы
 
     def _setup_signal_handlers(self) -> None:
-        """Deliver SIGINT/SIGTERM through the GLib main loop (safe for GTK).
-
-        На Windows `GLib.unix_signal_add` нет, а закрытие приходит оконными
-        сообщениями, которые GTK обрабатывает сам.
-        """
-        if platform_info.IS_WINDOWS:
-            self._signal_source_ids = []
-            return
+        """Deliver SIGINT/SIGTERM through the GLib main loop (safe for GTK)."""
         self._signal_source_ids = [
             GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, self._on_signal, signum)
             for signum in (signal.SIGINT, signal.SIGTERM)
         ]
 
-    # Активация второго запуска на Windows
-
-    def _start_activation_server(self) -> None:
-        if not platform_info.IS_WINDOWS or self._lock is None or self._lock_path is None:
-            return
-        from src.sys.windows.activation import ActivationServer, pipe_address
-
-        def deliver(uris: list[str]) -> None:
-            def _apply() -> bool:
-                self.activate()
-                for uri in uris:
-                    self.import_app_link(uri)
-                return GLib.SOURCE_REMOVE
-
-            GLib.idle_add(_apply)
-
-        try:
-            self._activation = ActivationServer(pipe_address(str(self._lock_path)), deliver)
-            self._activation.start()
-        except OSError as e:
-            logger.warning("Activation server did not start: %s", e)
-            self._activation = None
-
-    def _stop_activation_server(self) -> None:
-        if self._activation is not None:
-            self._activation.stop()
-            self._activation = None
-
     def _on_signal(self, signum: int) -> bool:
         logger.info("Received signal %s, terminating application", signum)
         self.quit()
         return GLib.SOURCE_REMOVE
 
 
-def run_app(config_dir=None, lock=None, with_tray: bool = True, uris=(), lock_path=None) -> int:
+def run_app(config_dir=None, lock=None, with_tray: bool = True, uris=()) -> int:
     """Entry point for the GTK4 interface."""
     from src.core.context import init_context
     from src.core.monitor import attach_monitor
@@ -648,7 +602,7 @@ def run_app(config_dir=None, lock=None, with_tray: bool = True, uris=(), lock_pa
     # подключение не начинает наблюдение — `ConnectionService` запускает уже
     # готовый монитор, но сам его не создаёт.
     attach_monitor(context)
-    app = TengaApplication(context=context, lock=lock, with_tray=with_tray, lock_path=lock_path)
+    app = TengaApplication(context=context, lock=lock, with_tray=with_tray)
     app.set_release_fetcher(fetch_releases)
     from src.core.app_update import fetch_app_releases
     from src.sub.route import local_proxy_url
```

`gui.py`: подсказка для `--ui gtk` на Windows; `lock_path` и pipe активации получает только Qt.

```diff
diff --git a/gui.py b/gui.py
index 22247e0..49b1db9 100755
--- a/gui.py
+++ b/gui.py
@@ -78,7 +78,7 @@ def gtk_install_hint() -> str:
     from src.core import platform_info
 
     if platform_info.IS_WINDOWS:
-        return "Среда GTK входит в установщик: переустановите Veblock."
+        return "Интерфейс GTK на Windows не поддерживается: запустите Veblock без --ui gtk."
     return "Установите пакеты: sudo apt install python3-gi gir1.2-gtk-4.0 gir1.2-adw-1"
 
 
@@ -247,14 +247,14 @@ def main() -> int:
         options = {
             "config_dir": args.config_dir,
             "lock": single_instance if holds_lock else None,
-            "lock_path": lock_file,
             "with_tray": not args.no_tray,
             "uris": args.uris,
         }
         if FRONTEND == "qt":
             from src.ui.qt.application import run_app
 
-            return run_app(**options, accept_activation=IS_WINDOWS)
+            # Pipe активации второго запуска — только на Windows.
+            return run_app(**options, lock_path=lock_file, accept_activation=IS_WINDOWS)
         from src.ui.application import run_app
 
         return run_app(**options)
```

**Step 5: Проверка**

```bash
git grep -n "platform_layout\|name_label\|style-windows" -- src tests gui.py Makefile   # пусто
uv run pytest -q --no-cov -p no:cacheprovider | tail -1   # 1578 passed, 10 skipped
make test-gtk 2>&1 | grep -E 'passed|failed' | tail -1                              # 281 passed (279 + 4 test_ui_styles − 2 status_card)
make test-tray 2>&1 | grep -E 'passed|failed' | tail -1                             # 146 passed, 5 skipped
make test-qt 2>&1 | grep -E 'passed|failed' | tail -1                               # 137 passed
python cli.py lint-all
```

`make test-gtk` печатает в stderr сообщения fuse и D-Bus песочницы — это не ошибки, итог в строке с `passed`. Если ruff ругается на порядок импортов (`I001`) или формат, исправь `python cli.py lint --fix` и `python cli.py format`.

Ручная проверка на Linux (живой дисплей): `python gui.py` — окно, карточка, страницы «Серверы», «Подписки», «Мониторинг», настройки выглядят как до задачи.

**Step 6: Commit**

```bash
git add -A src/ui gui.py Makefile tests
git commit -m "refactor(ui): GTK-интерфейс без Windows-веток — на Windows работает Qt"
```

---

### Task 5: Win32-трей и BMP-флаги удалены

Трей Windows с фазы 2 — `QSystemTrayIcon` (`QtTrayItem`), который `QtApplication` передаёт в `TrayController`. Win32-трей больше никто не создаёт. Из него остаётся только сборщик `.ico`.

**Files:**
- Move: `src/ui/tray/win32/ico.py` → `packaging/windows/ico.py`; `tests/test_ui_tray_win32_ico.py` → `tests/test_packaging_ico.py`
- Delete: остаток `src/ui/tray/win32/`, `tests/test_ui_tray_win32_{item,flags,menu}.py`, `tools/make_flag_bitmaps.py`, `assets/flags/win/`
- Modify: `src/ui/tray/controller.py`, `tools/make_ico.py`, `core/scripts/build_deb.sh`, `tests/test_ui_tray_controller.py`, `tests/test_ui_platform_branches.py`

**Step 1: Перенос сборщика `.ico`**

```bash
git mv src/ui/tray/win32/ico.py packaging/windows/ico.py
git mv tests/test_ui_tray_win32_ico.py tests/test_packaging_ico.py
```

`packaging/windows` — не пакет Python, поэтому тест загружает модуль по пути:

```diff
diff --git a/tests/test_packaging_ico.py b/tests/test_packaging_ico.py
index f5f53c8..5c24d2b 100644
--- a/tests/test_packaging_ico.py
+++ b/tests/test_packaging_ico.py
@@ -2,9 +2,15 @@
 
 from __future__ import annotations
 
+import importlib.util
 import struct
+from pathlib import Path
 
-from src.ui.tray.win32.ico import build_ico
+_PATH = Path(__file__).resolve().parents[1] / "packaging" / "windows" / "ico.py"
+_SPEC = importlib.util.spec_from_file_location("ico", _PATH)
+_ico = importlib.util.module_from_spec(_SPEC)
+_SPEC.loader.exec_module(_ico)
+build_ico = _ico.build_ico
 
 PNG_16 = b"\x89PNG\r\n\x1a\n" + b"a" * 20
 PNG_256 = b"\x89PNG\r\n\x1a\n" + b"b" * 30
```

```diff
diff --git a/tools/make_ico.py b/tools/make_ico.py
index a9f9c7b..5fbb818 100644
--- a/tools/make_ico.py
+++ b/tools/make_ico.py
@@ -23,9 +23,12 @@ from gi.repository import GdkPixbuf
 
 ROOT = Path(__file__).resolve().parent.parent
 sys.path.insert(0, str(ROOT))
+# Сборщик ICO лежит рядом со spec: им пользуются только инструменты сборки.
+sys.path.insert(0, str(ROOT / "packaging" / "windows"))
+
+from ico import build_ico
 
 from src.ui.tray.icons import ICON_CONNECTED, ICON_CONNECTING, ICON_DISCONNECTED
-from src.ui.tray.win32.ico import build_ico
 
 TEMPLATES = ROOT / "packaging" / "windows" / "icons"
 OUT_DIR = ROOT / "assets" / "icons" / "win"
```

**Step 2: Сборщик даёт те же файлы**

```bash
uv run pytest tests/test_packaging_ico.py -q --no-cov | tail -1
uv run python tools/make_ico.py && git status --short assets packaging
```

Expected: тесты проходят; после перегенерации `git status` показывает только перенос `ico.py`, изменённых `.ico` нет.

**Step 3: Тесты трея**

Тест выбора Win32-элемента уходит, `IS_WINDOWS` в `src/ui` остаётся только в `platform_texts.py`:

```diff
diff --git a/tests/test_ui_tray_controller.py b/tests/test_ui_tray_controller.py
index 5c8c999..ef13651 100644
--- a/tests/test_ui_tray_controller.py
+++ b/tests/test_ui_tray_controller.py
@@ -229,22 +229,3 @@ def test_a_state_change_is_delivered_through_the_dispatcher(context):
     context.proxy_state.set_running(profile_id=1)
 
     assert len(delivered) == 1
-
-
-def test_windows_uses_win32_item(monkeypatch):
-    from src.core import platform_info
-    from src.ui.tray import controller
-    from src.ui.tray.win32 import item as win32_item
-
-    monkeypatch.setattr(platform_info, "IS_WINDOWS", True)
-    created = []
-
-    class FakeItem:
-        def __init__(self, **_kwargs):
-            created.append(self)
-
-    monkeypatch.setattr(win32_item, "Win32TrayItem", FakeItem)
-
-    controller.TrayController(object(), object())
-
-    assert len(created) == 1
```

```diff
diff --git a/tests/test_ui_platform_branches.py b/tests/test_ui_platform_branches.py
index 2e75849..6571d7e 100644
--- a/tests/test_ui_platform_branches.py
+++ b/tests/test_ui_platform_branches.py
@@ -2,7 +2,6 @@
 
 Отличия текстов собраны в `platform_texts`. GTK-интерфейс работает только на
 Linux, Qt-интерфейс ОС не проверяет: Windows выбирает его в `gui.py`.
-Напрямую `IS_WINDOWS` читает только выбор трея.
 """
 
 from __future__ import annotations
@@ -13,7 +12,6 @@ UI = Path(__file__).resolve().parents[1] / "src" / "ui"
 
 ALLOWED = {
     "logic/platform_texts.py",
-    "tray/controller.py",
 }
 
 
```

**Step 4: Удаление**

```bash
git rm -rq src/ui/tray/win32 assets/flags/win tools/make_flag_bitmaps.py \
  tests/test_ui_tray_win32_item.py tests/test_ui_tray_win32_flags.py tests/test_ui_tray_win32_menu.py
```

`TrayController` по умолчанию создаёт только SNI-элемент:

```diff
diff --git a/src/ui/tray/controller.py b/src/ui/tray/controller.py
index 956330e..d7701f5 100644
--- a/src/ui/tray/controller.py
+++ b/src/ui/tray/controller.py
@@ -32,13 +32,7 @@ def _default_dispatch(fn: Callable[..., object], *args: object) -> None:
 
 
 def _default_item():
-    """Панель Linux говорит по D-Bus (SNI), Windows — через Shell_NotifyIcon."""
-    from src.core import platform_info
-
-    if platform_info.IS_WINDOWS:
-        from src.ui.tray.win32 import item as win32_item
-
-        return win32_item.Win32TrayItem()
+    """Панель Linux говорит по D-Bus (SNI); Qt-интерфейс передаёт свой элемент."""
     from src.ui.tray.sni import StatusNotifierItem
 
     return StatusNotifierItem()
```

`build_deb.sh` больше не исключает из пакета удалённый каталог:

```diff
diff --git a/core/scripts/build_deb.sh b/core/scripts/build_deb.sh
index 2144aae..b9066dc 100755
--- a/core/scripts/build_deb.sh
+++ b/core/scripts/build_deb.sh
@@ -57,9 +57,9 @@ stage_files() {
     rm -rf "$PKG_ROOT/$LIB_DIR/src/"*.egg-info
     cp "$PROJECT_ROOT/gui.py" "$PKG_ROOT/$LIB_DIR/"
     cp -r "$PROJECT_ROOT/assets" "$PKG_ROOT/$LIB_DIR/"
-    # Снимки экрана и исходники логотипа — для README, ICO и BMP — для Windows.
+    # Снимки экрана и исходники логотипа — для README, ICO — для Windows.
     rm -rf "$PKG_ROOT/$LIB_DIR/assets/"{screen-*.png,logo_inner.png,tenga-proxy.png,*.ico} \
-        "$PKG_ROOT/$LIB_DIR/assets/icons/win" "$PKG_ROOT/$LIB_DIR/assets/flags/win"
+        "$PKG_ROOT/$LIB_DIR/assets/icons/win"
 
     install -m 0755 "$PROJECT_ROOT/core/bin/xray" "$PKG_ROOT/$LIB_DIR/core/bin/xray"
     # Геобазы: без них правила geosite:/geoip: роняют запуск ядра.
```

**Step 5: Проверка**

```bash
git grep -n "tray.win32\|tray/win32\|flags/win\|make_flag_bitmaps\|platform_layout" \
  -- '*.py' '*.spec' '*.sh' Makefile   # пусто
uv run pytest -q --no-cov -p no:cacheprovider | tail -1   # 1565 passed, 5 skipped
make test-tray 2>&1 | grep -E 'passed|failed' | tail -1                             # 131 passed
make test-gtk 2>&1 | grep -E 'passed|failed' | tail -1                              # 281 passed
make test-qt 2>&1 | grep -E 'passed|failed' | tail -1                               # 137 passed
python cli.py lint-all
```

Пять пропусков вместо десяти: пропускались Windows-тесты Win32-трея, они удалены. `windows.yml` ещё упоминает `test_ui_tray_win32_*` — это задача 6.

**Step 6: Commit**

```bash
git add -A src/ui/tray packaging/windows tools tests assets/flags core/scripts/build_deb.sh
git commit -m "refactor: Win32-трей и BMP-флаги удалены — трей Windows теперь QSystemTrayIcon"
```

---

### Task 6: CI Windows без MSYS2

**Files:**
- Modify: `.github/workflows/windows.yml` (переписывается целиком)

**Step 1: Новый workflow**

Git Bash, `setup-python` 3.12 и `setup-uv`; `install_dev.sh` ставит окружение и xray. Windows-набор теперь без `test_ui_tray_win32_*`, зато с `tests/test_packaging_*.py`. GTK-тесты заменены Qt-тестами (обязательными). После сборки добавлен смоук собранного exe. Шаги после upload — как были, только `uv run`.

```yaml
name: Windows

on:
  push:
    branches: [develop, master]
    tags: ["v*"]
  pull_request:
  workflow_dispatch:

# Публикация установщика в релиз по тегу.
permissions:
  contents: write

jobs:
  build:
    runs-on: windows-latest
    defaults:
      run:
        # Git Bash: те же сценарии, что у разработчика на Windows.
        shell: bash
    env:
      # install_dev.sh отвечает на свои вопросы по умолчанию.
      CI: "true"
      # Как в собранном exe (PYTHON_OPTIONS в spec): UTF-8 вместо cp1252.
      PYTHONUTF8: "1"
      # uv берёт Python раннера, а не скачивает 3.11 из .python-version.
      UV_PYTHON: "3.12"
      UV_PYTHON_PREFERENCE: only-system
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - uses: astral-sh/setup-uv@v5

      - name: Inno Setup
        shell: pwsh
        run: |
          if (-not (Test-Path "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe")) {
            choco install innosetup --no-progress -y
          }

      # uv sync --extra windows --extra dev, xray.exe, wintun.dll, геобазы.
      - name: Environment
        run: bash core/scripts/install_dev.sh

      # Windows-код и общая логика: обязаны проходить.
      - name: Windows tests
        run: |
          uv run pytest -q --no-cov -p no:cacheprovider \
            tests/test_core_platform_info.py tests/test_sys_facades.py \
            tests/test_sys_windows_*.py tests/test_winsvc_*.py \
            tests/test_packaging_*.py tests/test_cli_build.py \
            tests/test_sys_tun_access.py tests/test_core_net_journal.py \
            tests/test_ui_logic_platform_*.py tests/test_ui_platform_branches.py

      # Интерфейс Windows: платформа offscreen, окна на рабочий стол не выходят.
      - name: Qt UI tests
        env:
          QT_QPA_PLATFORM: offscreen
        run: uv run pytest -q --no-cov -p no:cacheprovider -m qt tests/test_ui_qt_*.py

      # Весь набор: тесты Linux-реализаций здесь падать вправе, прогон
      # показывает, что ещё зависит от POSIX.
      - name: Full test suite (informational)
        continue-on-error: true
        run: uv run pytest -q -rfE --no-cov -p no:cacheprovider --continue-on-collection-errors

      - name: Build installer
        run: bash core/scripts/build_windows.sh

      # Собранный GUI стартует: в оконном exe нет stdout, поэтому проверка —
      # по журналу. Свой каталог настроек, чтобы не задеть ничего на раннере.
      - name: Frozen GUI smoke
        shell: pwsh
        env:
          QT_QPA_PLATFORM: offscreen
        run: |
          $app = "dist\windows\tenga-proxy"
          if (Test-Path "$app\_internal\gi") { throw "В сборку попал PyGObject" }
          $size = (Get-ChildItem -Recurse $app | Measure-Object Length -Sum).Sum / 1MB
          "Размер каталога: {0:N0} МБ" -f $size

          $env:TENGA_CONFIG_DIR = Join-Path $env:RUNNER_TEMP "veblock-smoke"
          $log = Join-Path $env:TENGA_CONFIG_DIR "logs\tenga_gui.log"
          $proc = Start-Process "$app\tenga-proxy.exe" -ArgumentList "--no-tray" -PassThru
          Start-Sleep -Seconds 10
          $alive = -not $proc.HasExited
          if ($alive) { Stop-Process -Id $proc.Id -Force }
          Get-Content $log -ErrorAction SilentlyContinue
          if (-not $alive) { throw "tenga-proxy.exe завершился сам, код $($proc.ExitCode)" }
          if (-not (Select-String -Path $log -Pattern "Frontend: qt" -Quiet)) {
            throw "В журнале нет «Frontend: qt»"
          }
          if (Select-String -Path $log -Pattern "Traceback" -Quiet) {
            throw "В журнале исключение"
          }

      - uses: actions/upload-artifact@v4
        with:
          name: tenga-proxy-windows-setup
          path: dist/windows/*.exe
          if-no-files-found: error

      # Тег создаёт владелец при выпуске версии; v0.18.0 обязан собрать 0.18.0.
      - name: Tag matches version
        if: startsWith(github.ref, 'refs/tags/v')
        run: |
          VERSION="$(uv run python -c 'import runpy; print(runpy.run_path("packaging/windows/version_info.py")["project_version"]())')"
          [ "v$VERSION" = "${{ github.ref_name }}" ] || { echo "Тег ${{ github.ref_name }} не совпадает с версией $VERSION"; exit 1; }

      - name: Attach installer to release
        if: startsWith(github.ref, 'refs/tags/v')
        shell: pwsh
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          $tag = "${{ github.ref_name }}"
          gh release view $tag 2>$null
          if ($LASTEXITCODE -ne 0) { gh release create $tag --draft --title $tag --notes "" }
          gh release upload $tag (Get-Item dist\windows\*.exe).FullName --clobber

      # Служба из собранного каталога: TUN, маршруты, NRPT и их откат на
      # настоящей Windows. Маршруты /1 на секунды перехватывают сеть раннера,
      # поэтому окно с ними в тестах минимальное.
      - name: Install service from build
        shell: pwsh
        run: |
          & dist\windows\tenga-proxy\tenga-proxy-svc.exe install
          Start-Sleep -Seconds 3
          Get-Service TengaProxySvc

      - name: Service integration tests
        timeout-minutes: 5
        env:
          TENGA_SERVICE_TESTS: "1"
        run: uv run pytest tests/integration -m windows -p no:cacheprovider --no-cov -v

      - name: Service log
        if: always()
        shell: pwsh
        run: |
          Get-ChildItem -Recurse "$env:ProgramData\tenga-proxy" -ErrorAction SilentlyContinue
          Get-Content "$env:ProgramData\tenga-proxy\logs\*" -ErrorAction SilentlyContinue

      - name: Remove service
        if: always()
        shell: pwsh
        run: |
          $svc = "dist\windows\tenga-proxy\tenga-proxy-svc.exe"
          if (Test-Path $svc) {
            & $svc remove
            & $svc cleanup
          }
```

**Step 2: Локальные проверки**

```bash
uv run python -c "import yaml; d = yaml.safe_load(open('.github/workflows/windows.yml')); print(len(d['jobs']['build']['steps']))"   # 17
grep -n "msys\|venv-win" .github/workflows/windows.yml   # пусто
uv run pytest -q --no-cov -p no:cacheprovider \
  tests/test_core_platform_info.py tests/test_sys_facades.py \
  tests/test_sys_windows_*.py tests/test_winsvc_*.py \
  tests/test_packaging_*.py tests/test_cli_build.py \
  tests/test_sys_tun_access.py tests/test_core_net_journal.py \
  tests/test_ui_logic_platform_*.py tests/test_ui_platform_branches.py | tail -1   # 194 passed, 2 skipped
```

Если установлены `actionlint` или `shellcheck`, прогони и их.

**Step 3: Commit**

```bash
git add .github/workflows/windows.yml
git commit -m "ci(windows): сборка и тесты без MSYS2 — uv, Qt, смоук собранного exe"
```

Первый настоящий прогон — после push, который делает владелец (задача 8).

---

### Task 7: Документация

**Files:**
- Modify: `CLAUDE.md`, `AGENTS.md`, `README.md`, `docs/{ru,en}/development.md`, `docs/{ru,en}/installation.md`, `docs/{ru,en}/index.md`, `docs/{ru,en}/overview.md`, `docs/plans/2026-10-28-windows-qt-frontend-design.md`

**Step 1: Правки**

Убираются MSYS2, `.venv-win`, `platform_layout` и `src/ui/tray/win32/`. Описываются Git Bash + uv, Qt на Windows, проверка состава сборки и смоук в CI. В дизайн-документ добавляются уточнения по итогам фазы 4.

```diff
diff --git a/CLAUDE.md b/CLAUDE.md
index e984620..9cf4212 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -4,7 +4,7 @@ This file provides guidance to Claude Code (claude.ai/code) when working with co
 
 ## Project Overview
 
-Veblock (ранее Tenga Proxy) - это клиент прокси для Linux и Windows с backend xray-core. Поддерживает протоколы VLESS, Trojan, VMess, Shadowsocks, SOCKS и HTTP. Имеет CLI и GTK GUI интерфейс с системным треем.
+Veblock (ранее Tenga Proxy) - это клиент прокси для Linux и Windows с backend xray-core. Поддерживает протоколы VLESS, Trojan, VMess, Shadowsocks, SOCKS и HTTP. Имеет CLI и GUI с системным треем: GTK 4 на Linux, Qt (PySide6) на Windows.
 
 ## Common Commands
 
@@ -114,7 +114,7 @@ src/
 │   ├── profiles.py    # ProfileEntry, ProfileStore - управление профилями
 │   ├── data_store.py  # Низкоуровневое хранилище (JSON файлы)
 │   └── config.py      # Настройки (routing, VPN, DNS)
-├── ui/            # GTK4 + libadwaita интерфейс
+├── ui/            # GTK4 + libadwaita интерфейс (Linux)
 │   ├── application.py # TengaApplication - Adw.Application, действия, трей
 │   ├── controller.py  # AppController - оркестровка без GTK, протокол Shell
 │   ├── qt/            # Интерфейс PySide6 (Windows; на Linux — gui.py --ui qt)
@@ -122,7 +122,7 @@ src/
 │   ├── pages/         # Страницы: профили, подписки, мониторинг
 │   ├── widgets/       # Виджеты (статус-карточка)
 │   ├── dialogs/       # Диалоги на Adw.Dialog / Adw.PreferencesDialog
-│   ├── tray/          # StatusNotifierItem + com.canonical.dbusmenu; win32/ — трей Windows
+│   ├── tray/          # TrayController; StatusNotifierItem + com.canonical.dbusmenu
 │   ├── logic/         # Логика без GTK: форматирование, задержка, формы
 │   └── models/        # Модели и фильтры списков
 ├── sys/           # Системные функции: фасады, реализация выбирается по ОС
@@ -194,9 +194,10 @@ True), `cancel`. `ConnectionMonitor` и `AppController` получают его
 `tests/test_sys_facades.py`. Windows-модули импортируются и на Linux
 (pywin32, winreg и ctypes — лениво), поэтому тестируются обычным pytest.
 
-**Отличия UI по ОС** - тексты в `src/ui/logic/platform_texts.py`, компоновка
-в `src/ui/logic/platform_layout.py`. Виджеты `IS_WINDOWS` не читают; где это
-допустимо, перечисляет `tests/test_ui_platform_branches.py`.
+**Отличия UI по ОС** - GTK работает на Linux, Qt на Windows; общие для обоих
+тексты с отличиями по ОС — в `src/ui/logic/platform_texts.py`. Виджеты
+`IS_WINDOWS` не читают; где это допустимо, перечисляет
+`tests/test_ui_platform_branches.py`.
 
 **TUN на Linux** - xray получает `cap_net_admin` через `setcap` в postinst
 deb-пакета, маршрут по умолчанию переключает помощник
@@ -340,10 +341,9 @@ profiles = parse_subscription_content(content)  # List[ProxyBean]
   win32 пропускаются. `tests/integration/` — служба на живой Windows (нужны
   установленная служба, права администратора и `TENGA_SERVICE_TESTS=1`);
   запускается в CI
-- Windows-разработка — Git Bash, CPython с python.org и uv
+- Windows-разработка — Git Bash, CPython 3.12 с python.org и uv
   (`bash core/scripts/install_dev.sh` ставит `--extra windows --extra dev`).
-  MSYS2 UCRT64 нужна только прежней GTK-сборке и CI до фазы 4
-  (`docs/plans/2026-10-28-windows-qt-frontend-design.md`)
+  MSYS2 и GTK на Windows не используются
 
 ### Code Style
 - Линтер: ruff
@@ -366,9 +366,13 @@ profiles = parse_subscription_content(content)  # List[ProxyBean]
 - Dev зависимости: pytest, ruff, coverage
 
 ### Windows Building
-- `bash core/scripts/build_windows.sh` в MSYS2: PyInstaller onedir
-  (`tenga-proxy.exe` и `tenga-proxy-svc.exe`), затем Inno Setup
-- CI `.github/workflows/windows.yml`: тесты, сборка установщика, установка
+- `bash core/scripts/build_windows.sh` в Git Bash: `uv run` с группами
+  `windows` и `build`, PyInstaller onedir (`tenga-proxy.exe` с Qt и
+  `tenga-proxy-svc.exe` без интерфейса), затем Inno Setup
+- Что попадает в сборку, проверяет `tests/test_packaging_spec.py` (нет `gi`,
+  есть `style.qss` и QtNetwork, служба без Qt)
+- CI `.github/workflows/windows.yml` (Git Bash, setup-python, uv): тесты
+  Windows-кода и Qt, сборка установщика, запуск собранного exe, установка
   службы и интеграционные тесты; по тегу `v*` установщик уходит в релиз
 
 ### deb Building
```

```diff
diff --git a/AGENTS.md b/AGENTS.md
index 7c182a2..0bb7c8c 100644
--- a/AGENTS.md
+++ b/AGENTS.md
@@ -9,11 +9,11 @@
 ## Проект и окружение
 
 Veblock (ранее Tenga Proxy) — прокси-клиент для Linux и Windows на Python
-3.11+ с xray-core, CLI и GUI на GTK 4 и libadwaita 1.5+. Протоколы: VLESS, Trojan, VMess,
+3.11+ с xray-core, CLI и GUI: GTK 4 и libadwaita 1.5+ на Linux, Qt (PySide6) на Windows. Протоколы: VLESS, Trojan, VMess,
 Shadowsocks, Hysteria2, SOCKS и HTTP. Режимы работы — TUN и системный
 прокси; VPN-интеграция зависит от ОС: NetworkManager на Linux, RAS и WireGuard на Windows.
 
-На Linux менеджер зависимостей — uv; на Windows используй MSYS2 UCRT64. PyGObject и Pycairo требуют системных библиотек.
+Менеджер зависимостей — uv на обеих ОС; на Windows — Git Bash и Python 3.12 с python.org. PyGObject и Pycairo на Linux требуют системных библиотек.
 Наличие Windows-окружения не позволяет автоматически проверить
 Linux GUI, D-Bus, TUN и сборку deb-пакета. Сообщай, какие проверки выполнены,
 какие недоступны; не выдавай пропущенные проверки за успешные.
@@ -91,7 +91,7 @@ Linux GUI, D-Bus, TUN и сборку deb-пакета. Сообщай, каки
   операции не должны блокировать главный цикл. Используй принятый механизм
   фоновых задач и доставки результатов из `src/ui/logic/async_utils.py`.
 - Меню, сочетания клавиш и трей используют общие Gio.SimpleAction приложения.
-- На Linux трей реализован через StatusNotifierItem и D-BusMenu на Gio; на Windows — через Shell_NotifyIcon в `src/ui/tray/win32/`.
+- На Linux трей реализован через StatusNotifierItem и D-BusMenu на Gio; на Windows — `QSystemTrayIcon` в `src/ui/qt/tray.py`, оба за `TrayController`.
   Не добавляй AppIndicator3 в процесс GTK 4: он связан с GTK 3.
 - Не обходи проверки безопасности конфигурации ради успешного подключения.
   Для изменений DNS, маршрутов, TUN и системного прокси проверяй обработку
@@ -177,9 +177,9 @@ Python: четыре пробела, длина строки 100, двойные
   Фасад выбирает реализацию при импорте, подмена `IS_WINDOWS` на него не
   действует. Новую функцию фасада добавляй в обе реализации: совпадение имён
   и сигнатур проверяет `tests/test_sys_facades.py`.
-- В `src/ui/` ОС напрямую не проверяют: тексты — `src/ui/logic/platform_texts.py`,
-  компоновка — `src/ui/logic/platform_layout.py`, функция на каждое отличие
-  с причиной. Допустимые места для `IS_WINDOWS` перечислены
+- В `src/ui/` ОС напрямую не проверяют: GTK-интерфейс работает только на
+  Linux, Qt — на Windows; тексты с отличиями по ОС —
+  `src/ui/logic/platform_texts.py`, функция на каждое отличие с причиной. Допустимые места для `IS_WINDOWS` перечислены
   в `tests/test_ui_platform_branches.py`.
 - TUN на Linux: права даёт `setcap` на xray в postinst пакета и помощник
   `/usr/libexec/tenga-proxy/tun-route-helper` через `sudo -n` (правило
@@ -192,30 +192,31 @@ Python: четыре пробела, длина строки 100, двойные
   проверка запросов, управление ядром, сетью и восстановлением состояния.
   GUI работает без повышения прав; служба устанавливается установщиком.
   Не ослабляй проверку команд, путей, конфигурации и прав доступа к pipe.
-- `src/ui/tray/win32/` — Windows-трей; не переноси зависимость D-Bus
-  в Windows-ветку исполнения. Единственный экземпляр и активация окна
+- `src/ui/qt/` — интерфейс Windows; он не импортирует `gi`, не переноси
+  туда зависимость GTK или D-Bus. Единственный экземпляр и активация окна
   на Windows используют платформенную реализацию.
 - `packaging/windows/` — PyInstaller spec, Inno Setup и сведения о версии.
   `.github/workflows/windows.yml` — фактическая последовательность CI
   Windows, `.github/workflows/linux.yml` — Linux: lint, pytest, `make test-gtk`,
   `make test-tray`, тесты на requests из Ubuntu, сборка и установка deb.
 
-На Windows Python, GTK, libadwaita, PyGObject, requests и pywin32 берутся
-из пакетов MSYS2 UCRT64. Не заменяй их обычным pip/uv-окружением без проверки
-совместимости. Подготовка: `bash core/scripts/install_dev.sh` в UCRT64.
+На Windows окружение — Git Bash, Python 3.12 с python.org и uv; MSYS2
+и GTK не используются. Подготовка: `bash core/scripts/install_dev.sh`
+(`uv sync --extra windows --extra dev`, xray.exe, wintun.dll).
 Сборка: `bash core/scripts/build_windows.sh` с PyInstaller и Inno Setup;
 результат — `dist/windows/veblock-<версия>-windows-x64-setup.exe`.
-CLI build выбирает скрипт по ОС; таблица команд uv выше относится к Linux.
+CLI build выбирает скрипт по ОС.
 
-В подготовленном MSYS2-окружении запускай Windows-набор как в CI:
+Windows-набор и Qt-тесты как в CI:
 
 ```bash
-python -m pytest -q --no-cov -p no:cacheprovider \
+uv run pytest -q --no-cov -p no:cacheprovider \
   tests/test_core_platform_info.py tests/test_sys_facades.py \
-  tests/test_sys_windows_*.py tests/test_ui_tray_win32_*.py tests/test_winsvc_*.py \
-  tests/test_packaging_version_info.py tests/test_cli_build.py \
+  tests/test_sys_windows_*.py tests/test_winsvc_*.py \
+  tests/test_packaging_*.py tests/test_cli_build.py \
   tests/test_sys_tun_access.py tests/test_core_net_journal.py \
   tests/test_ui_logic_platform_*.py tests/test_ui_platform_branches.py
+QT_QPA_PLATFORM=offscreen uv run pytest -q --no-cov -p no:cacheprovider -m qt tests/test_ui_qt_*.py
 ```
 
 Тесты `tests/integration/` с маркером windows требуют настоящей Windows
```

```diff
diff --git a/README.md b/README.md
index 299267e..a363cef 100644
--- a/README.md
+++ b/README.md
@@ -16,8 +16,9 @@ Veblock (раньше Tenga Proxy) — прокси-клиент для Linux и
 `vless://`, `trojan://`, `vmess://`, `ss://` и подписки, умеет пускать через
 прокси весь трафик системы или только выбранные сайты.
 
-Интерфейс написан на GTK 4 и libadwaita, поэтому выглядит как обычное
-приложение GNOME и подхватывает светлую или тёмную тему из настроек системы.
+На Linux интерфейс написан на GTK 4 и libadwaita и выглядит как обычное
+приложение GNOME, на Windows — на Qt в системном стиле. Светлая или тёмная
+тема берётся из настроек системы.
 
 ## Возможности
 
@@ -57,7 +58,7 @@ AppImage больше не выпускается. Как перейти с не
 Скачайте `veblock-<версия>-windows-x64-setup.exe` со страницы
 [Releases](https://github.com/vebulogmetra/tenga-proxy/releases) и запустите.
 Нужны Windows 10 или 11 (x64) и права администратора на время установки.
-GTK и xray-core входят в установщик.
+Qt и xray-core входят в установщик.
 
 Установщик регистрирует службу «Veblock»: через неё работает режим TUN,
 поэтому при подключении запрос UAC не появляется. Подробнее — в
```

```diff
diff --git a/docs/ru/development.md b/docs/ru/development.md
index 4e8cd4a..d9d7a26 100644
--- a/docs/ru/development.md
+++ b/docs/ru/development.md
@@ -197,33 +197,25 @@ python cli.py bump-version 1.0.0
 
 ### Окружение
 
-Используется MSYS2 UCRT64, а не `uv`: PyGObject и GTK берутся из пакетов
-MSYS2, pip их не соберёт. В оболочке «MSYS2 UCRT64»:
+Интерфейс Windows — Qt (PySide6), GTK на Windows не используется. Нужны
+Git for Windows (Git Bash), Python 3.12 с python.org и uv. В Git Bash:
 
 ```bash
-pacman -S --needed git unzip \
-  mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-python-pip \
-  mingw-w64-ucrt-x86_64-python-gobject mingw-w64-ucrt-x86_64-gtk4 \
-  mingw-w64-ucrt-x86_64-libadwaita mingw-w64-ucrt-x86_64-python-requests \
-  mingw-w64-ucrt-x86_64-python-pytest mingw-w64-ucrt-x86_64-python-pytest-cov \
-  mingw-w64-ucrt-x86_64-python-pywin32
-
-# Python MSYS2 по умолчанию читает файлы в cp1252
+# Python по умолчанию читает файлы в cp1252
 export PYTHONUTF8=1
 
-bash core/scripts/install_dev.sh     # xray.exe, wintun.dll, геобазы
-python gui.py
-python -m pytest -q --no-cov
+bash core/scripts/install_dev.sh     # uv sync --extra windows --extra dev, xray.exe, wintun.dll, геобазы
+uv run python gui.py
+uv run pytest -q --no-cov
+QT_QPA_PLATFORM=offscreen uv run pytest -q --no-cov -m qt tests/test_ui_qt_*.py
 ```
 
 ### Сборка установщика
 
-Нужен Inno Setup 6 (`ISCC.exe`; путь можно задать переменной `ISCC`):
+Нужен Inno Setup 6 (`ISCC.exe`; путь можно задать переменной `ISCC`).
+PyInstaller сценарий ставит сам (группа `build`):
 
 ```bash
-python -m venv --system-site-packages .venv-win
-. .venv-win/bin/activate
-pip install pyinstaller pyinstaller-hooks-contrib
 bash core/scripts/build_windows.sh
 # → dist/windows/veblock-<версия>-windows-x64-setup.exe
 ```
@@ -237,8 +229,8 @@ bash core/scripts/build_windows.sh
   `src/core/platform_info.py` при импорте фасада, код для Linux лежит в
   `src/sys/linux/`, для Windows — в `src/sys/windows/`. Имена и сигнатуры
   двух реализаций обязаны совпадать — это проверяет `tests/test_sys_facades.py`.
-- Отличия интерфейса: тексты — `src/ui/logic/platform_texts.py`, компоновка —
-  `src/ui/logic/platform_layout.py`. Виджеты ОС напрямую не проверяют.
+- Отличия интерфейса по ОС — только тексты в `src/ui/logic/platform_texts.py`:
+  GTK работает на Linux, Qt — на Windows. Виджеты ОС напрямую не проверяют.
 - Журнал отката сети (`src/core/net_journal.py`) общий: его пишут служба
   Windows и маршруты TUN на Linux. После падения приложения на Linux
   маршрут по умолчанию возвращается при следующем запуске.
@@ -249,8 +241,10 @@ bash core/scripts/build_windows.sh
   отката, команды `netsh`/PowerShell, состояние и pipe-сервер.
 - На Windows `AppContext.xray_manager` — `WindowsXrayManager`: конфиг с
   TUN-inbound запускает служба, остальные — сам GUI.
-- `src/ui/tray/win32/` — трей через `Shell_NotifyIcon`.
-- `packaging/windows/` — spec PyInstaller и сценарий Inno Setup.
+- Трей Windows — `QSystemTrayIcon` (`src/ui/qt/tray.py`) за тем же
+  `TrayController`, что и трей Linux.
+- `packaging/windows/` — spec PyInstaller (Qt без неиспользуемых модулей,
+  без GTK), сценарий Inno Setup и `ico.py` для `tools/make_ico.py`.
 
 ### Тесты
 
@@ -271,9 +265,10 @@ NRPT, откат). Нужны установленная служба и пра
 deb-пакета и его установка на раннере; по тегу `v*` пакет прикрепляется к
 релизу.
 
-`.github/workflows/windows.yml` на `windows-latest`: тесты Windows-кода,
-полный прогон (информационный), сборка установщика, установка службы из
-сборки и интеграционные тесты. По тегу `v*` установщик прикрепляется к
+`.github/workflows/windows.yml` на `windows-latest` в Git Bash с uv: тесты
+Windows-кода, Qt-тесты (offscreen), полный прогон (информационный), сборка
+установщика, запуск собранного `tenga-proxy.exe` с проверкой журнала,
+установка службы из сборки и интеграционные тесты. По тегу `v*` установщик прикрепляется к
 релизу; тег обязан совпадать с версией в `src/__init__.py`.
 
 ## Отладка
```

```diff
diff --git a/docs/en/development.md b/docs/en/development.md
index 23e5370..ba8fc8d 100644
--- a/docs/en/development.md
+++ b/docs/en/development.md
@@ -198,33 +198,25 @@ python cli.py bump-version 1.0.0
 
 ### Environment
 
-MSYS2 UCRT64 is used instead of `uv`: PyGObject and GTK come from MSYS2
-packages, pip cannot build them. In the "MSYS2 UCRT64" shell:
+The Windows interface is Qt (PySide6); GTK is not used on Windows. You need
+Git for Windows (Git Bash), Python 3.12 from python.org and uv. In Git Bash:
 
 ```bash
-pacman -S --needed git unzip \
-  mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-python-pip \
-  mingw-w64-ucrt-x86_64-python-gobject mingw-w64-ucrt-x86_64-gtk4 \
-  mingw-w64-ucrt-x86_64-libadwaita mingw-w64-ucrt-x86_64-python-requests \
-  mingw-w64-ucrt-x86_64-python-pytest mingw-w64-ucrt-x86_64-python-pytest-cov \
-  mingw-w64-ucrt-x86_64-python-pywin32
-
-# MSYS2 Python reads files as cp1252 by default
+# Python reads files as cp1252 by default
 export PYTHONUTF8=1
 
-bash core/scripts/install_dev.sh     # xray.exe, wintun.dll, geo databases
-python gui.py
-python -m pytest -q --no-cov
+bash core/scripts/install_dev.sh     # uv sync --extra windows --extra dev, xray.exe, wintun.dll, geo databases
+uv run python gui.py
+uv run pytest -q --no-cov
+QT_QPA_PLATFORM=offscreen uv run pytest -q --no-cov -m qt tests/test_ui_qt_*.py
 ```
 
 ### Building the installer
 
-Inno Setup 6 is required (`ISCC.exe`; the `ISCC` variable overrides the path):
+Inno Setup 6 is required (`ISCC.exe`; the `ISCC` variable overrides the path).
+The script installs PyInstaller itself (the `build` extra):
 
 ```bash
-python -m venv --system-site-packages .venv-win
-. .venv-win/bin/activate
-pip install pyinstaller pyinstaller-hooks-contrib
 bash core/scripts/build_windows.sh
 # → dist/windows/veblock-<version>-windows-x64-setup.exe
 ```
@@ -240,8 +232,8 @@ The build folder holds two executables: `tenga-proxy.exe` (GUI) and
   `src/sys/linux/`, Windows code in `src/sys/windows/`. Both implementations
   must export the same names and signatures; `tests/test_sys_facades.py`
   checks it.
-- UI differences: texts in `src/ui/logic/platform_texts.py`, layout in
-  `src/ui/logic/platform_layout.py`. Widgets do not check the OS themselves.
+- The only per-OS UI difference is texts in `src/ui/logic/platform_texts.py`:
+  GTK runs on Linux, Qt on Windows. Widgets do not check the OS themselves.
 - The network rollback journal (`src/core/net_journal.py`) is shared: the
   Windows service and the Linux TUN routes both write it. If the app crashes
   on Linux, the default route is restored on the next start.
@@ -252,8 +244,10 @@ The build folder holds two executables: `tenga-proxy.exe` (GUI) and
   journal, `netsh`/PowerShell commands, state and the pipe server.
 - On Windows `AppContext.xray_manager` is a `WindowsXrayManager`: a config with
   a TUN inbound is started by the service, everything else by the GUI itself.
-- `src/ui/tray/win32/` is the tray on top of `Shell_NotifyIcon`.
-- `packaging/windows/` holds the PyInstaller spec and the Inno Setup script.
+- The Windows tray is `QSystemTrayIcon` (`src/ui/qt/tray.py`) behind the same
+  `TrayController` as the Linux tray.
+- `packaging/windows/` holds the PyInstaller spec (Qt without unused modules,
+  no GTK), the Inno Setup script and `ico.py` for `tools/make_ico.py`.
 
 ### Tests
 
@@ -273,9 +267,10 @@ on your workstation: the routes capture the network during the test.
 and its installation on the runner; on a `v*` tag the package is attached to
 the release.
 
-`.github/workflows/windows.yml` on `windows-latest`: Windows-code tests, the
-full suite (informational), the installer build, installing the service from
-the build and the integration tests. On a `v*` tag the installer is attached
+`.github/workflows/windows.yml` on `windows-latest` in Git Bash with uv:
+Windows-code tests, Qt tests (offscreen), the full suite (informational), the
+installer build, a launch of the built `tenga-proxy.exe` with a log check,
+installing the service from the build and the integration tests. On a `v*` tag the installer is attached
 to the release; the tag must match the version in `src/__init__.py`.
 
 ## Debugging
```

```diff
diff --git a/docs/en/index.md b/docs/en/index.md
index ed73db5..3458a2f 100644
--- a/docs/en/index.md
+++ b/docs/en/index.md
@@ -11,7 +11,7 @@
 - Automatic system proxy setup (GNOME/KDE)
 - Flexible traffic routing (through VLESS, VPN, or directly)
 - Profile management
-- System tray with notifications (GTK)
+- System tray with notifications
 - Monitoring via Stats API (statistics)
 
 ## Quick Start
diff --git a/docs/en/installation.md b/docs/en/installation.md
index b789df3..69d834e 100644
--- a/docs/en/installation.md
+++ b/docs/en/installation.md
@@ -158,7 +158,7 @@ Download `veblock-<version>-windows-x64-setup.exe` from the
 it. Windows 10 or 11 (x64) is required; the installer asks for administrator
 rights (UAC). The wizard can add a desktop shortcut and start the app at sign-in.
 
-GTK, libadwaita, xray-core and the wintun driver are bundled; nothing else
+The Qt libraries, xray-core and the wintun driver are bundled; nothing else
 needs to be installed.
 
 Autostart and the `veblock://`, `wingeon://` links are registered under
diff --git a/docs/en/overview.md b/docs/en/overview.md
index 176b0d7..1b0a09b 100644
--- a/docs/en/overview.md
+++ b/docs/en/overview.md
@@ -87,7 +87,8 @@ Veblock uses an architecture with separation into:
 
 - **xray-core** - main traffic processing engine
 - **Python 3.11+** - implementation language
-- **GTK 4 + libadwaita 1.5** - graphical interface following the GNOME HIG
+- **GTK 4 + libadwaita 1.5** - Linux graphical interface following the GNOME HIG
+- **Qt 6 (PySide6)** - Windows graphical interface in the native style
 
 ### Development Tools
 
diff --git a/docs/ru/index.md b/docs/ru/index.md
index fd6f961..43ef759 100644
--- a/docs/ru/index.md
+++ b/docs/ru/index.md
@@ -11,7 +11,7 @@
 - Автоматическая настройка системного прокси (GNOME/KDE)
 - Гибкая маршрутизация трафика (через VLESS, VPN или напрямую)
 - Управление профилями
-- Системный трей с уведомлениями (GTK)
+- Системный трей с уведомлениями
 - Мониторинг через Stats API (статистика)
 
 ## Быстрый старт
diff --git a/docs/ru/installation.md b/docs/ru/installation.md
index d1b4a86..ef6c4ab 100644
--- a/docs/ru/installation.md
+++ b/docs/ru/installation.md
@@ -173,7 +173,7 @@ Stats API ядра использует Unix-сокет в новом прива
 Нужны Windows 10 или 11 (x64); установщик попросит права администратора (UAC).
 В мастере можно включить ярлык на рабочем столе и запуск при входе в систему.
 
-GTK, libadwaita, xray-core и драйвер wintun входят в установщик, отдельно
+Библиотеки Qt, xray-core и драйвер wintun входят в установщик, отдельно
 ничего ставить не нужно.
 
 Автозапуск и ссылки `veblock://`, `wingeon://` записываются в реестр
diff --git a/docs/ru/overview.md b/docs/ru/overview.md
index 5cd0015..0f55cfe 100644
--- a/docs/ru/overview.md
+++ b/docs/ru/overview.md
@@ -87,7 +87,8 @@ Veblock использует архитектуру с разделением н
 
 - **xray-core** - основной движок обработки трафика
 - **Python 3.11+** - язык реализации
-- **GTK 4 + libadwaita 1.5** - графический интерфейс по GNOME HIG
+- **GTK 4 + libadwaita 1.5** - графический интерфейс Linux по GNOME HIG
+- **Qt 6 (PySide6)** - графический интерфейс Windows в системном стиле
 
 ### Инструменты разработки
 
```

```diff
diff --git a/docs/plans/2026-10-28-windows-qt-frontend-design.md b/docs/plans/2026-10-28-windows-qt-frontend-design.md
index 9322f76..1960dde 100644
--- a/docs/plans/2026-10-28-windows-qt-frontend-design.md
+++ b/docs/plans/2026-10-28-windows-qt-frontend-design.md
@@ -75,6 +75,15 @@ GTK без изменения поведения. Ядро, хранилище,
   `2026-10-28-windows-qt-phase3-parity.md`; пресеты порядка правил и уровни
   журнала перенесены из GTK-диалогов в `src/ui/logic/`.
 
+**Уточнение по итогам фазы 4:**
+- `src/ui/logic/platform_layout.py` удалён целиком: все его функции были
+  Windows-ветками GTK; вместе с ним ушли `src/ui/widgets/name_label.py` и
+  обработка сигналов и pipe активации в `src/ui/application.py`;
+- `src/ui/tray/win32/ico.py` не удалён, а перенесён в
+  `packaging/windows/ico.py`: им `tools/make_ico.py` собирает `.ico`;
+- состав сборки проверяет `tests/test_packaging_spec.py`, CI Windows
+  запускает собранный exe и читает его журнал.
+
 **Появляется**: `src/ui/controller.py` (общая оркестровка) и фронтенд
 `src/ui/qt/`. `gui.py` выбирает фронтенд: на Windows — Qt, на Linux — GTK;
 флаг `--ui qt` запускает Qt-интерфейс на Linux для разработки (PySide6
```

**Step 2: Проверка**

```bash
grep -rn "MSYS2\|platform_layout\|tray/win32\|venv-win\|mingw-w64" CLAUDE.md AGENTS.md README.md docs/ru docs/en
uv run pytest tests/test_branding.py -q --no-cov | tail -1
```

Expected: `MSYS2` остаётся только там, где сказано, что MSYS2 и GTK на Windows не используются (`CLAUDE.md:346`, `AGENTS.md:203`); других совпадений нет. `test_branding` проходит.

**Step 3: Commit**

```bash
git add CLAUDE.md AGENTS.md README.md docs
git commit -m "docs: Windows без MSYS2 и GTK — Git Bash, uv, Qt; итоги фазы 4"
```

---

### Task 8: CI, приёмка на VM и релиз (вручную, владелец)

Эта задача не автоматизируется: нужны push, GitHub Actions и виртуальные машины Windows 10 и 11.

**Step 1: CI.** Push `develop`. В `windows.yml` зелёные шаги «Windows tests», «Qt UI tests», «Build installer», «Frozen GUI smoke», «Service integration tests». Размер каталога из вывода смоука записать в дизайн-документ (раздел «Сборка и поставка»; ожидание 60–80 МБ). Если выйдет заметно больше, смотри в `_internal`, какие модули Qt попали в сборку, и дополни `QT_UNUSED` в spec и тест.

Возможные падения и что делать:
- `uv` не нашёл Python 3.12 — проверь `UV_PYTHON` и шаг `setup-python`;
- в смоуке нет «Frontend: qt» и журнала — выведи `Get-ChildItem -Recurse $env:TENGA_CONFIG_DIR`: журнал мог лечь в `%LOCALAPPDATA%\tenga-proxy\logs`;
- `Traceback` в журнале смоука — это дефект сборки (чаще всего не хватает данных или модуля). Чинить spec, а не смоук.

**Step 2: Приёмка установщика на VM** (артефакт `tenga-proxy-windows-setup` из CI), Windows 10 22H2 и Windows 11 23H2+:
- установка поверх прежней GTK-версии: настройки и профили на месте, служба «Veblock» запущена, ярлыки работают;
- чистая установка; удаление через «Приложения» убирает службу, ярлыки и автозапуск;
- в `C:\Program Files\Veblock\_internal` нет `gi`, `gtk`, `libadwaita`;
- окно: светлая и тёмная тема, Snap Layouts, DPI 100/125/150/200 %, флаги в дереве и меню трея на высоком DPI;
- трей: значок, меню, подключение и отключение из трея, всплывающие уведомления, поведение после перезапуска Проводника;
- второй запуск и ссылка `veblock://` активируют уже открытое окно;
- подключение в режиме системного прокси и в режиме TUN (через службу, без UAC), VPN-режимы, failover, замер задержки, обновление подписки;
- открытые вопросы дизайна: нужен ли AppUserModelID для тостов, рендер svg-флагов в `QMenu`, `TaskbarCreated`. Ответы записать в дизайн-документ.

**Step 3: Релиз.** `python cli.py bump-version <версия>` (минорная: смена интерфейса Windows). Обновить заметки релиза: «Windows: новый интерфейс на Qt, установщик меньше, MSYS2 для разработки не нужен». Тег `v<версия>` → CI прикрепит установщик к черновику релиза; проверить и опубликовать.

**Step 4:** В конце этого плана отметить статус фазы 4 и найденное на VM.
