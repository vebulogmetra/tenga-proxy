"""Country flag parsing keeps stored names and ordinary text intact."""

import pytest

from src.ui.logic.country_flags import flag_parts, split_flag_prefix


@pytest.mark.parametrize("text", ["3-🇷🇺Авто", "🇫🇮 Сервер ☄", "A 🇵🇱 B 🇩🇪 C", "🇿🇿?", ""])
def test_inline_flags_preserve_original_text(text):
    assert "".join(value for _code, value in flag_parts(text)) == text


def test_flags_after_numeric_prefix_and_multiple_flags():
    assert flag_parts("3-🇷🇺Авто 🇵🇱") == [(None, "3-"), ("ru", "🇷🇺"), (None, "Авто "), ("pl", "🇵🇱")]


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
