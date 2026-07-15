"""
Shared profit math for Company_History rows. Lives in its own module so the
live collector (app/collector.py) and the one-off backfill script
(scripts/backfill_company_history.py) can't drift out of sync with each
other.

Torn "week" definition used for avg_daily_profit_7day: Sunday 14:00 UTC ->
the following Sunday 14:00 UTC. All Torn API timestamps are UTC (TCT), so
this window is computed directly against unix timestamps - no local
timezone involved anywhere here.
"""

from __future__ import annotations

import calendar
import datetime
from typing import Sequence


def safe_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def torn_week_window(ts: int) -> tuple[int, int]:
    """(start, end) unix timestamps for the Sun-14:00-UTC -> Sun-14:00-UTC
    week that contains ts. end is exclusive."""
    dt = datetime.datetime.utcfromtimestamp(ts)
    days_since_sunday = (dt.weekday() - 6) % 7  # datetime: Mon=0 ... Sun=6
    candidate = dt.replace(hour=14, minute=0, second=0, microsecond=0) - datetime.timedelta(days=days_since_sunday)
    if candidate > dt:
        candidate -= datetime.timedelta(days=7)
    start = calendar.timegm(candidate.timetuple())
    end = start + 7 * 86400
    return start, end


def compute_row_profit_fields(daily_income: float, weekly_income: float,
                               advertising_budget: float, total_wage: float,
                               daily_stockcost: float) -> dict:
    """
    daily_profit  = daily_income - (daily_stockcost + advertising_budget + total_wage)
    weekly_profit = weekly_income - (advertising_budget + total_wage) * 7
      (advertising_budget and total_wage are paid daily by Torn, so the
      weekly figure scales them by 7 to match weekly_income's own window)
    """
    daily_profit = daily_income - (daily_stockcost + advertising_budget + total_wage)
    weekly_profit = weekly_income - (advertising_budget + total_wage) * 7
    return {
        "daily_profit": round(daily_profit, 2),
        "weekly_profit": round(weekly_profit, 2),
    }


def compute_rolling_7day_average(prior_rows: Sequence[dict], current_timestamp: int,
                                  current_value: float, field_name: str) -> float:
    """
    Average of `field_name` across every snapshot that falls in the same
    Torn week as current_timestamp (Sun 14:00 UTC -> next Sun 14:00 UTC),
    including the current snapshot itself. This is a rolling, in-progress
    average that updates with every snapshot taken during the week - it is
    NOT a fixed "last completed week" figure.

    prior_rows: existing Company_History records (dicts with at least
    'timestamp' and field_name), any of which may be outside the current
    week - those are filtered out automatically.
    """
    start, end = torn_week_window(current_timestamp)
    values = [current_value]
    for row in prior_rows:
        ts = int(safe_float(row.get("timestamp")))
        if ts == current_timestamp:
            continue
        if start <= ts < end:
            v = row.get(field_name)
            if v not in (None, ""):
                values.append(safe_float(v))
    return round(sum(values) / len(values), 2) if values else 0.0


def compute_avg_daily_profit_7day(prior_rows: Sequence[dict], current_timestamp: int,
                                   current_daily_profit: float) -> float:
    return compute_rolling_7day_average(prior_rows, current_timestamp, current_daily_profit, "daily_profit")


def compute_avg_daily_income_7day(prior_rows: Sequence[dict], current_timestamp: int,
                                   current_daily_income: float) -> float:
    return compute_rolling_7day_average(prior_rows, current_timestamp, current_daily_income, "daily_income")
