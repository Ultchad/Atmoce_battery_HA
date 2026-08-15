"""Tests for AtmoceCloudClient."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.atmoce.cloud_client import (
    AtmoceCloudAuthError,
    AtmoceCloudClient,
    AtmoceCloudError,
)


def _mock_response(json_data: dict, status: int = 200) -> MagicMock:
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    return resp


def _mock_session(responses: list) -> MagicMock:
    """Build a context-manager mock that returns responses in order."""
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.post = AsyncMock(side_effect=responses[:1])
    session.get = AsyncMock(side_effect=responses[1:] if len(responses) > 1 else responses)
    return session


AUTH_OK = {
    "success": True,
    "data": {"access_token": "test-token-abc"},
}

SITE_DATA_OK = {
    "success": True,
    "data": [{
        "gridPower": 500,
        "solarGenerationPower": 2000,
        "dailySolarGeneration": 8.5,
        "lifetimeSolarGeneration": 1200.0,
        "dailyFromGrid": 1.2,
        "lifetimeFromGrid": 300.0,
        "dailyToGrid": 3.1,
        "lifetimeToGrid": 500.0,
        "batterySOC": 75,
        "batteryPower": -800,
        "batteryStatus": 1,
        "dailyBatteryCharging": 4.0,
        "dailyBatteryDischarge": 2.5,
        "lifetimeBatteryCharging": 900.0,
        "lifetimeBatteryDischarge": 850.0,
    }],
}


class TestAuthentication:
    @pytest.mark.asyncio
    async def test_authenticate_sets_token(self):
        client = AtmoceCloudClient("key", "secret")
        auth_resp = _mock_response(AUTH_OK)

        with patch("aiohttp.ClientSession") as mock_cls:
            session = MagicMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=False)
            session.post = AsyncMock(return_value=auth_resp)
            auth_resp.__aenter__ = AsyncMock(return_value=auth_resp)
            auth_resp.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = session

            await client._async_authenticate()

        assert client._access_token == "test-token-abc"

    @pytest.mark.asyncio
    async def test_authenticate_raises_on_failure(self):
        client = AtmoceCloudClient("bad", "creds")
        fail_resp = _mock_response({"success": False, "reason": "invalid credentials"})

        with patch("aiohttp.ClientSession") as mock_cls:
            session = MagicMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=False)
            fail_resp.__aenter__ = AsyncMock(return_value=fail_resp)
            fail_resp.__aexit__ = AsyncMock(return_value=False)
            session.post = AsyncMock(return_value=fail_resp)
            mock_cls.return_value = session

            with pytest.raises(AtmoceCloudAuthError, match="Cloud auth failed"):
                await client._async_authenticate()


class TestFetchSiteData:
    @pytest.mark.asyncio
    async def test_fetch_maps_fields_correctly(self):
        client = AtmoceCloudClient("key", "secret")
        client._access_token = "test-token"

        site_resp = _mock_response(SITE_DATA_OK)

        with patch("aiohttp.ClientSession") as mock_cls:
            session = MagicMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=False)
            site_resp.__aenter__ = AsyncMock(return_value=site_resp)
            site_resp.__aexit__ = AsyncMock(return_value=False)
            session.get = AsyncMock(return_value=site_resp)
            mock_cls.return_value = session

            data = await client.async_fetch_site_data("SN123")

        assert data["pv_power"] == 2000
        assert data["battery_soc"] == 75
        assert data["grid_power"] == 500
        assert data["battery_power"] == -800

    @pytest.mark.asyncio
    async def test_fetch_returns_none_for_unavailable_fields(self):
        client = AtmoceCloudClient("key", "secret")
        client._access_token = "test-token"

        site_resp = _mock_response(SITE_DATA_OK)

        with patch("aiohttp.ClientSession") as mock_cls:
            session = MagicMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=False)
            site_resp.__aenter__ = AsyncMock(return_value=site_resp)
            site_resp.__aexit__ = AsyncMock(return_value=False)
            session.get = AsyncMock(return_value=site_resp)
            mock_cls.return_value = session

            data = await client.async_fetch_site_data("SN123")

        # These fields are not available from Cloud API
        assert data["grid_voltage"] is None
        assert data["grid_current"] is None
        assert data["comm_control_mode"] is None
        assert data["forced_cmd"] is None

def _patched_session(get_responses: list, post_responses: list | None = None):
    """Patch aiohttp.ClientSession with ordered GET/POST responses.

    Returns (context_manager, session) so tests can assert on call counts.
    """
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)

    for resp in [*get_responses, *(post_responses or [])]:
        resp.__aenter__ = AsyncMock(return_value=resp)
        resp.__aexit__ = AsyncMock(return_value=False)

    session.get = AsyncMock(side_effect=list(get_responses))
    session.post = AsyncMock(side_effect=list(post_responses or []))

    patcher = patch("aiohttp.ClientSession", return_value=session)
    return patcher, session


class TestTokenExpiry:
    """A cached token that the portal has expired must not wedge the client."""

    @pytest.mark.asyncio
    async def test_expired_token_is_refreshed_and_fetch_retried(self):
        client = AtmoceCloudClient("key", "secret")
        client._access_token = "stale-token"

        rejected = _mock_response({"success": False, "reason": "token expired"})
        ok = _mock_response(SITE_DATA_OK)
        auth = _mock_response(AUTH_OK)

        patcher, session = _patched_session([rejected, ok], [auth])
        with patcher:
            data = await client.async_fetch_site_data("SN123")

        # Re-authenticated once and re-issued the fetch, rather than giving up.
        assert session.post.await_count == 1
        assert session.get.await_count == 2
        assert client._access_token == "test-token-abc"
        assert data["battery_soc"] == 75

    @pytest.mark.asyncio
    async def test_retry_happens_only_once(self):
        """A persistently failing endpoint must not loop."""
        client = AtmoceCloudClient("key", "secret")
        client._access_token = "stale-token"

        rejected = _mock_response({"success": False, "reason": "site not found"})
        rejected2 = _mock_response({"success": False, "reason": "site not found"})
        auth = _mock_response(AUTH_OK)

        patcher, session = _patched_session([rejected, rejected2], [auth])
        with patcher:
            with pytest.raises(AtmoceCloudError):
                await client.async_fetch_site_data("SN123")

        assert session.get.await_count == 2
        assert session.post.await_count == 1

    @pytest.mark.asyncio
    async def test_no_retry_when_there_was_no_token(self):
        """A cold client that fails auth should surface it, not retry blindly."""
        client = AtmoceCloudClient("bad", "creds")

        auth_fail = _mock_response({"success": False, "reason": "invalid credentials"})

        patcher, session = _patched_session([], [auth_fail])
        with patcher:
            with pytest.raises(AtmoceCloudAuthError):
                await client.async_fetch_site_data("SN123")

        assert session.post.await_count == 1
        assert session.get.await_count == 0


class TestFetchErrors:
    @pytest.mark.asyncio
    async def test_fetch_raises_on_api_error(self):
        client = AtmoceCloudClient("key", "secret")
        client._access_token = "test-token"

        fail1 = _mock_response({"success": False, "reason": "site not found"})
        fail2 = _mock_response({"success": False, "reason": "site not found"})
        auth = _mock_response(AUTH_OK)

        patcher, _ = _patched_session([fail1, fail2], [auth])
        with patcher:
            with pytest.raises(AtmoceCloudError, match="Cloud data fetch failed"):
                await client.async_fetch_site_data("SN123")

    @pytest.mark.asyncio
    async def test_fetch_raises_on_empty_data(self):
        client = AtmoceCloudClient("key", "secret")
        client._access_token = "test-token"

        empty1 = _mock_response({"success": True, "data": []})
        empty2 = _mock_response({"success": True, "data": []})
        auth = _mock_response(AUTH_OK)

        patcher, _ = _patched_session([empty1, empty2], [auth])
        with patcher:
            with pytest.raises(AtmoceCloudError):
                await client.async_fetch_site_data("SN123")
