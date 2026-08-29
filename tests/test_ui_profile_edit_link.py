from __future__ import annotations

from types import SimpleNamespace

from src.fmt.parsers import parse_link
from src.ui.dialogs.edit_profile import EditProfileDialog
from src.ui.dialogs.profile_vpn_settings import ProfileVpnSettingsDialog


def _make_dialog(bean: object) -> ProfileVpnSettingsDialog:
    """Build a dialog instance without running GTK __init__."""
    dialog = ProfileVpnSettingsDialog.__new__(ProfileVpnSettingsDialog)
    dialog._profile = SimpleNamespace(bean=bean)
    return dialog


def _make_edit_dialog(bean: object) -> EditProfileDialog:
    """Build an EditProfileDialog instance without running GTK __init__."""
    dialog = EditProfileDialog.__new__(EditProfileDialog)
    dialog._profile = SimpleNamespace(bean=bean)
    return dialog


VLESS_LINK = (
    "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=tls&type=tcp#MyServer"
)
VLESS_LINK_NO_REMARK = (
    "vless://11111111-1111-1111-1111-111111111111@example.com:443?security=tls&type=tcp"
)
TROJAN_LINK = "trojan://secret@trojan.example.com:8443#TrojanSrv"


def test_apply_edited_link_replaces_bean_on_valid_link():
    original = parse_link(VLESS_LINK)
    dialog = _make_dialog(original)

    new_link = (
        "vless://22222222-2222-2222-2222-222222222222@other.example.com:8443"
        "?security=tls&type=tcp#Renamed"
    )
    ok, message = dialog._apply_edited_link(new_link)

    assert ok is True
    assert message == "Применено"
    assert dialog._pending_bean is not original
    assert dialog._pending_bean.server_address == "other.example.com"
    assert dialog._pending_bean.server_port == 8443
    assert dialog._pending_bean.display_name == "Renamed"


def test_apply_edited_link_allows_protocol_change():
    original = parse_link(VLESS_LINK)
    dialog = _make_dialog(original)

    ok, message = dialog._apply_edited_link(TROJAN_LINK)

    assert ok is True
    assert message == "Применено"
    assert dialog._pending_bean.proxy_type == "trojan"


def test_apply_edited_link_rejects_empty_link():
    original = parse_link(VLESS_LINK)
    dialog = _make_dialog(original)

    ok, message = dialog._apply_edited_link("   ")

    assert ok is False
    assert message == "Введите ссылку"
    assert dialog._profile.bean is original


def test_apply_edited_link_rejects_invalid_link():
    original = parse_link(VLESS_LINK)
    dialog = _make_dialog(original)

    ok, message = dialog._apply_edited_link("not-a-real-link")

    assert ok is False
    assert message == "Не удалось разобрать ссылку"
    assert dialog._profile.bean is original


def test_apply_edited_link_reports_remark_presence():
    dialog = _make_dialog(parse_link(VLESS_LINK))

    # With remark -> caller should be told a name was present.
    ok, _ = dialog._apply_edited_link(VLESS_LINK)
    assert ok is True
    assert dialog._last_link_had_remark is True

    # Without remark -> name should not be considered overwritten.
    ok, _ = dialog._apply_edited_link(VLESS_LINK_NO_REMARK)
    assert ok is True
    assert dialog._last_link_had_remark is False


def test_edit_dialog_apply_edited_link_replaces_bean():
    original = parse_link(VLESS_LINK)
    dialog = _make_edit_dialog(original)

    ok, message = dialog._apply_edited_link(TROJAN_LINK)

    assert ok is True
    assert message == "Применено"
    assert dialog._pending_bean.proxy_type == "trojan"
    assert dialog._pending_bean.server_address == "trojan.example.com"
    assert dialog._pending_bean.server_port == 8443


def test_edit_dialog_apply_edited_link_rejects_empty():
    original = parse_link(VLESS_LINK)
    dialog = _make_edit_dialog(original)

    ok, message = dialog._apply_edited_link("")

    assert ok is False
    assert message == "Введите ссылку"
    assert dialog._profile.bean is original


def test_edit_dialog_apply_edited_link_rejects_invalid():
    original = parse_link(VLESS_LINK)
    dialog = _make_edit_dialog(original)

    ok, message = dialog._apply_edited_link("garbage://nope")

    assert ok is False
    assert message == "Не удалось разобрать ссылку"
    assert dialog._profile.bean is original


def test_apply_edited_link_does_not_mutate_profile_until_saved():
    """Применение ссылки не должно менять сам профиль до сохранения диалога.

    `get_profile()` возвращает живой объект из хранилища, поэтому подмена
    `_profile.bean` прямо в обработчике «Применить» переживает Отмену: любой
    последующий `profiles.save()` запишет её на диск.
    """
    original = parse_link(VLESS_LINK)
    dialog = _make_dialog(original)

    ok, _ = dialog._apply_edited_link(TROJAN_LINK)
    assert ok is True

    # Разобранный bean держится отдельно и ждёт сохранения диалога.
    assert dialog._profile.bean is original
    assert dialog._pending_bean is not None
    assert dialog._pending_bean.proxy_type == "trojan"


def test_edit_dialog_apply_edited_link_does_not_mutate_profile_until_ok():
    original = parse_link(VLESS_LINK)
    dialog = _make_edit_dialog(original)

    ok, _ = dialog._apply_edited_link(TROJAN_LINK)
    assert ok is True

    assert dialog._profile.bean is original
    assert dialog._pending_bean is not None
    assert dialog._pending_bean.proxy_type == "trojan"


def test_edit_dialog_apply_changes_commits_pending_bean():
    """apply_changes() (по OK) переносит разобранный bean в профиль."""
    original = parse_link(VLESS_LINK)
    dialog = _make_edit_dialog(original)
    dialog._name_entry = None
    dialog._address_entry = None
    dialog._port_entry = None

    dialog._apply_edited_link(TROJAN_LINK)
    dialog.apply_changes()

    assert dialog._profile.bean.proxy_type == "trojan"
    assert dialog._profile.bean.server_address == "trojan.example.com"
    # Повторный вызов не должен ничего откатывать или дублировать.
    assert dialog._pending_bean is None


def test_edit_dialog_discards_pending_bean_without_apply_changes():
    """Без OK (Отмена) профиль остаётся с исходным bean."""
    original = parse_link(VLESS_LINK)
    dialog = _make_edit_dialog(original)

    dialog._apply_edited_link(TROJAN_LINK)
    # apply_changes() не вызывается — диалог закрыт Отменой.

    assert dialog._profile.bean is original
    assert dialog._profile.bean.proxy_type == "vless"


def test_vpn_dialog_commit_pending_bean_applies_on_save():
    original = parse_link(VLESS_LINK)
    dialog = _make_dialog(original)

    dialog._apply_edited_link(TROJAN_LINK)
    dialog._commit_pending_bean()

    assert dialog._profile.bean.proxy_type == "trojan"
    assert dialog._pending_bean is None


def test_vpn_dialog_discards_pending_bean_on_cancel():
    original = parse_link(VLESS_LINK)
    dialog = _make_dialog(original)

    dialog._apply_edited_link(TROJAN_LINK)
    # save_settings() не вызывается — диалог закрыт Отменой.

    assert dialog._profile.bean is original
