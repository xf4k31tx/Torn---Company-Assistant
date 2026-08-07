# Torn Company Assistant Web-Migration Roadmap

**Status:** Phase 1 complete; Phase 2 next
**Date:** 2026-08-07
**Architecture:** [ADR-001: Web Application Migration](../architecture/ADR-001-web-application-migration.md)

## Current implementation status

- Phase 0 repository, architecture decisions, migration boundaries, and unchanged-file inventory are established.
- Phase 1 provides typed collection requests/results/data envelopes, deterministic progress events, and service ports for Torn, Torn Stats, persistence, jobs, and local workbooks.
- Framework-free Snapshot, Employee Efficiency, Run Everything, history-import, and scheduled-collection workflows run against mocked gateways and in-memory persistence.
- Async Torn and Torn Stats adapters sanitize transport failures without disclosing API keys.
- Torn API routes and response envelopes are implemented against `docs/planning/openapi.json`, the authoritative checked-in contract. Its live upstream source is `https://www.torn.com/swagger/openapi.json`.
- Reusable profit, ranking, income-tracking, and checksum tests have been ported as desktop-to-web calculation parity coverage.
- Position locks, assigned-position misplacement, Torn-authoritative current effectiveness, Torn Stats projections, stock deltas, profit/income, ranking, and star-band rules have desktop-to-web parity coverage.
- Phase 1 exit gates pass: the core imports no Tkinter or Google modules, strict type and lint checks pass, and progress stage sequences are tested.

## Guiding decisions

- PostgreSQL is the authoritative application database.
- The application has no Google authentication, Sheets, Drive, Picker, scope, or API dependency.
- Versioned local `.xlsx` workbooks provide portable company-history import, export, and backup.
- Existing Python domain logic is reused where practical.
- The web application must run locally on Windows before hosting is available.
- Local, staging, and production environments use the same service architecture.
- Every phase must be independently testable and leave the existing desktop application usable.
- No phase may expose Torn keys, Torn Stats keys, password hashes, session tokens, recovery data, or encryption keys.
- The previously approved Tkinter visual-modernization phases are replaced by this roadmap.

## Phase 0 — Baseline, branch strategy, and migration boundaries

### Deliverables

- Preserve the current desktop application and its passing test suite.
- Record representative desktop screenshots and expected calculations.
- Inventory reusable domain modules, desktop-specific dependencies, legacy Google integration code, and historical-data migration sources.
- Define API contracts for snapshots, employees, projections, rankings, stock, trends, settings, jobs, and reports.
- Establish web, migration, and release branches.
- Add architecture, security, and data-retention decision records.
- Define feature-parity acceptance criteria for every existing tab and popup.

### Exit gate

- Existing tests pass unchanged.
- Reusable and replaceable modules are documented.
- Desktop calculations have fixture data suitable for web parity tests.

## Phase 1 — Extract the reusable Python application core

### Deliverables

- Remove Tkinter, local Settings, and direct UI assumptions from collector workflows.
- Introduce service interfaces for Torn, Torn Stats, persistence, jobs, and local workbook import/export.
- Add typed request, result, and error models.
- Add actual progress-event callbacks to Snapshot, Employee Efficiency, Run Everything, imports, and scheduled collection.
- Preserve position locking, assignments, ranking, star-band, stock, income, and projection mathematics.
- Remove Google authentication, Sheets, Drive, Picker, and synchronization code from the web architecture.
- Keep the desktop application working through compatibility adapters until its historical data has been exported and web parity is accepted.

### Exit gate

- Core workflows run without importing Tkinter.
- Collector tests pass against in-memory or mocked persistence.
- Progress events are deterministic and tested.

## Phase 2 — Local desktop web-development environment

### Deliverables

- Add Dockerfiles and Docker Compose services for frontend, API, worker, scheduler, PostgreSQL, Redis, and reverse proxy.
- Add development and production-like local Compose profiles.
- Add a one-click Windows launcher such as `start-local.ps1` and a friendly wrapper shortcut.
- Wait for health checks and automatically open the default browser.
- Provide a stable localhost URL and documented shutdown command.
- Add hot reload for React and FastAPI development.
- Persist PostgreSQL data in a named local volume.
- Add local PostgreSQL backup and restore commands plus browser-based `.xlsx` history import/export.
- Ensure the application remains usable without internet except when calling Torn or Torn Stats.

### Exit gate

- A Windows user can start the full web application with one action.
- Browser, API, worker, database, and Redis health checks pass.
- Restarting local services preserves data.
- Local behavior matches the intended hosted architecture.

## Phase 3 — PostgreSQL schema and persistence layer

### Deliverables

- Add migration-managed tables for users, workspaces, memberships, roles, companies, encrypted credentials, configuration, jobs, job events, snapshots, employees, projections, assignments, stock, rankings, income history, star summaries, notifications, reports, and audit records.
- Add indexes for company, timestamp, reporting period, employee, ranking, and job queries.
- Add uniqueness and idempotency constraints for snapshots and scheduled periods.
- Implement repository interfaces used by the extracted core.
- Add transaction boundaries and rollback behavior.
- Add tenant-scoped queries and PostgreSQL row-level security where appropriate.
- Add retention and archival policies.

### Exit gate

- All schema migrations work on empty and populated databases.
- Tenant-isolation tests prevent cross-workspace access.
- Core workflows persist and reload complete results.

## Phase 4 — Authentication, authorization, and credential security

### Deliverables

- Add invite-controlled application accounts with Argon2id password hashing and optional TOTP or passkeys.
- Use secure, HttpOnly, SameSite cookies and CSRF protection.
- Add workspace membership and owner, manager, and viewer roles.
- Add invitation, removal, and role-change workflows.
- Encrypt Torn keys and Torn Stats keys with authenticated encryption.
- Store the master key outside PostgreSQL and support key rotation.
- Add credential redaction, audit events, session expiration, logout, and account deletion.
- Rate-limit authentication and credential endpoints.
- Add recovery codes and a secure administrator-assisted account recovery workflow.

### Exit gate

- Users can access only authorized workspaces and companies.
- Secrets never appear in API responses or logs.
- Encryption, rotation, session, CSRF, and authorization tests pass.

## Phase 5 — Background jobs, scheduling, and real-time progress

### Deliverables

- Run Snapshot, Employee Efficiency, Run Everything, imports, reports, and scheduled collection in Celery workers.
- Use Redis as the broker and progress-event transport.
- Add persistent job records, retries, timeouts, and failure stages.
- Add company-level locks and idempotency keys to prevent duplicate runs.
- Replace Windows Task Scheduler with a central scheduler.
- Support per-company schedules, time zones, selected operations, and next-run calculations.
- Stream job events to browsers through Server-Sent Events.
- Show operation name, company, actual stage, elapsed time, success, warning, and failure states.
- Preserve job history after the browser closes.

### Exit gate

- Jobs survive browser disconnection.
- Duplicate submissions do not create duplicate snapshots.
- Scheduled and manual jobs have tested retry and locking behavior.
- SSE reconnects and resumes without losing recorded stages.

## Phase 6 — FastAPI application API

### Deliverables

- Build versioned endpoints for companies, Overview, Employees, Position Efficiency, Company Rankings, Stock, Trends, Settings, schedules, jobs, notifications, scenarios, reports, spreadsheet imports/exports, and audit history.
- Add request validation and consistent error responses.
- Add pagination, sorting, filtering, and search contracts.
- Add OpenAPI documentation and generated frontend types.
- Add caching headers and server-side query caching where safe.
- Add health, readiness, and metrics endpoints.
- Add API integration and authorization tests.

### Exit gate

- Every existing desktop view has a documented API source.
- API tests cover success, validation, authorization, and failure cases.
- Large ranking, employee, stock, and history datasets remain responsive.

## Phase 7 — React foundation and design system

### Deliverables

- Create the React, TypeScript, and Vite application.
- Add routing, authenticated layouts, API client, query caching, and SSE job subscriptions.
- Build reusable cards, tables, filters, badges, tooltips, dialogs, legends, charts, loading states, empty states, and error boundaries.
- Add responsive navigation and a persistent company selector.
- Add light, dark, and system themes.
- Add compact and comfortable density options.
- Add accessible keyboard navigation, focus states, color contrast, and colorblind-safe score palettes.
- Add desktop, tablet, and mobile breakpoints.
- Add browser component and accessibility tests.

### Exit gate

- The web shell loads locally and through the production-like profile.
- Authentication, navigation, themes, company selection, and live job status work.
- Shared components satisfy accessibility and responsive-layout tests.

## Phase 8 — Existing feature parity

### Deliverables

- Rebuild Overview as KPI cards with grouped details and freshness indicators.
- Rebuild Employees with sorting, filtering, custom columns, totals, position locks, warning filters, frozen identity columns, and employee details.
- Rebuild Base and Total Position Efficiency with numeric sorting, legends, score colors, top-position emphasis, and comparison tools.
- Rebuild Company Rankings with sortable columns, search, star filter, Jump to My Company, own-company emphasis, pinned summary, and gap visuals.
- Rebuild Stock and Trends with interactive ranges, hover values, summary cards, comparison metrics, and responsive charts.
- Rebuild Settings for companies, roles, credentials, schedules, appearance, account management, and local spreadsheet backup/restore.
- Add the star-income range and ranking-neighbor dialogs.
- Match existing desktop calculations using shared fixtures.

### Exit gate

- Every current desktop tab and popup has an accepted web equivalent.
- Calculation parity tests pass.
- Manual desktop-browser review confirms feature parity.
- The desktop app remains available as a fallback.

## Phase 9 — Web-native decision-support features

### Deliverables

- Add notification center and per-tab freshness badges.
- Add staffing-problem and stale-data alerts.
- Add the assignment scenario planner with explicit apply confirmation.
- Add historical star-level and weekly-income timelines.
- Add management report generation and downloads.
- Add job, collection, and audit history views.
- Add optional Progressive Web App installation and desktop shortcut behavior.
- Add configurable notification preferences.

### Exit gate

- Scenarios never modify assignments before explicit confirmation.
- Reports match displayed values.
- Notifications deduplicate and link to actionable views.

## Phase 10 — Existing-data migration

### Deliverables

- Add an onboarding flow for workspace, company, Torn key, Torn Stats key, positions, and schedule.
- Import historical company data from the versioned local `.xlsx` workbook format.
- Add a desktop-assisted history exporter that creates a compatible `.xlsx` workbook without exporting DPAPI-protected settings or credentials.
- Require users to re-enter Torn and Torn Stats keys instead of transmitting decrypted desktop secrets.
- Validate imported snapshots, employees, rankings, stock, and star summaries.
- Produce migration reports showing accepted, skipped, and invalid records.
- Preserve original source data and support rollback before finalization.

### Exit gate

- Representative existing companies migrate successfully.
- Historical calculations and dates remain intact.
- No decrypted credential is written to an intermediate file.

## Phase 11 — Local spreadsheet history import, export, and backup

### Deliverables

- Define and document a versioned `.xlsx` workbook schema with a manifest sheet and separate sheets for supported company-history entities.
- Export selected companies, date ranges, and history categories directly as a browser download in both local and hosted modes.
- Exclude Torn keys, Torn Stats keys, password hashes, sessions, recovery data, encryption material, audit secrets, and server configuration from every workbook.
- Normalize timestamps to UTC, preserve stable record identifiers, and include the source company identity and export timestamp.
- Provide an import preview showing workbook version, company, date coverage, record counts, duplicates, conflicts, warnings, and rejected rows before data is committed.
- Support explicit merge-new, skip-duplicate, and controlled restore modes with transaction rollback on failure.
- Make repeated imports idempotent using stable identifiers and database uniqueness constraints.
- Treat uploaded workbooks as untrusted input: enforce file-size and row limits, parse values without executing formulas, reject macros and external links, and validate every sheet, field, type, timestamp, and company association.
- Stream temporary uploads and generated downloads without retaining them on the server longer than required for the operation.
- Record import and export audit events and provide a clear success/failure report.
- Keep automated encrypted PostgreSQL backups as the disaster-recovery mechanism; label spreadsheet files as portable user history backups.

### Exit gate

- Exporting and re-importing a representative company reproduces the same supported historical records and calculations.
- Re-importing the same workbook creates no duplicate history.
- Invalid, corrupted, oversized, or mismatched-company workbooks are rejected without partial database changes.
- Automated tests prove that no credential or authentication material can appear in an export.
- Import and export work identically from the Windows localhost launcher and the hosted application.

## Phase 12 — Hosted production environment

### Deliverables

- Deploy the Compose stack to the friend's server.
- Configure domain, DNS, Caddy HTTPS, firewall, persistent volumes, and least-privilege service accounts.
- Add encrypted off-server PostgreSQL backups and restore testing.
- Add monitoring for uptime, job failures, queue depth, database health, certificates, disk space, and API errors.
- Add centralized structured logs with secret redaction.
- Add deployment, rollback, migration, and incident-response procedures.
- Configure staging separately from production.
- Update Privacy Policy and Terms for server hosting, data retention, subprocessors, account deletion, and EEA/UK users.

### Exit gate

- Staging passes full automated and manual testing.
- Backup restoration is demonstrated.
- Security, privacy, performance, and accessibility reviews pass.
- Production deployment can be rolled back without data loss.

## Phase 13 — Beta, cutover, and desktop retirement

### Deliverables

- Run an invite-only beta with selected companies.
- Compare web and desktop results over multiple collection periods.
- Resolve parity, performance, and usability defects.
- Publish migration instructions and support procedures.
- Freeze new desktop features after web acceptance.
- Retain a time-limited desktop fallback and local `.xlsx` export tool.
- Remove legacy Google-related modules, packages, configuration fields, scopes, tests, credentials, and user-facing setup instructions after migration validation.
- Revoke the legacy OAuth credentials and disable its Google APIs after all required history exports are complete.
- Define the desktop application's end-of-support date.
- Archive final desktop source, executable, checksum, and migration documentation.

### Exit gate

- Web results match desktop results for accepted fixtures and beta companies.
- Users can complete normal operations without the desktop application.
- Production monitoring and support procedures are active.
- Production code, packages, configuration, and network activity contain no Google integration.
- Desktop retirement and legacy credential revocation are explicitly approved.

## Quality gates applied to every phase

- Existing applicable pytest tests remain green.
- New backend code has unit and integration tests.
- New frontend workflows have browser tests.
- Tenant isolation and credential redaction are tested.
- Database migrations have upgrade and rollback coverage.
- Documentation and the roadmap are updated with material decisions.
- No phase contains or depends on Google authentication, APIs, Sheets, Drive, Picker, or OAuth scopes.
- Local Windows desktop mode remains startable throughout development.
