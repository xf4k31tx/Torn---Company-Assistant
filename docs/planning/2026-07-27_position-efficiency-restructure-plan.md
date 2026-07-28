# TCA Implementation Plan - Position Efficiency Restructure, Total Effectiveness Projections, Stock History, Monthly Financials, Info-Glyph Explanations

Status: PLANNING ONLY - no code changes made yet. Awaiting go-ahead per phase.
Captured: 2026-07-27 planning session (chat backup + Mnemoverse memory).

## Confirmed decisions (all locked in during planning)

1. Tab nesting target structure:
```
Overview
Employees (parent)
 |- Employee Overview          (renamed from today's "Employees" tab)
 \- Position Efficiency (nested parent)
     |- Base Effectiveness Projections   (renamed from today's "Position Efficiency" tab)
     \- Total Effectiveness Projections  (new)
Stock & Profit Trends (renamed from "Stock & Profit", parent)
 |- Stock            (today's stock table + stock-worth chart, + 7-day history change)
 \- Company Trends    (today's standalone "Trends" tab content, merged in)
Settings
```
Renames are GUI-label only - underlying Google Sheet tab names (Position_Efficiency,
Employees, etc.) are NOT renamed, for backward compatibility with anything built
against the sheets directly.

2. Total Effectiveness Projections formula (confirmed, simplified):
   Total Projection[position] = Base Projection[position] + (effectiveness_total - effectiveness_working_stats)
   This exactly equals Base + Addiction + Inactivity + Management + Book + Merits +
   Settled In + Director's Education, since Torn's effectiveness_total is documented
   as the sum of all 8 components. Table has the SAME shape/behavior as Base
   Effectiveness Projections (same rows/columns/sorting/click-to-info-card) - not a
   different layout.

3. "Current Eff." vs "Work Stats Eff." - VERIFIED against code during planning:
   - effectiveness_working_stats ("Work Stats Eff.") = Torn's own real API value
     (emp.get("effectiveness")["working_stats"], from TornAPI.get_company_employees()).
   - projected_efficiency_current_position ("Current Eff.") = Tornstats' projection
     (projected.get(position_name, ""), from TornStatsAPI.get_efficiency()).
   This mapping is CORRECT and confirmed by the user (initial claim it was reversed
   was a misremember, retracted). No naming/data-source change needed for these two
   fields - keep as-is.

4. Stock & Profit Trends internal layout: sub-tabs (not a combined single pane),
   consistent with the Employees/Position Efficiency nesting pattern.

5. Stock sub-tab: show 7 rows per stock item (current + 6 prior days) instead of
   collapsing to latest-only, so directors can compare vs the last week. Flat,
   sortable table (not tree/grouped) with an added Date column, sorted by
   (name, timestamp descending) so each item's week sits together.

6. Monthly Income/Profit: rolling 30-day TRAILING TOTAL (sum, not average),
   continuously updating with every snapshot - not a calendar-month reset.
   Mirrors weekly_income/weekly_profit's "total over a period" semantics at
   30-day granularity. Surfaces automatically on the Overview tab (which
   generically loops every Company_History field) once the fields exist -
   no bespoke Overview GUI code needed. Also added to the Company Trends
   metric-picker dropdown.

7. Effectiveness-field explanations: info-glyph (small "i" icon) next to each
   field, separate click target from existing header-sort-click (which is
   already taken on Employee Overview and both Position Efficiency tables).
   Base/Total Effectiveness Projections tables get ONE explanation each
   (table-level, near the toolbar) since every position column means the same
   thing methodologically there - not one per column. Employee Overview grid
   and EmployeeInfoCard fields each get their own per-field explanation
   (genuinely different quantities per field).

## Phased implementation order

### Phase 1 - Tab restructure only (no new data/calculations)
- Rebuild `_build_layout()`: top-level becomes Overview, Employees (nested),
  Stock & Profit Trends (nested), Settings.
- Employees parent -> sub-Notebook: Employee Overview (re-parented existing
  content) + Position Efficiency (sub-Notebook: Base Effectiveness Projections
  = re-parented + renamed existing Position Efficiency tab content only;
  Total Effectiveness Projections tab exists as an empty placeholder/shell
  until Phase 2 wires real data).
- Stock & Profit Trends parent -> sub-Notebook: Stock (re-parented existing
  stock table+chart, no 7-day change yet) + Company Trends (re-parented
  existing Trends tab content, unchanged).
- Generalize `_populate_position_efficiency`/`_render_position_efficiency_rows`/
  `_sort_position_efficiency` to take a sheet-name/dataset parameter (prep for
  Phase 2 reuse) rather than duplicating ~200 lines of canvas code.
- `_refresh_all()` updated for new sub-tab structure.
- `EmployeeInfoCard` click-wiring confirmed still working on the renamed/
  re-parented Base Effectiveness Projections tab.
- Tests: update any tests referencing old tab/method names. README: tab list
  section updated for new names/nesting.

### Phase 2 - Total Effectiveness Projections
- `efficiency_calc.py`: add `build_total_effectiveness_projection_rows(rows, position_names)`.
- `collector.py`: write its output to new `Total_Effectiveness_Projections`
  sheet tab in `run_employee_efficiency()`, alongside existing Position_Efficiency write.
- GUI: wire the Total Effectiveness Projections sub-tab (placeholder from
  Phase 1) to real data via the generalized render/populate functions.
- Tests: new coverage for `build_total_effectiveness_projection_rows`
  (correct sum, blank when no base projection exists for a position).
  README: Sheets schema section gets the new tab.

### Phase 3 - Stock 7-day history
- Modify `_populate_stock`: replace latest-only collapse with per-item last-7
  snapshots, add Date column, sort by (name, date desc).
- Tests/README: update Stock section description.

### Phase 4 - Monthly Income/Profit
- `profit_calc.py`: add `compute_rolling_30day_sum()` (generalized rolling
  window+sum, mirroring `compute_rolling_7day_average`'s filter pattern) and
  `compute_monthly_income()`/`compute_monthly_profit()` wrappers.
- `collector.py`: add `monthly_income`/`monthly_profit` to
  `COMPANY_HISTORY_HEADERS`, populate in `run_snapshot()`.
- GUI: add both to Company Trends' `numeric_cols` dropdown list. Overview
  row appears automatically (generic per-field loop) - no Overview code change.
- Tests: new coverage for the rolling-30-day-sum function. README: Overview
  section note, Company Trends metric list update.

### Phase 5 - Info-glyph field explanations
- New field-explanation text registry (field key -> description string) in
  `gui/main_window.py` or a new small module, covering every effectiveness
  field plus one entry each for Base/Total Effectiveness Projections
  (table-level).
- Info-glyph widgets added: every effectiveness column header on Employee
  Overview, both EmployeeInfoCard effectiveness fields, one near each of the
  Base/Total Effectiveness Projections table toolbars.
- Tests: registry completeness (every relevant field key has an entry) and
  glyph-click smoke test similar to the EmployeeInfoCard real-widget checks
  used earlier this session. README: brief mention of the feature.

## Notes for whoever resumes this plan
- All backend math changes (Phase 2, Phase 4) should go through the same
  real-widget/real-function smoke-testing discipline used earlier this
  session (not just pure-function unit tests) before considering a phase done.
- Full pytest suite was at 77/77 passing as of the end of this planning
  session (last code change: EmployeeInfoCard ID field + blank-box/centering
  fixes) - each phase should return to a fully green suite before moving on.
- No files have been modified as a result of this planning conversation itself.
