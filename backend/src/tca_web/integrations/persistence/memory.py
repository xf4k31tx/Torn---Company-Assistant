from __future__ import annotations

from copy import deepcopy

from tca_web.application.contracts import (
    EmployeeEfficiencyData,
    ImportHistoryResult,
    JsonObject,
    SnapshotData,
)

type RepositoryKey = tuple[str, int]


class InMemoryCompanyDataRepository:
    def __init__(self) -> None:
        self.snapshots: dict[RepositoryKey, list[SnapshotData]] = {}
        self.efficiency: dict[RepositoryKey, EmployeeEfficiencyData] = {}
        self.imported: dict[RepositoryKey, list[JsonObject]] = {}

    async def save_snapshot(
        self,
        workspace_id: str,
        company_id: int,
        data: SnapshotData,
        *,
        is_update: bool,
    ) -> None:
        history = self.snapshots.setdefault((workspace_id, company_id), [])
        if is_update and history:
            history[-1] = data
        else:
            history.append(data)

    async def load_company_history(self, workspace_id: str, company_id: int) -> list[JsonObject]:
        return [
            deepcopy(snapshot.company)
            for snapshot in self.snapshots.get((workspace_id, company_id), [])
        ]

    async def load_stock_history(self, workspace_id: str, company_id: int) -> list[JsonObject]:
        rows: list[JsonObject] = []
        for snapshot in self.snapshots.get((workspace_id, company_id), []):
            rows.extend(deepcopy(snapshot.stock))
        return rows

    async def load_employee_effectiveness(
        self, workspace_id: str, company_id: int
    ) -> list[JsonObject]:
        data = self.efficiency.get((workspace_id, company_id))
        return deepcopy(data.employees) if data else []

    async def save_employee_efficiency(
        self,
        workspace_id: str,
        company_id: int,
        data: EmployeeEfficiencyData,
    ) -> None:
        self.efficiency[(workspace_id, company_id)] = data

    async def import_history(
        self,
        workspace_id: str,
        company_id: int,
        records: list[JsonObject],
    ) -> ImportHistoryResult:
        history = self.imported.setdefault((workspace_id, company_id), [])
        fingerprints = {repr(sorted(row.items())) for row in history}
        imported_count = 0
        for record in records:
            fingerprint = repr(sorted(record.items()))
            if fingerprint in fingerprints:
                continue
            history.append(deepcopy(record))
            fingerprints.add(fingerprint)
            imported_count += 1
        return ImportHistoryResult(
            imported_count=imported_count,
            skipped_count=len(records) - imported_count,
        )
