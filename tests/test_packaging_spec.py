"""Состав Windows-сборки: spec PyInstaller, исполненный с подменными классами."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "packaging" / "windows" / "tenga-proxy.spec"


class _Recorder:
    """Запоминает аргументы вместо сборки; у Analysis есть поля, нужные PYZ/EXE."""

    calls: list[_Recorder] = []

    def __init__(self, *args, **kwargs):
        self.args, self.kwargs = args, kwargs
        self.pure = self.scripts = self.binaries = self.datas = ()
        _Recorder.calls.append(self)


def _run_spec() -> dict:
    _Recorder.calls = []
    names = {
        "SPECPATH": str(SPEC.parent),
        "Analysis": type("Analysis", (_Recorder,), {}),
        "PYZ": type("PYZ", (_Recorder,), {}),
        "EXE": type("EXE", (_Recorder,), {}),
        "COLLECT": type("COLLECT", (_Recorder,), {}),
    }
    exec(compile(SPEC.read_text(encoding="utf-8"), str(SPEC), "exec"), names)
    return names


def _analyses() -> tuple[_Recorder, _Recorder]:
    names = _run_spec()
    return names["gui"], names["svc"]


def test_gui_bundle_has_no_gtk():
    gui, _svc = _analyses()

    assert "gi" in gui.kwargs["excludes"]
    assert not any("gi" in name for name in gui.kwargs.get("hiddenimports", []))
    assert "hooksconfig" not in gui.kwargs


def test_gui_bundle_carries_qt_resources():
    gui, _svc = _analyses()
    bundled = {Path(src).relative_to(ROOT).as_posix() for src, _dest in gui.kwargs["datas"]}

    # Всё, что Qt-интерфейс читает с диска рядом с модулями.
    resources = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "src" / "ui" / "qt").rglob("*")
        if path.is_file() and path.suffix not in (".py", ".pyc")
    }
    assert resources and resources <= bundled
    assert "src/ui/style.css" not in bundled
    assert not any(name.startswith("assets/screen-") for name in bundled)


def test_qt_network_stays_in_the_bundle():
    gui, _svc = _analyses()

    # Failover слушает QNetworkInformation.
    assert "PySide6.QtNetwork" not in gui.kwargs["excludes"]
    assert "PySide6.QtQml" in gui.kwargs["excludes"]


def test_service_bundle_has_no_interface():
    _gui, svc = _analyses()

    assert {"gi", "PySide6"} <= set(svc.kwargs["excludes"])


def test_both_exes_land_in_one_directory():
    names = _run_spec()
    exes = [call for call in _Recorder.calls if type(call).__name__ == "EXE"]

    assert [exe.kwargs["name"] for exe in exes] == ["tenga-proxy", "tenga-proxy-svc"]
    assert names["coll"].kwargs["name"] == "tenga-proxy"
