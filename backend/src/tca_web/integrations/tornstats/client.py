from __future__ import annotations

from typing import Any

import httpx

from tca_web.application.contracts import JsonObject


class TornStatsApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class TornStatsApiClient:
    BASE_URL = "https://www.tornstats.com/api"

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key cannot be empty")
        self._api_key = api_key
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> TornStatsApiClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_efficiency(
        self,
        manual_labor: int | None = None,
        intelligence: int | None = None,
        endurance: int | None = None,
    ) -> JsonObject:
        params = {
            name: value
            for name, value in {
                "man": manual_labor,
                "int": intelligence,
                "end": endurance,
            }.items()
            if value is not None
        }
        try:
            response = await self._client.get(
                f"{self.BASE_URL}/v2/{self._api_key}/efficiency",
                params=params,
            )
        except httpx.HTTPError:
            raise TornStatsApiError("Torn Stats request failed", retryable=True) from None
        if response.status_code >= 400:
            raise TornStatsApiError(
                "Torn Stats returned an HTTP error",
                status_code=response.status_code,
                retryable=response.status_code in {408, 425, 429} or response.status_code >= 500,
            )
        try:
            payload: Any = response.json()
        except ValueError:
            raise TornStatsApiError("Torn Stats returned invalid JSON", retryable=True) from None
        if not isinstance(payload, dict):
            raise TornStatsApiError("Torn Stats returned an unexpected response")
        if payload.get("status") is False:
            raise TornStatsApiError(str(payload.get("message") or "Torn Stats API error"))
        return payload
