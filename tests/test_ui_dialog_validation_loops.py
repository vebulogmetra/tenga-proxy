from __future__ import annotations

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk

from src.ui.dialogs import add_profile, edit_group


class _FakeDialog:
    def __init__(self, *_args, **_kwargs):
        self.run_calls = 0
        self.destroyed = False

    def run(self):
        self.run_calls += 1
        return Gtk.ResponseType.OK

    def destroy(self):
        self.destroyed = True


def test_edit_group_dialog_reruns_until_valid_name(monkeypatch):
    class FakeGroupDialog(_FakeDialog):
        def get_group_name(self):
            return None if self.run_calls == 1 else "Work"

    dialog = FakeGroupDialog()
    monkeypatch.setattr(edit_group, "EditGroupDialog", lambda *_a, **_k: dialog)

    assert edit_group.show_edit_group_dialog() == "Work"
    assert dialog.run_calls == 2
    assert dialog.destroyed is True


def test_edit_group_dialog_returns_none_on_cancel(monkeypatch):
    class CancelDialog(_FakeDialog):
        def run(self):
            self.run_calls += 1
            return Gtk.ResponseType.CANCEL

        def get_group_name(self):
            raise AssertionError("must not read the name on cancel")

    dialog = CancelDialog()
    monkeypatch.setattr(edit_group, "EditGroupDialog", lambda *_a, **_k: dialog)

    assert edit_group.show_edit_group_dialog() is None
    assert dialog.run_calls == 1
    assert dialog.destroyed is True


def test_add_profile_dialog_reruns_until_link_parses(monkeypatch):
    class FakeAddDialog(_FakeDialog):
        def get_profile(self):
            return None if self.run_calls == 1 else "bean"

    dialog = FakeAddDialog()
    monkeypatch.setattr(add_profile, "AddProfileDialog", lambda *_a, **_k: dialog)

    assert add_profile.show_add_profile_dialog() == "bean"
    assert dialog.run_calls == 2
    assert dialog.destroyed is True


def test_add_profile_dialog_returns_none_on_cancel(monkeypatch):
    class CancelDialog(_FakeDialog):
        def run(self):
            self.run_calls += 1
            return Gtk.ResponseType.CANCEL

        def get_profile(self):
            raise AssertionError("must not read the profile on cancel")

    dialog = CancelDialog()
    monkeypatch.setattr(add_profile, "AddProfileDialog", lambda *_a, **_k: dialog)

    assert add_profile.show_add_profile_dialog() is None
    assert dialog.run_calls == 1
    assert dialog.destroyed is True
