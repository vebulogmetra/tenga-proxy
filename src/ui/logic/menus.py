"""Состав меню окна, общий для GTK и Qt (без тулкита): (действие, подпись)."""

from __future__ import annotations

ADD_MENU = (
    ("add-profile", "Сервер по ссылке…"),
    ("add-profile-from-clipboard", "Сервер из буфера обмена"),
    ("add-subscription", "Подписка…"),
    ("add-group", "Группа…"),
)

# «Журнал…» добавляет Qt после «Настройки»: на Linux журнал живёт на вкладке.
MAIN_MENU = (
    ("refresh-subscriptions", "Обновить подписки"),
    ("test-latency", "Проверить задержку"),
    ("settings", "Настройки"),
    ("shortcuts", "Сочетания клавиш"),
    ("about", "О программе"),
    ("quit", "Выход"),
)
