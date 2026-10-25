"""Общий журнал отката: схему записей задаёт владелец."""

from __future__ import annotations

import json

import pytest

from src.core.net_journal import Journal


def _only_ops(entry: object) -> bool:
    return isinstance(entry, dict) and entry.get("op") == "ok"


def test_owner_schema_filters_entries_on_load(tmp_path):
    path = tmp_path / "j.json"
    path.write_text(json.dumps([{"op": "ok"}, {"op": "rm -rf"}, "junk"]))

    assert Journal(path, _only_ops).entries() == [{"op": "ok"}]


def test_record_refuses_entries_outside_the_schema(tmp_path):
    journal = Journal(tmp_path / "j.json", _only_ops)

    with pytest.raises(ValueError, match="invalid journal entry"):
        journal.record({"op": "rm -rf"})

    assert journal.entries() == []


def test_clear_forgets_entries_without_undo(tmp_path):
    path = tmp_path / "j.json"
    journal = Journal(path, _only_ops)
    journal.record({"op": "ok"})

    journal.clear()

    assert Journal(path, _only_ops).entries() == []
