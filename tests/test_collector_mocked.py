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
        # No prior Company_History rows seeded, so the trailing-30-day sums
        # collapse to exactly this single snapshot's daily figures.
        assert float(company_row["monthly_income"]) == pytest.approx(float(company_row["daily_income"]))
        assert float(company_row["monthly_profit"]) == pytest.approx(float(company_row["daily_profit"]))

    def test_health_score_computed(self, all_patched, mock_sheets: MockSheetsClient,
                                    test_settings, test_company):
        """Own company (id 220001, weekly income 29,750,000) ranks 7th of
        14 in the mock listings fixture (spread across 2 pages, joined via
        _metadata.links.next) - fully deterministic given the fixed mock
        data. Also covers the 10-star cohort numbers: 5 companies rated
        10.0 (ranks 1-5), own company outside that cohort, so
        income_to_reach_10_star = rank-5's weekly income (35,000,000) minus
        own weekly income (29,750,000) = 5,250,000. The current
        10-star count is refreshed and persisted on every daily snapshot."""
        from app.collector import Collector

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is True
        row = mock_sheets._tabs["Company_History"][0]
        assert row["rank_by_income"] == "7"
        assert row["rank_total_in_type"] == "14"
        assert float(row["rank_percentile"]) == pytest.approx((14 - 7 + 1) / 14 * 100, abs=0.1)
        assert collector.company["last_rank"] == 7  # persisted onto the company dict in-place

        assert row["star_10_count"] == "5"
        assert float(row["income_to_reach_10_star"]) == pytest.approx(5250000)
        assert float(row["income_buffer_before_9_star"]) == pytest.approx(5750000)
        assert float(row["income_to_reach_next_star"]) == pytest.approx(5250000)
        assert float(row["required_weekly_income_to_star_up"]) == pytest.approx(35000000)
        assert float(row["income_to_drop_to_previous_star"]) == pytest.approx(5750000)
        assert collector.company["star_10_count"] == 5

        # Full same-type listing persisted to its own current-state tab, not
        # just the 4-ish scalar Company_History fields.
        assert "Company_Rankings" in mock_sheets._tabs
        ranking_rows = mock_sheets._tabs["Company_Rankings"]
        assert len(ranking_rows) == 14
        assert ranking_rows[0]["rank"] == "1"
        assert ranking_rows[0]["name"] == "Titan Oil"
        own_row = next(r for r in ranking_rows if r["is_own_company"] == "True")
        assert own_row["rank"] == "7"
        assert own_row["name"] == "Knotty Oil Co"
        assert own_row["weekly_income"] == "29750000"
        assert own_row["daily_income"] == "4250000"

    def test_health_score_pagination_follows_next_link(self, all_patched, mock_sheets: MockSheetsClient,
                                                         test_settings, test_company, mock_torn):
        """Confirms all 14 companies are actually returned when the fixture
        forces multiple pages (page_size=9, splitting into 9 + 5) - and,
        critically, that pagination goes through get_company_listings()
        again with a reissued offset rather than GETting Torn's own `next`
        link directly, since that link has a confirmed live bug (missing
        the /{type_id} path segment - see
        TornAPI.get_all_company_listings' docstring). fetch_url must NOT be
        called at all here."""
        companies = mock_torn.get_all_company_listings(12, page_size=9)

        assert len(companies) == 14  # both pages merged
        assert {c["id"] for c in companies} == {
            220101, 220102, 220103, 220104, 220105, 220106, 220001, 220107,
            220108, 220109, 220110, 220111, 220112, 220100,
        }
        listing_calls = [c for c in mock_torn.calls if c.method == "get_company_listings"]
        assert len(listing_calls) == 2
        assert listing_calls[0].args == (12, 0, 9)  # company_type_id, offset, limit
        assert listing_calls[1].args == (12, 9, 9)  # offset correctly reissued, not GETting next's own path
        fetch_url_calls = [c for c in mock_torn.calls if c.method == "fetch_url"]
        assert fetch_url_calls == []  # the buggy next link must never be GETted directly

    def test_star_10_count_refreshes_on_daily_snapshot(
        self, all_patched, mock_sheets: MockSheetsClient,
        test_settings, test_company, mock_torn,
    ):
        """Every daily snapshot refreshes the count from the live listing."""
        from app.collector import Collector

        test_company["star_10_count"] = 3

        collector = Collector(test_company, base_settings=test_settings)
        collector.run_snapshot()

        row = mock_sheets._tabs["Company_History"][0]
        assert row["star_10_count"] == "5"
        assert collector.company["star_10_count"] == 5

    def test_star_10_count_freshly_captured_on_sunday_reset_snapshot(
        self, all_patched, mock_sheets: MockSheetsClient, test_settings, test_company, mock_torn,
    ):
        """Sunday snapshots also refresh and persist the live count."""
        from app.collector import Collector

        test_company["star_10_count"] = 1  # stale prior value - must be overwritten
        import datetime
        sunday_reset_ts = int(datetime.datetime(2026, 8, 2, 19, 0, tzinfo=datetime.timezone.utc).timestamp())
        mock_torn._data["get_company_timestamp_v2"]["response"]["timestamp"] = sunday_reset_ts

        collector = Collector(test_company, base_settings=test_settings)
        collector.run_snapshot()

        row = mock_sheets._tabs["Company_History"][0]
        assert row["star_10_count"] == "5"  # freshly counted from the listing
        assert collector.company["star_10_count"] == 5  # persisted, overriding the stale 1

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

    def test_monthly_income_and_profit_accumulate_across_prior_snapshots(self, all_patched,
                                                                          mock_sheets: MockSheetsClient,
                                                                          mock_torn: MockTornAPI,
                                                                          test_settings, test_company):
        """monthly_income/monthly_profit must SUM this snapshot's daily
        figures with prior Company_History rows falling within the trailing
        30 days - not just reflect the current snapshot alone."""
        from app.collector import Collector

        mock_ts = mock_torn.get_company_timestamp_v2()["timestamp"]
        prior_ts = mock_ts - 5 * 86400  # 5 days earlier: within the 30-day window, a different 18:00-UTC period
        mock_sheets.seed_tab("Company_History", [{
            "timestamp": str(prior_ts), "name": "Knotty Oil Co",
            "daily_income": "500000", "daily_profit": "100000",
        }])

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is True
        assert len(mock_sheets._tabs["Company_History"]) == 2  # new row appended, not deduped
        new_row = mock_sheets._tabs["Company_History"][0]  # newest-first insert order
        assert float(new_row["monthly_income"]) == pytest.approx(float(new_row["daily_income"]) + 500000)
        assert float(new_row["monthly_profit"]) == pytest.approx(float(new_row["daily_profit"]) + 100000)

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

    The fixture has no position capacities, so priority assignment fills
    every employee into the first alphabetical position, Accountant.
    Misplaced therefore means current_position != assigned_position:
    FinanceGuru is correctly placed and the other four are misplaced.
    """

    def test_successful_run(self, all_patched, mock_torn: MockTornAPI,
                             mock_sheets: MockSheetsClient, test_settings, test_company):
        from app.collector import Collector

        collector = Collector(test_company, base_settings=test_settings)
        result = collector.run_employee_efficiency()

        assert result.ok is True
        assert result.employee_count == 5
        assert result.misplaced_count == 4
        assert "Employee_Effectiveness" in mock_sheets._tabs
        assert "Position_Efficiency" in mock_sheets._tabs
        assert "Total_Effectiveness_Projections" in mock_sheets._tabs
        assert len(mock_sheets._tabs["Employee_Effectiveness"]) == 5

        director_row = next(r for r in mock_sheets._tabs["Employee_Effectiveness"] if r["name"] == "JohnKnot")
        assert director_row["misplaced_flag"] == "True"
        torn_director = next(
            employee for employee in mock_torn.get_company_employees()["employees"]
            if employee["name"] == "JohnKnot"
        )
        assert float(director_row["effectiveness_working_stats"]) == pytest.approx(
            torn_director["effectiveness"]["working_stats"]
        )
        assert float(director_row["projected_efficiency_current_position"]) == pytest.approx(94.2)

        position_row = next(
            r for r in mock_sheets._tabs["Position_Efficiency"] if r["name"] == "JohnKnot"
        )
        assert float(position_row["Director"]) == pytest.approx(94.2)
        assert float(position_row["Director"]) != float(director_row["effectiveness_working_stats"])

        # Total Effectiveness Projections: same base 94.2 plus this employee's
        # non-work-stats delta (effectiveness_total - effectiveness_working_stats).
        total_row = next(
            r for r in mock_sheets._tabs["Total_Effectiveness_Projections"] if r["name"] == "JohnKnot"
        )
        expected_delta = float(director_row["effectiveness_total"]) - float(director_row["effectiveness_working_stats"])
        assert float(total_row["Director"]) == pytest.approx(94.2 + expected_delta)

        courier_row = next(r for r in mock_sheets._tabs["Employee_Effectiveness"] if r["name"] == "OilHand42")
        assert courier_row["misplaced_flag"] == "True"

        accountant_row = next(
            r for r in mock_sheets._tabs["Employee_Effectiveness"] if r["name"] == "FinanceGuru"
        )
        assert accountant_row["assigned_position"] == "Accountant"
        assert accountant_row["misplaced_flag"] == "False"

    def test_misplaced_uses_assigned_position_not_best_fit(self):
        from app.collector import is_employee_misplaced

        assert is_employee_misplaced({
            "current_position": "Oil Courier",
            "assigned_position": "Oil Courier",
            "best_fit_position": "Director",
        }) is False
        assert is_employee_misplaced({
            "current_position": "Oil Courier",
            "assigned_position": "Accountant",
            "best_fit_position": "Oil Courier",
        }) is True
        assert is_employee_misplaced({
            "current_position": "Oil Courier",
            "assigned_position": "",
            "best_fit_position": "Director",
        }) is False

    def test_employee_table_defaults_use_tornstats_projected_current_position_effectiveness(self):
        from gui.main_window import EMPLOYEE_TABLE_COLUMNS, DEFAULT_VISIBLE_EMPLOYEE_COLUMNS

        labels = {key: label for label, key in EMPLOYEE_TABLE_COLUMNS}
        assert labels["projected_efficiency_current_position"] == "Current\nEff."
        assert labels["effectiveness_working_stats"] == "Work Stats\nEff."
        assert "projected_efficiency_current_position" in DEFAULT_VISIBLE_EMPLOYEE_COLUMNS
        assert "effectiveness_working_stats" not in DEFAULT_VISIBLE_EMPLOYEE_COLUMNS

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

    def test_locked_employee_uses_current_position_with_tornstats_efficiency(
        self, all_patched, mock_sheets: MockSheetsClient, test_settings, test_company
    ):
        from app.collector import Collector

        test_company["position_capacities"] = {
            "Director": 1,
            "Oil Courier": 2,
            "Accountant": 1,
            "Trainer": 1,
        }
        test_company["position_priority_order"] = [
            "Director", "Accountant", "Oil Courier", "Trainer"
        ]
        test_company["locked_employee_ids"] = ["220002"]

        result = Collector(test_company, base_settings=test_settings).run_employee_efficiency()

        assert result.ok is True
        locked_row = next(
            row for row in mock_sheets._tabs["Employee_Effectiveness"]
            if row["tId"] == "220002"
        )
        assert locked_row["assigned_position"] == locked_row["current_position"] == "Oil Courier"
        assert float(locked_row["assigned_efficiency"]) == float(
            locked_row["projected_efficiency_current_position"]
        )
        assert locked_row["misplaced_flag"] == "False"


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


def test_snapshot_writes_daily_income_history_and_star_summary(
    all_patched, mock_sheets, test_settings, test_company,
):
    from app.collector import Collector

    result = Collector(test_company, base_settings=test_settings).run_snapshot()

    assert result.ok is True
    history = mock_sheets.get_tab("Company_Income_History")
    assert len(history) == 14
    assert len({(row["company_id"], row["period_start"]) for row in history}) == 14
    summary = mock_sheets.get_tab("Star_Income_Summary")
    assert summary
    ten_star = next(row for row in summary if row["stars"] == "10")
    assert ten_star["total_count"] == "5"
    assert ten_star["eligible_count"] == "5"
    assert ten_star["coverage"] == "5/5"
    assert float(ten_star["minimum"]) > 0
    assert float(ten_star["p10"]) > 0
    assert float(ten_star["median"]) > 0
    assert float(ten_star["p90"]) > 0
    assert float(ten_star["maximum"]) > 0


def test_daily_income_run_avoids_employee_and_stock_endpoints(
    all_patched, mock_sheets, mock_torn, test_settings, test_company,
):
    from app.collector import Collector

    result = Collector(test_company, base_settings=test_settings).run_daily_income()

    assert result.ok is True
    called = {call.method for call in mock_torn.calls}
    assert "get_company_profile_v2" in called
    assert "get_company_timestamp_v2" in called
    assert "get_company_listings" in called
    assert "get_company_employees" not in called
    assert "get_company_stock_v2" not in called
    assert "Company_Income_History" in mock_sheets._tabs
    assert "Star_Income_Summary" in mock_sheets._tabs
