"""
Phase 2 coverage: build_total_effectiveness_projection_rows().

Total Projection[position] = Base Projection[position]
                              + (effectiveness_total - effectiveness_working_stats)
"""

from __future__ import annotations

from app.efficiency_calc import (
    build_position_efficiency_rows,
    build_total_effectiveness_projection_rows,
)


def _row(tId, name, current_position, effectiveness_total, effectiveness_working_stats, **projected):
    return {
        "tId": tId,
        "name": name,
        "current_position": current_position,
        "effectiveness_total": effectiveness_total,
        "effectiveness_working_stats": effectiveness_working_stats,
        "projected": projected,
    }


def test_total_projection_adds_non_work_stats_delta_to_base_projection():
    """effectiveness_total=187, effectiveness_working_stats=40 -> delta=147
    added on top of every position's base projection."""
    rows = [_row("1", "JohnKnot", "Director", 187, 40, Director=94.2, Trainer=71.3)]

    headers, out = build_total_effectiveness_projection_rows(rows, ["Director", "Trainer"])

    assert headers == ["tId", "name", "current_position", "Director", "Trainer"]
    director_total, trainer_total = out[0][3], out[0][4]
    assert director_total == 94.2 + 147
    assert trainer_total == 71.3 + 147


def test_total_projection_blank_when_no_base_projection_for_position():
    """A position missing from the employee's Tornstats projection block
    stays blank rather than becoming just the bare delta."""
    rows = [_row("1", "JohnKnot", "Director", 187, 40, Director=94.2)]

    headers, out = build_total_effectiveness_projection_rows(rows, ["Director", "Accountant"])

    assert out[0][headers.index("Director")] == 94.2 + 147
    assert out[0][headers.index("Accountant")] == ""


def test_total_projection_matches_documented_component_sum_identity():
    """effectiveness_total - effectiveness_working_stats is documented as
    exactly the sum of the other 7 components (settled_in, director_education,
    addiction, inactivity, management, book, merits) - verify the delta used
    here equals that explicit sum for a realistic breakdown."""
    components = {
        "working_stats": 40, "settled_in": 20, "director_education": 15,
        "addiction": -5, "inactivity": 0, "management": 10, "book": 5, "merits": 7,
    }
    total = sum(components.values())
    rows = [_row("1", "Emp", "Director", total, components["working_stats"], Director=100)]

    _, out = build_total_effectiveness_projection_rows(rows, ["Director"])

    expected_delta = sum(v for k, v in components.items() if k != "working_stats")
    assert out[0][3] == 100 + expected_delta


def test_total_projection_handles_missing_effectiveness_fields_gracefully():
    """Missing/blank effectiveness_total or effectiveness_working_stats
    should not raise - the delta falls back to 0 rather than crashing."""
    rows = [{"tId": "1", "name": "Emp", "current_position": "Director", "projected": {"Director": 50}}]

    headers, out = build_total_effectiveness_projection_rows(rows, ["Director"])

    assert out[0][headers.index("Director")] == 50


def test_total_projection_rows_same_shape_as_base_projection_rows():
    """Total Effectiveness Projections must have the same row/column shape
    (same headers, same row count/order) as Base Effectiveness Projections -
    a display table, not a different layout, per the confirmed plan."""
    rows = [
        _row("1", "A", "Director", 150, 100, Director=90, Trainer=60),
        _row("2", "B", "Trainer", 120, 90, Director=70, Trainer=95),
    ]
    positions = ["Director", "Trainer"]

    base_headers, base_out = build_position_efficiency_rows(rows, positions)
    total_headers, total_out = build_total_effectiveness_projection_rows(rows, positions)

    assert base_headers == total_headers
    assert len(base_out) == len(total_out)
    assert [r[:3] for r in base_out] == [r[:3] for r in total_out]  # tId/name/current_position identical
