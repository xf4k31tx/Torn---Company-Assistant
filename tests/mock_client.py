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
    """Drop-in replacement for app.torn_api.TornAPI (v2-first, matching the
    Phase 4 collector rewrite).

    Returns canned responses from mock_data/endpoints.json.
    Call ``.calls`` to inspect what the code under test requested.

    Use ``inject_error(name)`` on any method to make it raise
    ``TornAPIError`` with the named error scenario (one-shot: cleared after
    the next call to that method, whether or not it actually raised).
    """

    def __init__(self, api_key: str = "MOCK_KEY"):
        self.api_key = api_key
        self.calls: list[CallRecord] = []
        self._data = _load_mock_data()["torn_api"]["endpoints"]
        self._errors: dict[str, Optional[str]] = {
            "get_company_profile_v2": None,
            "get_company_employees": None,
            "get_company_stock_v2": None,
            "get_company_timestamp_v2": None,
            "get_company_listings": None,
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

    # -- method stubs matching the real (v2-first) TornAPI interface --

    def get_company_profile_v2(self) -> dict:
        self._record("get_company_profile_v2")
        self._raise_if_error("get_company_profile_v2")
        return copy.deepcopy(self._data["get_company_profile_v2"]["response"])

    def get_company_employees(self) -> dict:
        self._record("get_company_employees")
        self._raise_if_error("get_company_employees")
        return copy.deepcopy(self._data["get_company_employees"]["response"])

    def get_company_stock_v2(self) -> dict:
        self._record("get_company_stock_v2")
        self._raise_if_error("get_company_stock_v2")
        return copy.deepcopy(self._data["get_company_stock_v2"]["response"])

    def get_company_timestamp_v2(self) -> dict:
        self._record("get_company_timestamp_v2")
        self._raise_if_error("get_company_timestamp_v2")
        return copy.deepcopy(self._data["get_company_timestamp_v2"]["response"])

    def get_company_listings(self, company_type_id: int, offset: int = 0, limit: int = 100) -> dict:
        self._record("get_company_listings", company_type_id, offset, limit)
        self._raise_if_error("get_company_listings")
        # Real pagination: only return companies within [offset, offset+limit).
        # The mock fixture has 3 companies total, so a single page covers it
        # for the default limit=100 - this still exercises the collector's
        # pagination loop-termination logic (offset >= total, or empty batch).
        full = self._data["get_company_listings"]["response"]
        companies = full["companies"][offset:offset + limit]
        return {
            "companies": copy.deepcopy(companies),
            "_metadata": {**full["_metadata"], "offset": offset, "limit": limit},
        }

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
    """In-memory replacement for app.sheets_client.SheetsClient (Phase 4/5
    dict-row API, not the older positional-list one).

    Data lives in ``self._tabs`` as ``{tab_name: [list_of_dict_rows]}`` so
    tests can inspect what was written and control what ``read_records``
    returns. ``.calls`` tracks every operation.

    Note: real SheetsClient instances are obtained via the
    ``SheetsClient.get_or_create()`` classmethod, not by constructing one
    directly - conftest.py's ``patch_sheets`` fixture patches that
    classmethod to return a fixed instance of this mock rather than trying
    to make this class stand in for the real one structurally.
    """

    def __init__(self, sheet_id: str = "MOCK_SHEET_ID", sheet_name: str = ""):
        self.sheet_id = sheet_id
        self.sheet_name = sheet_name
        self.calls: list[CallRecord] = []
        self._tabs: dict[str, list[dict]] = {}

    @property
    def url(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{self.sheet_id}"

    def _record(self, method: str, *args, **kwargs) -> None:
        self.calls.append(CallRecord(method=method, args=args, kwargs=kwargs))

    # -- helpers for arranging test data --

    def seed_tab(self, title: str, records: list[dict]) -> None:
        """Pre-populate a tab with rows so read_records can return them."""
        self._tabs[title] = list(records)

    def get_tab(self, title: str) -> list[dict]:
        """Return the current in-memory contents of a tab."""
        return list(self._tabs.get(title, []))

    # -- method stubs matching the real (dict-row) SheetsClient interface --

    def append_history_row(self, title: str, headers: list[str], row: dict) -> None:
        self._record("append_history_row", title, headers, row)
        self._tabs.setdefault(title, [])
        self._tabs[title].insert(0, {h: str(row.get(h, "")) for h in headers})

    def append_history_rows(self, title: str, headers: list[str], rows: list[dict]) -> None:
        self._record("append_history_rows", title, headers, rows)
        self._tabs.setdefault(title, [])
        inserted = [{h: str(row.get(h, "")) for h in headers} for row in rows]
        self._tabs[title] = inserted + self._tabs[title]

    def overwrite_current_state(self, title: str, headers: list[str], rows: list[dict]) -> None:
        self._record("overwrite_current_state", title, headers, rows)
        self._tabs[title] = [{h: str(row.get(h, "")) for h in headers} for row in rows]

    def overwrite_worksheet(self, title: str, headers: list[str], rows: list[dict]) -> None:
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
