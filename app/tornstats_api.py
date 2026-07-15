"""
Thin wrapper around the Tornstats.com API (tornstats.com/api).

Base pattern: https://www.tornstats.com/api/{v1|v2}/{key}/{endpoint}
The key lives in the URL path, not a query param. All responses include a
"status" boolean that should be checked before trusting the payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests

BASE = "https://www.tornstats.com/api"


class TornStatsAPIError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(f"Tornstats API error: {message}")


@dataclass
class TornStatsAPI:
    api_key: str
    version: str = "v2"
    timeout: int = 15

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        url = f"{BASE}/{self.version}/{self.api_key}/{endpoint}".rstrip("/")
        resp = requests.get(url, params=params or {}, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and data.get("status") is False:
            raise TornStatsAPIError(data.get("message", "unknown error"))
        return data

    # ------------------------------------------------------- convenience --
    def get_efficiency(self, man: Optional[int] = None, intel: Optional[int] = None,
                        end: Optional[int] = None) -> dict:
        """
        Per-position effectiveness for every company type. If man/intel/end
        are omitted, Tornstats uses the key owner's live work stats.
        """
        params = {}
        if man is not None:
            params["man"] = man
        if intel is not None:
            params["int"] = intel
        if end is not None:
            params["end"] = end
        return self._get("efficiency", params)

    def get_faction_roster(self) -> dict:
        return self._get("faction/roster")

    def get_faction_skills(self) -> dict:
        return self._get("faction/skills")

    def validate_key(self) -> dict:
        return self._get("")
