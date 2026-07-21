"""
Thin wrapper around the official Torn API (api.torn.com).

Reference (ingested from torn.com/api.html, the Torn API v2 Swagger docs,
the YATA source, and live v2/company/* responses):
  - v1: https://api.torn.com/{section}/{id}?selections=a,b,c&key=...
  - v2: https://api.torn.com/v2/{section}/{id}/{selection}?key=...
        (v2 also accepts selections as a query param on some endpoints)
  - Rate limit: 100 requests/minute per user, 1000/minute per IP.
  - Error code 2 = bad key, 5 = rate limited, 7 = no permission for that
    selection/id relation, 13 = key disabled (owner inactive 7+ days),
    16 = access level too low.

v1 -> v2 migration (Phase 2 of the Employee Calculator merge): v2/company's
profile/employees/stock/timestamp selections (director's own company, no id
needed) are a confirmed superset of the old v1 combined call, with some
field renames - see collector.py and profit_calc.py for where those renamed
fields get mapped back onto the original Sheet column names. Notably:
  - v2 top-level key is the selection name itself ("profile"/"stock"/
    "employees"/"timestamp"), not "company"/"company_detailed"/etc like v1.
  - v2/company/stock returns a *list*, not a dict keyed by stock name.
  - advertising_budget (v1) -> advertisement_budget (v2, note the spelling).
  - v2 upgrades{} has 3 descriptive-string fields (staff_room, storage,
    storage_capacity); v1's numeric company_size has no v2 equivalent.

Phase 4 (collector rewrite) removed the last caller of the deprecated v1
get_company() combined selection, so it has been deleted from this module.
All company data now flows through the v2 methods below.
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

    # ---------------------------------------------------- v2 convenience --
    def get_company_profile_v2(self) -> dict:
        """
        v2/company/profile - director's own company. Confirmed live superset
        of v1's profile+detailed combined: name, created_at, days_old, type
        {id, name}, rating, director{...}, employees{hired, capacity},
        income{daily, weekly}, customers{daily, weekly}, funds, popularity,
        efficiency, environment, trains, advertisement_budget, upgrades
        {staff_room, storage, storage_capacity}, value. Top-level response
        key is "profile", not "company".
        """
        return self.v2("company", selection="profile")

    def get_company_employees(self) -> dict:
        """
        v2/company/employees - director's own company. Returns
        {"employees": [...]}, each with id, name, position {id, name},
        days_in_company, status, last_action, stats {manual_labor,
        intelligence, endurance}, effectiveness {...breakdown..., total},
        joined_at, wage, value.
        """
        return self.v2("company", selection="employees", extra_params={"striptags": "true"})

    def get_company_stock_v2(self) -> dict:
        """
        v2/company/stock - director's own company. Returns {"stock": [...]},
        a *list* (unlike v1's dict keyed by stock name), each item with
        name, id, cost, rrp, price, in_stock, on_order, sold_amount,
        sold_worth.
        """
        return self.v2("company", selection="stock")

    def get_company_timestamp_v2(self) -> dict:
        """v2/company/timestamp - director's own company. {"timestamp": int}."""
        return self.v2("company", selection="timestamp")

    def get_company_listings(self, company_type_id: int, offset: int = 0, limit: int = 100) -> dict:
        """Browse all companies of a given type (public directory) - source
        for the Company Health Score ranking feature."""
        return self.v2("company", company_type_id, "companies", extra_params={
            "limit": limit, "offset": offset
        })

    def check_key_info(self) -> dict:
        return self.v1("key", None, selections="info")
