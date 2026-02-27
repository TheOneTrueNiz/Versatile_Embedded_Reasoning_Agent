import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.oauth2.credentials import Credentials


GOOGLE_MCP_ROOT = (
    Path(__file__).resolve().parents[2] / "mcp_server_and_tools" / "google_workspace_mcp"
)
if str(GOOGLE_MCP_ROOT) not in sys.path:
    sys.path.append(str(GOOGLE_MCP_ROOT))

from auth import google_auth  # noqa: E402


class _DummyOAuthStore:
    def __init__(self, credentials: Credentials, user_email: str):
        self._credentials = credentials
        self._user_email = user_email

    def get_credentials_by_mcp_session(self, _session_id: str):
        return self._credentials

    def get_user_by_mcp_session(self, _session_id: str):
        return self._user_email

    def store_session(self, **_kwargs):
        return None


class _DummyCredentialStore:
    def __init__(self, credentials: Credentials):
        self._credentials = credentials
        self.requested_emails = []

    def get_credential(self, user_email: str):
        self.requested_emails.append(user_email)
        return self._credentials

    def store_credential(self, *_args, **_kwargs):
        return True

    def delete_credential(self, *_args, **_kwargs):
        return True

    def list_users(self):
        return []


def _expired_credentials(scopes):
    now_naive_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    creds = Credentials(
        token="expired_token",
        refresh_token="refresh_token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client_id",
        client_secret="client_secret",
        scopes=scopes,
        expiry=now_naive_utc - timedelta(hours=1),
    )
    return creds


def _valid_credentials(scopes):
    now_naive_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    return Credentials(
        token="valid_token",
        refresh_token="refresh_token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="client_id",
        client_secret="client_secret",
        scopes=scopes,
        expiry=now_naive_utc + timedelta(hours=1),
    )


def test_get_credentials_falls_back_after_oauth21_refresh_failure(monkeypatch):
    required_scopes = ["scope.a"]
    user_email = "jeffnyzio@gmail.com"
    session_id = "session-123"

    oauth_store = _DummyOAuthStore(
        credentials=_expired_credentials(required_scopes),
        user_email=user_email,
    )
    fallback_store = _DummyCredentialStore(_valid_credentials(required_scopes))

    load_session_calls = {"count": 0}

    def _load_credentials_from_session(_session_id):
        load_session_calls["count"] += 1
        return None

    monkeypatch.delenv("MCP_SINGLE_USER_MODE", raising=False)
    monkeypatch.setattr(google_auth, "get_oauth21_session_store", lambda: oauth_store)
    monkeypatch.setattr(google_auth, "get_credential_store", lambda: fallback_store)
    monkeypatch.setattr(
        google_auth, "load_credentials_from_session", _load_credentials_from_session
    )
    monkeypatch.setattr(google_auth, "is_stateless_mode", lambda: False)
    monkeypatch.setattr(
        Credentials,
        "refresh",
        lambda self, _request: (_ for _ in ()).throw(
            RuntimeError("simulated refresh failure")
        ),
    )

    credentials = google_auth.get_credentials(
        user_google_email=user_email,
        required_scopes=required_scopes,
        session_id=session_id,
    )

    assert credentials is not None
    assert credentials.token == "valid_token"
    assert fallback_store.requested_emails
    assert fallback_store.requested_emails[-1] == user_email
    assert load_session_calls["count"] == 0


def test_get_credentials_uses_mapped_user_email_for_fallback(monkeypatch):
    required_scopes = ["scope.a"]
    mapped_user_email = "jeffnyzio@gmail.com"

    oauth_store = _DummyOAuthStore(
        credentials=_expired_credentials(required_scopes),
        user_email=mapped_user_email,
    )
    fallback_store = _DummyCredentialStore(_valid_credentials(required_scopes))

    monkeypatch.delenv("MCP_SINGLE_USER_MODE", raising=False)
    monkeypatch.setattr(google_auth, "get_oauth21_session_store", lambda: oauth_store)
    monkeypatch.setattr(google_auth, "get_credential_store", lambda: fallback_store)
    monkeypatch.setattr(google_auth, "load_credentials_from_session", lambda _sid: None)
    monkeypatch.setattr(google_auth, "is_stateless_mode", lambda: False)
    monkeypatch.setattr(
        Credentials,
        "refresh",
        lambda self, _request: (_ for _ in ()).throw(
            RuntimeError("simulated refresh failure")
        ),
    )

    credentials = google_auth.get_credentials(
        user_google_email=None,
        required_scopes=required_scopes,
        session_id="session-456",
    )

    assert credentials is not None
    assert credentials.token == "valid_token"
    assert fallback_store.requested_emails
    assert fallback_store.requested_emails[-1] == mapped_user_email
