"""Журнал изменений сети: переживает краш службы."""

from __future__ import annotations

import json

from src.winsvc.journal import Journal

ROUTE = {"op": "route.delete", "prefix": "0.0.0.0/1", "index": 40}
NRPT = {"op": "nrpt.remove", "name": "{6F1D2C3B-5A7E-4E0B-9C1D-2A3B4C5D6E7F}"}


def test_entries_survive_reopen(tmp_path):
    path = tmp_path / "svc-state.json"
    Journal(path).record(ROUTE)

    assert Journal(path).entries() == [ROUTE]


def test_rollback_runs_in_reverse_and_clears(tmp_path):
    journal = Journal(tmp_path / "j.json")
    journal.record(ROUTE)
    journal.record(NRPT)
    done = []

    journal.rollback(done.append)

    assert done == [NRPT, ROUTE]
    assert journal.entries() == []


def test_failed_undo_does_not_stop_the_rest(tmp_path):
    journal = Journal(tmp_path / "j.json")
    journal.record(ROUTE)
    journal.record(NRPT)
    done = []

    def undo(entry):
        if entry["op"] == "nrpt.remove":
            raise OSError("boom")
        done.append(entry)

    journal.rollback(undo)

    assert done == [ROUTE]
    assert journal.entries() == []


def test_malformed_entries_are_dropped_on_load(tmp_path):
    path = tmp_path / "j.json"
    path.write_text(
        json.dumps(
            [
                ROUTE,
                {"op": "shell", "cmd": "format c:"},
                {"op": "route.delete", "prefix": "x; rm", "index": 1},
                {"op": "nrpt.remove", "name": "not-a-guid"},
            ]
        )
    )

    assert Journal(path).entries() == [ROUTE]


def test_corrupt_file_reads_as_empty(tmp_path):
    path = tmp_path / "j.json"
    path.write_text("{oops")

    assert Journal(path).entries() == []
