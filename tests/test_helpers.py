"""Reine Hilfsfunktionen: Regionen, TTL-Schlüssel, Text-Utilities."""

from __future__ import annotations

import pytest

import OneTimeSecret_Client as ots

# ---- _first_str / _flag ----------------------------------------------------

def test_first_str_returns_the_first_non_empty_string() -> None:
    assert ots._first_str(None, "", 0, "hit", "miss") == "hit"


def test_first_str_ignores_non_strings() -> None:
    assert ots._first_str(None, 42, True, {"a": 1}) == ""


@pytest.mark.parametrize("value", [True, 1, 2.5, "true", "TRUE", " yes ", "1"])
def test_flag_accepts_truthy_api_encodings(value: object) -> None:
    assert ots._flag(value) is True


@pytest.mark.parametrize("value", [False, 0, 0.0, "false", "no", "", None, [], "maybe"])
def test_flag_rejects_everything_else(value: object) -> None:
    assert ots._flag(value) is False


# ---- Regionen --------------------------------------------------------------

@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://eu.onetimesecret.com/api/v2/secret/conceal", "eu"),
        ("https://onetimesecret.com/api/v2/secret/conceal", "global"),
        ("https://US.ONETIMESECRET.COM/api/v2/secret/conceal", "us"),
        ("https://secrets.example.org/api/v2/secret/conceal", "custom"),
        ("", "custom"),
        ("not a url", "custom"),
    ],
)
def test_detect_region_from_url(url: str, expected: str) -> None:
    assert ots.detect_region_from_url(url) == expected


def test_build_api_url_uses_the_region_host() -> None:
    assert ots.build_api_url("uk") == "https://uk.onetimesecret.com/api/v2/secret/conceal"


def test_build_api_url_keeps_a_custom_url() -> None:
    custom = "https://secrets.example.org/api/v2/secret/conceal"
    assert ots.build_api_url("custom", custom) == custom


def test_build_api_url_falls_back_when_custom_is_empty() -> None:
    assert ots.build_api_url("custom", "") == ots.API_URL


def test_build_api_url_falls_back_for_an_unknown_region() -> None:
    assert ots.build_api_url("mars") == ots.API_URL


def test_every_region_except_custom_has_a_host() -> None:
    for key, (label, host) in ots.REGIONS.items():
        assert label
        assert host or key == "custom"


def test_region_round_trips_through_url_detection() -> None:
    for key, (_label, host) in ots.REGIONS.items():
        if not host:
            continue
        assert ots.detect_region_from_url(ots.build_api_url(key)) == key


# ---- TTL -------------------------------------------------------------------

def test_ttl_preset_keys_are_unique() -> None:
    keys = [p.key for p in ots.PRESETS]
    assert len(keys) == len(set(keys))


def test_ttl_presets_are_ordered_by_duration() -> None:
    seconds = [p.seconds for p in ots.PRESETS]
    assert seconds == sorted(seconds)


def test_default_ttl_key_exists() -> None:
    assert ots.preset_for_key(ots.DEFAULT_TTL_KEY).key == ots.DEFAULT_TTL_KEY


def test_preset_for_key_falls_back_to_the_default() -> None:
    assert ots.preset_for_key("does-not-exist").key == ots.DEFAULT_TTL_KEY


def test_preset_for_seconds_matches_exactly() -> None:
    assert ots.preset_for_seconds(3600).key == "1h"
    assert ots.preset_for_seconds(1234) is None


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("7d", "7d"),
        ("7 Tage", "7d"),      # Alt-Settings vor der Umstellung auf Schlüssel
        ("5 Min", "5m"),
        ("1 Std", "1h"),
        ("1 Tag", "1d"),
        ("", ots.DEFAULT_TTL_KEY),
        ("unbekannt", ots.DEFAULT_TTL_KEY),
    ],
)
def test_resolve_ttl_key_migrates_legacy_labels(stored: str, expected: str) -> None:
    assert ots.resolve_ttl_key(stored) == expected


def test_ttl_label_is_localised() -> None:
    preset = ots.preset_for_key("1d")
    assert preset.label("de") != preset.label("en")
    assert preset.label("de") == ots.STRINGS["ttl.1d"]["de"]


# ---- Text ------------------------------------------------------------------

def test_truncate_leaves_short_text_alone() -> None:
    assert ots._truncate("short", 10) == "short"


def test_truncate_adds_an_ellipsis() -> None:
    assert ots._truncate("abcdefghij", 5) == "abcd…"
    assert len(ots._truncate("abcdefghij", 5)) == 5


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("eu.onetimesecret.com", "EU"),
        ("US.onetimesecret.com", "US"),
        ("onetimesecret.com", "GLOBAL"),
        ("secrets.example.org", "GLOBAL"),
    ],
)
def test_region_label(host: str, expected: str) -> None:
    assert ots._region_label(host) == expected
