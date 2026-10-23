"""Точка входа службы: каталоги задаются до импорта src."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_service_directories_are_set_before_src_is_imported(tmp_path):
    script = (
        "import svc_main; svc_main.early_environment()\n"
        "from src.core import config\n"
        "from src.winsvc.service import data_dir\n"
        "print(config.CORE_DIR == data_dir())\n"
    )
    env = {**os.environ, "PROGRAMDATA": str(tmp_path)}
    env.pop("TENGA_CONFIG_DIR", None)

    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True
    )

    assert result.stdout.strip() == "True", result.stderr
    assert (tmp_path / "tenga-proxy").is_dir()
