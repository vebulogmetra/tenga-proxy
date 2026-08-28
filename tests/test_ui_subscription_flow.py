from __future__ import annotations

from types import SimpleNamespace

import gi

gi.require_version("Gtk", "3.0")

from gi.repository import Gtk

from src.ui import main_window
from src.ui.dialogs import subscription


def test_subscription_dialog_stays_open_after_invalid_input(monkeypatch):
    class FakeDialog:
        def __init__(self, parent, group):
            self.run_calls = 0
            self.destroyed = False

        def run(self):
            self.run_calls += 1
            return Gtk.ResponseType.OK

        def get_subscription_data(self):
            if self.run_calls == 1:
                return None
            return ("Test", "https://example.com/sub")

        def destroy(self):
            self.destroyed = True

    dialog = FakeDialog(None, None)

    def make_dialog(_parent, _group):
        return dialog

    monkeypatch.setattr(subscription, "SubscriptionDialog", make_dialog)

    result = subscription.show_subscription_dialog()

    assert result == ("Test", "https://example.com/sub")
    assert dialog.run_calls == 2
    assert dialog.destroyed is True


def test_subscription_update_preserves_background_error_for_ui(monkeypatch):
    group = SimpleNamespace(id=1, name="Test", is_subscription=True, subscription_url="https://x")
    profiles = SimpleNamespace(get_group=lambda _group_id: group)
    window = SimpleNamespace(
        _context=SimpleNamespace(profiles=profiles, config=object()),
        shown_results=[],
    )
    window._show_update_result = lambda *args: window.shown_results.append(args)

    class FakeDialog:
        def __init__(self, **kwargs):
            pass

        def set_wmclass(self, *args):
            pass

        def set_type_hint(self, *args):
            pass

        def set_skip_taskbar_hint(self, *args):
            pass

        def format_secondary_text(self, *args):
            pass

        def show(self):
            pass

    class FailingUpdater:
        def __init__(self, **kwargs):
            pass

        def update(self, *args, **kwargs):
            raise RuntimeError("network failed")

    class ImmediateThread:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

    callbacks = []
    monkeypatch.setattr(main_window.Gtk, "MessageDialog", FakeDialog)
    monkeypatch.setattr(main_window, "SubscriptionUpdater", FailingUpdater)
    monkeypatch.setattr(main_window.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(main_window.GLib, "idle_add", callbacks.append)

    main_window.MainWindow._update_subscription(window, group.id)
    callbacks[0]()

    assert window.shown_results[0][1:] == (False, 0, "Test", "network failed")
