# Knotty Oil Tracker

A Windows desktop app that pulls Torn company data (profile, stock,
employees, and Tornstats-projected position efficiency) via Torn's v2 API,
records snapshots in a Google Sheet per company, and provides a Tkinter
dashboard for current state, employee efficiency, and trends. Supports
tracking multiple companies from one installation, each with its own API
keys and its own Google Sheet.

## Data written to Google Sheets

Each configured company gets its own Google Sheet (existing ID, or
auto-created and named after the company on first run) with these tabs:

| Sheet tab | Contents | Write style |
| --- | --- | --- |
| `Company_History` | Company profile, financials, staffing, stock cost, 7-day rolling averages, and Company Health Score (rank vs. same-type companies by weekly income) | Append, newest first |
| `Stock_History` | Stock state, deltas from the preceding snapshot, and a stockout predictor (`days_until_stockout`) | Append, newest first |
| `Director_Efficiency` | Tornstats' own company-wide position-efficiency reference (separate from and not a substitute for per-employee data) | Append, newest first |
| `Employees` | Current employee roster and Torn's own per-employee effectiveness breakdown | Replace each Snapshot |
| `Employee_Effectiveness` | Per-employee Tornstats-projected efficiency at every position, best-fit position, capacity/priority-constrained assignment, misplaced-employee flag, and wage efficiency | Replace each Employee Efficiency run |
| `Position_Efficiency` | The same projections as a wide employee-by-position matrix (source for the GUI's Position Heatmap tab) | Replace each Employee Efficiency run |
| `Employee_Turnover_Log` | Join/leave events, diffed by employee ID against the previous `Employee_Effectiveness` roster | Append, newest first |

A sheet's header row is only ever extended, never reordered or shortened -
so an older sheet with fewer columns picks up any new ones automatically on
its next write, without misaligning historical rows.

## Two independent actions, or both together

- **Run Snapshot Now** - company profile/stock/employees + Health Score.
  Needs a Torn API key (Public API key optional - see below).
- **Run Employee Efficiency Now** - Tornstats-projected position
  efficiency, capacity/priority-constrained assignment, misplaced-employee
  and wage-efficiency flags, turnover log. Needs a Torn API key *and* a
  Tornstats API key.
- **Run Everything** - both, in one click.

A company missing a required key for a given action reports back a clear
failure message rather than being silently skipped.

## Setup

1. Create and activate a virtual environment, then install dependencies:

   ```
   pip install -r requirements.txt
   ```

2. In Google Cloud Console, enable the Google Sheets API and create an OAuth
   client with application type **Desktop app**. Download its JSON
   configuration. This configuration identifies the desktop app; it is not a
   Google service-account private key.

3. Start the app:

   ```
   python main.py
   ```

4. In **Settings**, sign in with Google (chooses the downloaded OAuth
   desktop-client JSON, then opens the system browser for consent).

5. In **Settings > Companies**, add each company you want to track:

   - **Torn API key** (required) - the company's limited-access key.
   - **Torn Public API key** (optional) - only needed for the Company
     Health Score, which ranks your company against every other public
     listing of the same type. Falls back to the limited-access key if
     left blank.
   - **Tornstats API key** (optional) - required only for Employee
     Efficiency runs, not for Snapshots.
   - **Google Sheet ID** (optional) - paste the ID of an existing Sheet to
     keep using it, or leave blank to have one auto-created and named
     after the company on first run. Either way, share any Sheet you paste
     in as **Editor** with every Google account that will use this app.

The Google OAuth refresh token, Torn/Tornstats API keys, and company
configurations are encrypted with Windows DPAPI in
`%LOCALAPPDATA%\\Knotty Oil Tracker\\secrets.dpapi`. They are usable only by
the same Windows account on the same machine.

## Migrating an existing installation

A pre-multi-company installation (a single Torn key + Sheet ID directly in
Settings, with no companies configured yet) still works for headless
commands via an automatic fallback, but won't show up in **Settings >
Companies** until you add it there explicitly.

After entering settings and signing in successfully, use **Remove Legacy
Plaintext Files** in Settings to remove legacy `.env`, `companies.json`, and
`service-account.json` files. The removal is not a guaranteed secure erase, so
rotate/revoke credentials that were ever copied, shared, or committed.

Do not distribute a shared Google service-account JSON file. Each app user
authorizes their own Google account, and access is managed by sharing or
removing their access to each company's Sheet.

## Running scheduled snapshots

After that Windows user has signed in once, a scheduled task under the same
Windows account can run:

```text
python main.py --snapshot             # Snapshot every configured company
python main.py --employee-efficiency  # Employee Efficiency pass for every configured company
python main.py --everything           # Both, for every configured company
python main.py --resort-history       # One-time: re-sort existing history tabs to newest-first
```

All four flags run headlessly and exit with a non-zero status if any
company failed.

## Project layout

```text
main.py                 GUI / headless entry point (--snapshot, --employee-efficiency, --everything, --resort-history)
app/config.py           DPAPI-encrypted per-user settings (Google OAuth, legacy single-company fallback)
app/companies.py        DPAPI-encrypted multi-company store (per-company API keys, Sheet, position config)
app/secure_storage.py   Windows DPAPI storage
app/google_auth.py      Google OAuth sign-in and token refresh
app/torn_api.py         Torn API wrapper (v2-first; v1 used only where v2 has no equivalent)
app/tornstats_api.py    Tornstats API wrapper (position-efficiency projections)
app/efficiency_calc.py  Per-employee position efficiency + capacity/priority-constrained assignment
app/profit_calc.py      Derived daily/weekly profit and 7-day rolling averages
app/sheets_client.py    Google Sheets read/write via per-user OAuth; auto-creates a company's Sheet if needed
app/collector.py        Snapshot / Employee Efficiency / Run Everything orchestration
gui/main_window.py      Tkinter GUI - Overview, Employees, Position Heatmap, Stock & Profit, Trends, Settings
scripts/                One-off maintenance/migration scripts (not run automatically)
```
