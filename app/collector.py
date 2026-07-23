"""
Orchestrates company data collection, v2-first (Phase 4 of the Employee
Calculator merge).

Two independent run paths, plus a convenience wrapper that runs both:

  - run_snapshot(): company profile/stock/employees + Company_History,
    Stock_History, Director_Efficiency (append-only), Employees (current
    roster, overwritten). Adds Company Health Score (rank vs. same-type
    companies) and a stockout predictor on Stock_History.
  - run_employee_efficiency(): Tornstats-projected position efficiency per
    employee (ported from the standalone Employee Calculator's
    efficiency_calc.py) + capacity/priority-constrained assignment +
    misplaced-employee flagging + wage efficiency, writing
    Employee_Effectiveness, Position_Efficiency, Employee_Turnover_Log.
  - run_everything(): both, in sequence.

Each Collector is scoped to one company dict (as stored by app/companies.py)
rather than a flat Settings object, since position_capacities/priority_order/
last_known_positions/last_rank/torn_public_api_key are all per-company.
torn_api_key/tornstats_api_key fall back to base Settings if a company
doesn't override them (useful for a single pre-multi-company install).

Note on daily_profit / weekly_profit: Torn's API has no direct "profit"
selection, so both are derived (see app/profit_calc.py):
  daily_profit  = daily_income - (daily_stockcost + advertising_budget + total_wage)
  weekly_profit = weekly_income - (advertising_budget + total_wage) * 7
These are approximations - they don't account for one-off costs (upgrade
purchases, etc.) that Torn doesn't expose, so treat them as directional
numbers rather than an exact P&L figure.

Note on avg_daily_profit_7day: rolling average of daily_profit across all
snapshots taken within the current Torn week (Sunday 18:00 UTC -> the
following Sunday 18:00 UTC). It updates with every snapshot during the
week rather than only being computed once the week is over.

Note on the same-24h-period check (_is_same_24h_period): a Snapshot only
appends a new history row if it falls in a different fixed 18:00 UTC ->
18:00 UTC period than the last one - not a rolling 24h window from the
last snapshot's actual timestamp. See that function's docstring for the
known tradeoff this implies.

Note on Company Health Score: rank of this company's weekly income among
every other company of the same type (v2/company/{type_id}/companies,
paginated 100 at a time). Uses the company's Public API key if configured,
falling back to the Limited-Access key otherwise - Rankings is the only
call that ever uses the Public key.

Note on stockout predictor: days_until_stockout = in_stock / sold_amount.
Torn's sold_amount is already a daily figure, so no historical trend is
needed for this estimate.
"""

from __future__ import annotations

import datetime
import time
from dataclasses import dataclass
from typing import Optional

from .config import Settings
from .efficiency_calc import (
    EMPLOYEE_HEADERS, assign_positions, build_position_efficiency_rows, compute_employee_rows,
    find_company_type_block,
)
from .profit_calc import compute_avg_daily_income_7day, compute_avg_daily_profit_7day, compute_row_profit_fields
from .sheets_client import SheetsClient
from .torn_api import TornAPI, TornAPIError
from .tornstats_api import TornStatsAPI, TornStatsAPIError

COMPANY_HISTORY_HEADERS = [
    "timestamp", "date", "name", "rating", "employees_hired", "employees_capacity",
    "daily_income", "daily_profit", "daily_customers", "weekly_income", "weekly_profit",
    "weekly_customers", "days_old",
    "company_funds", "popularity", "efficiency", "environment", "trains_available",
    "advertising_budget", "upgrade_staffroom_size",
    "upgrade_storage_size", "upgrade_storage_space", "total_wage",
    "avg_employee_effectiveness", "daily_stockcost",
    "avg_daily_profit_7day", "avg_daily_income_7day",
    "rank_by_income", "rank_total_in_type", "rank_percentile", "rank_trend",
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
    "delta_sold_worth", "created", "days_until_stockout", "stockout_soon",
]

DIRECTOR_EFFICIENCY_HEADERS = ["timestamp", "date", "position", "efficiency"]

EMPLOYEE_EFFECTIVENESS_HEADERS = EMPLOYEE_HEADERS + [
    "misplaced_flag", "wage_efficiency", "wage_efficiency_flag",
]

EMPLOYEE_TURNOVER_LOG_HEADERS = ["timestamp", "date", "tId", "name", "event", "position"]

# Torn's own per-employee effectiveness breakdown keys (this is real, accurate
# per-employee data straight from the company API - no guessing involved).
EFFECTIVENESS_KEYS = [
    "working_stats", "settled_in", "director_education", "addiction",
    "inactivity", "management", "book", "merits", "total",
]

STOCKOUT_SOON_DAYS = 3


def is_employee_misplaced(row: dict) -> bool:
    current_position = str(row.get("current_position") or "").strip()
    assigned_position = str(row.get("assigned_position") or "").strip()
    return bool(
        current_position
        and assigned_position
        and current_position != assigned_position
    )


def _ts_to_date(ts: int) -> str:
    try:
        return datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return ""


def _get_24h_period_start(ts: int) -> int:
    """Start of the fixed 24-hour period (18:00 UTC to 18:00 UTC next day)
    containing ts, as a UTC timestamp."""
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    seconds_today = dt.hour * 3600 + dt.minute * 60 + dt.second
    period_start_secs = 18 * 3600  # 6pm UTC
    if seconds_today < period_start_secs:
        period_ts = ts - seconds_today - (24 * 3600 - period_start_secs)
    else:
        period_ts = ts - seconds_today + period_start_secs
    return period_ts


def _is_same_24h_period(current_ts: int, last_ts: int) -> bool:
    """
    True if current_ts and last_ts fall in the same fixed 18:00 UTC -> 18:00
    UTC period.

    This is a deliberate, explicit design choice: hard-anchor the "same
    period" check to Torn's 18:00 UTC day boundary (matching the Torn week
    boundary used by profit_calc.torn_week_window), rather than a rolling
    window measured from the actual previous snapshot's timestamp. The
    tradeoff, and it's a real one: two snapshots only a few hours apart
    that happen to straddle 18:00 UTC will be classified as "different
    periods" and both get appended, exactly like a real live-caught case at
    the old 14:00 UTC boundary (two Company_History rows 13.3 hours apart,
    split purely because one landed just before 14:00 UTC and the other
    just after). If that duplicate-row edge case starts showing up in
    practice, a rolling-window check (any two snapshots < 24h apart are
    "the same period", regardless of wall-clock time) is the fix - but
    per explicit instruction this app is using the fixed 18:00 UTC
    boundary instead, so that "same period" always lines up with Torn's
    actual day boundary rather than with whenever a snapshot happened to
    run last.
    """
    return _get_24h_period_start(current_ts) == _get_24h_period_start(last_ts)


@dataclass
class SnapshotResult:
    ok: bool
    message: str
    company_name: str = ""
    employee_count: int = 0
    stock_count: int = 0
    sheet_url: str = ""
    is_update: bool = False  # True if we updated existing snapshot, False if we appended new one


@dataclass
class EmployeeEfficiencyResult:
    ok: bool
    message: str
    company_name: str = ""
    employee_count: int = 0
    misplaced_count: int = 0
    sheet_url: str = ""
    # "" when Tornstats position projections were matched to this company
    # via the authoritative company-type-id check; otherwise a short
    # human-readable warning that a fallback match was used instead (or
    # that no match was found at all) - see efficiency_calc.compute_employee_rows.
    verification_note: str = ""


@dataclass
class EverythingResult:
    snapshot: SnapshotResult
    employee_efficiency: EmployeeEfficiencyResult

    @property
    def ok(self) -> bool:
        return self.snapshot.ok and self.employee_efficiency.ok

    @property
    def message(self) -> str:
        return f"Snapshot: {self.snapshot.message} | Employee Efficiency: {self.employee_efficiency.message}"


class Collector:
    """Scoped to one company dict, as stored/returned by app/companies.py's
    load_companies()/save_companies(). torn_api_key/tornstats_api_key fall
    back to base_settings if the company doesn't override them.

    Mutates self.company in place when it resolves a new Google Sheet ID
    (auto-create) or a new Company Health Score rank - callers that loop
    over several companies are responsible for calling
    app.companies.save_companies(companies) once after the loop, the same
    pattern used by the module-level run_*_for_companies() helpers below.
    """

    def __init__(self, company: dict, base_settings: Optional[Settings] = None):
        self.company = company
        self.base_settings = base_settings or Settings.load()

    @property
    def name(self) -> str:
        return self.company.get("name") or "Unnamed"

    def _torn_key(self) -> str:
        return (self.company.get("torn_api_key") or self.base_settings.torn_api_key or "").strip()

    def _public_key(self) -> str:
        """Public API key for Rankings only - falls back to the
        Limited-Access key if no Public key is configured for this company."""
        return (self.company.get("torn_public_api_key") or "").strip() or self._torn_key()

    def _tornstats_key(self) -> str:
        return (self.company.get("tornstats_api_key") or self.base_settings.tornstats_api_key or "").strip()

    def _sheets(self) -> SheetsClient:
        sheet_id = (self.company.get("google_sheet_id") or "").strip()
        sheet_name = self.company.get("google_sheet_name") or self.name
        sheets, resolved_id, created = SheetsClient.get_or_create(sheet_id, self.name, sheet_name)
        if created:
            self.company["google_sheet_id"] = resolved_id
            if not self.company.get("google_sheet_name"):
                self.company["google_sheet_name"] = self.name
        return sheets

    def _compute_health_score(self, profile: dict, own_weekly_income: float):
        """
        Rank of this company's weekly income against every other company of
        the same type (v2/company/{type_id}/companies, paginated 100 at a
        time). Returns (rank, total_in_type, percentile, trend) where trend
        is "up"/"down"/"same"/"" (empty the first time, since there's no
        prior last_rank to compare against yet).

        Non-fatal: any failure (bad Public key, network error, own company
        not found in the listing, etc.) just returns all-blank so the rest
        of the snapshot still gets written. Persists the new rank onto
        self.company["last_rank"] on success.
        """
        company_type = (profile.get("type") or {}).get("id")
        own_id = profile.get("id")
        if not company_type or own_id is None:
            return None, None, None, ""
        try:
            torn_public = TornAPI(api_key=self._public_key())
            all_companies = []
            offset = 0
            limit = 100
            while True:
                resp = torn_public.get_company_listings(company_type, offset=offset, limit=limit)
                batch = resp.get("companies", []) or []
                all_companies.extend(batch)
                total = (resp.get("_metadata") or {}).get("total", len(all_companies))
                offset += limit
                if offset >= total or not batch:
                    break

            ranked = sorted(
                all_companies,
                key=lambda c: (c.get("income") or {}).get("weekly", 0) or 0,
                reverse=True,
            )
            total_n = len(ranked)
            rank = next((i + 1 for i, c in enumerate(ranked) if c.get("id") == own_id), None)
            if rank is None or not total_n:
                return None, total_n or None, None, ""

            percentile = round((total_n - rank + 1) / total_n * 100, 1)

            last_rank = self.company.get("last_rank")
            if last_rank is None:
                trend = ""
            elif rank < last_rank:
                trend = "up"
            elif rank > last_rank:
                trend = "down"
            else:
                trend = "same"

            self.company["last_rank"] = rank
            return rank, total_n, percentile, trend
        except Exception:
            return None, None, None, ""

    def run_snapshot(self) -> SnapshotResult:
        torn_key = self._torn_key()
        if not torn_key:
            return SnapshotResult(False, "No Torn API key configured. Add one in Settings.")
        torn = TornAPI(api_key=torn_key)

        try:
            profile = torn.get_company_profile_v2().get("profile", {}) or {}
            stock = torn.get_company_stock_v2().get("stock", []) or []
            employees = torn.get_company_employees().get("employees", []) or []
            timestamp = int(torn.get_company_timestamp_v2().get("timestamp", time.time()))
        except TornAPIError as e:
            return SnapshotResult(False, f"Torn API error: {e.message}")
        except Exception as e:
            return SnapshotResult(False, f"Could not reach Torn API: {e}")

        try:
            sheets = self._sheets()
        except Exception as e:
            return SnapshotResult(False, f"Sheets setup failed: {e}")

        upgrades = profile.get("upgrades", {}) or {}

        # ---------------------------------------------------- employees --
        total_wage = 0
        eff_totals = []
        employee_rows = []
        for emp in employees:
            eff = emp.get("effectiveness", {}) or {}
            wage = int(emp.get("wage", 0) or 0)
            total_wage += wage
            eff_totals.append(eff.get("total", 0) or 0)

            last_action = emp.get("last_action", {})
            last_action_ts = last_action.get("timestamp", "") if isinstance(last_action, dict) else last_action
            position_name = (emp.get("position") or {}).get("name", "")

            employee_rows.append({
                "tId": emp.get("id", ""),
                "name": emp.get("name", ""),
                "position": position_name,
                "wage": wage,
                "days_in_company": emp.get("days_in_company", ""),
                "last_action_ts": last_action_ts,
                "effectiveness_total": eff.get("total", 0),
                "effectiveness_working_stats": eff.get("working_stats", 0),
                "effectiveness_settled_in": eff.get("settled_in", 0),
                "effectiveness_director_education": eff.get("director_education", 0),
                "effectiveness_addiction": eff.get("addiction", 0),
                "effectiveness_inactivity": eff.get("inactivity", 0),
                "effectiveness_management": eff.get("management", 0),
                "effectiveness_book": eff.get("book", 0),
                "effectiveness_merits": eff.get("merits", 0),
            })

        avg_effectiveness = round(sum(eff_totals) / len(eff_totals), 2) if eff_totals else 0

        # -------------------------------------------------------- stock --
        previous_stock_rows = sheets.read_records("Stock_History")
        previous_by_name = {}
        for row in previous_stock_rows:
            rname = row.get("name")
            ts = int(row.get("timestamp") or 0)
            if ts >= timestamp:
                continue
            if rname not in previous_by_name or ts > int(previous_by_name[rname].get("timestamp", 0)):
                previous_by_name[rname] = row

        daily_stockcost = 0
        stock_rows = []
        for s in stock:
            name = s.get("name", "")
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

            # created = inventory change + current day sold_amount (YATA formula).
            # sold_amount is the daily variable amount (not cumulative).
            created = delta_in_stock + sold_amount

            # Stockout predictor: sold_amount is already a daily figure, so
            # in_stock / sold_amount directly estimates days of runway left.
            if sold_amount > 0:
                days_until_stockout = round(in_stock / sold_amount, 1)
                stockout_soon = days_until_stockout <= STOCKOUT_SOON_DAYS
            else:
                days_until_stockout = ""
                stockout_soon = False

            stock_rows.append({
                "timestamp": timestamp, "date": _ts_to_date(timestamp), "name": name,
                "in_stock": in_stock, "on_order": s.get("on_order", 0), "cost": cost,
                "price": s.get("price", 0), "sold_amount": sold_amount, "sold_worth": sold_worth,
                "delta_in_stock": delta_in_stock, "delta_sold_amount": delta_sold_amount,
                "delta_sold_worth": delta_sold_worth, "created": created,
                "days_until_stockout": days_until_stockout, "stockout_soon": stockout_soon,
            })

        # ------------------------------------------------------ company --
        income = profile.get("income", {}) or {}
        daily_income = float(income.get("daily", 0) or 0)
        weekly_income = float(income.get("weekly", 0) or 0)
        advertising_budget = float(profile.get("advertisement_budget", 0) or 0)

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

        rank, rank_total, rank_percentile, rank_trend = self._compute_health_score(profile, weekly_income)

        employees_block = profile.get("employees", {}) or {}
        customers_block = profile.get("customers", {}) or {}

        company_row = {
            "timestamp": timestamp, "date": _ts_to_date(timestamp),
            "name": profile.get("name", ""), "rating": profile.get("rating", ""),
            "employees_hired": employees_block.get("hired", ""),
            "employees_capacity": employees_block.get("capacity", ""),
            "daily_income": income.get("daily", ""), "daily_profit": profit_fields["daily_profit"],
            "daily_customers": customers_block.get("daily", ""),
            "weekly_income": income.get("weekly", ""), "weekly_profit": profit_fields["weekly_profit"],
            "weekly_customers": customers_block.get("weekly", ""), "days_old": profile.get("days_old", ""),
            "company_funds": profile.get("funds", ""), "popularity": profile.get("popularity", ""),
            "efficiency": profile.get("efficiency", ""), "environment": profile.get("environment", ""),
            "trains_available": profile.get("trains", ""),
            "advertising_budget": profile.get("advertisement_budget", ""),
            "upgrade_staffroom_size": upgrades.get("staff_room", ""),
            "upgrade_storage_size": upgrades.get("storage", ""),
            "upgrade_storage_space": upgrades.get("storage_capacity", ""),
            "total_wage": total_wage, "avg_employee_effectiveness": avg_effectiveness,
            "daily_stockcost": round(daily_stockcost, 2),
            "avg_daily_profit_7day": avg_daily_profit_7day, "avg_daily_income_7day": avg_daily_income_7day,
            "rank_by_income": rank if rank is not None else "",
            "rank_total_in_type": rank_total if rank_total else "",
            "rank_percentile": rank_percentile if rank_percentile is not None else "",
            "rank_trend": rank_trend,
        }

        # ----------------------------------------------- director effic. --
        # Was previously looping over every block Tornstats returns (every
        # company type in the game, ~25-30 of them) with no filtering at
        # all, so Director_Efficiency ended up with rows for Hair Salon, Law
        # Firm, etc. alongside this company's real numbers. Now matched the
        # same verified way as the per-employee lookups (company_type id
        # first, see find_company_type_block) so only this company's block
        # is ever written - and it's logged to logs/efficiency_verification.log
        # either way so a mismatch is visible instead of silent.
        type_block = profile.get("type") or {}
        director_company_type_id = type_block.get("id")
        director_company_type_name = type_block.get("name")
        director_known_positions = {e.get("position", {}).get("name") for e in employees if e.get("position")}
        director_known_positions.discard(None)

        tornstats_key = self._tornstats_key()
        director_rows = []
        if tornstats_key:
            tornstats = TornStatsAPI(api_key=tornstats_key)
            try:
                eff_data = tornstats.get_efficiency()
                block, _method = find_company_type_block(
                    eff_data, director_known_positions,
                    director_company_type_id, director_company_type_name,
                    context="director",
                )
                if block:
                    for position, value in block.items():
                        if position == "company":
                            continue
                        director_rows.append({
                            "timestamp": timestamp, "date": _ts_to_date(timestamp),
                            "position": position, "efficiency": value,
                        })
            except TornStatsAPIError:
                pass  # non-fatal - company/employee data still gets written
            except Exception:
                pass

        # -------------------------------------------------------- write --
        is_same_period = False
        if prior_company_rows:
            # Find the most recent prior snapshot by timestamp, not by row
            # position - new rows are inserted at the top of the sheet, so
            # position no longer implies recency.
            last_row = max(prior_company_rows, key=lambda r: int(r.get("timestamp") or 0))
            last_ts = int(last_row.get("timestamp") or 0)
            is_same_period = _is_same_24h_period(timestamp, last_ts)

        # Only append new rows if it's a different 18:00-UTC-to-18:00-UTC
        # period than the last snapshot. Otherwise we just re-verified the
        # current data (Employees is refreshed regardless).
        if not is_same_period:
            sheets.append_history_row("Company_History", COMPANY_HISTORY_HEADERS, company_row)
            sheets.append_history_rows("Stock_History", STOCK_HISTORY_HEADERS, stock_rows)
            if director_rows:
                sheets.append_history_rows("Director_Efficiency", DIRECTOR_EFFICIENCY_HEADERS, director_rows)

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

    def run_employee_efficiency(self) -> EmployeeEfficiencyResult:
        torn_key = self._torn_key()
        if not torn_key:
            return EmployeeEfficiencyResult(False, "No Torn API key configured. Add one in Settings.")
        tornstats_key = self._tornstats_key()
        if not tornstats_key:
            return EmployeeEfficiencyResult(False, "No Tornstats API key configured. Add one in Settings.")

        torn = TornAPI(api_key=torn_key)
        tornstats = TornStatsAPI(api_key=tornstats_key)

        try:
            employees = torn.get_company_employees().get("employees", []) or []
            timestamp = int(torn.get_company_timestamp_v2().get("timestamp", time.time()))
        except TornAPIError as e:
            return EmployeeEfficiencyResult(False, f"Torn API error: {e.message}")
        except Exception as e:
            return EmployeeEfficiencyResult(False, f"Could not reach Torn API: {e}")

        if not employees:
            return EmployeeEfficiencyResult(False, "No employees returned by the Torn API.")

        try:
            sheets = self._sheets()
        except Exception as e:
            return EmployeeEfficiencyResult(False, f"Sheets setup failed: {e}")

        # Fetched once, up front, so the Tornstats position-efficiency call
        # below can verify it's reading the right company's block (by
        # Torn's own company_type id - see efficiency_calc.find_company_type_block)
        # instead of relying only on the roster's currently-held positions,
        # and so we no longer need a second profile call later just for
        # total_capacity.
        total_capacity = None
        company_type_id = None
        company_type_name = None
        try:
            profile = torn.get_company_profile_v2().get("profile", {}) or {}
            total_capacity = (profile.get("employees") or {}).get("capacity")
            type_block = profile.get("type") or {}
            company_type_id = type_block.get("id")
            company_type_name = type_block.get("name")
        except Exception:
            pass  # non-fatal - assignment runs uncapped, and Tornstats matching
            # falls back to its older heuristic if the type id/name aren't known

        rows, position_names, verification_note = compute_employee_rows(
            employees, tornstats,
            expected_company_type_id=company_type_id,
            expected_company_type_name=company_type_name,
        )

        # Grow, never shrink, automatically - a position that stops showing
        # up in this run (e.g. the last person in it just quit) shouldn't
        # silently disappear from the sheet/GUI's column list. Positions are
        # only ever removed by an explicit, user-driven action (the Position
        # Effectiveness tab's "Configure Positions" checklist), never here.
        self.company["last_known_positions"] = sorted(
            set(self.company.get("last_known_positions") or []) | set(position_names)
        )

        capacities = self.company.get("position_capacities") or {}
        priority_order = self.company.get("position_priority_order") or []
        locked_employee_ids = {
            str(employee_id)
            for employee_id in (self.company.get("locked_employee_ids") or [])
        }
        lock_warnings = assign_positions(
            rows,
            position_names,
            capacities,
            total_capacity,
            priority_order,
            locked_employee_ids,
        )
        if lock_warnings:
            verification_note = " ".join(
                part for part in [verification_note, *lock_warnings] if part
            )

        # ------------------------------------------ misplaced + wage eff --
        misplaced_count = 0
        for row in rows:
            misplaced = is_employee_misplaced(row)
            row["misplaced_flag"] = misplaced
            if misplaced:
                misplaced_count += 1

            wage = row.get("wage") or 0
            eff_total = row.get("effectiveness_total") or 0
            row["wage_efficiency"] = round(wage / eff_total, 2) if eff_total else ""

        wage_effs = [r["wage_efficiency"] for r in rows if r["wage_efficiency"] != ""]
        avg_wage_eff = (sum(wage_effs) / len(wage_effs)) if wage_effs else 0
        for row in rows:
            we = row["wage_efficiency"]
            # Flag anyone paid 50%+ worse (higher wage-per-effectiveness-point)
            # than the roster average.
            row["wage_efficiency_flag"] = bool(we != "" and avg_wage_eff and we >= avg_wage_eff * 1.5)

        # --------------------------------------------------- turnover log --
        # Employee_Effectiveness is overwritten (current roster only) each
        # run, so the *previous* roster has to be read before we overwrite
        # it, and diffed by tId against the new one to log joins/leaves.
        previous_roster = sheets.read_records("Employee_Effectiveness")
        previous_ids = {str(r.get("tId")) for r in previous_roster if r.get("tId") not in (None, "")}
        current_ids = {str(r["tId"]) for r in rows if r.get("tId") not in (None, "")}
        current_by_id = {str(r["tId"]): r for r in rows}
        previous_by_id = {str(r.get("tId")): r for r in previous_roster}

        turnover_rows = []
        for tid in current_ids - previous_ids:
            row = current_by_id[tid]
            turnover_rows.append({
                "timestamp": timestamp, "date": _ts_to_date(timestamp), "tId": tid,
                "name": row.get("name", ""), "event": "joined", "position": row.get("current_position", ""),
            })
        for tid in previous_ids - current_ids:
            row = previous_by_id[tid]
            turnover_rows.append({
                "timestamp": timestamp, "date": _ts_to_date(timestamp), "tId": tid,
                "name": row.get("name", ""), "event": "left", "position": row.get("current_position", ""),
            })

        # ------------------------------------------------------- write --
        # rows already come from efficiency_calc as flat dicts keyed by
        # EMPLOYEE_HEADERS names (plus misplaced_flag/wage_efficiency/
        # wage_efficiency_flag added above, plus an internal "projected"
        # dict that overwrite_current_state simply ignores since it's not
        # in EMPLOYEE_EFFECTIVENESS_HEADERS).
        sheets.overwrite_current_state("Employee_Effectiveness", EMPLOYEE_EFFECTIVENESS_HEADERS, rows)

        pos_headers, pos_rows_list = build_position_efficiency_rows(rows, position_names)
        pos_rows = [dict(zip(pos_headers, r)) for r in pos_rows_list]
        sheets.overwrite_current_state("Position_Efficiency", pos_headers, pos_rows)

        if turnover_rows:
            sheets.append_history_rows("Employee_Turnover_Log", EMPLOYEE_TURNOVER_LOG_HEADERS, turnover_rows)

        return EmployeeEfficiencyResult(
            ok=True,
            message="Employee efficiency run complete.",
            company_name=self.name,
            employee_count=len(rows),
            misplaced_count=misplaced_count,
            sheet_url=sheets.url,
            verification_note=verification_note,
        )

    def run_everything(self) -> EverythingResult:
        snapshot = self.run_snapshot()
        employee_efficiency = self.run_employee_efficiency()
        return EverythingResult(snapshot=snapshot, employee_efficiency=employee_efficiency)


def persist_companies(companies: list) -> None:
    """Persist any in-place mutations (new google_sheet_id from auto-create,
    new last_rank from the Health Score) back to companies.json/DPAPI store.

    Deliberately NOT called automatically by the run_*_for_companies()
    helpers below - only call this with a `companies` list that actually
    came from app.companies.load_companies() (and was passed straight
    through, mutated in place). Calling it with an ad-hoc/throwaway
    companies list (e.g. in a test, or a one-off dry run) would silently
    overwrite the real saved company data with that throwaway data - this
    is exactly the mistake that happened during Phase 4 development, so
    persistence is opt-in and the caller's responsibility from here on."""
    from .companies import save_companies
    save_companies(companies)


def run_company_snapshots(companies: list, base_settings: Optional[Settings] = None) -> list:
    """
    Run one snapshot per company dict and return [(name, SnapshotResult), ...].

    This is the single implementation of "run N companies" shared by the GUI
    (Settings > Companies) and headless `python main.py --snapshot`, so the
    two modes can't drift out of sync with each other the way they used to.

    Each company dict may provide: name, torn_api_key, torn_public_api_key,
    tornstats_api_key, google_sheet_id, google_sheet_name. A blank
    torn_api_key/tornstats_api_key falls back to base_settings. A blank (or
    stale/deleted) google_sheet_id auto-creates a new Sheet named exactly
    the company's name, and the resulting ID is persisted back into
    companies.json - there is no shared default target sheet, since each
    company should write to its own Sheet.

    A company with no Torn API key configured (of its own or via
    base_settings), or one that exactly duplicates an already-queued
    (torn_api_key, google_sheet_id) pair, is reported back as a failed
    SnapshotResult with an explanatory message rather than being silently
    dropped from the run.

    Does NOT persist any in-place mutations (new google_sheet_id, new
    last_rank) back to disk - call app.collector.persist_companies(companies)
    afterward, but ONLY if `companies` came from
    app.companies.load_companies(). Passing an ad-hoc/throwaway companies
    list into persist_companies() would silently overwrite the real saved
    data with that throwaway data.
    """
    base = base_settings or Settings.load()
    results = []
    seen = set()
    for comp in companies:
        name = comp.get("name") or "Unnamed"
        torn_key = (comp.get("torn_api_key") or base.torn_api_key or "").strip()
        if not torn_key:
            results.append((name, SnapshotResult(False, "No Torn API key configured for this company.")))
            continue

        sheet_id = (comp.get("google_sheet_id") or "").strip()
        # Only dedupe when there's an explicit Sheet ID to collide on - a
        # blank ID always auto-creates its own fresh Sheet, so there's
        # nothing to dedupe against.
        if sheet_id:
            dedupe_key = (torn_key, sheet_id)
            if dedupe_key in seen:
                results.append((name, SnapshotResult(
                    False, "Skipped: duplicates another configured company's Torn key + Sheet ID."
                )))
                continue
            seen.add(dedupe_key)

        results.append((name, Collector(comp, base_settings=base).run_snapshot()))

    return results


def run_employee_efficiency_for_companies(companies: list, base_settings: Optional[Settings] = None) -> list:
    """Run one employee-efficiency pass per company dict and return
    [(name, EmployeeEfficiencyResult), ...]. Mirrors run_company_snapshots'
    shape. Does NOT persist - call app.collector.persist_companies(companies)
    afterward if `companies` came from app.companies.load_companies()."""
    base = base_settings or Settings.load()
    results = []
    for comp in companies:
        name = comp.get("name") or "Unnamed"
        results.append((name, Collector(comp, base_settings=base).run_employee_efficiency()))
    return results


def run_everything_for_companies(companies: list, base_settings: Optional[Settings] = None) -> list:
    """Run both a snapshot and an employee-efficiency pass per company dict
    and return [(name, EverythingResult), ...]. Does NOT persist - call
    app.collector.persist_companies(companies) afterward if `companies`
    came from app.companies.load_companies()."""
    base = base_settings or Settings.load()
    results = []
    for comp in companies:
        name = comp.get("name") or "Unnamed"
        results.append((name, Collector(comp, base_settings=base).run_everything()))
    return results


# The append-only history tabs that get newest-snapshot-first ordering.
# Employees and Employee_Effectiveness/Position_Efficiency are deliberately
# excluded - they're overwritten wholesale each run (current roster only),
# so there's no "order" to fix there.
HISTORY_TABS = ["Company_History", "Stock_History", "Director_Efficiency", "Employee_Turnover_Log"]


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
