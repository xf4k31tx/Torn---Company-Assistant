from __future__ import annotations

import datetime
import math
import statistics
from collections import defaultdict

REPORTING_HOUR = 18
REPORTING_MINUTE = 10
SECONDS_PER_DAY = 86400
ROLLING_DAYS = 7
HISTORY_PERIODS = 84

INCOME_HISTORY_HEADERS = [
    "period_start", "timestamp", "date", "company_id", "company_name",
    "rating", "daily_income", "weekly_income", "is_own_company",
]

STAR_INCOME_SUMMARY_HEADERS = [
    "period_start", "updated_at", "stars", "total_count", "eligible_count",
    "minimum", "p10", "median", "p90", "maximum", "coverage", "freshness",
]


def _as_int(value) -> int:
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return 0


def _as_float(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def reporting_period_start(timestamp) -> int:
    ts = _as_int(timestamp)
    if not ts:
        return 0
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    boundary = dt.replace(
        hour=REPORTING_HOUR, minute=REPORTING_MINUTE, second=0, microsecond=0
    )
    if dt < boundary:
        boundary -= datetime.timedelta(days=1)
    return int(boundary.timestamp())


def reporting_period_date(period_start: int) -> str:
    return datetime.datetime.fromtimestamp(
        period_start, tz=datetime.timezone.utc
    ).strftime("%Y-%m-%d 18:10 UTC")


def build_income_observations(
    companies: list[dict], timestamp: int, own_id=None
) -> list[dict]:
    period = reporting_period_start(timestamp)
    rows = []
    for company in companies:
        company_id = company.get("id")
        if company_id in (None, ""):
            continue
        income = company.get("income") or {}
        rows.append({
            "period_start": period,
            "timestamp": _as_int(timestamp),
            "date": reporting_period_date(period),
            "company_id": company_id,
            "company_name": company.get("name", ""),
            "rating": company.get("rating", ""),
            "daily_income": income.get("daily", ""),
            "weekly_income": income.get("weekly", ""),
            "is_own_company": str(company_id) == str(own_id),
        })
    return rows


def merge_income_observations(
    prior_rows: list[dict],
    companies: list[dict],
    timestamp: int,
    own_id=None,
    retention_periods: int = HISTORY_PERIODS,
) -> list[dict]:
    period = reporting_period_start(timestamp)
    cutoff = period - max(0, retention_periods - 1) * SECONDS_PER_DAY
    merged = {}
    for row in prior_rows:
        row_period = _as_int(row.get("period_start"))
        company_id = row.get("company_id")
        if row_period >= cutoff and company_id not in (None, ""):
            merged[(str(company_id), row_period)] = dict(row)
    for row in build_income_observations(companies, timestamp, own_id):
        merged[(str(row["company_id"]), period)] = row
    return sorted(
        merged.values(),
        key=lambda row: (-_as_int(row.get("period_start")), str(row.get("company_id"))),
    )


def _latest_rows_by_company(rows: list[dict], end_period: int) -> dict[str, dict]:
    latest = {}
    for row in sorted(rows, key=lambda item: _as_int(item.get("period_start")), reverse=True):
        company_id = str(row.get("company_id", ""))
        period = _as_int(row.get("period_start"))
        if company_id and period <= end_period and company_id not in latest:
            latest[company_id] = row
    return latest


def rolling_company_totals(
    rows: list[dict], end_period: int
) -> dict[str, dict]:
    latest = _latest_rows_by_company(rows, end_period)
    previous = _latest_rows_by_company(rows, end_period - SECONDS_PER_DAY)
    totals = {}
    for company_id, meta in latest.items():
        weekly_income = _as_float(meta.get("weekly_income"))
        prior_row = previous.get(company_id)
        prior_weekly_income = (
            _as_float(prior_row.get("weekly_income")) if prior_row else None
        )
        eligible = weekly_income is not None
        totals[company_id] = {
            "company_id": meta.get("company_id", company_id),
            "company_name": meta.get("company_name", ""),
            "rating": _as_float(meta.get("rating")),
            "is_own_company": str(meta.get("is_own_company", "")).lower() in {"true", "1", "yes"},
            "coverage": ROLLING_DAYS if eligible else 0,
            "eligible": eligible,
            "rolling_income": weekly_income,
            "previous_rolling_income": prior_weekly_income,
        }
    return totals


def percentile(values: list[float], fraction: float):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def summarize_star_ranges(
    totals: dict[str, dict], timestamp: int
) -> list[dict]:
    period = reporting_period_start(timestamp)
    counts = defaultdict(int)
    for company in totals.values():
        rating = company.get("rating")
        if rating is not None:
            counts[int(math.floor(rating))] += 1

    ordered = sorted(
        totals.values(),
        key=lambda company: (
            company.get("rolling_income") is not None,
            company.get("rolling_income") or 0,
        ),
        reverse=True,
    )
    summaries = []
    offset = 0
    for stars in sorted(counts, reverse=True):
        total_count = counts[stars]
        companies = ordered[offset:offset + total_count]
        offset += total_count
        values = [
            company["rolling_income"] for company in companies
            if company.get("eligible") and company.get("rolling_income") is not None
        ]
        eligible_count = len(values)
        summaries.append({
            "period_start": period,
            "updated_at": _as_int(timestamp),
            "stars": stars,
            "total_count": total_count,
            "eligible_count": eligible_count,
            "minimum": min(values) if values else "",
            "p10": percentile(values, 0.10) if values else "",
            "median": statistics.median(values) if values else "",
            "p90": percentile(values, 0.90) if values else "",
            "maximum": max(values) if values else "",
            "coverage": f"{eligible_count}/{total_count}",
            "freshness": "Current",
        })
    return summaries


def own_company_metrics(
    totals: dict[str, dict], summaries: list[dict]
) -> dict:
    own = next((value for value in totals.values() if value.get("is_own_company")), None)
    blank = {
        "rolling_7day_income": None,
        "rolling_7day_coverage": 0,
        "rolling_7day_change": None,
        "observed_range_position_percent": None,
        "observed_drop_buffer": None,
        "observed_next_star_gap": None,
    }
    if not own:
        return blank

    result = dict(blank)
    current = own.get("rolling_income")
    previous = own.get("previous_rolling_income")
    result["rolling_7day_income"] = current
    result["rolling_7day_coverage"] = own.get("coverage", 0)
    if current is not None and previous is not None:
        result["rolling_7day_change"] = current - previous
    if current is None or own.get("rating") is None:
        return result

    by_star = {int(row["stars"]): row for row in summaries}
    stars = int(math.floor(own["rating"]))
    current_range = by_star.get(stars)
    next_range = by_star.get(stars + 1)
    previous_range = by_star.get(stars - 1)
    if current_range:
        low = _as_float(current_range.get("minimum"))
        high = _as_float(current_range.get("maximum"))
        if low is not None and high is not None and high > low:
            result["observed_range_position_percent"] = max(
                0.0, min(100.0, (current - low) / (high - low) * 100)
            )
    if previous_range:
        threshold = _as_float(previous_range.get("maximum"))
        if threshold is not None:
            result["observed_drop_buffer"] = max(0.0, current - threshold)
    if next_range:
        threshold = _as_float(next_range.get("minimum"))
        if threshold is not None:
            result["observed_next_star_gap"] = max(0.0, threshold - current)
    return result
