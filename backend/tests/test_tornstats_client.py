import httpx
import pytest

from tca_web.integrations.tornstats.client import TornStatsApiClient, TornStatsApiError


@pytest.mark.asyncio
async def test_efficiency_uses_expected_stats_and_returns_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert dict(request.url.params) == {"man": "1", "int": "2", "end": "3"}
        assert request.url.path.endswith("/v2/secret/efficiency")
        return httpx.Response(200, json={"status": True, "12": {"company": "Oil", "Director": 99}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    api = TornStatsApiClient("secret", client=client)
    result = await api.get_efficiency(1, 2, 3)
    assert result["12"]["Director"] == 99
    await client.aclose()


@pytest.mark.asyncio
async def test_error_does_not_expose_api_key() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="failure")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    api = TornStatsApiClient("super-secret", client=client)
    with pytest.raises(TornStatsApiError) as error:
        await api.get_efficiency()
    assert "super-secret" not in str(error.value)
    assert error.value.retryable
    await client.aclose()
