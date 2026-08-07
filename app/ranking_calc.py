"""
Pure ranking + star-cohort math for the Company Health Score feature
(app/collector.py::_compute_health_score). No I/O here - every function
takes plain dicts/lists and returns plain values, same separation-of-concerns
pattern as profit_calc.py/efficiency_calc.py.

Company rank (by weekly income, among same-type companies) reshuffles as
income changes. Company ratings normally change only at the Sunday 18:10 UTC
reset. The current rating counts therefore define fixed slot sizes for each
star level throughout the week. Every daily calculation orders all same-type
companies by Weekly Income and applies those slot sizes from highest to
lowest. Promotion, demotion, and required-income values come from the
resulting rank cutoffs, not from the current rating attached to whichever
company happens to occupy a cutoff rank.

This is an empirical, income-only heuristic, not Torn's actual unpublished,
multi-factor rating formula.
"""

from __future__ import annotations

import datetime
from typing import Optional


def _weekly_income(company: dict) -> float:
    return float((company.get("income") or {}).get("weekly", 0) or 0)


def rank_companies_by_weekly_income(companies: list[dict]) -> list[dict]:
    """Companies sorted by weekly income, highest first. Does not mutate
    the input list. Ties keep their original relative order (Python's sort
    is stable) - good enough for this app's purposes; Torn's own tie-break
    rule (if any) isn't published."""
    return sorted(companies, key=_weekly_income, reverse=True)


def find_rank(ranked_companies: list[dict], own_id) -> Optional[int]:
    """1-indexed rank of the company with id == own_id within an already-
    ranked list, or None if it isn't present (e.g. dropped out of the
    listing, or the listing fetch partially failed)."""
    if own_id in (None, ""):
        return None
    target_id = str(own_id)
    return next(
        (index + 1 for index, company in enumerate(ranked_companies) if str(company.get("id")) == target_id),
        None,
    )


def count_10_star_companies(companies: list[dict]) -> int:
    """How many companies in *companies* currently show a 10.0 rating.
    Ratings are floats with one decimal in practice and 10.0 is the
    maximum, so >= 10.0 and == 10.0 are equivalent here - >= is used to be
    defensive against any float rounding noise."""
    return sum(1 for company in companies if float(company.get("rating") or 0) >= 10.0)


def count_companies_by_star(companies: list[dict]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for company in companies:
        try:
            stars = int(float(company.get("rating") or 0))
        except (TypeError, ValueError):
            continue
        if stars > 0:
            counts[stars] = counts.get(stars, 0) + 1
    return counts


def compute_star_band_metrics(
    ranked_companies: list[dict],
    own_id,
    own_weekly_income: float,
    own_rating,
) -> dict:
    blank = {
        "current_star_level": None,
        "next_star_level": None,
        "previous_star_level": None,
        "income_to_reach_next_star": None,
        "required_weekly_income_to_star_up": None,
        "income_to_drop_to_previous_star": None,
    }
    if not ranked_companies:
        return blank
    try:
        current_star = int(float(own_rating))
    except (TypeError, ValueError):
        return blank
    if find_rank(ranked_companies, own_id) is None or current_star <= 0:
        return blank

    counts = count_companies_by_star(ranked_companies)
    result = dict(blank)
    result["current_star_level"] = current_star

    next_star = current_star + 1
    if next_star <= 10 and counts.get(next_star, 0):
        cutoff_rank = sum(
            count for stars, count in counts.items() if stars >= next_star
        )
        if 0 < cutoff_rank <= len(ranked_companies):
            required = _weekly_income(ranked_companies[cutoff_rank - 1])
            result["next_star_level"] = next_star
            result["required_weekly_income_to_star_up"] = required
            result["income_to_reach_next_star"] = max(
                0.0, required - own_weekly_income
            )

    previous_star = current_star - 1
    if previous_star >= 1:
        first_outside_index = sum(
            count for stars, count in counts.items() if stars >= current_star
        )
        result["previous_star_level"] = previous_star
        if first_outside_index < len(ranked_companies):
            outside_income = _weekly_income(ranked_companies[first_outside_index])
            result["income_to_drop_to_previous_star"] = max(
                0.0, own_weekly_income - outside_income
            )

    return result


def is_weekly_star_reset_snapshot(timestamp: int) -> bool:
    """True when a snapshot can record the weekly post-reset star bands."""
    dt = datetime.datetime.fromtimestamp(int(timestamp), tz=datetime.timezone.utc)
    if dt.weekday() != 6:  # Monday=0 ... Sunday=6
        return False
    return (dt.hour, dt.minute) >= (18, 10)


def compute_star_cohort_metrics(
    ranked_companies: list[dict],
    own_id,
    own_weekly_income: float,
    star_10_count: Optional[int],
) -> dict:
    """Where the director's own company sits TODAY relative to this week's
    already-locked-in 10-star cohort size (star_10_count), using today's
    live rank-by-income order.

    Returns {"income_to_reach_10_star": float | None,
             "income_buffer_before_9_star": float | None}:
      - income_to_reach_10_star: additional weekly income needed to be
        earning enough to sit inside the top star_10_count companies right
        now (0.0 if already inside - "on track", not a guarantee, since
        Torn's actual re-grade may weigh other factors too). None if there
        isn't enough information to compute this (no confirmed cohort size
        yet, own company not found in the listing, or an empty listing).
      - income_buffer_before_9_star: only meaningful (non-None) when
        already inside the cohort - weekly income margin remaining before
        the next company outside the cohort overtakes the director's own
        company. None when outside the cohort, or when every same-type
        company is within the cohort (nobody outside to be overtaken by).
    """
    blank = {"income_to_reach_10_star": None, "income_buffer_before_9_star": None}
    if not star_10_count or star_10_count <= 0 or not ranked_companies:
        return blank

    own_rank = find_rank(ranked_companies, own_id)
    if own_rank is None:
        return blank

    if own_rank <= star_10_count:
        # Already inside this week's cohort - check the margin to the
        # first company sitting just outside it.
        first_outside_index = star_10_count  # 0-indexed
        if first_outside_index < len(ranked_companies):
            buffer = own_weekly_income - _weekly_income(ranked_companies[first_outside_index])
        else:
            buffer = None  # every same-type company is within the cohort
        return {"income_to_reach_10_star": 0.0, "income_buffer_before_9_star": buffer}

    cutoff_index = star_10_count - 1  # 0-indexed: last company inside the cohort
    if cutoff_index >= len(ranked_companies):
        # Defensive only - own_rank > star_10_count already implies enough
        # companies exist for this branch to be reachable in practice.
        return {"income_to_reach_10_star": 0.0, "income_buffer_before_9_star": None}

    gap = _weekly_income(ranked_companies[cutoff_index]) - own_weekly_income
    return {"income_to_reach_10_star": max(0.0, gap), "income_buffer_before_9_star": None}
