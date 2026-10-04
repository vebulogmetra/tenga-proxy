"""Обновление геобаз по кнопке: проверка суммы, атомарная замена, откат."""

from __future__ import annotations

import hashlib

import pytest

from src.core import geo
from src.core.geo import GEOIP_FILE, GEOSITE_FILE, asset_dir_for_core, asset_dirs, load_catalog
from src.core.geo_update import GEO_SOURCE, GeoUpdateError, update_geo_bases
from tests.test_core_geo import make_dat, put_bases

GOOD = {
    GEOSITE_FILE: make_dat("CATEGORY-RU", "CATEGORY-GOV-RU", "GOOGLE"),
    GEOIP_FILE: make_dat("RU", "PRIVATE", "CN"),
}


def checksum_line(name: str, data: bytes) -> bytes:
    return f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode()


def make_fetch(files: dict[str, bytes], checksums: dict[str, bytes] | None = None):
    """Подмена сети: отдаёт файлы и их `.sha256sum` по адресам источника."""
    checksums = checksums or {name: checksum_line(name, data) for name, data in files.items()}
    requested: list[str] = []

    def fetch(url: str, limit: int) -> bytes:
        requested.append(url)
        assert url.startswith(GEO_SOURCE + "/")
        name = url.removeprefix(GEO_SOURCE + "/")
        if name.endswith(".sha256sum"):
            return checksums[name.removesuffix(".sha256sum")]
        data = files[name]
        if len(data) > limit:
            raise GeoUpdateError("файл больше допустимого")
        return data

    fetch.requested = requested
    return fetch


def test_verified_bases_are_installed(tmp_path):
    target = tmp_path / "geo"

    update_geo_bases(target, fetch=make_fetch(GOOD))

    assert (target / GEOSITE_FILE).read_bytes() == GOOD[GEOSITE_FILE]
    assert (target / GEOIP_FILE).read_bytes() == GOOD[GEOIP_FILE]
    assert sorted(p.name for p in target.iterdir()) == [GEOIP_FILE, GEOSITE_FILE]


def test_checksum_mismatch_keeps_the_old_bases(tmp_path):
    target = put_bases(tmp_path / "geo")
    old = (target / GEOSITE_FILE).read_bytes()
    bad_sums = {name: checksum_line(name, b"something else") for name in GOOD}

    with pytest.raises(GeoUpdateError, match="контрольная сумма"):
        update_geo_bases(target, fetch=make_fetch(GOOD, bad_sums))

    assert (target / GEOSITE_FILE).read_bytes() == old
    assert sorted(p.name for p in target.iterdir()) == [GEOIP_FILE, GEOSITE_FILE]


def test_bases_without_required_categories_are_rejected(tmp_path):
    """База без категорий готовых правил уронила бы ядро при включённом тумблере."""
    files = {**GOOD, GEOIP_FILE: make_dat("CN")}

    with pytest.raises(GeoUpdateError, match="geoip:ru"):
        update_geo_bases(tmp_path / "geo", fetch=make_fetch(files))

    assert not (tmp_path / "geo" / GEOSITE_FILE).exists()


def test_one_bad_file_installs_nothing(tmp_path):
    """Базы меняются парой: половина обновления хуже, чем никакого."""
    files = {**GOOD, GEOIP_FILE: b"\xff\xff\xff"}

    with pytest.raises(GeoUpdateError):
        update_geo_bases(tmp_path / "geo", fetch=make_fetch(files))

    assert not (tmp_path / "geo" / GEOSITE_FILE).exists()


# --- использование скачанных баз -------------------------------------------


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.delenv("XRAY_LOCATION_ASSET", raising=False)
    monkeypatch.setattr(geo, "USER_GEO_DIR", tmp_path / "geo")
    monkeypatch.setattr(geo, "BUNDLED_GEO_DIR", put_bases(tmp_path / "bundle"))
    put_bases(tmp_path / "bin")
    return tmp_path


def test_downloaded_bases_win_over_bundled_ones(dirs):
    update_geo_bases(dirs / "geo", fetch=make_fetch(GOOD))

    assert asset_dir_for_core(dirs / "bin" / "xray") == dirs / "geo"
    assert "google" in load_catalog(asset_dirs(dirs / "bin" / "xray")).geosite


def test_corrupt_downloaded_bases_fall_back_to_bundled_ones(dirs):
    """Битый файл в каталоге обновлений не должен ломать запуск."""
    update_geo_bases(dirs / "geo", fetch=make_fetch(GOOD))
    (dirs / "geo" / GEOIP_FILE).write_bytes(b"\xff\xff\xff")

    assert asset_dir_for_core(dirs / "bin" / "xray") is None
    assert load_catalog(asset_dirs(dirs / "bin" / "xray")).geosite == frozenset({"x"})


@pytest.mark.parametrize("has_previous", [True, False], ids=["existing-pair", "first-install"])
def test_a_failed_second_replacement_rolls_back_the_first(tmp_path, monkeypatch, has_previous):
    from src.core import geo_update

    target = tmp_path / "geo"
    if has_previous:
        put_bases(target)
    before = {p.name: p.read_bytes() for p in target.iterdir()} if target.exists() else {}
    replace = geo_update.os.replace
    calls = 0

    def fail_second(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second rename failed")
        return replace(source, destination)

    monkeypatch.setattr(geo_update.os, "replace", fail_second)
    with pytest.raises(GeoUpdateError, match="не удалось записать"):
        update_geo_bases(target, fetch=make_fetch(GOOD))

    assert {p.name: p.read_bytes() for p in target.iterdir()} == before
