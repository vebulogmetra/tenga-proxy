import json

import pytest

from src.core.geo_update import GeoUpdateError, update_geo_bases
from tests.test_core_geo_update import GOOD, make_fetch


def fetch_version(version, files=None):
    get = make_fetch(files or GOOD)

    def fetch(url, limit):
        if url.endswith("/releases/latest"):
            return json.dumps({"tag_name": version}).encode()
        return get(url.replace(version, "202610192206"), limit)

    return fetch


def test_geo_update_refuses_rollback_and_same_version_changed_digest(tmp_path):
    update_geo_bases(tmp_path, fetch=fetch_version("202610192206"))
    manifest = (tmp_path / "release.json").read_bytes()
    with pytest.raises(GeoUpdateError, match="стар"):
        update_geo_bases(tmp_path, fetch=fetch_version("202610182206"))
    from tests.test_core_geo import make_dat

    changed = dict(GOOD, **{"geosite.dat": make_dat("CATEGORY-RU", "CATEGORY-GOV-RU", "OTHER")})
    with pytest.raises(GeoUpdateError, match="сумм"):
        update_geo_bases(tmp_path, fetch=fetch_version("202610192206", changed))
    assert (tmp_path / "release.json").read_bytes() == manifest
