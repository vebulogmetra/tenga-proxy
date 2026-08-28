from argparse import Namespace

import cli


def test_bump_version_does_not_change_ruff_target_version(monkeypatch, tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "core" / "scripts").mkdir(parents=True)
    (tmp_path / "src" / "__init__.py").write_text('__version__ = "0.10.5"\n')
    (tmp_path / "core" / "scripts" / "build_appimage.sh").write_text(
        'APP_VERSION="0.10.5"\n'
    )
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """\
[project]
version = "0.10.5"

[tool.ruff]
target-version = "py311"
"""
    )
    monkeypatch.setattr(cli, "__file__", str(tmp_path / "cli.py"))

    result = cli.cmd_bump_version(Namespace(version="0.10.7", force=False, build=False))

    assert result == 0
    assert 'version = "0.10.7"' in pyproject.read_text()
    assert 'target-version = "py311"' in pyproject.read_text()
