"""Choosing the locale for the standard GTK and libadwaita strings.

Интерфейс написан по-русски прямо в коде, а стандартные надписи — кнопки
диалога о программе, пункты «Подробности» и «Участники», подписи файлового
выбора — libadwaita и GTK берут из локали. При системной локали `en_US`
получалась смесь: свой текст по-русски, чужой по-английски.

Меняются только сообщения (`LC_MESSAGES`), но не числа и даты: подменять
`LANG` целиком значило бы навязать пользователю русский формат чисел там,
где он выбрал другой.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("tenga.ui.locale")

# Имена русской локали в разном написании: у разных дистрибутивов оно своё.
RUSSIAN_LOCALES = ("ru_RU.UTF-8", "ru_RU.utf8", "ru_RU")

# Переменные, по которым видно уже выбранный язык — от частной к общей,
# как их и читает gettext.
_LANGUAGE_VARS = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")


def _installed_locales() -> list[str]:
    """Russian locale names the system actually has."""
    try:
        import subprocess

        result = subprocess.run(
            ["locale", "-a"], capture_output=True, text=True, timeout=5, check=False
        )
        if result.returncode != 0:
            return []
        present = {line.strip() for line in result.stdout.splitlines()}
    except (OSError, subprocess.SubprocessError):
        return []

    return [name for name in RUSSIAN_LOCALES if name in present]


def choose_locale(
    environ: dict[str, str] | None = None,
    available: list[str] | tuple[str, ...] | None = None,
) -> dict[str, str]:
    """Environment overrides that put the standard strings into Russian.

    Пустой словарь означает «ничего менять не нужно»: либо язык уже русский,
    либо русской локали в системе нет и подмена сделала бы только хуже.
    """
    environ = os.environ if environ is None else environ

    for name in _LANGUAGE_VARS:
        value = environ.get(name, "")
        if value.startswith("ru"):
            return {}

    installed = _installed_locales() if available is None else list(available)
    if not installed:
        logger.debug("No Russian locale installed, leaving the environment alone")
        return {}

    return {"LANGUAGE": "ru", "LC_MESSAGES": installed[0]}


def apply_locale() -> None:
    """Ask for Russian standard strings before GTK is imported.

    Вызывается до импорта GTK: переводы подхватываются при инициализации
    библиотеки, и после неё смена переменных уже ничего не меняет.
    """
    for name, value in choose_locale().items():
        os.environ[name] = value
