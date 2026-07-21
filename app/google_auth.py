"""Per-user Google OAuth authentication stored with Windows DPAPI."""

from __future__ import annotations

import json
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from . import secure_storage

SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive.file"]
_TOKEN_KEY = "google_oauth_credentials"


def _save_credentials(credentials: Credentials) -> None:
    secure_storage.set(_TOKEN_KEY, json.loads(credentials.to_json()))


def authorize(client_config_file: str) -> Credentials:
    """Open the system browser and save the resulting refresh token securely."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    path = Path(client_config_file).expanduser()
    if not path.is_file():
        raise ValueError("Choose the OAuth desktop-client JSON file in Settings first.")
    flow = InstalledAppFlow.from_client_secrets_file(str(path), SCOPES)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    _save_credentials(credentials)
    return credentials


def get_credentials() -> Credentials:
    """Load and refresh the current user's OAuth credentials."""
    info = secure_storage.get(_TOKEN_KEY)
    if not info:
        raise RuntimeError("Google is not connected. Open Settings and choose 'Sign in with Google'.")
    credentials = Credentials.from_authorized_user_info(info, SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _save_credentials(credentials)
    if not credentials.valid:
        raise RuntimeError("Google authorization expired. Open Settings and sign in again.")
    return credentials
