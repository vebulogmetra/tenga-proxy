"""Иконки трея: файлы существуют, имена соответствуют состояниям."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from src.ui.logic.status import ConnectionState
from src.ui.tray4.icons import ICON_NAMES, icon_name_for, icons_directory


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (ConnectionState.DISCONNECTED, "tenga-proxy-disconnected"),
        (ConnectionState.CONNECTING, "tenga-proxy-connecting"),
        (ConnectionState.CONNECTED, "tenga-proxy-connected"),
        (ConnectionState.ERROR, "tenga-proxy-disconnected"),
    ],
)
def test_every_state_maps_to_an_icon(state, expected):
    assert icon_name_for(state) == expected


def test_the_three_names_are_distinct():
    # Дефект B17: в GTK3-версии все три состояния указывали на один файл.
    assert len(set(ICON_NAMES)) == 3


def test_the_icons_directory_exists():
    assert icons_directory().is_dir()


@pytest.mark.parametrize("name", ICON_NAMES)
def test_each_icon_file_is_present(name):
    assert (icons_directory() / f"{name}.svg").is_file()


@pytest.mark.parametrize("name", ICON_NAMES)
def test_each_icon_is_valid_svg(name):
    tree = ET.parse(icons_directory() / f"{name}.svg")

    assert tree.getroot().tag.endswith("svg")


@pytest.mark.parametrize("name", ICON_NAMES)
def test_each_icon_is_sixteen_units_square(name):
    root = ET.parse(icons_directory() / f"{name}.svg").getroot()

    # Панель масштабирует по viewBox; 16×16 — стандарт символьных иконок GNOME.
    assert root.get("viewBox") == "0 0 16 16"


def test_the_icons_differ_from_each_other():
    contents = {(icons_directory() / f"{name}.svg").read_text() for name in ICON_NAMES}

    assert len(contents) == 3
