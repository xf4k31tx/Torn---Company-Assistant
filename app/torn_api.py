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

import re
import urllib.parse
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
    def __init__(self, code: int, message: str = "", url: str = ""):
        self.code = code
        self.message = message or TORN_ERROR_MESSAGES.get(code, "Unknown Torn API error")
        self.url = url
        suffix = f" (url={url})" if url else ""
        super().__init__(f"Torn API error {code}: {self.message}{suffix}")


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
            # key= is redacted before this ever reaches a log line or
            # exception message - resp.url is the fully-resolved request
            # URL (including every query param actually sent), which is
            # far more useful for diagnosing "Incorrect ID"-type errors
            # than the caller's un-redacted API key would be.
            safe_url = re.sub(r"([?&]key=)[^&]*", r"\1REDACTED", resp.url)
            raise TornAPIError(
                int(data["error"].get("code", 0)), data["error"].get("error", ""), url=safe_url
            )
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
        for the Company Health Score ranking feature. See
        get_all_company_listings() below for the full pagination loop."""
        return self.v2("company", company_type_id, "companies", extra_params={
            "limit": limit, "offset": offset
        })

    def fetch_url(self, url: str) -> dict:
        """GET an already-complete URL rather than building one from
        section/id/selection - key/comment are still attached via _get,
        same as every other method here. General-purpose; NOT used by
        get_all_company_listings() below - see that method's docstring for
        why a confirmed live Torn API bug rules it out for this endpoint's
        pagination specifically."""
        return self._get(url, {})

    def get_all_company_listings(self, company_type_id: int, page_size: int = 100) -> list[dict]:
        """Every company of *company_type_id*.

        v2/company/{type_id}/companies' `_metadata.links.next` has a
        confirmed live bug (observed 2026-08-05 against a real key): the
        `next` URL it returns is missing the `/{type_id}` path segment
        entirely - e.g. ".../v2/company/companies?limit=100&offset=100..."
        instead of ".../v2/company/28/companies?limit=100&offset=100...".
        GETting that URL as-is fails with "Torn API error 6: Incorrect ID",
        since Torn's own server can't resolve a typeless /company/companies
        path. Page 1 (from get_company_listings, which always builds its
        own correctly-typed URL) is unaffected - only next-page links are
        broken.

        Rather than trust the link's PATH, this pulls just the offset/limit
        query params out of it and reissues the request through
        get_company_listings() - which always includes the type ID -
        instead of GETting the link directly. "Torn stopped giving us a
        next link" (or an empty page) is still what ends the loop; only the
        page 2+ URL construction is defended against.
        """
        all_companies: list[dict] = []
        resp = self.get_company_listings(company_type_id, limit=page_size)
        while True:
            batch = resp.get("companies", []) or []
            all_companies.extend(batch)
            next_url = ((resp.get("_metadata") or {}).get("links") or {}).get("next")
            if not next_url or not batch:
                break
            query = urllib.parse.parse_qs(urllib.parse.urlparse(next_url).query)
            next_offset = int((query.get("offset") or [len(all_companies)])[0])
            next_limit = int((query.get("limit") or [page_size])[0])
            resp = self.get_company_listings(company_type_id, offset=next_offset, limit=next_limit)
        return all_companies

    def check_key_info(self) -> dict:
        return self.v1("key", None, selections="info")
