"""
Desktop-to-web parity coverage for profit calculations.
"""

from __future__ import annotations

from tca_web.domain.profit_calc import (
    compute_monthly_income,
    compute_monthly_profit,
    compute_rolling_30day_sum,
)

DAY = 86400


def test_rolling_30day_sum_includes_current_value_with_no_prior_rows():
    total = compute_rolling_30day_sum(
        [], current_timestamp=1_700_000_000, current_value=1000.0, field_name="daily_income"
    )
    assert total == 1000.0


def test_rolling_30day_sum_adds_rows_within_the_trailing_window():
    now = 1_700_000_000
    prior_rows = [
        {"timestamp": str(now - 5 * DAY), "daily_income": "200"},
        {"timestamp": str(now - 29 * DAY), "daily_income": "50"},
    ]
    total = compute_rolling_30day_sum(
        prior_rows, now, current_value=1000.0, field_name="daily_income"
    )
    assert total == 1000.0 + 200.0 + 50.0


def test_rolling_30day_sum_excludes_rows_older_than_30_days():
    now = 1_700_000_000
    prior_rows = [
        {"timestamp": str(now - 31 * DAY), "daily_income": "999999"},  # just outside window
        {"timestamp": str(now - 30 * DAY - 1), "daily_income": "999999"},  # 1 second outside
    ]
    total = compute_rolling_30day_sum(
        prior_rows, now, current_value=1000.0, field_name="daily_income"
    )
    assert total == 1000.0


def test_rolling_30day_sum_excludes_future_timestamped_rows():
    """A row timestamped after current_timestamp must not count - the
    window is strictly trailing, not centered."""
    now = 1_700_000_000
    prior_rows = [{"timestamp": str(now + DAY), "daily_income": "999999"}]
    total = compute_rolling_30day_sum(
        prior_rows, now, current_value=1000.0, field_name="daily_income"
    )
    assert total == 1000.0


def test_rolling_30day_sum_does_not_double_count_a_row_matching_current_timestamp():
    now = 1_700_000_000
    prior_rows = [{"timestamp": str(now), "daily_income": "1000"}]  # duplicate of "current" row
    total = compute_rolling_30day_sum(
        prior_rows, now, current_value=1000.0, field_name="daily_income"
    )
    assert total == 1000.0  # not 2000.0


def test_rolling_30day_sum_skips_blank_or_missing_field_values():
    now = 1_700_000_000
    prior_rows = [
        {"timestamp": str(now - DAY), "daily_income": ""},
        {"timestamp": str(now - 2 * DAY)},  # field missing entirely
        {"timestamp": str(now - 3 * DAY), "daily_income": "300"},
    ]
    total = compute_rolling_30day_sum(
        prior_rows, now, current_value=1000.0, field_name="daily_income"
    )
    assert total == 1000.0 + 300.0


def test_rolling_30day_sum_is_a_total_not_an_average():
    """Confirmed plan semantics: SUM over the trailing period, mirroring
    weekly_income/weekly_profit - not compute_rolling_7day_average's mean."""
    now = 1_700_000_000
    prior_rows = [{"timestamp": str(now - DAY * n), "daily_income": "100"} for n in range(1, 6)]
    total = compute_rolling_30day_sum(
        prior_rows, now, current_value=100.0, field_name="daily_income"
    )
    assert total == 600.0  # 6 snapshots x 100, not the average (100)


def test_monthly_income_and_monthly_profit_wrappers_use_correct_fields():
    now = 1_700_000_000
    prior_rows = [
        {"timestamp": str(now - DAY), "daily_income": "500", "daily_profit": "150"},
    ]
    assert compute_monthly_income(prior_rows, now, current_daily_income=1000.0) == 1500.0
    assert compute_monthly_profit(prior_rows, now, current_daily_profit=300.0) == 450.0
