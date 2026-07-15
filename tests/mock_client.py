from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_MOCK_DATA_PATH = Path(__file__).resolve().parent / "mock_data" / "endpoints.json"


def _load_mock_data() -> dict:
    with open(_MOCK_DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Call tracking – test assertions can inspect what the mock was asked to do.
# ---------------------------------------------------------------------------

@dataclass
class CallRecord:
    method: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# MockTornAPI
# ---------------------------------------------------------------------------

class MockTornAPI:
    """Drop-in replacement for app.torn_api.TornAPI.

    Returns canned responses from mock_data/endpoints.json.
    Call ``.calls`` to inspect what the code under test requested.

    Use ``inject_error(name)`` on any method to make it raise
    ``TornAPIError`` with the named error scenario.
    """

    def __init__(self, api_key: str = "MOCK_KEY"):
        self.api_key = api_key
        self.calls: list[CallRecord] = []
        self._data = _load_mock_data()["torn_api"]["endpoints"]
        self._errors: dict[str, Optional[str]] = {
            "get_company": None,
            "get_company_listings": None,
            "get_user_workstats": None,
            "get_user_education": None,
            "check_key_info": None,
        }

    # -- error injection helpers --

    def inject_error(self, method: str, error_name: str) -> None:
        """Make the next call to *method* raise TornAPIError matching
        the named error from endpoints.json (e.g. ``"rate_limited"``)."""
        self._errors[method] = error_name

    def clear_errors(self) -> None:
        for k in self._errors:
            self._errors[k] = None

    def _raise_if_error(self, method: str) -> None:
        name = self._errors.get(method)
        if name is None:
            return
        self._errors[method] = None  # one-shot
        err_body = self._data.get("errors", {}).get(name)
        if err_body is None:
            raise RuntimeError(f"Unknown mock error name {name!r}")
        from app.torn_api import TornAPIError
        raise TornAPIError(
            code=int(err_body["error"]["code"]),
            message=err_body["error"]["error"],
        )

    def _record(self, method: str, *args, **kwargs) -> None:
        self.calls.append(CallRecord(method=method, args=args, kwargs=kwargs))

    # -- method stubs matching the real TornAPI interface --

    def get_company(self, company_id: Optional[str] = None) -> dict:
        self._record("get_company", company_id)
        self._raise_if_error("get_company")
        return copy.deepcopy(self._data["get_company"]["response"])

    def get_company_listings(self, company_type_id: int, offset: int = 0, limit: int = 100) -> dict:
        self._record("get_company_listings", company_type_id, offset, limit)
        self._raise_if_error("get_company_listings")
        return copy.deepcopy(self._data["get_company_listings"]["response"])

    def get_user_workstats(self, user_id: Optional[str] = None) -> dict:
        self._record("get_user_workstats", user_id)
        self._raise_if_error("get_user_workstats")
        return copy.deepcopy(self._data["get_user_workstats"]["response"])

    def get_user_education(self, user_id: Optional[str] = None) -> dict:
        self._record("get_user_education", user_id)
        self._raise_if_error("get_user_education")
        return copy.deepcopy(self._data["get_user_education"]["response"])

    def check_key_info(self) -> dict:
        self._record("check_key_info")
        self._raise_if_error("check_key_info")
        return copy.deepcopy(self._data["check_key_info"]["response"])


# ---------------------------------------------------------------------------
# MockTornStatsAPI
# ---------------------------------------------------------------------------

class MockTornStatsAPI:
    """Drop-in replacement for app.tornstats_api.TornStatsAPI."""

    def __init__(self, api_key: str = "MOCK_TS_KEY"):
        self.api_key = api_key
        self.calls: list[CallRecord] = []
        self._data = _load_mock_data()["tornstats_api"]["endpoints"]
        self._errors: dict[str, Optional[str]] = {
            "get_efficiency": None,
            "get_faction_roster": None,
            "get_faction_skills": None,
            "validate_key": None,
        }

    def inject_error(self, method: str, error_name: str) -> None:
        self._errors[method] = error_name

    def clear_errors(self) -> None:
        for k in self._errors:
            self._errors[k] = None

    def _raise_if_error(self, method: str) -> None:
        name = self._errors.get(method)
        if name is None:
            return
        self._errors[method] = None
        err_body = self._data.get("errors", {}).get(name)
        if err_body is None:
            raise RuntimeError(f"Unknown mock error name {name!r}")
        from app.tornstats_api import TornStatsAPIError
        raise TornStatsAPIError(message=err_body.get("message", "unknown error"))

    def _record(self, method: str, *args, **kwargs) -> None:
        self.calls.append(CallRecord(method=method, args=args, kwargs=kwargs))

    def get_efficiency(self, man: Optional[int] = None, intel: Optional[int] = None, end: Optional[int] = None) -> dict:
        self._record("get_efficiency", man, intel, end)
        self._raise_if_error("get_efficiency")
        return copy.deepcopy(self._data["get_efficiency"]["response"])

    def get_faction_roster(self) -> dict:
        self._record("get_faction_roster")
        self._raise_if_error("get_faction_roster")
        return copy.deepcopy(self._data["get_faction_roster"]["response"])

    def get_faction_skills(self) -> dict:
        self._record("get_faction_skills")
        self._raise_if_error("get_faction_skills")
        return copy.deepcopy(self._data["get_faction_skills"]["response"])

    def validate_key(self) -> dict:
        self._record("validate_key")
        self._raise_if_error("validate_key")
        return copy.deepcopy(self._data["validate_key"]["response"])


# ---------------------------------------------------------------------------
# MockSheetsClient
# ---------------------------------------------------------------------------

class MockSheetsClient:
    """In-memory replacement for app.sheets_client.SheetsClient.

    Data lives in ``self._tabs`` as ``{tab_name: [list_of_dict_rows]}`` so
    tests can inspect what was written and control what ``read_records``
    returns.  ``.calls`` tracks every operation.
    """

    SHEET_URL = "https://docs.google.com/spreadsheets/d/MOCK_SHEET_ID"

    def __init__(self, sheet_id: str = "MOCK_SHEET_ID", sheet_name: str = ""):
        self.sheet_id = sheet_id
        self.sheet_name = sheet_name
        self.calls: list[CallRecord] = []
        self._tabs: dict[str, list[dict]] = {}

    @property
    def url(self) -> str:
        return self.SHEET_URL

    def _record(self, method: str, *args, **kwargs) -> None:
        self.calls.append(CallRecord(method=method, args=args, kwargs=kwargs))

    # -- helpers for arranging test data --

    def seed_tab(self, title: str, records: list[dict]) -> None:
        """Pre-populate a tab with rows so read_records can return them."""
        self._tabs[title] = list(records)

    def get_tab(self, title: str) -> list[dict]:
        """Return the current in-memory contents of a tab."""
        return list(self._tabs.get(title, []))

    # -- method stubs matching the real SheetsClient interface --

    def append_history_row(self, title: str, headers: list[str], row: list) -> None:
        self._record("append_history_row", title, headers, row)
        if title not in self._tabs:
            self._tabs[title] = []
        self._tabs[title].insert(0, dict(zip(headers, [str(v) for v in row])))

    def append_history_rows(self, title: str, headers: list[str], rows: list[list]) -> None:
        self._record("append_history_rows", title, headers, rows)
        if title not in self._tabs:
            self._tabs[title] = []
        inserted = [dict(zip(headers, [str(v) for v in row])) for row in rows]
        self._tabs[title] = inserted + self._tabs[title]

    def overwrite_current_state(self, title: str, headers: list[str], rows: list[list]) -> None:
        self._record("overwrite_current_state", title, headers, rows)
        self._tabs[title] = [dict(zip(headers, [str(v) for v in row])) for row in rows]

    def overwrite_worksheet(self, title: str, headers: list[str], rows: list[list]) -> None:
        self.overwrite_current_state(title, headers, rows)

    def sort_history_newest_first(self, title: str) -> int:
        self._record("sort_history_newest_first", title)
        records = self._tabs.get(title, [])
        if len(records) < 2:
            return len(records)
        self._tabs[title] = sorted(records, key=lambda r: -int(r.get("timestamp", 0) or 0))
        return len(records)

    def read_records(self, title: str) -> list[dict]:
        self._record("read_records", title)
        return list(self._tabs.get(title, []))

    def read_raw_grid(self, title: str) -> list[list[str]]:
        self._record("read_raw_grid", title)
        records = self._tabs.get(title, [])
        if not records:
            return []
        headers = list(records[0].keys())
        return [headers] + [[str(r.get(h, "")) for h in headers] for r in records]
