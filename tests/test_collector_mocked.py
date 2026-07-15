"""Example tests using the mock clients.

Run with:  python -m pytest tests/test_collector_mocked.py -v
"""

from __future__ import annotations

import pytest

from tests.mock_client import MockSheetsClient, MockTornAPI, MockTornStatsAPI


class TestCollectorSnapshot:
    """Verify the Collector flow using fully mocked external APIs."""

    def test_successful_snapshot(self, all_patched, mock_torn: MockTornAPI,
                                 mock_sheets: MockSheetsClient, test_settings):
        from app.collector import Collector

        collector = Collector(settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is True
        assert result.company_name == "Knotty Oil Co"
        assert result.employee_count == 5
        assert result.stock_count == 4
        assert mock_torn.calls[0].method == "get_company"
        assert "Company_History" in mock_sheets._tabs
        assert "Employees" in mock_sheets._tabs
        assert "Stock_History" in mock_sheets._tabs

    def test_duplicate_24h_period_skips_append(self, all_patched,
                                                mock_sheets: MockSheetsClient,
                                                mock_torn: MockTornAPI,
                                                test_settings):
        from app.collector import Collector

        company_data = mock_torn.get_company()
        ts = company_data["timestamp"]
        mock_sheets.seed_tab("Company_History", [{"timestamp": str(ts), "name": "Knotty Oil Co"}])

        collector = Collector(settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is True
        assert result.is_update is True

    def test_missing_torn_key_returns_error(self, test_settings):
        from app.collector import Collector

        test_settings.torn_api_key = ""
        collector = Collector(settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is False
        assert "Torn API key" in result.message

    def test_torn_api_rate_limit_error(self, all_patched, mock_torn: MockTornAPI,
                                       test_settings):
        from app.collector import Collector

        mock_torn.inject_error("get_company", "rate_limited")
        collector = Collector(settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is False
        assert "rate limited" in result.message.lower()

    def test_torn_api_bad_key_error(self, all_patched, mock_torn: MockTornAPI,
                                    test_settings):
        from app.collector import Collector

        mock_torn.inject_error("get_company", "incorrect_key")
        collector = Collector(settings=test_settings)
        result = collector.run_snapshot()

        assert result.ok is False
        assert "Incorrect key" in result.message

    def test_multi_company_snapshot(self, all_patched, mock_sheets: MockSheetsClient,
                                    test_settings):
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

    def test_company_missing_sheet_id(self, all_patched, test_settings):
        from app.collector import run_company_snapshots

        companies = [{"name": "Broken", "torn_api_key": "KEY", "google_sheet_id": ""}]
        results = run_company_snapshots(companies, base_settings=test_settings)

        assert results[0][1].ok is False
        assert "Sheet ID" in results[0][1].message
