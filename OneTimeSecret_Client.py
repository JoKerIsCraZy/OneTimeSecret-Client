"""OneTimeSecret Client – professionelles Tkinter-GUI für OneTimeSecret v2."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
import tkinter as tk
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk
from typing import NamedTuple, Optional
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
    "app.subtitle":            {"de": "Verschlüsselte Nachrichten · einmal sichtbar · selbstzerstörend.",
                                "en": "Encrypted messages · single-use · self-destructing."},
    "nav.send":                {"de": "Senden",        "en": "Send"},
    "nav.history":             {"de": "Verlauf",       "en": "History"},
    "nav.settings":            {"de": "Einstellungen", "en": "Settings"},
    "sidebar.workspace":       {"de": "WORKSPACE",     "en": "WORKSPACE"},
    "sidebar.region":          {"de": "REGION",        "en": "REGION"},
    "sidebar.api":             {"de": "API",           "en": "API"},
    "sidebar.account":         {"de": "ACCOUNT",       "en": "ACCOUNT"},
    "send.eyebrow":            {"de": "NEUES SECRET",  "en": "NEW SECRET"},
    "send.title":              {"de": "Einmal-Link erstellen",
                                "en": "Create one-time link"},
    "send.subtitle":           {"de": "Einmal abrufbar · nach Abruf oder Ablauf der TTL automatisch gelöscht.",
                                "en": "Single-use · auto-deleted after retrieval or TTL expiration."},
    "send.recipient":          {"de": "Empfänger",     "en": "Recipient"},
    "send.optional":           {"de": "OPTIONAL",      "en": "OPTIONAL"},
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
    "result.link_label":       {"de": "EMPFÄNGER-LINK","en": "RECIPIENT LINK"},
    "result.copy":             {"de": "Kopieren",      "en": "Copy"},
    "result.copied":           {"de": "Link kopiert ✓","en": "Link copied ✓"},
    "result.status_label":     {"de": "STATUS",        "en": "STATUS"},
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
    "history.eyebrow":         {"de": "VERLAUF",       "en": "HISTORY"},
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
    "history.row.link":        {"de": "Link",          "en": "Link"},
    "history.row.burn":        {"de": "Verbrennen",    "en": "Burn"},
    "history.copy_meta":       {"de": "Status-Link kopiert", "en": "Status link copied"},
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
    "settings.eyebrow":        {"de": "EINSTELLUNGEN", "en": "SETTINGS"},
    "settings.title":          {"de": "API & Konfiguration", "en": "API & Configuration"},
    "settings.subtitle":       {"de": "Zugangsdaten, Region und Sprache anpassen.",
                                "en": "Configure credentials, region and language."},
    "settings.region":         {"de": "REGION",        "en": "REGION"},
    "settings.url":            {"de": "API-URL",       "en": "API URL"},
    "settings.user":           {"de": "BENUTZER (E-MAIL)", "en": "USER (EMAIL)"},
    "settings.key":            {"de": "API-KEY",       "en": "API KEY"},
    "settings.show":           {"de": "Anzeigen",      "en": "Show"},
    "settings.hide":           {"de": "Verbergen",     "en": "Hide"},
    "settings.advanced":       {"de": "ERWEITERT",     "en": "ADVANCED"},
    "settings.timeout":        {"de": "TIMEOUT (SEKUNDEN)", "en": "TIMEOUT (SECONDS)"},
    "settings.default_ttl":    {"de": "STANDARD-GÜLTIGKEIT", "en": "DEFAULT LIFETIME"},
    "settings.language":       {"de": "SPRACHE",       "en": "LANGUAGE"},
    "settings.test":           {"de": "Verbindung testen", "en": "Test connection"},
    "settings.reset":          {"de": "Zurücksetzen",  "en": "Reset"},
    "settings.save":           {"de": "Speichern",     "en": "Save"},
    "settings.saved":          {"de": "Einstellungen gespeichert", "en": "Settings saved"},
    "settings.reset_done":     {"de": "Auf Standard zurückgesetzt", "en": "Reset to defaults"},
    "settings.testing":        {"de": "Teste …",       "en": "Testing …"},
    "settings.test_ok":        {"de": "Verbindung OK", "en": "Connection OK"},
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
    "error.insecure_url":      {"de": "Unverschlüsselte Verbindung abgelehnt – die API-URL muss mit https:// beginnen.",
                                "en": "Refusing an unencrypted connection – the API URL must start with https://."},
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
    "error.no_secret_key":     {"de": "Antwort ohne Secret-Key.", "en": "Response contained no secret key."},
    "error.no_metadata_key":   {"de": "Antwort ohne Metadata-Key.", "en": "Response contained no metadata key."},
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
# Theme – "Vault" (refined enterprise dark)
# ============================================================

class Theme:
    # Surfaces
    BG       = "#0b0d13"
    SIDEBAR  = "#0f1219"
    SURFACE  = "#13161f"
    CARD     = "#1a1e2a"
    RAISED   = "#212636"
    INPUT_BG = "#0d1018"

    # Borders
    BORDER        = "#242937"
    BORDER_STRONG = "#2f3548"
    BORDER_FOCUS  = "#3d5a80"
    DIVIDER       = "#1c2030"

    # Text
    TEXT       = "#eaecf2"
    TEXT_SOFT  = "#c5cad6"
    TEXT_MUTED = "#8b91a3"
    TEXT_DIM   = "#5a6072"

    # Accent (cyan-teal)
    ACCENT       = "#22d3ee"
    ACCENT_HOVER = "#67e8f9"
    ACCENT_PRESS = "#06b6d4"
    ACCENT_TEXT  = "#062b33"
    ACCENT_SOFT  = "#0a2832"
    ACCENT_DIM   = "#0e3a44"

    # Status
    SUCCESS_FG     = "#34d399"
    SUCCESS_BG     = "#0d2920"
    SUCCESS_BORDER = "#1a4a36"
    ERROR_FG       = "#f87171"
    ERROR_BG       = "#2a0e15"
    ERROR_BORDER   = "#5a1f2a"
    WARNING_FG     = "#fbbf24"
    WARNING_BG     = "#2a200a"

    # Specials
    LINK_BG = "#0c1626"
    LINK_FG = "#7dd3fc"


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
        finally:
            self._release()

        if response.status_code >= 400:
            raise self._error_from_response(response)

        try:
            data = response.json()
        except ValueError as exc:
            raise _ots_error("error.invalid_json") from exc
        return data if isinstance(data, dict) else {}

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

    def share(self, secret: str, ttl_seconds: int, recipient: Optional[str] = None) -> ShareResult:
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

    def burn(self, identifier: str) -> str:
        """Vernichtet das Secret vor dem Abruf. Der Empfänger-Link wird sofort ungültig."""
        if not identifier:
            raise _ots_error("error.no_id")
        data = self._request(
            "POST", f"{self._api_base()}/api/v2/receipt/{identifier}/burn",
            json_body={},
        )
        state = self._state_from_receipt(data)
        return state if state != "unknown" else "burned"

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
            self.path.write_text(
                json.dumps([e.to_dict() for e in self._entries], indent=2, ensure_ascii=False),
                encoding="utf-8",
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

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.keyring_available and settings.api_user and settings.api_key:
            stored = self._write_key_to_keyring(settings.api_user, settings.api_key)
            payload = settings.to_dict_safe() if stored else settings.to_dict()
        else:
            payload = settings.to_dict()
        self.path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.current = settings


# ============================================================
# UI Primitives
# ============================================================

class FlatButton(tk.Frame):
    """Schlanker Button mit Hover/Press-States – ttk-frei, voll designbar."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        on_click: Callable[[], None],
        *,
        primary: bool = True,
        ghost: bool = False,
        font_obj: Optional[tkfont.Font] = None,
        padx: int = 18,
        pady: int = 9,
    ) -> None:
        super().__init__(parent, bg=parent["bg"], highlightthickness=0)
        self._on_click = on_click
        self._enabled = True

        if primary:
            self._bg_default = Theme.ACCENT
            self._fg_default = Theme.ACCENT_TEXT
            self._bg_hover   = Theme.ACCENT_HOVER
            self._bg_press   = Theme.ACCENT_PRESS
        elif ghost:
            self._bg_default = parent["bg"]
            self._fg_default = Theme.TEXT_MUTED
            self._bg_hover   = Theme.CARD
            self._bg_press   = Theme.RAISED
        else:
            self._bg_default = Theme.RAISED
            self._fg_default = Theme.TEXT
            self._bg_hover   = Theme.BORDER_STRONG
            self._bg_press   = Theme.BORDER_FOCUS

        self._label = tk.Label(
            self, text=text, bg=self._bg_default, fg=self._fg_default,
            font=font_obj or ("Segoe UI", 10, "bold"),
            padx=padx, pady=pady, cursor="hand2",
        )
        self._label.pack(fill="both", expand=True)
        self._label.bind("<Enter>", self._enter)
        self._label.bind("<Leave>", self._leave)
        self._label.bind("<Button-1>", self._press)
        self._label.bind("<ButtonRelease-1>", self._release)

    def set_text(self, text: str) -> None:
        self._label.configure(text=text)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if enabled:
            self._label.configure(bg=self._bg_default, fg=self._fg_default, cursor="hand2")
        else:
            self._label.configure(bg=Theme.CARD, fg=Theme.TEXT_DIM, cursor="arrow")

    def _enter(self, _e: tk.Event) -> None:
        if self._enabled:
            self._label.configure(bg=self._bg_hover)

    def _leave(self, _e: tk.Event) -> None:
        if self._enabled:
            self._label.configure(bg=self._bg_default)

    def _press(self, _e: tk.Event) -> None:
        if self._enabled:
            self._label.configure(bg=self._bg_press)

    def _release(self, _e: tk.Event) -> None:
        if not self._enabled:
            return
        self._label.configure(bg=self._bg_hover)
        self._on_click()


class PillBar(tk.Frame):
    """Auswahlleiste mit Pill-Buttons."""

    def __init__(
        self,
        parent: tk.Misc,
        presets: tuple[TTLPreset, ...],
        default_key: str,
        on_change: Callable[[TTLPreset], None],
        *,
        lang: str = DEFAULT_LANGUAGE,
    ) -> None:
        super().__init__(parent, bg=parent["bg"])
        self._on_change = on_change
        self._labels: dict[str, tk.Label] = {}
        self._selected = resolve_ttl_key(default_key)
        cols = 5
        for index, preset in enumerate(presets):
            row, col = divmod(index, cols)
            pill = tk.Label(
                self, text=preset.label(lang),
                bg=parent["bg"], fg=Theme.TEXT_MUTED,
                font=("Segoe UI", 9), padx=14, pady=7, cursor="hand2",
            )
            pill.grid(row=row, column=col, padx=(0, 6), pady=4, sticky="w")
            pill.bind("<Button-1>", lambda _e, p=preset: self._select(p))
            pill.bind("<Enter>", lambda _e, p=preset: self._hover(p.key, True))
            pill.bind("<Leave>", lambda _e, p=preset: self._hover(p.key, False))
            self._labels[preset.key] = pill
        self._refresh()

    @property
    def selected_key(self) -> str:
        return self._selected

    def selected_preset(self) -> TTLPreset:
        return preset_for_key(self._selected)

    def _select(self, preset: TTLPreset) -> None:
        self._selected = preset.key
        self._refresh()
        self._on_change(preset)

    def _hover(self, key: str, entering: bool) -> None:
        if key == self._selected:
            return
        widget = self._labels[key]
        widget.configure(
            bg=Theme.CARD if entering else self["bg"],
            fg=Theme.TEXT if entering else Theme.TEXT_MUTED,
        )

    def _refresh(self) -> None:
        for label, widget in self._labels.items():
            if label == self._selected:
                widget.configure(bg=Theme.ACCENT_DIM, fg=Theme.ACCENT)
            else:
                widget.configure(bg=self["bg"], fg=Theme.TEXT_MUTED)


class ThinScrollbar(tk.Frame):
    """Schlanke, moderne Scrollbar – ersetzt das Vista-artige ttk-Default."""

    WIDTH = 10
    THUMB_WIDTH = 4
    MIN_THUMB_HEIGHT = 28

    def __init__(self, parent: tk.Misc, command: Callable[..., None]) -> None:
        super().__init__(parent, bg=Theme.SURFACE, width=self.WIDTH)
        self.pack_propagate(False)
        self._command = command
        self._first = 0.0
        self._last = 1.0
        self._press_offset = 0

        self._thumb = tk.Frame(
            self, bg=Theme.BORDER_STRONG,
            width=self.THUMB_WIDTH, cursor="hand2",
        )
        self.bind("<Configure>", self._redraw)
        self.bind("<Button-1>", self._on_track_click)

        self._thumb.bind("<Button-1>", self._on_thumb_press)
        self._thumb.bind("<B1-Motion>", self._on_thumb_drag)
        self._thumb.bind("<Enter>", lambda _e: self._thumb.configure(bg=Theme.TEXT_MUTED))
        self._thumb.bind("<Leave>", lambda _e: self._thumb.configure(bg=Theme.BORDER_STRONG))

    def set(self, first: str, last: str) -> None:  # pragma: no cover
        self._first = float(first)
        self._last = float(last)
        self._redraw()

    def _redraw(self, _e: Optional[tk.Event] = None) -> None:
        h = self.winfo_height()
        if h <= 0:
            return
        span = self._last - self._first
        if span >= 0.999:
            self._thumb.place_forget()
            return
        y = int(self._first * h)
        height = max(self.MIN_THUMB_HEIGHT, int(span * h))
        x = (self.WIDTH - self.THUMB_WIDTH) // 2
        self._thumb.place(x=x, y=y, width=self.THUMB_WIDTH, height=height)

    def _on_thumb_press(self, e: tk.Event) -> str:
        self._press_offset = e.y
        return "break"

    def _on_thumb_drag(self, e: tk.Event) -> None:
        h = self.winfo_height()
        if h <= 0:
            return
        new_y = self._thumb.winfo_y() + e.y - self._press_offset
        ratio = max(0.0, min(1.0, new_y / h))
        self._command("moveto", str(ratio))

    def _on_track_click(self, e: tk.Event) -> None:
        h = self.winfo_height()
        if h <= 0:
            return
        span = self._last - self._first
        thumb_h = max(self.MIN_THUMB_HEIGHT, int(span * h))
        ratio = max(0.0, min(1.0, (e.y - thumb_h / 2) / h))
        self._command("moveto", str(ratio))


class NavItem(tk.Frame):
    """Sidebar-Eintrag mit aktivem/Hover-State und Akzent-Streifen links."""

    def __init__(
        self,
        parent: tk.Misc,
        label: str,
        key: str,
        on_select: Callable[[str], None],
        icon: str = "",
    ) -> None:
        super().__init__(parent, bg=Theme.SIDEBAR, cursor="hand2")
        self.key = key
        self._on_select = on_select
        self._active = False

        self._indicator = tk.Frame(self, bg=Theme.SIDEBAR, width=3)
        self._indicator.pack(side="left", fill="y")
        self._indicator.pack_propagate(False)

        self._body = tk.Frame(self, bg=Theme.SIDEBAR)
        self._body.pack(side="left", fill="both", expand=True, padx=(14, 14), pady=11)

        self._icon: Optional[tk.Label] = None
        if icon:
            self._icon = tk.Label(
                self._body, text=icon, bg=Theme.SIDEBAR, fg=Theme.TEXT_MUTED,
                font=("Segoe UI", 12),
            )
            self._icon.pack(side="left", padx=(0, 12))

        self._text = tk.Label(
            self._body, text=label, bg=Theme.SIDEBAR, fg=Theme.TEXT_MUTED,
            font=("Segoe UI", 10, "bold"),
        )
        self._text.pack(side="left")

        widgets = [self, self._indicator, self._body, self._text]
        if self._icon is not None:
            widgets.append(self._icon)
        for w in widgets:
            w.bind("<Button-1>", lambda _e: self._on_select(self.key))
            w.bind("<Enter>", lambda _e: self._hover(True))
            w.bind("<Leave>", lambda _e: self._hover(False))

    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            self._indicator.configure(bg=Theme.ACCENT)
            self._set_bg(Theme.ACCENT_SOFT)
            self._text.configure(fg=Theme.TEXT)
            if self._icon is not None:
                self._icon.configure(fg=Theme.ACCENT)
        else:
            self._indicator.configure(bg=Theme.SIDEBAR)
            self._set_bg(Theme.SIDEBAR)
            self._text.configure(fg=Theme.TEXT_MUTED)
            if self._icon is not None:
                self._icon.configure(fg=Theme.TEXT_MUTED)

    def _hover(self, entering: bool) -> None:
        if self._active:
            return
        bg = Theme.CARD if entering else Theme.SIDEBAR
        fg = Theme.TEXT if entering else Theme.TEXT_MUTED
        self._set_bg(bg)
        self._text.configure(fg=fg)
        if self._icon is not None:
            self._icon.configure(fg=fg)

    def _set_bg(self, color: str) -> None:
        self.configure(bg=color)
        self._body.configure(bg=color)
        self._text.configure(bg=color)
        if self._icon is not None:
            self._icon.configure(bg=color)


# ============================================================
# App
# ============================================================

class App(tk.Tk):
    SIDEBAR_WIDTH = 240

    def __init__(self) -> None:
        super().__init__()
        self.title("OneTimeSecret Client")
        self.geometry("1020x760")
        self.minsize(940, 700)
        self.configure(bg=Theme.BG)
        self._apply_window_icon()

        self.settings_store = SettingsStore()
        self.history = HistoryStore()

        self._current_section: str = "send"
        self._send_view: str = "form"
        self._toast_job: Optional[str] = None
        self._last_metadata_identifier: str = ""

        self._nav_items: dict[str, NavItem] = {}
        self._sections: dict[str, tk.Frame] = {}
        self._send_views: dict[str, tk.Frame] = {}
        self._main_frame: Optional[tk.Frame] = None
        self._sidebar_frame: Optional[tk.Frame] = None
        self._divider_frame: Optional[tk.Frame] = None

        self._apply_settings(self.settings_store.current)

        self._setup_fonts()
        self._setup_ttk_styles()
        self._build_ui()
        self._bind_shortcuts()
        self._center_window()

    # ---- Window chrome ----

    def _apply_window_icon(self) -> None:
        """Set the Tk window icon. Falls back silently to the Tk default."""
        if not ICON_PATH.exists():
            logger.debug("App icon not found at %s; using Tk default", ICON_PATH)
            return
        try:
            self.iconbitmap(default=str(ICON_PATH))
        except tk.TclError as exc:
            logger.debug("Could not apply window icon: %s", exc)

    # ---- Settings application ----

    def _apply_settings(self, settings: Settings) -> None:
        """Übernimmt Settings als App-Attribute und (re)initialisiert den API-Client."""
        self.settings = settings
        known_languages = {code for code, _label in LANGUAGES}
        self.lang = settings.language if settings.language in known_languages else DEFAULT_LANGUAGE
        self.api_host = urlparse(settings.api_url).hostname or "onetimesecret.com"
        self.link_base = f"https://{self.api_host}/secret"
        self.metadata_base = f"https://{self.api_host}/private"

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

    # ---- Fonts / Styles ----

    def _setup_fonts(self) -> None:
        families = set(tkfont.families())
        display = "Segoe UI Variable Display" if "Segoe UI Variable Display" in families else "Segoe UI"
        text = "Segoe UI Variable Text" if "Segoe UI Variable Text" in families else "Segoe UI"
        small = "Segoe UI Variable Small" if "Segoe UI Variable Small" in families else "Segoe UI"
        mono = "Cascadia Mono" if "Cascadia Mono" in families else "Consolas"

        self.f_title       = tkfont.Font(family=display, size=22)
        self.f_h2          = tkfont.Font(family=display, size=14, weight="bold")
        self.f_brand       = tkfont.Font(family=display, size=14, weight="bold")
        self.f_body        = tkfont.Font(family=text,    size=10)
        self.f_body_strong = tkfont.Font(family=text,    size=10, weight="bold")
        self.f_button      = tkfont.Font(family=text,    size=10, weight="bold")
        self.f_eyebrow     = tkfont.Font(family=small,   size=8,  weight="bold")
        self.f_caption     = tkfont.Font(family=small,   size=8)
        self.f_mono        = tkfont.Font(family=mono,    size=10)

    def _setup_ttk_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=Theme.SURFACE, background=Theme.ACCENT,
            bordercolor=Theme.SURFACE,
            lightcolor=Theme.ACCENT, darkcolor=Theme.ACCENT,
            thickness=3,
        )
        style.configure(
            "Vault.Vertical.TScrollbar",
            background=Theme.SURFACE, troughcolor=Theme.BG,
            bordercolor=Theme.BG, arrowcolor=Theme.TEXT_MUTED,
            relief="flat",
        )

    def _center_window(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 3
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _bind_shortcuts(self) -> None:
        self.bind_all("<Control-Return>", lambda _e: self._submit())
        self.bind_all("<Control-Key-1>", lambda _e: self._show_section("send"))
        self.bind_all("<Control-Key-2>", lambda _e: self._show_section("history"))
        self.bind_all("<Control-Key-3>", lambda _e: self._show_section("settings"))

    # ---- Shell ----

    def _build_ui(self) -> None:
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar | Divider | Main
        self._sidebar_frame = self._build_sidebar()
        self._sidebar_frame.grid(row=0, column=0, sticky="nsew")

        self._divider_frame = tk.Frame(self, bg=Theme.BORDER, width=1)
        self._divider_frame.grid(row=0, column=1, sticky="ns")

        self._main_frame = tk.Frame(self, bg=Theme.SURFACE)
        self._main_frame.grid(row=0, column=2, sticky="nsew")

        # Sections
        self._sections["send"] = self._build_send_section(self._main_frame)
        self._sections["history"] = self._build_history_section(self._main_frame)
        self._sections["settings"] = self._build_settings_section(self._main_frame)

        self._build_toast()
        self._show_section(self._current_section)

    def _build_sidebar(self) -> tk.Frame:
        sb = tk.Frame(self, bg=Theme.SIDEBAR, width=self.SIDEBAR_WIDTH)
        sb.grid_propagate(False)
        sb.pack_propagate(False)

        # Brand block
        brand = tk.Frame(sb, bg=Theme.SIDEBAR)
        brand.pack(fill="x", padx=24, pady=(28, 36))
        tk.Label(
            brand, text="◆", bg=Theme.SIDEBAR, fg=Theme.ACCENT,
            font=("Segoe UI", 16),
        ).pack(side="left")
        tk.Label(
            brand, text="OneTimeSecret", bg=Theme.SIDEBAR, fg=Theme.TEXT,
            font=self.f_brand,
        ).pack(side="left", padx=(12, 0))

        # Workspace eyebrow
        tk.Label(
            sb, text=self.t("sidebar.workspace"), bg=Theme.SIDEBAR,
            fg=Theme.TEXT_DIM, font=self.f_eyebrow,
        ).pack(anchor="w", padx=24, pady=(0, 10))

        # Nav items
        nav = tk.Frame(sb, bg=Theme.SIDEBAR)
        nav.pack(fill="x", padx=10)

        self._nav_items["send"] = NavItem(nav, self.t("nav.send"), "send", self._show_section, icon="✦")
        self._nav_items["send"].pack(fill="x", pady=(0, 2))

        self._nav_items["history"] = NavItem(nav, self.t("nav.history"), "history", self._show_section, icon="≡")
        self._nav_items["history"].pack(fill="x", pady=(0, 2))

        self._nav_items["settings"] = NavItem(nav, self.t("nav.settings"), "settings", self._show_section, icon="⚙")
        self._nav_items["settings"].pack(fill="x", pady=(0, 2))

        # Bottom info block
        bottom = tk.Frame(sb, bg=Theme.SIDEBAR)
        bottom.pack(side="bottom", fill="x", padx=24, pady=24)

        tk.Frame(bottom, bg=Theme.BORDER, height=1).pack(fill="x", pady=(0, 18))

        self._sidebar_kv(bottom, self.t("sidebar.region"), _region_label(self.api_host))
        self._sidebar_kv(bottom, self.t("sidebar.api"), "v2 · stable")
        self._sidebar_kv(bottom, self.t("sidebar.account"), _truncate(self.settings.api_user or "—", 22))

        return sb

    def _sidebar_kv(self, parent: tk.Misc, key: str, value: str) -> None:
        tk.Label(parent, text=key, bg=Theme.SIDEBAR, fg=Theme.TEXT_DIM,
                 font=self.f_eyebrow).pack(anchor="w")
        tk.Label(parent, text=value, bg=Theme.SIDEBAR, fg=Theme.TEXT_SOFT,
                 font=self.f_caption).pack(anchor="w", pady=(2, 12))

    def _show_section(self, name: str) -> None:
        if name not in self._sections:
            return
        self._current_section = name
        for s in self._sections.values():
            s.pack_forget()
        self._sections[name].pack(fill="both", expand=True)
        for k, item in self._nav_items.items():
            item.set_active(k == name)
        if name == "history":
            self._render_history()

    # ---- Send section ----

    def _build_send_section(self, parent: tk.Misc) -> tk.Frame:
        section = tk.Frame(parent, bg=Theme.SURFACE)

        head = tk.Frame(section, bg=Theme.SURFACE)
        head.pack(fill="x", padx=46, pady=(40, 28))
        tk.Label(
            head, text=self.t("send.eyebrow"), bg=Theme.SURFACE,
            fg=Theme.TEXT_DIM, font=self.f_eyebrow,
        ).pack(anchor="w")
        tk.Label(
            head, text=self.t("send.title"),
            bg=Theme.SURFACE, fg=Theme.TEXT, font=self.f_title,
        ).pack(anchor="w", pady=(4, 0))
        tk.Label(
            head, text=self.t("send.subtitle"),
            bg=Theme.SURFACE, fg=Theme.TEXT_MUTED, font=self.f_body,
        ).pack(anchor="w", pady=(8, 0))

        host = tk.Frame(section, bg=Theme.SURFACE)
        host.pack(fill="both", expand=True, padx=46, pady=(0, 40))

        self._send_views["form"] = self._build_form_view(host)
        self._send_views["result"] = self._build_result_view(host)
        self._show_send_view("form")

        return section

    def _build_form_view(self, parent: tk.Misc) -> tk.Frame:
        view = tk.Frame(parent, bg=Theme.SURFACE)
        view.columnconfigure(0, weight=1)
        view.rowconfigure(3, weight=1, minsize=200)

        # Empfänger
        self._field_eyebrow(view, self.t("send.recipient"), optional=True).grid(row=0, column=0, sticky="w")
        self.entry_empf_wrap, self.entry_empf = self._make_entry(view)
        self.entry_empf_wrap.grid(row=1, column=0, sticky="we", pady=(8, 24))

        # Nachricht header
        msg_row = tk.Frame(view, bg=Theme.SURFACE)
        msg_row.grid(row=2, column=0, sticky="we", pady=(0, 8))
        msg_row.columnconfigure(0, weight=1)
        self._field_eyebrow(msg_row, self.t("send.message")).grid(row=0, column=0, sticky="w")
        self.counter_label = tk.Label(
            msg_row, text=self.t("send.chars", n=0), bg=Theme.SURFACE,
            fg=Theme.TEXT_DIM, font=self.f_caption,
        )
        self.counter_label.grid(row=0, column=1, sticky="e")

        # Textarea
        wrap = tk.Frame(view, bg=Theme.BORDER)
        wrap.grid(row=3, column=0, sticky="nsew")
        self.txt = tk.Text(
            wrap, bd=0, relief="flat", wrap="word",
            bg=Theme.INPUT_BG, fg=Theme.TEXT,
            insertbackground=Theme.ACCENT,
            selectbackground=Theme.ACCENT_DIM, selectforeground=Theme.TEXT,
            font=self.f_body, padx=18, pady=14,
        )
        self.txt.pack(fill="both", expand=True, padx=1, pady=1)
        self.txt.bind("<<Modified>>", self._on_text_modified)
        self.txt.bind("<FocusIn>", lambda _e: wrap.configure(bg=Theme.BORDER_FOCUS))
        self.txt.bind("<FocusOut>", lambda _e: wrap.configure(bg=Theme.BORDER))

        # TTL
        self._field_eyebrow(view, self.t("send.ttl")).grid(row=4, column=0, sticky="w", pady=(24, 8))
        self.pill_bar = PillBar(
            view, PRESETS, self.settings.default_ttl, lambda _p: None, lang=self.lang,
        )
        self.pill_bar.grid(row=5, column=0, sticky="w")

        # Action bar
        bar = tk.Frame(view, bg=Theme.SURFACE)
        bar.grid(row=6, column=0, sticky="we", pady=(28, 0))
        bar.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(
            bar, mode="indeterminate", style="Accent.Horizontal.TProgressbar",
        )
        self.progress.grid(row=0, column=0, sticky="we", padx=(0, 18))

        self.submit_btn = FlatButton(
            bar, self.t("send.create"), self._submit,
            primary=True, font_obj=self.f_button, padx=22, pady=11,
        )
        self.submit_btn.grid(row=0, column=1, sticky="e")

        return view

    def _build_result_view(self, parent: tk.Misc) -> tk.Frame:
        view = tk.Frame(parent, bg=Theme.SURFACE)
        view.columnconfigure(0, weight=1)

        # Success header
        check_row = tk.Frame(view, bg=Theme.SURFACE)
        check_row.grid(row=0, column=0, sticky="w")
        tk.Label(
            check_row, text="✓", bg=Theme.SURFACE, fg=Theme.SUCCESS_FG,
            font=("Segoe UI", 28),
        ).pack(side="left", padx=(0, 14))
        text_block = tk.Frame(check_row, bg=Theme.SURFACE)
        text_block.pack(side="left")
        tk.Label(
            text_block, text=self.t("result.title"),
            bg=Theme.SURFACE, fg=Theme.TEXT, font=self.f_h2,
        ).pack(anchor="w")
        tk.Label(
            text_block, text=self.t("result.subtitle"),
            bg=Theme.SURFACE, fg=Theme.TEXT_MUTED, font=self.f_body,
        ).pack(anchor="w", pady=(2, 0))

        # Link box
        link_box = tk.Frame(
            view, bg=Theme.LINK_BG,
            highlightthickness=1, highlightbackground=Theme.BORDER_STRONG,
        )
        link_box.grid(row=1, column=0, sticky="we", pady=(28, 0))
        link_box.columnconfigure(0, weight=1)

        tk.Label(
            link_box, text=self.t("result.link_label"), bg=Theme.LINK_BG,
            fg=Theme.TEXT_DIM, font=self.f_eyebrow,
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 4))

        self.result_link_var = tk.StringVar()
        self.result_entry = tk.Entry(
            link_box, textvariable=self.result_link_var, bd=0,
            bg=Theme.LINK_BG, fg=Theme.LINK_FG, font=self.f_mono,
            readonlybackground=Theme.LINK_BG, state="readonly",
            insertbackground=Theme.LINK_FG,
        )
        self.result_entry.grid(row=1, column=0, sticky="we", padx=18, pady=(0, 14))

        copy_btn = FlatButton(
            link_box, self.t("result.copy"), self._copy_link,
            primary=False, font_obj=self.f_button, padx=18, pady=11,
        )
        copy_btn.grid(row=0, column=1, rowspan=2, padx=(0, 14), pady=14)

        # Status row
        status_box = tk.Frame(view, bg=Theme.CARD,
                              highlightthickness=1, highlightbackground=Theme.BORDER)
        status_box.grid(row=2, column=0, sticky="we", pady=(20, 0))
        status_box.columnconfigure(1, weight=1)

        tk.Label(
            status_box, text=self.t("result.status_label"), bg=Theme.CARD,
            fg=Theme.TEXT_DIM, font=self.f_eyebrow,
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 0))

        self.result_status_label = tk.Label(
            status_box,
            text=f"●  {self.t('state.new')}  –  {self.t('result.status_waiting')}",
            bg=Theme.CARD, fg=Theme.ACCENT, font=self.f_body_strong,
        )
        self.result_status_label.grid(row=1, column=0, columnspan=2, sticky="w",
                                       padx=18, pady=(4, 14))

        FlatButton(
            status_box, self.t("result.status_check"), self._check_last_status,
            primary=False, font_obj=self.f_caption, padx=14, pady=8,
        ).grid(row=0, column=1, rowspan=2, sticky="e", padx=(0, 14), pady=14)

        # Warning hint
        tk.Label(
            view, text=self.t("result.warning"),
            bg=Theme.SURFACE, fg=Theme.WARNING_FG, font=self.f_caption,
            wraplength=640, justify="left",
        ).grid(row=3, column=0, sticky="w", pady=(18, 0))

        # Action row
        actions = tk.Frame(view, bg=Theme.SURFACE)
        actions.grid(row=4, column=0, sticky="we", pady=(28, 0))
        actions.columnconfigure(1, weight=1)

        self.result_burn_btn = FlatButton(
            actions, self.t("burn.action"), self._burn_last_secret,
            primary=False, ghost=True, font_obj=self.f_button, padx=18, pady=12,
        )
        self.result_burn_btn.grid(row=0, column=0, sticky="w")

        FlatButton(
            actions, self.t("result.new"), self._reset_to_form,
            primary=True, font_obj=self.f_button, padx=24, pady=12,
        ).grid(row=0, column=2, sticky="e")

        return view

    def _show_send_view(self, view: str) -> None:
        for v in self._send_views.values():
            v.pack_forget()
        self._send_views[view].pack(fill="both", expand=True)
        self._send_view = view

    # ---- History section ----

    def _build_history_section(self, parent: tk.Misc) -> tk.Frame:
        section = tk.Frame(parent, bg=Theme.SURFACE)

        head = tk.Frame(section, bg=Theme.SURFACE)
        head.pack(fill="x", padx=46, pady=(40, 28))

        title_block = tk.Frame(head, bg=Theme.SURFACE)
        title_block.pack(side="left")
        tk.Label(
            title_block, text=self.t("history.eyebrow"), bg=Theme.SURFACE,
            fg=Theme.TEXT_DIM, font=self.f_eyebrow,
        ).pack(anchor="w")
        tk.Label(
            title_block, text=self.t("history.title"),
            bg=Theme.SURFACE, fg=Theme.TEXT, font=self.f_title,
        ).pack(anchor="w", pady=(4, 0))
        self.history_count_label = tk.Label(
            title_block, text=self.t("history.count_many", n=0),
            bg=Theme.SURFACE, fg=Theme.TEXT_MUTED, font=self.f_body,
        )
        self.history_count_label.pack(anchor="w", pady=(8, 0))

        actions = tk.Frame(head, bg=Theme.SURFACE)
        actions.pack(side="right", anchor="ne", pady=(28, 0))
        FlatButton(
            actions, self.t("history.clear"), self._clear_history,
            ghost=True, font_obj=self.f_caption, padx=14, pady=8,
        ).pack(side="right", padx=(8, 0))
        FlatButton(
            actions, self.t("history.refresh_all"), self._refresh_all_history,
            primary=False, font_obj=self.f_caption, padx=14, pady=8,
        ).pack(side="right")

        # Scrollable list
        list_wrap = tk.Frame(section, bg=Theme.SURFACE)
        list_wrap.pack(fill="both", expand=True, padx=46, pady=(0, 40))

        canvas = tk.Canvas(list_wrap, bg=Theme.SURFACE, highlightthickness=0, bd=0)
        scrollbar = ThinScrollbar(list_wrap, command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y", padx=(4, 0))

        inner = tk.Frame(canvas, bg=Theme.SURFACE)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _sync(_e: Optional[tk.Event] = None) -> None:
            canvas.update_idletasks()
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=bbox)

        def _on_canvas_resize(e: tk.Event) -> None:
            canvas.itemconfigure(win, width=e.width)
            _sync()

        inner.bind("<Configure>", _sync)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _wheel(e: tk.Event) -> None:
            canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        self._history_canvas = canvas
        self._history_container = inner

        return section

    # ---- Settings section ----

    def _build_settings_section(self, parent: tk.Misc) -> tk.Frame:
        section = tk.Frame(parent, bg=Theme.SURFACE)

        # Header
        head = tk.Frame(section, bg=Theme.SURFACE)
        head.pack(fill="x", padx=46, pady=(40, 28))
        tk.Label(
            head, text=self.t("settings.eyebrow"), bg=Theme.SURFACE,
            fg=Theme.TEXT_DIM, font=self.f_eyebrow,
        ).pack(anchor="w")
        tk.Label(
            head, text=self.t("settings.title"),
            bg=Theme.SURFACE, fg=Theme.TEXT, font=self.f_title,
        ).pack(anchor="w", pady=(4, 0))
        tk.Label(
            head, text=self.t("settings.subtitle"),
            bg=Theme.SURFACE, fg=Theme.TEXT_MUTED, font=self.f_body,
        ).pack(anchor="w", pady=(8, 0))

        # Scrollable form
        wrap = tk.Frame(section, bg=Theme.SURFACE)
        wrap.pack(fill="both", expand=True, padx=46, pady=(0, 40))

        canvas = tk.Canvas(wrap, bg=Theme.SURFACE, highlightthickness=0, bd=0)
        sb = ThinScrollbar(wrap, command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y", padx=(4, 0))

        form = tk.Frame(canvas, bg=Theme.SURFACE)
        win = canvas.create_window((0, 0), window=form, anchor="nw")

        def _sync_sb(_e: Optional[tk.Event] = None) -> None:
            canvas.update_idletasks()
            bbox = canvas.bbox("all")
            if bbox:
                canvas.configure(scrollregion=bbox)

        def _on_canvas_resize(e: tk.Event) -> None:
            canvas.itemconfigure(win, width=e.width)
            _sync_sb()

        form.bind("<Configure>", _sync_sb)
        canvas.bind("<Configure>", _on_canvas_resize)

        def _wheel(e: tk.Event) -> None:
            canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        # ---- Form widgets ----

        url_var = tk.StringVar(value=self.settings.api_url)
        user_var = tk.StringVar(value=self.settings.api_user)
        key_var = tk.StringVar(value=self.settings.api_key)
        timeout_var = tk.StringVar(value=str(self.settings.request_timeout))
        region_var = tk.StringVar(value=self.settings.region)
        lang_var = tk.StringVar(value=self.lang)
        ttl_var = tk.StringVar(value=self.settings.default_ttl)

        # Region
        self._field_eyebrow(form, self.t("settings.region")).pack(anchor="w", pady=(4, 8))
        region_options = [(k, label) for k, (label, _host) in REGIONS.items()]
        region_pills = self._build_option_pills(form, region_options, region_var)
        region_pills.pack(anchor="w")

        # API URL
        self._field_eyebrow(form, self.t("settings.url")).pack(anchor="w", pady=(22, 8))
        url_wrap, url_entry = self._make_entry(form)
        url_entry.configure(textvariable=url_var)
        url_wrap.pack(fill="x")

        def _on_region_change() -> None:
            new_region = region_var.get()
            if new_region != "custom":
                url_var.set(build_api_url(new_region))

        region_pills.bind_change(_on_region_change)

        # User
        self._field_eyebrow(form, self.t("settings.user")).pack(anchor="w", pady=(22, 8))
        user_wrap, user_entry = self._make_entry(form)
        user_entry.configure(textvariable=user_var)
        user_wrap.pack(fill="x")

        # Key
        self._field_eyebrow(form, self.t("settings.key")).pack(anchor="w", pady=(22, 8))
        key_row = tk.Frame(form, bg=Theme.SURFACE)
        key_row.pack(fill="x")
        key_row.columnconfigure(0, weight=1)
        key_wrap, key_entry = self._make_entry(key_row)
        key_entry.configure(textvariable=key_var, show="●")
        key_wrap.grid(row=0, column=0, sticky="we")

        toggle_btn = FlatButton(
            key_row, self.t("settings.show"),
            on_click=lambda: None,  # set below
            primary=False, font_obj=self.f_caption, padx=14, pady=10,
        )

        def _toggle_key_visible() -> None:
            current_show = key_entry.cget("show")
            if current_show:
                key_entry.configure(show="")
                toggle_btn.set_text(self.t("settings.hide"))
            else:
                key_entry.configure(show="●")
                toggle_btn.set_text(self.t("settings.show"))
        toggle_btn._on_click = _toggle_key_visible  # type: ignore[attr-defined]
        toggle_btn.grid(row=0, column=1, sticky="e", padx=(8, 0))

        # Keyring info
        keyring_msg = (self.t("settings.keyring_yes")
                       if self.settings_store.keyring_available
                       else self.t("settings.keyring_no"))
        keyring_color = Theme.SUCCESS_FG if self.settings_store.keyring_available else Theme.WARNING_FG
        tk.Label(
            form, text=keyring_msg, bg=Theme.SURFACE, fg=keyring_color,
            font=self.f_caption, justify="left", anchor="w", wraplength=620,
        ).pack(anchor="w", pady=(8, 0))

        # Language
        self._field_eyebrow(form, self.t("settings.language")).pack(anchor="w", pady=(28, 8))
        lang_options = [(k, label) for k, label in LANGUAGES]
        lang_pills = self._build_option_pills(form, lang_options, lang_var)
        lang_pills.pack(anchor="w")

        # Default TTL
        self._field_eyebrow(form, self.t("settings.default_ttl")).pack(anchor="w", pady=(28, 8))
        ttl_options = [(p.key, p.label(self.lang)) for p in PRESETS]
        ttl_pills = self._build_option_pills(form, ttl_options, ttl_var)
        ttl_pills.pack(anchor="w")

        # Advanced
        tk.Frame(form, bg=Theme.BORDER, height=1).pack(fill="x", pady=(32, 18))
        self._field_eyebrow(form, self.t("settings.advanced")).pack(anchor="w")

        self._field_eyebrow(form, self.t("settings.timeout")).pack(anchor="w", pady=(18, 8))
        timeout_wrap, timeout_entry = self._make_entry(form)
        timeout_entry.configure(textvariable=timeout_var, width=10)
        timeout_wrap.pack(anchor="w")

        # Buttons
        actions = tk.Frame(form, bg=Theme.SURFACE)
        actions.pack(fill="x", pady=(36, 0))
        actions.columnconfigure(0, weight=1)

        FlatButton(
            actions, self.t("settings.reset"),
            on_click=lambda: self._reset_settings(),
            ghost=True, font_obj=self.f_button, padx=18, pady=11,
        ).pack(side="left")

        self.test_btn = FlatButton(
            actions, self.t("settings.test"),
            on_click=lambda: self._test_connection(
                url_var.get().strip(), user_var.get().strip(), key_var.get(),
            ),
            primary=False, font_obj=self.f_button, padx=18, pady=11,
        )
        self.test_btn.pack(side="left", padx=(10, 0))

        FlatButton(
            actions, self.t("settings.save"),
            on_click=lambda: self._save_settings(
                url_var.get().strip(),
                user_var.get().strip(),
                key_var.get(),
                region_var.get(),
                lang_var.get(),
                timeout_var.get().strip(),
                ttl_var.get(),
            ),
            primary=True, font_obj=self.f_button, padx=22, pady=11,
        ).pack(side="right")

        return section

    def _build_option_pills(
        self,
        parent: tk.Misc,
        options: list[tuple[str, str]],
        var: tk.StringVar,
    ) -> tk.Frame:
        bar = tk.Frame(parent, bg=Theme.SURFACE)
        labels: dict[str, tk.Label] = {}
        change_callbacks: list[Callable[[], None]] = []

        def refresh() -> None:
            current = var.get()
            for key, lbl in labels.items():
                if key == current:
                    lbl.configure(bg=Theme.ACCENT_DIM, fg=Theme.ACCENT)
                else:
                    lbl.configure(bg=Theme.SURFACE, fg=Theme.TEXT_MUTED)

        def select(key: str) -> None:
            var.set(key)
            refresh()
            for cb in change_callbacks:
                try:
                    cb()
                except Exception:
                    logger.exception("option pill callback failed")

        for key, label in options:
            pill = tk.Label(
                bar, text=label, bg=Theme.SURFACE, fg=Theme.TEXT_MUTED,
                font=("Segoe UI", 9), padx=14, pady=7, cursor="hand2",
            )
            pill.pack(side="left", padx=(0, 6))
            pill.bind("<Button-1>", lambda _e, k=key: select(k))

            def hover(label_widget: tk.Label, k: str, entering: bool) -> None:
                if k == var.get():
                    return
                label_widget.configure(
                    bg=Theme.CARD if entering else Theme.SURFACE,
                    fg=Theme.TEXT if entering else Theme.TEXT_MUTED,
                )
            pill.bind("<Enter>", lambda _e, w=pill, k=key: hover(w, k, True))
            pill.bind("<Leave>", lambda _e, w=pill, k=key: hover(w, k, False))
            labels[key] = pill

        bar.bind_change = lambda cb: change_callbacks.append(cb)  # type: ignore[attr-defined]
        refresh()
        return bar

    def _save_settings(
        self,
        url: str,
        user: str,
        key: str,
        region: str,
        language: str,
        timeout_str: str,
        default_ttl: str,
    ) -> None:
        try:
            timeout = int(timeout_str or REQUEST_TIMEOUT_SECONDS)
            if timeout <= 0:
                timeout = REQUEST_TIMEOUT_SECONDS
        except ValueError:
            timeout = REQUEST_TIMEOUT_SECONDS

        # Region != custom: URL auto-bestimmen.
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
            self.settings_store.save(new_settings)
        except OSError as exc:
            self._show_toast(str(exc), ok=False)
            return

        self._apply_settings(self.settings_store.current)
        self._rebuild_ui(stay_on="settings")
        self._show_toast(self.t("settings.saved"), ok=True)

    def _reset_settings(self) -> None:
        defaults = Settings.defaults()
        try:
            self.settings_store.save(defaults)
        except OSError as exc:
            self._show_toast(str(exc), ok=False)
            return
        self._apply_settings(self.settings_store.current)
        self._rebuild_ui(stay_on="settings")
        self._show_toast(self.t("settings.reset_done"), ok=True)

    def _rebuild_ui(self, *, stay_on: Optional[str] = None) -> None:
        if stay_on:
            self._current_section = stay_on
        for w in (self._sidebar_frame, self._divider_frame, self._main_frame):
            if w is not None:
                # Widget may already be destroyed by Tk teardown; best-effort cleanup.
                with suppress(Exception):
                    w.destroy()
        if hasattr(self, "toast"):
            # Toast may already be gone; best-effort cleanup.
            with suppress(Exception):
                self.toast.destroy()
        self._nav_items.clear()
        self._sections.clear()
        self._send_views.clear()
        self._last_metadata_identifier = ""
        self._build_ui()

    def _render_history(self) -> None:
        for w in self._history_container.winfo_children():
            w.destroy()

        entries = self.history.entries()
        n = len(entries)
        if hasattr(self, "history_count_label"):
            key = "history.count_one" if n == 1 else "history.count_many"
            self.history_count_label.configure(text=self.t(key, n=n))

        if not entries:
            empty = tk.Frame(self._history_container, bg=Theme.SURFACE)
            empty.pack(fill="x", pady=80)
            tk.Label(
                empty, text="—", bg=Theme.SURFACE, fg=Theme.TEXT_DIM,
                font=("Segoe UI", 32),
            ).pack()
            tk.Label(
                empty, text=self.t("history.empty_title"),
                bg=Theme.SURFACE, fg=Theme.TEXT_MUTED, font=self.f_h2,
            ).pack(pady=(14, 4))
            tk.Label(
                empty, text=self.t("history.empty_sub"),
                bg=Theme.SURFACE, fg=Theme.TEXT_DIM, font=self.f_body,
            ).pack()
        else:
            for entry in entries:
                self._make_history_row(self._history_container, entry).pack(
                    fill="x", pady=(0, 1),
                )

        self._history_container.update_idletasks()
        bbox = self._history_canvas.bbox("all")
        if bbox:
            self._history_canvas.configure(scrollregion=bbox)

    def _make_history_row(self, parent: tk.Misc, entry: HistoryEntry) -> tk.Frame:
        row = tk.Frame(
            parent, bg=Theme.CARD,
            highlightthickness=1, highlightbackground=Theme.BORDER,
        )
        row.columnconfigure(2, weight=1)

        state_color, state_label = self._state_visual(entry.last_state)

        # Status dot column
        dot = tk.Label(
            row, text="●", bg=Theme.CARD, fg=state_color,
            font=("Segoe UI", 12),
        )
        dot.grid(row=0, column=0, rowspan=2, sticky="ns", padx=(20, 0))

        # State eyebrow
        tk.Label(
            row, text=state_label.upper(), bg=Theme.CARD, fg=state_color,
            font=self.f_eyebrow,
        ).grid(row=0, column=1, sticky="w", padx=(14, 0), pady=(14, 0))

        # Time (primary line)
        tk.Label(
            row, text=self._format_time(entry.created_at),
            bg=Theme.CARD, fg=Theme.TEXT, font=self.f_body_strong,
        ).grid(row=0, column=2, sticky="w", padx=(14, 14), pady=(14, 0))

        # Actions
        actions = tk.Frame(row, bg=Theme.CARD)
        actions.grid(row=0, column=3, rowspan=2, sticky="e", padx=(0, 14), pady=10)
        FlatButton(
            actions, self.t("history.row.status"),
            lambda i=entry.metadata_identifier: self._refresh_history_entry(i),
            primary=False, font_obj=self.f_caption, padx=12, pady=6,
        ).pack(side="left", padx=2)
        FlatButton(
            actions, self.t("history.row.link"),
            lambda k=entry.metadata_key: self._copy_metadata_link(k),
            primary=False, font_obj=self.f_caption, padx=12, pady=6,
        ).pack(side="left", padx=2)
        if self._is_burnable(entry.last_state):
            FlatButton(
                actions, self.t("history.row.burn"),
                lambda i=entry.metadata_identifier: self._burn_secret(i),
                primary=False, ghost=True, font_obj=self.f_caption, padx=12, pady=6,
            ).pack(side="left", padx=2)
        FlatButton(
            actions, "×",
            lambda i=entry.metadata_identifier: self._delete_history_entry(i),
            ghost=True, font_obj=self.f_caption, padx=10, pady=6,
        ).pack(side="left", padx=2)

        # Meta line
        meta_text = self._format_meta(entry)
        if meta_text:
            tk.Label(
                row, text=meta_text, bg=Theme.CARD, fg=Theme.TEXT_MUTED,
                font=self.f_caption, justify="left", anchor="w",
            ).grid(row=1, column=1, columnspan=2, sticky="w",
                   padx=(14, 14), pady=(4, 14))
        else:
            tk.Frame(row, bg=Theme.CARD, height=14).grid(row=1, column=1, sticky="we")

        return row

    def _state_visual(self, state: str) -> tuple[str, str]:
        s = (state or "").lower()
        color_map = {
            "new":       Theme.ACCENT,
            "shared":    Theme.ACCENT,
            "previewed": Theme.WARNING_FG,
            "revealed":  Theme.SUCCESS_FG,
            "burned":    Theme.SUCCESS_FG,
            "expired":   Theme.TEXT_DIM,
            "orphaned":  Theme.ERROR_FG,
            "unknown":   Theme.ERROR_FG,
            "":          Theme.ERROR_FG,
        }
        color = color_map.get(s, Theme.TEXT_MUTED)
        label_key = f"state.{s}" if s else "state.unknown"
        label = t(label_key, self.lang) if label_key in STRINGS else (s or self.t("state.unknown"))
        return color, label

    @staticmethod
    def _format_time(iso_str: str) -> str:
        try:
            dt = datetime.fromisoformat(iso_str)
        except ValueError:
            return iso_str
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone().strftime("%d.%m.%Y  %H:%M")

    def _format_meta(self, entry: HistoryEntry) -> str:
        bits: list[str] = []
        if entry.recipient:
            bits.append(self.t("history.meta.to", recipient=entry.recipient))
        ttl = self._ttl_label(entry)
        if ttl:
            bits.append(self.t("history.meta.ttl", ttl=ttl))
        if entry.last_checked and entry.last_checked != entry.created_at:
            bits.append(self.t("history.meta.checked", time=self._format_time(entry.last_checked)))
        return "    ·    ".join(bits)

    def _ttl_label(self, entry: HistoryEntry) -> str:
        """Die Sekunden sind die verlässliche Angabe; das gespeicherte Label ist nur
        der Fallback für Einträge aus älteren Versionen."""
        preset = preset_for_seconds(entry.ttl_seconds)
        if preset:
            return preset.label(self.lang)
        legacy = LEGACY_TTL_LABELS.get(entry.ttl_label)
        return preset_for_key(legacy).label(self.lang) if legacy else entry.ttl_label

    # ---- Toast ----

    def _build_toast(self) -> None:
        self.toast = tk.Label(
            self, text="", bg=Theme.SUCCESS_BG, fg=Theme.SUCCESS_FG,
            padx=18, pady=11, font=self.f_body,
            highlightthickness=1, highlightbackground=Theme.SUCCESS_BORDER,
        )
        self.toast.place_forget()

    def _show_toast(self, text: str, *, ok: bool, duration: int = 2800) -> None:
        bg = Theme.SUCCESS_BG if ok else Theme.ERROR_BG
        fg = Theme.SUCCESS_FG if ok else Theme.ERROR_FG
        border = Theme.SUCCESS_BORDER if ok else Theme.ERROR_BORDER
        self.toast.configure(text=text, bg=bg, fg=fg,
                             highlightbackground=border, highlightcolor=border)
        self.toast.place(relx=0.5, rely=1.0, anchor="s", y=-22)
        self.toast.lift()
        if self._toast_job is not None:
            # Scheduled callback may have already fired; ignore.
            with suppress(Exception):
                self.after_cancel(self._toast_job)
        self._toast_job = self.after(duration, self.toast.place_forget)

    # ---- Form helpers ----

    def _field_eyebrow(self, parent: tk.Misc, text: str, *, optional: bool = False) -> tk.Frame:
        row = tk.Frame(parent, bg=parent["bg"])
        tk.Label(
            row, text=text.upper(), bg=parent["bg"],
            fg=Theme.TEXT_MUTED, font=self.f_eyebrow,
        ).pack(side="left")
        if optional:
            tk.Label(
                row, text="  ·  OPTIONAL", bg=parent["bg"],
                fg=Theme.TEXT_DIM, font=self.f_eyebrow,
            ).pack(side="left")
        return row

    def _make_entry(self, parent: tk.Misc) -> tuple[tk.Frame, tk.Entry]:
        wrap = tk.Frame(
            parent, bg=Theme.INPUT_BG,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
            highlightcolor=Theme.BORDER_FOCUS,
        )
        entry = tk.Entry(
            wrap, bd=0, relief="flat",
            bg=Theme.INPUT_BG, fg=Theme.TEXT,
            insertbackground=Theme.ACCENT,
            selectbackground=Theme.ACCENT_DIM, selectforeground=Theme.TEXT,
            font=self.f_body,
        )
        entry.pack(fill="x", padx=14, pady=11)
        entry.bind("<FocusIn>", lambda _e: wrap.configure(highlightbackground=Theme.BORDER_FOCUS))
        entry.bind("<FocusOut>", lambda _e: wrap.configure(highlightbackground=Theme.BORDER))
        return wrap, entry

    # ---- Events ----

    def _on_text_modified(self, _event: tk.Event) -> None:
        if not self.txt.edit_modified():
            return
        text_content = self.txt.get("1.0", "end-1c")
        count = len(text_content)
        formatted = f"{count:,}".replace(",", ".")
        self.counter_label.configure(
            text=self.t("send.chars", n=formatted),
            fg=Theme.TEXT_MUTED if count > 0 else Theme.TEXT_DIM,
        )
        self.txt.edit_modified(False)

    def _reset_to_form(self) -> None:
        self.txt.delete("1.0", "end")
        self.entry_empf.delete(0, "end")
        self.result_link_var.set("")
        self._last_metadata_identifier = ""
        self._on_text_modified(tk.Event())
        self._show_send_view("form")
        self.txt.focus_set()

    def _copy_link(self) -> None:
        link = self.result_link_var.get()
        if not link:
            return
        self.clipboard_clear()
        self.clipboard_append(link)
        self.update_idletasks()
        self._show_toast(self.t("result.copied"), ok=True)

    def _check_last_status(self) -> None:
        identifier = self._last_metadata_identifier
        if not identifier:
            self._show_toast(self.t("result.no_status"), ok=False)
            return
        self._refresh_history_entry(identifier, also_update_result=True)

    # ---- Burn ----

    TERMINAL_STATES = frozenset({"burned", "revealed", "expired", "orphaned"})

    def _is_burnable(self, state: str) -> bool:
        return (state or "").lower() not in self.TERMINAL_STATES

    def _burn_last_secret(self) -> None:
        identifier = self._last_metadata_identifier
        if not identifier:
            self._show_toast(self.t("result.no_status"), ok=False)
            return
        self._burn_secret(identifier, from_result=True)

    def _burn_secret(self, identifier: str, *, from_result: bool = False) -> None:
        if not identifier:
            self._show_toast(self.t("error.no_id"), ok=False)
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
            # Ohne diesen Zweig stirbt der Thread still und der Button bliebe
            # dauerhaft auf "Verbrenne …" stehen.
            logger.exception("Unerwarteter Fehler beim Verbrennen")
            message = self.t("error.unexpected", error=exc)
            self.after(0, lambda: self._on_burn_failed(message, from_result))
            return
        self.after(0, lambda: self._on_burned(identifier, new_state, from_result))

    def _on_burned(self, identifier: str, new_state: str, from_result: bool) -> None:
        self.history.update_state(identifier, new_state)
        self._show_toast(self.t("burn.done"), ok=True, duration=4000)
        if from_result:
            self.result_burn_btn.set_text(self.t("burn.action"))
            color, label = self._state_visual(new_state)
            self.result_status_label.configure(text=f"●  {label}", fg=color)
        if self._current_section == "history":
            self._render_history()

    def _on_burn_failed(self, message: str, from_result: bool) -> None:
        if from_result:
            self.result_burn_btn.set_text(self.t("burn.action"))
            self.result_burn_btn.set_enabled(True)
        self._show_toast(self.t("burn.failed", error=message), ok=False, duration=5000)

    # ---- Connection test ----

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
            self._show_toast(self.t("settings.test_fail", error=error), ok=False, duration=5000)
            return
        if info.authenticated:
            msg = self.t("settings.test_ok_full", version=info.version, status=info.status)
        else:
            msg = self.t("settings.test_ok_anon", version=info.version)
        self._show_toast(msg, ok=True, duration=4000)

    # ---- History actions ----

    def _refresh_history_entry(self, identifier: str, *, also_update_result: bool = False) -> None:
        if not identifier:
            return
        threading.Thread(
            target=self._refresh_history_entry_worker,
            args=(self.client, identifier, also_update_result),
            daemon=True,
        ).start()

    def _refresh_history_entry_worker(
        self, client: OTSClient, identifier: str, also_update_result: bool,
    ) -> None:
        try:
            new_state = client.fetch_status(identifier)
        except OTSError as exc:
            message = self._error_text(exc)
            self.after(0, lambda: self._show_toast(message, ok=False, duration=5000))
            return
        except Exception as exc:
            logger.exception("Unerwarteter Fehler beim Status-Refresh")
            message = self.t("error.unexpected", error=exc)
            self.after(0, lambda: self._show_toast(message, ok=False, duration=5000))
            return
        self.after(0, lambda: self._on_state_refreshed(identifier, new_state, also_update_result))

    def _on_state_refreshed(self, identifier: str, new_state: str, update_result: bool) -> None:
        self.history.update_state(identifier, new_state)
        color, label = self._state_visual(new_state)
        self._show_toast(f"{self.t('result.status_label').title()}: {label}", ok=True)
        if self._current_section == "history":
            self._render_history()
        if update_result and identifier == self._last_metadata_identifier:
            self.result_status_label.configure(
                text=f"●  {label}", fg=color,
            )

    def _refresh_all_history(self) -> None:
        identifiers = [e.metadata_identifier for e in self.history.entries() if e.metadata_identifier]
        if not identifiers:
            self._show_toast(self.t("history.empty"), ok=True)
            return
        self._show_toast(self.t("history.refreshing", n=len(identifiers)), ok=True, duration=1500)
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
            color, label = self._state_visual(new_state)
            self.result_status_label.configure(text=f"●  {label}", fg=color)

    def _on_refresh_all_done(self, total: int, failed: int) -> None:
        if self._current_section == "history":
            self._render_history()
        if failed:
            self._show_toast(
                self.t("history.refresh_done", ok=total - failed, total=total, failed=failed),
                ok=False, duration=4000,
            )

    def _copy_metadata_link(self, metadata_key: str) -> None:
        if not metadata_key:
            return
        url = f"{self.metadata_base}/{metadata_key}"
        self.clipboard_clear()
        self.clipboard_append(url)
        self.update_idletasks()
        self._show_toast(self.t("history.copy_meta"), ok=True)

    def _delete_history_entry(self, identifier: str) -> None:
        self.history.remove(identifier)
        self._render_history()

    def _clear_history(self) -> None:
        self.history.clear()
        self._render_history()
        self._show_toast(self.t("history.cleared"), ok=True)

    def _save_to_history(
        self,
        result: ShareResult,
        recipient: Optional[str],
        ttl_label: str,
        ttl_seconds: int,
    ) -> None:
        now = datetime.now(UTC).isoformat(timespec="seconds")
        entry = HistoryEntry(
            created_at=now,
            recipient=recipient,
            ttl_label=ttl_label,
            ttl_seconds=ttl_seconds,
            metadata_key=result.metadata_key,
            metadata_identifier=result.metadata_identifier,
            # Bewusst die (unkritische) Receipt-shortid, nicht der Anfang des
            # Share-Tokens – die History liegt im Klartext auf der Platte.
            secret_preview=result.receipt_shortid,
            last_state=result.state,
            last_checked=now,
        )
        self.history.add(entry)
        if self._current_section == "history":
            self._render_history()

    # ---- Submit flow ----

    def _submit(self) -> None:
        if self._send_view != "form" or self._current_section != "send":
            return
        secret = self.txt.get("1.0", "end-1c").strip()
        if not secret:
            self._show_toast(self.t("send.empty"), ok=False)
            self.txt.focus_set()
            return

        recipient = self.entry_empf.get().strip()
        ttl_preset = self.pill_bar.selected_preset()

        self.submit_btn.set_enabled(False)
        self.submit_btn.set_text(self.t("send.sending"))
        self.progress.start(10)
        threading.Thread(
            target=self._request_thread,
            args=(self.client, secret, ttl_preset, recipient or None),
            daemon=True,
        ).start()

    def _request_thread(
        self, client: OTSClient, secret: str, ttl_preset: TTLPreset, recipient: Optional[str],
    ) -> None:
        try:
            result = client.share(secret, ttl_preset.seconds, recipient)
            # share_url stammt aus der Antwort (korrekt auch bei Custom Domains);
            # der aus dem API-Host gebaute Link ist nur der Fallback.
            secret_link = result.share_url or f"{self.link_base}/{result.secret_key}"
            self.after(0, lambda: self._on_success(secret_link, result, ttl_preset, recipient))
        except OTSError as exc:
            message = self._error_text(exc)
            self.after(0, lambda: self._on_error(message))
        except Exception as exc:
            logger.exception("Unerwarteter Fehler beim Senden")
            message = self.t("error.unexpected", error=exc)
            self.after(0, lambda: self._on_error(message))

    def _on_success(
        self,
        link: str,
        result: ShareResult,
        ttl_preset: TTLPreset,
        recipient: Optional[str],
    ) -> None:
        self.progress.stop()
        self.submit_btn.set_text(self.t("send.create"))
        self.submit_btn.set_enabled(True)

        self._last_metadata_identifier = result.metadata_identifier
        self.result_burn_btn.set_text(self.t("burn.action"))
        self.result_burn_btn.set_enabled(True)
        self.clipboard_clear()
        self.clipboard_append(link)
        self.update_idletasks()

        try:
            self._save_to_history(result, recipient, ttl_preset.key, ttl_preset.seconds)
        except Exception:
            logger.exception("History-Save fehlgeschlagen.")

        # Result-View befüllen
        self.result_link_var.set(link)
        self.result_entry.configure(state="normal")
        self.result_entry.selection_range(0, "end")
        self.result_entry.configure(state="readonly")

        color, label = self._state_visual(result.state)
        sub = self.t("result.status_waiting" if result.state == STATE_NEW else "result.status_history")
        self.result_status_label.configure(text=f"●  {label}  –  {sub}", fg=color)

        self._show_send_view("result")

        if result.state and result.state != STATE_NEW:
            logger.warning("Secret kommt bereits mit state=%s zurück", result.state)
            self._show_toast(self.t("warn.consumed", state=result.state),
                             ok=False, duration=5000)
        else:
            self._show_toast(self.t("result.copied"), ok=True)

    def _on_error(self, message: str) -> None:
        self.progress.stop()
        self.submit_btn.set_text(self.t("send.create"))
        self.submit_btn.set_enabled(True)
        self._show_toast(message, ok=False)


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
