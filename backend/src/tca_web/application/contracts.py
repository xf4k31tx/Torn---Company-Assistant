from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

type JsonObject = dict[str, Any]


class Operation(StrEnum):
    SNAPSHOT = "snapshot"
    EMPLOYEE_EFFICIENCY = "employee_efficiency"
    RUN_EVERYTHING = "run_everything"
    IMPORT_HISTORY = "import_history"
    SCHEDULED_COLLECTION = "scheduled_collection"


class ProgressState(StrEnum):
    STARTED = "started"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    WARNING = "warning"
    FAILED = "failed"


class ProgressEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Operation
    stage: str = Field(min_length=1, max_length=80)
    state: ProgressState
    message: str = Field(min_length=1, max_length=500)
    current: int | None = Field(default=None, ge=0)
    total: int | None = Field(default=None, ge=1)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def validate_progress(self) -> ProgressEvent:
        if (self.current is None) != (self.total is None):
            raise ValueError("current and total must be supplied together")
        if self.current is not None and self.total is not None and self.current > self.total:
            raise ValueError("current cannot exceed total")
        return self


type ProgressCallback = Callable[[ProgressEvent], None | Awaitable[None]]


async def emit_progress(callback: ProgressCallback | None, event: ProgressEvent) -> None:
    if callback is None:
        return
    result = callback(event)
    if inspect.isawaitable(result):
        await result


class SnapshotResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_name: str
    employee_count: int = Field(ge=0)
    stock_count: int = Field(ge=0)
    is_update: bool = False


class EmployeeEfficiencyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    company_name: str
    employee_count: int = Field(ge=0)
    misplaced_count: int = Field(ge=0)
    verification_note: str = ""


class CollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    workspace_id: str = Field(min_length=1)
    company_id: int = Field(gt=0)
    position_capacities: dict[str, int] = Field(default_factory=dict)
    position_priority_order: list[str] = Field(default_factory=list)
    locked_employee_ids: set[str] = Field(default_factory=set)


class SnapshotData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: int = Field(gt=0)
    company: JsonObject
    employees: list[JsonObject]
    stock: list[JsonObject]
    rankings: list[JsonObject]
    director_efficiency: list[JsonObject] = Field(default_factory=list)


class EmployeeEfficiencyData(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: int = Field(gt=0)
    employees: list[JsonObject]
    position_names: list[str]
    position_efficiency: list[JsonObject]
    total_effectiveness_projections: list[JsonObject]
    turnover: list[JsonObject]


class EverythingResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: SnapshotResult
    employee_efficiency: EmployeeEfficiencyResult


class ImportHistoryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    imported_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)


class ScheduledCollectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operation: Operation
    result: SnapshotResult | EmployeeEfficiencyResult | EverythingResult


class ServiceError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    retryable: bool = False


class TornResponse(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)


class CompanyProfileResponse(TornResponse):
    profile: JsonObject


class CompanyEmployeesResponse(TornResponse):
    employees: list[JsonObject]


class CompanyStockResponse(TornResponse):
    stock: list[JsonObject]


class TimestampResponse(TornResponse):
    timestamp: int


class PaginationLinks(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    next: str | None = None
    prev: str | None = None


class PaginationMetadata(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    links: PaginationLinks = Field(default_factory=PaginationLinks)


class CompaniesResponse(TornResponse):
    companies: list[JsonObject]
    metadata: PaginationMetadata = Field(
        default_factory=PaginationMetadata,
        validation_alias="_metadata",
        serialization_alias="_metadata",
    )


class KeyInfoResponse(TornResponse):
    info: JsonObject
