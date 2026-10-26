"""Чем компоновка интерфейса на Windows отличается от Linux (без GTK).

Виджеты не проверяют ОС сами: они спрашивают здесь про конкретное отличие,
а причина записана один раз, рядом с ним. Признак читается при вызове, и
тесты проверяют обе ветки на любой ОС.
"""

from __future__ import annotations

from src.core import platform_info


def stylesheets() -> list[str]:
    """Таблицы стилей в порядке подключения: Windows-правки поверх общих."""
    if platform_info.IS_WINDOWS:
        return ["style.css", "style-windows.css"]
    return ["style.css"]


def adaptive_dialog_width() -> bool:
    """Форма задаёт предпочтительную ширину вместо жёсткого минимума.

    На Windows окно часто узкое, и диалог становится листом внутри него:
    минимальная ширина обрезала бы его.
    """
    return platform_info.IS_WINDOWS


def wrapping_action_buttons() -> bool:
    """Кнопки действий переносятся по строкам, а не стоят в один ряд.

    Подписи кнопок в шрифте Windows шире и в один ряд не помещаются.
    """
    return platform_info.IS_WINDOWS


def compact_subscription_rows() -> bool:
    """Название подписки в две строки, сведения справа обрезаются по ширине."""
    return platform_info.IS_WINDOWS


def toasts_above_navigation() -> bool:
    """Уведомления показываются над содержимым, не закрывая нижние вкладки."""
    return platform_info.IS_WINDOWS


def bundled_flag_images() -> bool:
    """Флаги стран — картинками из комплекта.

    В шрифтах Windows эмодзи-флагов нет: вместо флага видны две буквы.
    """
    return platform_info.IS_WINDOWS


def monitoring_on_general_settings_page() -> bool:
    """Параметры мониторинга — на странице «Общие», без своей страницы.

    В узком Windows-диалоге навигация внизу, и шестая страница в неё не
    помещается.
    """
    return platform_info.IS_WINDOWS


def monolith_status_logo() -> bool:
    """В карточке статуса — «Монолит», у которого ядро окрашено по состоянию.

    Это логотип Windows-клиента, тот же, что в трее и у приложения. Картинка
    сама показывает состояние, в том числе подключение, вместо спиннера.
    """
    return platform_info.IS_WINDOWS
