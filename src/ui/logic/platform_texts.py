"""Тексты интерфейса, которые зависят от ОС (без GTK)."""

from __future__ import annotations

from src.core import platform_info


def vpn_group_title() -> str:
    return "VPN-подключение Windows" if platform_info.IS_WINDOWS else "Подключение NetworkManager"


def vpn_group_description() -> str:
    if platform_info.IS_WINDOWS:
        return (
            "Встроенный VPN Windows или туннель WireGuard, который профиль поднимает "
            "перед запуском прокси"
        )
    return "Профиль может поднимать VPN перед запуском прокси"


def missing_release_asset() -> str:
    if platform_info.IS_WINDOWS:
        return "установщик для этой системы отсутствует"
    return "deb-пакет для этой архитектуры отсутствует"


# Короткие подписи — для нижней навигации узкого Windows-диалога.
_SETTINGS_PAGE_TITLES = {
    "bypass": ("Обход блокировок", "Обход"),
    "subscriptions": ("Подписки", "Ссылки"),
    "about": ("О программе", "Версия"),
}


def settings_page_title(page: str) -> str:
    linux, windows = _SETTINGS_PAGE_TITLES[page]
    return windows if platform_info.IS_WINDOWS else linux
