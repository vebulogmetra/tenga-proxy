"""Country flag parsing keeps stored names and ordinary text intact."""

import pytest

from src.ui.logic.country_flags import split_flag_prefix


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("🇷🇺Москва", ("ru", "Москва")),
        (" 🇳🇱 Авто", ("nl", "Авто")),
        ("🇫🇮\ufe0fФинляндия", ("fi", "Финляндия")),
        ("Москва", (None, "Москва")),
        ("🇷Москва", (None, "🇷Москва")),
        ("", (None, "")),
    ],
)
def test_split_flag_prefix(text, expected):
    assert split_flag_prefix(text) == expected
