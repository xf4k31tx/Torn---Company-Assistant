import contextlib
import datetime
from types import SimpleNamespace

from app.income_tracking import reporting_period_start
from app.scheduled_collection import company_is_due, run_scheduled_collection
from app.windows_scheduler import build_task_xml, scheduled_command


def _ts(day, hour=18, minute=10):
    return int(datetime.datetime(
        2026, 8, day, hour, minute, tzinfo=datetime.timezone.utc
    ).timestamp())


class FakeSettings:
    scheduled_collection_enabled = True
    scheduled_company_names = []
    scheduled_last_run = ""
    scheduled_last_result = ""

    def save(self):
        self.saved = True


def test_company_due_uses_1810_reporting_period():
    company = {"last_scheduled_income_period": reporting_period_start(_ts(2))}
    assert company_is_due(company, _ts(2, 23, 0)) is False
    assert company_is_due(company, _ts(3, 18, 10)) is True


def test_task_xml_is_hourly_interactive_least_privilege_and_wakeable():
    xml = build_task_xml(
        "TCA.exe",
        ["--scheduled-daily-income"],
        wake_computer=True,
        start=datetime.datetime(2026, 8, 5, 12, 0),
        user_id="TEST\\user",
    )
    assert "<Interval>PT1H</Interval>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    assert "<RunLevel>LeastPrivilege</RunLevel>" in xml
    assert "<WakeToRun>true</WakeToRun>" in xml
    assert "--scheduled-daily-income" in xml


def test_scheduled_command_uses_stable_executable_for_frozen_build():
    executable, arguments = scheduled_command(
        executable=r"C:\Program Files\TCA\TCA.exe", frozen=True
    )
    assert executable.endswith("TCA.exe")
    assert arguments == ["--scheduled-daily-income"]


def test_scheduled_collection_skips_current_period(monkeypatch, tmp_path):
    now = _ts(2)
    settings = FakeSettings()
    company = {
        "name": "A",
        "last_scheduled_income_period": reporting_period_start(now),
    }
    called = []
    monkeypatch.setattr(
        "app.scheduled_collection._configure_logging",
        lambda: SimpleNamespace(info=lambda *_: None, error=lambda *_: None),
    )
    monkeypatch.setattr(
        "app.scheduled_collection.run_daily_income_for_companies",
        lambda *_args, **_kwargs: called.append(True),
    )
    code, results = run_scheduled_collection(
        [company], settings, timestamp=now, persist=False
    )
    assert code == 0
    assert results == []
    assert called == []
    assert "Already current" in settings.scheduled_last_result


def test_scheduled_collection_updates_successful_company(monkeypatch):
    now = _ts(2)
    settings = FakeSettings()
    company = {"name": "A"}
    result = SimpleNamespace(ok=True, message="ok")
    monkeypatch.setattr(
        "app.scheduled_collection._configure_logging",
        lambda: SimpleNamespace(info=lambda *_: None, error=lambda *_: None),
    )

    @contextlib.contextmanager
    def lock():
        yield True

    monkeypatch.setattr("app.scheduled_collection.collection_lock", lock)
    monkeypatch.setattr(
        "app.scheduled_collection.run_daily_income_for_companies",
        lambda *_args, **_kwargs: [("A", result)],
    )
    code, results = run_scheduled_collection(
        [company], settings, timestamp=now, persist=False
    )
    assert code == 0
    assert results == [("A", result)]
    assert company["last_scheduled_income_period"] == reporting_period_start(now)
    assert settings.scheduled_last_result == "Updated: A"


def test_scheduled_collection_respects_selected_companies(monkeypatch):
    now = _ts(2)
    settings = FakeSettings()
    settings.scheduled_company_names = ["B"]
    companies = [{"name": "A"}, {"name": "B"}]
    seen = []
    monkeypatch.setattr(
        "app.scheduled_collection._configure_logging",
        lambda: SimpleNamespace(info=lambda *_: None, error=lambda *_: None),
    )

    @contextlib.contextmanager
    def lock():
        yield True

    monkeypatch.setattr("app.scheduled_collection.collection_lock", lock)
    def run(due, **_kwargs):
        seen.extend(company["name"] for company in due)
        return [("B", SimpleNamespace(ok=True, message="ok"))]
    monkeypatch.setattr(
        "app.scheduled_collection.run_daily_income_for_companies", run
    )
    run_scheduled_collection(companies, settings, timestamp=now, persist=False)
    assert seen == ["B"]


def test_scheduled_collection_retries_failures(monkeypatch):
    from app.scheduled_collection import _collect_with_retries

    company = {"name": "A"}
    attempts = []
    monkeypatch.setattr("app.scheduled_collection.time.sleep", lambda _seconds: None)

    def run(_companies, **_kwargs):
        attempts.append(True)
        return [(
            "A",
            SimpleNamespace(ok=len(attempts) >= 2, message="temporary"),
        )]

    monkeypatch.setattr(
        "app.scheduled_collection.run_daily_income_for_companies", run
    )
    results = _collect_with_retries([company], FakeSettings())
    assert len(attempts) == 2
    assert results[0][1].ok is True
