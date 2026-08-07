"""Per-user Google OAuth authentication stored with Windows DPAPI."""

from __future__ import annotations

import json
import sys
import os
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from wsgiref.simple_server import WSGIRequestHandler, make_server
from wsgiref.util import request_uri

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from . import secure_storage

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
LEGACY_SPREADSHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
SHEETS_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
SCOPES = [DRIVE_FILE_SCOPE]
_TOKEN_KEY = "google_oauth_credentials"
_BUNDLED_CLIENT_RESOURCE = "_tca_oauth.dat"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


class _OAuthCallback:
    def __init__(self):
        self.last_request_uri = ""

    def __call__(self, environ, start_response):
        self.last_request_uri = request_uri(environ)
        body = (
            "<html><body style='font-family:sans-serif;text-align:center;padding:3rem'>"
            "<h2>Google authorization complete</h2>"
            "<p>You can close this tab and return to Torn Company Assistant.</p>"
            "</body></html>"
        ).encode("utf-8")
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"),
                                  ("Content-Length", str(len(body)))])
        return [body]


def _authorization_params(pick_sheet: bool) -> dict:
    params = {
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "false",
    }
    if pick_sheet:
        params.update({
            "trigger_onepick": "true",
            "allow_multiple": "false",
            "mimetypes": SHEETS_MIME_TYPE,
        })
    return params


def _client_config_path() -> Path:
    # 1. Check if running frozen inside a standalone build
    if getattr(sys, "frozen", False):
        # 1a. PyInstaller bundle root
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            meipass_path = Path(meipass) / _BUNDLED_CLIENT_RESOURCE
            if meipass_path.is_file():
                return meipass_path
        # 1b. Nuitka unpacks bundled files directly into the directory containing the code modules
        bundle_root = Path(__file__).resolve().parent
        path = bundle_root / "client_secret.json"
        if path.is_file():
            return path
        raise RuntimeError("This production build is missing its internal Google OAuth configuration.")

    # 2. Local fallback branch for your standard development workflow
    matches = sorted(_PROJECT_ROOT.glob("client_secret_*.json"))
    if len(matches) == 1:
        return matches[0]
        
    exact_dev_file = _PROJECT_ROOT / "client_secret.json"
    if exact_dev_file.is_file():
        return exact_dev_file
        
    raise RuntimeError("The development OAuth configuration is missing or ambiguous.")


def _load_client_config() -> dict:
    try:
        config = json.loads(_client_config_path().read_text(encoding="utf-8"))
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("The internal Google OAuth configuration could not be loaded.") from exc
    installed = config.get("installed") if isinstance(config, dict) else None
    if not isinstance(installed, dict) or not installed.get("client_id") or not installed.get("client_secret"):
        raise RuntimeError("The internal Google OAuth configuration is invalid.")
    return config


def _save_credentials(credentials: Credentials) -> None:
    secure_storage.set(_TOKEN_KEY, json.loads(credentials.to_json()))


def _run_local_flow(pick_sheet: bool) -> tuple[Credentials, list[str]]:
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_config(_load_client_config(), SCOPES)
    callback = _OAuthCallback()
    server = make_server("localhost", 0, callback, handler_class=_QuietHandler)
    try:
        flow.redirect_uri = f"http://localhost:{server.server_port}/"
        auth_url, _ = flow.authorization_url(**_authorization_params(pick_sheet))
        webbrowser.open(auth_url, new=1, autoraise=True)
        server.timeout = 300
        server.handle_request()
        if not callback.last_request_uri:
            raise TimeoutError("Google authorization timed out. Try again from Settings.")
        query = parse_qs(urlsplit(callback.last_request_uri).query)
        if query.get("error"):
            raise RuntimeError("Google authorization was canceled or denied.")
        response = callback.last_request_uri.replace("http://", "https://", 1)
        flow.fetch_token(authorization_response=response)
    finally:
        server.server_close()
    picked = [value for value in query.get("picked_file_ids", [""])[0].split(",") if value]
    # pyrefly: ignore [bad-return]
    return flow.credentials, picked


def authorize() -> Credentials:
    credentials, _ = _run_local_flow(pick_sheet=False)
    _save_credentials(credentials)
    return credentials


def pick_google_sheet() -> str:
    credentials, picked = _run_local_flow(pick_sheet=True)
    if not picked:
        raise RuntimeError("No Google Sheet was selected.")
    _save_credentials(credentials)
    return picked[0]


def get_credentials() -> Credentials:
    """Load and refresh the current user's OAuth credentials."""
    info = secure_storage.get(_TOKEN_KEY)
    if not info:
        raise RuntimeError("Google is not connected. Open Settings and choose 'Sign in with Google'.")
    if LEGACY_SPREADSHEETS_SCOPE in set(info.get("scopes") or []):
        raise RuntimeError(
            "Google access must be updated to drive.file only. Open Settings and sign in again."
        )
    credentials = Credentials.from_authorized_user_info(info, SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        _save_credentials(credentials)
    if not credentials.valid:
        raise RuntimeError("Google authorization expired. Open Settings and sign in again.")
    return credentials
