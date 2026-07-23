from __future__ import annotations

from app.config import Settings


def test_employee_column_preferences_round_trip(monkeypatch):
    stored = {}
    monkeypatch.setattr("app.config.secure_storage.get", lambda key, default: stored.get(key, default))
    monkeypatch.setattr("app.config.secure_storage.set", lambda key, value: stored.__setitem__(key, value))

    selected = ["name", "effectiveness_working_stats", "best_fit_position"]
    Settings(employee_visible_columns=selected).save()

    assert Settings.load().employee_visible_columns == selected


def test_invalid_employee_column_preferences_fall_back_to_empty(monkeypatch):
    monkeypatch.setattr(
        "app.config.secure_storage.get",
        lambda key, default: {"employee_visible_columns": "not-a-list"},
    )

    assert Settings.load().employee_visible_columns == []
