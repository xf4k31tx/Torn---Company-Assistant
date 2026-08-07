from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from tca_web.application.contracts import (
    CompaniesResponse,
    CompanyEmployeesResponse,
    CompanyProfileResponse,
    CompanyStockResponse,
    EmployeeEfficiencyData,
    ImportHistoryResult,
    JsonObject,
    KeyInfoResponse,
    ProgressEvent,
    SnapshotData,
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
    async def get_efficiency(
        self,
        manual_labor: int | None = None,
        intelligence: int | None = None,
        endurance: int | None = None,
    ) -> JsonObject: ...


@runtime_checkable
class CompanyDataRepository(Protocol):
    async def save_snapshot(
        self,
        workspace_id: str,
        company_id: int,
        data: SnapshotData,
        *,
        is_update: bool,
    ) -> None: ...

    async def load_company_history(
        self, workspace_id: str, company_id: int
    ) -> list[JsonObject]: ...

    async def load_stock_history(self, workspace_id: str, company_id: int) -> list[JsonObject]: ...

    async def load_employee_effectiveness(
        self, workspace_id: str, company_id: int
    ) -> list[JsonObject]: ...

    async def save_employee_efficiency(
        self, workspace_id: str, company_id: int, data: EmployeeEfficiencyData
    ) -> None: ...

    async def import_history(
        self, workspace_id: str, company_id: int, records: list[JsonObject]
    ) -> ImportHistoryResult: ...


@runtime_checkable
class ProgressSink(Protocol):
    async def publish(self, job_id: str, event: ProgressEvent) -> None: ...

    def stream(self, job_id: str, *, after_sequence: int = 0) -> AsyncIterator[ProgressEvent]: ...


@runtime_checkable
class WorkbookPort(Protocol):
    async def export_history(self, workspace_id: str, company_id: int) -> bytes: ...

    async def parse_history(self, content: bytes) -> list[JsonObject]: ...


@runtime_checkable
class JobPort(Protocol):
    async def enqueue(
        self, operation: str, workspace_id: str, company_id: int, payload: JsonObject
    ) -> str: ...
