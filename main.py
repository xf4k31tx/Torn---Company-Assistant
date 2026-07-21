#!/usr/bin/env python3
"""
Knotty Oil Tracker - entry point.

Usage:
    python main.py                     # launch the desktop GUI
    python main.py --snapshot          # run one snapshot headlessly (e.g. from cron/Task Scheduler) and exit
    python main.py --employee-efficiency  # run one employee-efficiency pass headlessly and exit
    python main.py --everything        # run a snapshot + an employee-efficiency pass headlessly and exit
    python main.py --resort-history    # one-time: re-sort existing history rows to newest-first and exit
"""

import sys


def _load_companies_or_legacy(settings):
    from app.companies import load_companies
    companies = load_companies()
    came_from_store = bool(companies)
    if not companies and settings.torn_api_key and settings.google_sheet_id:
        # Legacy/first-run fallback: no Companies configured yet, but the
        # encrypted default settings have a Torn key + Sheet - treat that
        # as a single company so headless commands still work pre-migration.
        # This ephemeral list did NOT come from the Companies store, so it
        # must never be handed to persist_companies() - see main()'s
        # `came_from_store` guard below.
        companies = [{
            "name": "Primary company",
            "torn_api_key": settings.torn_api_key,
            "tornstats_api_key": settings.tornstats_api_key,
            "google_sheet_id": settings.google_sheet_id,
            "google_sheet_name": settings.google_sheet_name,
        }]
    return companies, came_from_store


def main():
    if "--snapshot" in sys.argv:
        from app.collector import run_company_snapshots
        from app.config import Settings

        settings = Settings.load()
        companies, came_from_store = _load_companies_or_legacy(settings)
        if not companies:
            print("No companies configured. Add at least one company in Settings.")
            sys.exit(1)

        results = run_company_snapshots(companies, base_settings=settings)
        if came_from_store:
            from app.collector import persist_companies
            persist_companies(companies)
        overall_ok = True
        for name, result in results:
            print(f"[{name}] {result.message}")
            if result.ok:
                print(f"  Employees: {result.employee_count} | Stock rows: {result.stock_count} | Sheet: {result.sheet_url}")
            else:
                overall_ok = False
        sys.exit(0 if overall_ok else 1)
    elif "--employee-efficiency" in sys.argv:
        from app.collector import run_employee_efficiency_for_companies
        from app.config import Settings

        settings = Settings.load()
        companies, came_from_store = _load_companies_or_legacy(settings)
        if not companies:
            print("No companies configured. Add at least one company in Settings.")
            sys.exit(1)

        results = run_employee_efficiency_for_companies(companies, base_settings=settings)
        if came_from_store:
            from app.collector import persist_companies
            persist_companies(companies)
        overall_ok = True
        for name, result in results:
            print(f"[{name}] {result.message}")
            if result.ok:
                print(f"  Employees: {result.employee_count} | Misplaced: {result.misplaced_count} | Sheet: {result.sheet_url}")
            else:
                overall_ok = False
        sys.exit(0 if overall_ok else 1)
    elif "--everything" in sys.argv:
        from app.collector import run_everything_for_companies
        from app.config import Settings

        settings = Settings.load()
        companies, came_from_store = _load_companies_or_legacy(settings)
        if not companies:
            print("No companies configured. Add at least one company in Settings.")
            sys.exit(1)

        results = run_everything_for_companies(companies, base_settings=settings)
        if came_from_store:
            from app.collector import persist_companies
            persist_companies(companies)
        overall_ok = True
        for name, result in results:
            s, e = result.snapshot, result.employee_efficiency
            print(f"[{name}] {result.message}")
            if s.ok:
                print(f"  Snapshot: Employees: {s.employee_count} | Stock rows: {s.stock_count} | Sheet: {s.sheet_url}")
            if e.ok:
                print(f"  Employee Efficiency: Employees: {e.employee_count} | Misplaced: {e.misplaced_count}")
            if not result.ok:
                overall_ok = False
        sys.exit(0 if overall_ok else 1)
    elif "--resort-history" in sys.argv:
        from app.collector import resort_existing_history
        from app.config import Settings

        settings = Settings.load()
        companies, _came_from_store = _load_companies_or_legacy(settings)
        if not companies:
            print("No companies configured. Add at least one company in Settings.")
            sys.exit(1)

        results = resort_existing_history(companies, base_settings=settings)
        overall_ok = True
        for name, per_tab in results:
            if per_tab is None:
                print(f"[{name}] Could not reach this company's Sheet.")
                overall_ok = False
                continue
            parts = ", ".join(
                f"{tab}: {count if count is not None else 'failed'} row(s)"
                for tab, count in per_tab.items()
            )
            print(f"[{name}] {parts}")
            if any(count is None for count in per_tab.values()):
                overall_ok = False
        sys.exit(0 if overall_ok else 1)
    else:
        from gui.main_window import launch
        launch()


if __name__ == "__main__":
    main()
