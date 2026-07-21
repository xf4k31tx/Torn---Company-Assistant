"""
Tests using the mock clients, exercising app.collector.Collector against the
current (Phase 4-7) API: Collector(company_dict, base_settings=...), the two
independent run_snapshot()/run_employee_efficiency() actions plus
run_everything(), and the module-level run_*_for_companies() wrappers.

Run with:  python -m pytest tests/test_collector_mocked.py -v

Mock fixture shape (tests/mock_data/endpoints.json): 5 employees across
Director/Oil Courier (x2)/Accountant/Trainer, matching the Tornstats mock's
"12" efficiency block (Director=94.2, Oil Courier=68.5, Accountant=82.1,
Trainer=71.3 - flat, ignoring each employee's individual stats, since the
mock doesn't vary its response by input). That makes the "who's misplaced"
outcome fully deterministic - see TestCollectorEmployeeEfficiency's comment
for the by-hand derivation.
"""

from __future__ import annotations

import pytest

from tests.mock_client import MockSheetsClient, MockTornAPI, MockTornStatsAPI


class TestCollectorSnapshot:
    """Verify the Collector.run_snapshot() flow using fully mocked external APIs."""

    def test_successful_snapshot(self, all_patched, mock_torn: MockTornAPI,
                                  mock_sheets: MockSheetsClient, test_settings, test_company):
        from app.collector import Collector

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is True
        assert result.company_name == "Knotty Oil Co"
        assert result.employee_count == 5
        assert result.stock_count == 4
        called_methods = {c.method for c in mock_torn.calls}
        assert {"get_company_profile_v2", "get_company_employees", "get_company_stock_v2",
                "get_company_timestamp_v2", "get_company_listings"} <= called_methods
        assert "Company_History" in mock_sheets._tabs
        assert "Employees" in mock_sheets._tabs
        assert "Stock_History" in mock_sheets._tabs

        company_row = mock_sheets._tabs["Company_History"][0]
        assert company_row["total_wage"] == "572000"
        assert float(company_row["avg_employee_effectiveness"]) == pytest.approx(76.6)

    def test_health_score_computed(self, all_patched, mock_sheets: MockSheetsClient,
                                    test_settings, test_company):
        """Own company (id 220001, weekly income 29,750,000) ranks 2nd of 3
        in the mock listings fixture (Quick Lube 40M > Knotty Oil 29.75M >
        Oil Express 15M) - fully deterministic given the fixed mock data."""
        from app.collector import Collector

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is True
        row = mock_sheets._tabs["Company_History"][0]
        assert row["rank_by_income"] == "2"
        assert row["rank_total_in_type"] == "3"
        assert float(row["rank_percentile"]) == pytest.approx(66.7, abs=0.1)
        assert collector.company["last_rank"] == 2  # persisted onto the company dict in-place

    def test_stockout_predictor_flags_low_stock(self, all_patched, mock_sheets: MockSheetsClient,
                                                 test_settings, test_company):
        """Oil Canister: in_stock=5, sold_amount=5 -> 1.0 days of runway,
        under the 3-day STOCKOUT_SOON_DAYS threshold."""
        from app.collector import Collector

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is True
        stock_rows = mock_sheets._tabs["Stock_History"]
        oil_canister = next(r for r in stock_rows if r["name"] == "Oil Canister")
        assert float(oil_canister["days_until_stockout"]) == pytest.approx(1.0)
        assert oil_canister["stockout_soon"] == "True"

        premium_oil = next(r for r in stock_rows if r["name"] == "Premium Oil")
        assert float(premium_oil["days_until_stockout"]) > 3  # 250/40 = 6.25 days, not soon
        assert premium_oil["stockout_soon"] == "False"

    def test_duplicate_24h_period_skips_append(self, all_patched,
                                                mock_sheets: MockSheetsClient,
                                                mock_torn: MockTornAPI,
                                                test_settings, test_company):
        from app.collector import Collector

        mock_ts = mock_torn.get_company_timestamp_v2()["timestamp"]
        mock_sheets.seed_tab("Company_History", [{"timestamp": str(mock_ts), "name": "Knotty Oil Co"}])

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is True
        assert result.is_update is True
        # Same fixed 18:00-UTC period as the seeded row - no new row appended.
        assert len(mock_sheets._tabs["Company_History"]) == 1

    def test_missing_torn_key_returns_error(self, test_settings):
        from app.collector import Collector

        test_settings.torn_api_key = ""
        company = {"name": "NoKeyCo"}
        collector = Collector(company, base_settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is False
        assert "Torn API key" in result.message

    def test_torn_api_rate_limit_error(self, all_patched, mock_torn: MockTornAPI,
                                        test_settings, test_company):
        from app.collector import Collector

        mock_torn.inject_error("get_company_profile_v2", "rate_limited")
        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is False
        assert "rate limited" in result.message.lower()

    def test_torn_api_bad_key_error(self, all_patched, mock_torn: MockTornAPI,
                                     test_settings, test_company):
        from app.collector import Collector

        mock_torn.inject_error("get_company_profile_v2", "incorrect_key")
        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is False
        assert "Incorrect key" in result.message

    def test_multi_company_snapshot(self, all_patched, test_settings):
        from app.collector import run_company_snapshots

        companies = [
            {"name": "Alpha", "torn_api_key": "KEY_A", "google_sheet_id": "SHEET_A"},
            {"name": "Beta", "torn_api_key": "KEY_B", "google_sheet_id": "SHEET_B"},
        ]
        results = run_company_snapshots(companies, base_settings=test_settings)

        assert len(results) == 2
        for name, res in results:
            assert res.ok is True, f"{name} failed: {res.message}"

    def test_duplicate_company_skipped(self, all_patched, test_settings):
        from app.collector import run_company_snapshots

        companies = [
            {"name": "A", "torn_api_key": "KEY_X", "google_sheet_id": "SHEET_X"},
            {"name": "B", "torn_api_key": "KEY_X", "google_sheet_id": "SHEET_X"},
        ]
        results = run_company_snapshots(companies, base_settings=test_settings)

        assert results[0][1].ok is True
        assert results[1][1].ok is False
        assert "duplicate" in results[1][1].message.lower()

    def test_company_blank_sheet_id_auto_creates(self, patch_torn, patch_tornstats,
                                                   mock_sheets: MockSheetsClient, test_settings):
        """Replaces the old (Phase <=3) "missing sheet ID -> failure" test:
        as of Phase 4/5, a blank google_sheet_id auto-creates a new Sheet
        named after the company instead of failing."""
        from unittest.mock import patch as mock_patch
        from app.collector import Collector

        company = {"name": "NewlyAddedCo", "torn_api_key": "KEY"}  # no google_sheet_id at all
        with mock_patch("app.collector.SheetsClient.get_or_create",
                         return_value=(mock_sheets, "AUTO_CREATED_SHEET_ID", True)) as mock_get_or_create:
            collector = Collector(company, base_settings=test_settings)
            result = collector.run_snapshot()

        assert result.ok is True
        # get_or_create() called with the blank ID and the company's name.
        mock_get_or_create.assert_called_once_with("", "NewlyAddedCo", "NewlyAddedCo")
        # The resolved (auto-created) ID gets written back onto the company
        # dict in place, so a caller's persist_companies() picks it up.
        assert company["google_sheet_id"] == "AUTO_CREATED_SHEET_ID"


class TestCollectorEmployeeEfficiency:
    """
    Verify the Collector.run_employee_efficiency() flow.

    Misplaced-employee derivation (mock fixture is deterministic - the
    Tornstats mock always returns the same flat block regardless of input
    stats): projected efficiency per position is Director=94.2, Oil
    Courier=68.5, Accountant=82.1, Trainer=71.3 for every employee, so
    best_fit is always Director (94.2) for everyone. misplaced_flag fires
    when (best_fit - current) >= 15:
      - JohnKnot (Director, 94.2):        diff  0.0 -> not misplaced
      - OilHand42 (Oil Courier, 68.5):     diff 25.7 -> misplaced
      - TankFillr (Oil Courier, 68.5):     diff 25.7 -> misplaced
      - FinanceGuru (Accountant, 82.1):    diff 12.1 -> not misplaced
      - TrainerX (Trainer, 71.3):          diff 22.9 -> misplaced
    -> misplaced_count == 3.
    """

    def test_successful_run(self, all_patched, mock_sheets: MockSheetsClient,
                             test_settings, test_company):
        from app.collector import Collector

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_employee_efficiency()

        assert result.ok is True
        assert result.employee_count == 5
        assert result.misplaced_count == 3
        assert "Employee_Effectiveness" in mock_sheets._tabs
        assert "Position_Efficiency" in mock_sheets._tabs
        assert len(mock_sheets._tabs["Employee_Effectiveness"]) == 5

        director_row = next(r for r in mock_sheets._tabs["Employee_Effectiveness"] if r["name"] == "JohnKnot")
        assert director_row["misplaced_flag"] == "False"
        courier_row = next(r for r in mock_sheets._tabs["Employee_Effectiveness"] if r["name"] == "OilHand42")
        assert courier_row["misplaced_flag"] == "True"

    def test_missing_tornstats_key_returns_error(self, patch_torn, test_settings):
        from app.collector import Collector

        test_settings.tornstats_api_key = ""
        company = {"name": "NoTSKeyCo", "torn_api_key": "KEY"}
        collector = Collector(company, base_settings=test_settings)
        result = collector.run_employee_efficiency()

        assert result.ok is False
        assert "Tornstats API key" in result.message

    def test_missing_torn_key_returns_error(self, test_settings):
        from app.collector import Collector

        test_settings.torn_api_key = ""
        company = {"name": "NoKeyCo", "tornstats_api_key": "TS_KEY"}
        collector = Collector(company, base_settings=test_settings)
        result = collector.run_employee_efficiency()

        assert result.ok is False
        assert "Torn API key" in result.message

    def test_turnover_log_first_run_all_joined(self, all_patched, mock_sheets: MockSheetsClient,
                                                test_settings, test_company):
        from app.collector import Collector

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_employee_efficiency()

        assert result.ok is True
        turnover = mock_sheets._tabs.get("Employee_Turnover_Log", [])
        assert len(turnover) == 5
        assert all(r["event"] == "joined" for r in turnover)

    def test_turnover_log_no_new_events_on_unchanged_roster(self, all_patched, mock_sheets: MockSheetsClient,
                                                              test_settings, test_company):
        from app.collector import Collector

        # Seed Employee_Effectiveness with exactly the roster the mock
        # employees data will produce, so the "previous roster" diff finds
        # no joins/leaves on this run.
        mock_sheets.seed_tab("Employee_Effectiveness", [
            {"tId": "220001", "name": "JohnKnot", "current_position": "Director"},
            {"tId": "220002", "name": "OilHand42", "current_position": "Oil Courier"},
            {"tId": "220003", "name": "TankFillr", "current_position": "Oil Courier"},
            {"tId": "220004", "name": "FinanceGuru", "current_position": "Accountant"},
            {"tId": "220005", "name": "TrainerX", "current_position": "Trainer"},
        ])

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_employee_efficiency()

        assert result.ok is True
        assert mock_sheets._tabs.get("Employee_Turnover_Log", []) == []

    def test_turnover_log_detects_departure(self, all_patched, mock_sheets: MockSheetsClient,
                                             test_settings, test_company):
        from app.collector import Collector

        # Seed a previous roster with an extra employee (id 999999) who is
        # NOT in the mock's current 5-employee roster - should log a "left"
        # event, on top of no "joined" events for the 5 who match.
        mock_sheets.seed_tab("Employee_Effectiveness", [
            {"tId": "220001", "name": "JohnKnot", "current_position": "Director"},
            {"tId": "220002", "name": "OilHand42", "current_position": "Oil Courier"},
            {"tId": "220003", "name": "TankFillr", "current_position": "Oil Courier"},
            {"tId": "220004", "name": "FinanceGuru", "current_position": "Accountant"},
            {"tId": "220005", "name": "TrainerX", "current_position": "Trainer"},
            {"tId": "999999", "name": "GoneGuy", "current_position": "Trainer"},
        ])

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_employee_efficiency()

        assert result.ok is True
        turnover = mock_sheets._tabs.get("Employee_Turnover_Log", [])
        assert len(turnover) == 1
        assert turnover[0]["tId"] == "999999"
        assert turnover[0]["event"] == "left"

    def test_capacity_priority_assignment_applied(self, all_patched, mock_sheets: MockSheetsClient,
                                                    test_settings, test_company):
        """When a company has position_capacities/position_priority_order
        configured, assign_positions() runs and populates assigned_position/
        assigned_efficiency on every row (not just the unconstrained
        best_fit_position)."""
        from app.collector import Collector

        test_company["position_capacities"] = {"Director": 1, "Oil Courier": 2, "Accountant": 1, "Trainer": 1}
        test_company["position_priority_order"] = ["Director", "Accountant", "Oil Courier", "Trainer"]

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_employee_efficiency()

        assert result.ok is True
        rows = mock_sheets._tabs["Employee_Effectiveness"]
        assigned = {r["name"]: r["assigned_position"] for r in rows}
        # Only one Director seat, and JohnKnot is the only candidate with a
        # projection for it in this fixture (flat 94.2 for everyone) - all
        # 5 candidates tie for every position under this mock's flat
        # response, so capacity=1 means exactly one of them gets Director;
        # the assertion that matters here is that assignment actually ran
        # (every row has SOME assigned_position, not blank).
        assert all(v != "" for v in assigned.values())


class TestCollectorEverything:
    def test_run_everything_both_succeed(self, all_patched, mock_sheets: MockSheetsClient,
                                          test_settings, test_company):
        from app.collector import Collector

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_everything()

        assert result.ok is True
        assert result.snapshot.ok is True
        assert result.employee_efficiency.ok is True
        assert "Company_History" in mock_sheets._tabs
        assert "Employee_Effectiveness" in mock_sheets._tabs

    def test_run_everything_for_companies_wrapper(self, all_patched, test_settings):
        from app.collector import run_everything_for_companies

        companies = [{"name": "Gamma", "torn_api_key": "KEY_G", "tornstats_api_key": "TS_G", "google_sheet_id": "SHEET_G"}]
        results = run_everything_for_companies(companies, base_settings=test_settings)

        assert len(results) == 1
        name, result = results[0]
        assert name == "Gamma"
        assert result.ok is True


class TestPersistCompanies:
    """persist_companies() is opt-in (Phase 4/5 fix) - the run_*_for_companies()
    wrappers must NOT call it themselves."""

    def test_run_company_snapshots_does_not_auto_persist(self, all_patched, test_settings):
        from unittest.mock import patch as mock_patch
        from app.collector import run_company_snapshots

        companies = [{"name": "Delta", "torn_api_key": "KEY_D", "google_sheet_id": "SHEET_D"}]
        with mock_patch("app.companies.save_companies") as mock_save:
            run_company_snapshots(companies, base_settings=test_settings)
            mock_save.assert_not_called()

    def test_persist_companies_calls_save(self, test_settings):
        from unittest.mock import patch as mock_patch
        from app.collector import persist_companies

        companies = [{"name": "Epsilon"}]
        with mock_patch("app.companies.save_companies") as mock_save:
            persist_companies(companies)
            mock_save.assert_called_once_with(companies)
