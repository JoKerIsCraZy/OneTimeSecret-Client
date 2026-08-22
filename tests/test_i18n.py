"""Übersetzungen: Vollständigkeit und Fallback-Verhalten.

Der Client startet standardmäßig auf Englisch – deutsche Restketten in der UI
oder im API-Layer sind damit ein Bug, kein Schönheitsfehler.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import OneTimeSecret_Client as ots

SOURCE = Path(ots.__file__).read_text(encoding="utf-8")


def test_every_string_is_translated_into_every_language() -> None:
    languages = {code for code, _label in ots.LANGUAGES}
    missing = {
        key: sorted(languages - set(entry))
        for key, entry in ots.STRINGS.items()
        if languages - set(entry)
    }
    assert missing == {}


def test_no_translation_is_empty() -> None:
    empty = [
        f"{key}/{lang}"
        for key, entry in ots.STRINGS.items()
        for lang, text in entry.items()
        if not text.strip()
    ]
    assert empty == []


def test_every_ttl_preset_has_a_label() -> None:
    for preset in ots.PRESETS:
        assert f"ttl.{preset.key}" in ots.STRINGS


def test_every_state_has_a_label() -> None:
    known_states = {state for state, _flag in ots.OTSClient._STATE_FLAGS}
    known_states |= {ots.STATE_NEW, "shared", "unknown"}
    for state in known_states:
        assert f"state.{state}" in ots.STRINGS


def test_translation_keys_used_in_code_exist() -> None:
    """Fängt Tippfehler in `self.t("…")` ab – `t()` gibt sonst still den Key zurück."""
    used = set(re.findall(r"""(?:self\.)?\bt\(\s*["']([a-z][a-z0-9_.]*\.[a-z0-9_.]+)["']""", SOURCE))
    assert used, "no translation lookups found – has the call pattern changed?"
    assert sorted(used - set(ots.STRINGS)) == []


def test_message_keys_raised_by_the_api_layer_exist() -> None:
    """Jeder `message_key=` an einer OTSError muss übersetzbar sein."""
    raised = set(re.findall(r"""message_key\s*=\s*["']([^"']+)["']""", SOURCE))
    raised |= set(re.findall(r"""_ots_error\(\s*["']([^"']+)["']""", SOURCE))
    assert raised, "no message keys found – has the error construction changed?"
    assert sorted(raised - set(ots.STRINGS)) == []


@pytest.mark.parametrize("lang", ["de", "en"])
def test_t_returns_the_requested_language(lang: str) -> None:
    assert ots.t("nav.send", lang) == ots.STRINGS["nav.send"][lang]


def test_t_falls_back_to_the_default_language() -> None:
    assert ots.t("nav.send", "fr") == ots.STRINGS["nav.send"][ots.DEFAULT_LANGUAGE]


def test_t_returns_the_key_when_the_string_is_unknown() -> None:
    assert ots.t("does.not.exist", "en") == "does.not.exist"


def test_t_formats_placeholders() -> None:
    assert ots.t("send.chars", "en", n=7) == "7 characters"


def test_t_survives_a_missing_placeholder() -> None:
    """Lieber der unformatierte Text als ein KeyError mitten im Mainloop."""
    assert "{n}" in ots.t("send.chars", "en")
