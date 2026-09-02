# Дизайн: полный редизайн UI/UX Tenga Proxy (GTK4 + libadwaita)

Дата: 2026-09-02
Статус: одобрено (brainstorming с владельцем проекта)

## Цель

Заменить текущий GTK3-интерфейс (`src/ui`, ~6300 строк, самописная тёмная тема)
на нативное GNOME-приложение на GTK4 + libadwaita, следуя GNOME HIG. Попутно
устранить накопленные дефекты UI: гонки потоков, утечки таймеров, блокирующие
вызовы в главном потоке, дублирование диалогов, смешение языков в кнопках.

## Решения (по итогам brainstorming)

1. **Стек**: GTK 4 + libadwaita ≥ 1.5 (нужны `Adw.Dialog`, `Adw.AlertDialog`,
   `Adw.PreferencesDialog`, `Adw.AboutDialog`, `Adw.Breakpoint`). Минимальная
   целевая платформа: Ubuntu 24.04 / Fedora 40 / Debian 13. На машине разработчика
   GTK 4.14.5, libadwaita 1.5.0.
2. **Визуальный ориентир**: Adwaita HIG, системная тема (светлая и тёмная
   приходят автоматически). Собственный CSS сводится к нескольким классам
   (цвета задержки, статусный индикатор) через именованные цвета Adwaita.
3. **Структура экранов меняется**: логотип уходит из центра окна в компактную
   статус-карточку, вкладки становятся `Adw.ViewSwitcher`, два диалога
   редактирования профиля объединяются в один, модальные `MessageDialog`
   заменяются тостами и `Adw.AlertDialog`.
4. **Трей**: собственная реализация `org.kde.StatusNotifierItem` +
   `com.canonical.dbusmenu` поверх `Gio.DBusConnection`. AppIndicator3
   несовместим с GTK4-процессом. Новых зависимостей нет.
5. **Последовательность**: этап 0 — исправления логики, не зависящие от GTK,
   сразу в `develop`; далее ветка `feature/ui-adwaita` до функционального
   паритета, затем слияние.
6. **Вне объёма (YAGNI)**: gettext/i18n (строки остаются русскими, но кнопки
   приводятся к одному языку), новые функции прокси, изменение CLI. Задача из
   `TASK/TASK.md` (замер задержки до youtube.com) планируется отдельно.

## Текущее состояние и дефекты

Скриншоты текущего UI сняты 2026-09-02 (главное окно 3 вкладки, 6 диалогов).
Ключевые проблемы, подтверждённые чтением кода:

| # | Дефект | Где |
|---|--------|-----|
| B1 | Тест задержки группы создаёт поток и временный xray на каждый профиль без ограничения (128 профилей = 128 процессов), `profiles.save()` из рабочих потоков | `main_window.py:697-775` |
| B2 | `profile.latency_ms` пишется из потоков, читается в `_refresh_profiles` в главном | `main_window.py:752` |
| B3 | Обработчики SIGINT/SIGTERM вызывают `Gtk.main_quit()` и диалоги напрямую из signal-контекста | `app.py:100-110` |
| B4 | Монитор запускает новый поток на каждый тик, не дожидаясь предыдущего | `core/monitor.py:113` |
| B5 | Список локальных сетей (CIDR) захардкожен трижды | `app.py:566, 588`, `profile_vpn_settings.py:621` |
| B6 | Обе ветки `if routing.mode == PROXY_ALL … else …` идентичны | `app.py:732-741` |
| B7 | Диалоги «Группа» и «Добавить профиль» закрываются при ошибке валидации без сообщения | `edit_group.py:130`, `add_profile.py:186` |
| B8 | `GLib.timeout_add` без сохранения id: fade-in окна, «Скопировано!» | `style.py:253`, `edit_profile.py:241`, `profile_vpn_settings.py:265` |
| B9 | Кнопки стилизуются по русским подстрокам подписи («удал», «подключ») | `style.py:182-192` |
| B10 | `nmcli`/`ip` вызываются синхронно в `__init__` диалога профиля и при каждом обновлении состояния | `profile_vpn_settings.py:324-364, 657`, `main_window.py:1455` |
| B11 | Высота списка профилей ограничена 235 px независимо от размера окна | `main_window.py:263` |
| B12 | Геометрия окна сохраняется на каждый `configure-event` | `main_window.py:1961-1979` |
| B13 | Смешение языков: Cancel/Apply/OK/Add при русском UI; уведомления частью на английском | все диалоги, `app.py:270-505` |
| B14 | ~16 копий блока `Gtk.MessageDialog` + `set_wmclass` + `run()` | `main_window.py` |
| B15 | Два разных диалога редактирования профиля с дублированной секцией «Редактировать» | `edit_profile.py`, `profile_vpn_settings.py` |
| B16 | Нет клавиатурного доступа: контекстные меню только по правой кнопке, нет ускорителей, нет мнемоник | `main_window.py:1531, 1063` |
| B17 | Три иконки трея указывают на один файл, состояние не отличимо | `tray.py:37-39` |
| B18 | Статистика трафика (`upload_bytes/download_bytes`) нигде не отображается | `main_window.py:31` |
| B19 | Устаревшие API: `Gtk.STOCK_*`, `set_wmclass`, `modify_font`, `Menu.popup`, `set_position` | все файлы `src/ui` |
| B20 | Unix-сокет single instance падает с `EINVAL` при длинном пути конфигурации (лимит 108 байт) | `src/sys/single_instance.py` |
| B21 | Блок «Статус VPN» добавляется во фрейм, уже занятый сеткой, и не отображается вовсе | `profile_vpn_settings.py:382` |

B1–B7, B20, B21 исправлены на этапе 0 (2026-09-02): B21 найден при проверке
всех диалогов, остальные не зависят от GTK. Остальные исчезают
вместе со старым кодом при миграции и закрываются требованиями к новому UI.

## Архитектура нового UI

### Слои

```
src/ui/
├── application.py      # TengaApplication(Adw.Application): lifecycle, actions,
│                       #   единственность экземпляра (Gio), сигналы, тосты
├── window.py           # MainWindow(Adw.ApplicationWindow): ToolbarView,
│                       #   HeaderBar, ViewStack, Breakpoint, статус-карточка
├── pages/
│   ├── profiles.py     # ProfilesPage: SearchBar + ColumnView(TreeListModel)
│   ├── subscriptions.py# SubscriptionsPage: ListBox из Adw.ActionRow
│   └── monitoring.py   # MonitoringPage: Adw.PreferencesPage со статусами и трафиком
├── widgets/
│   ├── status_card.py  # StatusCard: индикатор, имя профиля, задержка, трафик, кнопка
│   └── latency_label.py# метка задержки с классами latency-good/medium/bad
├── models/
│   ├── profile_items.py# ProfileItem/GroupItem(GObject) + построение TreeListModel
│   └── filters.py      # чистые функции фильтрации/сортировки (тестируются без GTK)
├── dialogs/
│   ├── add_profile.py  # Adw.Dialog: ссылка + имя, live-парсинг
│   ├── subscription.py # Adw.Dialog: название + URL
│   ├── rename_group.py # Adw.AlertDialog с полем ввода
│   ├── profile.py      # Adw.PreferencesDialog: Профиль / VPN / Маршруты (объединённый)
│   └── settings.py     # Adw.PreferencesDialog: Основные / Мониторинг / DNS
├── tray/
│   ├── sni.py          # StatusNotifierItem над Gio.DBus
│   ├── dbusmenu.py     # com.canonical.dbusmenu: дерево пунктов, события
│   └── tray.py         # TrayController: связывает SNI с состоянием приложения
├── logic/
│   ├── async_utils.py  # run_in_background(fn, on_done): поток → GLib.idle_add
│   ├── latency.py      # LatencyRunner: ThreadPoolExecutor(max_workers=4), отмена
│   └── formatting.py   # format_bytes, latency_text, статус-строки
└── style.css           # ≤ 60 строк: latency-*, status-dot, карточка
```

`src/ui/logic` и `src/ui/models/filters.py` не импортируют GTK и тестируются
обычным pytest. Виджеты тонкие: получают данные из `AppContext`, отдают события
в `TengaApplication` через `Gio.SimpleAction` (`app.connect`, `app.disconnect`,
`app.add-profile`, `app.settings`, `win.search`, `profile.edit`, `profile.delete` и т. д.).
Единый набор действий используют меню окна, контекстные меню, ускорители и трей.

### Главное окно

```
┌──────────────────────────────────────────────────────────┐
│ ☰  Tenga Proxy            [Профили][Подписки][Мониторинг]  🔍 ＋ │  Adw.HeaderBar
├──────────────────────────────────────────────────────────┤
│ ┌─ StatusCard ────────────────────────────────────────┐ │
│ │ ● Подключено · Польша | XHTTP VPN#6                 │ │
│ │   132 ms · ↑ 1.2 MB ↓ 48.7 MB · TUN     [Отключить] │ │
│ └─────────────────────────────────────────────────────┘ │
│ ┌─ SearchBar (скрыт до Ctrl+F / 🔍) ──────────────────┐ │
│ ├─ ColumnView ────────────────────────────────────────┤ │
│ │ ▾ 📡 OverSecure (128)                               │ │
│ │     ✓ Германия (XHTTP)     VLESS  130.17.…  1322 ms │ │
│ │       Польша | XHTTP VPN#6 VLESS  91.206.…  1378 ms │ │
│ │ ▸ 📁 Single-node (2)                                │ │
│ └─────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────┘
       ToastOverlay: «Подписка обновлена: 597 профилей»
```

- `Adw.Breakpoint` при ширине < 550 sp переносит `ViewSwitcher` в
  `Adw.ViewSwitcherBar` внизу.
- Список занимает всё свободное место (`vexpand`), ограничения высоты убраны (B11).
- Кнопка Подключить/Отключить: `suggested-action` / `destructive-action`,
  состояние «Подключение…» показывает `Adw.Spinner` внутри карточки.
- Клик по строке выбирает профиль, двойной клик или Enter подключает.
- Контекстное меню профиля: Подключить, Тест задержки, Редактировать,
  Копировать ссылку, Удалить. Открывается правой кнопкой, клавишей Menu и
  Shift+F10 (`Gtk.PopoverMenu` из `Gio.Menu`).
- Ускорители: Ctrl+F поиск, Ctrl+N добавить профиль, Ctrl+Shift+N подписка,
  Ctrl+, настройки, Delete удалить, F5 обновить подписки, Ctrl+Q выход, Ctrl+W
  скрыть окно.
- Меню «☰»: Настройки, Сочетания клавиш, О программе, Выход.
- Меню «＋»: Профиль из ссылки, Профиль из буфера обмена, Подписка, Группа.

### Подписки

`Gtk.ListBox` (`boxed-list`) из `Adw.ActionRow`: заголовок = название, подзаголовок =
URL, суффикс = «597 · 20.12.2025», кнопки Обновить/Редактировать/Удалить.
Пустое состояние — `Adw.StatusPage` с кнопкой «Добавить подписку».

### Мониторинг

`Adw.PreferencesPage`: группа «Соединение» (статус прокси, VPN, последняя проверка,
кнопка «Проверить сейчас»), группа «Маршрутизация активного профиля» (режим,
direct/proxy/vpn правила), группа «Трафик» (↑/↓ за сессию). Вкладка скрывается,
если мониторинг отключён в настройках (как сейчас).

### Диалоги

| Диалог | Тип | Содержимое |
|--------|-----|------------|
| Добавить профиль | `Adw.Dialog` | `Adw.EntryRow` «Ссылка» с кнопкой вставки, `Adw.EntryRow` «Имя», строка результата парсинга; кнопка «Добавить» неактивна, пока ссылка не разобрана (закрывает B7) |
| Подписка | `Adw.Dialog` | название, URL, «Обновлено»; кнопка «Сохранить» неактивна при невалидном URL |
| Группа | `Adw.AlertDialog` + `Gtk.Entry` | переименование |
| Профиль | `Adw.PreferencesDialog` | страницы Профиль (имя, ссылка, замена ссылки), VPN (`Adw.SwitchRow`, `Adw.ComboRow` для подключения/интерфейсов, автоподключение), Маршруты (`Adw.ComboRow` режим, приоритет, три списка в `Gtk.TextView` внутри `Adw.PreferencesGroup`). Объединяет два старых диалога (B15). Списки `nmcli` загружаются в фоне, строки показывают спиннер (B10) |
| Настройки | `Adw.PreferencesDialog` | Основные (адрес/порт, режим, TUN), Мониторинг, DNS, Логи. «О программе» — `Adw.AboutDialog` из меню |
| Подтверждения | `Adw.AlertDialog` | удаление профиля/группы/подписки, очистка логов; деструктивная кнопка помечена `destructive` |
| Результаты операций | `Adw.Toast` | добавлено/обновлено/скопировано/ошибка (B14) |

Все диалоги асинхронные (`present` + callback/`choose`), синхронные `run()`-циклы
из `app.py` переводятся на колбэки.

### Трей (StatusNotifierItem)

- `sni.py` регистрирует объект `/StatusNotifierItem` с интерфейсом
  `org.kde.StatusNotifierItem` (свойства Category, Id, Title, Status, IconName,
  IconThemePath, Menu, ItemIsMenu; методы Activate, SecondaryActivate, Scroll;
  сигналы NewIcon, NewStatus, NewTitle) и вызывает `RegisterStatusNotifierItem`
  у `org.kde.StatusNotifierWatcher`. Следит за появлением watcher через
  `Gio.bus_watch_name`, чтобы пережить перезапуск панели.
- `dbusmenu.py` реализует `com.canonical.dbusmenu`: `GetLayout`, `GetGroupProperties`,
  `Event`, `AboutToShow`, сигнал `LayoutUpdated`. Пункты описываются простым
  деревом Python-объектов (`MenuItem(label, action, enabled, children, separator)`).
- Три реальных иконки: `tenga-proxy-tray-disconnected`, `-connected`, `-connecting`
  (symbolic SVG в `assets/icons/hicolor/symbolic/apps`), закрывает B17.
- Если watcher отсутствует (GNOME без расширения), трей молча не показывается,
  приложение продолжает работать в фоне; закрытие окна скрывает его, повторный
  запуск активирует через `Gio.Application`.

### Единственность экземпляра

`Adw.Application` с `application_id="ru.tenga.Proxy"` и флагами по умолчанию:
второй запуск вызывает `activate` первого и показывает окно. Самописный
Unix-сокет удаляется (закрывает B20). Файловая блокировка `SingleInstance`
остаётся как страховка от двух xray при отсутствии D-Bus.

### Потоки и фоновые операции

- `run_in_background(fn, on_done, on_error)`: выполняет `fn` в потоке, результат
  доставляет в главный поток через `GLib.idle_add`, всегда возвращает
  `GLib.SOURCE_REMOVE`.
- `LatencyRunner`: `ThreadPoolExecutor(max_workers=4)`, результаты пачкой
  через idle; `profiles.save()` только в главном потоке после завершения (B1, B2).
- Сигналы: `GLib.unix_signal_add(PRIORITY_DEFAULT, SIGINT/SIGTERM, app.quit)` (B3).
- Монитор: флаг «проверка идёт», тик пропускается, если предыдущая не закончилась (B4).
- Геометрия окна: сохраняется по `close-request` и при `unmap`, не на каждое
  изменение размера (B12).

### Сборка и совместимость

- `core/scripts/build_appimage.sh` копирует исходники и использует системный
  `python3-gi`; проверки зависимостей меняются с `gir1.2-gtk-3.0` на
  `gir1.2-gtk-4.0` и `gir1.2-adw-1`.
- В `gui.py` перед импортом UI: проверка `Adw.get_minor_version() >= 5` с
  понятным сообщением об ошибке и списком пакетов для установки.
- `GSK_RENDERER=ngl` по умолчанию; при `TENGA_SOFTWARE_RENDER=1` выставляется `cairo`.

### Тестирование

- Чистая логика (`src/ui/logic`, `src/ui/models/filters.py`, `tray/dbusmenu.py`
  дерево пунктов) — обычные pytest-тесты без дисплея.
- Виджеты — тесты с маркером `gtk`, запускаются под `xvfb-run -a` (`make test-gtk`),
  пропускаются автоматически, если `Gtk.init_check()` не проходит. Проверяют
  построение окна, действия, состояние кнопок диалогов.
- SNI — тест с приватной сессионной шиной (`Gio.TestDBus`): регистрация объекта,
  `GetLayout`, обработка `Event("clicked")`.
- Существующие тесты `tests/test_ui_*.py` переписываются под новые модули
  (логика замены ссылки переезжает в `dialogs/profile.py`, тест подписки — на колбэки).

## Критерии готовности (паритет функций)

- Все действия текущего UI доступны: добавить/редактировать/удалить профиль,
  группу, подписку; обновить подписку; тест задержки профиля и группы;
  подключение/отключение; настройки; мониторинг; трей с выбором профиля.
- Ни одного вызова `subprocess`/сети/диска из обработчиков GTK в главном потоке.
- Одинаковый язык всех надписей и кнопок (русский).
- Окно корректно работает от 360×500 до полноэкранного, светлая и тёмная тема.
- `uv run pytest` и `make test-gtk` проходят; `python cli.py lint-all` без ошибок.
- AppImage запускается на чистой Ubuntu 24.04.
