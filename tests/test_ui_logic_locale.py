from __future__ import annotations

from src.ui.logic.locale import RUSSIAN_LOCALES, choose_locale


def test_a_russian_locale_is_kept():
    """Уже русская локаль менять ничего не должна."""
    assert choose_locale({"LANGUAGE": "ru", "LC_ALL": "ru_RU.UTF-8"}) == {}


def test_a_russian_lang_alone_is_enough():
    assert choose_locale({"LANG": "ru_RU.UTF-8"}) == {}


def test_an_english_locale_gets_russian_added():
    """Интерфейс написан по-русски, поэтому и надписи GTK просим русские."""
    chosen = choose_locale({"LANG": "en_US.UTF-8"}, available=RUSSIAN_LOCALES[:1])

    assert chosen["LANGUAGE"] == "ru"
    assert chosen["LC_MESSAGES"] == RUSSIAN_LOCALES[0]


def test_an_empty_environment_gets_russian_too():
    chosen = choose_locale({}, available=RUSSIAN_LOCALES[:1])

    assert chosen["LANGUAGE"] == "ru"


def test_nothing_is_forced_without_a_russian_locale_installed():
    """Без установленной локали подмена только сломала бы форматирование."""
    assert choose_locale({"LANG": "en_US.UTF-8"}, available=[]) == {}


def test_other_categories_are_left_alone():
    """Меняются только надписи: числа и даты остаются как в системе."""
    chosen = choose_locale({"LANG": "en_US.UTF-8"}, available=RUSSIAN_LOCALES[:1])

    assert "LANG" not in chosen
    assert "LC_ALL" not in chosen
    assert "LC_NUMERIC" not in chosen
