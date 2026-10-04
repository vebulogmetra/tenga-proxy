"""Каталог geo-категорий: что на самом деле есть в geosite.dat и geoip.dat.

Ссылка на категорию, которой в базе нет, — не пустое правило: ядро отвергает
конфиг целиком. Поэтому перед сборкой такие записи надо уметь отсеять.
"""

from pathlib import Path

import pytest

from src.core import geo
from src.core.geo import (
    GEOIP_FILE,
    GEOSITE_FILE,
    GeoCatalog,
    asset_dir_for_core,
    asset_dirs,
    load_catalog,
    read_categories,
)

BUNDLED = Path("core/bin")


def _varint(value: int) -> bytes:
    out = bytearray()
    while value > 0x7F:
        out.append(value & 0x7F | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _field(number: int, payload: bytes) -> bytes:
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def make_dat(*codes: str, filler: bytes = b"") -> bytes:
    """GeoSiteList/GeoIPList: entry = 1 { country_code = 1; ...остальное = 2 }."""
    return b"".join(_field(1, _field(1, code.encode()) + _field(2, filler)) for code in codes)


def test_reads_category_names_in_lower_case(tmp_path):
    path = tmp_path / GEOSITE_FILE
    path.write_bytes(make_dat("CATEGORY-RU", "GOOGLE", filler=b"x" * 300))

    assert read_categories(path) == frozenset({"category-ru", "google"})


def test_missing_file_gives_empty_set(tmp_path):
    assert read_categories(tmp_path / "nope.dat") == frozenset()


def test_corrupt_file_gives_empty_set(tmp_path):
    """Обрезанная при скачивании база не должна ронять сборку конфига."""
    path = tmp_path / GEOIP_FILE
    path.write_bytes(make_dat("RU", "CN")[:-3] + b"\xff\xff\xff\xff")

    assert read_categories(path) == frozenset()


def test_catalog_knows_entries_by_kind():
    catalog = GeoCatalog(geosite=frozenset({"category-ru"}), geoip=frozenset({"ru"}))

    assert catalog.knows("geosite:category-ru")
    assert catalog.knows("geosite:category-ru@ads")  # атрибут каталог не проверяет
    assert catalog.knows("geoip:ru")
    assert not catalog.knows("geosite:ru")
    assert not catalog.knows("geoip:category-ru")


def test_split_keeps_non_geo_rules_and_reports_unknown():
    catalog = GeoCatalog(geosite=frozenset({"google"}), geoip=frozenset())

    kept, dropped = catalog.split(["domain:a.example", "geosite:google", "geosite:nope"])

    assert kept == ["domain:a.example", "geosite:google"]
    assert dropped == ["geosite:nope"]


def test_load_catalog_takes_first_directory_that_has_the_file(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / GEOSITE_FILE).write_bytes(make_dat("ONE"))
    (second / GEOSITE_FILE).write_bytes(make_dat("TWO"))
    (second / GEOIP_FILE).write_bytes(make_dat("RU"))

    catalog = load_catalog([first, second])

    assert catalog.geosite == frozenset({"one"})
    assert catalog.geoip == frozenset({"ru"})


def test_load_catalog_notices_replaced_file(tmp_path):
    path = tmp_path / GEOIP_FILE
    path.write_bytes(make_dat("RU"))
    assert load_catalog([tmp_path]).geoip == frozenset({"ru"})

    path.write_bytes(make_dat("RU", "BY"))

    assert load_catalog([tmp_path]).geoip == frozenset({"ru", "by"})


def test_asset_dirs_follow_the_core_lookup_order(tmp_path, monkeypatch):
    """Ядро ищет базы в XRAY_LOCATION_ASSET, иначе рядом с бинарником."""
    monkeypatch.delenv("XRAY_LOCATION_ASSET", raising=False)
    assert asset_dirs(tmp_path / "bin" / "xray")[0] == tmp_path / "bin"

    monkeypatch.setenv("XRAY_LOCATION_ASSET", str(tmp_path / "geo"))
    assert asset_dirs(tmp_path / "bin" / "xray")[0] == tmp_path / "geo"


@pytest.mark.skipif(not (BUNDLED / GEOSITE_FILE).exists(), reason="нет core/bin/geosite.dat")
def test_bundled_bases_have_the_categories_the_builder_refers_to():
    catalog = load_catalog([BUNDLED])

    assert {"category-ru", "category-gov-ru"} <= catalog.geosite
    assert {"ru", "private"} <= catalog.geoip


# --- где ядро возьмёт базы -------------------------------------------------


def put_bases(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / GEOSITE_FILE).write_bytes(make_dat("X"))
    (directory / GEOIP_FILE).write_bytes(make_dat("X"))
    return directory


def test_bundled_bases_are_a_fallback_after_the_binary_directory(tmp_path, monkeypatch):
    """Установка без баз рядом с ядром берёт их из комплекта приложения."""
    monkeypatch.delenv("XRAY_LOCATION_ASSET", raising=False)
    monkeypatch.setattr(geo, "BUNDLED_GEO_DIR", tmp_path / "bundle")

    dirs = asset_dirs(tmp_path / "bin" / "xray")

    assert dirs[:2] == [tmp_path / "bin", tmp_path / "bundle"]


def test_core_needs_no_hint_when_bases_lie_next_to_it(tmp_path, monkeypatch):
    monkeypatch.delenv("XRAY_LOCATION_ASSET", raising=False)
    monkeypatch.setattr(geo, "BUNDLED_GEO_DIR", put_bases(tmp_path / "bundle"))
    put_bases(tmp_path / "bin")

    assert asset_dir_for_core(tmp_path / "bin" / "xray") is None


def test_core_is_pointed_at_bundled_bases_when_it_has_none(tmp_path, monkeypatch):
    """Сам ядро в комплект приложения не заглянет — каталог называем через окружение."""
    monkeypatch.delenv("XRAY_LOCATION_ASSET", raising=False)
    bundle = put_bases(tmp_path / "bundle")
    monkeypatch.setattr(geo, "BUNDLED_GEO_DIR", bundle)

    assert asset_dir_for_core(tmp_path / "bin" / "xray") == bundle


def test_user_chosen_asset_directory_is_respected(tmp_path, monkeypatch):
    monkeypatch.setenv("XRAY_LOCATION_ASSET", str(tmp_path / "mine"))
    monkeypatch.setattr(geo, "BUNDLED_GEO_DIR", put_bases(tmp_path / "bundle"))

    assert asset_dir_for_core(tmp_path / "bin" / "xray") is None


def test_no_bases_anywhere_gives_no_hint(tmp_path, monkeypatch):
    monkeypatch.delenv("XRAY_LOCATION_ASSET", raising=False)
    monkeypatch.setattr(geo, "BUNDLED_GEO_DIR", tmp_path / "bundle")
    monkeypatch.setattr(geo, "SYSTEM_ASSET_DIRS", ())

    assert asset_dir_for_core(tmp_path / "bin" / "xray") is None


@pytest.mark.parametrize("data", [b"\x0a\x03\x0a\x04R", b"\x0a\x00\x0a\x03\x0a\x01R"])
def test_category_name_must_fit_inside_its_entry(tmp_path, data):
    path = tmp_path / GEOSITE_FILE
    path.write_bytes(data)

    assert read_categories(path) == frozenset()
