"""Состав меню окна, общий для GTK и Qt (без тулкита): (действие, подпись)."""

from __future__ import annotations

# Лучший сервер текущей группы: в главном меню и в трее.
CONNECT_BEST_LABEL = "Подключить лучший сервер"
# То же для конкретной группы, в меню её строки.
CONNECT_BEST_GROUP_LABEL = "Подключить лучший"

ADD_MENU = (
    ("add-profile", "Сервер по ссылке…"),
    ("add-profile-from-clipboard", "Сервер из буфера обмена"),
    ("add-subscription", "Подписка…"),
    ("add-group", "Группа…"),
)

MAIN_MENU = (
    ("refresh-subscriptions", "Обновить подписки"),
    ("connect-best", CONNECT_BEST_LABEL),
    ("test-latency", "Проверить задержку"),
    ("network-diagnostics", "Диагностика сети…"),
    ("settings", "Настройки"),
    ("show-log", "Журнал…"),
    ("shortcuts", "Сочетания клавиш"),
    ("about", "О программе"),
    ("quit", "Выход"),
)
