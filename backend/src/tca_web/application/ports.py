from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from tca_web.application.contracts import (
    CompaniesResponse,
    CompanyEmployeesResponse,
    CompanyProfileResponse,
    CompanyStockResponse,
    JsonObject,
    KeyInfoResponse,
    ProgressEvent,
    TimestampResponse,
)


@runtime_checkable
class TornGateway(Protocol):
    async def get_company_profile(self) -> CompanyProfileResponse: ...

    async def get_company_employees(self) -> CompanyEmployeesResponse: ...

    async def get_company_stock(self) -> CompanyStockResponse: ...

    async def get_company_timestamp(self) -> TimestampResponse: ...

    async def get_companies(
        self, company_type_id: int, *, offset: int = 0, limit: int = 100
    ) -> CompaniesResponse: ...

    async def get_all_companies(
        self, company_type_id: int, *, page_size: int = 100
    ) -> list[JsonObject]: ...

    async def get_key_info(self) -> KeyInfoResponse: ...


@runtime_checkable
class TornStatsGateway(Protocol):
    async def get_company_efficiency(self, company_id: int) -> JsonObject: ...


@runtime_checkable
class SnapshotRepository(Protocol):
    async def save_snapshot(self, workspace_id: str, company_id: int, data: JsonObject) -> str: ...

    async def load_latest_snapshot(
        self, workspace_id: str, company_id: int
    ) -> JsonObject | None: ...


@runtime_checkable
class ProgressSink(Protocol):
    async def publish(self, job_id: str, event: ProgressEvent) -> None: ...

    def stream(self, job_id: str, *, after_sequence: int = 0) -> AsyncIterator[ProgressEvent]: ...


@runtime_checkable
class WorkbookPort(Protocol):
    async def export_history(self, workspace_id: str, company_id: int) -> bytes: ...

    async def preview_import(self, workspace_id: str, content: bytes) -> JsonObject: ...
