"""Тексты интерфейса, которые зависят от ОС (без GTK)."""

from __future__ import annotations

from src.core import platform_info


def vpn_group_title() -> str:
    return "VPN-подключение Windows" if platform_info.IS_WINDOWS else "Подключение NetworkManager"


def vpn_group_description() -> str:
    if platform_info.IS_WINDOWS:
        return (
            "Встроенный VPN Windows или туннель WireGuard, который поднимается для сервера "
            "перед запуском прокси"
        )
    return "Для сервера можно поднимать VPN перед запуском прокси"


def missing_release_asset() -> str:
    if platform_info.IS_WINDOWS:
        return "установщик для этой системы отсутствует"
    return "deb-пакет для этой архитектуры отсутствует"


_SETTINGS_PAGE_TITLES = {
    "bypass": "Обход блокировок",
    "subscriptions": "Подписки",
    "about": "О программе",
}


def settings_page_title(page: str) -> str:
    return _SETTINGS_PAGE_TITLES[page]
