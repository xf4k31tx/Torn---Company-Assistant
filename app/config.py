"""Per-user app settings stored encrypted with Windows DPAPI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from . import secure_storage

_SETTINGS_KEY = "settings"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_ENV_PATH = PROJECT_ROOT / ".env"


@dataclass
class Settings:
    torn_api_key: str = ""
    tornstats_api_key: str = ""
    google_sheet_id: str = ""
    google_sheet_name: str = ""
    snapshot_interval_minutes: int = 30
    last_selected_company: str = ""
    employee_visible_columns: list[str] = field(default_factory=list)

    @classmethod
    def load(cls) -> "Settings":
        values = secure_storage.get(_SETTINGS_KEY, {})
        # One-way convenience migration: values are loaded from an existing
        # plaintext .env so the user can save them into DPAPI from Settings.
        # The plaintext file is never written by this version of the app.
        if not values and LEGACY_ENV_PATH.exists():
            legacy = dotenv_values(LEGACY_ENV_PATH)
            values = {
                "torn_api_key": legacy.get("TORN_API_KEY", ""),
                "tornstats_api_key": legacy.get("TORNSTATS_API_KEY", ""),
                "google_sheet_id": legacy.get("GOOGLE_SHEET_ID", ""),
                "google_sheet_name": legacy.get("GOOGLE_SHEET_NAME", ""),
                "snapshot_interval_minutes": legacy.get("SNAPSHOT_INTERVAL_MINUTES", 30),
                "last_selected_company": legacy.get("LAST_SELECTED_COMPANY", ""),
            }
        if not isinstance(values, dict):
            return cls()
        allowed = {key: values[key] for key in cls.__dataclass_fields__ if key in values}
        try:
            allowed["snapshot_interval_minutes"] = int(allowed.get("snapshot_interval_minutes", 30) or 0)
        except (TypeError, ValueError):
            allowed["snapshot_interval_minutes"] = 0
        columns = allowed.get("employee_visible_columns", [])
        allowed["employee_visible_columns"] = (
            [str(column) for column in columns] if isinstance(columns, list) else []
        )
        return cls(**allowed)

    def save(self) -> None:
        secure_storage.set(_SETTINGS_KEY, asdict(self))

    def as_dict(self) -> dict:
        return asdict(self)
