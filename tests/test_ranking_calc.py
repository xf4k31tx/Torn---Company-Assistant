"""
Phase 6 coverage: app/ranking_calc.py - the pure ranking + star-cohort math
behind the Company Health Score feature (rank_by_income, the 10-star
"income to reach"/"buffer before dropping" numbers).
"""

from __future__ import annotations

import datetime

from app.ranking_calc import (
    compute_star_band_metrics,
    compute_star_cohort_metrics,
    count_companies_by_star,
    count_10_star_companies,
    find_rank,
    is_weekly_star_reset_snapshot,
    rank_companies_by_weekly_income,
)


def _company(id_, weekly, rating=9.0, name=None):
    return {"id": id_, "name": name or f"Company {id_}", "rating": rating, "income": {"weekly": weekly}}


# ---------------------------------------------------------------------------
# rank_companies_by_weekly_income / find_rank
# ---------------------------------------------------------------------------

def test_rank_companies_by_weekly_income_sorts_descending():
    companies = [_company(1, 100), _company(2, 300), _company(3, 200)]

    ranked = rank_companies_by_weekly_income(companies)

    assert [c["id"] for c in ranked] == [2, 3, 1]


def test_rank_companies_by_weekly_income_does_not_mutate_input():
    companies = [_company(1, 100), _company(2, 300)]
    original_order = list(companies)

    rank_companies_by_weekly_income(companies)

    assert companies == original_order


def test_rank_companies_by_weekly_income_handles_missing_income_as_zero():
    companies = [{"id": 1, "name": "A"}, _company(2, 50)]

    ranked = rank_companies_by_weekly_income(companies)

    assert [c["id"] for c in ranked] == [2, 1]


def test_find_rank_is_1_indexed():
    ranked = rank_companies_by_weekly_income([_company(1, 100), _company(2, 300), _company(3, 200)])

    assert find_rank(ranked, 2) == 1
    assert find_rank(ranked, 3) == 2
    assert find_rank(ranked, 1) == 3


def test_find_rank_returns_none_when_not_present():
    ranked = rank_companies_by_weekly_income([_company(1, 100)])

    assert find_rank(ranked, 999) is None


# ---------------------------------------------------------------------------
# count_10_star_companies
# ---------------------------------------------------------------------------

def test_count_10_star_companies_counts_only_exact_10s():
    companies = [
        _company(1, 100, rating=10.0), _company(2, 90, rating=9.9),
        _company(3, 80, rating=10.0), _company(4, 70, rating=10.0),
    ]

    assert count_10_star_companies(companies) == 3


def test_count_10_star_companies_empty_list_is_zero():
    assert count_10_star_companies([]) == 0


# ---------------------------------------------------------------------------
# is_weekly_star_reset_snapshot
# ---------------------------------------------------------------------------

def _ts(year, month, day, hour, minute):
    return int(datetime.datetime(year, month, day, hour, minute, tzinfo=datetime.timezone.utc).timestamp())


def test_is_weekly_star_reset_snapshot_true_on_sunday_at_exactly_18_10_utc():
    # 2026-08-02 is a Sunday.
    assert is_weekly_star_reset_snapshot(_ts(2026, 8, 2, 18, 10)) is True


def test_is_weekly_star_reset_snapshot_true_later_on_sunday():
    assert is_weekly_star_reset_snapshot(_ts(2026, 8, 2, 23, 59)) is True


def test_is_weekly_star_reset_snapshot_false_just_before_cutoff():
    assert is_weekly_star_reset_snapshot(_ts(2026, 8, 2, 18, 9)) is False


def test_is_weekly_star_reset_snapshot_false_on_other_weekdays():
    # 2026-08-03 is a Monday.
    assert is_weekly_star_reset_snapshot(_ts(2026, 8, 3, 20, 0)) is False


def test_is_weekly_star_reset_snapshot_false_early_sunday_before_reset():
    assert is_weekly_star_reset_snapshot(_ts(2026, 8, 2, 0, 0)) is False


# ---------------------------------------------------------------------------
# compute_star_cohort_metrics
# ---------------------------------------------------------------------------

def test_cohort_metrics_outside_cohort_computes_gap_to_cutoff_company():
    # 5 companies, star_10_count=2 -> cohort is ranks 1-2. Own company at
    # rank 3 (weekly=200) needs to beat rank-2's income (weekly=300).
    companies = [
        _company(1, 500), _company(2, 300), _company("own", 200), _company(4, 100), _company(5, 50),
    ]
    ranked = rank_companies_by_weekly_income(companies)

    result = compute_star_cohort_metrics(ranked, "own", own_weekly_income=200, star_10_count=2)

    assert result["income_to_reach_10_star"] == 100  # 300 - 200
    assert result["income_buffer_before_9_star"] is None


def test_cohort_metrics_inside_cohort_computes_buffer_to_next_company():
    # star_10_count=3, own company at rank 2 (weekly=400) - inside cohort.
    # Buffer against rank-4 (first company outside), weekly=150.
    companies = [
        _company(1, 500), _company("own", 400), _company(3, 300), _company(4, 150), _company(5, 50),
    ]
    ranked = rank_companies_by_weekly_income(companies)

    result = compute_star_cohort_metrics(ranked, "own", own_weekly_income=400, star_10_count=3)

    assert result["income_to_reach_10_star"] == 0.0
    assert result["income_buffer_before_9_star"] == 250  # 400 - 150


def test_cohort_metrics_gap_floored_at_zero_when_already_ahead_of_cutoff():
    """Defensive floor: if the caller's own_weekly_income (e.g. a slightly
    fresher read than what's in ranked_companies' own entry) is already
    above the cutoff company's income, the gap must never go negative -
    "0" (already there), not "-100"."""
    companies = [_company(1, 500), _company("own", 490), _company(3, 100)]
    ranked = rank_companies_by_weekly_income(companies)

    result = compute_star_cohort_metrics(ranked, "own", own_weekly_income=600, star_10_count=1)

    assert result["income_to_reach_10_star"] == 0
    assert result["income_buffer_before_9_star"] is None


def test_cohort_metrics_inside_cohort_with_nobody_outside_it():
    """Cohort size >= total companies of this type - everyone is "inside",
    so there's no one below to compute a drop-out buffer against."""
    companies = [_company(1, 500), _company("own", 400)]
    ranked = rank_companies_by_weekly_income(companies)

    result = compute_star_cohort_metrics(ranked, "own", own_weekly_income=400, star_10_count=5)

    assert result["income_to_reach_10_star"] == 0.0
    assert result["income_buffer_before_9_star"] is None


def test_cohort_metrics_blank_when_star_10_count_unknown():
    ranked = rank_companies_by_weekly_income([_company(1, 500), _company("own", 400)])

    result = compute_star_cohort_metrics(ranked, "own", own_weekly_income=400, star_10_count=None)

    assert result == {"income_to_reach_10_star": None, "income_buffer_before_9_star": None}


def test_cohort_metrics_blank_when_star_10_count_is_zero():
    ranked = rank_companies_by_weekly_income([_company(1, 500)])

    result = compute_star_cohort_metrics(ranked, 1, own_weekly_income=500, star_10_count=0)

    assert result == {"income_to_reach_10_star": None, "income_buffer_before_9_star": None}


def test_cohort_metrics_blank_when_own_company_not_in_listing():
    ranked = rank_companies_by_weekly_income([_company(1, 500), _company(2, 300)])

    result = compute_star_cohort_metrics(ranked, "missing", own_weekly_income=400, star_10_count=1)

    assert result == {"income_to_reach_10_star": None, "income_buffer_before_9_star": None}


def test_cohort_metrics_blank_when_ranked_companies_empty():
    result = compute_star_cohort_metrics([], "own", own_weekly_income=400, star_10_count=2)

    assert result == {"income_to_reach_10_star": None, "income_buffer_before_9_star": None}


def test_star_counts_use_current_ratings_as_fixed_slot_sizes():
    companies = [
        _company(1, 1000, 10), _company(2, 950, 9),
        _company(3, 900, 10), _company(4, 850, 9),
        _company(5, 700, 9), _company(6, 600, 8),
    ]
    assert count_companies_by_star(companies) == {10: 2, 9: 3, 8: 1}


def test_star_band_metrics_use_ranked_slots_not_current_company_labels():
    companies = [
        _company(1, 1000, 10),
        _company(2, 950, 9),
        _company("own", 850, 9),
        _company(4, 800, 10),
        _company(5, 700, 9),
        _company(6, 600, 8),
        _company(7, 500, 8),
    ]
    ranked = rank_companies_by_weekly_income(companies)

    result = compute_star_band_metrics(
        ranked, "own", own_weekly_income=850, own_rating=9
    )

    assert result["current_star_level"] == 9
    assert result["next_star_level"] == 10
    assert result["previous_star_level"] == 8
    assert result["required_weekly_income_to_star_up"] == 950
    assert result["income_to_reach_next_star"] == 100
    assert result["income_to_drop_to_previous_star"] == 250
