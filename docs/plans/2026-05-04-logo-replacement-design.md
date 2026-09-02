# Замена иконок приложения и кликабельный логотип

**Дата:** 2026-05-04

## Цель

Заменить системную иконку приложения на `logo_icon.png` и логотип на главном экране на `logo_inner.png`. Логотип на главном экране сделать кликабельным с поведением:

- **Не подключено, есть selected профиль:** логотип серый, клик подключает к выбранному профилю.
- **Не подключено, нет selected:** логотип серый, клик показывает диалог "Выберите профиль".
- **Подключение:** логотип серый с анимацией пульсации, не кликабельный (`set_sensitive(False)`).
- **Подключено:** логотип цветной, клик отключает.

## Файлы

### Иконки

- `assets/tenga-proxy.png` — копия `logo_icon.png` (системная иконка приложения и трей).
- `assets/logo_inner.png` — копия одноимённого файла из корня (для главного окна).
- `assets/tenga-proxy.svg` — оставить как есть для совместимости со старыми путями, но скрипты сборки будут использовать PNG напрямую.

### Скрипты сборки

- `core/scripts/build_appimage.sh` (стр. 92-97): копировать `assets/tenga-proxy.png` в `hicolor/256x256/apps/`. Убрать вызов `rsvg-convert`.
- `core/scripts/install_appimage.sh` (стр. 129-138): аналогично.

## Системная иконка окна

`src/ui/main_window.py:116`: заменить `set_icon_name("network-transmit-receive")` на `set_icon_from_file(<путь к assets/tenga-proxy.png>)`. Использовать новый хелпер `get_asset_path()` в `src/core/config.py`.

## Иконка трея

`src/ui/tray.py:26-29`: `ICON_*` заменить на абсолютные пути к `assets/tenga-proxy.png` через `get_asset_path()`. AppIndicator поддерживает абсолютные пути.

## Кликабельный логотип

### Виджет

В `_setup_ui` (main_window.py:142-144) `Gtk.Image.new_from_icon_name("tenga-proxy", ...)` заменить на:

```python
self._header_button = Gtk.Button()
self._header_button.set_relief(Gtk.ReliefStyle.NONE)  # без рамки
self._header_button.get_style_context().add_class("tenga-logo-button")
self._header_icon = Gtk.Image()
self._header_button.add(self._header_icon)
self._header_button.connect("clicked", self._on_logo_clicked)
header_box.pack_start(self._header_button, False, False, 0)
```

### Загрузка изображения

При создании окна загрузить `logo_inner.png` через `GdkPixbuf.Pixbuf.new_from_file_at_size(path, 64, 64)`. Сохранить два pixbuf:
- `self._logo_color` — оригинальный цветной.
- `self._logo_gray` — `pixbuf.copy()` + `saturate_and_pixelate(dest, saturation=0.0, pixelate=False)`.

### Состояния

В `_update_ui` (main_window.py:1351) удалить вызовы `_update_icon_color`. Добавить `_update_logo_state`:

```python
def _update_logo_state(self, state: ProxyState, connecting: bool = False):
    if connecting:
        self._header_icon.set_from_pixbuf(self._logo_gray)
        self._header_button.set_sensitive(False)
        self._header_button.get_style_context().add_class("tenga-logo-pulse")
        self._header_button.set_tooltip_text("Подключение...")
    elif state.is_running:
        self._header_icon.set_from_pixbuf(self._logo_color)
        self._header_button.set_sensitive(True)
        self._header_button.get_style_context().remove_class("tenga-logo-pulse")
        profile = self._context.profiles.get_profile(state.started_profile_id)
        name = profile.name if profile else "..."
        self._header_button.set_tooltip_text(f"Отключиться от: {name}")
    else:
        self._header_icon.set_from_pixbuf(self._logo_gray)
        self._header_button.set_sensitive(True)
        self._header_button.get_style_context().remove_class("tenga-logo-pulse")
        sel = self._get_selected_profile_id()
        if sel is not None:
            profile = self._context.profiles.get_profile(sel)
            name = profile.name if profile else "..."
            self._header_button.set_tooltip_text(f"Подключиться к: {name}")
        else:
            self._header_button.set_tooltip_text("Выберите профиль")
```

### Анимация пульсации

CSS в `style.css` (или где определены классы `tenga-*`):

```css
@keyframes tenga-logo-pulse {
    0% { opacity: 1.0; }
    50% { opacity: 0.4; }
    100% { opacity: 1.0; }
}
.tenga-logo-button.tenga-logo-pulse {
    animation: tenga-logo-pulse 1.2s ease-in-out infinite;
}
.tenga-logo-button {
    background: transparent;
    border: none;
    box-shadow: none;
    padding: 0;
}
```

### Логика клика

```python
def _on_logo_clicked(self, _btn):
    # переиспользуем _on_connect_clicked — логика идентична
    self._on_connect_clicked(_btn)
```

`_on_connect_clicked` уже корректно: подключает, если есть selected; показывает диалог "Выберите профиль" иначе; отключает, если уже подключено.

### Состояние "Connecting"

`ProxyState` не имеет поля `is_connecting`. Добавлять не обязательно — короткое визуальное состояние "пульсирующий серый" можно реализовать на стороне UI:
- При клике (Connect) → сразу `_update_logo_state(state, connecting=True)`.
- Когда `_on_state_changed` приходит с `is_running=True` → `connecting=False`.
- При клике (Disconnect) → аналогично `connecting=True` до прихода `is_running=False`.

Это даёт визуальную пульсацию во время операции без изменений в `ProxyState`.

## Что НЕ меняется

- `ProfileManager` API — используем существующие `get_selected_profile`/`get_profile`.
- `_on_connect_clicked` — уже обрабатывает все случаи корректно.
- `_update_icon_color` — оставляем (мёртвый код можно удалить позже, или удалим в этом же изменении).

## Тесты

Ручная проверка:
1. Запуск `python gui.py` — окно показывает `logo_inner.png` серого цвета (если нет активного профиля).
2. Выбор профиля + клик по логотипу → подключение, логотип становится цветным.
3. Клик по цветному логотипу → отключение, логотип серый.
4. Клик по логотипу без выбранного профиля → диалог "Выберите профиль".
5. Системная иконка окна (alt+tab, taskbar) — `logo_icon.png`.
6. Иконка трея — `logo_icon.png`.
