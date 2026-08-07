from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from gui.main_window import (
    DEFAULT_VISIBLE_EMPLOYEE_COLUMNS,
    EMPLOYEE_EFFECTIVENESS_EXPLAINED_COLUMNS,
    EMPLOYEE_FOOTER_TOTAL_COLUMNS,
    EMPLOYEE_INFO_CARD_EXPLAINED_LABELS,
    EMPLOYEE_TABLE_COLUMNS,
    FIELD_EXPLANATIONS,
    MainWindow,
    build_employee_info_card_fields,
    calculate_popup_geometry,
    company_selector_values,
    derive_star_progress,
    employee_cell_style,
    employee_footer_total,
    format_employee_field,
    format_field,
    format_star_progress,
    open_single_instance_popup,
    position_efficiency_score_style,
    position_efficiency_sort_value,
    rank_neighbors_from_sheet_rows,
    scroll_canvas_xview,
    select_recent_stock_history_rows,
    sort_company_ranking_rows,
)


def test_popup_geometry_is_centered_and_clamped_inside_parent():
    assert calculate_popup_geometry(
        100, 200, 800, 600, 400, 300
    ) == (400, 300, 300, 350)
    assert calculate_popup_geometry(
        100, 200, 800, 600, 1000, 900
    ) == (776, 576, 112, 212)
    assert calculate_popup_geometry(
        -900, 50, 700, 500, 300, 200
    ) == (300, 200, -700, 200)


def test_single_instance_popup_focuses_existing_then_reopens_after_close(
    bare_main_window,
):
    created = []

    def factory():
        popup = tk.Toplevel(bare_main_window)
        created.append(popup)
        return popup

    first = open_single_instance_popup(bare_main_window, "test-popup", factory)
    second = open_single_instance_popup(bare_main_window, "test-popup", factory)

    assert second is first
    assert len(created) == 1

    first.destroy()
    bare_main_window.update_idletasks()

    third = open_single_instance_popup(bare_main_window, "test-popup", factory)
    try:
        assert third is not first
        assert len(created) == 2
    finally:
        third.destroy()


def test_company_selector_values_are_shared_and_have_empty_fallback():
    companies = [{"name": "Alpha"}, {"name": "Beta"}]

    assert company_selector_values(companies) == ["Alpha", "Beta"]
    assert company_selector_values([]) == ["(No companies configured)"]


def test_overview_income_to_reach_10_star_is_currency():
    assert format_field("income_to_reach_10_star", 5_250_000, "Company_History") == "$5,250,000"


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


# ---------------------------------------------------------------------------
# Phase 2: Base vs Total Effectiveness Projections sub-tab independence.
# Both sub-tabs share the same _populate_position_efficiency/_render_
# position_efficiency_rows/_sort_position_efficiency code, keyed by "base"/
# "total" via MainWindow._pe_state(). This is a real-widget smoke test (not
# just a pure-function test) to catch the class of bug where one sub-tab's
# populate/sort call silently clobbers the other's cached rows or sort
# column through shared instance state.
# ---------------------------------------------------------------------------

def _make_bare_main_window():
    """A real, Tcl-backed MainWindow instance without running the full
    __init__ (which loads DPAPI-encrypted settings/companies from disk and
    isn't needed here) - mirrors test_position_locks.py's object.__new__()
    pattern, but uses tk.Tk.__init__ instead of object.__new__ since this
    test needs working Canvas/font machinery, not just plain attribute
    access."""
    window = MainWindow.__new__(MainWindow)
    tk.Tk.__init__(window)
    window.withdraw()
    return window


@pytest.fixture(scope="module")
def bare_main_window():
    """Shared across every real-widget test in this module rather than one
    tk.Tk() per test: repeatedly creating/destroying separate Tk root
    interpreters in the same process is flaky on this Python/Tcl build
    (observed: a second tk.Tk() after an earlier one's .destroy() can fail
    with "couldn't read file scale.tcl" even though the Tcl install is
    fine) - see the module-level note near the top of this file's Phase 2/3
    widget tests. Individual tests are expected to set only the attributes
    they need and not assume any state left behind by another test."""
    window = _make_bare_main_window()
    yield window
    window.destroy()


def test_base_and_total_effectiveness_tabs_stay_independent(bare_main_window):
    window = bare_main_window
    base_records = [
        {"tId": "1", "name": "Bob", "current_position": "Director", "Director": "80", "Trainer": "60"},
        {"tId": "2", "name": "Amy", "current_position": "Trainer", "Director": "50", "Trainer": "90"},
    ]
    total_records = [
        {"tId": "1", "name": "Bob", "current_position": "Director", "Director": "120", "Trainer": "100"},
        {"tId": "2", "name": "Amy", "current_position": "Trainer", "Director": "90", "Trainer": "130"},
    ]
    employee_eff_records = [{"tId": "1", "name": "Bob"}, {"tId": "2", "name": "Amy"}]

    def fake_safe_read(sheet_name):
        if sheet_name == "Position_Efficiency":
            return base_records
        if sheet_name == "Total_Effectiveness_Projections":
            return total_records
        if sheet_name == "Employee_Effectiveness":
            return employee_eff_records
        return []

    window._active_company = lambda: {"last_known_positions": [], "position_efficiency_hidden_positions": []}
    window._employee_info_lookup = {}
    window._position_efficiency_states = {}
    window._position_efficiency_all_positions = []
    window._safe_read = fake_safe_read
    window.base_effectiveness_canvas = tk.Canvas(window)
    window.total_effectiveness_canvas = tk.Canvas(window)

    window._populate_position_efficiency()  # defaults: Position_Efficiency -> base canvas, key="base"
    window._populate_position_efficiency(
        sheet_name="Total_Effectiveness_Projections",
        canvas=window.total_effectiveness_canvas,
        key="total",
    )

    base_state = window._pe_state("base")
    total_state = window._pe_state("total")

    # Each sub-tab kept its own records - neither call clobbered the other.
    assert base_state["records"] == base_records
    assert total_state["records"] == total_records
    assert base_state["records"] != total_state["records"]
    assert base_state["labels"]["name"] == "Name (click for more info)"
    assert total_state["labels"]["name"] == "Name (click for more info)"

    # Both canvases actually got real widget content drawn onto them.
    assert window.base_effectiveness_canvas.find_all()
    assert window.total_effectiveness_canvas.find_all()

    # Sorting the Base tab must not disturb the Total tab's own sort state.
    window._sort_position_efficiency(
        "Director", True, canvas=window.base_effectiveness_canvas, key="base"
    )
    assert base_state["sort_column"] == "Director"
    assert base_state["sort_reverse"] is True
    assert total_state["sort_column"] == "name"
    assert total_state["sort_reverse"] is False

    # The employee info card lookup (shared, same underlying data
    # source for both sub-tabs) is still populated correctly.
    assert window._employee_info_lookup == {
        "1": {"tId": "1", "name": "Bob"},
        "2": {"tId": "2", "name": "Amy"},
    }


# ---------------------------------------------------------------------------
# Phase 3: select_recent_stock_history_rows() - the Stock sub-tab's per-item
# last-7-snapshots view (replaces the old latest-only collapse).
# ---------------------------------------------------------------------------

def _stock_row(name, timestamp, date=None):
    return {"name": name, "timestamp": str(timestamp), "date": date or f"day{timestamp}"}


def test_select_recent_stock_history_caps_at_seven_per_item():
    rows = [_stock_row("Oil Canister", ts) for ts in range(1, 11)]  # 10 snapshots, one item

    result = select_recent_stock_history_rows(rows)

    assert len(result) == 7
    # Newest (highest timestamp) 7 kept, in descending order.
    assert [r["timestamp"] for r in result] == [str(ts) for ts in range(10, 3, -1)]


def test_select_recent_stock_history_groups_by_name_newest_first_within_group():
    rows = [
        _stock_row("Premium Oil", 1), _stock_row("Premium Oil", 3), _stock_row("Premium Oil", 2),
        _stock_row("Oil Canister", 5), _stock_row("Oil Canister", 4),
    ]

    result = select_recent_stock_history_rows(rows)

    # Alphabetical by name first, each item's own rows newest-timestamp-first.
    assert [(r["name"], r["timestamp"]) for r in result] == [
        ("Oil Canister", "5"), ("Oil Canister", "4"),
        ("Premium Oil", "3"), ("Premium Oil", "2"), ("Premium Oil", "1"),
    ]


def test_select_recent_stock_history_respects_custom_count():
    rows = [_stock_row("Oil Canister", ts) for ts in range(1, 6)]

    result = select_recent_stock_history_rows(rows, count=2)

    assert [r["timestamp"] for r in result] == ["5", "4"]


def test_select_recent_stock_history_handles_empty_and_missing_timestamps():
    assert select_recent_stock_history_rows([]) == []

    rows = [{"name": "Item"}, {"name": "Item", "timestamp": "5"}]
    result = select_recent_stock_history_rows(rows)
    # Missing/blank timestamp treated as 0, sorted last (still included since under count=7).
    assert [r.get("timestamp") for r in result] == ["5", None]


def test_select_recent_stock_history_does_not_mix_items_across_the_seven_cap():
    """A single item with more than 7 snapshots must not crowd out another
    item's rows - the cap applies per item, not globally."""
    rows = (
        [_stock_row("Popular Item", ts) for ts in range(1, 12)]  # 11 snapshots
        + [_stock_row("Rare Item", 1)]
    )

    result = select_recent_stock_history_rows(rows)

    popular_count = sum(1 for r in result if r["name"] == "Popular Item")
    rare_count = sum(1 for r in result if r["name"] == "Rare Item")
    assert popular_count == 7
    assert rare_count == 1


def test_populate_stock_shows_per_item_history_not_latest_only(bare_main_window):
    """Real-widget smoke test: the Stock sub-tab's tree must show the
    trimmed per-item history (via select_recent_stock_history_rows), not a
    single latest-only row per item like before Phase 3."""
    window = bare_main_window
    window.company_var = tk.StringVar(value="TestCo")
    window.companies = [{"name": "TestCo"}]
    window.company_combos = []
    window.stock_sub_tab = tk.Frame(window)
    window._build_stock_tab()

    records = [
        {"name": "Oil Canister", "timestamp": str(ts), "date": f"day{ts}", "in_stock": str(ts)}
        for ts in range(1, 9)  # 8 snapshots for one item
    ]
    window._safe_read = lambda sheet_name: records if sheet_name == "Stock_History" else []

    window._populate_stock()

    row_ids = window.stock_tree.get_children()
    assert len(row_ids) == 7  # capped per item, not all 8 raw snapshots

    columns = window.stock_tree["columns"]
    date_index = list(columns).index("date")
    first_row_values = window.stock_tree.item(row_ids[0])["values"]
    assert first_row_values[date_index] == "day8"  # newest snapshot first


# ---------------------------------------------------------------------------
# Phase 6: Legal menu separated from File menu (TOS + Privacy Policy moved
# out of File into their own top-level "Legal" cascade).
# ---------------------------------------------------------------------------

def test_legal_menu_separated_from_file_menu(bare_main_window):
    """TOS and Privacy Policy live in their own 'Legal' menu next to File,
    not mixed into the File menu's Run Snapshot/Refresh/Exit actions."""
    window = bare_main_window
    window.run_snapshot = lambda: None
    window.refresh_from_sheet = lambda: None
    window.show_terms = lambda: None
    window.show_privacy = lambda: None

    window._build_menu()

    menubar = window.nametowidget(window["menu"])
    cascade_indices = {
        menubar.entrycget(i, "label"): i
        for i in range(menubar.index("end") + 1)
        if menubar.type(i) not in ("tearoff", "separator")
    }
    assert list(cascade_indices.keys()) == ["File", "Legal"]

    file_menu = window.nametowidget(menubar.entrycget(cascade_indices["File"], "menu"))
    file_labels = [
        file_menu.entrycget(i, "label")
        for i in range(file_menu.index("end") + 1)
        if file_menu.type(i) not in ("separator", "tearoff")
    ]
    assert file_labels == ["Run Snapshot Now", "Refresh From Sheet", "Exit"]
    assert "TOS" not in file_labels
    assert "Privacy Policy" not in file_labels

    legal_menu = window.nametowidget(menubar.entrycget(cascade_indices["Legal"], "menu"))
    legal_labels = [
        legal_menu.entrycget(i, "label")
        for i in range(legal_menu.index("end") + 1)
        if legal_menu.type(i) not in ("separator", "tearoff")
    ]
    assert legal_labels == ["TOS", "Privacy Policy"]


# ---------------------------------------------------------------------------
# Phase 5: info-glyph field explanations.
# ---------------------------------------------------------------------------

def test_field_explanations_registry_covers_every_employee_effectiveness_column():
    """Every column in EMPLOYEE_EFFECTIVENESS_EXPLAINED_COLUMNS (the columns
    that actually get a header glyph) must have a registry entry - a column
    added to the glyph list without matching text would silently show
    "No explanation available" in production."""
    for key in EMPLOYEE_EFFECTIVENESS_EXPLAINED_COLUMNS:
        assert key in FIELD_EXPLANATIONS
        assert FIELD_EXPLANATIONS[key].strip()


def test_field_explanations_registry_covers_info_card_labels():
    for key in EMPLOYEE_INFO_CARD_EXPLAINED_LABELS.values():
        assert key in FIELD_EXPLANATIONS


def test_field_explanations_registry_covers_projection_tables():
    assert "base_effectiveness_projections" in FIELD_EXPLANATIONS
    assert "total_effectiveness_projections" in FIELD_EXPLANATIONS
    assert FIELD_EXPLANATIONS["base_effectiveness_projections"].strip()
    assert FIELD_EXPLANATIONS["total_effectiveness_projections"].strip()


def test_employee_effectiveness_explained_columns_excludes_computed_assignment_fields():
    """best_fit_efficiency/assigned_efficiency are the app's own computed
    assignment values, not Torn effectiveness components - they were
    deliberately left out of the glyph list, per the plan."""
    assert "best_fit_efficiency" not in EMPLOYEE_EFFECTIVENESS_EXPLAINED_COLUMNS
    assert "assigned_efficiency" not in EMPLOYEE_EFFECTIVENESS_EXPLAINED_COLUMNS


def test_employee_overview_header_glyph_click_shows_explanation(bare_main_window, monkeypatch):
    """Real-widget smoke test: clicking an effectiveness column's info-glyph
    on Employee Overview pops up that field's registry text, and does NOT
    trigger the header's sort click."""
    import types

    window = bare_main_window
    window.employee_overview_tab = tk.Frame(window)
    window.company_var = tk.StringVar(value="TestCo")
    window.companies = [{"name": "TestCo"}]
    window.company_combos = []
    window.settings = types.SimpleNamespace(employee_visible_columns=[])
    window._build_employees_tab()

    window._employee_sort_column = None
    window._employee_sort_reverse = False
    sort_calls = []
    window._sort_employees = lambda col, reverse: sort_calls.append(col)

    records = [{"tId": "1", "name": "Bob", "current_position": "Director", "effectiveness_total": "150"}]
    window._render_employee_rows(records)

    shown = []
    monkeypatch.setattr(
        "gui.main_window.messagebox.showinfo",
        lambda title, text, parent=None: shown.append((title, text)),
    )

    # Find the info-glyph button under the "effectiveness_total" header cell.
    header_cell = None
    for child in window.employees_grid.winfo_children():
        if isinstance(child, tk.Frame) and child.grid_info().get("row") == 0:
            header_cell = child
            break
    assert header_cell is not None, "expected an effectiveness header to be wrapped in a Frame"

    glyph_button = header_cell.winfo_children()[-1]  # glyph packed side="right", added last
    # pyrefly: ignore [missing-attribute]
    glyph_button.invoke()

    assert len(shown) == 1
    assert shown[0][1] == FIELD_EXPLANATIONS["effectiveness_total"]
    assert sort_calls == []  # glyph click must not also trigger a sort


def test_employee_info_card_glyphs_wired_to_correct_keys(bare_main_window, monkeypatch):
    """Real-widget smoke test: EmployeeInfoCard's 'Current Eff.' and
    'Total Eff.' rows each carry a glyph wired to the matching registry key.
    Uses the shared bare_main_window fixture as master rather than a fresh
    tk.Tk() root - repeated tk.Tk() creation/destruction in one process is
    flaky here (see bare_main_window's own docstring)."""
    from gui.main_window import EmployeeInfoCard

    record = {
        "name": "Bob", "tId": "1", "current_position": "Director",
        "projected_efficiency_current_position": "94.2", "effectiveness_total": "150",
    }
    card = EmployeeInfoCard(bare_main_window, record)
    try:
        shown = []
        monkeypatch.setattr(
            "gui.main_window.messagebox.showinfo",
            lambda title, text, parent=None: shown.append((title, text)),
        )

        glyph_buttons = [
            widget
            for frame in card.winfo_children()
            for body_canvas in frame.winfo_children() if isinstance(body_canvas, tk.Canvas)
            for body in body_canvas.winfo_children()
            for row_frame in body.winfo_children() if isinstance(row_frame, ttk.Frame)
            for widget in row_frame.winfo_children() if isinstance(widget, tk.Button)
        ]
        assert len(glyph_buttons) == 2  # Current Eff. + Total Eff.

        for glyph in glyph_buttons:
            glyph.invoke()

        assert len(shown) == 2
        shown_texts = {text for _title, text in shown}
        assert FIELD_EXPLANATIONS["projected_efficiency_current_position"] in shown_texts
        assert FIELD_EXPLANATIONS["effectiveness_total"] in shown_texts
    finally:
        card.destroy()


def test_base_and_total_projection_toolbars_each_have_exactly_one_glyph(bare_main_window, monkeypatch):
    """Table-level glyph: one per toolbar (not one per position column) on
    both the Base and Total Effectiveness Projections sub-tabs."""
    window = bare_main_window
    window.company_var = tk.StringVar(value="TestCo")
    window.companies = [{"name": "TestCo"}]
    window.company_combos = []
    window.base_effectiveness_tab = tk.Frame(window)
    window.total_effectiveness_tab = tk.Frame(window)
    window._build_base_effectiveness_tab()
    window._build_total_effectiveness_tab()

    shown = []
    monkeypatch.setattr(
        "gui.main_window.messagebox.showinfo",
        lambda title, text, parent=None: shown.append((title, text)),
    )

    def find_glyph(toolbar_tab):
        toolbar = toolbar_tab.winfo_children()[0]
        buttons_by_text = [
            w for w in toolbar.winfo_children()
            if isinstance(w, tk.Button) and w["text"] == "\u24d8"
        ]
        return buttons_by_text

    base_glyphs = find_glyph(window.base_effectiveness_tab)
    total_glyphs = find_glyph(window.total_effectiveness_tab)
    assert len(base_glyphs) == 1
    assert len(total_glyphs) == 1

    base_glyphs[0].invoke()
    total_glyphs[0].invoke()

    assert len(shown) == 2
    shown_texts = {text for _title, text in shown}
    assert FIELD_EXPLANATIONS["base_effectiveness_projections"] in shown_texts
    assert FIELD_EXPLANATIONS["total_effectiveness_projections"] in shown_texts


# ---------------------------------------------------------------------------
# Phase 6: rank_neighbors_from_sheet_rows() + the Health Score neighbor
# popup (real-widget smoke test).
# ---------------------------------------------------------------------------

def _ranking_row(rank, name, is_own=False, rating="9.0", daily="1000000", weekly="7000000"):
    return {
        "rank": str(rank), "id": str(1000 + rank), "name": name, "rating": rating,
        "daily_income": daily, "weekly_income": weekly, "is_own_company": str(is_own),
    }


def test_rank_neighbors_selects_5_above_and_5_below_own_company():
    rows = [_ranking_row(r, f"Co{r}", is_own=(r == 7)) for r in range(1, 15)]

    neighbors = rank_neighbors_from_sheet_rows(rows)

    assert [n["rank"] for n in neighbors] == [str(r) for r in range(2, 13)]  # 5 above, own, 5 below
    own = next(n for n in neighbors if n["is_own_company"] == "True")
    assert own["rank"] == "7"


def test_rank_neighbors_clips_at_top_when_own_company_near_rank_1():
    rows = [_ranking_row(r, f"Co{r}", is_own=(r == 2)) for r in range(1, 15)]

    neighbors = rank_neighbors_from_sheet_rows(rows)

    assert neighbors[0]["rank"] == "1"  # clipped, no padding below rank 1
    assert neighbors[-1]["rank"] == "7"  # own(2) + 5 below = 7


def test_rank_neighbors_clips_at_bottom_when_own_company_near_last_rank():
    rows = [_ranking_row(r, f"Co{r}", is_own=(r == 13)) for r in range(1, 15)]

    neighbors = rank_neighbors_from_sheet_rows(rows)

    assert neighbors[-1]["rank"] == "14"  # clipped, no padding past the last company
    assert neighbors[0]["rank"] == "8"  # own(13) - 5 above = 8


def test_rank_neighbors_respects_custom_span():
    rows = [_ranking_row(r, f"Co{r}", is_own=(r == 5)) for r in range(1, 10)]

    neighbors = rank_neighbors_from_sheet_rows(rows, span=2)

    assert [n["rank"] for n in neighbors] == ["3", "4", "5", "6", "7"]


def test_rank_neighbors_returns_empty_when_no_own_company_flagged():
    rows = [_ranking_row(r, f"Co{r}") for r in range(1, 5)]  # none flagged is_own

    assert rank_neighbors_from_sheet_rows(rows) == []


def test_rank_neighbors_returns_empty_for_empty_input():
    assert rank_neighbors_from_sheet_rows([]) == []


def test_rank_neighbors_sorts_by_rank_even_if_input_order_is_scrambled():
    rows = [_ranking_row(r, f"Co{r}", is_own=(r == 3)) for r in [5, 1, 3, 2, 4]]

    neighbors = rank_neighbors_from_sheet_rows(rows, span=5)

    assert [n["rank"] for n in neighbors] == ["1", "2", "3", "4", "5"]


def test_health_score_click_opens_neighbors_popup_other_rows_do_not(bare_main_window, monkeypatch):
    """Real-widget smoke test: selecting the Health Score row opens
    HealthScoreNeighborsCard populated from Company_Rankings; selecting any
    other Overview row does nothing."""
    from gui.main_window import HealthScoreNeighborsCard
    import types

    window = bare_main_window
    window.overview_tab = tk.Frame(window)
    window.company_var = tk.StringVar(value="TestCo")
    window.companies = [{"name": "TestCo"}]
    window.company_combos = []
    window.settings = types.SimpleNamespace(last_selected_company=None)
    window._build_overview_tab()

    ranking_rows = [_ranking_row(r, f"Co{r}", is_own=(r == 3)) for r in range(1, 6)]
    window._safe_read = lambda sheet_name: ranking_rows if sheet_name == "Company_Rankings" else []

    opened = []
    monkeypatch.setattr(
        "gui.main_window.HealthScoreNeighborsCard",
        lambda master, neighbors: opened.append(neighbors),
    )

    plain_id = window.overview_tree.insert("", "end", text="employees", values=("5",))
    health_id = window.overview_tree.insert(
        "", "end", text="health score (rank by income) (click for more info)",
        values=("#3 of 5",),
    )

    window.overview_tree.selection_set(plain_id)
    window._on_overview_row_selected()
    assert opened == []  # a non-Health-Score row must not open anything

    window.overview_tree.selection_set(health_id)
    window._on_overview_row_selected()
    assert len(opened) == 1
    assert [n["rank"] for n in opened[0]] == ["1", "2", "3", "4", "5"]


def test_health_score_neighbors_card_renders_rows_and_bolds_own_company(bare_main_window):
    """Real-widget smoke test: the popup itself actually lays out one row
    per neighbor with the director's own row visually distinguished (bold),
    not just that the right data was selected upstream. Uses the shared
    bare_main_window fixture as the Toplevel's master rather than a fresh
    tk.Tk() root - see the bare_main_window fixture's own docstring for why
    (repeated tk.Tk() creation/destruction in one process is flaky here)."""
    from gui.main_window import HealthScoreNeighborsCard

    neighbors = [_ranking_row(r, f"Co{r}", is_own=(r == 2)) for r in range(1, 4)]
    card = HealthScoreNeighborsCard(bare_main_window, neighbors)
    try:
        content = card.winfo_children()[0]
        body = content.winfo_children()[0]
        # 4 rows total: 1 header + 3 data rows, 5 columns each.
        name_cells = [
            w for w in body.grid_slaves() if isinstance(w, ttk.Label) and w.grid_info()["column"] == 1
        ]
        assert len(name_cells) == 4  # header + 3 companies

        own_cell = next(w for w in name_cells if w["text"] == "Co2")
        other_cell = next(w for w in name_cells if w["text"] == "Co1")
        assert own_cell["font"] != other_cell["font"]  # own row visually bolded
    finally:
        card.destroy()


def test_health_score_neighbors_card_shows_message_when_no_data(bare_main_window):
    from gui.main_window import HealthScoreNeighborsCard

    card = HealthScoreNeighborsCard(bare_main_window, [])
    try:
        content = card.winfo_children()[0]
        labels = [w for w in content.winfo_children() if isinstance(w, ttk.Label)]
        assert any("No ranking data" in w["text"] for w in labels)
    finally:
        card.destroy()


# ---------------------------------------------------------------------------
# Phase 7: Company Rankings sub-tab (format_star_progress + real-widget
# smoke test confirming the locked own-company row and the scrollable list
# are independently and correctly sourced).
# ---------------------------------------------------------------------------

def test_format_star_progress_shows_gap_when_outside_cohort():
    assert format_star_progress(5250000, "", 9) == "Need $5,250,000/wk more"


def test_format_star_progress_shows_buffer_at_max_star():
    assert format_star_progress(None, 250000, 10) == "$250,000/wk buffer before 9-star"


def test_format_star_progress_inside_next_star_income_range():
    assert format_star_progress(0, "", 9) == "In the projected 10-star income range"


def test_format_star_progress_not_enough_data_when_blank():
    assert format_star_progress("", "") == "Not enough data yet"
    assert format_star_progress(None, None) == "Not enough data yet"


def test_company_ranking_rows_sort_by_each_column_with_missing_values_last():
    rows = [
        {
            "name": "Beta", "rank": "10", "rating": "8",
            "daily_income": "1,000", "weekly_income": "7,000",
        },
        {
            "name": "alpha", "rank": "2", "rating": "10",
            "daily_income": "20", "weekly_income": "900",
        },
        {
            "name": "Gamma", "rank": "1", "rating": "9",
            "daily_income": "300", "weekly_income": "10,000",
        },
        {
            "name": "", "rank": "", "rating": "",
            "daily_income": "", "weekly_income": "",
        },
    ]

    assert [row["name"] for row in sort_company_ranking_rows(rows, "rank")] == [
        "Gamma", "alpha", "Beta", "",
    ]
    assert [row["name"] for row in sort_company_ranking_rows(rows, "name")] == [
        "alpha", "Beta", "Gamma", "",
    ]
    assert [
        row["name"]
        for row in sort_company_ranking_rows(rows, "rating", reverse=True)
    ] == ["alpha", "Gamma", "Beta", ""]
    assert [
        row["name"]
        for row in sort_company_ranking_rows(rows, "daily_income")
    ] == ["alpha", "Gamma", "Beta", ""]
    assert [
        row["name"]
        for row in sort_company_ranking_rows(rows, "weekly_income", reverse=True)
    ] == ["Gamma", "Beta", "alpha", ""]


def test_company_rankings_tab_locked_row_and_list_are_independently_sourced(bare_main_window):
    """Real-widget smoke test: the locked row comes from Company_History
    (own company's rank/income/star-progress), the scrollable list comes
    from Company_Rankings (every same-type company) - confirms both are
    populated correctly and don't get mixed up, same shared-state caution
    as Phase 2's Base/Total Effectiveness Projections bug."""
    window = bare_main_window
    window.company_rankings_tab = tk.Frame(window)
    window.company_var = tk.StringVar(value="TestCo")
    window.companies = [{"name": "TestCo"}]
    window.company_combos = []
    window._build_company_rankings_tab()

    locked_frame = next(
        child for child in window.company_rankings_tab.winfo_children()
        if isinstance(child, ttk.LabelFrame)
    )
    locked_headers = {
        child["text"] for child in locked_frame.winfo_children()
        if isinstance(child, ttk.Label) and child["text"] != "-"
    }
    assert locked_headers == {
        "Rank", "Daily Income", "Weekly Income",
        "Weekly Income Gap to Next Star", "Observed Range Position",
        "Weekly Income Gap to Previous Star", "Change Since Yesterday",
    }

    ranking_rows = [_ranking_row(r, f"Co{r}", is_own=(r == 3)) for r in range(1, 6)]
    ranking_rows[2]["weekly_income"] = "29750000"
    history_rows = [
        {
            "timestamp": "100", "rank_by_income": "3", "daily_income": "4250000",
            "weekly_income": "29750000", "income_to_reach_10_star": "5250000",
            "income_buffer_before_9_star": "",
            "rolling_7day_income": "28000000",
            "observed_range_position_percent": "72",
            "observed_drop_buffer": "3000000",
            "observed_next_star_gap": "4500000",
            "rolling_7day_change": "-250000",
        },
        {
            "timestamp": "50", "rank_by_income": "", "daily_income": "1000000",
            "weekly_income": "7000000", "income_to_reach_10_star": "",
            "income_buffer_before_9_star": "",
        },
    ]

    def fake_safe_read(sheet_name):
        if sheet_name == "Company_Rankings":
            return ranking_rows
        if sheet_name == "Company_History":
            return history_rows
        if sheet_name == "Star_Income_Summary":
            return [
                {"stars": "10", "minimum": "40000000"},
                {"stars": "9", "minimum": "20000000", "maximum": "35000000"},
                {"stars": "8", "maximum": "10000000"},
            ]
        return []

    window._safe_read = fake_safe_read
    window._populate_company_rankings()

    # Historical values remain pinned, while star metrics use current sheets.
    locked = window._company_rankings_locked_labels
    assert locked["rank"]["text"] == "3"
    assert locked["daily_income"]["text"] == "$4,250,000"
    assert locked["weekly_income"]["text"] == "$29,750,000"
    assert locked["next_star_gap"]["text"] == "$10,250,000"
    assert locked["range_position"]["text"] == "65%"
    assert locked["previous_star_gap"]["text"] == "$19,750,000"
    assert locked["daily_change"]["text"] == "-$250,000"
    assert set(locked) == {
        "rank", "daily_income", "weekly_income", "next_star_gap",
        "range_position", "previous_star_gap", "daily_change",
    }

    # Scrollable list: all 5 companies from Company_Rankings, sorted by rank.
    row_ids = window.company_rankings_tree.get_children()
    assert len(row_ids) == 5
    first_row_values = window.company_rankings_tree.item(row_ids[0])["values"]
    assert first_row_values[0] == 1  # rank column, first item
    own_row_id = next(
        rid for rid in row_ids if window.company_rankings_tree.item(rid)["values"][1] == "Co3"
    )
    assert "own_company" in window.company_rankings_tree.item(own_row_id)["tags"]
    assert all(
        window.company_rankings_tree.heading(column, "command")
        for column in window.company_rankings_tree["columns"]
    )
    assert window.company_rankings_tree.heading("rank", "text").endswith("▲")

    window._sort_company_rankings("weekly_income")
    row_ids = window.company_rankings_tree.get_children()
    assert window.company_rankings_tree.item(row_ids[0])["values"][1] == "Co1"
    assert window.company_rankings_tree.heading("weekly_income", "text").endswith("▲")

    window._sort_company_rankings("weekly_income")
    row_ids = window.company_rankings_tree.get_children()
    assert window.company_rankings_tree.item(row_ids[0])["values"][1] == "Co3"
    assert window.company_rankings_tree.heading("weekly_income", "text").endswith("▼")

    window._populate_company_rankings()
    row_ids = window.company_rankings_tree.get_children()
    assert window.company_rankings_tree.item(row_ids[0])["values"][1] == "Co3"
    assert locked["rank"]["text"] == "3"


def test_derive_star_progress_uses_next_slot_minimum():
    ranking_rows = [{
        "rank": "80", "name": "Own", "rating": "9.0",
        "weekly_income": "864904308", "is_own_company": "True",
    }]
    summaries = [
        {"stars": "10", "total_count": "77", "minimum": "972267370"},
        {
            "stars": "9", "total_count": "100",
            "minimum": "700000000", "maximum": "900000000",
        },
        {"stars": "8", "total_count": "120", "maximum": "600000000"},
    ]

    result = derive_star_progress(ranking_rows, summaries)

    assert result["required_weekly_income_to_star_up"] == 972267370
    assert result["income_to_reach_next_star"] == 107363062
    assert result["observed_next_star_gap"] == 107363062
    assert result["income_to_drop_to_previous_star"] == 264904308
    assert result["observed_drop_buffer"] == 264904308
    assert result["observed_range_position_percent"] == pytest.approx(82.452154)
    assert result["star_10_count"] == "77"


@pytest.mark.parametrize(
    ("weekly_income", "expected"),
    [("50", 0.0), ("100", 50.0), ("150", 100.0), ("200", 100.0)],
)
def test_derive_star_progress_clamps_observed_range(weekly_income, expected):
    ranking_rows = [{
        "rating": "9", "weekly_income": weekly_income,
        "is_own_company": "True",
    }]
    summaries = [{"stars": "9", "minimum": "50", "maximum": "150"}]

    result = derive_star_progress(ranking_rows, summaries)

    assert result["observed_range_position_percent"] == expected


def test_derive_star_progress_omits_unavailable_observed_metrics():
    ranking_rows = [{
        "rating": "10", "weekly_income": "500",
        "is_own_company": "True",
    }]
    summaries = [
        {"stars": "10", "minimum": "500", "maximum": "500"},
        {"stars": "9", "maximum": ""},
    ]

    result = derive_star_progress(ranking_rows, summaries)

    assert "observed_range_position_percent" not in result
    assert "observed_drop_buffer" not in result
    assert "observed_next_star_gap" not in result


def test_overview_uses_dynamic_star_labels_and_required_income(bare_main_window):
    import types

    window = bare_main_window
    window.overview_tab = tk.Frame(window)
    window.company_var = tk.StringVar(value="TestCo")
    window.companies = [{"name": "TestCo"}]
    window.company_combos = []
    window.settings = types.SimpleNamespace(last_selected_company=None)
    window._build_overview_tab()

    history = [{
        "timestamp": "100", "rating": "9.0", "employees_hired": "10",
        "employees_capacity": "15", "income_to_reach_10_star": "1",
        "income_buffer_before_9_star": "2",
        "rank_by_income": "80", "rank_total_in_type": "433",
    }]
    rankings = [{
        "rank": "80", "rating": "9.0", "weekly_income": "864904308",
        "is_own_company": "True",
    }]
    summaries = [
        {"stars": "10", "total_count": "77", "minimum": "972267370"},
        {"stars": "9", "total_count": "100", "minimum": "700000000"},
        {"stars": "8", "total_count": "120", "maximum": "600000000"},
    ]

    def fake_safe_read(sheet_name):
        return {
            "Company_History": history,
            "Company_Rankings": rankings,
            "Star_Income_Summary": summaries,
        }.get(sheet_name, [])

    window._safe_read = fake_safe_read
    window._populate_overview()

    displayed = {
        window.overview_tree.item(row_id, "text"):
        window.overview_tree.item(row_id, "values")[0]
        for row_id in window.overview_tree.get_children()
    }
    assert displayed["income to reach 10 star"] == "$107,363,062"
    assert displayed["required weekly income to star up"] == "$972,267,370"
    assert displayed["income to drop to 8 star"] == "$264,904,308"
    assert displayed["star 10 count (click for more info)"] == "77"
    assert (
        displayed["health score (rank by income) (click for more info)"]
        == "#80 of 433"
    )
    assert "observed next-star gap" not in displayed
    assert "observed drop buffer" not in displayed
    assert "income to drop to 9 star" not in displayed


def test_income_drop_label_and_rolling_values_are_currency():
    from gui.main_window import format_field, pretty_label

    assert pretty_label("income_buffer_before_9_star") == "income to drop to 9 star"
    assert format_field(
        "income_buffer_before_9_star", 123456, "Company_History"
    ) == "$123,456"
    assert format_field(
        "rolling_7day_income", 7654321, "Company_History"
    ) == "$7,654,321"


def test_star_10_count_click_opens_observed_range_popup(
    bare_main_window, monkeypatch,
):
    import types

    window = bare_main_window
    window.overview_tab = tk.Frame(window)
    window.company_var = tk.StringVar(value="TestCo")
    window.companies = [{"name": "TestCo"}]
    window.company_combos = []
    window.settings = types.SimpleNamespace(last_selected_company=None)
    window._build_overview_tab()

    rows = [{
        "stars": "10", "total_count": "5", "minimum": "100",
        "p10": "120", "median": "150", "p90": "190",
        "maximum": "200", "coverage": "5/5", "updated_at": "1",
    }]
    window._safe_read = (
        lambda sheet_name: rows if sheet_name == "Star_Income_Summary" else []
    )
    opened = []
    monkeypatch.setattr(
        "gui.main_window.StarIncomeSummaryCard",
        lambda master, summary: opened.append(summary),
    )
    item = window.overview_tree.insert(
        "", "end", text="star 10 count (click for more info)", values=("5",)
    )
    window.overview_tree.selection_set(item)
    window._on_overview_row_selected()
    assert opened == [rows]


def test_star_income_summary_numeric_sort_key():
    from gui.main_window import StarIncomeSummaryCard

    assert StarIncomeSummaryCard._sort_value({"median": "100"}, "median") < (
        StarIncomeSummaryCard._sort_value({"median": "900"}, "median")
    )


def test_star_income_summary_uses_plain_language_columns():
    from gui.main_window import StarIncomeSummaryCard

    assert "p10" not in StarIncomeSummaryCard.COLUMNS
    assert "p90" not in StarIncomeSummaryCard.COLUMNS
    assert StarIncomeSummaryCard.LABELS["stars"] == "Star Level"
    assert StarIncomeSummaryCard.LABELS["total_count"] == "Company Count"
    assert StarIncomeSummaryCard.LABELS["minimum"] == "Minimum Weekly Income"
    assert (
        StarIncomeSummaryCard.LABELS["maximum"]
        == "Top Performer Weekly Income"
    )
    assert "income target used for promotion" in StarIncomeSummaryCard.COLUMN_GUIDE


def test_star_income_summary_formats_coverage_as_words(bare_main_window):
    from gui.main_window import StarIncomeSummaryCard

    card = StarIncomeSummaryCard(bare_main_window, [{
        "stars": "10", "total_count": "77", "minimum": "100",
        "median": "150", "maximum": "200", "coverage": "77/77",
        "updated_at": "1",
    }])
    try:
        row_id = card.tree.get_children()[0]
        values = card.tree.item(row_id, "values")
        coverage_index = StarIncomeSummaryCard.COLUMNS.index("coverage")
        assert values[coverage_index] == "77 of 77"
    finally:
        card.destroy()


def test_observed_range_position_and_freshness_formatting():
    from gui.main_window import format_data_freshness, format_field

    now = 2_000_000
    assert format_data_freshness(now - 60, now=now) == "Current"
    assert format_data_freshness(now - 86400, now=now) == "1 day stale"
    assert format_data_freshness(now - 172800, now=now) == "2 days stale"
    assert format_field(
        "observed_range_position_percent", 72.4, "Company_History"
    ) == "72%"
