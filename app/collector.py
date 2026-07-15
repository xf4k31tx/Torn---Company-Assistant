"""
Orchestrates one full snapshot:

  1. Pull the company profile/detailed/employees/stock from the Torn API
     (single v2 call).
  2. Pull the director's own position-efficiency projection from Tornstats
     (a *separate* thing from Torn's per-employee "effectiveness" - see the
     note on EMPLOYEE_EFFECTIVENESS_KEYS below).
  3. Compute deltas against the last Stock_History snapshot.
  4. Write everything to three tabs in the target Google Sheet:
       - Company_History   (append-only, one row per run)
       - Employees          (overwritten every run - current roster only)
       - Stock_History      (append-only, one row per stock per run)
       - Director_Efficiency (append-only, one row per run)

Note on daily_profit / weekly_profit: Torn's API has no direct "profit"
selection, so both are derived (see app/profit_calc.py):
  daily_profit  = daily_income - (daily_stockcost + advertising_budget + total_wage)
  weekly_profit = weekly_income - (advertising_budget + total_wage) * 7
These are approximations - they don't account for one-off costs (upgrade
purchases, etc.) that Torn doesn't expose, so treat them as directional
numbers rather than an exact P&L figure.

Note on avg_daily_profit_7day: rolling average of daily_profit across all
snapshots taken within the current Torn week (Sunday 14:00 UTC -> the
following Sunday 14:00 UTC). It updates with every snapshot during the
week rather than only being computed once the week is over.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass
from typing import Optional

from .config import Settings
from .profit_calc import compute_avg_daily_income_7day, compute_avg_daily_profit_7day, compute_row_profit_fields
from .sheets_client import SheetsClient
from .torn_api import TornAPI, TornAPIError
from .tornstats_api import TornStatsAPI, TornStatsAPIError

COMPANY_HISTORY_HEADERS = [
    "timestamp", "date", "name", "rating", "employees_hired", "employees_capacity",
    "daily_income", "daily_profit", "daily_customers", "weekly_income", "weekly_profit",
    "weekly_customers", "days_old",
    "company_funds", "popularity", "efficiency", "environment", "trains_available",
    "advertising_budget", "upgrade_company_size", "upgrade_staffroom_size",
    "upgrade_storage_size", "upgrade_storage_space", "total_wage",
    "avg_employee_effectiveness", "daily_stockcost",
    "avg_daily_profit_7day", "avg_daily_income_7day",
]

EMPLOYEES_HEADERS = [
    "tId", "name", "position", "wage", "days_in_company", "last_action_ts",
    "effectiveness_total", "effectiveness_working_stats", "effectiveness_settled_in",
    "effectiveness_director_education", "effectiveness_addiction",
    "effectiveness_inactivity", "effectiveness_management", "effectiveness_book",
    "effectiveness_merits",
]

STOCK_HISTORY_HEADERS = [
    "timestamp", "date", "name", "in_stock", "on_order", "cost", "price",
    "sold_amount", "sold_worth", "delta_in_stock", "delta_sold_amount",
    "delta_sold_worth", "created",
]

DIRECTOR_EFFICIENCY_HEADERS = ["timestamp", "date", "position", "efficiency"]

# Torn's own per-employee effectiveness breakdown keys (this is real, accurate
# per-employee data straight from the company API - no guessing involved).
EFFECTIVENESS_KEYS = [
    "working_stats", "settled_in", "director_education", "addiction",
    "inactivity", "management", "book", "merits", "total",
]


def _ts_to_date(ts: int) -> str:
    import datetime
    try:
        return datetime.datetime.utcfromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return ""


def _get_24h_period_start(ts: int) -> int:
    """Get the start of the 24-hour period (2pm UTC) for the given timestamp.
    Period is 14:00 UTC to 14:00 UTC next day.
    
    Returns the period start as a UTC timestamp."""
    dt = datetime.datetime.utcfromtimestamp(ts)
    # Calculate seconds since midnight UTC
    seconds_today = dt.hour * 3600 + dt.minute * 60 + dt.second
    # 2pm UTC = 14 * 3600 = 50400 seconds
    period_start_secs = 14 * 3600
    
    if seconds_today < period_start_secs:
        # Before 2pm, so period started yesterday at 2pm
        period_ts = ts - seconds_today - (24 * 3600 - period_start_secs)
    else:
        # At or after 2pm, so period started today at 2pm
        period_ts = ts - seconds_today + period_start_secs
    
    return period_ts


def _is_same_24h_period(ts1: int, ts2: int) -> bool:
    """Check if two timestamps are in the same 24-hour period (2pm-2pm UTC)."""
    return _get_24h_period_start(ts1) == _get_24h_period_start(ts2)


@dataclass
class SnapshotResult:
    ok: bool
    message: str
    company_name: str = ""
    employee_count: int = 0
    stock_count: int = 0
    sheet_url: str = ""
    is_update: bool = False  # True if we updated existing snapshot, False if we appended new one


class Collector:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings.load()

    def _clients(self):
        s = self.settings
        torn = TornAPI(api_key=s.torn_api_key)
        tornstats = TornStatsAPI(api_key=s.tornstats_api_key) if s.tornstats_api_key else None
        sheets = SheetsClient(
            sheet_id=s.google_sheet_id,
            sheet_name=s.google_sheet_name,
        )
        return torn, tornstats, sheets

    def run_snapshot(self) -> SnapshotResult:
        if not self.settings.torn_api_key:
            return SnapshotResult(False, "No Torn API key configured. Add one in Settings.")

        try:
            torn, tornstats, sheets = self._clients()
        except Exception as e:
            return SnapshotResult(False, f"Setup failed: {e}")

        try:
            data = torn.get_company()
        except TornAPIError as e:
            return SnapshotResult(False, f"Torn API error: {e.message}")
        except Exception as e:
            return SnapshotResult(False, f"Could not reach Torn API: {e}")

        profile = data.get("company", {})
        detailed = data.get("company_detailed", {})
        employees = data.get("company_employees", {}) or {}
        stock = data.get("company_stock", {}) or {}
        timestamp = int(data.get("timestamp", time.time()))
        upgrades = detailed.get("upgrades", {})

        # ---------------------------------------------------- employees --
        total_wage = 0
        eff_totals = []
        employee_rows = []
        for tid, emp in employees.items():
            eff = emp.get("effectiveness", {}) or {}
            wage = int(emp.get("wage", 0) or 0)
            total_wage += wage
            eff_total = eff.get("total", 0) or 0
            eff_totals.append(eff_total)

            last_action = emp.get("last_action", {})
            last_action_ts = last_action.get("timestamp", "") if isinstance(last_action, dict) else last_action

            employee_rows.append([
                tid,
                emp.get("name", ""),
                emp.get("position", ""),
                wage,
                emp.get("days_in_company", ""),
                last_action_ts,
                eff.get("total", 0),
                eff.get("working_stats", 0),
                eff.get("settled_in", 0),
                eff.get("director_education", 0),
                eff.get("addiction", 0),
                eff.get("inactivity", 0),
                eff.get("management", 0),
                eff.get("book", 0),
                eff.get("merits", 0),
            ])

        avg_effectiveness = round(sum(eff_totals) / len(eff_totals), 2) if eff_totals else 0

        # -------------------------------------------------------- stock --
        previous_stock_rows = sheets.read_records("Stock_History")
        previous_by_name = {}
        for row in previous_stock_rows:
            name = row.get("name")
            ts = int(row.get("timestamp") or 0)
            if ts >= timestamp:
                continue
            if name not in previous_by_name or ts > int(previous_by_name[name].get("timestamp", 0)):
                previous_by_name[name] = row

        daily_stockcost = 0
        stock_rows = []
        for name, s in stock.items():
            in_stock = int(s.get("in_stock", 0) or 0)
            cost = float(s.get("cost", 0) or 0)
            sold_amount = int(s.get("sold_amount", 0) or 0)
            sold_worth = float(s.get("sold_worth", 0) or 0)
            daily_stockcost += sold_amount * cost

            prev = previous_by_name.get(name)
            if prev:
                delta_in_stock = in_stock - int(prev.get("in_stock", 0) or 0)
                delta_sold_amount = sold_amount - int(prev.get("sold_amount", 0) or 0)
                delta_sold_worth = sold_worth - float(prev.get("sold_worth", 0) or 0)
            else:
                delta_in_stock = in_stock
                delta_sold_amount = sold_amount
                delta_sold_worth = sold_worth

            # Calculate created: inventory change + current day sold_amount
            # Formula from YATA: created = delta_in_stock + sold_amount
            # sold_amount is the daily variable amount (not cumulative)
            created = delta_in_stock + sold_amount

            stock_rows.append([
                timestamp, _ts_to_date(timestamp), name, in_stock,
                s.get("on_order", 0), cost, s.get("price", 0), sold_amount, sold_worth,
                delta_in_stock, delta_sold_amount, delta_sold_worth,
                created,
            ])

        # ------------------------------------------------------ company --
        daily_income = float(profile.get("daily_income", 0) or 0)
        weekly_income = float(profile.get("weekly_income", 0) or 0)
        advertising_budget = float(detailed.get("advertising_budget", 0) or 0)

        profit_fields = compute_row_profit_fields(
            daily_income=daily_income,
            weekly_income=weekly_income,
            advertising_budget=advertising_budget,
            total_wage=total_wage,
            daily_stockcost=daily_stockcost,
        )

        prior_company_rows = sheets.read_records("Company_History")
        avg_daily_profit_7day = compute_avg_daily_profit_7day(
            prior_rows=prior_company_rows,
            current_timestamp=timestamp,
            current_daily_profit=profit_fields["daily_profit"],
        )
        avg_daily_income_7day = compute_avg_daily_income_7day(
            prior_rows=prior_company_rows,
            current_timestamp=timestamp,
            current_daily_income=daily_income,
        )

        company_row = [
            timestamp, _ts_to_date(timestamp),
            profile.get("name", ""), profile.get("rating", ""),
            profile.get("employees_hired", ""), profile.get("employees_capacity", ""),
            profile.get("daily_income", ""), profit_fields["daily_profit"], profile.get("daily_customers", ""),
            profile.get("weekly_income", ""), profit_fields["weekly_profit"],
            profile.get("weekly_customers", ""), profile.get("days_old", ""),
            detailed.get("company_funds", ""), detailed.get("popularity", ""),
            detailed.get("efficiency", ""), detailed.get("environment", ""),
            detailed.get("trains_available", ""), detailed.get("advertising_budget", ""),
            upgrades.get("company_size", ""), upgrades.get("staffroom_size", ""),
            upgrades.get("storage_size", ""), upgrades.get("storage_space", ""),
            total_wage, avg_effectiveness, round(daily_stockcost, 2),
            avg_daily_profit_7day, avg_daily_income_7day,
        ]

        # ----------------------------------------------- director effic. --
        director_rows = []
        if tornstats is not None:
            try:
                eff_data = tornstats.get_efficiency()
                for _, block in eff_data.items():
                    if not isinstance(block, dict) or "company" not in block:
                        continue
                    for position, value in block.items():
                        if position == "company":
                            continue
                        director_rows.append([timestamp, _ts_to_date(timestamp), position, value])
            except TornStatsAPIError:
                pass  # non-fatal - company/employee data still gets written
            except Exception:
                pass

        # -------------------------------------------------------- write --
        prior_company_rows = sheets.read_records("Company_History")
        is_same_period = False

        if prior_company_rows:
            # Find the most recent prior snapshot by timestamp, not by row
            # position - new rows are inserted at the top of the sheet, so
            # position no longer implies recency.
            last_row = max(prior_company_rows, key=lambda r: int(r.get("timestamp") or 0))
            last_ts = int(last_row.get("timestamp") or 0)
            is_same_period = _is_same_24h_period(timestamp, last_ts)
        
        # Only append new rows if it's a different 24h period
        # If same period, we just re-verified the current data (Employees sheet is refreshed)
        if not is_same_period:
            sheets.append_history_row("Company_History", COMPANY_HISTORY_HEADERS, company_row)
            sheets.append_history_rows("Stock_History", STOCK_HISTORY_HEADERS, stock_rows)
            if director_rows:
                sheets.append_history_rows("Director_Efficiency", DIRECTOR_EFFICIENCY_HEADERS, director_rows)
        
        # Always refresh Employees (current roster only)
        sheets.overwrite_current_state("Employees", EMPLOYEES_HEADERS, employee_rows)

        return SnapshotResult(
            ok=True,
            message="Snapshot complete." + (" (Verified data - same 24h period)" if is_same_period else ""),
            company_name=profile.get("name", ""),
            employee_count=len(employee_rows),
            stock_count=len(stock_rows),
            sheet_url=sheets.url,
            is_update=is_same_period,
        )


def run_company_snapshots(companies: list, base_settings: Optional[Settings] = None) -> list:
    """
    Run one snapshot per company dict and return [(name, SnapshotResult), ...].

    This is the single implementation of "run N companies" shared by the GUI
    (Settings > Companies) and headless `python main.py --snapshot`, so the
    two modes can't drift out of sync with each other the way they used to.

    Each company dict may provide: name, torn_api_key, tornstats_api_key,
    google_sheet_id, google_sheet_name. A blank torn_api_key/tornstats_api_key
    falls back to base_settings (useful for a single pre-multi-company
    install); google_sheet_id is mandatory per company - there is no shared
    default target sheet, since each company should write to its own Sheet.

    A company with no google_sheet_id, or one that exactly duplicates an
    already-queued (torn_api_key, google_sheet_id) pair, is reported back as
    a failed SnapshotResult with an explanatory message rather than being
    silently dropped from the run.
    """
    base = base_settings or Settings.load()
    results = []
    seen = set()
    for comp in companies:
        name = comp.get("name") or "Unnamed"
        sheet_id = (comp.get("google_sheet_id") or "").strip()
        if not sheet_id:
            results.append((name, SnapshotResult(False, "No Google Sheet ID configured for this company.")))
            continue
        torn_key = (comp.get("torn_api_key") or base.torn_api_key or "").strip()
        if not torn_key:
            results.append((name, SnapshotResult(False, "No Torn API key configured for this company.")))
            continue
        dedupe_key = (torn_key, sheet_id)
        if dedupe_key in seen:
            results.append((name, SnapshotResult(
                False, "Skipped: duplicates another configured company's Torn key + Sheet ID."
            )))
            continue
        seen.add(dedupe_key)

        s = Settings.load()  # fresh copy so signed-in Google OAuth state is always current
        s.torn_api_key = torn_key
        s.tornstats_api_key = (comp.get("tornstats_api_key") or base.tornstats_api_key or "").strip()
        s.google_sheet_id = sheet_id
        s.google_sheet_name = comp.get("google_sheet_name") or ""
        results.append((name, Collector(settings=s).run_snapshot()))
    return results


# The three append-only history tabs that get newest-snapshot-first ordering.
# Employees is deliberately excluded - it's overwritten wholesale each
# snapshot (current roster only), so there's no "order" to fix there.
HISTORY_TABS = ["Company_History", "Stock_History", "Director_Efficiency"]


def resort_existing_history(companies: list, base_settings: Optional[Settings] = None) -> list:
    """One-time migration: re-sort each configured company's existing
    history rows into newest-first order (matching how new snapshots are
    now written). Returns [(company_name, {tab_name: row_count_or_None}), ...]
    - row_count is None if that company's Sheet couldn't be reached at all."""
    base = base_settings or Settings.load()
    results = []
    for comp in companies:
        name = comp.get("name") or "Unnamed"
        sheet_id = (comp.get("google_sheet_id") or "").strip()
        if not sheet_id:
            results.append((name, None))
            continue
        try:
            sheets = SheetsClient(sheet_id=sheet_id, sheet_name=comp.get("google_sheet_name") or "")
        except Exception:
            results.append((name, None))
            continue
        per_tab = {}
        for tab in HISTORY_TABS:
            try:
                per_tab[tab] = sheets.sort_history_newest_first(tab)
            except Exception:
                per_tab[tab] = None
        results.append((name, per_tab))
    return results
