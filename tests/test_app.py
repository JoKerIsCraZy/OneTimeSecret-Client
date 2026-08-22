"""Smoke-Tests gegen die echte Tk-Oberfläche.

Baut das Fenster wirklich auf (versteckt) und klickt sich durch die Bereiche.
Ohne Display werden die Tests übersprungen statt zu scheitern.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

import OneTimeSecret_Client as ots


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """App auf einem leeren Konfigurationsverzeichnis – die echte
    %APPDATA%\\OneTimeSecret bleibt unangetastet."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(ots, "_KEYRING_AVAILABLE", False)

    try:
        window = ots.App()
    except tk.TclError as exc:  # pragma: no cover - CI ohne Desktop
        pytest.skip(f"Tk is unavailable here: {exc}")

    window.withdraw()
    window.update_idletasks()
    try:
        yield window
    finally:
        window.destroy()


def test_app_starts_on_the_send_section(app: ots.App) -> None:
    assert app._current_section == "send"
    assert app._send_view == "form"


def test_sections_can_be_switched(app: ots.App) -> None:
    for section in ("history", "settings", "send"):
        app._show_section(section)
        app.update_idletasks()
        assert app._current_section == section


def test_the_default_ttl_is_preselected(app: ots.App) -> None:
    assert app.ttl_group.value == ots.DEFAULT_TTL_KEY
    assert ots.preset_for_key(app.ttl_group.value).seconds == 604800


def test_choosing_a_ttl_updates_the_selection(app: ots.App) -> None:
    app.ttl_group.set_value("5m")
    app.update_idletasks()
    assert ots.preset_for_key(app.ttl_group.value).seconds == 300


def test_the_ttl_group_is_keyboard_operable(app: ots.App) -> None:
    """Jede Auswahl muss ohne Maus erreichbar sein."""
    group = app.ttl_group
    keys = [key for key, _label in group._items]
    group._focus_index = keys.index("7d")
    group._step(1)
    group._activate()
    assert group.value == keys[keys.index("7d") + 1]


def test_ttl_labels_follow_the_configured_language(app: ots.App) -> None:
    assert app.lang == "en"
    labels = {label for _key, label in app.ttl_group._items}
    assert ots.STRINGS["ttl.7d"]["en"] in labels
    assert ots.STRINGS["ttl.7d"]["de"] not in labels


def test_saving_settings_switches_the_language(app: ots.App) -> None:
    app._save_settings(
        url=ots.API_URL, user="", key="", region="eu",
        language="de", timeout_str="20", default_ttl="1h",
    )
    app.update_idletasks()
    assert app.lang == "de"
    assert app.settings.default_ttl == "1h"
    assert app.ttl_group.value == "1h"
    labels = {label for _key, label in app.ttl_group._items}
    assert ots.STRINGS["ttl.7d"]["de"] in labels


def test_an_invalid_timeout_falls_back_instead_of_crashing(app: ots.App) -> None:
    app._save_settings(
        url=ots.API_URL, user="", key="", region="eu",
        language="en", timeout_str="not-a-number", default_ttl="7d",
    )
    assert app.settings.request_timeout == ots.REQUEST_TIMEOUT_SECONDS


def test_error_messages_follow_the_selected_language(app: ots.App) -> None:
    error = ots._ots_error("error.auth")
    assert app._error_text(error) == ots.STRINGS["error.auth"]["en"]
    app._apply_settings(
        ots.Settings(
            api_url=ots.API_URL, api_user="", api_key="", region="eu",
            language="de", request_timeout=20, default_ttl="7d",
        )
    )
    assert app._error_text(error) == ots.STRINGS["error.auth"]["de"]


def test_error_detail_from_the_server_is_kept(app: ots.App) -> None:
    error = ots._ots_error("error.http", code=500, detail="upstream exploded")
    assert "upstream exploded" in app._error_text(error)


def test_history_renders_new_and_legacy_entries(app: ots.App) -> None:
    """Alte Einträge tragen ein deutsches TTL-Label, neue den Schlüssel –
    beide müssen in der aktuellen Sprache erscheinen."""
    app.history.add(ots.HistoryEntry(
        created_at="2026-01-01T10:00:00+00:00", recipient="you@example.org",
        ttl_label="7 Tage", ttl_seconds=604800, metadata_key="MK",
        metadata_identifier="legacy", secret_preview="abc1234",
        last_state=ots.STATE_NEW, last_checked="2026-01-01T11:00:00+00:00",
    ))
    app.history.add(ots.HistoryEntry(
        created_at="2026-01-02T10:00:00+00:00", recipient=None,
        ttl_label="1h", ttl_seconds=3600, metadata_key="MK2",
        metadata_identifier="modern", secret_preview="def5678",
        last_state="burned", last_checked="2026-01-02T10:00:00+00:00",
    ))
    app._show_section("history")
    app._render_history()
    app.update_idletasks()

    entries = app.history.entries()
    assert app._ttl_label(entries[1]) == ots.STRINGS["ttl.7d"]["en"]
    assert app._ttl_label(entries[0]) == ots.STRINGS["ttl.1h"]["en"]
    assert "to you@example.org" in app._format_meta(entries[1])


def test_state_labels_are_localised(app: ots.App) -> None:
    _color, label = app._state_visual("burned")
    assert label == ots.STRINGS["state.burned"]["en"]


def test_the_status_link_opens_the_v2_receipt_page(
    app: ots.App, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/private/<id> ist die v1-Adresse und liefert auf v2-Servern 404."""
    opened: list[str] = []
    monkeypatch.setattr(ots.webbrowser, "open", lambda url, new=0: opened.append(url) or True)

    assert app.metadata_base.endswith("/receipt")
    app._open_status_link("ABC123")
    assert opened == ["https://eu.onetimesecret.com/receipt/ABC123"]


def test_the_status_link_falls_back_to_the_clipboard(
    app: ots.App, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ohne konfigurierten Browser soll der Link nicht einfach verloren gehen."""
    monkeypatch.setattr(ots.webbrowser, "open", lambda url, new=0: False)
    app._open_status_link("ABC123")
    assert app.clipboard_get() == "https://eu.onetimesecret.com/receipt/ABC123"


def test_the_recipient_link_is_never_persisted(app: ots.App, tmp_path: Path) -> None:
    """Der Empfaenger-Link ist das Geheimnis selbst - er wird beim Klick vom
    Server geholt, nicht in history.json abgelegt."""
    assert "secret_key" not in ots.HistoryEntry.__dataclass_fields__
    app.history.add(ots.HistoryEntry(
        created_at="2026-01-01T10:00:00+00:00", recipient=None, ttl_label="7d",
        ttl_seconds=604800, metadata_key="MK", metadata_identifier="MID",
        secret_preview="abc1234", last_state=ots.STATE_NEW, last_checked="",
    ))
    on_disk = (tmp_path / "OneTimeSecret" / "history.json").read_text(encoding="utf-8")
    assert "/secret/" not in on_disk


def test_the_recipient_link_lands_on_the_clipboard(app: ots.App) -> None:
    app._on_share_link("https://eu.onetimesecret.com/secret/SK")
    assert app.clipboard_get() == "https://eu.onetimesecret.com/secret/SK"


def test_a_message_never_pushes_a_field_out_of_the_send_form(app: ots.App) -> None:
    """Eine eingeblendete Meldung nahm dem Formular Hoehe weg - die untersten
    Zeilen (Passphrase, Erzeugen) verschwanden dabei kommentarlos."""
    # Ein zurueckgezogenes Fenster rechnet keine Geometrie aus - fuer diesen Test
    # muss es kurz sichtbar sein.
    app.deiconify()
    app._show_section("send")
    app._show_message("Eine Meldung, die Platz braucht", "success")
    app.update()
    app.update_idletasks()

    column = app.entry_passphrase.master.master
    assert column.winfo_height() > 100, "Formular wurde nicht ausgemessen"
    for child in column.winfo_children():
        bottom = child.winfo_y() + child.winfo_height()
        assert bottom <= column.winfo_height(), f"{child} ragt aus dem Formular"
    assert app.entry_passphrase.winfo_height() > 1
    assert app.submit_btn.winfo_height() > 1
    app.withdraw()


def test_the_passphrase_can_be_revealed(app: ots.App) -> None:
    entry = app.entry_passphrase.entry
    assert entry.cget("show") == "●"
    app.passphrase_reveal_btn._command()
    assert entry.cget("show") == ""
    app.passphrase_reveal_btn._command()
    assert entry.cget("show") == "●"


def test_a_passphrase_reaches_the_api(app: ots.App, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: dict = {}

    class FakeClient:
        def share(self, secret, ttl, recipient=None, passphrase=None):
            sent.update(secret=secret, ttl=ttl, recipient=recipient, passphrase=passphrase)
            return ots.ShareResult(secret_key="SK", metadata_key="MK",
                                   metadata_identifier="MID", state=ots.STATE_NEW)

    app.txt.insert("1.0", "geheim")
    app.entry_passphrase.entry.insert(0, "  hunter2  ")
    app._request_thread(FakeClient(), "geheim", ots.preset_for_key("1h"), None, "hunter2")
    assert sent["passphrase"] == "hunter2"

    app._on_success("https://eu.onetimesecret.com/secret/SK",
                    ots.ShareResult("SK", "MK", "MID", ots.STATE_NEW),
                    ots.preset_for_key("1h"), None, True)
    app.update()
    assert app.result_passphrase_label.cget("text")
    assert app.history.entries()[0].has_passphrase is True


def test_burnable_states(app: ots.App) -> None:
    assert app._is_burnable(ots.STATE_NEW) is True
    assert app._is_burnable("shared") is True
    assert app._is_burnable("burned") is False
    assert app._is_burnable("REVEALED") is False
