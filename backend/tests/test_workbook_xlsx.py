from io import BytesIO

import pytest
from openpyxl import Workbook

from tca_web.integrations.workbook.xlsx import (
    WorkbookValidationError,
    export_workbook,
    parse_workbook,
)


def test_workbook_round_trip_preserves_sheets_and_values() -> None:
    records = [
        {"_sheet": "Company_History", "timestamp": 1, "daily_income": 10.5},
        {"_sheet": "Employees", "tId": "123", "name": "Employee"},
    ]

    content = export_workbook(records, workspace_id="local", company_id=12)
    parsed = parse_workbook(content)

    assert parsed == records


def test_import_rejects_formula_cells() -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "History"
    sheet.append(["value"])
    sheet.append(["=1+1"])
    output = BytesIO()
    workbook.save(output)
    workbook.close()

    with pytest.raises(WorkbookValidationError, match="contains a formula"):
        parse_workbook(output.getvalue())


def test_import_rejects_invalid_content() -> None:
    with pytest.raises(WorkbookValidationError, match="not a valid"):
        parse_workbook(b"not a workbook")
