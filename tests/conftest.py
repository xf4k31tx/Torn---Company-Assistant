from __future__ import annotations

from unittest.mock import patch

import pytest

from tests.mock_client import MockSheetsClient, MockTornAPI, MockTornStatsAPI


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
# Convenience: a ready-to-use Settings object with test values.
# ---------------------------------------------------------------------------

@pytest.fixture
def test_settings():
    """Return a Settings dataclass populated with fields that point the
    Collector at our mock clients (the fields aren't actually used when
    clients are patched, but having real-looking values avoids confusing
    validation failures)."""
    from app.config import Settings
    return Settings(
        torn_api_key="TEST_TORN_KEY",
        tornstats_api_key="TEST_TS_KEY",
        google_sheet_id="TEST_SHEET_ID",
        google_sheet_name="Test Sheet",
    )


# ---------------------------------------------------------------------------
# Patch the three client classes so the app code uses our mocks.
# Each patched call returns the fixture instance from the corresponding
# autouse fixture below.
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
    with patch("app.collector.SheetsClient", return_value=mock_sheets):
        yield


@pytest.fixture
def all_patched(patch_torn, patch_tornstats, patch_sheets):
    """Convenience: activate all three patches at once."""
    yield
