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
    assert app.pill_bar.selected_key == ots.DEFAULT_TTL_KEY
    assert app.pill_bar.selected_preset().seconds == 604800


def test_selecting_a_ttl_pill_updates_the_selection(app: ots.App) -> None:
    app.pill_bar._select(ots.preset_for_key("5m"))
    app.update_idletasks()
    assert app.pill_bar.selected_preset().seconds == 300


def test_ttl_pills_are_labelled_in_the_configured_language(app: ots.App) -> None:
    assert app.lang == "en"
    labels = {widget.cget("text") for widget in app.pill_bar._labels.values()}
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
    assert app.pill_bar.selected_key == "1h"
    labels = {widget.cget("text") for widget in app.pill_bar._labels.values()}
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


def test_burnable_states(app: ots.App) -> None:
    assert app._is_burnable(ots.STATE_NEW) is True
    assert app._is_burnable("shared") is True
    assert app._is_burnable("burned") is False
    assert app._is_burnable("REVEALED") is False
