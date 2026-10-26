# Переименование в Veblock: план реализации

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** приложение называется для пользователя «Veblock», как Android-версия;
обновление ставится поверх прежней версии, профили и настройки сохраняются.

**Architecture:** меняется только видимое имя: заголовок окна, «О приложении»,
уведомления, трей, ярлыки, установщик Windows, отображаемое имя службы, тексты
ошибок, документация. Технические идентификаторы остаются прежними, как
`applicationId com.wingeon.app` на Android (коммит `ac554c17` в
`tenga-proxy-android`). Сменить любой из них — значит писать миграцию, а
пользователь от этого ничего не получит.

**Tech Stack:** Python 3.11, GTK 4 + libadwaita, Inno Setup, dpkg, pytest, ruff.

---

## Что меняется и что нет

Новое имя пишется везде как `Veblock`, без «Proxy». В тексте и в CLI это
`Veblock`, в коде `"Veblock"`.

| Остаётся (технический идентификатор) | Почему |
|---|---|
| deb-пакет `tenga-proxy`, `/usr/bin/tenga-proxy`, `/usr/lib/tenga-proxy`, `/usr/libexec/tenga-proxy/tun-route-helper`, `/etc/sudoers.d/tenga-proxy` | Смена имени пакета требует переходного пакета (Replaces/Conflicts) и меняет пути в sudoers и setcap |
| файл `tenga-proxy_<версия>_<arch>.deb` | Имя файла повторяет имя пакета: так пишут `apt remove tenga-proxy` |
| `~/.config/tenga-proxy`, `%APPDATA%\tenga-proxy`, `%PROGRAMDATA%\tenga-proxy`, `TENGA_CONFIG_DIR`, `tenga_*.log`, `tenga-proxy.lock` | Без миграции потеряются профили |
| `APP_ID = "ru.tenga.Proxy"`, `tenga-proxy.desktop`, `StartupWMClass`, имена иконок `tenga-proxy*` | Это имя на D-Bus, мьютекс и pipe активации на Windows; от него зависят закреплённые ярлыки |
| служба `TengaProxySvc`, pipe `\\.\pipe\tenga-proxy-svc`, `tenga-proxy.exe`, `tenga-proxy-svc.exe`, AppId установщика, значение автозапуска `Tenga Proxy` в `HKCU\...\Run` | Установщик находит прежнюю версию и снимает службу по этим именам |
| репозиторий `vebulogmetra/tenga-proxy` | `src/core/app_update.py` проверяет префикс `RELEASE_PREFIX`: после переименования репозитория старые версии перестанут видеть обновления |
| классы `TengaApplication`, `__gtype_name__ = "Tenga…"`, логгеры `tenga.*`, имена потоков | Пользователь их не видит |
| `LEGACY_USER_AGENT`, `tenga://`, `legacy_appimage.py` | Нужны для совместимости со старыми данными |

| Меняется | Где |
|---|---|
| имя в интерфейсе | окно, «О приложении», уведомления, группа в настройках, трей (SNI и Win32), `--version` |
| тексты ошибок | служба Windows недоступна или не установлена, «переустановите …» |
| диагностика | заголовок выгрузки, имя файла по умолчанию `veblock-diagnostics.txt` (на Android `veblock-logs-*.txt`) |
| Linux | `Name=` в `.desktop` (а в `Keywords` добавить `tenga`, чтобы поиск по старому имени работал), `index.theme`, описание пакета, сообщения `install_deb.sh` |
| Windows | `AppName`, папка установки для новых установок, меню «Пуск», ярлык на рабочем столе, сообщения установщика, имя файла установщика `veblock-<версия>-windows-x64-setup.exe`, ресурс версии exe, отображаемое имя и описание службы |
| User-Agent запроса к GitHub API за ядром | `tenga-proxy` → `Veblock` |
| документация | README, `docs/ru`, `docs/en`, `mkdocs.yml` (`site_name`), введение в CLAUDE.md и AGENTS.md |

**Чего не делаем:** логотип не меняем (на Android он не менялся). Настройку
«Представляться как Veblock» для подписок не добавляем: на десктопе её не было
и раньше, User-Agent по умолчанию — `v2rayNG/1.8.23`.

**Ограничение среды:** на машине разработчика идёт рабочая TUN-сессия на
`xray0`. GUI для проверки запускать можно, подключаться в режиме TUN нельзя.

---

### Task 1: Сторожевой тест имени

**Files:**
- Create: `tests/test_branding.py`

**Step 1: Написать падающий тест**

```python
"""Видимое имя — Veblock; технические идентификаторы tenga-proxy не меняются.

Что и почему оставлено прежним — docs/plans/2026-10-26-veblock-rebrand.md.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCANNED = (
    "src",
    "gui.py",
    "cli.py",
    "svc_main.py",
    "packaging",
    "core/scripts",
    "assets/tenga-proxy.desktop",
    "assets/theme/hicolor/index.theme",
    "Makefile",
)
BINARY = {".png", ".ico", ".svg", ".pyc"}
OLD_NAME = re.compile(r"\bTenga (?:Proxy|CLI)\b")


def _files():
    for entry in SCANNED:
        path = ROOT / entry
        if path.is_file():
            yield path
            continue
        for item in sorted(path.rglob("*")):
            if item.is_file() and "__pycache__" not in item.parts and item.suffix not in BINARY:
                yield item


def test_old_display_name_is_gone():
    hits = []
    for path in _files():
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for number, line in enumerate(lines, 1):
            # [InstallDelete] и значение автозапуска в .iss называют старое имя намеренно.
            if path.suffix == ".iss" and (line.startswith("Type:") or "ValueName:" in line):
                continue
            if OLD_NAME.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert hits == []


def test_app_name():
    from src import __app_name__

    assert __app_name__ == "Veblock"


def test_desktop_entry_keeps_the_old_name_searchable():
    text = (ROOT / "assets/tenga-proxy.desktop").read_text(encoding="utf-8")
    assert "Name=Veblock\n" in text
    assert "tenga;" in text.split("Keywords=", 1)[1].splitlines()[0]
    assert "Icon=tenga-proxy\n" in text
    assert "StartupWMClass=tenga-proxy\n" in text


def test_windows_installer_upgrades_the_previous_install():
    text = (ROOT / "packaging/windows/tenga-proxy.iss").read_text(encoding="utf-8")
    assert "AppId={{23089B2F-C5D8-45CE-A943-89C573F63388}" in text
    assert "AppName=Veblock\n" in text
    assert "OutputBaseFilename=veblock-{#AppVersion}-windows-x64-setup" in text
    # Прежние ярлыки «Tenga Proxy» не должны остаться рядом с новыми.
    assert '{autoprograms}\\Tenga Proxy' in text
    assert '{autodesktop}\\Tenga Proxy.lnk' in text
    assert 'ValueName: "Tenga Proxy"' in text  # автозапуск: имя значения прежнее


def test_service_identifiers_are_kept():
    from src.winsvc.server import PIPE_NAME
    from src.winsvc.service import DISPLAY_NAME, SERVICE_NAME

    assert SERVICE_NAME == "TengaProxySvc"
    assert PIPE_NAME == r"\\.\pipe\tenga-proxy-svc"
    assert DISPLAY_NAME == "Veblock"
```

**Step 2: Запустить и убедиться, что падает**

Run: `uv run pytest tests/test_branding.py -v`
Expected: FAIL. `test_old_display_name_is_gone` перечисляет около 60 строк;
`test_app_name`, тесты `.desktop`, `.iss` и `DISPLAY_NAME` тоже падают.
`test_service_identifiers_are_kept` падает только на `DISPLAY_NAME`. Если
вместо этого он падает на импорте, `src/winsvc/service.py` не импортируется на
Linux; тогда читать `DISPLAY_NAME` регуляркой из текста файла.

**Step 3: Commit**

```bash
git add tests/test_branding.py
git commit -m "test: сторожевой тест имени Veblock"
```

Тест остаётся красным до Task 7 — так задумано: по мере задач список строк в
выводе сокращается.

---

### Task 2: Имя приложения в ядре и точках входа

**Files:**
- Modify: `src/__init__.py:2`
- Modify: `gui.py:29,59,106`
- Modify: `cli.py:802,805`
- Modify: `src/core/diagnostics_export.py:18`
- Modify: `src/core/core_update.py:88`
- Test: `tests/test_core_core_update.py:117`

**Step 1: Обновить ожидания в тестах**

`tests/test_core_core_update.py:117`: `"User-Agent": "tenga-proxy"` →
`"User-Agent": "Veblock"`. Найти тесты выгрузки диагностики:
`grep -rn "Tenga Proxy" tests/` — заменить ожидаемый заголовок на `Veblock`.

**Step 2: Убедиться, что они падают**

Run: `uv run pytest tests/test_core_core_update.py tests/test_branding.py::test_app_name -v`
Expected: FAIL

**Step 3: Заменить строки**

- `src/__init__.py`: `__app_name__ = "Veblock"`
- `gui.py:29`: `description="Veblock"`; `:59`: `"… переустановите Veblock."`;
  `:106`: `logger.info("=== Veblock starting ===")`
- `cli.py:802`: `"Starting Veblock CLI, log file: %s"`; `:805`:
  `description="Veblock CLI - консольный клиент прокси"`
- `src/core/diagnostics_export.py:18`: `f"Veblock {__version__}\n…"`
- `src/core/core_update.py:88`: `"User-Agent": "Veblock"`

**Step 4: Запустить**

Run: `uv run pytest tests/test_core_core_update.py tests/test_branding.py::test_app_name -v`
Expected: PASS

**Step 5: Commit**

```bash
git add -u
git commit -m "feat: имя приложения Veblock в CLI, GUI и диагностике"
```

---

### Task 3: GTK-интерфейс и трей

**Files:**
- Modify: `src/ui/window.py:106` — `title="Veblock"`
- Modify: `src/ui/application.py:301` — `Gio.Notification.new("Veblock")`
- Modify: `src/ui/application.py:697,706` — `application_name="Veblock"`,
  `f"Veblock {app_version()}\n…"`
- Modify: `src/ui/dialogs/settings.py:344` — `Adw.PreferencesGroup(title="Veblock")`
- Modify: `src/ui/pages/monitoring.py:139` — `"veblock-diagnostics.txt"`
- Modify: `src/ui/tray/controller.py:110-115` — префикс `Veblock: `
- Modify: `src/ui/tray/sni.py:123` — `title: str = "Veblock"` (`item_id`
  оставить `tenga-proxy`: это технический Id SNI)
- Modify: `src/ui/tray/win32/backend.py:339` — `"Veblock"`
- Test: `tests/test_ui_tray_controller.py:63,87,170`, `tests/test_ui_application.py:648`

**Step 1: Обновить ожидания в тестах**

Во всех перечисленных строках тестов `"Tenga Proxy: …"` → `"Veblock: …"`.
Найти остальные: `grep -rn "Tenga Proxy\|tenga-diagnostics" tests/`.

**Step 2: Убедиться, что они падают**

Run: `uv run pytest tests/test_ui_tray_controller.py -v`
Expected: FAIL на подсказках трея.

**Step 3: Заменить строки** по списку выше.

**Step 4: Запустить**

Run: `uv run pytest tests/test_ui_tray_controller.py -v && make test-tray && make test-gtk`
Expected: PASS. `test-gtk` и `test-tray` проверяют `test_ui_application.py:648`
и SNI.

**Step 5: Commit**

```bash
git add -u
git commit -m "feat(ui): Veblock в окне, трее, уведомлениях и «О приложении»"
```

---

### Task 4: Служба Windows и тексты ошибок

**Files:**
- Modify: `src/winsvc/service.py:11-12` —
  `DISPLAY_NAME = "Veblock"`,
  `DESCRIPTION = "Запускает TUN-режим Veblock: xray-core, маршруты и DNS."`
  (`SERVICE_NAME` не трогать)
- Modify: `src/winsvc/state.py:65` — `"переустановите Veblock"`
- Modify: `src/sys/windows/service_client.py:1,22` — `Служба Veblock недоступна: …`
- Modify: `src/sys/windows/tun_access.py:7` — `Служба Veblock не установлена: …`
- Modify: `src/sys/windows/tun_route.py:1` — докстрока
- Test: `tests/test_sys_tun_access.py:115`

**Step 1:** обновить `tests/test_sys_tun_access.py:115` и найти остальные
ожидания: `grep -rn "Служба Tenga\|переустановите Tenga" tests/`.

**Step 2:** Run: `uv run pytest tests/test_sys_tun_access.py tests/test_branding.py::test_service_identifiers_are_kept -v` — Expected: FAIL

**Step 3:** заменить строки.

**Step 4:** Run тот же — Expected: PASS

Отображаемое имя службы обновится при установке: `PrepareToInstall` в `.iss`
удаляет службу, а `[Run]` регистрирует её заново.

**Step 5: Commit**

```bash
git add -u
git commit -m "feat(windows): служба отображается как Veblock"
```

---

### Task 5: Пакет для Linux

**Files:**
- Modify: `assets/tenga-proxy.desktop` — `Name=Veblock`,
  `Keywords=proxy;vpn;xray;network;tenga;`. Остальное без изменений.
- Modify: `assets/theme/hicolor/index.theme:2` — `Name=Veblock`
- Modify: `core/scripts/build_deb.sh:3,127,151` — комментарий, описание пакета
  (`Description:` начинать с `Veblock`, вторая строка — `Veblock connects
  through …`), баннер. `APP_NAME="tenga-proxy"` и `Package:` не трогать.
- Modify: `core/scripts/install_deb.sh:3,37,41,43` — `Veblock установлен.
  Запуск: tenga-proxy или из меню приложений`, `Удаление Veblock...`,
  `Veblock удалён`
- Modify: `packaging/linux/sudoers:1`, `packaging/linux/tenga-proxy:2` — комментарии
- `src/sys/linux/tun_access.py:82-84` не трогать: там имя пакета `tenga-proxy`
  для `apt install --reinstall`, оно верное.

**Step 1:** Run: `uv run pytest tests/test_branding.py::test_desktop_entry_keeps_the_old_name_searchable tests/test_cli_build.py -v` — Expected: первый FAIL

**Step 2:** внести правки.

**Step 3:** Run тот же — Expected: PASS

**Step 4: Собрать пакет и посмотреть метаданные**

Run: `python cli.py build && dpkg-deb -I dist/tenga-proxy_*_amd64.deb | sed -n '/Package/,$p'`
Expected: `Package: tenga-proxy`, описание начинается с `Veblock`.

Run: `dpkg-deb -c dist/tenga-proxy_*_amd64.deb | grep -E 'applications|sudoers|libexec'`
Expected: пути прежние (`tenga-proxy.desktop`, `sudoers.d/tenga-proxy`,
`libexec/tenga-proxy/tun-route-helper`).

**Step 5: Commit**

```bash
git add -u
git commit -m "build(linux): Veblock в меню приложений и описании пакета"
```

---

### Task 6: Установщик Windows

**Files:**
- Modify: `packaging/windows/tenga-proxy.iss`
- Modify: `packaging/windows/version_info.py:32,36`
- Modify: `core/scripts/build_windows.sh:2,34`
- Modify: `cli.py:367`
- Test: `tests/test_packaging_version_info.py:26`

**Step 1:** `tests/test_packaging_version_info.py:26` →
`"StringStruct('ProductName', 'Veblock')"`. Run:
`uv run pytest tests/test_packaging_version_info.py tests/test_branding.py::test_windows_installer_upgrades_the_previous_install -v` — Expected: FAIL

**Step 2: `version_info.py`**: `FileDescription` и `ProductName` → `'Veblock'`.
`InternalName` и `OriginalFilename` не трогать: они совпадают с именем exe.

**Step 3: `.iss`**

```ini
; Установщик Veblock для Windows. Версию передаёт build_windows.sh:
;   iscc /DAppVersion=0.19.0 packaging\windows\tenga-proxy.iss
...
[Setup]
; Не менять: по AppId установщик находит прежнюю версию.
AppId={{23089B2F-C5D8-45CE-A943-89C573F63388}
AppName=Veblock
...
; Обновление поверх прежней версии оставляет её каталог (UsePreviousAppDir),
; новая установка идёт в «Veblock».
DefaultDirName={autopf}\Veblock
DefaultGroupName=Veblock
; Иначе обновление положит ярлык «Veblock» в прежнюю папку «Tenga Proxy».
UsePreviousGroup=no
...
OutputBaseFilename=veblock-{#AppVersion}-windows-x64-setup

[CustomMessages]
ru.AutoStart=Запускать Veblock при входе в систему
en.AutoStart=Start Veblock when I sign in
ru.RegisterService=Регистрация службы Veblock...
en.RegisterService=Registering the Veblock service...

[InstallDelete]
; Ярлыки версий до переименования в Veblock.
Type: filesandordirs; Name: "{autoprograms}\Tenga Proxy"
Type: files; Name: "{autodesktop}\Tenga Proxy.lnk"

[Icons]
Name: "{group}\Veblock"; Filename: "{app}\tenga-proxy.exe"
Name: "{autodesktop}\Veblock"; Filename: "{app}\tenga-proxy.exe"; Tasks: desktopicon

[Registry]
; Имя значения автозапуска прежнее: с новым именем у обновлённых установок
; осталось бы и старое, и приложение запускалось бы дважды.
Root: HKCU; ... ValueName: "Tenga Proxy"; ...   (строка без изменений)

[Run]
... Description: "{cm:LaunchProgram,Veblock}" ...
```

Значение автозапуска (`ValueName: "Tenga Proxy"`) не трогать: в «Диспетчере
задач → Автозагрузка» Windows показывает `FileDescription` из exe, то есть
`Veblock`.

**Step 4:** `core/scripts/build_windows.sh:34` →
`echo "[OK] dist/windows/veblock-$VERSION-windows-x64-setup.exe"`; комментарий
в строке 2. `cli.py:367` → `veblock-<версия>-windows-x64-setup.exe`.

`src/core/app_update.py` правок не требует: `_asset_matches` на Windows
проверяет `-setup.exe`, `windows` и `x64`, а не префикс. Добавить проверку в
`tests/test_core_app_update.py` рядом с тестом на строке 60 — копию с ассетом
`veblock-0.18.0-windows-x64-setup.exe` и `has_asset is True`.

**Step 5:** Run: `uv run pytest tests/test_packaging_version_info.py tests/test_core_app_update.py tests/test_branding.py::test_windows_installer_upgrades_the_previous_install -v` — Expected: PASS

**Step 6: Commit**

```bash
git add -u
git commit -m "build(windows): установщик Veblock, прежние ярлыки удаляются"
```

---

### Task 7: Скрипты разработки

**Files:**
- Modify: `cli.py:293,390,416,444,482,545` — баннеры `Veblock - …`
- Modify: `core/scripts/bump_version.sh:61`, `core/scripts/install_dev.sh:403`,
  `core/scripts/setup.sh:22` — баннеры
- Modify: `Makefile:102` — `закройте Veblock перед прогоном`
- Modify: `tests/conftest.py:89` — `другим экземпляром Veblock`

Баннеры выровнены пробелами по ширине рамки — после замены выровнять заново.

**Step 1:** Run: `uv run pytest tests/test_branding.py -v`
Expected: **PASS** — все тесты сторожа зелёные. Если в
`test_old_display_name_is_gone` остались строки, исправить их в этой задаче.

**Step 2: Commit**

```bash
git add -u
git commit -m "chore: Veblock в скриптах разработки"
```

---

### Task 8: Документация

**Files:**
- Modify: `README.md` — заголовок и `alt` логотипа `Veblock`; абзац под
  заголовком: «Veblock (раньше Tenga Proxy) — прокси-клиент …»; имя файла
  установщика Windows `veblock-<версия>-windows-x64-setup.exe`; служба
  «Veblock». Команды `apt install ./tenga-proxy_…deb`, `tenga-proxy` и ссылки
  на репозиторий не менять.
- Modify: `mkdocs.yml:1` — `site_name: Veblock` (`site_url`, `repo_url` прежние)
- Modify: `docs/ru/*.md`, `docs/en/*.md` (22 файла) — имя продукта → Veblock;
  команды, пути и имена пакета/служб/exe прежние. В `docs/ru/installation.md`
  и `docs/en/installation.md` добавить короткий раздел:

  ```markdown
  ## Переход с Tenga Proxy

  Приложение переименовано в Veblock. Обновление ставится поверх прежней версии:
  профили, подписки и настройки сохраняются. Команда запуска (`tenga-proxy`),
  имя deb-пакета и каталог настроек (`~/.config/tenga-proxy`) прежние.
  ```
- Modify: `CLAUDE.md:7` и `AGENTS.md:1,11` — «Veblock (ранее Tenga Proxy) — …»;
  в «Important Notes» CLAUDE.md добавить подраздел:

  ```markdown
  ### Имя приложения
  - Пользователь видит «Veblock» (`src.__app_name__`), как в Android-версии
  - Технические имена остались `tenga-proxy`/`ru.tenga.Proxy`/`TengaProxySvc`:
    пакет, каталоги настроек, app id, служба, pipe, exe, AppId установщика,
    репозиторий. Их смена требует миграции —
    см. `docs/plans/2026-10-26-veblock-rebrand.md`
  - `tests/test_branding.py` не пускает «Tenga Proxy» обратно в интерфейс
  ```
- Не трогать: `docs/plans/*` (история), `docs/screenshots/*` — пересъёмка
  отдельной задачей, если нужно.

**Step 1: Проверить остатки**

Run: `grep -rn "Tenga" README.md mkdocs.yml docs/ru docs/en`
Expected: только «раньше Tenga Proxy» / «Переход с Tenga Proxy» и ссылки на
репозиторий `tenga-proxy`.

**Step 2:** Run: `uv run --with mkdocs-material mkdocs build --strict` (если
mkdocs есть в окружении; иначе пропустить и указать это в отчёте)

**Step 3: Commit**

```bash
git add -u
git commit -m "docs: приложение называется Veblock"
```

---

### Task 9: Проверка

**Step 1: Тесты и линтер**

Run: `uv run pytest && make test-gtk && make test-tray && python cli.py lint-all`
Expected: всё PASS, ruff без замечаний.

**Step 2: Остатки старого имени**

Run: `git grep -n "Tenga Proxy\|Tenga CLI" -- ':!docs/plans' ':!tests/test_sys_legacy_appimage.py'`
Expected: только раздел «Переход с Tenga Proxy», `[InstallDelete]` в `.iss` и
`ValueName: "Tenga Proxy"`.

**Step 3: Живая проверка GUI на Linux** (без подключения в режиме TUN — см.
ограничение среды)

Run: `python gui.py`
Проверить: заголовок окна, «О приложении», подсказка трея — `Veblock`. После
`python cli.py setup` в меню приложений видно «Veblock», и поиск находит его
и по «tenga».

**Step 4: Windows (CI и ручная проверка)**

- Пуш ветки → `.github/workflows/windows.yml` собирает
  `veblock-<версия>-windows-x64-setup.exe`, ставит службу и гоняет
  интеграционные тесты.
- Вручную на Windows с установленной 0.18.0: запустить новый установщик
  поверх. Проверить: в «Приложениях» — «Veblock»; в «Пуске» нет «Tenga Proxy»,
  есть «Veblock»; в `services.msc` служба «Veblock» (имя службы
  `TengaProxySvc`); профили на месте; автозапуск один; ссылка `veblock://add/…`
  открывает приложение.

**Step 5: Выпуск** — по решению владельца:
`python cli.py bump-version 0.19.0`, в заметках к релизу — текст «Переход с
Tenga Proxy» из Task 8.
