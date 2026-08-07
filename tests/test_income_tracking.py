import datetime

from app.income_tracking import (
    SECONDS_PER_DAY,
    build_income_observations,
    merge_income_observations,
    own_company_metrics,
    percentile,
    reporting_period_start,
    rolling_company_totals,
    summarize_star_ranges,
)


def _ts(day, hour=18, minute=10):
    return int(datetime.datetime(
        2026, 8, day, hour, minute, tzinfo=datetime.timezone.utc
    ).timestamp())


def _row(company_id, period, income, rating=10, own=False):
    return {
        "period_start": period,
        "timestamp": period + 60,
        "company_id": company_id,
        "company_name": f"Company {company_id}",
        "rating": rating,
        "daily_income": "",
        "weekly_income": income,
        "is_own_company": own,
    }


def test_reporting_period_uses_1810_utc_boundary():
    assert reporting_period_start(_ts(2, 18, 9)) == _ts(1)
    assert reporting_period_start(_ts(2, 18, 10)) == _ts(2)
    assert reporting_period_start(_ts(2, 23, 59)) == _ts(2)


def test_daily_observations_use_public_company_income_and_own_marker():
    companies = [{
        "id": 7,
        "name": "Own",
        "rating": 9,
        "income": {"daily": 1234, "weekly": 999999},
    }]
    rows = build_income_observations(companies, _ts(2), own_id="7")
    assert rows[0]["daily_income"] == 1234
    assert rows[0]["weekly_income"] == 999999
    assert rows[0]["is_own_company"] is True


def test_merge_replaces_duplicate_company_reporting_period():
    period = _ts(2)
    prior = [_row(1, period, 100)]
    companies = [{
        "id": 1, "name": "Company 1", "rating": 10,
        "income": {"daily": 250, "weekly": 1750},
    }]
    merged = merge_income_observations(prior, companies, period + 600)
    assert len(merged) == 1
    assert merged[0]["daily_income"] == 250
    assert merged[0]["weekly_income"] == 1750


def test_weekly_income_is_immediately_eligible():
    end = _ts(2)
    result = rolling_company_totals([_row(1, end, 700, own=True)], end)["1"]
    assert result["coverage"] == 7
    assert result["eligible"] is True
    assert result["rolling_income"] == 700


def test_daily_snapshot_uses_latest_weekly_value_and_previous_value():
    end = _ts(2)
    rows = [
        _row(1, end, 50, own=True),
        _row(1, end - SECONDS_PER_DAY, 700, own=True),
    ]
    result = rolling_company_totals(rows, end)["1"]
    assert result["rolling_income"] == 50
    assert result["previous_rolling_income"] == 700


def test_missing_weekly_income_is_not_eligible():
    end = _ts(2)
    row = _row(1, end, 0)
    row["weekly_income"] = ""
    result = rolling_company_totals([row], end)["1"]
    assert result["eligible"] is False
    assert result["coverage"] == 0


def test_percentile_interpolates_and_handles_single_value():
    assert percentile([10], 0.1) == 10
    assert percentile([0, 100], 0.1) == 10


def test_summary_reports_percentiles_counts_and_coverage():
    totals = {
        str(i): {
            "rating": 10.0,
            "eligible": i != 3,
            "rolling_income": i * 100 if i != 3 else None,
        }
        for i in range(1, 4)
    }
    summary = summarize_star_ranges(totals, _ts(2))[0]
    assert summary["stars"] == 10
    assert summary["total_count"] == 3
    assert summary["eligible_count"] == 2
    assert summary["minimum"] == 100
    assert summary["median"] == 150
    assert summary["maximum"] == 200
    assert summary["coverage"] == "2/3"


def test_own_company_metrics_use_observed_percentile_boundaries():
    totals = {
        "own": {
            "rating": 9.0, "eligible": True, "rolling_income": 150,
            "previous_rolling_income": 140, "coverage": 7,
            "is_own_company": True,
        },
    }
    summaries = [
        {"stars": 8, "minimum": 50, "maximum": 100},
        {"stars": 9, "minimum": 100, "maximum": 200},
        {"stars": 10, "minimum": 300, "maximum": 500},
    ]
    result = own_company_metrics(totals, summaries)
    assert result["rolling_7day_change"] == 10
    assert result["observed_drop_buffer"] == 50
    assert result["observed_next_star_gap"] == 150
    assert result["observed_range_position_percent"] == 50


def test_summary_allocates_star_ranges_by_income_rank_slots():
    totals = {
        "a": {"rating": 10.0, "eligible": True, "rolling_income": 1000},
        "b": {"rating": 9.0, "eligible": True, "rolling_income": 950},
        "c": {"rating": 10.0, "eligible": True, "rolling_income": 800},
        "d": {"rating": 9.0, "eligible": True, "rolling_income": 700},
    }

    summaries = {
        row["stars"]: row for row in summarize_star_ranges(totals, _ts(2))
    }

    assert summaries[10]["total_count"] == 2
    assert summaries[10]["minimum"] == 950
    assert summaries[10]["maximum"] == 1000
    assert summaries[9]["total_count"] == 2
    assert summaries[9]["minimum"] == 700
    assert summaries[9]["maximum"] == 800
