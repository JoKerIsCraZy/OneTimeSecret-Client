"""OneTimeSecret Client – professionelles Tkinter-GUI für OneTimeSecret v2."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
import threading
import tkinter as tk
import webbrowser
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox
from typing import ClassVar, NamedTuple, Optional
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

try:
    from urllib3.util.retry import Retry  # type: ignore
except ImportError:  # pragma: no cover - urllib3 ships with requests
    Retry = None  # type: ignore


def _resource_path(*parts: str) -> Path:
    """Resolve a bundled resource path for both source runs and PyInstaller builds."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


ICON_PATH: Path = _resource_path("assets", "onetime.ico")

logger = logging.getLogger("onetimesecret")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ------------------ DEFAULT CONFIG ------------------
# Keine Credentials im Quelltext. Beim ersten Start trägt der User
# E-Mail + API-Key im Settings-Tab ein. Der Key wird dann im Windows
# Credential Manager (DPAPI-verschlüsselt) gespeichert, die übrigen
# Settings unter %APPDATA%\OneTimeSecret\settings.json.
API_USER = ""
API_KEY  = ""
API_URL  = "https://eu.onetimesecret.com/api/v2/secret/conceal"
# ----------------------------------------------------

REQUEST_TIMEOUT_SECONDS: int = 20

STATE_NEW = "new"

# Eigene Fehlerklasse (kein API-Wert): Aufruf ohne hinterlegte Zugangsdaten.
MISSING_CONFIG = "MissingConfig"

# ---- Regionen / Sprache ----
REGIONS: dict[str, tuple[str, str]] = {
    # key -> (Anzeige-Label, Host)
    "eu":     ("EU",     "eu.onetimesecret.com"),
    "global": ("Global", "onetimesecret.com"),
    "us":     ("US",     "us.onetimesecret.com"),
    "uk":     ("UK",     "uk.onetimesecret.com"),
    "ca":     ("CA",     "ca.onetimesecret.com"),
    "nz":     ("NZ",     "nz.onetimesecret.com"),
    "custom": ("Custom", ""),
}
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("de", "Deutsch"),
    ("en", "English"),
)
DEFAULT_LANGUAGE = "en"


def detect_region_from_url(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for key, (_label, region_host) in REGIONS.items():
        if region_host and host == region_host:
            return key
    return "custom"


def build_api_url(region: str, custom_url: str = "") -> str:
    if region == "custom" and custom_url:
        return custom_url
    info = REGIONS.get(region)
    if not info or not info[1]:
        return custom_url or API_URL
    return f"https://{info[1]}/api/v2/secret/conceal"


# ---- Übersetzungen (DE / EN) ----
STRINGS: dict[str, dict[str, str]] = {
    "nav.send":                {"de": "Senden",        "en": "Send"},
    "nav.history":             {"de": "Verlauf",       "en": "History"},
    "nav.settings":            {"de": "Einstellungen", "en": "Settings"},
    "send.title":              {"de": "Einmal-Link erstellen",
                                "en": "Create one-time link"},
    "send.subtitle":           {"de": "Einmal abrufbar · nach Abruf oder Ablauf der TTL automatisch gelöscht.",
                                "en": "Single-use · auto-deleted after retrieval or TTL expiration."},
    "send.recipient":          {"de": "Empfänger",     "en": "Recipient"},
    "send.optional":           {"de": "(optional)",   "en": "(optional)"},
    "send.message":            {"de": "Nachricht",     "en": "Message"},
    "send.ttl":                {"de": "Gültigkeit",    "en": "Lifetime"},
    "send.create":             {"de": "Erzeugen",      "en": "Create"},
    "send.sending":            {"de": "Sende …",       "en": "Sending …"},
    "send.empty":              {"de": "Bitte eine Nachricht eingeben.",
                                "en": "Please enter a message."},
    "send.chars":              {"de": "{n} Zeichen",   "en": "{n} characters"},
    "result.title":            {"de": "Link erzeugt",  "en": "Link created"},
    "result.subtitle":         {"de": "Bereits in der Zwischenablage.",
                                "en": "Already on your clipboard."},
    "result.link_label":       {"de": "Empfänger-Link", "en": "Recipient link"},
    "result.copy":             {"de": "Kopieren",      "en": "Copy"},
    "result.copied":           {"de": "Link kopiert ✓","en": "Link copied ✓"},
    "result.status_check":     {"de": "Status prüfen", "en": "Check status"},
    "result.status_waiting":   {"de": "noch nicht abgerufen", "en": "not retrieved yet"},
    "result.status_history":   {"de": "siehe Verlauf", "en": "see history"},
    "result.warning":          {"de": "⚠  Den Empfänger-Link nicht selbst öffnen – er ist nur einmal abrufbar. "
                                      "Mit Status prüfen sehen, ob der Empfänger ihn schon abgerufen hat.",
                                "en": "⚠  Don't open the recipient link yourself – it can only be retrieved once. "
                                      "Use Check status to see if the recipient has accessed it."},
    "result.new":              {"de": "Neue Nachricht senden", "en": "Send new message"},
    "result.no_status":        {"de": "Kein Status-Identifier vorhanden.",
                                "en": "No status identifier available."},
    "history.title":           {"de": "Erzeugte Secrets", "en": "Created secrets"},
    "history.count_one":       {"de": "{n} Eintrag",   "en": "{n} entry"},
    "history.count_many":      {"de": "{n} Einträge",  "en": "{n} entries"},
    "history.refresh_all":     {"de": "Alle aktualisieren", "en": "Refresh all"},
    "history.clear":           {"de": "Verlauf leeren","en": "Clear history"},
    "history.empty_title":     {"de": "Noch keine Secrets erzeugt",
                                "en": "No secrets created yet"},
    "history.empty_sub":       {"de": "Erzeuge dein erstes Secret im Senden-Bereich.",
                                "en": "Create your first secret in the Send section."},
    "history.cleared":         {"de": "Verlauf geleert","en": "History cleared"},
    "history.empty":           {"de": "Verlauf ist leer.", "en": "History is empty."},
    "history.refreshing":      {"de": "Aktualisiere {n} Einträge …",
                                "en": "Refreshing {n} entries …"},
    "history.row.status":      {"de": "Status",        "en": "Status"},
    "history.row.share":       {"de": "Empfänger-Link", "en": "Recipient link"},
    "history.copy_share":      {"de": "Empfänger-Link kopiert – er ist nur einmal abrufbar",
                                "en": "Recipient link copied – it can only be retrieved once"},
    "history.fetching_share":  {"de": "Hole Empfänger-Link …", "en": "Fetching recipient link …"},
    "history.row.burn":        {"de": "Verbrennen",    "en": "Burn"},
    "history.open_meta":       {"de": "Status-Seite im Browser geöffnet",
                                "en": "Status page opened in the browser"},
    "history.open_failed":     {"de": "Browser ließ sich nicht öffnen – Link stattdessen kopiert",
                                "en": "Could not open a browser – link copied instead"},
    "history.meta.to":         {"de": "an {recipient}", "en": "to {recipient}"},
    "history.meta.ttl":        {"de": "TTL {ttl}",     "en": "TTL {ttl}"},
    "history.meta.checked":    {"de": "geprüft {time}", "en": "checked {time}"},
    "history.refresh_done":    {"de": "{ok}/{total} aktualisiert, {failed} fehlgeschlagen",
                                "en": "{ok}/{total} refreshed, {failed} failed"},
    "burn.action":             {"de": "Verbrennen",    "en": "Burn"},
    "burn.confirm_title":      {"de": "Secret verbrennen?", "en": "Burn secret?"},
    "burn.confirm":            {"de": "Der Empfänger-Link wird sofort ungültig. Die Nachricht kann danach "
                                      "von niemandem mehr abgerufen werden.\n\nFortfahren?",
                                "en": "The recipient link becomes invalid immediately. Nobody will be able "
                                      "to retrieve the message afterwards.\n\nContinue?"},
    "burn.done":               {"de": "Secret verbrannt – Link ist ungültig",
                                "en": "Secret burned – link is invalid"},
    "burn.failed":             {"de": "Verbrennen fehlgeschlagen: {error}",
                                "en": "Burn failed: {error}"},
    "burn.busy":               {"de": "Verbrenne …",   "en": "Burning …"},
    "settings.title":          {"de": "API & Konfiguration", "en": "API & Configuration"},
    "settings.subtitle":       {"de": "Zugangsdaten, Region und Sprache anpassen.",
                                "en": "Configure credentials, region and language."},
    "settings.region":         {"de": "Region",       "en": "Region"},
    "settings.url":            {"de": "API-URL",      "en": "API URL"},
    "settings.user":           {"de": "E-Mail-Adresse", "en": "Email address"},
    "settings.key":            {"de": "API-Key",      "en": "API key"},
    "settings.show":           {"de": "Anzeigen",      "en": "Show"},
    "settings.hide":           {"de": "Verbergen",     "en": "Hide"},
    "settings.timeout":        {"de": "Zeitüberschreitung", "en": "Timeout"},
    "settings.default_ttl":    {"de": "Standard-Gültigkeit", "en": "Default lifetime"},
    "settings.language":       {"de": "Sprache",      "en": "Language"},
    "settings.test":           {"de": "Verbindung testen", "en": "Test connection"},
    "settings.reset":          {"de": "Zurücksetzen",  "en": "Reset"},
    "settings.save":           {"de": "Speichern",     "en": "Save"},
    "settings.saved":          {"de": "Einstellungen gespeichert", "en": "Settings saved"},
    "settings.saved_plaintext": {"de": "Gespeichert – ohne Keyring liegt der API-Key im Klartext "
                                       "in settings.json.",
                                 "en": "Saved – without a keyring the API key sits in plaintext "
                                       "in settings.json."},
    "settings.key_not_stored": {"de": "Einstellungen gespeichert, aber der API-Key konnte nicht im "
                                      "Credential Manager abgelegt werden – er gilt nur für diese "
                                      "Sitzung.",
                                "en": "Settings saved, but the API key could not be placed in the "
                                      "credential manager – it only applies to this session."},
    "settings.reset_done":     {"de": "Auf Standard zurückgesetzt", "en": "Reset to defaults"},
    "settings.testing":        {"de": "Teste …",       "en": "Testing …"},
    "settings.test_ok_full":   {"de": "Verbindung & Login OK · Server {version} ({status})",
                                "en": "Connection & login OK · server {version} ({status})"},
    "settings.test_ok_anon":   {"de": "Server erreichbar ({version}) – keine Zugangsdaten hinterlegt",
                                "en": "Server reachable ({version}) – no credentials configured"},
    "settings.test_fail":      {"de": "Verbindung fehlgeschlagen: {error}",
                                "en": "Connection failed: {error}"},
    "settings.keyring_yes":    {"de": "API-Key wird im Windows Credential Manager gespeichert (DPAPI-verschlüsselt).",
                                "en": "API key is stored in Windows Credential Manager (DPAPI-encrypted)."},
    "settings.keyring_no":     {"de": "Keyring nicht verfügbar – API-Key liegt im Klartext in settings.json. "
                                      "Installiere `pip install keyring` für sichere Speicherung.",
                                "en": "Keyring not available – API key is stored in plaintext in settings.json. "
                                      "Install `pip install keyring` for secure storage."},
    "state.new":               {"de": "wartet",        "en": "waiting"},
    "state.shared":            {"de": "geteilt",       "en": "shared"},
    "state.previewed":         {"de": "Vorschau",      "en": "preview"},
    "state.revealed":          {"de": "abgerufen",     "en": "retrieved"},
    "state.burned":            {"de": "verbrannt",     "en": "burned"},
    "state.expired":           {"de": "abgelaufen",    "en": "expired"},
    "state.orphaned":          {"de": "verwaist",      "en": "orphaned"},
    "state.unknown":           {"de": "unbekannt",     "en": "unknown"},
    "warn.consumed":           {"de": "⚠ Secret-Status ist '{state}' – möglicherweise schon konsumiert.",
                                "en": "⚠ Secret status is '{state}' – may have been consumed already."},
    "error.api_config":        {"de": "API-Konfiguration fehlt.", "en": "API configuration missing."},
    "error.network":           {"de": "Netzwerkfehler: {error}", "en": "Network error: {error}"},
    "error.unexpected":        {"de": "Unerwarteter Fehler: {error}",
                                "en": "Unexpected error: {error}"},
    "error.no_id":             {"de": "Kein Identifier vorhanden.", "en": "No identifier available."},
    "error.credentials_charset": {"de": "E-Mail oder API-Key enthält Zeichen, die nicht übertragen werden "
                                       "können – beim Kopieren aus einer Tabelle rutscht leicht ein "
                                       "Rahmenzeichen mit hinein. Bitte in den Einstellungen neu eingeben.",
                                 "en": "Email or API key contains characters that cannot be transmitted – "
                                       "copying from a table easily drags a border character along. "
                                       "Please re-enter them in the settings."},
    "error.insecure_url":      {"de": "Unverschlüsselte Verbindung abgelehnt – die API-URL muss mit https:// beginnen.",
                                "en": "Refusing an unencrypted connection – the API URL must start with https://."},
    "error.refused":           {"de": "Der Server hat den Vorgang abgelehnt.",
                                "en": "The server refused the operation."},
    "error.invalid_json":      {"de": "API-Antwort war kein gültiges JSON.",
                                "en": "API response was not valid JSON."},
    "error.auth":              {"de": "Zugangsdaten abgelehnt – E-Mail und API-Key prüfen.",
                                "en": "Credentials rejected – check your email and API key."},
    "error.not_found":         {"de": "Nicht gefunden – das Secret ist abgelaufen, verbrannt oder gehört "
                                      "zu einem anderen Account.",
                                "en": "Not found – the secret has expired, was burned, or belongs to a "
                                      "different account."},
    "error.rate_limit":        {"de": "Rate-Limit erreicht – bitte kurz warten.",
                                "en": "Rate limit reached – please wait a moment."},
    "error.rate_limit_retry":  {"de": "Rate-Limit erreicht – in {seconds}s erneut versuchen.",
                                "en": "Rate limit reached – retry in {seconds}s."},
    "error.rejected":          {"de": "Eingabe wurde abgelehnt (422).",
                                "en": "Input was rejected (422)."},
    "error.rejected_field":    {"de": "Eingabe wurde abgelehnt (422) – Feld: {field}.",
                                "en": "Input was rejected (422) – field: {field}."},
    "error.http":              {"de": "HTTP {code}", "en": "HTTP {code}"},
    "error.no_share_link":     {"de": "Kein Empfänger-Link mehr verfügbar – das Secret wurde abgerufen, "
                                      "verbrannt oder ist abgelaufen.",
                                "en": "No recipient link available any more – the secret was retrieved, "
                                      "burned or has expired."},
    "error.no_secret_key":     {"de": "Antwort ohne Secret-Key.", "en": "Response contained no secret key."},
    "error.no_metadata_key":   {"de": "Antwort ohne Metadata-Key.", "en": "Response contained no metadata key."},
    "nav.no_account":          {"de": "Kein Konto hinterlegt", "en": "No account configured"},
    "send.passphrase":         {"de": "Passphrase",   "en": "Passphrase"},
    "send.passphrase_hint":    {"de": "Der Empfänger braucht sie zusätzlich zum Link – schick sie auf "
                                      "einem anderen Weg, sonst ist der zweite Kanal wirkungslos.",
                                "en": "The recipient needs it on top of the link – send it through a "
                                      "different channel, otherwise the second factor is pointless."},
    "result.passphrase_note":  {"de": "Mit Passphrase geschützt. Ohne sie kann der Empfänger die "
                                      "Nachricht nicht öffnen.",
                                "en": "Protected with a passphrase. Without it the recipient cannot "
                                      "open the message."},
    "history.row.page":        {"de": "Statusseite",  "en": "Status page"},
    "history.meta.passphrase": {"de": "mit Passphrase", "en": "passphrase set"},
    "history.empty_action":    {"de": "Erstes Secret erzeugen", "en": "Create your first secret"},
    "history.state_now":       {"de": "Zustand: {state}", "en": "State: {state}"},
    "history.refresh_ok":      {"de": "{n} Einträge aktualisiert", "en": "{n} entries refreshed"},
    "history.clear_confirm":   {"de": "Der lokale Verlauf wird gelöscht. Die Secrets selbst bleiben "
                                      "davon unberührt.\n\nFortfahren?",
                                "en": "The local history will be deleted. The secrets themselves are "
                                      "not affected.\n\nContinue?"},
    "settings.reset_confirm":  {"de": "Alle Einstellungen werden auf die Vorgaben zurückgesetzt und "
                                      "der hinterlegte API-Key entfernt.\n\nFortfahren?",
                                "en": "All settings return to their defaults and the stored API key "
                                      "is removed.\n\nContinue?"},
    "settings.timeout_hint":   {"de": "Sekunden, die auf eine Antwort des Servers gewartet wird.",
                                "en": "Seconds to wait for a response from the server."},
    "ttl.5m":                  {"de": "5 Min",  "en": "5 min"},
    "ttl.30m":                 {"de": "30 Min", "en": "30 min"},
    "ttl.1h":                  {"de": "1 Std",  "en": "1 hr"},
    "ttl.4h":                  {"de": "4 Std",  "en": "4 hrs"},
    "ttl.12h":                 {"de": "12 Std", "en": "12 hrs"},
    "ttl.1d":                  {"de": "1 Tag",  "en": "1 day"},
    "ttl.3d":                  {"de": "3 Tage", "en": "3 days"},
    "ttl.7d":                  {"de": "7 Tage", "en": "7 days"},
    "ttl.14d":                 {"de": "14 Tage","en": "14 days"},
}


def t(key: str, lang: str, **fmt: object) -> str:
    entry = STRINGS.get(key)
    if not entry:
        return key
    text = entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or key
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError):
            return text
    return text


# ============================================================
# Domain
# ============================================================

@dataclass(frozen=True)
class TTLPreset:
    """`key` ist der stabile, sprachunabhängige Bezeichner – er wird persistiert
    und in der History abgelegt. Das Label ist reine Anzeige und übersetzt."""

    key: str
    seconds: int

    def label(self, lang: str) -> str:
        return t(f"ttl.{self.key}", lang)


PRESETS: tuple[TTLPreset, ...] = (
    TTLPreset("5m", 300),
    TTLPreset("30m", 1800),
    TTLPreset("1h", 3600),
    TTLPreset("4h", 14400),
    TTLPreset("12h", 43200),
    TTLPreset("1d", 86400),
    TTLPreset("3d", 259200),
    TTLPreset("7d", 604800),
    TTLPreset("14d", 1209600),
)
DEFAULT_TTL_KEY: str = "7d"

# Vor der Umstellung auf Schlüssel stand das deutsche Label in settings.json /
# history.json. Alte Dateien sollen ohne Zutun weiterlaufen.
LEGACY_TTL_LABELS: dict[str, str] = {
    "5 Min": "5m", "30 Min": "30m", "1 Std": "1h", "4 Std": "4h", "12 Std": "12h",
    "1 Tag": "1d", "3 Tage": "3d", "7 Tage": "7d", "14 Tage": "14d",
}


def preset_for_key(key: str) -> TTLPreset:
    by_key = {preset.key: preset for preset in PRESETS}
    return by_key.get(key) or by_key.get(DEFAULT_TTL_KEY) or PRESETS[0]


def preset_for_seconds(seconds: int) -> Optional[TTLPreset]:
    for preset in PRESETS:
        if preset.seconds == seconds:
            return preset
    return None


def resolve_ttl_key(value: str) -> str:
    """Nimmt einen Schlüssel oder ein Alt-Label und liefert immer einen gültigen Schlüssel."""
    value = (value or "").strip()
    if any(preset.key == value for preset in PRESETS):
        return value
    return LEGACY_TTL_LABELS.get(value, DEFAULT_TTL_KEY)

# ============================================================
# Theme – Windows 11 (Fluent), dunkel
# ============================================================

class Theme:
    """Fluent-Dunkeldesign in Volltonwerten.

    Fluent legt seine Ebenen als Weiß mit niedriger Deckkraft über den Grund
    (`#FFFFFF0A` und ähnlich). Tk kennt keine Deckkraft auf Widgets, deshalb sind
    die Ebenen hier einmal ausgerechnet und fest hinterlegt."""

    # Ebenen
    BG_BASE       = "#202020"   # Fenster, Navigationsspalte
    BG_LAYER      = "#272727"   # Inhaltsfläche
    BG_CARD       = "#2B2B2B"   # Karten, Listenzeilen, Felder in Ruhe
    BG_CARD_HOVER = "#323232"   # Karte unter dem Zeiger
    BG_CARD_PRESS = "#292929"   # Karte gedrückt
    BG_INPUT      = "#2B2B2B"
    BG_WELL       = "#232323"   # Eingabefeld auf einer Karte
    BG_INPUT_FOCUS = "#1F1F1F"  # Feld mit Schreibmarke: dunkler, wie in Fluent

    # Linien
    STROKE        = "#353535"   # Trennlinien, Kartenrand
    STROKE_STRONG = "#454545"   # Rand eines Steuerelements
    STROKE_HOVER  = "#525252"

    # Text
    TEXT          = "#FFFFFF"
    TEXT_SECONDARY = "#C5C5C5"
    TEXT_TERTIARY = "#9D9D9D"
    TEXT_DISABLED = "#6B6B6B"

    # Akzent – trägt ausschließlich Primäraktion, Auswahl und Zustand
    ACCENT        = "#60CDFF"
    ACCENT_HOVER  = "#7ED8FF"
    ACCENT_PRESS  = "#42B8F0"
    ACCENT_MUTED  = "#2E4756"   # Akzent als Fläche hinter Text
    ON_ACCENT     = "#003A5C"

    # Zustände
    SUCCESS       = "#6CCB5F"
    CAUTION       = "#FCE100"
    DANGER        = "#FF99A4"
    DANGER_STRONG = "#C42B1C"

    # Maße
    RADIUS        = 4
    RADIUS_CARD   = 6
    FOCUS_RING    = "#FFFFFF"


def _rounded_points(x1: float, y1: float, x2: float, y2: float, r: float) -> list[float]:
    """Stützpunkte für ein Rechteck mit runden Ecken.

    Tk kann keine runden Ecken auf Widgets; auf dem Canvas entsteht die Form als
    geglättetes Polygon. Die doppelten Eckpunkte halten die Kanten gerade und
    runden nur die Ecken."""
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]


def control_fill(parent_bg: str) -> str:
    """Fläche eines Knopfs oder einer Kachel, passend zur Unterlage.

    Ohne Umriss trägt allein die Fläche die Abgrenzung – auf der Inhaltsfläche eine
    Stufe heller, auf einer Karte noch eine weiter."""
    return Theme.BG_CARD_HOVER if parent_bg == Theme.BG_CARD else Theme.BG_CARD


def well_fill(parent_bg: str) -> str:
    """Fläche eines Eingabefelds: eine Stufe *dunkler* als die Unterlage, damit es
    als Vertiefung liest und nicht als Knopf."""
    return Theme.BG_WELL if parent_bg == Theme.BG_CARD else Theme.BG_INPUT


def draw_round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float,
                    radius: float, **kwargs: object) -> int:
    return canvas.create_polygon(
        _rounded_points(x1, y1, x2, y2, radius),
        smooth=True, splinesteps=16, **kwargs,  # type: ignore[arg-type]
    )



# ============================================================
# API
# ============================================================

class OTSError(RuntimeError):
    """Wird ausgelöst, wenn der OneTimeSecret-Service nicht erreichbar ist oder unerwartete Daten liefert.

    ``error_type`` ist die maschinenlesbare Fehlerklasse der API (ADR-013), auf die
    aufrufender Code verzweigen kann; ``request_id`` dient dem Support-Abgleich.

    ``message_key``/``message_args`` erlauben es der UI, den Text in der eingestellten
    Sprache zu rendern – ``str(exc)`` bleibt die (englische) Fassung für Logs und
    Kontexte ohne Sprachwahl. ``detail`` ist der unübersetzte Servertext, der an die
    lokalisierte Meldung angehängt wird.
    """

    def __init__(
        self,
        message: str,
        *,
        error_type: str = "",
        request_id: str = "",
        status_code: Optional[int] = None,
        message_key: str = "",
        message_args: Optional[dict] = None,
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.request_id = request_id
        self.status_code = status_code
        self.message_key = message_key
        self.message_args = dict(message_args or {})
        self.detail = detail

    def localized(self, lang: str) -> str:
        """Meldung in der gewünschten Sprache; fällt auf den Rohtext zurück."""
        if not self.message_key:
            return str(self)
        text = t(self.message_key, lang, **self.message_args)
        return f"{text} – {self.detail}" if self.detail else text


def _ots_error(
    message_key: str,
    *,
    error_type: str = "",
    request_id: str = "",
    status_code: Optional[int] = None,
    detail: str = "",
    **message_args: object,
) -> OTSError:
    """Baut eine OTSError, deren Text sowohl übersetzbar als auch sofort lesbar ist."""
    return OTSError(
        t(message_key, DEFAULT_LANGUAGE, **message_args) + (f" – {detail}" if detail else ""),
        error_type=error_type,
        request_id=request_id,
        status_code=status_code,
        message_key=message_key,
        message_args=message_args,
        detail=detail,
    )


class ShareResult(NamedTuple):
    secret_key: str
    metadata_key: str
    metadata_identifier: str
    state: str
    share_domain: str = ""
    share_url: str = ""
    receipt_shortid: str = ""


class ServiceInfo(NamedTuple):
    status: str
    version: str
    authenticated: bool


def _first_str(*candidates: object) -> str:
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    return ""


_HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?(:\d{1,5})?$", re.IGNORECASE)


def _is_valid_host(value: str) -> bool:
    """Prüft, ob ein Wert ein reiner Host (optional mit Port) ist.

    Die Share-Domain kommt aus der Serverantwort und landet in einem Link, den der
    Nutzer weitergibt. Etwas wie `evil.example/x?next=` würde den Empfänger-Link
    auf eine fremde Adresse umbiegen, `user@evil.example` ihn verschleiern."""
    return (
        bool(value)
        and len(value) <= 253
        and ".." not in value
        and _HOST_RE.match(value) is not None
    )


def _flag(value: object) -> bool:
    """Die API typisiert Booleans teils als String ("true") oder Zahl – tolerant auswerten."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return False


class OTSClient:
    """Dünner Wrapper um die OneTimeSecret API v2 (Basic Auth, JSON)."""

    # Zustände, aus denen ein Secret nicht mehr herauskommt.
    TERMINAL_STATES: frozenset[str] = frozenset({"burned", "revealed", "expired", "orphaned", "received"})

    # Reihenfolge = Priorität: terminale Zustände zuerst.
    _STATE_FLAGS: tuple[tuple[str, str], ...] = (
        ("burned", "is_burned"),
        ("revealed", "is_revealed"),
        ("expired", "is_expired"),
        ("orphaned", "is_orphaned"),
        ("previewed", "is_previewed"),
    )

    def __init__(
        self,
        url: str,
        user: str,
        key: str,
        *,
        share_domain: str = "",
        timeout: int = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self.url = url
        self.user = user
        self.key = key
        self.share_domain = share_domain or (urlparse(url).hostname or "onetimesecret.com")
        self.timeout = timeout
        self._session = self._build_session()
        self._lifecycle = threading.Lock()
        self._inflight = 0
        self._closing = False

    # ---- Session / Transport ----

    @staticmethod
    def _build_session() -> requests.Session:
        """Session mit Keep-Alive und Backoff. Retries nur für GET – ein wiederholtes
        POST /conceal würde ein zweites Secret anlegen."""
        session = requests.Session()
        session.headers.update({
            "Accept": "application/json",
            "User-Agent": "OneTimeSecret-Client (+https://github.com/JoKerIsCraZy/OneTimeSecret-Client)",
        })
        if Retry is not None:
            retry = Retry(
                total=2, connect=2, read=2, status=2,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET"}),
                respect_retry_after_header=True,
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
        return session

    def close(self) -> None:
        """Schließt die Session, sobald kein Request mehr unterwegs ist.

        Ein Settings-Speichern tauscht den Client mitten im Betrieb aus; würde die
        Session dabei unter einem laufenden Worker weggezogen, bräche dessen Request
        mit einem irreführenden Netzwerkfehler ab."""
        with self._lifecycle:
            self._closing = True
            idle = self._inflight == 0
        if idle:
            self._session.close()

    def _release(self) -> None:
        with self._lifecycle:
            self._inflight -= 1
            close_now = self._closing and self._inflight == 0
        if close_now:
            self._session.close()

    # ---- Sicherheit ----

    # Loopback bleibt für selbst gehostete Instanzen ohne TLS erreichbar.
    PLAINTEXT_HOSTS: frozenset[str] = frozenset({"localhost", "127.0.0.1", "::1"})

    @classmethod
    def _ensure_secure(cls, url: str) -> None:
        """Der Client spricht HTTPS. Eine http-URL aus den Settings würde Basic-Auth-
        Credentials und das Secret im Klartext über die Leitung schicken."""
        parsed = urlparse(url)
        if parsed.scheme == "https":
            return
        if parsed.scheme == "http" and (parsed.hostname or "").lower() in cls.PLAINTEXT_HOSTS:
            return
        raise _ots_error("error.insecure_url")

    def _ensure_credentials_transmittable(self) -> None:
        """Basic Auth geht als latin-1-kodierter Header raus.

        Ein aus einer Tabelle kopierter Key – etwa mit einem Rahmenzeichen wie │ –
        ließe requests tief im Stack mit einem UnicodeEncodeError scheitern, den der
        Nutzer als "Unerwarteter Fehler: 'latin-1' codec can't encode character"
        vorgesetzt bekäme. Hier gibt es stattdessen eine Meldung, die sagt, was zu
        tun ist."""
        for value in (self.user, self.key):
            try:
                value.encode("latin-1")
            except UnicodeEncodeError as exc:
                raise _ots_error("error.credentials_charset") from exc

    def _api_base(self) -> str:
        parsed = urlparse(self.url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @property
    def has_credentials(self) -> bool:
        return bool(self.user and self.key)

    def _request(
        self,
        method: str,
        url: str,
        *,
        json_body: Optional[dict] = None,
        require_auth: bool = True,
    ) -> dict:
        if require_auth and not self.has_credentials:
            raise _ots_error("error.api_config", error_type=MISSING_CONFIG)
        self._ensure_secure(url)
        self._ensure_credentials_transmittable()

        with self._lifecycle:
            self._inflight += 1
        try:
            response = self._session.request(
                method, url,
                auth=(self.user, self.key) if self.has_credentials else None,
                json=json_body,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            logger.exception("OneTimeSecret API request failed (%s %s)", method, url)
            raise _ots_error("error.network", error=exc) from exc
        except UnicodeEncodeError as exc:
            # Sollte die Vorprüfung nicht greifen: nicht als "unerwarteter Fehler"
            # durchreichen, der Nutzer kann damit nichts anfangen.
            logger.error("Request could not be encoded (%s %s): %s", method, url, exc)
            raise _ots_error("error.credentials_charset") from exc
        finally:
            self._release()

        if response.status_code >= 400:
            raise self._error_from_response(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise _ots_error("error.invalid_json") from exc
        if not isinstance(data, dict):
            return {}

        # v2 meldet einen abgelehnten Vorgang nicht über den Statuscode, sondern
        # über `success` im Body: ein Burn ohne `continue` etwa kommt als HTTP 200
        # mit success=false zurück, ohne dass etwas passiert wäre. Endpunkte ohne
        # dieses Feld (/status, /version) bleiben davon unberührt.
        if data.get("success") is False:
            detail = _first_str(data.get("error"), data.get("message"))
            logger.error("API refused the operation (%s %s): %s", method, url, detail or "-")
            raise _ots_error("error.refused", detail=detail)
        return data

    @staticmethod
    def _error_from_response(response: requests.Response) -> OTSError:
        """Baut aus dem Fehler-Envelope {error, error_type, message, error_id, request_id}
        eine sprechende Exception."""
        code = response.status_code
        payload: dict = {}
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                payload = parsed
        except ValueError:
            # Kein JSON-Envelope (z. B. Proxy-/Gateway-Fehlerseite) – dann bleibt es
            # bei der generischen Meldung anhand des Statuscodes.
            logger.debug("API error response body is not valid JSON (status=%s).", code)

        error_type = _first_str(payload.get("error_type"))
        request_id = _first_str(payload.get("request_id"))
        error_id = _first_str(payload.get("error_id"))
        # In v2 ist `error` die nutzerseitige Meldung, `message` die Legacy-Variante.
        server_msg = _first_str(payload.get("error"), payload.get("message"))
        field = _first_str(payload.get("field"))

        # message_key trägt die übersetzbare Erklärung, detail den unübersetzten
        # Servertext – die UI setzt beides in der eingestellten Sprache zusammen.
        args: dict[str, object] = {}
        if code in (401, 403):
            key = "error.auth"
        elif code == 404:
            key = "error.not_found"
        elif code == 429:
            retry_after = response.headers.get("Retry-After", "")
            key = "error.rate_limit_retry" if retry_after else "error.rate_limit"
            if retry_after:
                args["seconds"] = retry_after
        elif code == 422:
            key = "error.rejected_field" if field else "error.rejected"
            if field:
                args["field"] = field
        else:
            key = "error.http"
            args["code"] = code

        logger.error(
            "API error: status=%s type=%s field=%s request_id=%s error_id=%s msg=%s",
            code, error_type or "-", field or "-", request_id or "-", error_id or "-", server_msg or "-",
        )
        return _ots_error(
            key,
            error_type=error_type,
            request_id=request_id,
            status_code=code,
            detail=server_msg,
            **args,
        )

    # ---- Secrets ----

    def share(self, secret: str, ttl_seconds: int, recipient: Optional[str] = None,
              passphrase: Optional[str] = None) -> ShareResult:
        """Legt das Secret an.

        Mit `passphrase` verlangt der Server sie beim Abruf zusätzlich zum Link.
        Sie wird nirgends gespeichert: der Empfänger muss sie auf einem anderen Weg
        bekommen, sonst hebt sie den Zweck des zweiten Kanals auf."""
        if not self.url:
            raise _ots_error("error.api_config", error_type=MISSING_CONFIG)
        body: dict = {
            "secret": {
                "kind": "conceal",
                "share_domain": self.share_domain,
                "secret": secret,
                "ttl": ttl_seconds,
            }
        }
        if recipient:
            body["secret"]["recipient"] = recipient
        if passphrase:
            body["secret"]["passphrase"] = passphrase

        data = self._request("POST", self.url, json_body=body)
        result = self._share_result(data)
        if not result.secret_key:
            raise _ots_error("error.no_secret_key")
        if not result.metadata_key:
            raise _ots_error("error.no_metadata_key")
        # Nichts aus der Antwort loggen (siehe #17) – Keys und Metadaten sind sensibel.
        logger.info("share completed: secret_key=<redacted> meta_id=<redacted> state=<redacted>")
        return result

    def fetch_status(self, identifier: str) -> str:
        """Liefert den Zustand des *Secrets* (nicht des Receipts) über den Owner-Endpoint."""
        if not identifier:
            raise _ots_error("error.no_id")
        data = self._request("GET", f"{self._api_base()}/api/v2/receipt/{identifier}")
        return self._state_from_receipt(data)

    def share_link(self, identifier: str) -> str:
        """Holt den Empfänger-Link zum Receipt.

        Der Link wird bewusst nicht in der History gespeichert – er ist das
        Geheimnis selbst, und die History liegt im Klartext auf der Platte. Der
        Server kennt ihn, solange das Secret noch abrufbar ist."""
        if not identifier:
            raise _ots_error("error.no_id")
        data = self._request("GET", f"{self._api_base()}/api/v2/receipt/{identifier}")
        record = data.get("record") if isinstance(data.get("record"), dict) else {}

        # Der Server liefert share_path auch für ein verbranntes oder abgerufenes
        # Secret weiter. Der Zustand entscheidet, nicht das Vorhandensein des Pfads –
        # sonst landet ein toter Link in der Zwischenablage.
        if self._state_from_receipt(data) in self.TERMINAL_STATES:
            raise _ots_error("error.no_share_link")

        link = self._safe_share_url(_first_str(record.get("share_url")))
        if not link:
            path = _first_str(record.get("share_path")).lstrip("/")
            if path:
                link = f"{self._api_base()}/{path}"
        if not link:
            raise _ots_error("error.no_share_link")
        return link

    @staticmethod
    def _safe_share_url(url: str) -> str:
        """Der Link geht in die Zwischenablage – eine Serverantwort darf ihn nicht
        auf ein anderes Schema oder einen krummen Host umbiegen."""
        if not url:
            return ""
        parsed = urlparse(url)
        if parsed.scheme != "https" or not _is_valid_host(parsed.netloc):
            logger.warning("Ignoring malformed share_url from API response.")
            return ""
        return url

    def burn(self, identifier: str) -> str:
        """Vernichtet das Secret vor dem Abruf. Der Empfänger-Link wird sofort ungültig.

        `continue` ist im OpenAPI-Spec nur ein optionales Feld, in Wahrheit aber die
        Bestätigung, ohne die der Server den Burn nicht ausführt: er antwortet dann
        mit HTTP 200 und success=false, und das Secret bleibt abrufbar."""
        if not identifier:
            raise _ots_error("error.no_id")
        data = self._request(
            "POST", f"{self._api_base()}/api/v2/receipt/{identifier}/burn",
            json_body={"continue": "true"},
        )
        # Die Antwort trägt den Datensatz von *vor* dem Burn (state bleibt "new",
        # is_burned false); erst der nächste GET zeigt den neuen Zustand. Nachdem
        # `_request` success=false bereits abgefangen hat, ist hier verbrannt.
        state = self._state_from_receipt(data)
        return state if state in self.TERMINAL_STATES else "burned"

    def ping(self) -> ServiceInfo:
        """Erreichbarkeit über die auth-freien Endpoints, Credentials über /receipt/recent."""
        base = self._api_base()
        status_data = self._request("GET", f"{base}/api/v2/status", require_auth=False)
        version_data = self._request("GET", f"{base}/api/v2/version", require_auth=False)

        status = _first_str(status_data.get("status")) or "ok"
        version = self._format_version(version_data.get("version"))

        authenticated = False
        if self.has_credentials:
            self._request("GET", f"{base}/api/v2/receipt/recent")
            authenticated = True
        return ServiceInfo(status=status, version=version, authenticated=authenticated)

    # ---- Response-Mapping ----

    @staticmethod
    def _format_version(raw: object) -> str:
        """/api/v2/version liefert die Version als Liste (["0","25","11"]); je nach
        Deployment sind aber auch String oder Objekt möglich."""
        if isinstance(raw, (list, tuple)):
            return ".".join(str(part) for part in raw) or "?"
        if isinstance(raw, dict):
            return _first_str(raw.get("version"), raw.get("commit")) or "?"
        if isinstance(raw, str):
            return raw or "?"
        return str(raw) if raw is not None else "?"

    @classmethod
    def _state_from_receipt(cls, data: dict) -> str:
        """Receipt-Antworten führen den Secret-Zustand in `secret_state` bzw. in den
        is_*-Flags. `record.state` ist der Zustand des *Receipts* und läuft dem
        Secret voraus (z. B. "shared", während das Secret noch "new" ist) – daher
        nur als letzter Fallback."""
        record = data.get("record") if isinstance(data.get("record"), dict) else {}

        secret_state = _first_str(record.get("secret_state"))
        if secret_state:
            return secret_state

        for state, flag_key in cls._STATE_FLAGS:
            if _flag(record.get(flag_key)):
                return state

        return _first_str(record.get("state"), data.get("state")) or "unknown"

    @staticmethod
    def _share_result(data: dict) -> ShareResult:
        record = data.get("record") if isinstance(data.get("record"), dict) else {}
        secret_obj = record.get("secret") if isinstance(record.get("secret"), dict) else {}
        receipt_obj = record.get("receipt") if isinstance(record.get("receipt"), dict) else {}

        secret_key = _first_str(
            secret_obj.get("key"), secret_obj.get("identifier"),
            secret_obj.get("shortid"), data.get("secret_key"),
        )
        metadata_key = _first_str(
            receipt_obj.get("key"), receipt_obj.get("identifier"),
            receipt_obj.get("shortid"), data.get("metadata_key"),
        )
        metadata_identifier = _first_str(
            receipt_obj.get("identifier"), receipt_obj.get("key"),
            receipt_obj.get("shortid"), data.get("metadata_key"),
        )
        # Die Domain aus der Antwort gewinnt – bei Custom-Domain-Accounts weicht sie
        # vom API-Host ab, aus dem der Client sonst den Link basteln würde.
        share_domain = _first_str(record.get("share_domain"), receipt_obj.get("share_domain"))
        if share_domain and not _is_valid_host(share_domain):
            logger.warning("Ignoring malformed share_domain from API response.")
            share_domain = ""
        share_url = f"https://{share_domain}/secret/{secret_key}" if (share_domain and secret_key) else ""
        state = _first_str(secret_obj.get("state"), STATE_NEW) or STATE_NEW
        return ShareResult(
            secret_key=secret_key,
            metadata_key=metadata_key,
            metadata_identifier=metadata_identifier,
            state=state,
            share_domain=share_domain,
            share_url=share_url,
            receipt_shortid=_first_str(receipt_obj.get("shortid")),
        )


# ============================================================
# History
# ============================================================

def _write_private_text(path: Path, payload: str) -> None:
    """Schreibt eine Datei, die nur der aktuelle Benutzer lesen kann.

    settings.json und history.json enthalten Zugangsdaten bzw. Receipt-Identifier,
    mit denen sich Secrets verbrennen lassen. Unter POSIX entstünde ohne diesen
    Umweg eine 0644-Datei (umask), die jeder lokale Benutzer mitlesen kann; unter
    Windows regelt die ACL des Profilverzeichnisses den Zugriff."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(payload)
    if os.name != "nt":
        # Der Modus aus os.open greift nur bei Neuanlage – bestehende Dateien
        # aus älteren Versionen nachziehen.
        os.chmod(path, 0o600)


@dataclass
class HistoryEntry:
    created_at: str
    recipient: Optional[str]
    ttl_label: str
    ttl_seconds: int
    metadata_key: str
    metadata_identifier: str
    secret_preview: str
    last_state: str
    last_checked: str
    has_passphrase: bool = False

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @staticmethod
    def _int(value: object) -> int:
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0

    @classmethod
    def from_dict(cls, data: dict) -> HistoryEntry:
        return cls(
            created_at=str(data.get("created_at", "")),
            recipient=data.get("recipient") or None,
            ttl_label=str(data.get("ttl_label", "")),
            ttl_seconds=cls._int(data.get("ttl_seconds", 0)),
            metadata_key=str(data.get("metadata_key", "")),
            metadata_identifier=str(data.get("metadata_identifier", "")),
            secret_preview=str(data.get("secret_preview", "")),
            last_state=str(data.get("last_state", "")),
            last_checked=str(data.get("last_checked", "")),
            has_passphrase=_flag(data.get("has_passphrase")),
        )


class HistoryStore:
    MAX_ENTRIES = 200

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or self._default_path()
        self._entries: list[HistoryEntry] = []
        self._load()

    @staticmethod
    def _default_path() -> Path:
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", str(Path.home())))
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
        return base / "OneTimeSecret" / "history.json"

    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.exception("History-Datei korrupt – starte leer.")
            return
        if isinstance(data, list):
            self._entries = [HistoryEntry.from_dict(x) for x in data if isinstance(x, dict)]

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            _write_private_text(
                self.path,
                json.dumps([e.to_dict() for e in self._entries], indent=2, ensure_ascii=False),
            )
        except OSError:
            logger.exception("Konnte History nicht schreiben (%s).", self.path)

    def entries(self) -> list[HistoryEntry]:
        return list(self._entries)

    def add(self, entry: HistoryEntry) -> None:
        self._entries.insert(0, entry)
        if len(self._entries) > self.MAX_ENTRIES:
            self._entries = self._entries[: self.MAX_ENTRIES]
        self._save()

    def update_state(self, metadata_identifier: str, new_state: str) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        for entry in self._entries:
            if entry.metadata_identifier == metadata_identifier:
                entry.last_state = new_state
                entry.last_checked = now
        self._save()

    def remove(self, metadata_identifier: str) -> None:
        self._entries = [e for e in self._entries if e.metadata_identifier != metadata_identifier]
        self._save()

    def clear(self) -> None:
        self._entries = []
        self._save()


# ============================================================
# Settings
# ============================================================

# Optional: Windows Credential Manager via keyring. Wenn nicht installiert,
# fallen wir auf settings.json als Storage zurück (dann liegt der Key im Klartext).
try:
    import keyring  # type: ignore
    _KEYRING_AVAILABLE = True
except ImportError:  # pragma: no cover
    keyring = None  # type: ignore
    _KEYRING_AVAILABLE = False

KEYRING_SERVICE = "OneTimeSecret-Client"

# Wo der API-Key nach einem Speichern liegt. Die Oberfläche meldet das Ergebnis,
# statt aus "keyring importierbar" auf "sicher gespeichert" zu schließen.
KEY_STORAGE_KEYRING = "keyring"   # im Credential Manager (DPAPI)
KEY_STORAGE_FILE = "file"         # Klartext in settings.json – kein Keyring vorhanden
KEY_STORAGE_FAILED = "failed"     # Keyring vorhanden, Schreiben fehlgeschlagen: nicht gespeichert
KEY_STORAGE_NONE = "none"         # kein Key eingetragen


@dataclass
class Settings:
    api_url: str
    api_user: str
    api_key: str
    region: str
    language: str
    request_timeout: int
    default_ttl: str

    def to_dict_safe(self) -> dict:
        """Variante ohne api_key (für settings.json, wenn keyring verfügbar)."""
        d = self.__dict__.copy()
        d["api_key"] = ""
        return d

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @staticmethod
    def _timeout(value: object) -> int:
        """Eine von Hand editierte settings.json darf den Start nicht verhindern."""
        try:
            timeout = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return REQUEST_TIMEOUT_SECONDS
        return timeout if timeout > 0 else REQUEST_TIMEOUT_SECONDS

    @classmethod
    def from_dict(cls, data: dict) -> Settings:
        # `default_ttl_label` ist der Feldname vor der Umstellung auf TTL-Schlüssel.
        stored_ttl = data.get("default_ttl") or data.get("default_ttl_label") or DEFAULT_TTL_KEY
        return cls(
            api_url=str(data.get("api_url", "")),
            api_user=str(data.get("api_user", "")),
            api_key=str(data.get("api_key", "")),
            region=str(data.get("region", "") or detect_region_from_url(str(data.get("api_url", "")))),
            language=str(data.get("language", DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE),
            request_timeout=cls._timeout(data.get("request_timeout", REQUEST_TIMEOUT_SECONDS)),
            default_ttl=resolve_ttl_key(str(stored_ttl)),
        )

    @classmethod
    def defaults(cls) -> Settings:
        return cls(
            api_url=API_URL,
            api_user=API_USER,
            api_key=API_KEY,
            region=detect_region_from_url(API_URL),
            language=DEFAULT_LANGUAGE,
            request_timeout=REQUEST_TIMEOUT_SECONDS,
            default_ttl=DEFAULT_TTL_KEY,
        )


class SettingsStore:
    """Persistente Konfiguration. API-Key landet wenn möglich im Windows Credential
    Manager (keyring), restliche Felder in settings.json. Beim ersten Start werden
    die Hardcoded-Defaults aus dem Quelltext übernommen."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or self._default_path()
        self.keyring_available = _KEYRING_AVAILABLE
        self.last_key_storage: str = KEY_STORAGE_NONE
        self.current: Settings = self._load()

    @staticmethod
    def _default_path() -> Path:
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", str(Path.home())))
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
        return base / "OneTimeSecret" / "settings.json"

    def _read_key_from_keyring(self, user: str) -> str:
        if not (self.keyring_available and user):
            return ""
        try:
            return keyring.get_password(KEYRING_SERVICE, user) or ""  # type: ignore
        except Exception:
            logger.exception("Keyring read failed.")
            return ""

    def _write_key_to_keyring(self, user: str, key: str) -> bool:
        if not (self.keyring_available and user):
            return False
        try:
            keyring.set_password(KEYRING_SERVICE, user, key)  # type: ignore
            return True
        except Exception:
            logger.exception("Keyring write failed.")
            return False

    @staticmethod
    def _migrate(data: dict) -> dict:
        """Hebt eine settings.json vom Vorgängerformat an (ohne das Original zu ändern).

        `default_ttl_label` hielt das deutsche Label, `default_ttl` hält den Schlüssel.
        Fehlt `region`, wird sie aus der URL abgeleitet: sonst gewinnt beim Merge die
        Default-Region, und das nächste Speichern würde die URL auf deren Host
        zurücksetzen – der Nutzer verlöre seine Region, ohne sie angefasst zu haben."""
        patched = dict(data)
        if not patched.get("default_ttl") and patched.get("default_ttl_label"):
            patched["default_ttl"] = resolve_ttl_key(str(patched["default_ttl_label"]))
        if not patched.get("region") and patched.get("api_url"):
            patched["region"] = detect_region_from_url(str(patched["api_url"]))
        return patched

    def _load(self) -> Settings:
        defaults = Settings.defaults()
        merged = defaults.to_dict()

        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                data = self._migrate(data)
                merged.update({k: v for k, v in data.items() if v not in (None, "")})
        except (FileNotFoundError, OSError):
            # Settings file missing or unreadable -> fall back to defaults silently.
            pass
        except json.JSONDecodeError:
            logger.exception("Settings-Datei korrupt – verwende Defaults.")

        settings = Settings.from_dict(merged)

        # Falls keyring den Key kennt, hat das Vorrang vor allem im File / Default.
        keyring_key = self._read_key_from_keyring(settings.api_user)
        if keyring_key:
            settings.api_key = keyring_key

        return settings

    def _delete_key_from_keyring(self, user: str) -> None:
        if not (self.keyring_available and user):
            return
        try:
            keyring.delete_password(KEYRING_SERVICE, user)  # type: ignore
        except Exception:
            # Kein Eintrag vorhanden ist der Normalfall und kein Fehler.
            logger.debug("No keyring entry to delete for the previous user.", exc_info=True)

    def save(self, settings: Settings) -> str:
        """Speichert die Settings und meldet zurück, wo der API-Key gelandet ist.

        Der Key wird nur dann in settings.json geschrieben, wenn gar kein Keyring
        vorhanden ist – das ist der dokumentierte Klartext-Fallback für Läufe aus
        dem Quelltext. Schlägt dagegen ein *vorhandener* Keyring beim Schreiben
        fehl, wird der Key bewusst nirgends abgelegt: eine stille Herabstufung auf
        Klartext, während die Oberfläche DPAPI verspricht, wäre schlimmer als ein
        Key, den man nach dem Neustart erneut eingeben muss."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        previous_user = self.current.api_user

        if not (settings.api_user and settings.api_key):
            storage = KEY_STORAGE_NONE
        elif not self.keyring_available:
            storage = KEY_STORAGE_FILE
        elif self._write_key_to_keyring(settings.api_user, settings.api_key):
            storage = KEY_STORAGE_KEYRING
        else:
            storage = KEY_STORAGE_FAILED

        # Alten Eintrag räumen: nach einem Reset, einem geleerten Key-Feld oder
        # einem Benutzerwechsel bliebe sonst ein gültiges Credential zurück.
        keep = settings.api_user if storage == KEY_STORAGE_KEYRING else ""
        if previous_user and previous_user != keep:
            self._delete_key_from_keyring(previous_user)
        if settings.api_user and settings.api_user != keep:
            self._delete_key_from_keyring(settings.api_user)

        payload = settings.to_dict() if storage == KEY_STORAGE_FILE else settings.to_dict_safe()
        _write_private_text(self.path, json.dumps(payload, indent=2, ensure_ascii=False))

        self.current = settings
        self.last_key_storage = storage
        return storage

# ============================================================
# Ikonografie – die Symbolschrift von Windows
# ============================================================

# Tks Canvas zeichnet ohne Kantenglättung: von Hand gezogene Linien werden treppig
# und wirken neben geglätteter Schrift billig. Windows bringt sein eigenes
# Symbolsystem als Schriftart mit – dieselbe, aus der Terminal und Einstellungen
# ihre Symbole nehmen. Die Schriftmaschine glättet sie, die Strichstärke passt zur
# Textschrift, und es kostet keine zusätzliche Abhängigkeit.
ICON_FONTS: tuple[str, ...] = ("Segoe Fluent Icons", "Segoe MDL2 Assets")

ICON_GLYPHS: dict[str, str] = {
    "send":     "",
    "history":  "",
    "settings": "",
    "refresh":  "",
    "copy":     "",
    "burn":     "",
    "delete":   "",
    "remove":   "",
    "external": "",
    "link":     "",
    "eye":      "",
    "key":      "",
    "info":     "",
    "check":    "",
    "warning":  "",
    "error":    "",
    "close":    "",
}

_ICON_FONTS: dict[tuple[int, int], Optional[tkfont.Font]] = {}


def icon_font(widget: tk.Misc, size: int) -> Optional[tkfont.Font]:
    """Symbolschrift für diesen Interpreter, oder None auf Systemen ohne sie.

    Der Schlüssel enthält den Tk-Interpreter: Schriftobjekte gehören zu ihrem Root
    und überleben dessen Ende nicht."""
    key = (id(widget.tk), size)
    if key not in _ICON_FONTS:
        families = set(tkfont.families())
        family = next((name for name in ICON_FONTS if name in families), "")
        _ICON_FONTS[key] = tkfont.Font(family=family, size=size) if family else None
    return _ICON_FONTS[key]


def has_icons(widget: tk.Misc) -> bool:
    return icon_font(widget, 12) is not None


def draw_icon(canvas: tk.Canvas, name: str, cx: float, cy: float,
              size: float, color: str) -> bool:
    """Setzt ein Symbol mittig auf (cx, cy). Fehlt die Schrift, bleibt der Platz
    leer und der Aufrufer zeigt nur den Text."""
    glyph = ICON_GLYPHS.get(name)
    font = icon_font(canvas, max(8, int(size * 0.75)))
    if not glyph or font is None:
        return False
    canvas.create_text(cx, cy, text=glyph, font=font, fill=color, anchor="center")
    return True


# ============================================================
# Steuerelemente – auf Canvas gezeichnet, alle Zustände
# ============================================================

class Button(tk.Canvas):
    """Fluent-Knopf: gezeichnet statt gerahmt, damit die Ecken rund sein können.

    Varianten: `accent` (eine primäre Aktion je Ansicht), `standard` (Umriss),
    `subtle` (nur Text). Führt Ruhe, Zeiger, Fokus, gedrückt, deaktiviert und
    arbeitend."""

    HEIGHT = 32
    PAD_X = 14
    ICON_GAP = 8
    RING = 2

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
        *,
        variant: str = "standard",
        icon: str = "",
        font_obj: Optional[tkfont.Font] = None,
        min_width: int = 0,
        height: int = HEIGHT,
        icon_only: bool = False,
    ) -> None:
        self._bg = parent["bg"]
        self._font = font_obj or tkfont.nametofont("TkDefaultFont")
        self._text = text
        self._icon = icon
        self._icon_only = icon_only
        self._variant = variant
        self._command = command
        self._height = height
        self._min_width = min_width
        self._state = "rest"
        self._enabled = True
        self._focused = False

        super().__init__(
            parent, bg=self._bg, highlightthickness=0, bd=0,
            height=height + self.RING * 2, cursor="hand2", takefocus=1,
        )
        self.configure(width=self._measure())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<FocusIn>", self._on_focus_in)
        self.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Return>", self._on_key)
        self.bind("<space>", self._on_key)
        self._render()

    # ---- Maße ----

    def _shows_icon(self) -> bool:
        """Ohne die Symbolschrift des Systems zeigt der Knopf nur seinen Text –
        und reserviert dann auch keinen Platz für ein Symbol."""
        return bool(self._icon) and has_icons(self)

    def _measure(self) -> int:
        if self._icon_only:
            return self._height + self.RING * 2
        width = self._font.measure(self._text) + self.PAD_X * 2
        if self._shows_icon():
            width += 16 + self.ICON_GAP
        return max(width, self._min_width) + self.RING * 2

    # ---- Zustandswechsel ----

    def set_text(self, text: str) -> None:
        self._text = text
        self.configure(width=self._measure())
        self._render()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.configure(cursor="hand2" if enabled else "arrow", takefocus=1 if enabled else 0)
        self._state = "rest"
        self._render()

    def _on_enter(self, _e: tk.Event) -> None:
        if self._enabled:
            self._state = "hover"
            self._render()

    def _on_leave(self, _e: tk.Event) -> None:
        self._state = "rest"
        self._render()

    def _on_press(self, _e: tk.Event) -> None:
        if not self._enabled:
            return
        self.focus_set()
        self._state = "press"
        self._render()

    def _on_release(self, event: tk.Event) -> None:
        if not self._enabled:
            return
        inside = 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height()
        self._state = "hover" if inside else "rest"
        self._render()
        if inside:
            self._command()

    def _on_key(self, _e: tk.Event) -> str:
        if self._enabled:
            self._command()
        return "break"

    def _on_focus_in(self, _e: tk.Event) -> None:
        self._focused = True
        self._render()

    def _on_focus_out(self, _e: tk.Event) -> None:
        self._focused = False
        self._render()

    # ---- Darstellung ----

    def _colors(self) -> tuple[str, str, str]:
        """(Fläche, Rand, Text) für den aktuellen Zustand."""
        if not self._enabled:
            disabled = control_fill(self._bg)
            return disabled, disabled, Theme.TEXT_DISABLED
        if self._variant == "accent":
            fill = {"rest": Theme.ACCENT, "hover": Theme.ACCENT_HOVER,
                    "press": Theme.ACCENT_PRESS}[self._state]
            return fill, fill, Theme.ON_ACCENT
        if self._variant == "subtle":
            fill = {"rest": self._bg, "hover": Theme.BG_CARD_HOVER,
                    "press": Theme.BG_CARD_PRESS}[self._state]
            return fill, fill, Theme.TEXT
        rest = control_fill(self._bg)
        fill = {"rest": rest, "hover": Theme.BG_CARD_HOVER,
                "press": Theme.BG_CARD_PRESS}[self._state]
        stroke = Theme.STROKE_HOVER if self._state == "hover" else fill
        return fill, stroke, Theme.TEXT

    def _render(self) -> None:
        self.delete("all")
        fill, stroke, text_color = self._colors()
        width = int(self["width"])
        r = self.RING
        x2, y2 = width - r, self._height + r

        if self._focused and self._enabled:
            draw_round_rect(self, 1, 1, width - 1, self._height + r * 2 - 1,
                            Theme.RADIUS + 2, fill="", outline=Theme.FOCUS_RING, width=2)
        draw_round_rect(self, r, r, x2, y2, Theme.RADIUS, fill=fill, outline=stroke)

        cy = (r + y2) / 2
        if self._icon_only:
            if not draw_icon(self, self._icon, (r + x2) / 2, cy, 18, text_color):
                self.create_text((r + x2) / 2, cy, text=self._text or "…",
                                 fill=text_color, font=self._font, anchor="center")
            return
        if self._shows_icon():
            total = 16 + self.ICON_GAP + self._font.measure(self._text)
            start = (r + x2) / 2 - total / 2
            draw_icon(self, self._icon, start + 8, cy, 16, text_color)
            self.create_text(start + 16 + self.ICON_GAP, cy, text=self._text,
                             fill=text_color, font=self._font, anchor="w")
        else:
            self.create_text((r + x2) / 2, cy, text=self._text, fill=text_color,
                             font=self._font, anchor="center")


class Field(tk.Canvas):
    """Fluent-Eingabefeld: gezeichneter Rahmen, unter der Schreibmarke bekommt die
    Unterkante die Akzentfarbe."""

    HEIGHT = 32

    def __init__(
        self,
        parent: tk.Misc,
        *,
        textvariable: Optional[tk.StringVar] = None,
        font_obj: Optional[tkfont.Font] = None,
        show: str = "",
        readonly: bool = False,
        height: int = HEIGHT,
        placeholder: str = "",
    ) -> None:
        self._bg = parent["bg"]
        self._fill = well_fill(self._bg)
        self._height = height
        self._focused = False
        self._hovered = False
        super().__init__(parent, bg=self._bg, highlightthickness=0, bd=0, height=height)

        self.entry = tk.Entry(
            self, textvariable=textvariable, font=font_obj,
            bg=self._fill, fg=Theme.TEXT, insertbackground=Theme.ACCENT,
            relief="flat", bd=0, highlightthickness=0,
            selectbackground=Theme.ACCENT_MUTED, selectforeground=Theme.TEXT,
            show=show, readonlybackground=self._fill,
            disabledbackground=Theme.BG_CARD, disabledforeground=Theme.TEXT_DISABLED,
        )
        if readonly:
            self.entry.configure(state="readonly")
        self._placeholder = placeholder
        self._window = self.create_window(12, height / 2, window=self.entry,
                                          anchor="w", height=height - 10)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Configure>", lambda _e: self._render())
        self.bind("<Button-1>", lambda _e: self.entry.focus_set())

    def _stroke(self) -> str:
        """Ruhend fast unsichtbar – der Rand meldet sich erst, wenn man hinzeigt."""
        if self._focused:
            return Theme.STROKE_STRONG
        return Theme.STROKE_HOVER if self._hovered else self._fill

    def _set_hover(self, hovered: bool) -> None:
        self._hovered = hovered
        self._render()

    def _on_focus_in(self, _e: tk.Event) -> None:
        self._focused = True
        self.entry.configure(bg=Theme.BG_INPUT_FOCUS)
        self._render()

    def _on_focus_out(self, _e: tk.Event) -> None:
        self._focused = False
        self.entry.configure(bg=self._fill)
        self._render()

    def _render(self) -> None:
        self.delete("frame")
        width = self.winfo_width()
        if width <= 1:
            return
        fill = Theme.BG_INPUT_FOCUS if self._focused else self._fill
        stroke = self._stroke()
        draw_round_rect(self, 1, 1, width - 1, self._height - 1, Theme.RADIUS,
                        fill=fill, outline=stroke, tags="frame")
        if self._focused:
            # Fluents Kennzeichen für das aktive Feld: 2px Akzent an der Unterkante.
            self.create_line(1 + Theme.RADIUS, self._height - 2, width - 1 - Theme.RADIUS,
                             self._height - 2, fill=Theme.ACCENT, width=2, tags="frame")
        self.itemconfigure(self._window, width=width - 24)
        self.tag_lower("frame")


class TextArea(tk.Canvas):
    """Mehrzeiliges Eingabefeld mit demselben Rahmenverhalten wie `Field`."""

    def __init__(self, parent: tk.Misc, *, font_obj: Optional[tkfont.Font] = None,
                 height: int = 160) -> None:
        self._bg = parent["bg"]
        self._fill = well_fill(self._bg)
        self._height = height  # angeforderte Mindesthöhe; gezeichnet wird die echte
        self._focused = False
        self._hovered = False
        super().__init__(parent, bg=self._bg, highlightthickness=0, bd=0, height=height)

        self.text = tk.Text(
            self, font=font_obj, bg=self._fill, fg=Theme.TEXT,
            insertbackground=Theme.ACCENT, relief="flat", bd=0, highlightthickness=0,
            selectbackground=Theme.ACCENT_MUTED, selectforeground=Theme.TEXT,
            wrap="word", undo=True, padx=0, pady=0,
        )
        self._window = self.create_window(12, 10, window=self.text, anchor="nw")
        self.text.bind("<FocusIn>", self._on_focus_in)
        self.text.bind("<FocusOut>", self._on_focus_out)
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Configure>", lambda _e: self._render())

    def _stroke(self) -> str:
        if self._focused:
            return Theme.STROKE_STRONG
        return Theme.STROKE_HOVER if self._hovered else self._fill

    def _set_hover(self, hovered: bool) -> None:
        self._hovered = hovered
        self._render()

    def _on_focus_in(self, _e: tk.Event) -> None:
        self._focused = True
        self.text.configure(bg=Theme.BG_INPUT_FOCUS)
        self._render()

    def _on_focus_out(self, _e: tk.Event) -> None:
        self._focused = False
        self.text.configure(bg=self._fill)
        self._render()

    def _render(self) -> None:
        self.delete("frame")
        width, height = self.winfo_width(), self.winfo_height()
        if width <= 1 or height <= 1:
            return
        fill = Theme.BG_INPUT_FOCUS if self._focused else self._fill
        stroke = self._stroke()
        draw_round_rect(self, 1, 1, width - 1, height - 1, Theme.RADIUS,
                        fill=fill, outline=stroke, tags="frame")
        if self._focused:
            self.create_line(1 + Theme.RADIUS, height - 2, width - 1 - Theme.RADIUS,
                             height - 2, fill=Theme.ACCENT, width=2, tags="frame")
        self.itemconfigure(self._window, width=width - 24, height=height - 20)
        self.tag_lower("frame")


class ChoiceGroup(tk.Canvas):
    """Auswahlgruppe aus gleich gebauten Kacheln – für Gültigkeit, Region, Sprache.

    Eine Kachel trägt die Akzentfläche, alle anderen die Kartenfläche; die Auswahl
    ist damit ohne Farbsehen erkennbar, weil sie zusätzlich den Textkontrast dreht."""

    TILE_HEIGHT = 32
    GAP = 6

    def __init__(
        self,
        parent: tk.Misc,
        options: list[tuple[str, str]],
        value: str,
        on_change: Callable[[str], None],
        *,
        font_obj: Optional[tkfont.Font] = None,
        columns: int = 5,
    ) -> None:
        self._bg = parent["bg"]
        self._font = font_obj or tkfont.nametofont("TkDefaultFont")
        self._items = options
        self._value = value
        self._on_change = on_change
        self._columns = columns
        self._hover: Optional[str] = None
        self._focus_index = max(0, [k for k, _ in options].index(value) if any(
            k == value for k, _ in options) else 0)
        self._focused = False
        self._boxes: dict[str, tuple[float, float, float, float]] = {}

        rows = math.ceil(len(options) / columns)
        height = rows * self.TILE_HEIGHT + (rows - 1) * self.GAP
        super().__init__(parent, bg=self._bg, highlightthickness=0, bd=0,
                         height=height, takefocus=1)
        self.bind("<Configure>", lambda _e: self._render())
        self.bind("<Motion>", self._on_motion)
        self.bind("<Leave>", lambda _e: self._set_hover(None))
        self.bind("<Button-1>", self._on_click)
        self.bind("<FocusIn>", lambda _e: self._set_focused(True))
        self.bind("<FocusOut>", lambda _e: self._set_focused(False))
        self.bind("<Left>", lambda _e: self._step(-1))
        self.bind("<Right>", lambda _e: self._step(1))
        self.bind("<Return>", lambda _e: self._activate())
        self.bind("<space>", lambda _e: self._activate())

    @property
    def value(self) -> str:
        return self._value

    def set_value(self, value: str) -> None:
        self._value = value
        self._render()

    def _set_hover(self, key: Optional[str]) -> None:
        if key != self._hover:
            self._hover = key
            self._render()

    def _set_focused(self, focused: bool) -> None:
        self._focused = focused
        self._render()

    def _hit(self, x: float, y: float) -> Optional[str]:
        for key, (x1, y1, x2, y2) in self._boxes.items():
            if x1 <= x <= x2 and y1 <= y <= y2:
                return key
        return None

    def _on_motion(self, event: tk.Event) -> None:
        self._set_hover(self._hit(event.x, event.y))

    def _on_click(self, event: tk.Event) -> None:
        self.focus_set()
        key = self._hit(event.x, event.y)
        if key and key != self._value:
            self._value = key
            self._focus_index = [k for k, _ in self._items].index(key)
            self._render()
            self._on_change(key)

    def _step(self, delta: int) -> str:
        self._focus_index = (self._focus_index + delta) % len(self._items)
        self._render()
        return "break"

    def _activate(self) -> str:
        key = self._items[self._focus_index][0]
        if key != self._value:
            self._value = key
            self._render()
            self._on_change(key)
        return "break"

    def _render(self) -> None:
        self.delete("all")
        self._boxes.clear()
        width = self.winfo_width()
        if width <= 1:
            return
        columns = self._columns
        tile_w = (width - (columns - 1) * self.GAP) / columns
        for index, (key, label) in enumerate(self._items):
            row, col = divmod(index, columns)
            x1 = col * (tile_w + self.GAP)
            y1 = row * (self.TILE_HEIGHT + self.GAP)
            x2, y2 = x1 + tile_w, y1 + self.TILE_HEIGHT
            self._boxes[key] = (x1, y1, x2, y2)

            selected = key == self._value
            if selected:
                fill, stroke, fg = Theme.ACCENT, Theme.ACCENT, Theme.ON_ACCENT
            elif self._hover == key:
                fill, stroke, fg = Theme.BG_CARD_HOVER, Theme.STROKE_HOVER, Theme.TEXT
            else:
                # Die Fläche unterscheidet die Kachel schon vom Grund; ein Umriss
                # obendrauf macht aus einer Auswahl ein Gitter.
                rest = control_fill(self._bg)
                fill, stroke, fg = rest, rest, Theme.TEXT_SECONDARY
            draw_round_rect(self, x1 + 1, y1 + 1, x2 - 1, y2 - 1, Theme.RADIUS,
                            fill=fill, outline=stroke)
            if self._focused and index == self._focus_index:
                draw_round_rect(self, x1 + 1, y1 + 1, x2 - 1, y2 - 1, Theme.RADIUS,
                                fill="", outline=Theme.FOCUS_RING, width=2)
            self.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=label, fill=fg,
                             font=self._font, anchor="center")


class NavItem(tk.Canvas):
    """Eintrag der Navigationsspalte, 40 px hoch, mit Akzentbalken bei Auswahl."""

    HEIGHT = 40

    def __init__(self, parent: tk.Misc, text: str, icon: str,
                 command: Callable[[], None], *,
                 font_obj: Optional[tkfont.Font] = None) -> None:
        self._bg = parent["bg"]
        self._font = font_obj or tkfont.nametofont("TkDefaultFont")
        self._text = text
        self._icon = icon
        self._command = command
        self._active = False
        self._hover = False
        self._focused = False
        super().__init__(parent, bg=self._bg, highlightthickness=0, bd=0,
                         height=self.HEIGHT, cursor="hand2", takefocus=1)
        self.bind("<Configure>", lambda _e: self._render())
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<Button-1>", lambda _e: (self.focus_set(), self._command()))
        self.bind("<Return>", lambda _e: self._command())
        self.bind("<space>", lambda _e: self._command())
        self.bind("<FocusIn>", lambda _e: self._set_focused(True))
        self.bind("<FocusOut>", lambda _e: self._set_focused(False))

    def set_active(self, active: bool) -> None:
        self._active = active
        self._render()

    def _set_hover(self, hover: bool) -> None:
        self._hover = hover
        self._render()

    def _set_focused(self, focused: bool) -> None:
        self._focused = focused
        self._render()

    def _render(self) -> None:
        self.delete("all")
        width = self.winfo_width()
        if width <= 1:
            return
        if self._active:
            fill, fg = Theme.BG_CARD, Theme.TEXT
        elif self._hover:
            fill, fg = Theme.BG_CARD_HOVER, Theme.TEXT
        else:
            fill, fg = self._bg, Theme.TEXT_SECONDARY
        draw_round_rect(self, 2, 2, width - 2, self.HEIGHT - 2, Theme.RADIUS, fill=fill,
                        outline=fill)
        if self._active:
            self.create_line(4, 12, 4, self.HEIGHT - 12, fill=Theme.ACCENT, width=3,
                             capstyle="round")
        if self._focused:
            draw_round_rect(self, 2, 2, width - 2, self.HEIGHT - 2, Theme.RADIUS,
                            fill="", outline=Theme.FOCUS_RING, width=2)
        drawn = draw_icon(self, self._icon, 26, self.HEIGHT / 2, 18, fg)
        self.create_text(46 if drawn else 20, self.HEIGHT / 2, text=self._text,
                         fill=fg, font=self._font, anchor="w")


class InfoBar(tk.Frame):
    """Fluents Meldungsleiste: bleibt stehen, bis sie beantwortet oder ersetzt wird.

    Ersetzt die frühere schwebende Sprechblase – die verschwand nach ein paar
    Sekunden, auch wenn die Meldung ein Fehler war, den jemand lesen musste."""

    SEVERITIES: ClassVar[dict[str, tuple[str, str]]] = {
        "info":    (Theme.ACCENT, "info"),
        "success": (Theme.SUCCESS, "check"),
        "warning": (Theme.CAUTION, "warning"),
        "error":   (Theme.DANGER, "error"),
    }

    def __init__(self, parent: tk.Misc, *, font_obj: Optional[tkfont.Font] = None,
                 on_close: Optional[Callable[[], None]] = None) -> None:
        super().__init__(parent, bg=Theme.BG_CARD, highlightthickness=1,
                         highlightbackground=Theme.STROKE)
        self._font = font_obj or tkfont.nametofont("TkDefaultFont")
        self._on_close = on_close

        self._accent = tk.Frame(self, bg=Theme.ACCENT, width=3)
        self._accent.pack(side="left", fill="y")

        self._icon = tk.Canvas(self, bg=Theme.BG_CARD, width=20, height=20,
                               highlightthickness=0, bd=0)
        self._icon.pack(side="left", padx=(12, 0), pady=12)

        self._label = tk.Label(self, text="", bg=Theme.BG_CARD, fg=Theme.TEXT,
                               font=self._font, justify="left", anchor="w",
                               wraplength=520)
        self._label.pack(side="left", fill="x", expand=True, padx=(10, 10), pady=10)

        self._close = Button(self, "", self._dismiss, variant="subtle", icon="close",
                             icon_only=True, height=28)
        self._close.pack(side="right", padx=(0, 8))

    def show(self, message: str, severity: str = "info") -> None:
        color, icon = self.SEVERITIES.get(severity, self.SEVERITIES["info"])
        self._accent.configure(bg=color)
        self._icon.delete("all")
        draw_icon(self._icon, icon, 10, 10, 16, color)
        self._label.configure(text=message)

    def _dismiss(self) -> None:
        if self._on_close:
            self._on_close()


class ThinScrollbar(tk.Canvas):
    """Schmale Bildlaufleiste ohne Pfeile, wie in Fluent."""

    WIDTH = 12
    THUMB = 4
    THUMB_HOVER = 6
    MIN_THUMB = 32

    def __init__(self, parent: tk.Misc, command: Callable[..., None]) -> None:
        super().__init__(parent, bg=parent["bg"], width=self.WIDTH,
                         highlightthickness=0, bd=0)
        self._command = command
        self._first = 0.0
        self._last = 1.0
        self._hover = False
        self._drag_origin: Optional[float] = None
        self.bind("<Configure>", lambda _e: self._render())
        self.bind("<Enter>", lambda _e: self._set_hover(True))
        self.bind("<Leave>", lambda _e: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", lambda _e: setattr(self, "_drag_origin", None))

    def set(self, first: str, last: str) -> None:
        self._first, self._last = float(first), float(last)
        self._render()

    def _set_hover(self, hover: bool) -> None:
        self._hover = hover
        self._render()

    def _thumb_bounds(self) -> tuple[float, float]:
        height = self.winfo_height()
        top = self._first * height
        bottom = self._last * height
        if bottom - top < self.MIN_THUMB:
            bottom = min(height, top + self.MIN_THUMB)
            top = bottom - self.MIN_THUMB
        return top, bottom

    def _render(self) -> None:
        self.delete("all")
        if self._first <= 0.0 and self._last >= 1.0:
            return
        top, bottom = self._thumb_bounds()
        width = self.THUMB_HOVER if self._hover else self.THUMB
        x = (self.WIDTH - width) / 2
        draw_round_rect(self, x, top + 2, x + width, bottom - 2, width / 2,
                        fill=Theme.STROKE_HOVER if self._hover else Theme.STROKE_STRONG,
                        outline="")

    def _on_press(self, event: tk.Event) -> None:
        top, bottom = self._thumb_bounds()
        if top <= event.y <= bottom:
            self._drag_origin = event.y - top
            return
        fraction = max(0.0, min(1.0, event.y / max(1, self.winfo_height())))
        self._command("moveto", fraction - (self._last - self._first) / 2)

    def _on_drag(self, event: tk.Event) -> None:
        if self._drag_origin is None:
            return
        height = max(1, self.winfo_height())
        fraction = max(0.0, min(1.0, (event.y - self._drag_origin) / height))
        self._command("moveto", fraction)


# ============================================================
# App
# ============================================================

class App(tk.Tk):
    """Fenster und Ablauf.

    RICHTUNG: Die Designsprache von Windows selbst, voll ausgeführt – kein Zitat
    und keine eigene Bildsprache. Wer die App neben den Windows-Einstellungen
    öffnet, soll keinen Bruch bemerken. Was sie dafür ablegt: die Augenbrauen über
    den Überschriften, die schwebende Sprechblase, Unicode-Zeichen als Symbole und
    den Cyan-auf-Navy-Anstrich.
    EIGENE WELT: Fluent-Dunkelebenen (#202020/#272727/#2B2B2B) mit einem einzigen
    Akzent (#60CDFF), der nur Primäraktion, Auswahl und Zustand trägt; Segoe UI
    Variable in fester Rampe, Cascadia Mono ausschließlich für Maschinenwerte;
    Steuerelemente auf Canvas gezeichnet, damit die Ecken rund und die Fokusringe
    echt sind.
    ABLAUF: Fenster auf, Nachricht tippen, Link liegt in der Zwischenablage. Alles
    andere – Verlauf, Zustand, Verbrennen, Einstellungen – ordnet sich diesem Weg
    unter.
    ERSTE ANSICHT: Navigationsspalte links (208 px), rechts eine Spalte von höchstens
    640 px: Überschrift, Empfänger, Nachricht, Gültigkeit, Passphrase, darunter
    rechtsbündig die einzige Akzentfläche der Ansicht.
    FORM: Kategorie-Standard, bewusst gewählt (stehende Alternative des
    Richtungswurfs), Qualitätsmaßstab Windows Terminal und Einstellungen.
    """

    NAV_WIDTH = 208
    CONTENT_MAX = 640

    def __init__(self) -> None:
        super().__init__()
        self.title("OneTimeSecret Client")
        # Höher als das Formular braucht: so bleibt Luft, wenn unten eine Meldung
        # einblendet, und der Verlauf zeigt mehr als drei Einträge.
        self.geometry("1060x860")
        self.minsize(920, 640)
        self.configure(bg=Theme.BG_BASE)
        self._apply_window_icon()

        self.settings_store = SettingsStore()
        self.history = HistoryStore()

        self._current_section = "send"
        self._send_view = "form"
        self._last_metadata_identifier = ""
        self._message_job: Optional[str] = None

        self._nav_items: dict[str, NavItem] = {}
        self._sections: dict[str, tk.Frame] = {}
        self._send_views: dict[str, tk.Frame] = {}
        self._nav_frame: Optional[tk.Frame] = None
        self._content_frame: Optional[tk.Frame] = None

        self._apply_settings(self.settings_store.current)
        self._setup_fonts()
        self._build_ui()
        self._bind_shortcuts()
        self._center_window()

    # ---- Fenster ----

    def _apply_window_icon(self) -> None:
        if not ICON_PATH.exists():
            logger.debug("App icon not found at %s; using Tk default", ICON_PATH)
            return
        try:
            self.iconbitmap(default=str(ICON_PATH))
        except tk.TclError as exc:
            logger.debug("Could not apply window icon: %s", exc)

    def _center_window(self) -> None:
        self.update_idletasks()
        width, height = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - width) // 2
        y = max(0, (self.winfo_screenheight() - height) // 2 - 30)
        self.geometry(f"+{x}+{y}")

    def _bind_shortcuts(self) -> None:
        self.bind("<Control-Return>", lambda _e: self._submit())
        self.bind("<Escape>", lambda _e: self._reset_to_form())
        self.bind("<Control-l>", lambda _e: self._copy_link())

    # ---- Einstellungen ----

    def _apply_settings(self, settings: Settings) -> None:
        self.settings = settings
        known_languages = {code for code, _label in LANGUAGES}
        self.lang = settings.language if settings.language in known_languages else DEFAULT_LANGUAGE
        self.api_host = urlparse(settings.api_url).hostname or "onetimesecret.com"
        self.link_base = f"https://{self.api_host}/secret"
        # /private/<id> ist die v1-Adresse und antwortet auf v2-Servern mit 404.
        self.metadata_base = f"https://{self.api_host}/receipt"

        # __dict__ statt getattr: tk.Tk bringt selbst eine Methode `client` mit,
        # die getattr sonst als "vorheriger Client" zurückgibt.
        previous = self.__dict__.get("client")
        if isinstance(previous, OTSClient):
            previous.close()

        self.client = OTSClient(
            settings.api_url, settings.api_user, settings.api_key,
            share_domain=self.api_host,
            timeout=settings.request_timeout,
        )

    def t(self, key: str, **fmt: object) -> str:
        return t(key, self.lang, **fmt)

    def _error_text(self, exc: OTSError) -> str:
        """Der API-Layer liefert die Meldung als Schlüssel plus (unübersetztem)
        Serverdetail – gerendert wird sie erst hier, in der eingestellten Sprache."""
        return exc.localized(self.lang)

    # ---- Schrift ----

    def _setup_fonts(self) -> None:
        families = set(tkfont.families())

        def pick(*candidates: str) -> str:
            for name in candidates:
                if name in families:
                    return name
            return candidates[-1]

        ui = pick("Segoe UI Variable Text", "Segoe UI", "Selawik", "Helvetica")
        display = pick("Segoe UI Variable Display", "Segoe UI Variable Text", "Segoe UI", "Helvetica")
        mono = pick("Cascadia Mono", "Consolas", "Courier New")

        # Fluents Rampe: feste Größen, Schrittweite ~1.2 – kein fließendes Skalieren.
        self.f_title = tkfont.Font(family=display, size=20, weight="bold")
        self.f_subtitle = tkfont.Font(family=ui, size=13, weight="bold")
        self.f_body_strong = tkfont.Font(family=ui, size=10, weight="bold")
        self.f_body = tkfont.Font(family=ui, size=10)
        self.f_caption = tkfont.Font(family=ui, size=9)
        self.f_mono = tkfont.Font(family=mono, size=10)
        self.f_mono_small = tkfont.Font(family=mono, size=9)

    # ---- Gerüst ----

    def _build_ui(self) -> None:
        self._nav_frame = self._build_nav()
        self._nav_frame.pack(side="left", fill="y")
        self._nav_frame.pack_propagate(False)

        self._content_frame = tk.Frame(self, bg=Theme.BG_LAYER)
        self._content_frame.pack(side="left", fill="both", expand=True)

        body = tk.Frame(self._content_frame, bg=Theme.BG_LAYER)
        body.pack(fill="both", expand=True)
        self._body = body

        self._sections["send"] = self._build_send_section(body)
        self._sections["history"] = self._build_history_section(body)
        self._sections["settings"] = self._build_settings_section(body)

        self._build_message_bar()
        self._show_section(self._current_section)

    def _build_nav(self) -> tk.Frame:
        nav = tk.Frame(self, bg=Theme.BG_BASE, width=self.NAV_WIDTH)

        header = tk.Frame(nav, bg=Theme.BG_BASE)
        header.pack(fill="x", padx=16, pady=(20, 18))
        mark = tk.Canvas(header, bg=Theme.BG_BASE, width=20, height=20,
                         highlightthickness=0, bd=0)
        mark.pack(side="left")
        mark.create_polygon(10, 2, 18, 10, 10, 18, 2, 10, fill=Theme.ACCENT, outline="")
        tk.Label(header, text="OneTimeSecret", bg=Theme.BG_BASE, fg=Theme.TEXT,
                 font=self.f_body_strong).pack(side="left", padx=(10, 0))

        for name, icon in (("send", "send"), ("history", "history"), ("settings", "settings")):
            item = NavItem(nav, self.t(f"nav.{name}"), icon,
                           lambda n=name: self._show_section(n), font_obj=self.f_body)
            item.pack(fill="x", padx=8, pady=1)
            self._nav_items[name] = item

        footer = tk.Frame(nav, bg=Theme.BG_BASE)
        footer.pack(side="bottom", fill="x", padx=20, pady=18)
        account = self.settings.api_user or self.t("nav.no_account")
        tk.Label(footer, text=_truncate(account, 26), bg=Theme.BG_BASE,
                 fg=Theme.TEXT_SECONDARY, font=self.f_caption, anchor="w").pack(fill="x")
        tk.Label(footer, text=f"{_region_label(self.api_host)} · {self.api_host}",
                 bg=Theme.BG_BASE, fg=Theme.TEXT_TERTIARY, font=self.f_caption,
                 anchor="w").pack(fill="x", pady=(2, 0))
        return nav

    def _show_section(self, name: str) -> None:
        self._current_section = name
        for section_name, frame in self._sections.items():
            frame.pack_forget()
            if section_name in self._nav_items:
                self._nav_items[section_name].set_active(section_name == name)
        self._sections[name].pack(fill="both", expand=True)
        if name == "history":
            self._render_history()

    # ---- Bausteine ----

    def _page(self, parent: tk.Misc, title: str, subtitle: str = "") -> tuple[tk.Frame, tk.Frame]:
        """Seitengerüst: Überschrift ohne Augenbraue, darunter der Inhalt."""
        page = tk.Frame(parent, bg=Theme.BG_LAYER)
        head = tk.Frame(page, bg=Theme.BG_LAYER)
        head.pack(fill="x", padx=40, pady=(32, 0))
        tk.Label(head, text=title, bg=Theme.BG_LAYER, fg=Theme.TEXT,
                 font=self.f_title, anchor="w").pack(fill="x")
        if subtitle:
            tk.Label(head, text=subtitle, bg=Theme.BG_LAYER, fg=Theme.TEXT_SECONDARY,
                     font=self.f_body, anchor="w", justify="left").pack(fill="x", pady=(6, 0))
        return page, head

    def _label(self, parent: tk.Misc, text: str, *, hint: str = "") -> tk.Frame:
        wrap = tk.Frame(parent, bg=parent["bg"])
        line = tk.Frame(wrap, bg=parent["bg"])
        line.pack(fill="x")
        tk.Label(line, text=text, bg=parent["bg"], fg=Theme.TEXT,
                 font=self.f_body, anchor="w").pack(side="left")
        if hint:
            tk.Label(line, text=hint, bg=parent["bg"], fg=Theme.TEXT_TERTIARY,
                     font=self.f_caption, anchor="w").pack(side="left", padx=(8, 0))
        return wrap

    def _capped_column(self, parent: tk.Frame, max_width: int = 0) -> tk.Frame:
        """Inhaltsspalte mit gedeckelter Breite – Formulare bleiben lesbar, auch
        wenn das Fenster breit gezogen wird."""
        limit = max_width or self.CONTENT_MAX
        column = tk.Frame(parent, bg=parent["bg"])
        column.pack(fill="x", anchor="w")

        def _cap(_e: Optional[tk.Event] = None) -> None:
            column.pack_configure(padx=(0, max(0, parent.winfo_width() - limit)))

        parent.bind("<Configure>", _cap, add="+")
        _cap()
        return column

    def _scrollable(self, parent: tk.Misc) -> tk.Frame:
        canvas = tk.Canvas(parent, bg=Theme.BG_LAYER, highlightthickness=0, bd=0)
        bar = ThinScrollbar(parent, canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y", padx=(0, 4), pady=8)
        canvas.pack(side="left", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=Theme.BG_LAYER)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync(_e: Optional[tk.Event] = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(window, width=canvas.winfo_width())

        inner.bind("<Configure>", _sync)
        canvas.bind("<Configure>", _sync)
        canvas.bind("<Enter>", lambda _e: canvas.bind_all(
            "<MouseWheel>", lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units")))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))
        return inner

    # ---- Senden ----

    def _build_send_section(self, parent: tk.Misc) -> tk.Frame:
        section = tk.Frame(parent, bg=Theme.BG_LAYER)
        self._send_views["form"] = self._build_form_view(section)
        self._send_views["result"] = self._build_result_view(section)
        self._send_views[self._send_view].pack(fill="both", expand=True)
        return section

    def _build_form_view(self, parent: tk.Misc) -> tk.Frame:
        page, _head = self._page(parent, self.t("send.title"), self.t("send.subtitle"))

        # Aktionszeile zuerst und fest am unteren Rand: die einzige Primäraktion der
        # Ansicht darf nie herausgedrückt werden. Die Felder darüber scrollen – sonst
        # verdeckt eine eingeblendete Meldung die untersten Zeilen.
        actions = tk.Frame(page, bg=Theme.BG_LAYER)
        actions.pack(side="bottom", fill="x", padx=40, pady=(12, 28))
        self.submit_btn = Button(actions, self.t("send.create"), self._submit,
                                 variant="accent", font_obj=self.f_body, min_width=120)
        self.submit_btn.pack(side="right")

        holder = tk.Frame(page, bg=Theme.BG_LAYER)
        holder.pack(fill="both", expand=True, padx=(40, 24), pady=(24, 0))
        form = self._capped_column(self._scrollable(holder))

        self._label(form, self.t("send.recipient"), hint=self.t("send.optional")).pack(fill="x")
        self.entry_recipient = Field(form, font_obj=self.f_body)
        self.entry_recipient.pack(fill="x", pady=(6, 18))

        message_head = tk.Frame(form, bg=Theme.BG_LAYER)
        message_head.pack(fill="x")
        tk.Label(message_head, text=self.t("send.message"), bg=Theme.BG_LAYER,
                 fg=Theme.TEXT, font=self.f_body).pack(side="left")
        self.char_label = tk.Label(message_head, text=self.t("send.chars", n=0),
                                   bg=Theme.BG_LAYER, fg=Theme.TEXT_TERTIARY,
                                   font=self.f_caption)
        self.char_label.pack(side="right")

        area = TextArea(form, font_obj=self.f_body, height=150)
        area.pack(fill="x", pady=(6, 18))
        self.txt = area.text
        self.txt.bind("<<Modified>>", self._on_text_modified)

        self._label(form, self.t("send.ttl")).pack(fill="x")
        self.ttl_group = ChoiceGroup(
            form, [(p.key, p.label(self.lang)) for p in PRESETS],
            self.settings.default_ttl, lambda _k: None,
            font_obj=self.f_caption, columns=5,
        )
        self.ttl_group.pack(fill="x", pady=(6, 18))

        self._label(form, self.t("send.passphrase"), hint=self.t("send.optional")).pack(fill="x")
        tk.Label(form, text=self.t("send.passphrase_hint"), bg=Theme.BG_LAYER,
                 fg=Theme.TEXT_TERTIARY, font=self.f_caption, anchor="w",
                 justify="left", wraplength=self.CONTENT_MAX).pack(fill="x", pady=(2, 6))
        passphrase_row = tk.Frame(form, bg=Theme.BG_LAYER)
        passphrase_row.pack(fill="x", pady=(0, 24))
        self.entry_passphrase = Field(passphrase_row, font_obj=self.f_body, show="●")
        self.entry_passphrase.pack(side="left", fill="x", expand=True)

        def _toggle_passphrase() -> None:
            hidden = self.entry_passphrase.entry.cget("show") != ""
            self.entry_passphrase.entry.configure(show="" if hidden else "●")
            reveal.set_text(self.t("settings.hide") if hidden else self.t("settings.show"))

        reveal = Button(passphrase_row, self.t("settings.show"), _toggle_passphrase,
                        icon="eye", font_obj=self.f_caption)
        reveal.pack(side="left", padx=(8, 0))
        self.passphrase_reveal_btn = reveal
        return page

    def _build_result_view(self, parent: tk.Misc) -> tk.Frame:
        page, _head = self._page(parent, self.t("result.title"), self.t("result.subtitle"))

        actions = tk.Frame(page, bg=Theme.BG_LAYER)
        actions.pack(side="bottom", fill="x", padx=40, pady=(12, 28))
        Button(actions, self.t("result.new"), self._reset_to_form, variant="accent",
               font_obj=self.f_body).pack(side="left")
        Button(actions, self.t("result.status_check"), self._check_last_status,
               icon="refresh", font_obj=self.f_body).pack(side="left", padx=(8, 0))
        self.result_burn_btn = Button(actions, self.t("burn.action"), self._burn_last_secret,
                                      icon="burn", font_obj=self.f_body)
        self.result_burn_btn.pack(side="left", padx=(8, 0))

        holder = tk.Frame(page, bg=Theme.BG_LAYER)
        holder.pack(fill="both", expand=True, padx=(40, 24), pady=(24, 0))
        body = self._capped_column(self._scrollable(holder))

        self._label(body, self.t("result.link_label")).pack(fill="x")
        link_row = tk.Frame(body, bg=Theme.BG_LAYER)
        link_row.pack(fill="x", pady=(6, 10))
        self.result_link_var = tk.StringVar()
        self.result_field = Field(link_row, textvariable=self.result_link_var,
                                  font_obj=self.f_mono_small, readonly=True)
        self.result_field.pack(side="left", fill="x", expand=True)
        Button(link_row, self.t("result.copy"), self._copy_link, icon="copy",
               font_obj=self.f_body).pack(side="left", padx=(8, 0))

        card = tk.Frame(body, bg=Theme.BG_CARD, highlightthickness=1,
                        highlightbackground=Theme.STROKE)
        card.pack(fill="x", pady=(8, 0))
        inner = tk.Frame(card, bg=Theme.BG_CARD)
        inner.pack(fill="x", padx=16, pady=14)
        self.result_state_label = tk.Label(inner, text="", bg=Theme.BG_CARD,
                                           fg=Theme.ACCENT, font=self.f_body_strong)
        self.result_state_label.pack(side="left")
        self.result_status_label = tk.Label(inner, text="", bg=Theme.BG_CARD,
                                            fg=Theme.TEXT_SECONDARY, font=self.f_body,
                                            anchor="w")
        self.result_status_label.pack(side="left", padx=(10, 0))

        self.result_passphrase_label = tk.Label(
            body, text="", bg=Theme.BG_LAYER, fg=Theme.CAUTION, font=self.f_caption,
            anchor="w", justify="left", wraplength=self.CONTENT_MAX,
        )
        self.result_passphrase_label.pack(fill="x", pady=(12, 0))

        tk.Label(body, text=self.t("result.warning"), bg=Theme.BG_LAYER,
                 fg=Theme.TEXT_SECONDARY, font=self.f_caption, anchor="w",
                 justify="left", wraplength=self.CONTENT_MAX).pack(fill="x", pady=(12, 0))

        return page

    def _show_send_view(self, view: str) -> None:
        self._send_views[self._send_view].pack_forget()
        self._send_view = view
        self._send_views[view].pack(fill="both", expand=True)

    # ---- Verlauf ----

    def _build_history_section(self, parent: tk.Misc) -> tk.Frame:
        page, head = self._page(parent, self.t("history.title"))

        bar = tk.Frame(head, bg=Theme.BG_LAYER)
        bar.pack(fill="x", pady=(14, 0))
        self.history_count = tk.Label(bar, text="", bg=Theme.BG_LAYER,
                                      fg=Theme.TEXT_SECONDARY, font=self.f_body)
        self.history_count.pack(side="left")
        Button(bar, self.t("history.clear"), self._clear_history, icon="delete",
               variant="subtle", font_obj=self.f_body).pack(side="right")
        Button(bar, self.t("history.refresh_all"), self._refresh_all_history,
               icon="refresh", font_obj=self.f_body).pack(side="right", padx=(0, 8))

        holder = tk.Frame(page, bg=Theme.BG_LAYER)
        holder.pack(fill="both", expand=True, padx=(40, 24), pady=(18, 24))
        self._history_container = self._scrollable(holder)
        return page

    def _render_history(self) -> None:
        for widget in self._history_container.winfo_children():
            widget.destroy()

        entries = self.history.entries()
        count_key = "history.count_one" if len(entries) == 1 else "history.count_many"
        self.history_count.configure(text=self.t(count_key, n=len(entries)))

        if not entries:
            self._render_history_empty()
            return
        for entry in entries:
            self._make_history_row(self._history_container, entry).pack(
                fill="x", pady=(0, 8), padx=(0, 8))

    def _render_history_empty(self) -> None:
        """Leerzustand erklärt den nächsten Schritt, statt Leere zu melden."""
        box = tk.Frame(self._history_container, bg=Theme.BG_LAYER)
        box.pack(fill="x", pady=(40, 0))
        tk.Label(box, text=self.t("history.empty_title"), bg=Theme.BG_LAYER,
                 fg=Theme.TEXT, font=self.f_subtitle).pack(anchor="w")
        tk.Label(box, text=self.t("history.empty_sub"), bg=Theme.BG_LAYER,
                 fg=Theme.TEXT_SECONDARY, font=self.f_body, anchor="w",
                 justify="left").pack(anchor="w", pady=(6, 14))
        Button(box, self.t("history.empty_action"), lambda: self._show_section("send"),
               variant="accent", font_obj=self.f_body).pack(anchor="w")

    def _make_history_row(self, parent: tk.Misc, entry: HistoryEntry) -> tk.Frame:
        color, label = self._state_visual(entry.last_state)
        row = tk.Frame(parent, bg=Theme.BG_CARD, highlightthickness=1,
                       highlightbackground=Theme.STROKE)

        top = tk.Frame(row, bg=Theme.BG_CARD)
        top.pack(fill="x", padx=16, pady=(14, 0))

        tk.Label(top, text=label, bg=Theme.BG_CARD, fg=color,
                 font=self.f_body_strong).pack(side="left")
        tk.Label(top, text=self._format_time(entry.created_at), bg=Theme.BG_CARD,
                 fg=Theme.TEXT_SECONDARY, font=self.f_mono_small).pack(side="right")

        meta = self._format_meta(entry)
        if meta:
            tk.Label(row, text=meta, bg=Theme.BG_CARD, fg=Theme.TEXT_TERTIARY,
                     font=self.f_caption, anchor="w", justify="left").pack(
                fill="x", padx=16, pady=(6, 0))

        actions = tk.Frame(row, bg=Theme.BG_CARD)
        actions.pack(fill="x", padx=12, pady=(10, 10))
        identifier = entry.metadata_identifier

        Button(actions, self.t("history.row.status"),
               lambda i=identifier: self._refresh_history_entry(i),
               icon="refresh", variant="subtle", font_obj=self.f_caption).pack(side="left")
        Button(actions, self.t("history.row.page"),
               lambda i=identifier or entry.metadata_key: self._open_status_link(i),
               icon="external", variant="subtle", font_obj=self.f_caption).pack(
            side="left", padx=(4, 0))
        if self._is_burnable(entry.last_state):
            Button(actions, self.t("history.row.share"),
                   lambda i=identifier: self._copy_share_link(i),
                   icon="link", variant="subtle", font_obj=self.f_caption).pack(
                side="left", padx=(4, 0))
            Button(actions, self.t("history.row.burn"),
                   lambda i=identifier: self._burn_secret(i),
                   icon="burn", variant="subtle", font_obj=self.f_caption).pack(
                side="left", padx=(4, 0))
        Button(actions, "", lambda i=identifier: self._delete_history_entry(i),
               icon="remove", variant="subtle", icon_only=True,
               font_obj=self.f_caption).pack(side="right")
        return row

    def _state_visual(self, state: str) -> tuple[str, str]:
        key = (state or "unknown").lower()
        colors = {
            STATE_NEW: Theme.ACCENT,
            "shared": Theme.ACCENT,
            "previewed": Theme.CAUTION,
            "viewed": Theme.CAUTION,
            "revealed": Theme.SUCCESS,
            "received": Theme.SUCCESS,
            "burned": Theme.DANGER,
            "expired": Theme.TEXT_TERTIARY,
            "orphaned": Theme.TEXT_TERTIARY,
        }
        color = colors.get(key, Theme.TEXT_TERTIARY)
        label_key = f"state.{key}"
        label = self.t(label_key) if label_key in STRINGS else key
        return color, label

    @staticmethod
    def _format_time(iso_str: str) -> str:
        try:
            moment = datetime.fromisoformat(iso_str).astimezone()
        except (ValueError, TypeError):
            return iso_str or "–"
        return moment.strftime("%d.%m.%Y  %H:%M")

    def _ttl_label(self, entry: HistoryEntry) -> str:
        """Die Sekunden sind die verlässliche Angabe; das gespeicherte Label ist nur
        der Fallback für Einträge aus älteren Versionen."""
        preset = preset_for_seconds(entry.ttl_seconds)
        if preset:
            return preset.label(self.lang)
        legacy = LEGACY_TTL_LABELS.get(entry.ttl_label)
        return preset_for_key(legacy).label(self.lang) if legacy else entry.ttl_label

    def _format_meta(self, entry: HistoryEntry) -> str:
        bits: list[str] = []
        if entry.recipient:
            bits.append(self.t("history.meta.to", recipient=entry.recipient))
        ttl = self._ttl_label(entry)
        if ttl:
            bits.append(self.t("history.meta.ttl", ttl=ttl))
        if entry.has_passphrase:
            bits.append(self.t("history.meta.passphrase"))
        if entry.last_checked and entry.last_checked != entry.created_at:
            bits.append(self.t("history.meta.checked", time=self._format_time(entry.last_checked)))
        return "   ·   ".join(bits)

    # ---- Einstellungen ----

    def _settings_card(self, parent: tk.Misc, title: str, description: str = "") -> tk.Frame:
        """Eine Einstellungskarte wie in den Windows-Einstellungen: Beschriftung
        links, Steuerelement rechts oder darunter."""
        card = tk.Frame(parent, bg=Theme.BG_CARD, highlightthickness=1,
                        highlightbackground=Theme.STROKE)
        card.pack(fill="x", pady=(0, 8))
        head = tk.Frame(card, bg=Theme.BG_CARD)
        head.pack(fill="x", padx=16, pady=(14, 0))
        tk.Label(head, text=title, bg=Theme.BG_CARD, fg=Theme.TEXT,
                 font=self.f_body, anchor="w").pack(fill="x")
        if description:
            tk.Label(head, text=description, bg=Theme.BG_CARD, fg=Theme.TEXT_TERTIARY,
                     font=self.f_caption, anchor="w", justify="left",
                     wraplength=self.CONTENT_MAX - 40).pack(fill="x", pady=(2, 0))
        body = tk.Frame(card, bg=Theme.BG_CARD)
        body.pack(fill="x", padx=16, pady=(10, 14))
        return body

    def _build_settings_section(self, parent: tk.Misc) -> tk.Frame:
        page, _head = self._page(parent, self.t("settings.title"), self.t("settings.subtitle"))
        holder = tk.Frame(page, bg=Theme.BG_LAYER)
        holder.pack(fill="both", expand=True, padx=(40, 24), pady=(20, 24))
        form = self._scrollable(holder)

        column = self._capped_column(form)

        url_var = tk.StringVar(value=self.settings.api_url)
        user_var = tk.StringVar(value=self.settings.api_user)
        key_var = tk.StringVar(value=self.settings.api_key)
        timeout_var = tk.StringVar(value=str(self.settings.request_timeout))
        region_var = tk.StringVar(value=self.settings.region)
        lang_var = tk.StringVar(value=self.lang)
        ttl_var = tk.StringVar(value=self.settings.default_ttl)

        body = self._settings_card(column, self.t("settings.user"))
        user_field = Field(body, textvariable=user_var, font_obj=self.f_body)
        user_field.pack(fill="x")

        body = self._settings_card(
            column, self.t("settings.key"),
            self.t("settings.keyring_yes") if self.settings_store.keyring_available
            else self.t("settings.keyring_no"))
        key_row = tk.Frame(body, bg=Theme.BG_CARD)
        key_row.pack(fill="x")
        key_field = Field(key_row, textvariable=key_var, font_obj=self.f_mono_small, show="●")
        key_field.pack(side="left", fill="x", expand=True)

        def _toggle_key() -> None:
            hidden = key_field.entry.cget("show") != ""
            key_field.entry.configure(show="" if hidden else "●")
            show_btn.set_text(self.t("settings.hide") if hidden else self.t("settings.show"))

        show_btn = Button(key_row, self.t("settings.show"), _toggle_key, icon="eye",
                          font_obj=self.f_caption)
        show_btn.pack(side="left", padx=(8, 0))

        body = self._settings_card(column, self.t("settings.region"))
        region_group = ChoiceGroup(
            body, [(k, label) for k, (label, _host) in REGIONS.items()],
            region_var.get(), lambda key: _on_region(key), font_obj=self.f_caption, columns=4)
        region_group.pack(fill="x")

        body = self._settings_card(column, self.t("settings.url"))
        url_field = Field(body, textvariable=url_var, font_obj=self.f_mono_small)
        url_field.pack(fill="x")

        def _on_region(key: str) -> None:
            region_var.set(key)
            if key != "custom":
                url_var.set(build_api_url(key))

        body = self._settings_card(column, self.t("settings.language"))
        ChoiceGroup(body, list(LANGUAGES), lang_var.get(), lang_var.set,
                    font_obj=self.f_caption, columns=4).pack(fill="x")

        body = self._settings_card(column, self.t("settings.default_ttl"))
        ChoiceGroup(body, [(p.key, p.label(self.lang)) for p in PRESETS],
                    ttl_var.get(), ttl_var.set, font_obj=self.f_caption,
                    columns=5).pack(fill="x")

        body = self._settings_card(column, self.t("settings.timeout"),
                                   self.t("settings.timeout_hint"))
        timeout_field = Field(body, textvariable=timeout_var, font_obj=self.f_body)
        timeout_field.pack(anchor="w")
        timeout_field.configure(width=120)

        actions = tk.Frame(column, bg=Theme.BG_LAYER)
        actions.pack(fill="x", pady=(16, 0))
        Button(actions, self.t("settings.save"),
               lambda: self._save_settings(
                   url_var.get().strip(), user_var.get().strip(), key_var.get().strip(),
                   region_var.get(), lang_var.get(), timeout_var.get().strip(), ttl_var.get()),
               variant="accent", font_obj=self.f_body, min_width=110).pack(side="left")
        self.test_btn = Button(actions, self.t("settings.test"),
                               lambda: self._test_connection(
                                   url_var.get().strip(), user_var.get().strip(),
                                   key_var.get().strip()),
                               font_obj=self.f_body)
        self.test_btn.pack(side="left", padx=(8, 0))
        Button(actions, self.t("settings.reset"), self._reset_settings,
               variant="subtle", font_obj=self.f_body).pack(side="right")
        return page

    def _save_settings(self, url: str, user: str, key: str, region: str,
                       language: str, timeout_str: str, default_ttl: str) -> None:
        try:
            timeout = int(timeout_str or REQUEST_TIMEOUT_SECONDS)
            if timeout <= 0:
                timeout = REQUEST_TIMEOUT_SECONDS
        except ValueError:
            timeout = REQUEST_TIMEOUT_SECONDS

        if region != "custom":
            url = build_api_url(region)

        new_settings = Settings(
            api_url=url,
            api_user=user,
            api_key=key,
            region=region or detect_region_from_url(url),
            language=language or DEFAULT_LANGUAGE,
            request_timeout=timeout,
            default_ttl=resolve_ttl_key(default_ttl),
        )
        try:
            storage = self.settings_store.save(new_settings)
        except OSError as exc:
            self._show_message(str(exc), "error")
            return

        self._apply_settings(self.settings_store.current)
        self._rebuild_ui(stay_on="settings")
        self._show_save_result(storage)

    def _show_save_result(self, storage: str) -> None:
        """Meldet, wo der Key tatsächlich gelandet ist – eine pauschale
        Sicherheitszusage wäre falsch, wenn der Keyring-Schreibversuch scheiterte."""
        if storage == KEY_STORAGE_FAILED:
            self._show_message(self.t("settings.key_not_stored"), "error")
        elif storage == KEY_STORAGE_FILE:
            self._show_message(self.t("settings.saved_plaintext"), "warning")
        else:
            self._show_message(self.t("settings.saved"), "success")

    def _reset_settings(self) -> None:
        if not messagebox.askyesno(self.t("settings.reset"), self.t("settings.reset_confirm"),
                                   icon="warning", default="no", parent=self):
            return
        try:
            self.settings_store.save(Settings.defaults())
        except OSError as exc:
            self._show_message(str(exc), "error")
            return
        self._apply_settings(self.settings_store.current)
        self._rebuild_ui(stay_on="settings")
        self._show_message(self.t("settings.reset_done"), "success")

    def _rebuild_ui(self, *, stay_on: Optional[str] = None) -> None:
        if stay_on:
            self._current_section = stay_on
        for widget in (self._nav_frame, self._content_frame):
            if widget is not None:
                with suppress(Exception):
                    widget.destroy()
        self._nav_items.clear()
        self._sections.clear()
        self._send_views.clear()
        self._send_view = "form"
        self._last_metadata_identifier = ""
        self._build_ui()

    # ---- Meldungen ----

    def _build_message_bar(self) -> None:
        self._message_holder = tk.Frame(self._content_frame, bg=Theme.BG_LAYER)
        self.message_bar = InfoBar(self._message_holder, font_obj=self.f_body,
                                   on_close=self._hide_message)
        self.message_bar.pack(fill="x")
        # Nicht packen: die Leiste erscheint erst bei einer Meldung – und dann
        # `before=self._body`, sonst hat der expandierende Inhalt den Platz schon.

    def _show_message(self, text: str, severity: str = "info", *,
                      duration: Optional[int] = None) -> None:
        """Eine Meldung bleibt stehen, bis sie geschlossen oder ersetzt wird.
        Nur Bestätigungen verschwinden von selbst – ein Fehler wartet auf Lesen."""
        if self._message_job is not None:
            with suppress(Exception):
                self.after_cancel(self._message_job)
            self._message_job = None
        self.message_bar.show(text, severity)
        self._message_holder.pack(side="bottom", fill="x", padx=40, pady=(12, 20),
                                  before=self._body)
        if duration is None:
            duration = 4000 if severity == "success" else 0
        if duration:
            self._message_job = self.after(duration, self._hide_message)

    def _hide_message(self) -> None:
        self._message_job = None
        self._message_holder.pack_forget()

    # ---- Ereignisse ----

    def _on_text_modified(self, _event: tk.Event) -> None:
        if not self.txt.edit_modified():
            return
        count = len(self.txt.get("1.0", "end-1c"))
        self.char_label.configure(text=self.t("send.chars", n=count))
        self.txt.edit_modified(False)

    def _reset_to_form(self) -> None:
        if self._send_view != "result":
            return
        self.txt.delete("1.0", "end")
        self.entry_recipient.entry.delete(0, "end")
        self.entry_passphrase.entry.delete(0, "end")
        self.char_label.configure(text=self.t("send.chars", n=0))
        self._show_send_view("form")
        self.txt.focus_set()

    def _copy_link(self) -> None:
        link = self.result_link_var.get()
        if not link:
            return
        self.clipboard_clear()
        self.clipboard_append(link)
        self.update_idletasks()
        self._show_message(self.t("result.copied"), "success")

    def _check_last_status(self) -> None:
        if not self._last_metadata_identifier:
            self._show_message(self.t("result.no_status"), "error")
            return
        self._refresh_history_entry(self._last_metadata_identifier, also_update_result=True)

    # ---- Verbrennen ----

    def _is_burnable(self, state: str) -> bool:
        return (state or "").lower() not in OTSClient.TERMINAL_STATES

    def _burn_last_secret(self) -> None:
        if not self._last_metadata_identifier:
            self._show_message(self.t("result.no_status"), "error")
            return
        self._burn_secret(self._last_metadata_identifier, from_result=True)

    def _burn_secret(self, identifier: str, *, from_result: bool = False) -> None:
        if not identifier:
            self._show_message(self.t("error.no_id"), "error")
            return
        if not messagebox.askyesno(
            self.t("burn.confirm_title"), self.t("burn.confirm"),
            icon="warning", default="no", parent=self,
        ):
            return
        if from_result:
            self.result_burn_btn.set_text(self.t("burn.busy"))
            self.result_burn_btn.set_enabled(False)
        # Client im Main-Thread festhalten: ein Settings-Speichern währenddessen
        # tauscht self.client aus, der laufende Request gehört aber zum alten.
        threading.Thread(
            target=self._burn_worker, args=(self.client, identifier, from_result), daemon=True,
        ).start()

    def _burn_worker(self, client: OTSClient, identifier: str, from_result: bool) -> None:
        try:
            new_state = client.burn(identifier)
        except OTSError as exc:
            # Meldung vorher binden: `exc` ist nach dem except-Block nicht mehr
            # gebunden, das Lambda läuft aber erst später im Mainloop.
            message = self._error_text(exc)
            self.after(0, lambda: self._on_burn_failed(message, from_result))
            return
        except Exception as exc:
            # Ohne diesen Zweig stirbt der Thread still und der Knopf bliebe
            # dauerhaft auf "Verbrenne …" stehen.
            logger.exception("Unerwarteter Fehler beim Verbrennen")
            message = self.t("error.unexpected", error=exc)
            self.after(0, lambda: self._on_burn_failed(message, from_result))
            return
        self.after(0, lambda: self._on_burned(identifier, new_state, from_result))

    def _on_burned(self, identifier: str, new_state: str, from_result: bool) -> None:
        self.history.update_state(identifier, new_state)
        self._show_message(self.t("burn.done"), "success")
        if from_result:
            self.result_burn_btn.set_text(self.t("burn.action"))
            self._update_result_state(new_state)
        if self._current_section == "history":
            self._render_history()

    def _on_burn_failed(self, message: str, from_result: bool) -> None:
        if from_result:
            self.result_burn_btn.set_text(self.t("burn.action"))
            self.result_burn_btn.set_enabled(True)
        self._show_message(self.t("burn.failed", error=message), "error")

    # ---- Verbindungstest ----

    def _test_connection(self, url: str, user: str, key: str) -> None:
        self.test_btn.set_text(self.t("settings.testing"))
        self.test_btn.set_enabled(False)
        threading.Thread(
            target=self._test_connection_worker,
            args=(url or self.settings.api_url, user, key),
            daemon=True,
        ).start()

    def _test_connection_worker(self, url: str, user: str, key: str) -> None:
        """Testet die im Formular stehenden Werte, nicht die gespeicherten."""
        probe = OTSClient(url, user, key, timeout=self.settings.request_timeout)
        try:
            info = probe.ping()
        except OTSError as exc:
            message = self._error_text(exc)
            self.after(0, lambda: self._on_test_done(None, message))
            return
        except Exception as exc:  # pragma: no cover - defensiv
            logger.exception("Verbindungstest fehlgeschlagen")
            message = str(exc)
            self.after(0, lambda: self._on_test_done(None, message))
            return
        finally:
            probe.close()
        self.after(0, lambda: self._on_test_done(info, ""))

    def _on_test_done(self, info: Optional[ServiceInfo], error: str) -> None:
        self.test_btn.set_text(self.t("settings.test"))
        self.test_btn.set_enabled(True)
        if info is None:
            self._show_message(self.t("settings.test_fail", error=error), "error")
            return
        if info.authenticated:
            self._show_message(
                self.t("settings.test_ok_full", version=info.version, status=info.status),
                "success")
        else:
            self._show_message(self.t("settings.test_ok_anon", version=info.version), "warning")

    # ---- Verlauf: Aktionen ----

    def _refresh_history_entry(self, identifier: str, *, also_update_result: bool = False) -> None:
        if not identifier:
            return
        threading.Thread(
            target=self._refresh_history_entry_worker,
            args=(self.client, identifier, also_update_result),
            daemon=True,
        ).start()

    def _refresh_history_entry_worker(self, client: OTSClient, identifier: str,
                                      also_update_result: bool) -> None:
        try:
            new_state = client.fetch_status(identifier)
        except OTSError as exc:
            message = self._error_text(exc)
            self.after(0, lambda: self._show_message(message, "error"))
            return
        except Exception as exc:
            logger.exception("Unerwarteter Fehler beim Status-Refresh")
            message = self.t("error.unexpected", error=exc)
            self.after(0, lambda: self._show_message(message, "error"))
            return
        self.after(0, lambda: self._on_state_refreshed(identifier, new_state, also_update_result))

    def _on_state_refreshed(self, identifier: str, new_state: str, update_result: bool) -> None:
        self.history.update_state(identifier, new_state)
        _color, label = self._state_visual(new_state)
        self._show_message(self.t("history.state_now", state=label), "info", duration=4000)
        if self._current_section == "history":
            self._render_history()
        if update_result and identifier == self._last_metadata_identifier:
            self._update_result_state(new_state)

    def _refresh_all_history(self) -> None:
        identifiers = [e.metadata_identifier for e in self.history.entries() if e.metadata_identifier]
        if not identifiers:
            self._show_message(self.t("history.empty"), "info", duration=3000)
            return
        self._show_message(self.t("history.refreshing", n=len(identifiers)), "info", duration=2000)
        # Ein Worker, der die Einträge seriell abfragt: bei 200 Einträgen wären es
        # sonst 200 parallele Threads/Verbindungen – und ein sicheres Rate-Limit.
        threading.Thread(
            target=self._refresh_all_worker, args=(self.client, identifiers), daemon=True,
        ).start()

    def _refresh_all_worker(self, client: OTSClient, identifiers: list[str]) -> None:
        failed = 0
        for identifier in identifiers:
            try:
                new_state = client.fetch_status(identifier)
            except OTSError as exc:
                failed += 1
                logger.warning("Status-Refresh für %s fehlgeschlagen: %s", identifier[:8], exc)
                continue
            except Exception:
                # Ein kaputter Eintrag darf die restlichen nicht mitreißen.
                failed += 1
                logger.exception("Unerwarteter Fehler beim Status-Refresh (%s)", identifier[:8])
                continue
            self.after(0, lambda i=identifier, s=new_state: self._apply_refreshed_state(i, s))
        self.after(0, lambda: self._on_refresh_all_done(len(identifiers), failed))

    def _apply_refreshed_state(self, identifier: str, new_state: str) -> None:
        self.history.update_state(identifier, new_state)
        if identifier == self._last_metadata_identifier:
            self._update_result_state(new_state)

    def _on_refresh_all_done(self, total: int, failed: int) -> None:
        if self._current_section == "history":
            self._render_history()
        if failed:
            self._show_message(
                self.t("history.refresh_done", ok=total - failed, total=total, failed=failed),
                "warning")
        else:
            self._show_message(self.t("history.refresh_ok", n=total), "success")

    def _copy_share_link(self, identifier: str) -> None:
        if not identifier:
            self._show_message(self.t("error.no_id"), "error")
            return
        self._show_message(self.t("history.fetching_share"), "info", duration=2000)
        threading.Thread(
            target=self._copy_share_link_worker, args=(self.client, identifier), daemon=True,
        ).start()

    def _copy_share_link_worker(self, client: OTSClient, identifier: str) -> None:
        try:
            link = client.share_link(identifier)
        except OTSError as exc:
            message = self._error_text(exc)
            self.after(0, lambda: self._show_message(message, "error"))
            return
        except Exception as exc:
            logger.exception("Unerwarteter Fehler beim Holen des Empfänger-Links")
            message = self.t("error.unexpected", error=exc)
            self.after(0, lambda: self._show_message(message, "error"))
            return
        self.after(0, lambda: self._on_share_link(link))

    def _on_share_link(self, link: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(link)
        self.update_idletasks()
        self._show_message(self.t("history.copy_share"), "success")

    def _open_status_link(self, identifier: str) -> None:
        """Öffnet die Verwaltungsseite des Secrets im Browser.

        Das ist nicht der Empfänger-Link: die Seite zeigt den Zustand und erlaubt
        das Verbrennen – sie zu öffnen verbraucht das Secret nicht."""
        if not identifier:
            return
        url = f"{self.metadata_base}/{identifier}"
        try:
            opened = webbrowser.open(url, new=2)
        except Exception:
            logger.exception("Konnte den Browser nicht öffnen.")
            opened = False
        if opened:
            self._show_message(self.t("history.open_meta"), "success")
            return
        # Ohne konfigurierten Browser bleibt der Link wenigstens greifbar.
        self.clipboard_clear()
        self.clipboard_append(url)
        self.update_idletasks()
        self._show_message(self.t("history.open_failed"), "warning")

    def _delete_history_entry(self, identifier: str) -> None:
        self.history.remove(identifier)
        self._render_history()

    def _clear_history(self) -> None:
        if not self.history.entries():
            return
        if not messagebox.askyesno(self.t("history.clear"), self.t("history.clear_confirm"),
                                   icon="warning", default="no", parent=self):
            return
        self.history.clear()
        self._render_history()
        self._show_message(self.t("history.cleared"), "success")

    def _save_to_history(self, result: ShareResult, recipient: Optional[str],
                         ttl_key: str, ttl_seconds: int, has_passphrase: bool) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        entry = HistoryEntry(
            created_at=now,
            recipient=recipient,
            ttl_label=ttl_key,
            ttl_seconds=ttl_seconds,
            metadata_key=result.metadata_key,
            metadata_identifier=result.metadata_identifier,
            # Bewusst die (unkritische) Receipt-shortid, nicht der Anfang des
            # Share-Tokens – die History liegt im Klartext auf der Platte.
            secret_preview=result.receipt_shortid,
            last_state=result.state,
            last_checked=now,
            has_passphrase=has_passphrase,
        )
        self.history.add(entry)
        if self._current_section == "history":
            self._render_history()

    # ---- Senden ----

    def _submit(self) -> None:
        if self._send_view != "form" or self._current_section != "send":
            return
        secret = self.txt.get("1.0", "end-1c").strip()
        if not secret:
            self._show_message(self.t("send.empty"), "error")
            self.txt.focus_set()
            return

        recipient = self.entry_recipient.entry.get().strip()
        passphrase = self.entry_passphrase.entry.get().strip()
        ttl_preset = preset_for_key(self.ttl_group.value)

        self.submit_btn.set_enabled(False)
        self.submit_btn.set_text(self.t("send.sending"))
        threading.Thread(
            target=self._request_thread,
            args=(self.client, secret, ttl_preset, recipient or None, passphrase or None),
            daemon=True,
        ).start()

    def _request_thread(self, client: OTSClient, secret: str, ttl_preset: TTLPreset,
                        recipient: Optional[str], passphrase: Optional[str]) -> None:
        try:
            result = client.share(secret, ttl_preset.seconds, recipient, passphrase)
            # share_url stammt aus der Antwort (korrekt auch bei Custom Domains);
            # der aus dem API-Host gebaute Link ist nur der Fallback.
            secret_link = result.share_url or f"{self.link_base}/{result.secret_key}"
            self.after(0, lambda: self._on_success(
                secret_link, result, ttl_preset, recipient, bool(passphrase)))
        except OTSError as exc:
            message = self._error_text(exc)
            self.after(0, lambda: self._on_error(message))
        except Exception as exc:
            logger.exception("Unerwarteter Fehler beim Senden")
            message = self.t("error.unexpected", error=exc)
            self.after(0, lambda: self._on_error(message))

    def _on_success(self, link: str, result: ShareResult, ttl_preset: TTLPreset,
                    recipient: Optional[str], has_passphrase: bool) -> None:
        self.submit_btn.set_text(self.t("send.create"))
        self.submit_btn.set_enabled(True)

        self._last_metadata_identifier = result.metadata_identifier
        self.result_burn_btn.set_text(self.t("burn.action"))
        self.result_burn_btn.set_enabled(True)
        self.clipboard_clear()
        self.clipboard_append(link)
        self.update_idletasks()

        try:
            self._save_to_history(result, recipient, ttl_preset.key,
                                  ttl_preset.seconds, has_passphrase)
        except Exception:
            logger.exception("History-Save fehlgeschlagen.")

        self.result_link_var.set(link)
        self._update_result_state(result.state)
        self.result_passphrase_label.configure(
            text=self.t("result.passphrase_note") if has_passphrase else "")
        self._show_send_view("result")

        if result.state and result.state != STATE_NEW:
            logger.warning("Secret kommt bereits mit state=%s zurück", result.state)
            self._show_message(self.t("warn.consumed", state=result.state), "warning")
        else:
            self._show_message(self.t("result.copied"), "success")

    def _update_result_state(self, state: str) -> None:
        color, label = self._state_visual(state)
        self.result_state_label.configure(text=label, fg=color)
        sub = self.t("result.status_waiting" if state == STATE_NEW else "result.status_history")
        self.result_status_label.configure(text=sub)

    def _on_error(self, message: str) -> None:
        self.submit_btn.set_text(self.t("send.create"))
        self.submit_btn.set_enabled(True)
        self._show_message(message, "error")


# ============================================================
# Helpers
# ============================================================

def _region_label(host: str) -> str:
    h = host.lower()
    if h.startswith("eu."):
        return "EU"
    if h.startswith("us."):
        return "US"
    if h.startswith("ca."):
        return "CA"
    if h.startswith("uk."):
        return "UK"
    if h.startswith("nz."):
        return "NZ"
    return "GLOBAL"


def _truncate(text: str, length: int) -> str:
    if len(text) <= length:
        return text
    return text[: length - 1] + "…"


if __name__ == "__main__":
    App().mainloop()
