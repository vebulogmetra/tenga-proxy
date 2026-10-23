"""Интеграционные тесты идут только по явной просьбе: им нужна установленная
служба и права администратора, а маршруты на время теста перехватывают сеть.
"""

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("TENGA_SERVICE_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="TENGA_SERVICE_TESTS=1 включает тесты службы")
    for item in items:
        item.add_marker(skip)
