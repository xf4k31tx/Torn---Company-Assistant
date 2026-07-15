# Knotty Oil Tracker

A Windows desktop app that pulls Torn company data, records snapshots in a
shared Google Sheet, and provides a Tkinter dashboard for current state and
trends.

## Data written to Google Sheets

| Sheet tab | Contents | Write style |
| --- | --- | --- |
| `Company_History` | Company profile, financial, staffing, and stock-cost snapshots | Append |
| `Employees` | Current employee roster and effectiveness data | Replace each snapshot |
| `Stock_History` | Stock state and changes from the preceding snapshot | Append |
| `Director_Efficiency` | Optional Tornstats position-efficiency reference | Append |

Torn's employee effectiveness is recorded in `Employees`. `Director_Efficiency`
is a separate Tornstats projection and should not be treated as full-roster
effectiveness data.

## Setup

1. Create and activate a virtual environment, then install dependencies:

   ```
   pip install -r requirements.txt
   ```

2. In Google Cloud Console, enable the Google Sheets API and create an OAuth
   client with application type **Desktop app**. Download its JSON
   configuration. This configuration identifies the desktop app; it is not a
   Google service-account private key.

3. Create the target Google Sheet and share it as **Editor** with every Google
   account that will use this app. Copy the Sheet ID from the Sheet URL.

4. Start the app:

   ```
   python main.py
   ```

5. In **Settings**, each user:

   - enters their own limited Torn API key (and optional Tornstats key);
   - chooses the downloaded Google OAuth desktop-client JSON;
   - enters the shared Google Sheet ID;
   - clicks **Save Securely** and then **Sign in with Google**.

The app opens the system browser for Google consent. The Google OAuth refresh
token, Torn API keys, and company configurations are encrypted with Windows
DPAPI in `%LOCALAPPDATA%\\Knotty Oil Tracker\\secrets.dpapi`. They are usable
only by the same Windows account on the same machine.

## Migrating an existing installation

After entering settings and signing in successfully, use **Remove Legacy
Plaintext Files** in Settings to remove legacy `.env`, `companies.json`, and
`service-account.json` files. The removal is not a guaranteed secure erase, so
rotate/revoke credentials that were ever copied, shared, or committed.

Do not distribute a shared Google service-account JSON file. Each app user
authorizes their own Google account, and access is managed by sharing or
removing their access to the target Sheet.

## Running scheduled snapshots

After that Windows user has signed in once, a scheduled task under the same
Windows account can run:

```text
python main.py --snapshot
```

## Project layout

```text
main.py                 GUI / headless entry point
app/config.py           DPAPI-encrypted per-user settings
app/secure_storage.py   Windows DPAPI storage
app/google_auth.py      Google OAuth sign-in and token refresh
app/sheets_client.py    Google Sheets read/write via per-user OAuth
app/collector.py        Snapshot collection orchestration
gui/main_window.py      Tkinter GUI
```
