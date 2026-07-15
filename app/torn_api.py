"""
Thin wrapper around the official Torn API (api.torn.com).

Reference (ingested from torn.com/api.html and the YATA source):
  - v1: https://api.torn.com/{section}/{id}?selections=a,b,c&key=...
  - v2: https://api.torn.com/v2/{section}/{id}/{selection}?key=...
        (v2 also accepts selections as a query param on some endpoints)
  - Rate limit: 100 requests/minute per user, 1000/minute per IP.
  - Error code 2 = bad key, 5 = rate limited, 7 = no permission for that
    selection/id relation, 13 = key disabled (owner inactive 7+ days),
    16 = access level too low.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import requests

V1_BASE = "https://api.torn.com"
V2_BASE = "https://api.torn.com/v2"

TORN_ERROR_MESSAGES = {
    0: "Unknown error",
    1: "Key is empty",
    2: "Incorrect key",
    3: "Wrong type",
    4: "Wrong fields",
    5: "Too many requests (rate limited, max 100/min)",
    6: "Incorrect ID",
    7: "Incorrect ID-entity relation (no permission to view this)",
    8: "IP block",
    9: "API disabled",
    11: "Key change error (only once every 60s)",
    12: "Key read error",
    13: "Key temporarily disabled (owner inactive 7+ days)",
    14: "Daily read limit reached",
    16: "Access level of this key is not high enough",
    18: "API key has been paused by the owner",
    19: "Must be migrated to crimes 2.0",
    20: "Race not yet finished",
    21: "Incorrect category",
    22: "This selection is only available in API v1",
    23: "This selection is only available in API v2",
}


class TornAPIError(Exception):
    def __init__(self, code: int, message: str = ""):
        self.code = code
        self.message = message or TORN_ERROR_MESSAGES.get(code, "Unknown Torn API error")
        super().__init__(f"Torn API error {code}: {self.message}")


@dataclass
class TornAPI:
    api_key: str
    comment: str = "knotty-oil-tracker"
    timeout: int = 15

    def _get(self, url: str, params: dict) -> dict:
        params = {**params, "key": self.api_key, "comment": self.comment}
        resp = requests.get(url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            raise TornAPIError(int(data["error"].get("code", 0)), data["error"].get("error", ""))
        return data

    # ---------------------------------------------------------------- v2 --
    def v2(self, section: str, id_: Optional[str] = None, selection: Optional[str] = None,
           extra_params: Optional[dict] = None) -> dict:
        path = f"{V2_BASE}/{section}"
        if id_ not in (None, ""):
            path += f"/{id_}"
        if selection:
            path += f"/{selection}"
        return self._get(path, extra_params or {})

    # ---------------------------------------------------------------- v1 --
    def v1(self, section: str, id_: Optional[str] = None, selections: Optional[str] = None,
           extra_params: Optional[dict] = None) -> dict:
        path = f"{V1_BASE}/{section}"
        if id_ not in (None, ""):
            path += f"/{id_}"
        params = dict(extra_params or {})
        if selections:
            params["selections"] = selections
        return self._get(path, params)

    # ------------------------------------------------------- convenience --
    def get_company(self, company_id: Optional[str] = None) -> dict:
        """
        Full company snapshot: profile, detailed, employees, stock, timestamp.
        If company_id is None, uses the key owner's own company.

        Note: this combined selection set is a v1-only call (v2 rejects it
        with error 22/23 "This selection is only available in API v1" -
        confirmed against YATA's own implementation, which pulls company
        data via v1 and reserves v2 for the separate "browse all companies
        of a type" directory endpoint below).
        """
        return self.v1("company", company_id, selections="detailed,employees,profile,stock,timestamp")

    def get_company_listings(self, company_type_id: int, offset: int = 0, limit: int = 100) -> dict:
        """Browse all companies of a given type (public directory)."""
        return self.v2("company", company_type_id, "companies", extra_params={
            "limit": limit, "offset": offset
        })

    def get_user_workstats(self, user_id: Optional[str] = None) -> dict:
        """Manual labor / intelligence / endurance for the key owner (or given user)."""
        return self.v1("user", user_id, selections="workstats")

    def get_user_education(self, user_id: Optional[str] = None) -> dict:
        return self.v1("user", user_id, selections="education")

    def check_key_info(self) -> dict:
        return self.v1("key", None, selections="info")
