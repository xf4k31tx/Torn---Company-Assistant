from __future__ import annotations

from typing import Any, TypeVar
from urllib.parse import parse_qs, urlparse

import httpx
from pydantic import BaseModel, ValidationError

from tca_web.application.contracts import (
    CompaniesResponse,
    CompanyEmployeesResponse,
    CompanyProfileResponse,
    CompanyStockResponse,
    JsonObject,
    KeyInfoResponse,
    TimestampResponse,
)

ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class TornApiError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


class TornApiClient:
    BASE_URL = "https://api.torn.com/v2"

    def __init__(
        self,
        api_key: str,
        *,
        comment: str = "torn-company-assistant",
        timeout: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key cannot be empty")
        self._api_key = api_key
        self._comment = comment
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url=self.BASE_URL, timeout=timeout)

    async def __aenter__(self) -> TornApiClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(
        self,
        path: str,
        model: type[ResponseModel],
        *,
        params: dict[str, str | int] | None = None,
    ) -> ResponseModel:
        query: dict[str, str | int] = {
            "key": self._api_key,
            "comment": self._comment,
            **(params or {}),
        }
        try:
            response = await self._client.get(path, params=query)
        except httpx.HTTPError:
            raise TornApiError("Torn API request failed", retryable=True) from None

        if response.status_code >= 400:
            raise TornApiError(
                "Torn API returned an HTTP error",
                status_code=response.status_code,
                retryable=response.status_code in {408, 425, 429} or response.status_code >= 500,
            )

        try:
            payload: Any = response.json()
        except ValueError:
            raise TornApiError("Torn API returned invalid JSON", retryable=True) from None
        if not isinstance(payload, dict):
            raise TornApiError("Torn API returned an unexpected response")

        error = payload.get("error")
        if isinstance(error, dict):
            code = self._optional_int(error.get("code"))
            message = str(error.get("error") or "Torn API error")
            raise TornApiError(
                message,
                code=code,
                retryable=code in {5, 8, 9, 10},
            )

        try:
            return model.model_validate(payload)
        except ValidationError:
            raise TornApiError("Torn API response did not match its OpenAPI contract") from None

    @staticmethod
    def _optional_int(value: object) -> int | None:
        try:
            return int(str(value)) if value is not None else None
        except (TypeError, ValueError):
            return None

    async def get_company_profile(self) -> CompanyProfileResponse:
        return await self._get(
            "/company/profile",
            CompanyProfileResponse,
            params={"striptags": "true"},
        )

    async def get_company_employees(self) -> CompanyEmployeesResponse:
        return await self._get(
            "/company/employees",
            CompanyEmployeesResponse,
            params={"striptags": "true"},
        )

    async def get_company_stock(self) -> CompanyStockResponse:
        return await self._get("/company/stock", CompanyStockResponse)

    async def get_company_timestamp(self) -> TimestampResponse:
        return await self._get("/company/timestamp", TimestampResponse)

    async def get_companies(
        self,
        company_type_id: int,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> CompaniesResponse:
        if company_type_id < 1:
            raise ValueError("company_type_id must be positive")
        if offset < 0:
            raise ValueError("offset cannot be negative")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return await self._get(
            f"/company/{company_type_id}/companies",
            CompaniesResponse,
            params={"offset": offset, "limit": limit, "striptags": "true"},
        )

    async def get_all_companies(
        self,
        company_type_id: int,
        *,
        page_size: int = 100,
    ) -> list[JsonObject]:
        companies: list[JsonObject] = []
        offset = 0
        seen_offsets: set[int] = set()

        while offset not in seen_offsets:
            seen_offsets.add(offset)
            page = await self.get_companies(company_type_id, offset=offset, limit=page_size)
            companies.extend(page.companies)
            next_url = page.metadata.links.next
            if not next_url or not page.companies:
                break
            query = parse_qs(urlparse(next_url).query)
            offset = self._page_value(query, "offset", len(companies))
            page_size = self._page_value(query, "limit", page_size)
            if not 1 <= page_size <= 100:
                raise TornApiError("Torn API pagination returned an invalid page size")

        return companies

    @staticmethod
    def _page_value(query: dict[str, list[str]], name: str, default: int) -> int:
        try:
            return int((query.get(name) or [str(default)])[0])
        except (TypeError, ValueError):
            raise TornApiError(f"Torn API pagination returned an invalid {name}") from None

    async def get_key_info(self) -> KeyInfoResponse:
        return await self._get("/key/info", KeyInfoResponse)
