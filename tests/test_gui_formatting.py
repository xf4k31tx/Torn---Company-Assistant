from __future__ import annotations

from gui.main_window import (
    EMPLOYEE_TABLE_COLUMNS,
    company_selector_values,
    employee_cell_style,
    employee_footer_total,
    format_employee_field,
    position_efficiency_score_style,
    position_efficiency_sort_value,
    scroll_canvas_xview,
)


def test_company_selector_values_are_shared_and_have_empty_fallback():
    companies = [{"name": "Alpha"}, {"name": "Beta"}]

    assert company_selector_values(companies) == ["Alpha", "Beta"]
    assert company_selector_values([]) == ["(No companies configured)"]


def test_employee_footer_totals_numeric_values_and_skips_missing_values():
    rows = [
        {"wage": 100_000, "effectiveness_total": 120, "effectiveness_addiction": -10},
        {"wage": "50,000", "effectiveness_total": "80.5", "effectiveness_addiction": ""},
        {"wage": 25_000, "effectiveness_total": None, "effectiveness_addiction": -5},
    ]

    assert employee_footer_total(rows, "wage") == "175,000"
    assert employee_footer_total(rows, "effectiveness_total") == "200.5"
    assert employee_footer_total(rows, "effectiveness_addiction") == "-15"
    assert employee_footer_total(rows, "assigned_efficiency") == ""


def test_horizontal_canvas_scroll_flushes_redraws():
    calls = []

    class Canvas:
        def xview(self, *args):
            calls.append(("xview", args))

        def update_idletasks(self):
            calls.append(("update_idletasks", ()))

    scroll_canvas_xview(Canvas(), "moveto", "0.5")

    assert calls == [
        ("xview", ("moveto", "0.5")),
        ("update_idletasks", ()),
    ]


def test_time_since_last_action_column_uses_elapsed_time(monkeypatch):
    monkeypatch.setattr("gui.main_window.time.time", lambda: 1_000_000)

    assert format_employee_field(
        "time_since_last_action", {"last_action_ts": 1_000_000 - (2 * 86400 + 4 * 3600)}
    ) == "2d 4h ago"


def test_time_since_last_action_column_is_backed_by_timestamp():
    labels = {key: label for label, key in EMPLOYEE_TABLE_COLUMNS}

    assert labels["time_since_last_action"] == "Time Since\nLast Action"
    assert "last_action_ts" not in labels


def test_position_efficiency_score_bands_and_boundaries():
    assert position_efficiency_score_style(49)[:2] == ("49", "#c62828")
    assert position_efficiency_score_style(50)[:2] == ("50", "#ef6c00")
    assert position_efficiency_score_style(74)[:2] == ("74", "#ef6c00")
    assert position_efficiency_score_style(75)[:2] == ("75", "#f9c74f")
    assert position_efficiency_score_style(99)[:2] == ("99", "#f9c74f")
    assert position_efficiency_score_style(100)[:2] == ("100", "#66bb6a")
    assert position_efficiency_score_style(124)[:2] == ("124", "#66bb6a")
    assert position_efficiency_score_style(125)[:2] == ("125", "#1b5e20")


def test_position_efficiency_missing_values_are_blank():
    assert position_efficiency_score_style("")[0] == ""
    assert position_efficiency_score_style(None)[0] == ""
    assert position_efficiency_score_style("not-a-number")[0] == ""


def test_addiction_and_inactivity_warning_threshold():
    assert format_employee_field("effectiveness_addiction", {"effectiveness_addiction": -10}) == "\u26a0 -10"
    assert format_employee_field("effectiveness_inactivity", {"effectiveness_inactivity": -11}) == "\u26a0 -11"
    assert format_employee_field("effectiveness_addiction", {"effectiveness_addiction": -9}) == "-9"
    assert format_employee_field("effectiveness_inactivity", {"effectiveness_inactivity": ""}) == ""


def test_employee_position_cell_reflects_assignment_match():
    assert employee_cell_style("current_position", {
        "current_position": "Director", "assigned_position": "Director",
    }) == ("#d4edda", "#155724")
    assert employee_cell_style("current_position", {
        "current_position": "Director", "assigned_position": "Accountant",
    }) == ("#f8d7da", "#721c24")
    assert employee_cell_style("current_position", {
        "current_position": "Director", "assigned_position": "",
    }) == ("#ffffff", "#000000")


def test_employee_addiction_and_inactivity_cell_colors():
    assert employee_cell_style(
        "effectiveness_addiction", {"effectiveness_addiction": -10}
    ) == ("#f8d7da", "#721c24")
    assert employee_cell_style(
        "effectiveness_inactivity", {"effectiveness_inactivity": -11}
    ) == ("#f8d7da", "#721c24")
    assert employee_cell_style(
        "effectiveness_addiction", {"effectiveness_addiction": -9}
    ) == ("#ffffff", "#000000")


def test_position_efficiency_sorting_is_numeric():
    rows = [{"Director": "9"}, {"Director": "100"}, {"Director": "42"}, {"Director": ""}]

    ordered = sorted(rows, key=lambda row: position_efficiency_sort_value(row, "Director"))

    assert [row["Director"] for row in ordered] == ["", "9", "42", "100"]
