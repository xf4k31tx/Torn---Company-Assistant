from collections.abc import Callable

import httpx
import pytest

from tca_web.integrations.torn.client import TornApiClient, TornApiError


def client(handler: Callable[[httpx.Request], httpx.Response]) -> TornApiClient:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url=TornApiClient.BASE_URL)
    return TornApiClient("secret-key", client=http)


@pytest.mark.asyncio
async def test_profile_uses_openapi_v2_path_and_parameters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/company/profile"
        assert request.url.params["key"] == "secret-key"
        assert request.url.params["comment"] == "torn-company-assistant"
        assert request.url.params["striptags"] == "true"
        return httpx.Response(200, json={"profile": {"name": "Test Company"}})

    response = await client(handler).get_company_profile()

    assert response.profile["name"] == "Test Company"


@pytest.mark.asyncio
async def test_api_error_never_exposes_key_or_request_url() -> None:
    api = client(
        lambda _: httpx.Response(200, json={"error": {"code": 2, "error": "Incorrect key"}})
    )

    with pytest.raises(TornApiError) as raised:
        await api.get_company_profile()

    assert raised.value.code == 2
    assert "secret-key" not in str(raised.value)
    assert "http" not in str(raised.value)


@pytest.mark.asyncio
async def test_http_error_is_sanitized_and_retryable() -> None:
    api = client(lambda _: httpx.Response(429, json={"error": "rate limited"}))

    with pytest.raises(TornApiError) as raised:
        await api.get_company_stock()

    assert raised.value.status_code == 429
    assert raised.value.retryable is True
    assert "secret-key" not in str(raised.value)


@pytest.mark.asyncio
async def test_response_must_match_openapi_envelope() -> None:
    api = client(lambda _: httpx.Response(200, json={"employees": "not-a-list"}))

    with pytest.raises(TornApiError, match="OpenAPI contract"):
        await api.get_company_employees()


@pytest.mark.asyncio
async def test_company_pagination_preserves_type_path() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        offset = int(request.url.params["offset"])
        if offset == 0:
            return httpx.Response(
                200,
                json={
                    "companies": [{"id": 1}],
                    "_metadata": {
                        "links": {
                            "next": "https://api.torn.com/v2/company/companies?limit=1&offset=1"
                        }
                    },
                },
            )
        return httpx.Response(
            200,
            json={"companies": [{"id": 2}], "_metadata": {"links": {"next": None}}},
        )

    companies = await client(handler).get_all_companies(28, page_size=1)

    assert [company["id"] for company in companies] == [1, 2]
    assert [request.url.path for request in requests] == [
        "/v2/company/28/companies",
        "/v2/company/28/companies",
    ]


@pytest.mark.parametrize(
    ("company_type_id", "offset", "limit"),
    [(0, 0, 100), (1, -1, 100), (1, 0, 0), (1, 0, 101)],
)
@pytest.mark.asyncio
async def test_company_page_validates_openapi_bounds(
    company_type_id: int, offset: int, limit: int
) -> None:
    api = client(lambda _: httpx.Response(500))

    with pytest.raises(ValueError):
        await api.get_companies(company_type_id, offset=offset, limit=limit)
