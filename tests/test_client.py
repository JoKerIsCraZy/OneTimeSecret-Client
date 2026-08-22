"""OTSClient: Transport, Fehler-Envelope und Antwort-Mapping.

Kein Netzwerk – die Session wird durch ein Double ersetzt.
"""

from __future__ import annotations

import json
import threading
from typing import Optional

import pytest
import requests

import OneTimeSecret_Client as ots

API_URL = "https://eu.onetimesecret.com/api/v2/secret/conceal"


# ---- Test doubles ----------------------------------------------------------

def make_response(
    status: int = 200,
    payload: Optional[object] = None,
    *,
    body: bytes = b"",
    headers: Optional[dict] = None,
) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(payload).encode() if payload is not None else body
    response.headers.update(headers or {})
    return response


class FakeSession:
    """Ersetzt requests.Session – zeichnet Aufrufe auf und liefert vorbereitete Antworten."""

    def __init__(self, *responses: object) -> None:
        self._responses = list(responses) or [make_response(200, {})]
        self.calls: list[tuple[str, str, dict]] = []
        self.closed = False

    def request(self, method: str, url: str, **kwargs: object) -> requests.Response:
        self.calls.append((method, url, kwargs))
        item = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item()
        return item

    def close(self) -> None:
        self.closed = True


def make_client(*responses: object, user: str = "me@example.org", key: str = "secret-key") -> ots.OTSClient:
    client = ots.OTSClient(API_URL, user, key)
    client._session = FakeSession(*responses)  # type: ignore[assignment]
    return client


# ---- _request --------------------------------------------------------------

def test_request_sends_basic_auth_and_timeout() -> None:
    client = make_client(make_response(200, {"ok": True}))
    client._request("GET", "https://eu.onetimesecret.com/api/v2/status")
    _method, _url, kwargs = client._session.calls[0]
    assert kwargs["auth"] == ("me@example.org", "secret-key")
    assert kwargs["timeout"] == ots.REQUEST_TIMEOUT_SECONDS


def test_request_omits_auth_when_no_credentials() -> None:
    client = make_client(make_response(200, {}), user="", key="")
    client._request("GET", "https://eu.onetimesecret.com/api/v2/status", require_auth=False)
    assert client._session.calls[0][2]["auth"] is None


def test_request_without_credentials_raises_a_localisable_error() -> None:
    client = make_client(user="", key="")
    with pytest.raises(ots.OTSError) as excinfo:
        client._request("GET", "https://eu.onetimesecret.com/api/v2/receipt/abc")
    assert excinfo.value.error_type == ots.MISSING_CONFIG
    assert excinfo.value.message_key == "error.api_config"
    assert client._session.calls == []


def test_request_wraps_network_failures() -> None:
    client = make_client(requests.ConnectionError("boom"))
    with pytest.raises(ots.OTSError) as excinfo:
        client._request("GET", "https://eu.onetimesecret.com/api/v2/status")
    assert excinfo.value.message_key == "error.network"


def test_request_rejects_a_non_json_success_body() -> None:
    client = make_client(make_response(200, body=b"<html>nope</html>"))
    with pytest.raises(ots.OTSError) as excinfo:
        client._request("GET", "https://eu.onetimesecret.com/api/v2/status")
    assert excinfo.value.message_key == "error.invalid_json"


def test_request_normalises_a_non_object_json_body() -> None:
    client = make_client(make_response(200, [1, 2, 3]))
    assert client._request("GET", "https://eu.onetimesecret.com/api/v2/status") == {}


def test_request_rejects_credentials_that_cannot_be_sent() -> None:
    """Ein aus einer Tabelle kopierter API-Key schleppt gern ein Rahmenzeichen mit.
    requests wuerde daran erst tief im Stack mit einem UnicodeEncodeError sterben."""
    client = make_client(key="x" * 54 + "│" + "y")
    with pytest.raises(ots.OTSError) as excinfo:
        client._request("GET", "https://eu.onetimesecret.com/api/v2/receipt/abc")
    assert excinfo.value.message_key == "error.credentials_charset"
    assert client._session.calls == []


def test_request_rejects_a_non_latin1_user() -> None:
    client = make_client(user="│me@example.org")
    with pytest.raises(ots.OTSError) as excinfo:
        client._request("GET", "https://eu.onetimesecret.com/api/v2/receipt/abc")
    assert excinfo.value.message_key == "error.credentials_charset"


def test_accented_credentials_still_go_through() -> None:
    """latin-1 deckt Umlaute ab - die duerfen nicht mit abgelehnt werden."""
    client = make_client(make_response(200, {"ok": True}), user="jörg@example.org", key="schlüssel")
    assert client._request("GET", "https://eu.onetimesecret.com/api/v2/status") == {"ok": True}


def test_request_refuses_plain_http() -> None:
    """README verspricht HTTPS-only – eine http-URL aus den Settings darf nicht rausgehen."""
    client = ots.OTSClient("http://eu.onetimesecret.com/api/v2/secret/conceal", "me", "key")
    client._session = FakeSession()  # type: ignore[assignment]
    with pytest.raises(ots.OTSError) as excinfo:
        client._request("GET", "http://eu.onetimesecret.com/api/v2/status")
    assert excinfo.value.message_key == "error.insecure_url"
    assert client._session.calls == []


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_request_allows_plain_http_on_loopback(host: str) -> None:
    """Selbst gehostete Instanz auf dem eigenen Rechner bleibt testbar."""
    client = ots.OTSClient(f"http://{host}:3000/api/v2/secret/conceal", "me", "key")
    client._session = FakeSession(make_response(200, {"ok": True}))  # type: ignore[assignment]
    assert client._request("GET", f"http://{host}:3000/api/v2/status") == {"ok": True}


# ---- Fehler-Envelope -------------------------------------------------------

@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_map_to_a_credentials_message(status: int) -> None:
    error = ots.OTSClient._error_from_response(make_response(status, {"error": "nope"}))
    assert error.message_key == "error.auth"
    assert error.status_code == status


def test_not_found_maps_to_its_own_message() -> None:
    error = ots.OTSClient._error_from_response(make_response(404, {}))
    assert error.message_key == "error.not_found"


def test_rate_limit_carries_retry_after() -> None:
    error = ots.OTSClient._error_from_response(
        make_response(429, {}, headers={"Retry-After": "30"})
    )
    assert error.message_key == "error.rate_limit_retry"
    assert error.message_args == {"seconds": "30"}


def test_rate_limit_without_retry_after() -> None:
    error = ots.OTSClient._error_from_response(make_response(429, {}))
    assert error.message_key == "error.rate_limit"


def test_unprocessable_entity_keeps_the_server_message_and_field() -> None:
    error = ots.OTSClient._error_from_response(
        make_response(422, {"error": "ttl too large", "field": "ttl"})
    )
    assert error.message_key == "error.rejected_field"
    assert error.message_args["field"] == "ttl"
    assert "ttl too large" in str(error)


def test_server_error_falls_back_to_the_status_code() -> None:
    error = ots.OTSClient._error_from_response(make_response(500, {}))
    assert error.message_key == "error.http"
    assert error.message_args == {"code": 500}


def test_error_envelope_metadata_is_captured() -> None:
    error = ots.OTSClient._error_from_response(
        make_response(403, {"error_type": "AuthFailed", "request_id": "req-1", "error_id": "err-1"})
    )
    assert error.error_type == "AuthFailed"
    assert error.request_id == "req-1"


def test_non_json_error_body_still_produces_an_error() -> None:
    """Proxy-/Gateway-Fehlerseiten sind HTML – das darf nicht in einen Parser-Crash laufen."""
    error = ots.OTSClient._error_from_response(make_response(502, body=b"<html>bad gateway</html>"))
    assert error.status_code == 502
    assert error.message_key == "error.http"


def test_error_detail_is_not_repeated() -> None:
    error = ots.OTSClient._error_from_response(make_response(500, {"error": "kaputt"}))
    assert str(error).count("kaputt") == 1


# ---- Antwort-Mapping -------------------------------------------------------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (["0", "25", "11"], "0.25.11"),
        ("1.2.3", "1.2.3"),
        ({"version": "9.9"}, "9.9"),
        ({"commit": "abc123"}, "abc123"),
        (None, "?"),
        ([], "?"),
        ({}, "?"),
    ],
)
def test_format_version(raw: object, expected: str) -> None:
    assert ots.OTSClient._format_version(raw) == expected


def test_secret_state_wins_over_flags() -> None:
    data = {"record": {"secret_state": "received", "is_burned": True}}
    assert ots.OTSClient._state_from_receipt(data) == "received"


def test_terminal_flags_take_priority_over_softer_ones() -> None:
    data = {"record": {"is_burned": True, "is_previewed": True}}
    assert ots.OTSClient._state_from_receipt(data) == "burned"


def test_string_flags_are_honoured() -> None:
    assert ots.OTSClient._state_from_receipt({"record": {"is_revealed": "true"}}) == "revealed"


def test_receipt_state_is_only_the_last_resort() -> None:
    assert ots.OTSClient._state_from_receipt({"record": {"state": "shared"}}) == "shared"


def test_unmappable_receipt_is_unknown() -> None:
    assert ots.OTSClient._state_from_receipt({}) == "unknown"
    assert ots.OTSClient._state_from_receipt({"record": "not-a-dict"}) == "unknown"


def test_share_result_prefers_the_domain_from_the_response() -> None:
    """Custom-Domain-Accounts liefern eine andere Domain als der API-Host."""
    data = {
        "record": {
            "share_domain": "secrets.acme.example",
            "secret": {"key": "SECRETKEY"},
            "receipt": {"key": "METAKEY", "identifier": "META-ID", "shortid": "abc1234"},
        }
    }
    result = ots.OTSClient._share_result(data)
    assert result.share_url == "https://secrets.acme.example/secret/SECRETKEY"
    assert result.metadata_identifier == "META-ID"
    assert result.receipt_shortid == "abc1234"


def test_share_result_falls_back_through_key_aliases() -> None:
    data = {"record": {"secret": {"shortid": "s1"}, "receipt": {"shortid": "r1"}}}
    result = ots.OTSClient._share_result(data)
    assert result.secret_key == "s1"
    assert result.metadata_key == "r1"


def test_share_result_defaults_the_state_to_new() -> None:
    assert ots.OTSClient._share_result({}).state == ots.STATE_NEW


@pytest.mark.parametrize(
    "hostile",
    [
        "evil.example/path?next=",
        "user@evil.example",
        "evil.example#",
        "evil example",
        "evil.example/",
    ],
)
def test_share_result_rejects_a_malformed_share_domain(hostile: str) -> None:
    """Der Link geht in die Zwischenablage – eine vom Server gelieferte Domain,
    die kein reiner Host ist, darf ihn nicht umbiegen."""
    data = {"record": {"share_domain": hostile, "secret": {"key": "KEY"}, "receipt": {"key": "M"}}}
    result = ots.OTSClient._share_result(data)
    assert result.share_url == ""


def test_share_result_accepts_a_host_with_a_port() -> None:
    data = {"record": {"share_domain": "localhost:3000", "secret": {"key": "KEY"}, "receipt": {"key": "M"}}}
    assert ots.OTSClient._share_result(data).share_url == "https://localhost:3000/secret/KEY"


# ---- Öffentliche Operationen ----------------------------------------------

def test_share_posts_the_conceal_envelope() -> None:
    client = make_client(make_response(200, {
        "success": True,
        "record": {"secret": {"key": "SK"}, "receipt": {"key": "MK", "identifier": "MID"}},
    }))
    result = client.share("hello", 3600, recipient="you@example.org")
    method, url, kwargs = client._session.calls[0]
    assert (method, url) == ("POST", API_URL)
    assert kwargs["json"]["secret"]["ttl"] == 3600
    assert kwargs["json"]["secret"]["recipient"] == "you@example.org"
    assert result.secret_key == "SK"


def test_share_omits_an_empty_recipient() -> None:
    client = make_client(make_response(200, {"record": {"secret": {"key": "SK"}, "receipt": {"key": "MK"}}}))
    client.share("hello", 300, recipient=None)
    assert "recipient" not in client._session.calls[0][2]["json"]["secret"]


def test_share_rejects_a_response_without_keys() -> None:
    client = make_client(make_response(200, {"record": {}}))
    with pytest.raises(ots.OTSError) as excinfo:
        client.share("hello", 300)
    assert excinfo.value.message_key == "error.no_secret_key"


def test_share_without_a_url_is_a_config_error() -> None:
    client = ots.OTSClient("", "me", "key")
    client._session = FakeSession()  # type: ignore[assignment]
    with pytest.raises(ots.OTSError) as excinfo:
        client.share("hello", 300)
    assert excinfo.value.error_type == ots.MISSING_CONFIG


def test_fetch_status_hits_the_receipt_endpoint() -> None:
    client = make_client(make_response(200, {"record": {"secret_state": "received"}}))
    assert client.fetch_status("MID") == "received"
    assert client._session.calls[0][1] == "https://eu.onetimesecret.com/api/v2/receipt/MID"


def test_fetch_status_requires_an_identifier() -> None:
    client = make_client()
    with pytest.raises(ots.OTSError) as excinfo:
        client.fetch_status("")
    assert excinfo.value.message_key == "error.no_id"


def test_share_link_prefers_the_url_from_the_server() -> None:
    client = make_client(make_response(200, {"record": {
        "share_url": "https://eu.onetimesecret.com/secret/SK",
        "share_path": "secret/SK",
    }}))
    assert client.share_link("MID") == "https://eu.onetimesecret.com/secret/SK"
    assert client._session.calls[0][:2] == ("GET", "https://eu.onetimesecret.com/api/v2/receipt/MID")


def test_share_link_falls_back_to_the_path() -> None:
    """share_url fehlt bei manchen Deployments, share_path ist immer dabei."""
    client = make_client(make_response(200, {"record": {"share_path": "secret/SK"}}))
    assert client.share_link("MID") == "https://eu.onetimesecret.com/secret/SK"


@pytest.mark.parametrize(
    "hostile",
    ["http://evil.example/secret/SK", "javascript:alert(1)", "https://evil example/secret/SK"],
)
def test_share_link_rejects_a_malformed_server_url(hostile: str) -> None:
    """Der Link geht in die Zwischenablage - eine krumme Serverantwort darf ihn
    nicht umbiegen; dann zaehlt nur der Pfad auf dem konfigurierten Host."""
    client = make_client(make_response(200, {"record": {"share_url": hostile, "share_path": "secret/SK"}}))
    assert client.share_link("MID") == "https://eu.onetimesecret.com/secret/SK"


@pytest.mark.parametrize("flag", ["is_burned", "is_revealed", "is_expired"])
def test_share_link_reports_a_consumed_secret(flag: str) -> None:
    """Der Server gibt share_path auch nach dem Burn noch heraus - der Zustand
    entscheidet, sonst wandert ein toter Link in die Zwischenablage."""
    client = make_client(make_response(200, {"record": {flag: True, "share_path": "secret/SK"}}))
    with pytest.raises(ots.OTSError) as excinfo:
        client.share_link("MID")
    assert excinfo.value.message_key == "error.no_share_link"


def test_share_link_still_works_for_a_previewed_secret() -> None:
    """Angesehen, aber nicht abgerufen: der Link ist weiterhin gueltig."""
    client = make_client(make_response(200, {"record": {"is_previewed": True, "share_path": "secret/SK"}}))
    assert client.share_link("MID") == "https://eu.onetimesecret.com/secret/SK"


def test_share_link_requires_an_identifier() -> None:
    client = make_client()
    with pytest.raises(ots.OTSError) as excinfo:
        client.share_link("")
    assert excinfo.value.message_key == "error.no_id"


def test_burn_posts_and_reports_the_new_state() -> None:
    client = make_client(make_response(200, {"success": True, "record": {"is_burned": True}}))
    assert client.burn("MID") == "burned"
    method, url, _kwargs = client._session.calls[0]
    assert (method, url) == ("POST", "https://eu.onetimesecret.com/api/v2/receipt/MID/burn")


def test_burn_sends_the_continue_flag() -> None:
    """Ohne `continue` fuehrt der Server den Burn nicht aus: er antwortet mit
    HTTP 200 und success=false, und das Secret bleibt abrufbar."""
    client = make_client(make_response(200, {"success": True, "record": {"is_burned": True}}))
    client.burn("MID")
    assert client._session.calls[0][2]["json"] == {"continue": "true"}


def test_burn_reports_a_refused_burn_as_an_error() -> None:
    """success=false bei HTTP 200 - der haeufigste Weg, wie ein Burn stillschweigend
    nicht stattfindet."""
    client = make_client(make_response(200, {"success": False, "record": {"state": "new"}}))
    with pytest.raises(ots.OTSError) as excinfo:
        client.burn("MID")
    assert excinfo.value.message_key == "error.refused"


def test_burn_trusts_success_over_a_stale_record() -> None:
    """Die Burn-Antwort traegt den Datensatz von vor dem Burn: state bleibt 'new'
    und is_burned false. Erst der naechste GET zeigt is_burned=true."""
    client = make_client(make_response(200, {
        "success": True,
        "record": {"state": "new", "secret_state": None, "is_burned": False},
    }))
    assert client.burn("MID") == "burned"


def test_burn_keeps_a_terminal_state_from_the_response() -> None:
    client = make_client(make_response(200, {"success": True, "record": {"is_revealed": True}}))
    assert client.burn("MID") == "revealed"


def test_burn_assumes_burned_when_the_server_stays_vague() -> None:
    client = make_client(make_response(200, {}))
    assert client.burn("MID") == "burned"


def test_request_rejects_an_envelope_that_reports_failure() -> None:
    client = make_client(make_response(200, {"success": False}))
    with pytest.raises(ots.OTSError) as excinfo:
        client._request("POST", "https://eu.onetimesecret.com/api/v2/receipt/MID/burn")
    assert excinfo.value.message_key == "error.refused"


def test_request_accepts_an_envelope_without_a_success_flag() -> None:
    """/status und /version antworten ohne success-Feld - das ist kein Fehler."""
    client = make_client(make_response(200, {"status": "nominal"}))
    assert client._request("GET", "https://eu.onetimesecret.com/api/v2/status") == {"status": "nominal"}


def test_ping_reports_version_and_authentication() -> None:
    client = make_client(
        make_response(200, {"status": "nominal"}),
        make_response(200, {"version": ["0", "25", "11"]}),
        make_response(200, {"records": []}),
    )
    info = client.ping()
    assert (info.status, info.version, info.authenticated) == ("nominal", "0.25.11", True)


def test_ping_without_credentials_skips_the_authenticated_probe() -> None:
    client = make_client(
        make_response(200, {"status": "ok"}),
        make_response(200, {"version": "1.0"}),
        user="", key="",
    )
    info = client.ping()
    assert info.authenticated is False
    assert len(client._session.calls) == 2


# ---- Lebenszyklus ----------------------------------------------------------

def test_close_closes_an_idle_session() -> None:
    client = make_client()
    client.close()
    assert client._session.closed is True


def test_close_waits_for_an_in_flight_request() -> None:
    """Settings speichern tauscht den Client aus – ein laufender Request darf
    dabei nicht die Session unter sich weggezogen bekommen."""
    released = threading.Event()
    entered = threading.Event()

    def blocking_response() -> requests.Response:
        entered.set()
        released.wait(timeout=5)
        return make_response(200, {"ok": True})

    client = make_client(blocking_response)
    worker = threading.Thread(target=lambda: client._request("GET", "https://eu.onetimesecret.com/api/v2/status"))
    worker.start()
    assert entered.wait(timeout=5)

    client.close()
    assert client._session.closed is False, "session closed while a request was still running"

    released.set()
    worker.join(timeout=5)
    assert client._session.closed is True
