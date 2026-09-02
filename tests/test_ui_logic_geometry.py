"""Tests for window geometry persistence helpers."""

from __future__ import annotations

import pytest

from src.ui.logic.geometry import (
    DEFAULT_GEOMETRY,
    MIN_HEIGHT,
    MIN_WIDTH,
    Geometry,
    format_geometry,
    parse_geometry,
)


def test_empty_string_gives_default():
    assert parse_geometry("") == DEFAULT_GEOMETRY


def test_parses_width_height_and_maximized():
    assert parse_geometry("900,700,0,0,1") == Geometry(900, 700, maximized=True)


def test_reads_legacy_string_with_real_coordinates():
    # Строки, записанные GTK3-окном, содержат позицию; она игнорируется.
    assert parse_geometry("820,640,120,80,0") == Geometry(820, 640, maximized=False)


def test_missing_maximized_field_defaults_to_false():
    assert parse_geometry("820,640") == Geometry(820, 640, maximized=False)


@pytest.mark.parametrize("raw", ["garbage", "a,b,c,d,e", ",,,,", "800"])
def test_broken_input_never_raises(raw):
    result = parse_geometry(raw)
    assert result.width >= MIN_WIDTH
    assert result.height >= MIN_HEIGHT


def test_too_small_size_is_raised_to_minimum():
    result = parse_geometry("10,10,0,0,0")
    assert result == Geometry(MIN_WIDTH, MIN_HEIGHT, maximized=False)


def test_one_broken_field_does_not_discard_the_other():
    assert parse_geometry("900,oops,0,0,0") == Geometry(900, DEFAULT_GEOMETRY.height, False)


def test_format_writes_five_fields_with_zero_position():
    assert format_geometry(Geometry(900, 700, maximized=True)) == "900,700,0,0,1"


def test_round_trip():
    geometry = Geometry(1024, 768, maximized=False)
    assert parse_geometry(format_geometry(geometry)) == geometry
