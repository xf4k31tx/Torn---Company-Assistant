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

- Separate Overview, Employees, Position Efficiency, Stock & Profit, Trends,
  and Settings tabs.
- A synchronized company selector across all data tabs. The last selected
  company persists between sessions.
- Independent Snapshot and Employee Efficiency operations, plus a combined
  Run Everything action.
- Sortable, filterable Employees grid with persistent custom column choices.
- Employee current-position locks that reserve those positions before the
  remaining assignment calculation fills available seats.
- Configurable position capacities and fill-priority order per company.
- Sortable Position Efficiency grid with configurable visible positions.
- Stock deltas, stockout estimates, profit history, health scoring, turnover
  tracking, wage-efficiency flags, and trend charts.
- Per-user Google OAuth and Windows DPAPI-protected local credentials.
- Headless commands suitable for Windows Task Scheduler.

## Effectiveness and assignment rules

Torn and Tornstats values have intentionally different roles:

- **Current Pos. Eff.** is Torn's authoritative
  `effectiveness_working_stats` value for the employee's current staffed
  position.
- **Position Efficiency**, **Best Fit**, and **Assigned Eff.** use Tornstats
  projections for hypothetical positions.
- The hidden-by-default **Current Pos. Projected Eff.** value remains available
  through **Columns...** for internally consistent Tornstats comparisons. It
  is not presented as the employee's real current effectiveness.
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
- A Totals footer for Wage, Total Eff., Current Pos. Eff., Addiction Eff.,
  Inactivity Eff., and Assigned Eff.

The **Run Employee Efficiency Now** button is located on this tab beside
**Refresh**. Position locks and custom column selections are saved immediately.

## Position Efficiency score colors

The Position Efficiency tab displays rounded Tornstats projection scores in
individually colored, numerically sortable cells:

| Score | Color |
| --- | --- |
| Below 50 | Red |
| 50–74 | Orange |
| 75–99 | Yellow |
| 100–124 | Green |
| 125+ | Dark green |

Missing or nonnumeric projections remain neutral. **Configure Positions**
controls which position columns are visible for the selected company.

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
| `Company_History` | Company profile, financials, staffing, stock cost, seven-day rolling averages, and health-score rank among same-type companies | Append, newest first |
| `Stock_History` | Stock state, changes from the preceding snapshot, sales, and stockout estimates | Append, newest first |
| `Director_Efficiency` | Tornstats company-wide position-efficiency reference | Append, newest first |
| `Employees` | Current roster and Torn's per-employee effectiveness breakdown | Replace each Snapshot |
| `Employee_Effectiveness` | Torn effectiveness, Tornstats projections, best fit, constrained assignment, misplaced flag, wage efficiency, and last-action timestamp | Replace each Employee Efficiency run |
| `Position_Efficiency` | Wide employee-by-position Tornstats projection matrix used by the Position Efficiency tab | Replace each Employee Efficiency run |
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

3. In Google Cloud Console, enable the Google Sheets API and Google Drive API.
4. Create an OAuth client with application type **Desktop app**, then download
   its JSON configuration. This identifies the desktop application; it is not
   a service-account private key.
5. Start TCA:

   ```powershell
   python main.py
   ```

6. In **Settings**, choose the OAuth desktop-client JSON, select
   **Save Securely**, and then select **Sign in with Google**.
7. In **Settings > Companies**, add each company:

   - **Torn API key** — required limited-access company key.
   - **Torn Public API key** — optional key used for Company Health Score
     comparisons; the limited-access key is used as fallback.
   - **Tornstats API key** — required only for Employee Efficiency operations.
   - **Google Sheet ID** — optional existing Sheet ID. Leave blank to create a
     Sheet automatically.

When using an existing Sheet, grant Editor access to every Google account that
will use it.

## Security and local data

Google OAuth credentials, Torn/Tornstats keys, company configuration, position
locks, and related settings are encrypted with Windows DPAPI in:

```text
%LOCALAPPDATA%\Knotty Oil Tracker\secrets.dpapi
```

The encrypted data is bound to the same Windows account and machine. Every user
must authorize Google and configure credentials on each machine. DPAPI does not
protect secrets from someone controlling the unlocked Windows account.

Do not distribute a shared Google service-account private key. Each user signs
in with their own Google account, and access is controlled through Google Sheet
sharing.

Employee-efficiency verification may be written locally to
`logs\efficiency_verification.log`. The log can include employee names, Torn
IDs, company information, matching details, positions, and projected values.

## Migrating an older installation

Legacy `.env` and `companies.json` values may be read once when encrypted
settings do not yet exist. Save the migrated values securely, verify Google
sign-in, and then use **Remove Legacy Plaintext Files** to remove `.env`,
`companies.json`, and `service-account.json`.

File deletion is not guaranteed secure erasure. Rotate or revoke keys and
credentials that were previously shared, committed, or otherwise exposed.

The **Sort Existing Rows (One-Time)** action rewrites existing
`Company_History`, `Stock_History`, and `Director_Efficiency` rows into
newest-first order without changing their values.

## Headless and scheduled operation

After the Windows user has completed Google sign-in once:

```text
python main.py --snapshot             # Snapshot every configured company
python main.py --employee-efficiency  # Efficiency pass for every company
python main.py --everything           # Run both operations
python main.py --resort-history       # One-time newest-first history migration
```

These commands are suitable for Windows Task Scheduler when run under the same
Windows account that owns the encrypted credentials. They exit with a nonzero
status when a company operation fails.

## Tests

Run the complete automated test suite from the repository root:

```powershell
python -m pytest
```

The tests cover mocked collection and Google Sheet writes, secure settings,
current-versus-projected effectiveness, misplaced calculations, position
locks, score bands, warning thresholds, totals, sorting, company selectors,
last-action formatting, and column persistence.

## Building the Windows executable

Install PyInstaller in the active environment, then build from the maintained
specification:

```powershell
python -m PyInstaller --noconfirm --clean "Knotty Oil Tracker.spec"
```

The specification collects both Matplotlib and the lazily imported
`google_auth_oauthlib` package. The generated executable is unsigned and may
trigger Microsoft Defender SmartScreen. Test-launch every new build and verify
Google sign-in, secure storage, and external configuration before distributing
it.

## Legal documents

Draft Terms of Service and Privacy Policy documents are stored in `legal\`.
They identify Khristian Boone, also known as sharpsplinter `[351311]`, and
include Ohio, EEA, and UK provisions. Replace all bracketed contact and
representative placeholders and obtain qualified legal review before
publication.

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
app/sheets_client.py    Google Sheets access and automatic Sheet creation
app/collector.py        Snapshot and Employee Efficiency orchestration
gui/main_window.py      Tkinter dashboard and settings interface
scripts/                Manual maintenance and migration scripts
tests/                  Pytest suite and mock endpoint data
legal/                  Draft Terms of Service and Privacy Policy
Knotty Oil Tracker.spec PyInstaller build specification
```
