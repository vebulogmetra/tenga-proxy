"""Интеграционные тесты идут только по явной просьбе: им нужна установленная
служба и права администратора, а маршруты на время теста перехватывают сеть.
"""

import os
from pathlib import Path

import pytest

HERE = Path(__file__).parent


def pytest_collection_modifyitems(config, items):
    if os.environ.get("TENGA_SERVICE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="TENGA_SERVICE_TESTS=1 включает тесты службы")
    # Хук получает все тесты прогона, а не только свои.
    for item in items:
        if HERE in Path(item.path).parents:
            item.add_marker(skip)
