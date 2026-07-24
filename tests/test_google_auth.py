from __future__ import annotations

import json

import pytest

from app import google_auth


def test_google_scope_is_drive_file_only():
    assert google_auth.SCOPES == [google_auth.DRIVE_FILE_SCOPE]
    assert google_auth.LEGACY_SPREADSHEETS_SCOPE not in google_auth.SCOPES


def test_picker_requests_one_spreadsheet():
    params = google_auth._authorization_params(pick_sheet=True)

    assert params["trigger_onepick"] == "true"
    assert params["allow_multiple"] == "false"
    assert params["mimetypes"] == google_auth.SHEETS_MIME_TYPE
    assert params["include_granted_scopes"] == "false"


def test_standard_sign_in_does_not_trigger_picker():
    params = google_auth._authorization_params(pick_sheet=False)

    assert "trigger_onepick" not in params
    assert params["include_granted_scopes"] == "false"


def test_picker_saves_credentials_and_returns_sheet(monkeypatch):
    class FakeCredentials:
        def to_json(self):
            return json.dumps({"token": "token", "scopes": google_auth.SCOPES})

    saved = {}
    monkeypatch.setattr(
        google_auth,
        "_run_local_flow",
        lambda pick_sheet: (FakeCredentials(), ["sheet-123"]),
    )
    monkeypatch.setattr(
        google_auth.secure_storage,
        "set",
        lambda key, value: saved.__setitem__(key, value),
    )

    assert google_auth.pick_google_sheet() == "sheet-123"
    assert saved["google_oauth_credentials"]["scopes"] == google_auth.SCOPES


def test_picker_rejects_missing_selection(monkeypatch):
    monkeypatch.setattr(
        google_auth,
        "_run_local_flow",
        lambda pick_sheet: (object(), []),
    )

    with pytest.raises(RuntimeError, match="No Google Sheet"):
        google_auth.pick_google_sheet()


def test_legacy_spreadsheets_token_requires_reauthorization(monkeypatch):
    monkeypatch.setattr(
        google_auth.secure_storage,
        "get",
        lambda key: {
            "token": "legacy",
            "scopes": [
                google_auth.DRIVE_FILE_SCOPE,
                google_auth.LEGACY_SPREADSHEETS_SCOPE,
            ],
        },
    )

    with pytest.raises(RuntimeError, match="drive.file only"):
        google_auth.get_credentials()


def test_loads_internal_client_configuration(monkeypatch, tmp_path):
    config_path = tmp_path / google_auth._BUNDLED_CLIENT_RESOURCE
    config_path.write_text(
        json.dumps({"installed": {"client_id": "test-id", "client_secret": "test-secret"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(google_auth, "_client_config_path", lambda: config_path)

    config = google_auth._load_client_config()

    assert config["installed"]["client_id"] == "test-id"


def test_frozen_build_uses_neutral_internal_resource(monkeypatch, tmp_path):
    resource = tmp_path / google_auth._BUNDLED_CLIENT_RESOURCE
    resource.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(google_auth.sys, "frozen", True, raising=False)
    monkeypatch.setattr(google_auth.sys, "_MEIPASS", str(tmp_path), raising=False)

    assert google_auth._client_config_path() == resource


def test_invalid_internal_client_configuration_is_rejected(monkeypatch, tmp_path):
    config_path = tmp_path / google_auth._BUNDLED_CLIENT_RESOURCE
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(google_auth, "_client_config_path", lambda: config_path)

    with pytest.raises(RuntimeError, match="invalid"):
        google_auth._load_client_config()
