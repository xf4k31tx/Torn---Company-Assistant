from tca_web.domain.efficiency import (
    assign_positions,
    build_employee_row,
    build_position_efficiency_rows,
    build_total_effectiveness_projection_rows,
    find_company_type_block,
    is_employee_misplaced,
)


def row(employee_id: int, current: str, **projected: float) -> dict:
    return {
        "tId": str(employee_id),
        "current_position": current,
        "projected": projected,
        "assigned_position": "",
        "assigned_efficiency": "",
    }


def test_company_type_match_prefers_authoritative_id_over_label() -> None:
    response = {
        "12": {"company": "Oil Company", "Director": 101},
        "99": {"company": "Oil Rig", "Director": 999},
    }
    block, method = find_company_type_block(response, {"Director"}, 12, "Oil Rig")
    assert method == "id"
    assert block == response["12"]


def test_current_effectiveness_is_torn_value_and_projection_stays_separate() -> None:
    employee = {
        "id": 1,
        "name": "Employee",
        "position": {"name": "Director"},
        "effectiveness": {"total": 187, "working_stats": 40},
    }
    result = build_employee_row(employee, {"Director": 94.2, "Trainer": 71.3})
    assert result["effectiveness_working_stats"] == 40
    assert result["projected_efficiency_current_position"] == 94.2
    assert result["best_fit_position"] == "Director"


def test_locked_employee_consumes_current_position_seat() -> None:
    rows = [
        row(1, "Director", Director=40, Trainer=120),
        row(2, "Trainer", Director=110, Trainer=90),
        row(3, "Trainer", Director=100, Trainer=80),
    ]
    assign_positions(
        rows,
        ["Director", "Trainer"],
        {"Director": 1, "Trainer": 2},
        total_capacity=3,
        priority_order=["Director", "Trainer"],
        locked_employee_ids={"1"},
    )
    assert [item["assigned_position"] for item in rows] == ["Director", "Trainer", "Trainer"]


def test_locked_over_capacity_warns_and_misplaced_uses_assignment() -> None:
    rows = [row(1, "Director", Director=40), row(2, "Director", Director=50)]
    warnings = assign_positions(rows, ["Director"], {"Director": 1}, locked_employee_ids={"1", "2"})
    assert warnings == ["2 locked employees exceed the Director capacity of 1."]
    rows[0]["best_fit_position"] = "Trainer"
    assert not is_employee_misplaced(rows[0])
    rows[0]["assigned_position"] = "Trainer"
    assert is_employee_misplaced(rows[0])


def test_projection_tables_preserve_base_and_add_non_working_delta() -> None:
    rows = [
        {
            "tId": "1",
            "name": "Employee",
            "current_position": "Director",
            "effectiveness_total": 187,
            "effectiveness_working_stats": 40,
            "projected": {"Director": 94.2},
        }
    ]
    base_headers, base = build_position_efficiency_rows(rows, ["Director", "Trainer"])
    total_headers, total = build_total_effectiveness_projection_rows(rows, ["Director", "Trainer"])
    assert base_headers == total_headers
    assert base[0][3:] == [94.2, ""]
    assert total[0][3:] == [241.2, ""]
