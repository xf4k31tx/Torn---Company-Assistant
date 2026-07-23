from __future__ import annotations

from app.efficiency_calc import assign_positions
from gui import main_window
from gui.main_window import MainWindow, employee_position_is_locked


def _row(employee_id, current_position, **projected):
    return {
        "tId": str(employee_id),
        "current_position": current_position,
        "projected": projected,
        "assigned_position": "",
        "assigned_efficiency": "",
    }


def test_locked_employee_keeps_current_position_and_consumes_its_seat():
    rows = [
        _row(1, "Director", Director=40, Trainer=120),
        _row(2, "Trainer", Director=110, Trainer=90),
        _row(3, "Trainer", Director=100, Trainer=80),
    ]

    assign_positions(
        rows,
        ["Director", "Trainer"],
        {"Director": 1, "Trainer": 2},
        total_capacity=3,
        priority_order=["Director", "Trainer"],
        locked_employee_ids={"1"},
    )

    assert rows[0]["assigned_position"] == "Director"
    assert rows[0]["assigned_efficiency"] == 40
    assert rows[1]["assigned_position"] == "Trainer"
    assert rows[2]["assigned_position"] == "Trainer"


def test_locked_employees_are_hard_constraints_when_over_capacity():
    rows = [
        _row(1, "Director", Director=40),
        _row(2, "Director", Director=50),
        _row(3, "Trainer", Director=120),
    ]

    warnings = assign_positions(
        rows,
        ["Director"],
        {"Director": 1},
        locked_employee_ids={"1", "2"},
    )

    assert [row["assigned_position"] for row in rows] == ["Director", "Director", ""]
    assert warnings == ["2 locked employees exceed the Director capacity of 1."]


def test_stale_lock_is_ignored_and_unlock_restores_normal_assignment():
    rows = [
        _row(1, "Director", Director=40),
        _row(2, "Trainer", Director=110),
    ]

    assign_positions(
        rows,
        ["Director"],
        {"Director": 1},
        locked_employee_ids={"999"},
    )

    assert rows[0]["assigned_position"] == ""
    assert rows[1]["assigned_position"] == "Director"


def test_locked_position_without_projection_keeps_position_with_blank_efficiency():
    rows = [_row(1, "Director", Trainer=90)]

    assign_positions(
        rows,
        ["Director", "Trainer"],
        {"Director": 1, "Trainer": 1},
        locked_employee_ids={"1"},
    )

    assert rows[0]["assigned_position"] == "Director"
    assert rows[0]["assigned_efficiency"] == ""


def test_lock_helper_normalizes_employee_ids():
    assert employee_position_is_locked({"tId": 123}, ["123"])
    assert not employee_position_is_locked({"tId": "456"}, ["123"])
    assert not employee_position_is_locked({"tId": ""}, [""])


def test_position_lock_toggle_persists_on_active_company(monkeypatch):
    company = {"name": "Test Company", "locked_employee_ids": []}
    saved = []
    monkeypatch.setattr(main_window.companies_mod, "save_companies", lambda companies: saved.append(companies))

    window = object.__new__(MainWindow)
    window.companies = [company]
    window._active_company = lambda: company
    window._employee_sort_column = None

    class LockVar:
        value = True

        def get(self):
            return self.value

        def set(self, value):
            self.value = value

    lock_var = LockVar()
    window._set_employee_position_lock(
        {"tId": "123", "current_position": "Director"}, lock_var
    )

    assert company["locked_employee_ids"] == ["123"]
    assert saved[-1] is window.companies

    lock_var.value = False
    window._set_employee_position_lock(
        {"tId": "123", "current_position": "Director"}, lock_var
    )

    assert company["locked_employee_ids"] == []
