# Architecture Decision Record

**Title:** Migrate Torn Company Assistant from a Windows desktop application to a self-hosted web application
**Status:** Accepted
**Date:** 2026-08-06

## Context

Torn Company Assistant is currently a Windows Tkinter application. It stores configuration locally, protects credentials with Windows DPAPI, uses a desktop OAuth loopback flow, schedules collection through Windows Task Scheduler, reads application views from remote spreadsheets, and writes collected data back to those spreadsheets.

The current application already contains reusable Python domain logic for Torn and Torn Stats API access, snapshots, employee effectiveness, position assignment, company rankings, income tracking, stock calculations, and scheduled collection. The principal desktop-specific areas are the Tkinter interface, local settings and DPAPI storage, desktop OAuth flow, direct Sheet-backed views, and Windows scheduling.

The application is intended to become a multi-user web application hosted on a server operated by a trusted third party. Before production hosting is available, the same web application must remain runnable and testable on a Windows desktop.

External spreadsheet and cloud-drive services are not required once PostgreSQL stores the application's operational data. Keeping a remote spreadsheet as the primary store would preserve network latency, repeat API reads, complicate multi-user isolation, and reproduce the desktop application's slow-loading behavior. Users still need a portable way to migrate and retain company history without relying on a third-party API.

## Decision

Torn Company Assistant will be migrated to a browser-based, self-hosted web application.

PostgreSQL will become the authoritative system of record for users, workspaces, companies, credentials, configuration, snapshots, employees, effectiveness projections, stock, trends, rankings, star-income summaries, jobs, notifications, and audit history.

All Google integration will be removed from the web application, including Google OAuth, Sheets, Drive, Picker, API scopes, synchronization, and related credentials. No Google service will be required for authentication, collection, storage, reporting, backup, or page rendering.

Users will import and export company history through locally saved `.xlsx` workbooks selected or downloaded through the browser. PostgreSQL remains authoritative; workbooks are portable migration and backup artifacts rather than a live datastore. The workbook format will be versioned and will contain separate sheets for supported historical entities plus a manifest describing schema version, export timestamp, and company identity. It will never contain Torn keys, Torn Stats keys, passwords, sessions, encryption keys, or other credentials.

The backend will use FastAPI and retain the existing Python calculation and API modules after they are separated from Tkinter and local-settings assumptions.

Long-running Snapshot, Employee Efficiency, Run Everything, import, and scheduled-collection operations will run in Celery workers through Redis. Actual job-stage events will be delivered to the browser using Server-Sent Events.

The web interface will use React, TypeScript, and Vite. PostgreSQL will be accessed through a migration-managed persistence layer. The production deployment will use Docker Compose with separate frontend, API, worker, scheduler, PostgreSQL, Redis, reverse-proxy, and backup services.

The application will be usable locally throughout development. A Windows launcher will start the same Docker Compose stack used for development, wait for service health checks, and open the browser to a localhost URL. Local mode will use PostgreSQL rather than a substitute database so development and production behavior remain aligned. Hot-reload commands may be provided for development, while a production-like local profile will be used for acceptance testing.

The existing desktop application will remain available as a fallback during migration. It will not receive the planned Tkinter visual redesign beyond fixes necessary to protect existing users or support migration.

Authentication will be app-managed and independent of third-party identity providers. The initial implementation will use invite-controlled accounts, securely hashed passwords, secure sessions, recovery codes, and optional TOTP or passkeys.

Server-side Torn keys and Torn Stats keys will be encrypted at rest using authenticated encryption and a master key stored outside PostgreSQL. Secrets will not appear in browser responses, logs, job payloads, or unencrypted backups.

All application data will be scoped to a workspace and company. Authorization checks are mandatory at the API and job layers; PostgreSQL row-level security may be used as defense in depth.

## Consequences

### Positive

- Web pages can load from PostgreSQL without waiting for Google Sheets.
- The application becomes accessible from Windows, macOS, Linux, tablets, and supported mobile browsers.
- Background jobs continue even if the user closes the browser.
- Central scheduling replaces per-computer Windows Scheduled Tasks.
- Credentials can be managed and rotated centrally.
- The same code and containers run locally, in staging, and in production.
- Removing all Google integration eliminates Google API quotas, OAuth scopes, branding verification, and external spreadsheet availability from the application lifecycle.
- Existing Python collection and calculation logic can be reused.
- PostgreSQL enables fast filtering, history, notifications, reporting, auditing, and multi-user access.
- Real job progress can be displayed through persistent server-side job records and SSE events.

### Negative

- This is a substantial application migration rather than a direct GUI conversion.
- The server operator becomes responsible for patching, HTTPS, uptime, monitoring, backups, restores, and incident response.
- DPAPI cannot protect server-side multi-user credentials and must be replaced.
- Existing users must create web credentials and re-enter Torn and Torn Stats keys through a controlled process.
- PostgreSQL, Redis, workers, and the reverse proxy introduce more operational components.
- Privacy Policy and Terms of Service must be updated for server-side storage and the hosting provider.
- The desktop and web applications must coexist temporarily until feature parity and migration validation are complete.

### Neutral and deferred

- Existing company history must first be saved as a compatible local `.xlsx` workbook before it can be imported.
- Spreadsheet backups are point-in-time exports; they do not replace automated PostgreSQL backups.
- A Progressive Web App installation may later provide a desktop-like shortcut, but it is not required for local development.
- Final production hosting details may change without changing the application architecture, provided the platform supports the required containers, persistent volumes, HTTPS, and backups.