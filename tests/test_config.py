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


def test_legacy_oauth_file_path_is_removed_on_save(monkeypatch):
    stored = {
        "settings": {
            "google_oauth_client_file": "C:/private/client.json",
            "snapshot_interval_minutes": 30,
        }
    }
    monkeypatch.setattr("app.config.secure_storage.get", lambda key, default: stored.get(key, default))
    monkeypatch.setattr("app.config.secure_storage.set", lambda key, value: stored.__setitem__(key, value))

    settings = Settings.load()
    settings.save()

    assert "google_oauth_client_file" not in stored["settings"]


def test_scheduled_collection_preferences_round_trip(monkeypatch):
    from app.config import Settings

    stored = {}
    monkeypatch.setattr("app.config.secure_storage.get", lambda *_args: stored)
    monkeypatch.setattr(
        "app.config.secure_storage.set",
        lambda _key, value: stored.update(value),
    )
    settings = Settings(
        scheduled_collection_enabled=True,
        scheduled_company_names=["A", "B"],
        scheduled_wake_computer=True,
    )
    settings.save()
    loaded = Settings.load()
    assert loaded.scheduled_collection_enabled is True
    assert loaded.scheduled_company_names == ["A", "B"]
    assert loaded.scheduled_wake_computer is True
