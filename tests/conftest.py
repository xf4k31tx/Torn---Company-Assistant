from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.mock_client import MockSheetsClient, MockTornAPI, MockTornStatsAPI


# ---------------------------------------------------------------------------
# Safety net: NO test may ever write to the real DPAPI-encrypted companies
# store, no matter what it calls. This is autouse (applies to every test in
# this whole tests/ package) and function-scoped (fresh patch per test).
#
# This exists because of a real, live incident during development: before
# app.collector's run_*_for_companies() helpers made persistence an
# explicit, opt-in step (app.collector.persist_companies()), a test using a
# throwaway/fake companies list caused a pytest run to silently overwrite
# the real production company records (real API keys, Sheet IDs, position
# config) with that test's fixture data. persist_companies() being opt-in
# everywhere now makes that specific failure mode structurally impossible,
# but this fixture is a second, independent layer of protection: even a
# future test/helper that calls app.companies.save_companies() directly,
# by mistake or otherwise, hits this mock instead of the real DPAPI store.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def block_real_companies_persistence():
    with patch("app.companies.save_companies") as mock_save:
        yield mock_save


# ---------------------------------------------------------------------------
# Fixtures: brand-new mock instances per test
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_torn() -> MockTornAPI:
    return MockTornAPI(api_key="TEST_TORN_KEY")


@pytest.fixture
def mock_tornstats() -> MockTornStatsAPI:
    return MockTornStatsAPI(api_key="TEST_TS_KEY")


@pytest.fixture
def mock_sheets() -> MockSheetsClient:
    return MockSheetsClient(sheet_id="TEST_SHEET_ID")


# ---------------------------------------------------------------------------
# Convenience: a ready-to-use Settings object with test values, used as the
# Collector's base_settings fallback (company dicts still take priority -
# see app/collector.py's _torn_key()/_tornstats_key()).
# ---------------------------------------------------------------------------

@pytest.fixture
def test_settings():
    from app.config import Settings
    return Settings(
        torn_api_key="TEST_TORN_KEY",
        tornstats_api_key="TEST_TS_KEY",
        google_sheet_id="TEST_SHEET_ID",
        google_sheet_name="Test Sheet",
    )


@pytest.fixture
def test_company():
    """A ready-to-use company dict matching the mock Torn/Tornstats data's
    "Knotty Oil Co" fixture (5 employees, positions Director/Oil Courier x2/
    Accountant/Trainer - matching the tornstats mock's "12" efficiency
    block so find_company_type_block() actually matches in tests)."""
    return {
        "name": "Knotty Oil Co",
        "torn_api_key": "TEST_TORN_KEY",
        "tornstats_api_key": "TEST_TS_KEY",
        "google_sheet_id": "TEST_SHEET_ID",
        "google_sheet_name": "Test Sheet",
    }


# ---------------------------------------------------------------------------
# Patch the three client classes so the app code uses our mocks.
# ---------------------------------------------------------------------------

@pytest.fixture
def patch_torn(mock_torn: MockTornAPI):
    with patch("app.collector.TornAPI", return_value=mock_torn):
        yield


@pytest.fixture
def patch_tornstats(mock_tornstats: MockTornStatsAPI):
    with patch("app.collector.TornStatsAPI", return_value=mock_tornstats):
        yield


@pytest.fixture
def patch_sheets(mock_sheets: MockSheetsClient):
    """Real SheetsClient objects are obtained via the get_or_create()
    classmethod (Phase 4/5), not by constructing SheetsClient(...) directly
    - so this patches that classmethod (matching its real 3-tuple return:
    (client, resolved_sheet_id, was_created)) rather than the class
    constructor. Always reports was_created=False and echoes back
    mock_sheets.sheet_id, regardless of what sheet_id/company_name/
    sheet_name the collector passed in - tests that specifically care about
    the auto-create path patch this differently themselves (see
    test_company_blank_sheet_id_auto_creates)."""
    with patch("app.collector.SheetsClient.get_or_create",
               return_value=(mock_sheets, mock_sheets.sheet_id, False)):
        yield


@pytest.fixture
def all_patched(patch_torn, patch_tornstats, patch_sheets):
    """Convenience: activate all three patches at once."""
    yield
