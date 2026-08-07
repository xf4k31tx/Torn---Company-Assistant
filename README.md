# Torn Company Assistant

Torn Company Assistant (TCA) is a Windows desktop application for tracking
Torn companies. It retrieves company, stock, employee, and effectiveness data
from Torn, obtains hypothetical position-efficiency projections from
Tornstats, stores company-specific history in Google Sheets, and presents the
results in a Tkinter dashboard.

The application supports multiple companies from one Windows installation.
Each company has its own API keys, position configuration, and Google Sheet.
The packaged executable is currently named `Knotty Oil Tracker.exe`.

## Main features

- Overview, Employees, Stock & Profit Trends, and Settings top-level tabs.
  Overview nests a General sub-tab (the original company-metrics summary,
  including the clickable Health Score row) and a Company Rankings sub-tab.
  Employees nests Employee Overview and a Position Efficiency parent with
  Base Effectiveness Projections and Total Effectiveness Projections sub-tabs.
  Stock & Profit Trends nests Stock and Company Trends sub-tabs. A separate
  Legal menu next to File holds the TOS and Privacy Policy viewers.
- A synchronized company selector across all data tabs. The last selected
  company persists between sessions.
- Custom popup windows open centered within the main application window and
  are reduced to fit its visible bounds instead of appearing elsewhere on the
  desktop. Repeated clicks focus the existing matching popup instead of opening
  duplicates; closing it allows that popup to be opened again normally.
  Directly clickable fields append `(click for more info)` to their
  visible labels, including Health Score, Star 10 Count, and the Name field in
  the Position Efficiency grids.
- Independent Snapshot and Employee Efficiency operations, plus a combined
  Run Everything action.
- Sortable, filterable Employees grid with persistent custom column choices,
  and info (i) glyphs on every effectiveness column explaining what that
  field means - both on the grid headers and on the employee info card.
- Employee current-position locks that reserve those positions before the
  remaining assignment calculation fills available seats.
- Configurable position capacities and fill-priority order per company.
- Sortable Base and Total Effectiveness Projections grids with configurable
  visible positions.
- A per-item Stock sub-tab showing each item's last 7 snapshots (not just the
  latest), so you can compare against the prior week at a glance.
- Stock deltas, stockout estimates, daily/weekly/monthly profit history,
  Company Health Score ranking (with a 5-above/5-below neighbor popup and a
  full Company Rankings tab), turnover tracking, wage-efficiency flags, and
  trend charts.
- Per-user Google OAuth and Windows DPAPI-protected local credentials.
- Headless commands suitable for Windows Task Scheduler.
- A separate TCA Checksum Verifier utility so downloaded releases can be
  confirmed intact against a published SHA-256 manifest.

## Effectiveness and assignment rules

Torn and Tornstats values have intentionally different roles:

- **Work Stats Eff.** is Torn's authoritative
  `effectiveness_working_stats` value for the employee's current staffed
  position.
- **Position Efficiency**, **Best Fit**, and **Assigned Eff.** use Tornstats
  projections for hypothetical positions.
- **Current Eff.**, visible by default, is the Tornstats-projected
  (`projected_efficiency_current_position`) efficiency at the employee's
  current position — for internally consistent Tornstats comparisons. It
  is not presented as the employee's real current effectiveness; that is
  **Work Stats Eff.** above.
- **Misplaced** is true only when **Assigned Position** differs from the
  employee's current Torn position. Best Fit does not control this flag.
- A checked **Lock** beside an employee's current position forces the next
  Employee Efficiency run to assign that employee to that position first.
  Locked employees consume configured position and company capacity before
  remaining seats are filled.

The assignment calculation fills configured positions in priority order. For
each position, it selects the highest Tornstats-projected employees who remain
unassigned, subject to position and company capacity. Hard locks are honored
even when they exceed a configured capacity, and the run reports a warning.

**Total Effectiveness Projection** (shown on the Total Effectiveness
Projections sub-tab) extends the Base Effectiveness Projection at every
position by each employee's own non-work-stats effectiveness:

```text
Total Projection[position] = Base Projection[position]
                              + (effectiveness_total - effectiveness_working_stats)
```

Since Torn documents `effectiveness_total` as the sum of all 8 effectiveness
components for the employee's current position, that difference is exactly
the sum of the other 7 (settled in, education, addiction, inactivity,
management, book, merits) — the part of an employee's real effectiveness
that raw work stats alone don't explain. A cell is left blank wherever the
underlying Base Effectiveness Projection is also blank for that
employee/position.

## Employees tab

The Employees grid includes:

- Numeric sorting, name filtering, persistent column selection, and horizontal
  and vertical scrolling.
- A human-readable **Time Since Last Action** value such as `2d 4h ago`.
- Position cells colored green when current and assigned positions match, or
  red when they differ.
- Addiction and Inactivity values shown with a warning and red cell when the
  value is `-10` or lower.
- Row warnings for misplaced employees and wage-efficiency outliers.
- A Totals footer for Wage and every effectiveness column shown (Total,
  Work Stats, Current, Settled In, Education, Addiction, Inactivity,
  Management, Book, Merits), plus Assigned Eff.

The **Run Employee Efficiency Now** button is located on this tab beside
**Refresh**. Position locks and custom column selections are saved immediately.

## Stock tab

The **Stock** sub-tab (under Stock & Profit Trends) shows each stock item's
last 7 snapshots - current plus the 6 prior days - rather than collapsing to
a single latest-only row, so you can compare in-stock, sold, cost, price, and
created counts against the prior week at a glance. Rows are grouped by item
name with the newest snapshot on top of each item's block. A chart of total
sold worth over time, below the table, still covers the full snapshot
history rather than just the 7 rows shown per item.

## Position Efficiency score colors

The Base Effectiveness Projections and Total Effectiveness Projections
sub-tabs (under Employees > Position Efficiency) display rounded projection
scores in individually colored, numerically sortable cells. Both sub-tabs
share the same table shape (one row per employee, one column per position)
and the same score-color bands - the only difference is what each cell
represents:

- **Base Effectiveness Projections** shows Tornstats' bare work-stats-only
  projection per position (the `Position_Efficiency` sheet tab).
- **Total Effectiveness Projections** adds each employee's non-work-stats
  effectiveness (settled in, education, addiction, inactivity, management,
  book, merits) on top of that same base projection, for every position
  (the `Total_Effectiveness_Projections` sheet tab). A cell is blank
  wherever the underlying base projection is also blank.

| Score | Color |
| --- | --- |
| Below 50 | Red |
| 50–74 | Orange |
| 75–98 | Yellow |
| 99–128 | Green |
| 129+ | Dark green |

Missing or nonnumeric projections remain neutral. **Configure Positions**
controls which position columns are visible for the selected company, and
applies to both sub-tabs.

## Company Health Score & Rankings

The **Health Score (rank by income)** row on Overview > General shows the
company's current rank by weekly income among every other company of the
same type, its percentile, and whether that rank moved up, down, or stayed
the same since the last snapshot. Clicking that row opens a popup listing
the 5 same-type companies immediately above and 5 immediately below the
company in the current ranking, each with name, rating, and daily/weekly
income, with the company's own row bolded.

The **Company Rankings** sub-tab (Overview > Company Rankings) shows the
full same-type ranking. Click any **Rank**, **Name**, **Rating**, **Daily
Income**, or **Weekly Income** heading to sort that column ascending or
descending. The company's own summary remains locked above the sortable,
scrollable list, showing its rank, current income, observed range position,
weekly-income gaps to the next and previous star levels, and change since
yesterday. The duplicate Rolling
7-Day Income and Observed Next-Star Gap displays are intentionally omitted.
The observed range position and displayed next/previous-star gaps are
recalculated from the current `Company_Rankings` and `Star_Income_Summary`
sheets whenever the tab refreshes; stored `Company_History` values are used
only as a fallback.

Clicking **Star 10 Count** on Overview > General opens a sortable
**Projected Weekly Income Ranges by Star Level** table. Current star counts define the
number of slots at each level. Every same-type company is then ordered by
current Weekly Income, highest to lowest, and those fixed slot counts are
applied down the ranked list. This means a 9-star company already earning
inside the top 10-star slot count contributes to the projected 10-star range,
while the displaced 10-star company falls into the projected 9-star range.

The table shows **Star Level**, **Company Count**, **Minimum Weekly
Income**, **Median Weekly Income**, **Top Performer Weekly Income**,
**Companies Included**, **Data Status**, and **Last Updated (UTC)**. P10 and
P90 remain available in the underlying Sheet data but are intentionally
hidden from the popup. A **Column Guide** explains how every visible value is
used. Each fixed 18:10 UTC daily observation uses Torn's current Weekly Income
value directly, so one successful collection populates the ranges. Completed
Sunday-to-Sunday summaries are retained for up to 12 weeks.

Overview > General dynamically labels the promotion and demotion fields for
the selected company's current level, such as **Income to Reach 10 Star** and
**Income to Drop to 8 Star** for a 9-star company. **Required Weekly Income
to Star Up** displays the absolute Weekly Income at the last slot of the next
star band; the income-to-reach value is the remaining gap between the
company's current Weekly Income and that cutoff. The redundant Observed
Next-Star Gap and Observed Drop Buffer rows are hidden from General because
they duplicate the generalized income-to-reach and income-to-drop fields.

These values are **empirical estimates, not Torn's own (unpublished,
multi-factor) rating formula**. Star counts are refreshed daily but are only
expected to change following Torn's Sunday rating update. Income ordering and
projected slot occupants can change throughout the week. Treat every value as
an income-based performance benchmark, not a guaranteed promotion threshold.

## Operations

The run buttons process every configured company. The synchronized company
selector controls which company's stored results are displayed; it does not
limit a run to only the selected company.

- **Run Snapshot Now** retrieves company profile, stock, employees, and health
  score data. It requires a Torn API key. A separate public Torn key is
  optional.
- **Run Employee Efficiency Now** retrieves Tornstats projections, performs
  capacity/priority/lock-aware assignments, updates misplaced and
  wage-efficiency flags, and records turnover. It requires Torn and Tornstats
  API keys.
- **Run Everything** performs both operations.
- **Refresh From Sheet** reloads the selected company's displayed data.

An operation that lacks a required key reports a clear failure instead of
silently skipping the company.

## Google Sheets data

Each configured company uses its own Google Sheet. An existing Sheet ID may be
provided, or the application can create a Sheet named after the company on its
first write.

| Sheet tab | Contents | Write style |
| --- | --- | --- |
| `Company_History` | Company profile, financials, staffing, stock cost, rolling averages, health-score rank, generalized next/previous-star gaps, and required Weekly Income to star up | Append, newest first |
| `Stock_History` | Stock state, changes from the preceding snapshot, sales, and stockout estimates | Append, newest first |
| `Director_Efficiency` | Tornstats company-wide position-efficiency reference | Append, newest first |
| `Employees` | Current roster and Torn's per-employee effectiveness breakdown | Replace each Snapshot |
| `Employee_Effectiveness` | Torn effectiveness, Tornstats projections, best fit, constrained assignment, misplaced flag, wage efficiency, and last-action timestamp | Replace each Employee Efficiency run |
| `Position_Efficiency` | Wide employee-by-position Tornstats projection matrix used by the Base Effectiveness Projections sub-tab | Replace each Employee Efficiency run |
| `Total_Effectiveness_Projections` | Wide employee-by-position matrix: each Position_Efficiency base projection plus that employee's non-work-stats effectiveness delta (effectiveness_total − effectiveness_working_stats), used by the Total Effectiveness Projections sub-tab | Replace each Employee Efficiency run |
| `Company_Rankings` | Every same-type company from the latest Health Score fetch (rank, name, rating, daily/weekly income, and whether it's the director's own company), used by the Company Rankings sub-tab and the Health Score neighbor popup | Replace each Snapshot or scheduled income run |
| `Company_Income_History` | Per-company daily and Weekly Income observations keyed to fixed 18:10 UTC reporting periods | Replace with the bounded snapshot history |
| `Star_Income_Summary` | Current rank-slot-based Weekly Income min/P10/median/P90/max range, count, coverage, and freshness for every star level | Replace each Snapshot or scheduled income run |
| `Star_Income_Summary_History` | Completed Sunday-to-Sunday star-level summaries retained for up to 12 weeks | Replace with bounded weekly history |
| `Employee_Turnover_Log` | Join and leave events detected by employee ID | Append, newest first |

Existing Sheet headers are extended when new columns are introduced; they are
not reordered or shortened.

## Requirements

- Windows, because secure local storage uses Windows DPAPI.
- Python and the packages listed in `requirements.txt`.
- A limited-access Torn API key for each company.
- A Tornstats API key for Employee Efficiency features.
- A Google account and Google OAuth Desktop app client.

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. In Google Cloud Console, enable the Google Sheets API, Google Drive API, and Google Picker API.
4. Create an OAuth client with application type **Desktop app**, then place its
   downloaded JSON configuration in the project root. The ignored
   `client_secret_*.json` file is auto-discovered for development and embedded
   under a neutral internal resource name in production builds; never commit it.
5. Start TCA:

   ```powershell
   python main.py
   ```

6. In **Settings**, select **Sign in with Google**. Production users are not
   prompted for an OAuth configuration file or shown its filename.
7. In **Settings > Companies**, add each company:

   - **Torn API key** — required limited-access company key.
   - **Torn Public API key** — optional key used for Company Health Score
     comparisons; the limited-access key is used as fallback.
   - **Tornstats API key** — required only for Employee Efficiency operations.
   - **Google Sheet** — after a company is added, Google Picker opens so you can
     explicitly select that company's existing Sheet. If selection is canceled,
     leave the assignment blank and TCA creates a new Sheet on the first run.

The OAuth flow requests only `drive.file`; TCA can access Sheets it creates or
that the user explicitly selects with Google Picker. When sharing an existing
Sheet, grant Editor access to every Google account that will use it.

## Security and local data

Google OAuth credentials, Torn/Tornstats keys, company configuration, position
locks, and related settings are encrypted with Windows DPAPI in:

```text
%LOCALAPPDATA%\Knotty Oil Tracker\secrets.dpapi
```

The encrypted data is bound to the same Windows account and machine. Every user
must authorize Google and configure credentials on each machine. DPAPI does not
protect secrets from someone controlling the unlocked Windows account.

Each user signs in with their own Google account via the per-user OAuth flow
described above; TCA does not use a shared Google service account. Access to
a company's Sheet is controlled entirely through normal Google Sheet sharing.

Employee-efficiency verification may be written locally to
`logs\efficiency_verification.log`. The log can include employee names, Torn
IDs, company information, matching details, positions, and projected values.

## Migrating an older installation

Legacy `.env` (read by `app/config.py`) and `companies.json` (read by
`app/companies.py`) values are read once, automatically, only when no
encrypted settings exist yet in DPAPI storage. Save the migrated values in
**Settings**, or add/edit any company, to persist them into the encrypted
store. There is no in-app action that deletes the legacy plaintext files —
once migration is confirmed working, delete `.env` and `companies.json` from
the project folder yourself.

File deletion is not guaranteed secure erasure. Rotate or revoke keys and
credentials that were previously shared, committed, or otherwise exposed.

The **Sort Existing Rows (One-Time)** action rewrites existing
`Company_History`, `Stock_History`, and `Director_Efficiency` rows into
newest-first order without changing their values.

## Headless and scheduled operation

After the Windows user has completed Google sign-in once:

```text
python main.py --snapshot             # Snapshot every configured company
python main.py --scheduled-daily-income # Update stale rolling-income data only
python main.py --employee-efficiency  # Efficiency pass for every company
python main.py --everything           # Run both operations
python main.py --resort-history       # One-time newest-first history migration
```

These commands are suitable for Windows Task Scheduler when run under the same
Windows account that owns the encrypted credentials. They exit with a nonzero
status when a company operation fails.

Settings includes an optional **Scheduled Daily Collection** panel. It creates
a non-admin, per-user Windows task that launches hourly but exits immediately
unless the current 18:10 UTC reporting period is stale. This avoids duplicate
collection and daylight-saving-time drift while still producing only one
daily observation. Users can include all or selected companies, optionally
wake the computer, run a test, repair the task, and view its last/next run and
result. No API keys, Google tokens, or Sheet IDs are placed in task arguments.

## Tests

Run the complete automated test suite from the repository root:

```powershell
python -m pytest
```

The tests cover mocked collection and Google Sheet writes, secure settings,
current-versus-projected effectiveness, misplaced calculations, position
locks, score bands, warning thresholds, totals, sorting, company selectors,
last-action formatting, column persistence, checksum manifest parsing and
file-integrity verification, Google OAuth scope/config handling, monthly
income/profit rolling calculations, per-item stock history selection, info-
glyph field explanations, and Company Health Score ranking - including the
v2 cursor-pagination fetch, daily star-count refresh, fixed-count
rank-slot allocation, generalized promotion/demotion thresholds, direct
Weekly Income snapshots aligned to 18:10 UTC, coverage/percentile boundaries,
the observed-range popup, scheduled-task XML/gating, the neighbor popup, and
the Company Rankings tab.

## Building the Windows executable

Install PyInstaller in the active environment, then build from the maintained
specification:

```powershell
python -m PyInstaller --noconfirm --clean "Knotty Oil Tracker.spec"
```

The specification collects Matplotlib and the lazily imported
`google_auth_oauthlib` package. It also validates the ignored local OAuth
configuration, stages it under a neutral resource name, and embeds it in the
one-file executable without exposing the downloaded filename. The generated
executable is unsigned and may trigger Microsoft Defender SmartScreen.
Test-launch every new build and verify Google sign-in, secure storage, and
external configuration before distributing it.

Build the separate file-integrity verifier and generate the main executable's
release checksum:

```powershell
python -m PyInstaller --noconfirm --clean "TCA Checksum Verifier.spec"
python scripts/generate_release_checksum.py "dist\Knotty Oil Tracker.exe"
```

Distribute `TCA Checksum Verifier.exe` and
`Knotty Oil Tracker.exe.sha256` alongside the application. Publish the same
SHA-256 value on the official TCA website or release page so users can compare
against a source independent of the downloaded executable.

## Legal documents

Draft Terms of Service and Privacy Policy documents are stored in `legal\`
as `.docx` files, and are viewable in-app from the **Legal** menu (next to
**File**) via **TOS** and **Privacy Policy**. They identify Khristian Boone,
also known as sharpsplinter `[351311]`, and include Ohio, EEA, and UK
provisions. Replace all bracketed contact and representative placeholders
and obtain qualified legal review before publication.

## Project layout

```text
main.py                 GUI and headless entry point
app/config.py           DPAPI-protected per-user settings
app/companies.py        DPAPI-protected multi-company configuration
app/secure_storage.py   Windows DPAPI storage
app/google_auth.py      Google OAuth sign-in and token refresh
app/torn_api.py         Torn API wrapper
app/tornstats_api.py    Tornstats projection API wrapper
app/efficiency_calc.py  Projection, best-fit, locking, and assignment logic
app/profit_calc.py      Profit fields and seven-day rolling averages
app/ranking_calc.py     Company Health Score ranking and generalized star-slot math
app/income_tracking.py   18:10-aligned Weekly Income snapshots and star-range math
app/scheduled_collection.py  Idempotent background collection and locking
app/windows_scheduler.py Windows Scheduled Task installation and status
app/sheets_client.py    Google Sheets access and automatic Sheet creation
app/collector.py        Snapshot and Employee Efficiency orchestration
app/checksum.py         SHA-256 hashing and .sha256 manifest parsing
gui/main_window.py      Tkinter dashboard and settings interface
verify_checksum.py      Standalone TCA Checksum Verifier GUI/CLI entry point
scripts/generate_release_checksum.py  Writes a release build's .sha256 manifest
scripts/backfill_company_history.py   One-off Company_History profit-formula migration
tests/                  Pytest suite and mock endpoint data
legal/                  Draft Terms of Service and Privacy Policy
Knotty Oil Tracker.spec PyInstaller build specification
TCA Checksum Verifier.spec Integrity-verifier build specification
```
