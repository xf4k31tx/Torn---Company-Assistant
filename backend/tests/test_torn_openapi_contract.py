import json
from pathlib import Path
from typing import Any

SPEC_PATH = Path(__file__).parents[2] / "docs" / "planning" / "openapi.json"

EXPECTED_OPERATIONS = {
    "/company/profile": ("getMyCompanyProfile", "CompanyProfileResponseMixed"),
    "/company/employees": ("getMyCompanyEmployees", "CompanyEmployeesResponse"),
    "/company/stock": ("getMyCompanyStock", "CompanyStockResponse"),
    "/company/timestamp": ("getCompanyTimestamp", "TimestampResponse"),
    "/company/{typeId}/companies": ("getCompaniesList", "CompaniesResponse"),
    "/key/info": ("getKeyInfo", "KeyInfoResponse"),
}


def load_spec() -> dict[str, Any]:
    with SPEC_PATH.open(encoding="utf-8") as source:
        return json.load(source)


def test_required_torn_routes_match_master_openapi_contract() -> None:
    spec = load_spec()

    assert spec["openapi"] == "3.1.0"
    assert spec["servers"][0]["url"] == "https://api.torn.com/v2"
    for path, (operation_id, response_name) in EXPECTED_OPERATIONS.items():
        operation = spec["paths"][path]["get"]
        response = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert operation["operationId"] == operation_id
        assert response["$ref"] == f"#/components/schemas/{response_name}"


def test_company_listing_bounds_match_client_validation() -> None:
    spec = load_spec()
    operation = spec["paths"]["/company/{typeId}/companies"]["get"]
    resolved = []
    for parameter in operation["parameters"]:
        reference = parameter.get("$ref")
        if reference:
            parameter = spec["components"]["parameters"][reference.rsplit("/", 1)[-1]]
        resolved.append(parameter)
    parameters = {parameter["name"]: parameter for parameter in resolved}

    assert parameters["typeId"]["required"] is True
    assert parameters["limit"]["schema"]["minimum"] == 1
    assert parameters["limit"]["schema"]["maximum"] == 100
    assert parameters["offset"]["schema"]["minimum"] == 0
