"""Persistenz: Verlauf und Einstellungen auf der Platte."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

import OneTimeSecret_Client as ots


def make_entry(identifier: str = "MID", **overrides: object) -> ots.HistoryEntry:
    fields = {
        "created_at": "2026-01-01T10:00:00+00:00",
        "recipient": "you@example.org",
        "ttl_label": "7d",
        "ttl_seconds": 604800,
        "metadata_key": "MK",
        "metadata_identifier": identifier,
        "secret_preview": "abc1234",
        "last_state": ots.STATE_NEW,
        "last_checked": "2026-01-01T10:00:00+00:00",
    }
    fields.update(overrides)
    return ots.HistoryEntry(**fields)  # type: ignore[arg-type]


# ---- HistoryStore ----------------------------------------------------------

def test_history_starts_empty_when_no_file_exists(tmp_path: Path) -> None:
    store = ots.HistoryStore(tmp_path / "history.json")
    assert store.entries() == []


def test_history_add_puts_the_newest_first(tmp_path: Path) -> None:
    store = ots.HistoryStore(tmp_path / "history.json")
    store.add(make_entry("first"))
    store.add(make_entry("second"))
    assert [e.metadata_identifier for e in store.entries()] == ["second", "first"]


def test_history_survives_a_reload(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    ots.HistoryStore(path).add(make_entry("kept"))
    assert [e.metadata_identifier for e in ots.HistoryStore(path).entries()] == ["kept"]


def test_history_is_capped(tmp_path: Path) -> None:
    store = ots.HistoryStore(tmp_path / "history.json")
    for i in range(ots.HistoryStore.MAX_ENTRIES + 10):
        store.add(make_entry(f"id-{i}"))
    entries = store.entries()
    assert len(entries) == ots.HistoryStore.MAX_ENTRIES
    assert entries[0].metadata_identifier == f"id-{ots.HistoryStore.MAX_ENTRIES + 9}"


def test_history_entries_returns_a_copy(tmp_path: Path) -> None:
    store = ots.HistoryStore(tmp_path / "history.json")
    store.add(make_entry())
    store.entries().clear()
    assert len(store.entries()) == 1


def test_update_state_stamps_the_check_time(tmp_path: Path) -> None:
    store = ots.HistoryStore(tmp_path / "history.json")
    store.add(make_entry("MID", last_checked=""))
    store.update_state("MID", "burned")
    entry = store.entries()[0]
    assert entry.last_state == "burned"
    assert entry.last_checked


def test_update_state_ignores_unknown_identifiers(tmp_path: Path) -> None:
    store = ots.HistoryStore(tmp_path / "history.json")
    store.add(make_entry("MID"))
    store.update_state("other", "burned")
    assert store.entries()[0].last_state == ots.STATE_NEW


def test_remove_and_clear(tmp_path: Path) -> None:
    store = ots.HistoryStore(tmp_path / "history.json")
    store.add(make_entry("a"))
    store.add(make_entry("b"))
    store.remove("a")
    assert [e.metadata_identifier for e in store.entries()] == ["b"]
    store.clear()
    assert store.entries() == []


def test_corrupt_history_starts_empty_instead_of_crashing(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text("{not json", encoding="utf-8")
    assert ots.HistoryStore(path).entries() == []


def test_history_ignores_non_list_content(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text('{"nope": true}', encoding="utf-8")
    assert ots.HistoryStore(path).entries() == []


def test_history_skips_broken_records(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps(["string", 42, {"metadata_identifier": "ok"}]), encoding="utf-8")
    entries = ots.HistoryStore(path).entries()
    assert [e.metadata_identifier for e in entries] == ["ok"]


def test_history_entry_tolerates_a_broken_ttl(tmp_path: Path) -> None:
    entry = ots.HistoryEntry.from_dict({"metadata_identifier": "x", "ttl_seconds": "nope"})
    assert entry.ttl_seconds == 0


def test_history_never_stores_the_secret_itself(tmp_path: Path) -> None:
    """`secret_preview` hält bewusst die Receipt-shortid – die Datei liegt im Klartext."""
    assert "secret" not in {f for f in ots.HistoryEntry.__dataclass_fields__ if f == "secret"}
    store = ots.HistoryStore(tmp_path / "history.json")
    store.add(make_entry(secret_preview="abc1234"))
    assert "my-actual-secret" not in (tmp_path / "history.json").read_text(encoding="utf-8")


# ---- SettingsStore ---------------------------------------------------------

@pytest.fixture
def no_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kein Credential Manager – der Key landet dann in settings.json."""
    monkeypatch.setattr(ots, "_KEYRING_AVAILABLE", False)
    monkeypatch.setattr(ots, "keyring", None)


def test_settings_default_when_no_file(tmp_path: Path, no_keyring: None) -> None:
    store = ots.SettingsStore(tmp_path / "settings.json")
    assert store.current.api_url == ots.API_URL
    assert store.current.language == ots.DEFAULT_LANGUAGE
    assert store.current.default_ttl == ots.DEFAULT_TTL_KEY


def test_settings_round_trip(tmp_path: Path, no_keyring: None) -> None:
    path = tmp_path / "settings.json"
    store = ots.SettingsStore(path)
    store.save(ots.Settings(
        api_url="https://uk.onetimesecret.com/api/v2/secret/conceal",
        api_user="me@example.org",
        api_key="k",
        region="uk",
        language="de",
        request_timeout=42,
        default_ttl="1h",
    ))
    reloaded = ots.SettingsStore(path).current
    assert reloaded.region == "uk"
    assert reloaded.language == "de"
    assert reloaded.request_timeout == 42
    assert reloaded.default_ttl == "1h"


def test_corrupt_settings_fall_back_to_defaults(tmp_path: Path, no_keyring: None) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{broken", encoding="utf-8")
    assert ots.SettingsStore(path).current.api_url == ots.API_URL


def test_settings_migrate_the_legacy_ttl_label(tmp_path: Path, no_keyring: None) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"default_ttl_label": "3 Tage"}), encoding="utf-8")
    assert ots.SettingsStore(path).current.default_ttl == "3d"


def test_settings_reject_an_unusable_timeout(tmp_path: Path, no_keyring: None) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"request_timeout": "nonsense"}), encoding="utf-8")
    assert ots.SettingsStore(path).current.request_timeout == ots.REQUEST_TIMEOUT_SECONDS


def test_region_is_derived_from_the_url_when_missing(tmp_path: Path, no_keyring: None) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"api_url": "https://ca.onetimesecret.com/api/v2/secret/conceal"}),
        encoding="utf-8",
    )
    assert ots.SettingsStore(path).current.region == "ca"


def test_key_lands_in_settings_json_without_a_keyring(tmp_path: Path, no_keyring: None) -> None:
    path = tmp_path / "settings.json"
    store = ots.SettingsStore(path)
    store.save(ots.Settings(
        api_url=ots.API_URL, api_user="me@example.org", api_key="plaintext-key",
        region="eu", language="en", request_timeout=20, default_ttl="7d",
    ))
    assert json.loads(path.read_text(encoding="utf-8"))["api_key"] == "plaintext-key"


def test_key_is_kept_out_of_settings_json_when_stored_in_the_keyring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(ots, "_KEYRING_AVAILABLE", True)
    monkeypatch.setattr(
        ots.SettingsStore, "_write_key_to_keyring",
        lambda self, user, key: bool(vault.__setitem__((ots.KEYRING_SERVICE, user), key) or True),
    )
    monkeypatch.setattr(
        ots.SettingsStore, "_read_key_from_keyring",
        lambda self, user: vault.get((ots.KEYRING_SERVICE, user), ""),
    )

    path = tmp_path / "settings.json"
    ots.SettingsStore(path).save(ots.Settings(
        api_url=ots.API_URL, api_user="me@example.org", api_key="dpapi-key",
        region="eu", language="en", request_timeout=20, default_ttl="7d",
    ))

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["api_key"] == ""
    assert ots.SettingsStore(path).current.api_key == "dpapi-key"


def test_a_failed_keyring_write_never_downgrades_to_plaintext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ist ein Keyring da und sein Schreiben scheitert, darf der Key nicht
    stillschweigend im Klartext landen – die UI verspricht dann DPAPI."""
    monkeypatch.setattr(ots, "_KEYRING_AVAILABLE", True)
    monkeypatch.setattr(ots.SettingsStore, "_write_key_to_keyring", lambda self, user, key: False)
    monkeypatch.setattr(ots.SettingsStore, "_read_key_from_keyring", lambda self, user: "")
    monkeypatch.setattr(ots.SettingsStore, "_delete_key_from_keyring", lambda self, user: None)

    path = tmp_path / "settings.json"
    storage = ots.SettingsStore(path).save(ots.Settings(
        api_url=ots.API_URL, api_user="me@example.org", api_key="never-write-me",
        region="eu", language="en", request_timeout=20, default_ttl="7d",
    ))

    assert storage == ots.KEY_STORAGE_FAILED
    on_disk = path.read_text(encoding="utf-8")
    assert "never-write-me" not in on_disk
    assert json.loads(on_disk)["api_key"] == ""


def test_save_reports_where_the_key_landed(tmp_path: Path, no_keyring: None) -> None:
    store = ots.SettingsStore(tmp_path / "settings.json")
    settings = ots.Settings(
        api_url=ots.API_URL, api_user="me@example.org", api_key="k",
        region="eu", language="en", request_timeout=20, default_ttl="7d",
    )
    assert store.save(settings) == ots.KEY_STORAGE_FILE
    assert store.save(replace_key(settings, "")) == ots.KEY_STORAGE_NONE


def replace_key(settings: ots.Settings, key: str) -> ots.Settings:
    data = settings.to_dict()
    data["api_key"] = key
    return ots.Settings.from_dict(data)


def test_clearing_the_key_removes_the_keyring_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nach `Zurücksetzen` darf kein gültiges Credential im Credential Manager
    zurückbleiben – sonst überlebt der Zugang die Übergabe des Rechners."""
    vault: dict[str, str] = {"me@example.org": "old-key"}
    monkeypatch.setattr(ots, "_KEYRING_AVAILABLE", True)
    monkeypatch.setattr(
        ots.SettingsStore, "_write_key_to_keyring",
        lambda self, user, key: bool(vault.__setitem__(user, key) or True),
    )
    monkeypatch.setattr(ots.SettingsStore, "_read_key_from_keyring", lambda self, user: vault.get(user, ""))
    monkeypatch.setattr(ots.SettingsStore, "_delete_key_from_keyring", lambda self, user: vault.pop(user, None))

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"api_user": "me@example.org"}), encoding="utf-8")
    store = ots.SettingsStore(path)
    assert store.current.api_key == "old-key"

    store.save(ots.Settings.defaults())
    assert vault == {}


def test_switching_users_removes_the_previous_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault: dict[str, str] = {"old@example.org": "old-key"}
    monkeypatch.setattr(ots, "_KEYRING_AVAILABLE", True)
    monkeypatch.setattr(
        ots.SettingsStore, "_write_key_to_keyring",
        lambda self, user, key: bool(vault.__setitem__(user, key) or True),
    )
    monkeypatch.setattr(ots.SettingsStore, "_read_key_from_keyring", lambda self, user: vault.get(user, ""))
    monkeypatch.setattr(ots.SettingsStore, "_delete_key_from_keyring", lambda self, user: vault.pop(user, None))

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"api_user": "old@example.org"}), encoding="utf-8")
    store = ots.SettingsStore(path)
    store.save(ots.Settings(
        api_url=ots.API_URL, api_user="new@example.org", api_key="new-key",
        region="eu", language="en", request_timeout=20, default_ttl="7d",
    ))
    assert vault == {"new@example.org": "new-key"}


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes do not apply on Windows")
def test_config_files_are_not_world_readable(tmp_path: Path, no_keyring: None) -> None:
    settings_path = tmp_path / "settings.json"
    ots.SettingsStore(settings_path).save(ots.Settings(
        api_url=ots.API_URL, api_user="me@example.org", api_key="k",
        region="eu", language="en", request_timeout=20, default_ttl="7d",
    ))
    history_path = tmp_path / "history.json"
    ots.HistoryStore(history_path).add(make_entry())

    for path in (settings_path, history_path):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600, path


def test_to_dict_safe_drops_the_key() -> None:
    settings = ots.Settings(
        api_url=ots.API_URL, api_user="me", api_key="top-secret",
        region="eu", language="en", request_timeout=20, default_ttl="7d",
    )
    assert settings.to_dict_safe()["api_key"] == ""
    assert settings.to_dict()["api_key"] == "top-secret"
