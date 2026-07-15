"""Windows DPAPI-backed storage for per-user application secrets.

The encrypted file is deliberately useless on another Windows account.  This
is appropriate for OAuth refresh tokens and API keys: users can copy the app,
but must sign in/configure their own credentials on each machine.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Knotty Oil Tracker"
SECRETS_PATH = APP_DATA_DIR / "secrets.dpapi"
_DESCRIPTION = "Knotty Oil Tracker local secrets"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Secure local credential storage is supported on Windows only.")
    source = ctypes.create_string_buffer(data)
    source_blob = _DataBlob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    encrypted_blob = _DataBlob()
    crypt_protect = ctypes.windll.crypt32.CryptProtectData
    crypt_protect.argtypes = [
        ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt_protect.restype = wintypes.BOOL
    if not crypt_protect(ctypes.byref(source_blob), _DESCRIPTION, None, None, None,
                         _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(encrypted_blob)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(encrypted_blob.pbData, encrypted_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(encrypted_blob.pbData)


def _unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Secure local credential storage is supported on Windows only.")
    source = ctypes.create_string_buffer(data)
    source_blob = _DataBlob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_byte)))
    plain_blob = _DataBlob()
    crypt_unprotect = ctypes.windll.crypt32.CryptUnprotectData
    crypt_unprotect.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt_unprotect.restype = wintypes.BOOL
    if not crypt_unprotect(ctypes.byref(source_blob), None, None, None, None,
                           _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(plain_blob)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(plain_blob.pbData, plain_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(plain_blob.pbData)


def load() -> dict:
    """Return the per-user secret dictionary, or an empty dictionary initially."""
    if not SECRETS_PATH.exists():
        return {}
    try:
        encoded = SECRETS_PATH.read_text(encoding="ascii")
        value = json.loads(_unprotect(base64.b64decode(encoded)).decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(
            "Could not decrypt local credentials. Sign in/configure the app again for this Windows user."
        ) from exc
    if not isinstance(value, dict):
        raise RuntimeError("Local credential storage has an invalid format.")
    return value


def save(values: dict) -> None:
    """Atomically replace the encrypted per-user secret dictionary."""
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    plaintext = json.dumps(values, separators=(",", ":")).encode("utf-8")
    encrypted = base64.b64encode(_protect(plaintext)).decode("ascii")
    temp_path = SECRETS_PATH.with_suffix(".tmp")
    temp_path.write_text(encrypted, encoding="ascii")
    os.replace(temp_path, SECRETS_PATH)


def get(name: str, default=None):
    return load().get(name, default)


def set(name: str, value) -> None:
    values = load()
    values[name] = value
    save(values)
