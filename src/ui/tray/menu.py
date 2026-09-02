"""Build the tray menu out of the current state.

Чистая функция без GTK и без D-Bus: состав меню — это решение о содержании, и
проверять его удобнее обычным тестом, чем через шину.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.ui.logic.status import ConnectionState
from src.ui.tray.dbusmenu import MenuItem, separator

# Больше двух десятков пунктов панель растягивает на весь экран; полный список
# всегда доступен в окне.
MAX_PROFILES = 20
MAX_LABEL = 40


def shorten(name: str, limit: int = MAX_LABEL) -> str:
    """Cut a long profile name down to a size the panel can show."""
    if len(name) <= limit:
        return name
    return name[: limit - 1] + "…"


def _status_label(state: ConnectionState, profile_name: str) -> str:
    if state is ConnectionState.CONNECTED:
        return f"Статус: {profile_name}" if profile_name else "Статус: подключено"
    if state is ConnectionState.CONNECTING:
        return "Статус: подключение…"
    if state is ConnectionState.ERROR:
        return "Статус: ошибка"
    return "Статус: Отключено"


def _connection_entry(state: ConnectionState) -> MenuItem:
    if state is ConnectionState.CONNECTED:
        return MenuItem("Отключить", action="app.disconnect")
    if state is ConnectionState.CONNECTING:
        # Ни «Подключить», ни «Отключить» во время подключения не имеют
        # смысла: единственное осмысленное действие — прервать.
        return MenuItem("Отменить", action="app.disconnect")
    return MenuItem("Подключить", action="app.connect")


def _profile_entries(profiles: Sequence, active_profile_id: int | None) -> list[MenuItem]:
    if not profiles:
        return [MenuItem("(нет профилей)", enabled=False)]

    shown = list(profiles[:MAX_PROFILES])
    truncated = len(profiles) > MAX_PROFILES

    # Подключённый профиль обязан оставаться в списке, даже если по порядку он
    # не попал в первые двадцать.
    hidden_active = (
        truncated
        and active_profile_id is not None
        and not any(p.id == active_profile_id for p in shown)
    )
    if hidden_active:
        active = next((p for p in profiles if p.id == active_profile_id), None)
        if active is not None:
            shown = shown[: MAX_PROFILES - 1] + [active]

    entries = [
        MenuItem(
            shorten(profile.name),
            action="app.connect-profile",
            target=profile.id,
            checked=profile.id == active_profile_id,
        )
        for profile in shown
    ]

    if truncated:
        entries.append(MenuItem("Показать все…", action="app.activate-window"))

    return entries


def build_menu(
    state: ConnectionState,
    profiles: Sequence,
    profile_name: str = "",
    active_profile_id: int | None = None,
) -> list[MenuItem]:
    """Describe the whole tray menu for the current state."""
    return [
        MenuItem(_status_label(state, profile_name), enabled=False),
        separator(),
        _connection_entry(state),
        separator(),
        MenuItem("Профили", children=_profile_entries(profiles, active_profile_id)),
        MenuItem("Добавить профиль…", action="app.add-profile"),
        separator(),
        MenuItem("Открыть окно", action="app.activate-window"),
        MenuItem("Настройки…", action="app.settings"),
        separator(),
        MenuItem("Выход", action="app.quit"),
    ]
