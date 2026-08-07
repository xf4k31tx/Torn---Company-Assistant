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

---

## Addendum (2026-08-03) - Health Score neighbor popup + Company Rankings tab

Phases 1-5 above are complete and merged (98/99 -> 105/106 passing across the
session, one pre-existing unrelated `test_google_auth.py` failure throughout).
Phase 4's Monthly Income/Profit and the existing "Health Score (rank by
income)" Overview row (`app/collector.py::_compute_health_score`,
`app/torn_api.py::get_company_listings`) turned out to already be implemented
outside this conversation - this addendum builds on top of that existing
Health Score plumbing rather than starting from scratch.

### Confirmed technical findings (verified against the existing code + a web
search of Torn's own API forum before writing this addendum - not guessed)

- **Endpoint already wired**: `v2/company/{company_type_id}/companies`
  (`TornAPI.get_company_listings(company_type_id, offset, limit)`), paginated
  100 at a time via `limit`/`offset`, response shape
  `{"companies": [...], "_metadata": {"total": N}}`. Confirmed as the correct
  endpoint via Torn's own "API Development" sub-forum (a Torn staff reply
  pointing a developer at exactly this call for "the most current list of
  company info"), and via Torn's "Upcoming API changes" thread confirming the
  v2 `companies` selection takes one `cat` (company type)-equivalent per
  request and is capped at 100 results per page - matching the pagination
  loop `_compute_health_score` already implements.
- **Each listing entry's real fields - CORRECTED 2026-08-03, verified
  directly against `https://api-playground.torn.com/company/28/companies`
  (Torn's own official playground, tested with a real key) rather than
  assumed from the test mock**: every company in the listing has
  `id`, `name`, `created_at`, `days_old`, `image`, `type.id`/`type.name`,
  `rating`, `director.id`/`director.name`/`director.status`/
  `director.last_action`, `employees.hired`/`employees.capacity`,
  `income.daily`/`income.weekly`, `customers.daily`/`customers.weekly`,
  `applications_allowed`. The envelope also carries `companies_timestamp`,
  `companies_delay`, and `_metadata.links.next`/`prev` (cursor-style
  pagination, alongside/instead of the offset param the code currently
  loops on - worth double-checking during implementation whether `offset`
  still works as `_compute_health_score` assumes or whether the `next` link
  is now the intended way to page).
  **`income.daily` IS available for every company, not just the director's
  own** - this resolves Open Question 1 below: no estimate needed, every
  row in both new features can show real daily and weekly income.
  `tests/mock_data/endpoints.json`'s `get_company_listings` fixture is
  stale against this real schema (only has `id`/`name`/`rating`/
  `income.weekly` today) and needs updating to match before Phase 6/7 tests
  are written, so tests exercise the real field set instead of a
  simplified one.
- **Company type filtering already happens server-side**: we request
  `v2/company/{our_own_type_id}/companies`, so every entry returned already
  matches the director's own company type - no separate `company_type`
  field-based client-side filtering is needed (the earlier chat message's
  worry about "incorrect companies shown for the wrong director company
  type" is already handled by which endpoint we call, not by post-filtering
  a mixed-type list). `profile.type.id` (from the company's own
  `get_company_profile_v2()` call, already made every `run_snapshot()`) is
  the type ID to pass in.
- **Access level**: `torn -> companies` is Public access per
  `Welcome_to_the_Torn_API.md`'s own access table, confirmed by the existing
  Settings dialog copy ("Company's Public Torn API key (optional - only
  needed for the Health Score ranking...")) - already wired, no new key type
  needed for either new feature below.
- **Architecture constraint carried over from every prior phase**: the GUI
  never calls the Torn API directly - it only reads from the Google Sheet
  (module docstring: "the Sheet is the source of truth"). Both features below
  need the *full* ranked company list (not just the 4 scalar
  rank/total/percentile/trend fields `_compute_health_score` currently
  returns), so `run_snapshot()` needs to persist the full ranked listing to a
  new sheet tab each run, not just the summary row it writes to
  `Company_History` today.

### Open questions - all RESOLVED 2026-08-03

1. ~~Daily income for OTHER companies isn't available from the listing
   endpoint~~ **RESOLVED**: it IS available (`income.daily` on every listing
   entry, confirmed via the real API playground - see above). Both features
   show real daily and weekly income for every company, no estimating needed.
2. **"Amount needed to become 10-star" - RESOLVED with a star-cohort-size
   algorithm** (not the simpler "lowest current 10-star income" heuristic
   floated earlier - that was wrong because rank and rating update on
   different clocks):
   - Company **rank** (by weekly income) reshuffles continuously, every time
     any company's income updates.
   - Company **rating** (stars) only recalculates once a week, **Sundays at
     18:10 UTC** - it stays frozen at whatever it was set to all the rest of
     the week, even as income/rank keep moving underneath it. So mid-week,
     a company sitting at rank 12 can still show `rating: 10.0` (earned last
     Sunday) even though 11 other companies currently out-earn it - that
     company just hasn't been re-graded yet.
   - Algorithm: capture `star_10_count` = the number of same-type companies
     with `rating == 10.0` in the listing, but **only from the snapshot
     taken on a Sunday at/after 18:10 UTC** (the first snapshot after that
     week's recalculation - use the snapshot's own timestamp, already
     captured via `torn.get_company_timestamp_v2()`, converted to UTC
     weekday/hour). Persist `star_10_count` on `self.company["star_10_count"]`
     (same mutate-in-place + `persist_companies()` pattern as
     `last_rank`) so it carries forward through the rest of the week
     unchanged, exactly as the user specified ("every Sunday determine how
     many 10*'s there are and then throughout the rest of the week use that
     10* count").
   - Every snapshot (Sunday or not), using the **current day's rank-by-income
     order** and the **carried-forward `star_10_count`**: the company
     currently sitting at rank `star_10_count` (the last slot in this week's
     10-star-sized cohort) is the cutoff. `income_to_reach_10_star` = that
     cutoff company's weekly income minus the director's own weekly income,
     floored at 0 (0/negative means already inside the cohort - i.e.
     currently on track to hold or earn 10 stars at the next Sunday reset).
     If already inside the cohort (`rank <= star_10_count`), also compute
     `income_buffer_before_9_star` = own weekly income minus the weekly
     income of the company at rank `star_10_count + 1` (the first company
     just outside the cohort) - "how much margin before being overtaken and
     dropping to 9 stars by Sunday." Both numbers are plainly labeled as
     based on this week's already-locked-in 10-star headcount, not a
     guaranteed Torn formula, since actual re-grading could in principle
     also weigh other factors Torn hasn't published.
   - First-ever run (no `star_10_count` persisted yet, e.g. app installed
     mid-week): fall back to counting `rating == 10.0` directly in the
     current listing as a same-day estimate, clearly labeled "estimate,
     updates to a confirmed count next Sunday," rather than blocking the
     feature entirely until the next Sunday.
3. **New sheet tab - RESOLVED, confirmed**: `Company_Rankings`, overwritten
   every `run_snapshot()`, one row per company:
   `rank, id, name, rating, daily_income, weekly_income, is_own_company`.
   `star_10_count`, `income_to_reach_10_star`, and
   `income_buffer_before_9_star` are per-snapshot scalars, not per-company -
   these are stored the same way `rank_by_income` etc. are today: as
   extra `Company_History` columns (added to `COMPANY_HISTORY_HEADERS`),
   not in `Company_Rankings`.
4. **Feature 1 popup - RESOLVED, confirmed**: `Toplevel` popup (matching
   `EmployeeInfoCard`'s pattern) triggered by clicking the Health Score row
   specifically, showing the 5 companies above and 5 below the director's
   own company by rank (name/rating/daily/weekly income each), own row
   highlighted.
5. **Feature 2 nesting - RESOLVED, confirmed, with a naming change**:
   `Overview` becomes a parent tab with two sub-tabs - **`General`** (today's
   existing Company_History metrics tree, moved as-is and renamed from
   "Overview" to avoid a sub-tab sharing its parent's name) and
   `Company Rankings` (new: full same-type listing from the new sheet tab,
   columns Rank / Name / Rating / Daily Income / Weekly Income, sorted by
   rank, plus a locked/pinned row for the director's own company showing
   Rank / Daily Income / Weekly Income / Income to reach 10-star (or, if
   already 10-star, Income buffer before dropping to 9-star) per the
   algorithm above).

### Pagination - RESOLVED 2026-08-03: switch to `next`-link-following

The real schema's `_metadata.links.next`/`prev` (cursor-style) supersedes the
`offset`-based loop `_compute_health_score` currently implements. Implementation
task: change `TornAPI.get_company_listings` to follow `_metadata.links.next`
until it's null/absent, rather than incrementing `offset` by `limit` and
comparing against `_metadata.total` - the `offset`/`limit` params may still be
accepted for the *first* request, but subsequent pages should be fetched via
whatever URL `next` provides rather than hand-rolling the next offset, since
that's clearly the intended paging mechanism for this endpoint now. Needs a
small mock-fixture update (`tests/mock_data/endpoints.json`) to include a
`next` link on a first page and `null`/absent on the last, so the pagination
loop's termination condition is actually exercised by a test rather than
assumed.

### Phase 6 (confirmed) - Health Score neighbor popup + 10-star cohort math
- `TornAPI.get_company_listings`: switch pagination to follow
  `_metadata.links.next` (see above). Update `tests/mock_data/endpoints.json`
  to the real schema (full field set: `created_at`, `days_old`, `image`,
  `type`, `director`, `employees`, `income.daily`/`income.weekly`,
  `customers`, `applications_allowed`, `companies_timestamp`,
  `companies_delay`, `_metadata.links.next`/`prev`) plus a realistic
  Sunday-vs-weekday pair of scenarios for the star-cohort tests below.
- `collector.py`: `_compute_health_score` (or a rename, since it now does
  more than rank) persists the full ranked listing to the new
  `Company_Rankings` sheet tab; computes and persists `star_10_count`
  (Sunday-only capture, carried forward `self.company["star_10_count"]`
  otherwise) and the derived `income_to_reach_10_star`/
  `income_buffer_before_9_star`, added to `COMPANY_HISTORY_HEADERS`.
- Pure function `rank_neighbors(ranked_companies, own_id, span=5)` in
  `gui/main_window.py` (or a small ranking-helpers module) selecting the 5
  above / 5 below - unit-testable without Tk (edge cases: own company at
  rank 1 or last, fewer than 11 total companies in the type).
- Pure function(s) for the star-cohort math (cutoff-company lookup,
  floor-at-0 gap, Sunday-18:10-UTC detection from a timestamp) - unit-tested
  independently of the collector's I/O, same separation-of-concerns as
  `profit_calc.py`/`efficiency_calc.py`.
- GUI: bind a click handler on the Health Score row specifically (not the
  whole tree), open a `Toplevel` popup listing the neighbors, own-company
  row highlighted.
- Tests: pure-function coverage for `rank_neighbors` and the star-cohort
  math (including the Sunday-capture vs. weekday-carry-forward split and the
  first-ever-run fallback) + a real-widget smoke test for the popup (same
  discipline as `EmployeeInfoCard`'s tests) + collector-level test asserting
  `star_10_count` is captured only on the Sunday-18:10-UTC+ snapshot and
  unchanged on other days.

### Phase 7 (confirmed) - Company Rankings sub-tab
- GUI: restructure `Overview` into a parent tab with `General` (renamed from
  today's `Overview`) + `Company Rankings` sub-tabs (same nesting pattern as
  Phase 1).
- `Company Rankings` sub-tab: full sortable list read from the new
  `Company_Rankings` sheet tab, plus a locked/pinned row for the director's
  own company (Rank / Daily Income / Weekly Income / Income to reach
  10-star or buffer before 9-star, per Phase 6's persisted values).
- Tests: real-widget smoke test confirming the locked row's own-company
  values and the scrollable list's values are independent and correctly
  sourced (same shared-state caution as Phase 2's Base/Total Effectiveness
  Projections bug).
- README: new sheet tab documented, Company Rankings feature described,
  10-star heuristic caveat spelled out plainly so it's never read as an
  official Torn number.

