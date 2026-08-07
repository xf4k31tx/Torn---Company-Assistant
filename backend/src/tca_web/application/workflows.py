from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tca_web.application.contracts import (
    CollectionRequest,
    EmployeeEfficiencyData,
    EmployeeEfficiencyResult,
    EverythingResult,
    ImportHistoryResult,
    JsonObject,
    Operation,
    ProgressCallback,
    ProgressEvent,
    ProgressState,
    ScheduledCollectionResult,
    SnapshotData,
    SnapshotResult,
    emit_progress,
)
from tca_web.application.ports import (
    CompanyDataRepository,
    TornGateway,
    TornStatsGateway,
    WorkbookPort,
)
from tca_web.domain.efficiency import (
    NON_POSITION_KEYS,
    assign_positions,
    build_employee_row,
    build_position_efficiency_rows,
    build_total_effectiveness_projection_rows,
    find_company_type_block,
    is_employee_misplaced,
)
from tca_web.domain.profit_calc import (
    compute_avg_daily_income_7day,
    compute_avg_daily_profit_7day,
    compute_monthly_income,
    compute_monthly_profit,
    compute_row_profit_fields,
)
from tca_web.domain.ranking_calc import (
    compute_star_band_metrics,
    count_10_star_companies,
    find_rank,
    rank_companies_by_weekly_income,
)


async def _event(
    callback: ProgressCallback | None,
    operation: Operation,
    stage: str,
    state: ProgressState,
    message: str,
    current: int | None = None,
    total: int | None = None,
) -> None:
    await emit_progress(
        callback,
        ProgressEvent(
            operation=operation,
            stage=stage,
            state=state,
            message=message,
            current=current,
            total=total,
        ),
    )


def _optional_int(value: object) -> int | None:
    try:
        return int(str(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float:
    try:
        return float(str(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


def _period_start(timestamp: object) -> int:
    value = _optional_int(timestamp)
    if not value:
        return 0
    moment = datetime.fromtimestamp(value, tz=UTC)
    if moment.hour < 18:
        moment -= timedelta(days=1)
    return int(moment.replace(hour=18, minute=0, second=0, microsecond=0).timestamp())


def _profile_type(profile: JsonObject) -> tuple[int | None, str | None]:
    block = profile.get("type") or profile.get("company_type") or {}
    if isinstance(block, dict):
        name = block.get("name")
        return _optional_int(block.get("id")), str(name) if name else None
    return _optional_int(block), None


def _snapshot_employee(employee: JsonObject) -> JsonObject:
    effectiveness = employee.get("effectiveness") or {}
    position = employee.get("position") or {}
    effectiveness = effectiveness if isinstance(effectiveness, dict) else {}
    position = position if isinstance(position, dict) else {}
    last_action = employee.get("last_action")
    return {
        "tId": employee.get("id", ""),
        "name": employee.get("name", ""),
        "position": position.get("name", ""),
        "wage": _optional_int(employee.get("wage")) or 0,
        "days_in_company": employee.get("days_in_company", ""),
        "last_action_ts": (
            last_action.get("timestamp", "") if isinstance(last_action, dict) else last_action
        ),
        **{
            f"effectiveness_{key}": effectiveness.get(key, 0)
            for key in (
                "total",
                "working_stats",
                "settled_in",
                "director_education",
                "addiction",
                "inactivity",
                "management",
                "book",
                "merits",
            )
        },
    }


def _stock_rows(
    stock: list[JsonObject],
    previous: list[JsonObject],
    timestamp: int,
) -> tuple[list[JsonObject], float]:
    latest: dict[str, JsonObject] = {}
    for row in previous:
        name = str(row.get("name") or "")
        row_timestamp = _optional_int(row.get("timestamp")) or 0
        prior_timestamp = _optional_int(latest.get(name, {}).get("timestamp")) or 0
        if row_timestamp < timestamp and row_timestamp > prior_timestamp:
            latest[name] = row
    output: list[JsonObject] = []
    stock_cost = 0.0
    for item in stock:
        name = str(item.get("name") or "")
        in_stock = _optional_int(item.get("in_stock")) or 0
        cost = _number(item.get("cost"))
        sold_amount = _optional_int(item.get("sold_amount")) or 0
        sold_worth = _number(item.get("sold_worth"))
        stock_cost += sold_amount * cost
        prior = latest.get(name)
        prior_in_stock = _optional_int(prior.get("in_stock")) if prior else 0
        prior_sold = _optional_int(prior.get("sold_amount")) if prior else 0
        prior_worth = _number(prior.get("sold_worth")) if prior else 0.0
        days = round(in_stock / sold_amount, 1) if sold_amount else ""
        output.append(
            {
                "timestamp": timestamp,
                "date": _date(timestamp),
                "name": name,
                "in_stock": in_stock,
                "on_order": item.get("on_order", 0),
                "cost": cost,
                "price": item.get("price", 0),
                "sold_amount": sold_amount,
                "sold_worth": sold_worth,
                "delta_in_stock": in_stock - (prior_in_stock or 0),
                "delta_sold_amount": sold_amount - (prior_sold or 0),
                "delta_sold_worth": sold_worth - prior_worth,
                "created": in_stock - (prior_in_stock or 0) + sold_amount,
                "days_until_stockout": days,
                "stockout_soon": bool(sold_amount and _number(days) <= 3),
            }
        )
    return output, round(stock_cost, 2)


class SnapshotWorkflow:
    def __init__(
        self,
        torn: TornGateway,
        repository: CompanyDataRepository,
        tornstats: TornStatsGateway | None = None,
    ) -> None:
        self._torn = torn
        self._repository = repository
        self._tornstats = tornstats

    async def run(
        self,
        request: CollectionRequest,
        progress: ProgressCallback | None = None,
    ) -> SnapshotResult:
        operation = Operation.SNAPSHOT
        await _event(progress, operation, "starting", ProgressState.STARTED, "Snapshot started")
        try:
            result = await self._run(request, progress)
        except Exception:
            await _event(progress, operation, "failed", ProgressState.FAILED, "Snapshot failed")
            raise
        await _event(progress, operation, "completed", ProgressState.SUCCEEDED, "Snapshot complete")
        return result

    async def _run(
        self, request: CollectionRequest, progress: ProgressCallback | None
    ) -> SnapshotResult:
        operation = Operation.SNAPSHOT
        profile_response = await self._torn.get_company_profile()
        await _event(progress, operation, "profile", ProgressState.RUNNING, "Profile fetched", 1, 6)
        employees_response = await self._torn.get_company_employees()
        await _event(
            progress, operation, "employees", ProgressState.RUNNING, "Employees fetched", 2, 6
        )
        stock_response = await self._torn.get_company_stock()
        timestamp_response = await self._torn.get_company_timestamp()
        timestamp = timestamp_response.timestamp
        await _event(progress, operation, "stock", ProgressState.RUNNING, "Stock fetched", 3, 6)

        profile = profile_response.profile
        employees = employees_response.employees
        company_type_id, company_type_name = _profile_type(profile)
        ranked: list[JsonObject] = []
        if company_type_id:
            try:
                ranked = rank_companies_by_weekly_income(
                    await self._torn.get_all_companies(company_type_id)
                )
            except Exception:
                ranked = []
        await _event(
            progress, operation, "rankings", ProgressState.RUNNING, "Rankings calculated", 4, 6
        )

        previous_company = await self._repository.load_company_history(
            request.workspace_id, request.company_id
        )
        previous_stock = await self._repository.load_stock_history(
            request.workspace_id, request.company_id
        )
        employee_rows = [_snapshot_employee(employee) for employee in employees]
        stock_rows, daily_stock_cost = _stock_rows(stock_response.stock, previous_stock, timestamp)
        total_wage = sum(_number(row.get("wage")) for row in employee_rows)
        effectiveness = [_number(row.get("effectiveness_total")) for row in employee_rows]
        income = profile.get("income") or {}
        income = income if isinstance(income, dict) else {}
        daily_income = _number(income.get("daily"))
        weekly_income = _number(income.get("weekly"))
        advertising = _number(profile.get("advertisement_budget"))
        profit = compute_row_profit_fields(
            daily_income, weekly_income, advertising, total_wage, daily_stock_cost
        )
        own_id = profile.get("id") or profile.get("company_id") or request.company_id
        rank = find_rank(ranked, own_id)
        total_in_type = len(ranked)
        star = compute_star_band_metrics(ranked, own_id, weekly_income, profile.get("rating"))
        previous_rank = (
            _optional_int(previous_company[-1].get("rank_by_income")) if previous_company else None
        )
        if rank is None or previous_rank is None:
            rank_trend = ""
        elif rank < previous_rank:
            rank_trend = "up"
        elif rank > previous_rank:
            rank_trend = "down"
        else:
            rank_trend = "same"
        upgrades = profile.get("upgrades") or {}
        customers = profile.get("customers") or {}
        employee_block = profile.get("employees") or {}
        upgrades = upgrades if isinstance(upgrades, dict) else {}
        customers = customers if isinstance(customers, dict) else {}
        employee_block = employee_block if isinstance(employee_block, dict) else {}
        company_row: JsonObject = {
            "timestamp": timestamp,
            "date": _date(timestamp),
            "name": profile.get("name", ""),
            "rating": profile.get("rating", ""),
            "employees_hired": employee_block.get("hired", ""),
            "employees_capacity": employee_block.get("capacity", ""),
            "daily_income": income.get("daily", ""),
            "daily_profit": profit["daily_profit"],
            "daily_customers": customers.get("daily", ""),
            "weekly_income": income.get("weekly", ""),
            "weekly_profit": profit["weekly_profit"],
            "weekly_customers": customers.get("weekly", ""),
            "days_old": profile.get("days_old", ""),
            "company_funds": profile.get("funds", ""),
            "popularity": profile.get("popularity", ""),
            "efficiency": profile.get("efficiency", ""),
            "environment": profile.get("environment", ""),
            "trains_available": profile.get("trains", ""),
            "advertising_budget": profile.get("advertisement_budget", ""),
            "upgrade_staffroom_size": upgrades.get("staff_room", ""),
            "upgrade_storage_size": upgrades.get("storage", ""),
            "upgrade_storage_space": upgrades.get("storage_capacity", ""),
            "total_wage": total_wage,
            "avg_employee_effectiveness": (
                round(sum(effectiveness) / len(effectiveness), 2) if effectiveness else 0
            ),
            "daily_stockcost": daily_stock_cost,
            "avg_daily_profit_7day": compute_avg_daily_profit_7day(
                previous_company, timestamp, profit["daily_profit"]
            ),
            "avg_daily_income_7day": compute_avg_daily_income_7day(
                previous_company, timestamp, daily_income
            ),
            "monthly_income": compute_monthly_income(previous_company, timestamp, daily_income),
            "monthly_profit": compute_monthly_profit(
                previous_company, timestamp, profit["daily_profit"]
            ),
            "rank_by_income": rank if rank is not None else "",
            "rank_total_in_type": total_in_type or "",
            "rank_percentile": (
                round((total_in_type - rank + 1) / total_in_type * 100, 1)
                if rank and total_in_type
                else ""
            ),
            "rank_trend": rank_trend,
            "star_10_count": count_10_star_companies(ranked),
            "income_to_reach_10_star": (
                star["income_to_reach_next_star"]
                if star["income_to_reach_next_star"] is not None
                else ""
            ),
            "income_buffer_before_9_star": (
                star["income_to_drop_to_previous_star"]
                if star["income_to_drop_to_previous_star"] is not None
                else ""
            ),
            **{key: value if value is not None else "" for key, value in star.items()},
        }
        ranking_rows = [
            {
                "rank": index + 1,
                "id": company.get("id", ""),
                "name": company.get("name", ""),
                "rating": company.get("rating", ""),
                "daily_income": (company.get("income") or {}).get("daily", ""),
                "weekly_income": (company.get("income") or {}).get("weekly", ""),
                "is_own_company": str(company.get("id")) == str(own_id),
            }
            for index, company in enumerate(ranked)
        ]
        director_rows: list[JsonObject] = []
        if self._tornstats:
            try:
                response = await self._tornstats.get_efficiency()
                known = {
                    str((employee.get("position") or {}).get("name"))
                    for employee in employees
                    if isinstance(employee.get("position"), dict)
                    and (employee.get("position") or {}).get("name")
                }
                block, _ = find_company_type_block(
                    response, known, company_type_id, company_type_name
                )
                if block:
                    director_rows = [
                        {
                            "timestamp": timestamp,
                            "date": _date(timestamp),
                            "position": position,
                            "efficiency": value,
                        }
                        for position, value in block.items()
                        if position != "company"
                    ]
            except Exception:
                pass
        await _event(
            progress,
            operation,
            "calculations",
            ProgressState.RUNNING,
            "Calculations complete",
            5,
            6,
        )
        is_update = bool(
            previous_company
            and _period_start(previous_company[-1].get("timestamp")) == _period_start(timestamp)
        )
        await self._repository.save_snapshot(
            request.workspace_id,
            request.company_id,
            SnapshotData(
                timestamp=timestamp,
                company=company_row,
                employees=employee_rows,
                stock=stock_rows,
                rankings=ranking_rows,
                director_efficiency=director_rows,
            ),
            is_update=is_update,
        )
        await _event(progress, operation, "persist", ProgressState.RUNNING, "Snapshot saved", 6, 6)
        return SnapshotResult(
            company_name=str(profile.get("name") or ""),
            employee_count=len(employee_rows),
            stock_count=len(stock_rows),
            is_update=is_update,
        )


class EmployeeEfficiencyWorkflow:
    def __init__(
        self,
        torn: TornGateway,
        tornstats: TornStatsGateway,
        repository: CompanyDataRepository,
    ) -> None:
        self._torn = torn
        self._tornstats = tornstats
        self._repository = repository

    async def run(
        self,
        request: CollectionRequest,
        progress: ProgressCallback | None = None,
    ) -> EmployeeEfficiencyResult:
        operation = Operation.EMPLOYEE_EFFICIENCY
        await _event(
            progress, operation, "starting", ProgressState.STARTED, "Efficiency run started"
        )
        try:
            result = await self._run(request, progress)
        except Exception:
            await _event(
                progress, operation, "failed", ProgressState.FAILED, "Efficiency run failed"
            )
            raise
        await _event(
            progress, operation, "completed", ProgressState.SUCCEEDED, "Efficiency run complete"
        )
        return result

    async def _run(
        self, request: CollectionRequest, progress: ProgressCallback | None
    ) -> EmployeeEfficiencyResult:
        operation = Operation.EMPLOYEE_EFFICIENCY
        profile = (await self._torn.get_company_profile()).profile
        await _event(progress, operation, "profile", ProgressState.RUNNING, "Profile fetched", 1, 3)
        employees = (await self._torn.get_company_employees()).employees
        timestamp = (await self._torn.get_company_timestamp()).timestamp
        await _event(
            progress, operation, "employees", ProgressState.RUNNING, "Employees fetched", 2, 3
        )
        known_positions = {
            str((employee.get("position") or {}).get("name"))
            for employee in employees
            if isinstance(employee.get("position"), dict)
            and (employee.get("position") or {}).get("name")
        }
        type_id, type_name = _profile_type(profile)
        rows: list[JsonObject] = []
        positions: set[str] = set()
        methods: set[str] = set()
        total_employees = max(len(employees), 1)
        for index, employee in enumerate(employees, 1):
            stats = employee.get("stats") or {}
            stats = stats if isinstance(stats, dict) else {}
            projected: dict[str, float] = {}
            try:
                response = await self._tornstats.get_efficiency(
                    _optional_int(stats.get("manual_labor")),
                    _optional_int(stats.get("intelligence")),
                    _optional_int(stats.get("endurance")),
                )
                block, method = find_company_type_block(
                    response, known_positions, type_id, type_name
                )
                methods.add(method)
                if block:
                    for position, value in block.items():
                        if position in NON_POSITION_KEYS:
                            continue
                        try:
                            projected[position] = float(value)
                        except (TypeError, ValueError):
                            continue
                    positions.update(projected)
            except Exception:
                methods.add("none")
            rows.append(build_employee_row(employee, projected))
            await _event(
                progress,
                operation,
                "projections",
                ProgressState.RUNNING,
                f"Projected employee {index} of {len(employees)}",
                index,
                total_employees,
            )
        position_names = sorted(positions) if positions else sorted(known_positions)
        employee_block = profile.get("employees") or {}
        employee_block = employee_block if isinstance(employee_block, dict) else {}
        warnings = assign_positions(
            rows,
            position_names,
            request.position_capacities,
            _optional_int(employee_block.get("capacity")),
            request.position_priority_order,
            request.locked_employee_ids,
        )
        misplaced_count = 0
        for row in rows:
            row["misplaced_flag"] = is_employee_misplaced(row)
            misplaced_count += int(bool(row["misplaced_flag"]))
            wage = _number(row.get("wage"))
            total = _number(row.get("effectiveness_total"))
            row["wage_efficiency"] = round(wage / total, 2) if total else ""
        wage_values = [
            _number(row["wage_efficiency"])
            for row in rows
            if row.get("wage_efficiency") not in (None, "")
        ]
        average_wage = sum(wage_values) / len(wage_values) if wage_values else 0
        for row in rows:
            value = row.get("wage_efficiency")
            row["wage_efficiency_flag"] = bool(
                value not in (None, "") and average_wage and _number(value) >= average_wage * 1.5
            )
        previous = await self._repository.load_employee_effectiveness(
            request.workspace_id, request.company_id
        )
        previous_by_id = {
            str(row.get("tId")): row for row in previous if row.get("tId") is not None
        }
        current_by_id = {str(row.get("tId")): row for row in rows if row.get("tId") is not None}
        turnover = [
            {
                "timestamp": timestamp,
                "date": _date(timestamp),
                "tId": employee_id,
                "name": current_by_id[employee_id].get("name", ""),
                "event": "joined",
                "position": current_by_id[employee_id].get("current_position", ""),
            }
            for employee_id in current_by_id.keys() - previous_by_id.keys()
        ]
        turnover.extend(
            {
                "timestamp": timestamp,
                "date": _date(timestamp),
                "tId": employee_id,
                "name": previous_by_id[employee_id].get("name", ""),
                "event": "left",
                "position": previous_by_id[employee_id].get("current_position", ""),
            }
            for employee_id in previous_by_id.keys() - current_by_id.keys()
        )
        base_headers, base_rows = build_position_efficiency_rows(rows, position_names)
        total_headers, total_rows = build_total_effectiveness_projection_rows(rows, position_names)
        note = ""
        if not methods or methods == {"none"}:
            note = "Torn Stats returned no matching company-type projections."
        elif methods != {"id"}:
            fallbacks = ", ".join(sorted(methods - {"id"}))
            note = f"Position projections used fallback matching ({fallbacks})."
        if warnings:
            note = " ".join(part for part in [note, *warnings] if part)
        await self._repository.save_employee_efficiency(
            request.workspace_id,
            request.company_id,
            EmployeeEfficiencyData(
                timestamp=timestamp,
                employees=rows,
                position_names=position_names,
                position_efficiency=[
                    dict(zip(base_headers, values, strict=True)) for values in base_rows
                ],
                total_effectiveness_projections=[
                    dict(zip(total_headers, values, strict=True)) for values in total_rows
                ],
                turnover=turnover,
            ),
        )
        await _event(
            progress, operation, "persist", ProgressState.RUNNING, "Efficiency saved", 3, 3
        )
        return EmployeeEfficiencyResult(
            company_name=str(profile.get("name") or ""),
            employee_count=len(rows),
            misplaced_count=misplaced_count,
            verification_note=note,
        )


class RunEverythingWorkflow:
    def __init__(
        self,
        snapshot: SnapshotWorkflow,
        efficiency: EmployeeEfficiencyWorkflow,
    ) -> None:
        self._snapshot = snapshot
        self._efficiency = efficiency

    async def run(
        self,
        request: CollectionRequest,
        progress: ProgressCallback | None = None,
    ) -> EverythingResult:
        operation = Operation.RUN_EVERYTHING
        await _event(
            progress, operation, "starting", ProgressState.STARTED, "Run Everything started"
        )
        try:
            await _event(
                progress, operation, "snapshot", ProgressState.RUNNING, "Running snapshot", 1, 2
            )
            snapshot = await self._snapshot.run(request, progress)
            await _event(
                progress,
                operation,
                "efficiency",
                ProgressState.RUNNING,
                "Running efficiency",
                2,
                2,
            )
            efficiency = await self._efficiency.run(request, progress)
        except Exception:
            await _event(
                progress, operation, "failed", ProgressState.FAILED, "Run Everything failed"
            )
            raise
        await _event(
            progress, operation, "completed", ProgressState.SUCCEEDED, "Run Everything complete"
        )
        return EverythingResult(snapshot=snapshot, employee_efficiency=efficiency)


class ImportHistoryWorkflow:
    def __init__(self, workbook: WorkbookPort, repository: CompanyDataRepository) -> None:
        self._workbook = workbook
        self._repository = repository

    async def run(
        self,
        request: CollectionRequest,
        content: bytes,
        progress: ProgressCallback | None = None,
    ) -> ImportHistoryResult:
        operation = Operation.IMPORT_HISTORY
        await _event(progress, operation, "starting", ProgressState.STARTED, "Import started")
        try:
            records = await self._workbook.parse_history(content)
            await _event(
                progress,
                operation,
                "validate",
                ProgressState.RUNNING,
                "Workbook validated",
                1,
                2,
            )
            result = await self._repository.import_history(
                request.workspace_id, request.company_id, records
            )
            await _event(
                progress, operation, "persist", ProgressState.RUNNING, "History imported", 2, 2
            )
        except Exception:
            await _event(progress, operation, "failed", ProgressState.FAILED, "Import failed")
            raise
        await _event(progress, operation, "completed", ProgressState.SUCCEEDED, "Import complete")
        return result


class ScheduledCollectionWorkflow:
    def __init__(
        self,
        snapshot: SnapshotWorkflow,
        efficiency: EmployeeEfficiencyWorkflow,
        everything: RunEverythingWorkflow,
    ) -> None:
        self._snapshot = snapshot
        self._efficiency = efficiency
        self._everything = everything

    async def run(
        self,
        request: CollectionRequest,
        operation: Operation,
        progress: ProgressCallback | None = None,
    ) -> ScheduledCollectionResult:
        if operation not in {
            Operation.SNAPSHOT,
            Operation.EMPLOYEE_EFFICIENCY,
            Operation.RUN_EVERYTHING,
        }:
            raise ValueError("scheduled collection supports collection operations only")
        wrapper = Operation.SCHEDULED_COLLECTION
        await _event(
            progress, wrapper, "starting", ProgressState.STARTED, "Scheduled collection started"
        )
        await _event(progress, wrapper, "dispatch", ProgressState.RUNNING, f"Running {operation}")
        result: SnapshotResult | EmployeeEfficiencyResult | EverythingResult
        try:
            if operation == Operation.SNAPSHOT:
                result = await self._snapshot.run(request, progress)
            elif operation == Operation.EMPLOYEE_EFFICIENCY:
                result = await self._efficiency.run(request, progress)
            else:
                result = await self._everything.run(request, progress)
        except Exception:
            await _event(
                progress,
                wrapper,
                "failed",
                ProgressState.FAILED,
                "Scheduled collection failed",
            )
            raise
        await _event(
            progress, wrapper, "completed", ProgressState.SUCCEEDED, "Scheduled collection complete"
        )
        return ScheduledCollectionResult(operation=operation, result=result)
