import pytest

from src.ui.logic.formatting import format_bytes


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "0 B"),
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (5 * 1024**2, "5.0 MB"),
        (3 * 1024**3, "3.00 GB"),
    ],
)
def test_format_bytes(value, expected):
    assert format_bytes(value) == expected
