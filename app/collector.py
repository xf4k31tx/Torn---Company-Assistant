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
    Employee_Effectiveness, Position_Efficiency, Total_Effectiveness_Projections,
    Employee_Turnover_Log.
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

Note on monthly_income/monthly_profit: rolling 30-day TRAILING TOTAL (sum,
not average) of daily_income/daily_profit across every snapshot in the 30
days immediately preceding and including the current one - see
app/profit_calc.py's compute_rolling_30day_sum. Unlike
avg_daily_profit_7day above, this is NOT anchored to any fixed calendar
week/month boundary; it continuously updates with every snapshot, mirroring
weekly_income/weekly_profit's "total over a period" semantics at 30-day
granularity.

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
    EMPLOYEE_HEADERS, assign_positions, build_position_efficiency_rows,
    build_total_effectiveness_projection_rows, compute_employee_rows,
    find_company_type_block,
)
from .profit_calc import (
    compute_avg_daily_income_7day, compute_avg_daily_profit_7day,
    compute_monthly_income, compute_monthly_profit, compute_row_profit_fields,
)
from .income_tracking import (
    HISTORY_PERIODS, INCOME_HISTORY_HEADERS, SECONDS_PER_DAY,
    STAR_INCOME_SUMMARY_HEADERS, merge_income_observations,
    own_company_metrics, reporting_period_start, rolling_company_totals,
    summarize_star_ranges,
)
from .ranking_calc import (
    compute_star_band_metrics, count_10_star_companies, find_rank,
    is_weekly_star_reset_snapshot, rank_companies_by_weekly_income,
)
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
    "monthly_income", "monthly_profit",
    "rank_by_income", "rank_total_in_type", "rank_percentile", "rank_trend",
    "star_10_count", "income_to_reach_10_star", "income_buffer_before_9_star",
    "income_to_reach_next_star", "required_weekly_income_to_star_up",
    "income_to_drop_to_previous_star",
    "rolling_7day_income", "rolling_7day_coverage", "rolling_7day_change",
    "observed_range_position_percent", "observed_drop_buffer",
    "observed_next_star_gap",
]

COMPANY_RANKINGS_HEADERS = [
    "rank", "id", "name", "rating", "daily_income", "weekly_income", "is_own_company",
]

STAR_INCOME_SUMMARY_HISTORY_HEADERS = ["week_start"] + STAR_INCOME_SUMMARY_HEADERS

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

# Torn's own per-employee effectiveness breakdown keys
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


def extract_company_type_info(profile: dict) -> tuple[Optional[int], Optional[str]]:
    """Extracts (company_type_id, company_type_name) from profile['type']."""
    type_block = profile.get("type") or profile.get("company_type") or {}
    if isinstance(type_block, dict):
        type_id = type_block.get("id")
        type_name = type_block.get("name")
        try:
            type_id_int = int(type_id) if type_id is not None else None
        except (ValueError, TypeError):
            type_id_int = None
        return (type_id_int, str(type_name) if type_name else None)
    elif isinstance(type_block, (int, str)):
        try:
            return (int(type_block), None)
        except (ValueError, TypeError):
            pass
    return None, None


def extract_company_id(profile: dict) -> Optional[int]:
    """Extracts company ID from profile['id']."""
    cid = profile.get("id") or profile.get("company_id")
    if cid is not None:
        try:
            return int(cid)
        except (ValueError, TypeError):
            # pyrefly: ignore [bad-return]
            return str(cid)
    return None


def _ts_to_date(ts: int) -> str:
    try:
        return datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return ""


def _safe_int_ts(val) -> int:
    try:
        return int(float(str(val).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def _get_24h_period_start(ts) -> int:
    """Start of the fixed 24-hour period (18:00 UTC to 18:00 UTC next day)
    containing ts, returned as an exact integer UTC Unix timestamp."""
    ts_int = _safe_int_ts(ts)
    if not ts_int:
        return 0
    dt = datetime.datetime.fromtimestamp(ts_int, tz=datetime.timezone.utc)
    if dt.hour < 18:
        period_dt = (dt - datetime.timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)
    else:
        period_dt = dt.replace(hour=18, minute=0, second=0, microsecond=0)
    return int(period_dt.timestamp())


def _is_same_24h_period(current_ts, last_ts) -> bool:
    """
    True if current_ts and last_ts fall in the same fixed 18:00 UTC -> 18:00
    UTC period.
    """
    start_cur = _get_24h_period_start(current_ts)
    start_last = _get_24h_period_start(last_ts)
    return bool(start_cur and start_last and start_cur == start_last)


@dataclass
class SnapshotResult:
    ok: bool
    message: str
    company_name: str = ""
    employee_count: int = 0
    stock_count: int = 0
    sheet_url: str = ""
    is_update: bool = False


@dataclass
class HealthScoreResult:
    rank: Optional[int] = None
    total_in_type: Optional[int] = None
    percentile: Optional[float] = None
    trend: str = ""
    ranked_companies: list = None  # type: ignore[assignment]
    star_10_count: Optional[int] = None
    income_to_reach_10_star: Optional[float] = None
    income_buffer_before_9_star: Optional[float] = None
    income_to_reach_next_star: Optional[float] = None
    required_weekly_income_to_star_up: Optional[float] = None
    income_to_drop_to_previous_star: Optional[float] = None
    current_star_level: Optional[int] = None
    next_star_level: Optional[int] = None
    previous_star_level: Optional[int] = None

    def __post_init__(self):
        if self.ranked_companies is None:
            # pyrefly: ignore [bad-assignment]
            self.ranked_companies = []


@dataclass
class EmployeeEfficiencyResult:
    ok: bool
    message: str
    company_name: str = ""
    employee_count: int = 0
    misplaced_count: int = 0
    sheet_url: str = ""
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
    def __init__(self, company: dict, base_settings: Optional[Settings] = None):
        self.company = company
        self.base_settings = base_settings or Settings.load()

    @property
    def name(self) -> str:
        return self.company.get("name") or "Unnamed"

    def _torn_key(self) -> str:
        return (self.company.get("torn_api_key") or self.base_settings.torn_api_key or "").strip()

    def _public_key(self) -> str:
        pub_key = (self.company.get("torn_public_api_key") or "").strip()
        if pub_key:
            return pub_key
        return self._torn_key()

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

    def _compute_health_score(self, profile: dict, own_weekly_income: float, timestamp: int) -> HealthScoreResult:
        company_type, _ = extract_company_type_info(profile)
        own_id = extract_company_id(profile)
        if not company_type or not own_id:
            return HealthScoreResult()

        pub_key = (self.company.get("torn_public_api_key") or "").strip()
        primary_key = pub_key if pub_key else self._torn_key()

        try:
            torn_public = TornAPI(api_key=primary_key)
            all_companies = torn_public.get_all_company_listings(company_type)
        except Exception as err:
            if pub_key and pub_key != self._torn_key():
                try:
                    torn_public = TornAPI(api_key=self._torn_key())
                    all_companies = torn_public.get_all_company_listings(company_type)
                except Exception as fallback_err:
                    import logging
                    logging.warning(
                        f"Health score computation failed for {self.name}: {fallback_err} "
                        f"(company_type={company_type!r}, own_id={own_id!r}, "
                        f"used_public_key={bool(pub_key)}, fallback_to_torn_key=True)"
                    )
                    return HealthScoreResult()
            else:
                import logging
                logging.warning(
                    f"Health score computation failed for {self.name}: {err} "
                    f"(company_type={company_type!r}, own_id={own_id!r}, "
                    f"used_public_key={bool(pub_key)}, fallback_to_torn_key=False)"
                )
                return HealthScoreResult()

        try:
            ranked = rank_companies_by_weekly_income(all_companies)
            total_n = len(ranked)
            rank = find_rank(ranked, own_id)
            if rank is None or not total_n:
                return HealthScoreResult(total_in_type=total_n or None, ranked_companies=ranked)

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

            star_10_count = count_10_star_companies(ranked)
            self.company["star_10_count"] = star_10_count

            cohort = compute_star_band_metrics(
                ranked, own_id, own_weekly_income, profile.get("rating")
            )

            return HealthScoreResult(
                rank=rank, total_in_type=total_n, percentile=percentile, trend=trend,
                ranked_companies=ranked, star_10_count=star_10_count,
                income_to_reach_10_star=cohort["income_to_reach_next_star"],
                income_buffer_before_9_star=cohort["income_to_drop_to_previous_star"],
                income_to_reach_next_star=cohort["income_to_reach_next_star"],
                required_weekly_income_to_star_up=cohort[
                    "required_weekly_income_to_star_up"
                ],
                income_to_drop_to_previous_star=cohort[
                    "income_to_drop_to_previous_star"
                ],
                current_star_level=cohort["current_star_level"],
                next_star_level=cohort["next_star_level"],
                previous_star_level=cohort["previous_star_level"],
            )
        except Exception as exc:
            import logging
            logging.warning(f"Health score calculation error for {self.name}: {exc}")
            return HealthScoreResult()

    def _update_income_tracking(
        self,
        sheets: SheetsClient,
        ranked_companies: list[dict],
        own_id,
        timestamp: int,
    ) -> dict:
        prior = sheets.read_records("Company_Income_History")
        history = merge_income_observations(
            prior, ranked_companies, timestamp, own_id=own_id
        )
        sheets.overwrite_current_state(
            "Company_Income_History", INCOME_HISTORY_HEADERS, history
        )

        period = reporting_period_start(timestamp)
        totals = rolling_company_totals(history, period)
        summaries = summarize_star_ranges(totals, timestamp)
        sheets.overwrite_current_state(
            "Star_Income_Summary", STAR_INCOME_SUMMARY_HEADERS, summaries
        )

        if is_weekly_star_reset_snapshot(timestamp):
            completed_period = period - SECONDS_PER_DAY
            completed_totals = rolling_company_totals(history, completed_period)
            live_by_id = {
                str(company.get("id")): company for company in ranked_companies
            }
            for company_id, total in completed_totals.items():
                live = live_by_id.get(str(company_id))
                if live:
                    total["rating"] = float(live.get("rating") or 0)
                    total["is_own_company"] = str(live.get("id")) == str(own_id)
            completed = summarize_star_ranges(completed_totals, timestamp)
            prior_weekly = sheets.read_records("Star_Income_Summary_History")
            weekly_by_key = {}
            cutoff = period - HISTORY_PERIODS * SECONDS_PER_DAY
            for row in prior_weekly:
                week_start = _safe_int_ts(row.get("week_start"))
                stars = row.get("stars")
                if week_start >= cutoff and stars not in (None, ""):
                    weekly_by_key[(week_start, str(stars))] = dict(row)
            for row in completed:
                weekly_row = {"week_start": period, **row}
                weekly_by_key[(period, str(row["stars"]))] = weekly_row
            weekly_rows = sorted(
                weekly_by_key.values(),
                key=lambda row: (
                    -_safe_int_ts(row.get("week_start")),
                    -_safe_int_ts(row.get("stars")),
                ),
            )
            sheets.overwrite_current_state(
                "Star_Income_Summary_History",
                STAR_INCOME_SUMMARY_HISTORY_HEADERS,
                weekly_rows,
            )

        return own_company_metrics(totals, summaries)

    def run_daily_income(self) -> SnapshotResult:
        torn_key = self._torn_key()
        if not torn_key:
            return SnapshotResult(False, "No Torn API key configured. Add one in Settings.")
        torn = TornAPI(api_key=torn_key)
        try:
            profile = torn.get_company_profile_v2().get("profile", {}) or {}
            timestamp = int(
                torn.get_company_timestamp_v2().get("timestamp", time.time())
            )
        except TornAPIError as exc:
            return SnapshotResult(False, f"Torn API error: {exc.message}")
        except Exception as exc:
            return SnapshotResult(False, f"Could not reach Torn API: {exc}")

        try:
            sheets = self._sheets()
        except Exception as exc:
            return SnapshotResult(False, f"Sheets setup failed: {exc}")

        weekly_income = float(
            ((profile.get("income") or {}).get("weekly", 0)) or 0
        )
        health = self._compute_health_score(profile, weekly_income, timestamp)
        own_id = extract_company_id(profile)
        self._update_income_tracking(
            sheets, health.ranked_companies, own_id, timestamp
        )
        ranking_rows = [
            {
                "rank": index + 1,
                "id": company.get("id", ""),
                "name": company.get("name", ""),
                "rating": company.get("rating", ""),
                "daily_income": (company.get("income") or {}).get("daily", ""),
                "weekly_income": (company.get("income") or {}).get("weekly", ""),
                "is_own_company": str(company.get("id")) == str(own_id),
            }
            for index, company in enumerate(health.ranked_companies)
        ]
        sheets.overwrite_current_state(
            "Company_Rankings", COMPANY_RANKINGS_HEADERS, ranking_rows
        )
        return SnapshotResult(
            True,
            "Daily income collection complete.",
            company_name=profile.get("name", self.name),
            sheet_url=sheets.url,
        )

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
            ts = _safe_int_ts(row.get("timestamp"))
            if ts >= timestamp:
                continue
            if rname not in previous_by_name or ts > _safe_int_ts(previous_by_name[rname].get("timestamp")):
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

            created = delta_in_stock + sold_amount

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
        monthly_income = compute_monthly_income(
            prior_rows=prior_company_rows,
            current_timestamp=timestamp,
            current_daily_income=daily_income,
        )
        monthly_profit = compute_monthly_profit(
            prior_rows=prior_company_rows,
            current_timestamp=timestamp,
            current_daily_profit=profit_fields["daily_profit"],
        )

        health = self._compute_health_score(profile, weekly_income, timestamp)
        own_id = extract_company_id(profile)
        income_metrics = self._update_income_tracking(
            sheets, health.ranked_companies, own_id, timestamp
        )

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
            "monthly_income": monthly_income, "monthly_profit": monthly_profit,
            "rank_by_income": health.rank if health.rank is not None else "",
            "rank_total_in_type": health.total_in_type if health.total_in_type else "",
            "rank_percentile": health.percentile if health.percentile is not None else "",
            "rank_trend": health.trend,
            "star_10_count": health.star_10_count if health.star_10_count is not None else "",
            "income_to_reach_10_star": (
                health.income_to_reach_10_star if health.income_to_reach_10_star is not None else ""
            ),
            "income_buffer_before_9_star": (
                health.income_buffer_before_9_star if health.income_buffer_before_9_star is not None else ""
            ),
            "income_to_reach_next_star": (
                health.income_to_reach_next_star
                if health.income_to_reach_next_star is not None else ""
            ),
            "required_weekly_income_to_star_up": (
                health.required_weekly_income_to_star_up
                if health.required_weekly_income_to_star_up is not None else ""
            ),
            "income_to_drop_to_previous_star": (
                health.income_to_drop_to_previous_star
                if health.income_to_drop_to_previous_star is not None else ""
            ),
            "rolling_7day_income": (
                income_metrics.get("rolling_7day_income")
                if income_metrics.get("rolling_7day_income") is not None else ""
            ),
            "rolling_7day_coverage": (
                f"{income_metrics.get('rolling_7day_coverage', 0)}/7"
            ),
            "rolling_7day_change": (
                income_metrics.get("rolling_7day_change")
                if income_metrics.get("rolling_7day_change") is not None else ""
            ),
            "observed_range_position_percent": (
                income_metrics.get("observed_range_position_percent")
                if income_metrics.get("observed_range_position_percent") is not None else ""
            ),
            "observed_drop_buffer": (
                income_metrics.get("observed_drop_buffer")
                if income_metrics.get("observed_drop_buffer") is not None else ""
            ),
            "observed_next_star_gap": (
                income_metrics.get("observed_next_star_gap")
                if income_metrics.get("observed_next_star_gap") is not None else ""
            ),
        }

        # ----------------------------------------------- director effic. --
        director_company_type_id, director_company_type_name = extract_company_type_info(profile)
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
                pass
            except Exception:
                pass

        # -------------------------------------------------------- write --
        is_same_period = False
        if prior_company_rows:
            last_row = max(prior_company_rows, key=lambda r: _safe_int_ts(r.get("timestamp")))
            last_ts = _safe_int_ts(last_row.get("timestamp"))
            if last_ts > 0:
                is_same_period = _is_same_24h_period(timestamp, last_ts)

        if not is_same_period:
            sheets.append_history_row("Company_History", COMPANY_HISTORY_HEADERS, company_row)
            sheets.append_history_rows("Stock_History", STOCK_HISTORY_HEADERS, stock_rows)
            if director_rows:
                sheets.append_history_rows("Director_Efficiency", DIRECTOR_EFFICIENCY_HEADERS, director_rows)

        sheets.overwrite_current_state("Employees", EMPLOYEES_HEADERS, employee_rows)

        ranking_rows = [
            {
                "rank": index + 1,
                "id": c.get("id", ""),
                "name": c.get("name", ""),
                "rating": c.get("rating", ""),
                "daily_income": (c.get("income") or {}).get("daily", ""),
                "weekly_income": (c.get("income") or {}).get("weekly", ""),
                "is_own_company": str(c.get("id")) == str(own_id),
            }
            for index, c in enumerate(health.ranked_companies)
        ]
        sheets.overwrite_current_state("Company_Rankings", COMPANY_RANKINGS_HEADERS, ranking_rows)

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

        total_capacity = None
        company_type_id = None
        company_type_name = None
        try:
            profile = torn.get_company_profile_v2().get("profile", {}) or {}
            total_capacity = (profile.get("employees") or {}).get("capacity")
            company_type_id, company_type_name = extract_company_type_info(profile)
        except Exception:
            pass

        rows, position_names, verification_note = compute_employee_rows(
            employees, tornstats,
            expected_company_type_id=company_type_id,
            expected_company_type_name=company_type_name,
        )

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
            row["wage_efficiency_flag"] = bool(we != "" and avg_wage_eff and we >= avg_wage_eff * 1.5)

        # --------------------------------------------------- turnover log --
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
        sheets.overwrite_current_state("Employee_Effectiveness", EMPLOYEE_EFFECTIVENESS_HEADERS, rows)

        pos_headers, pos_rows_list = build_position_efficiency_rows(rows, position_names)
        pos_rows = [dict(zip(pos_headers, r)) for r in pos_rows_list]
        sheets.overwrite_current_state("Position_Efficiency", pos_headers, pos_rows)

        total_headers, total_rows_list = build_total_effectiveness_projection_rows(rows, position_names)
        total_rows = [dict(zip(total_headers, r)) for r in total_rows_list]
        sheets.overwrite_current_state("Total_Effectiveness_Projections", total_headers, total_rows)

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
    from .companies import save_companies
    save_companies(companies)


def run_company_snapshots(companies: list, base_settings: Optional[Settings] = None) -> list:
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


def run_daily_income_for_companies(
    companies: list,
    base_settings: Optional[Settings] = None,
) -> list:
    base = base_settings or Settings.load()
    results = []
    for comp in companies:
        name = comp.get("name") or "Unnamed"
        results.append((name, Collector(comp, base_settings=base).run_daily_income()))
    return results


def run_employee_efficiency_for_companies(companies: list, base_settings: Optional[Settings] = None) -> list:
    base = base_settings or Settings.load()
    results = []
    for comp in companies:
        name = comp.get("name") or "Unnamed"
        results.append((name, Collector(comp, base_settings=base).run_employee_efficiency()))
    return results


def run_everything_for_companies(companies: list, base_settings: Optional[Settings] = None) -> list:
    base = base_settings or Settings.load()
    results = []
    for comp in companies:
        name = comp.get("name") or "Unnamed"
        results.append((name, Collector(comp, base_settings=base).run_everything()))
    return results


HISTORY_TABS = ["Company_History", "Stock_History", "Director_Efficiency", "Employee_Turnover_Log"]


def resort_existing_history(companies: list, base_settings: Optional[Settings] = None) -> list:
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
                # pyrefly: ignore [unsupported-operation]
                per_tab[tab] = None
        # pyrefly: ignore [bad-argument-type]
        results.append((name, per_tab))
    return results
