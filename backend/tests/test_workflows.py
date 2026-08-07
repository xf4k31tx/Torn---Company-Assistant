from __future__ import annotations

from tca_web.application.contracts import (
    CollectionRequest,
    CompaniesResponse,
    CompanyEmployeesResponse,
    CompanyProfileResponse,
    CompanyStockResponse,
    JsonObject,
    KeyInfoResponse,
    Operation,
    TimestampResponse,
)
from tca_web.application.workflows import (
    EmployeeEfficiencyWorkflow,
    ImportHistoryWorkflow,
    RunEverythingWorkflow,
    ScheduledCollectionWorkflow,
    SnapshotWorkflow,
)
from tca_web.integrations.persistence.memory import InMemoryCompanyDataRepository


class TornStub:
    async def get_company_profile(self) -> CompanyProfileResponse:
        return CompanyProfileResponse(
            profile={
                "id": 10,
                "name": "Test Company",
                "type": {"id": 12, "name": "Oil Rig"},
                "rating": 9,
                "employees": {"hired": 2, "capacity": 2},
                "income": {"daily": 1000, "weekly": 7000},
                "customers": {"daily": 5, "weekly": 35},
                "advertisement_budget": 10,
            }
        )

    async def get_company_employees(self) -> CompanyEmployeesResponse:
        return CompanyEmployeesResponse(
            employees=[
                {
                    "id": 1,
                    "name": "A",
                    "position": {"name": "Director"},
                    "wage": 100,
                    "stats": {"manual_labor": 1, "intelligence": 2, "endurance": 3},
                    "effectiveness": {"total": 80, "working_stats": 40},
                },
                {
                    "id": 2,
                    "name": "B",
                    "position": {"name": "Trainer"},
                    "wage": 200,
                    "stats": {"manual_labor": 4, "intelligence": 5, "endurance": 6},
                    "effectiveness": {"total": 90, "working_stats": 50},
                },
            ]
        )

    async def get_company_stock(self) -> CompanyStockResponse:
        return CompanyStockResponse(
            stock=[
                {
                    "name": "Oil",
                    "in_stock": 100,
                    "cost": 10,
                    "price": 20,
                    "sold_amount": 5,
                    "sold_worth": 100,
                }
            ]
        )

    async def get_company_timestamp(self) -> TimestampResponse:
        return TimestampResponse(timestamp=1_800_000_000)

    async def get_companies(
        self, company_type_id: int, *, offset: int = 0, limit: int = 100
    ) -> CompaniesResponse:
        return CompaniesResponse(companies=[])

    async def get_all_companies(
        self, company_type_id: int, *, page_size: int = 100
    ) -> list[JsonObject]:
        return [
            {"id": 20, "name": "Leader", "rating": 10, "income": {"weekly": 9000}},
            {"id": 10, "name": "Test Company", "rating": 9, "income": {"weekly": 7000}},
        ]

    async def get_key_info(self) -> KeyInfoResponse:
        return KeyInfoResponse(info={})


class TornStatsStub:
    async def get_efficiency(
        self,
        manual_labor: int | None = None,
        intelligence: int | None = None,
        endurance: int | None = None,
    ) -> JsonObject:
        if manual_labor is None:
            return {"12": {"company": "Oil Company", "Director": 100, "Trainer": 90}}
        return {
            "12": {
                "company": "Oil Company",
                "Director": 40 + manual_labor,
                "Trainer": 100 - manual_labor,
            }
        }


class WorkbookStub:
    async def export_history(self, workspace_id: str, company_id: int) -> bytes:
        return b""

    async def parse_history(self, content: bytes) -> list[JsonObject]:
        assert content == b"workbook"
        return [{"timestamp": 1, "daily_income": 10}]


def request() -> CollectionRequest:
    return CollectionRequest(
        workspace_id="workspace",
        company_id=10,
        position_capacities={"Director": 1, "Trainer": 1},
        position_priority_order=["Director", "Trainer"],
        locked_employee_ids={"1"},
    )


async def test_snapshot_preserves_financial_stock_and_ranking_math() -> None:
    repository = InMemoryCompanyDataRepository()
    workflow = SnapshotWorkflow(TornStub(), repository, TornStatsStub())
    events = []
    result = await workflow.run(request(), events.append)
    data = repository.snapshots[("workspace", 10)][0]
    assert result.company_name == "Test Company"
    assert data.company["daily_profit"] == 640.0
    assert data.company["rank_by_income"] == 2
    assert data.company["income_to_reach_next_star"] == 2000.0
    assert data.stock[0]["delta_sold_amount"] == 5
    assert [event.stage for event in events] == [
        "starting",
        "profile",
        "employees",
        "stock",
        "rankings",
        "calculations",
        "persist",
        "completed",
    ]


async def test_efficiency_uses_torn_current_value_and_tornstats_hypotheticals() -> None:
    repository = InMemoryCompanyDataRepository()
    workflow = EmployeeEfficiencyWorkflow(TornStub(), TornStatsStub(), repository)
    events = []
    result = await workflow.run(request(), events.append)
    data = repository.efficiency[("workspace", 10)]
    first = data.employees[0]
    assert first["effectiveness_working_stats"] == 40
    assert first["projected_efficiency_current_position"] == 41.0
    assert first["assigned_position"] == "Director"
    assert result.employee_count == 2
    assert [event.stage for event in events] == [
        "starting",
        "profile",
        "employees",
        "projections",
        "projections",
        "persist",
        "completed",
    ]


async def test_run_everything_import_and_schedule_have_real_progress() -> None:
    repository = InMemoryCompanyDataRepository()
    snapshot = SnapshotWorkflow(TornStub(), repository, TornStatsStub())
    efficiency = EmployeeEfficiencyWorkflow(TornStub(), TornStatsStub(), repository)
    everything = RunEverythingWorkflow(snapshot, efficiency)
    run_events = []
    result = await everything.run(request(), run_events.append)
    assert result.snapshot.employee_count == 2
    assert [event.stage for event in run_events if event.operation == Operation.RUN_EVERYTHING] == [
        "starting",
        "snapshot",
        "efficiency",
        "completed",
    ]

    import_events = []
    imported = await ImportHistoryWorkflow(WorkbookStub(), repository).run(
        request(), b"workbook", import_events.append
    )
    assert imported.imported_count == 1
    assert [event.stage for event in import_events] == [
        "starting",
        "validate",
        "persist",
        "completed",
    ]

    scheduled_events = []
    scheduled = ScheduledCollectionWorkflow(snapshot, efficiency, everything)
    await scheduled.run(request(), Operation.SNAPSHOT, scheduled_events.append)
    assert [
        event.stage
        for event in scheduled_events
        if event.operation == Operation.SCHEDULED_COLLECTION
    ] == ["starting", "dispatch", "completed"]
