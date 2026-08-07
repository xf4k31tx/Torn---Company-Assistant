from __future__ import annotations

from typing import Any, Literal

from tca_web.application.contracts import JsonObject

NON_POSITION_KEYS = {"company", "stats", "status", "message"}
type MatchMethod = Literal["id", "name", "heuristic", "none"]


def find_company_type_block(
    response: JsonObject,
    known_positions: set[str],
    expected_type_id: int | None = None,
    expected_type_name: str | None = None,
) -> tuple[JsonObject | None, MatchMethod]:
    if expected_type_id is not None:
        candidate = response.get(str(expected_type_id))
        if isinstance(candidate, dict) and "company" in candidate:
            return candidate, "id"
    if expected_type_name:
        wanted = expected_type_name.strip().casefold()
        for key, candidate in response.items():
            if (
                key not in NON_POSITION_KEYS
                and isinstance(candidate, dict)
                and str(candidate.get("company", "")).strip().casefold() == wanted
            ):
                return candidate, "name"
    matches: list[JsonObject] = []
    if known_positions:
        for key, candidate in response.items():
            if key in NON_POSITION_KEYS or not isinstance(candidate, dict):
                continue
            positions = set(candidate) - {"company"}
            if known_positions.issubset(positions):
                matches.append(candidate)
    if matches:
        return min(matches, key=lambda block: len(set(block) - {"company"})), "heuristic"
    return None, "none"


def build_employee_row(employee: JsonObject, projected: dict[str, float]) -> JsonObject:
    stats = employee.get("stats") or {}
    effectiveness = employee.get("effectiveness") or {}
    position = employee.get("position") or {}
    stats = stats if isinstance(stats, dict) else {}
    effectiveness = effectiveness if isinstance(effectiveness, dict) else {}
    position = position if isinstance(position, dict) else {}
    current_position = str(position.get("name") or "")
    last_action = employee.get("last_action")
    last_action_ts = (
        last_action.get("timestamp", "") if isinstance(last_action, dict) else last_action
    )
    best_position: str | Any = ""
    best_value: float | str = ""
    if projected:
        best_position, best_value = max(projected.items(), key=lambda item: item[1])
    return {
        "tId": employee.get("id"),
        "name": employee.get("name", ""),
        "current_position": current_position,
        "wage": employee.get("wage", 0),
        "days_in_company": employee.get("days_in_company", ""),
        "last_action_ts": last_action_ts,
        "manual_labor": stats.get("manual_labor", ""),
        "intelligence": stats.get("intelligence", ""),
        "endurance": stats.get("endurance", ""),
        "effectiveness_total": effectiveness.get("total", 0),
        "effectiveness_working_stats": effectiveness.get("working_stats", 0),
        "effectiveness_settled_in": effectiveness.get("settled_in", 0),
        "effectiveness_director_education": effectiveness.get("director_education", 0),
        "effectiveness_addiction": effectiveness.get("addiction", 0),
        "effectiveness_inactivity": effectiveness.get("inactivity", 0),
        "effectiveness_management": effectiveness.get("management", 0),
        "effectiveness_book": effectiveness.get("book", 0),
        "effectiveness_merits": effectiveness.get("merits", 0),
        "projected_efficiency_current_position": projected.get(current_position, ""),
        "best_fit_position": best_position,
        "best_fit_efficiency": best_value,
        "assigned_position": "",
        "assigned_efficiency": "",
        "projected": projected,
    }


def assign_positions(
    rows: list[JsonObject],
    position_names: list[str],
    capacities: dict[str, int],
    total_capacity: int | None = None,
    priority_order: list[str] | None = None,
    locked_employee_ids: set[str] | None = None,
) -> list[str]:
    ordered = [position for position in (priority_order or []) if position in position_names]
    ordered.extend(position for position in position_names if position not in ordered)
    locked = {str(employee_id) for employee_id in (locked_employee_ids or set())}
    assigned = [False] * len(rows)
    filled: dict[str, int] = {}
    total = 0
    for index, row in enumerate(rows):
        employee_id = str(row.get("tId") or "")
        current = str(row.get("current_position") or "").strip()
        if employee_id not in locked or not current:
            continue
        projected = row.get("projected") or {}
        row["assigned_position"] = current
        row["assigned_efficiency"] = (
            projected.get(current, "") if isinstance(projected, dict) else ""
        )
        assigned[index] = True
        filled[current] = filled.get(current, 0) + 1
        total += 1
    warnings = [
        f"{count} locked employees exceed the {position} capacity of {capacities[position]}."
        for position, count in sorted(filled.items())
        if position in capacities and count > capacities[position]
    ]
    if total_capacity is not None and total > total_capacity:
        warnings.append(
            f"{total} locked employees exceed the company capacity of {total_capacity}."
        )
    for position in ordered:
        if total_capacity is not None and total >= total_capacity:
            break
        candidates: list[tuple[float, int]] = []
        for index, row in enumerate(rows):
            projected = row.get("projected") or {}
            if not assigned[index] and isinstance(projected, dict) and position in projected:
                try:
                    candidates.append((float(projected[position]), index))
                except (TypeError, ValueError):
                    continue
        candidates.sort(reverse=True)
        count = filled.get(position, 0)
        cap = capacities.get(position)
        for effectiveness, index in candidates:
            if cap is not None and count >= cap:
                break
            if total_capacity is not None and total >= total_capacity:
                break
            rows[index]["assigned_position"] = position
            rows[index]["assigned_efficiency"] = effectiveness
            assigned[index] = True
            count += 1
            total += 1
    return warnings


def is_employee_misplaced(row: JsonObject) -> bool:
    current = str(row.get("current_position") or "").strip()
    assigned = str(row.get("assigned_position") or "").strip()
    return bool(current and assigned and current != assigned)


def build_position_efficiency_rows(
    rows: list[JsonObject], position_names: list[str]
) -> tuple[list[str], list[list[Any]]]:
    headers = ["tId", "name", "current_position", *position_names]
    output = []
    for row in rows:
        projected = row.get("projected") or {}
        projected = projected if isinstance(projected, dict) else {}
        output.append(
            [row.get("tId"), row.get("name", ""), row.get("current_position", "")]
            + [projected.get(position, "") for position in position_names]
        )
    return headers, output


def build_total_effectiveness_projection_rows(
    rows: list[JsonObject], position_names: list[str]
) -> tuple[list[str], list[list[Any]]]:
    headers = ["tId", "name", "current_position", *position_names]
    output = []
    for row in rows:
        projected = row.get("projected") or {}
        projected = projected if isinstance(projected, dict) else {}
        try:
            delta = float(row.get("effectiveness_total") or 0) - float(
                row.get("effectiveness_working_stats") or 0
            )
        except (TypeError, ValueError):
            delta = 0.0
        cells: list[float | str] = []
        for position in position_names:
            base = projected.get(position, "")
            try:
                cells.append(float(base) + delta if base not in (None, "") else "")
            except (TypeError, ValueError):
                cells.append("")
        output.append(
            [row.get("tId"), row.get("name", ""), row.get("current_position", ""), *cells]
        )
    return headers, output
