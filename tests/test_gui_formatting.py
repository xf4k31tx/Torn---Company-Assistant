from __future__ import annotations

from gui.main_window import (
    DEFAULT_VISIBLE_EMPLOYEE_COLUMNS,
    EMPLOYEE_FOOTER_TOTAL_COLUMNS,
    EMPLOYEE_TABLE_COLUMNS,
    build_employee_info_card_fields,
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
    assert position_efficiency_score_style(98)[:2] == ("98", "#f9c74f")
    assert position_efficiency_score_style(99)[:2] == ("99", "#66bb6a")
    assert position_efficiency_score_style(128)[:2] == ("128", "#66bb6a")
    assert position_efficiency_score_style(129)[:2] == ("129", "#1b5e20")


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


# ---------------------------------------------------------------------------
# Regression coverage for a real bug: EMPLOYEE_FOOTER_TOTAL_COLUMNS and
# DEFAULT_VISIBLE_EMPLOYEE_COLUMNS are hand-typed literal sets of field keys
# that must line up with EMPLOYEE_TABLE_COLUMNS (the single source of truth
# for valid employee field keys). The "Current Eff." column's totals footer
# was silently blank because this set referenced "effectiveness_working_stats"
# instead of the field the column actually displays,
# "projected_efficiency_current_position" - and separately, the "Education
# Eff." column was silently excluded from the default column view because
# DEFAULT_VISIBLE_EMPLOYEE_COLUMNS had "effectiveness_education" instead of
# the real key "effectiveness_director_education". Both were membership-only
# typos with no error at import time or runtime - only a visibly blank/
# missing cell - so these tests both pin the specific fix and, more
# importantly, guard the whole set against the same class of typo recurring
# for any other column in the future.
# ---------------------------------------------------------------------------

def _valid_employee_column_keys():
    return {key for _, key in EMPLOYEE_TABLE_COLUMNS}


def test_employee_footer_total_columns_are_all_valid_table_keys():
    """Guard: every key in EMPLOYEE_FOOTER_TOTAL_COLUMNS must be a real,
    currently-defined employee column key. A key that doesn't match any
    EMPLOYEE_TABLE_COLUMNS entry can never be reached by the footer
    renderer's `if column in EMPLOYEE_FOOTER_TOTAL_COLUMNS` check, so it
    would be silent dead weight - and, more importantly, a *valid* column
    whose intended total key was mistyped would fail this the same way the
    original bug did."""
    valid_keys = _valid_employee_column_keys()
    unknown_keys = EMPLOYEE_FOOTER_TOTAL_COLUMNS - valid_keys

    assert not unknown_keys, (
        f"EMPLOYEE_FOOTER_TOTAL_COLUMNS references key(s) not present in "
        f"EMPLOYEE_TABLE_COLUMNS: {sorted(unknown_keys)}"
    )


def test_current_position_projected_efficiency_column_has_a_footer_total():
    """Regression for the reported bug: the 'Current\\nEff.' column (backed
    by field key 'projected_efficiency_current_position') must be one of
    the columns the Employees tab totals footer computes a value for."""
    labels = {key: label for label, key in EMPLOYEE_TABLE_COLUMNS}

    assert labels["projected_efficiency_current_position"] == "Current\nEff."
    assert "projected_efficiency_current_position" in EMPLOYEE_FOOTER_TOTAL_COLUMNS

    rows = [
        {"projected_efficiency_current_position": 120},
        {"projected_efficiency_current_position": "95.5"},
        {"projected_efficiency_current_position": ""},
    ]
    assert employee_footer_total(rows, "projected_efficiency_current_position") == "215.5"


def test_default_visible_employee_columns_are_all_valid_table_keys():
    """Guard: every key in DEFAULT_VISIBLE_EMPLOYEE_COLUMNS must be a real,
    currently-defined employee column key. _build_employees_tab() computes
    the default visible column list by iterating EMPLOYEE_TABLE_COLUMNS and
    keeping only keys that are `in DEFAULT_VISIBLE_EMPLOYEE_COLUMNS` - a
    mistyped key here silently drops that column from the first-run/reset
    default view with no error anywhere."""
    valid_keys = _valid_employee_column_keys()
    unknown_keys = DEFAULT_VISIBLE_EMPLOYEE_COLUMNS - valid_keys

    assert not unknown_keys, (
        f"DEFAULT_VISIBLE_EMPLOYEE_COLUMNS references key(s) not present in "
        f"EMPLOYEE_TABLE_COLUMNS: {sorted(unknown_keys)}"
    )


def test_education_effectiveness_column_is_visible_by_default():
    """Regression for the reported bug: 'Education\\nEff.' (field key
    'effectiveness_director_education') must be part of the default
    visible-column set, matching every other effectiveness-breakdown
    column it's grouped alongside."""
    labels = {key: label for label, key in EMPLOYEE_TABLE_COLUMNS}

    assert labels["effectiveness_director_education"] == "Education\nEff."
    assert "effectiveness_director_education" in DEFAULT_VISIBLE_EMPLOYEE_COLUMNS


def test_default_visible_employee_columns_resolve_in_table_order():
    """End-to-end check of the actual selection logic used in
    _build_employees_tab(): iterating EMPLOYEE_TABLE_COLUMNS and filtering
    by DEFAULT_VISIBLE_EMPLOYEE_COLUMNS should yield exactly the intended
    default columns, in table order, with none silently dropped."""
    resolved = [key for _, key in EMPLOYEE_TABLE_COLUMNS if key in DEFAULT_VISIBLE_EMPLOYEE_COLUMNS]

    assert set(resolved) == DEFAULT_VISIBLE_EMPLOYEE_COLUMNS
    assert "effectiveness_director_education" in resolved


# ---------------------------------------------------------------------------
# Employee info card popup (Position Efficiency tab -> click a Name cell).
# ---------------------------------------------------------------------------

def test_employee_info_card_fields_use_current_eff_terminology():
    """'Current Eff.' on the card must be the same field/terminology as the
    Employees and Position Efficiency tabs' own 'Current Eff.' column
    (projected_efficiency_current_position, Tornstats' projection) -
    NOT Torn's own effectiveness_working_stats ('Work Stats Eff.')."""
    record = {
        "tId": "123",
        "name": "Jane Doe",
        "last_action_ts": 0,
        "manual_labor": 100000,
        "endurance": 300000,
        "intelligence": 50000,
        "current_position": "Stylist",
        "projected_efficiency_current_position": 165,
        "effectiveness_working_stats": 40,
        "effectiveness_total": 187,
    }

    fields = dict(build_employee_info_card_fields(record))

    assert fields["Current Eff."] == "165"
    assert fields["Total Eff."] == "187"
    assert "Work Stats Eff." not in fields


def test_employee_info_card_fields_full_layout_and_formatting():
    record = {
        "name": "Jane Doe",
        "last_action_ts": 0,
        "manual_labor": 1234567,
        "endurance": 300000,
        "intelligence": 50000,
        "current_position": "Stylist",
        "projected_efficiency_current_position": 165,
        "effectiveness_total": 187,
    }

    fields = build_employee_info_card_fields(record)
    labels = [label for label, _ in fields]

    assert labels == [
        "Name", "ID", "Last Online", "Manual Labor", "Endurance", "Intelligence",
        "Current Position", "Current Eff.", "Total Eff.",
    ]
    values = dict(fields)
    assert values["Name"] == "Jane Doe"
    assert values["Manual Labor"] == "1,234,567"  # comma-formatted, matches format_int
    assert values["Current Position"] == "Stylist"


def test_employee_info_card_fields_handle_missing_record_gracefully():
    """The caller passes None when the lookup by tId misses (stale cache);
    build_employee_info_card_fields must not raise, and every value should
    be a safe blank/placeholder rather than 'None' or a KeyError."""
    fields = dict(build_employee_info_card_fields(None))

    assert fields["Name"] == ""
    assert fields["ID"] == ""
    assert fields["Last Online"] == "Unknown"
    assert fields["Current Position"] == ""


def test_employee_info_card_id_field_shows_tid_labeled_as_id():
    """tId is renamed to 'ID' only for display on the card - the underlying
    record field being read is still 'tId'."""
    fields = dict(build_employee_info_card_fields({"tId": "123456", "name": "Jane Doe"}))

    assert fields["ID"] == "123456"
    assert "tId" not in fields


def test_employee_info_card_fields_unknown_last_online_when_never_active():
    fields = dict(build_employee_info_card_fields({"name": "New Hire", "last_action_ts": ""}))

    assert fields["Last Online"] == "Unknown"
