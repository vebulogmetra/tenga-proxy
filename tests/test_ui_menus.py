"""Состав меню и сочетания: GTK и Qt должны предлагать одно и то же."""

from __future__ import annotations

import re
from pathlib import Path

from src.ui.logic.menus import MAIN_MENU

ROOT = Path(__file__).resolve().parents[1]


def test_main_menu_has_network_diagnostics_after_latency():
    names = [name for name, _ in MAIN_MENU]
    assert names.index("network-diagnostics") == names.index("test-latency") + 1
    assert dict(MAIN_MENU)["network-diagnostics"] == "Диагностика сети…"


def test_ctrl_d_is_declared_in_both_toolkits():
    gtk = (ROOT / "src/ui/application.py").read_text(encoding="utf-8")
    qt = (ROOT / "src/ui/qt/dialogs/shortcuts.py").read_text(encoding="utf-8")
    assert re.search(r'"app\.network-diagnostics": \["<Control>d"\]', gtk)
    assert re.search(r'"network-diagnostics": "Ctrl\+D"', qt)


def test_main_menu_has_the_log_item_after_settings():
    from src.ui.logic.menus import MAIN_MENU

    names = [name for name, _label in MAIN_MENU]
    assert names.index("show-log") == names.index("settings") + 1
    assert dict(MAIN_MENU)["show-log"] == "Журнал…"
