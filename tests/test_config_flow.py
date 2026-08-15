"""Tests for Atmoce config flow validation logic."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.atmoce.config_flow import AtmoceConfigFlow
from custom_components.atmoce.const import (
    CONF_BATTERY_MODEL,
    CONF_CAPACITY_KWH,
    CONF_CHARGE_KW,
    CONF_CLOUD_APP_KEY,
    CONF_CLOUD_APP_SECRET,
    CONF_CLOUD_ENABLED,
    CONF_CLOUD_WEB_EMAIL,
    CONF_CLOUD_WEB_PASSWORD,
    CONF_DISCHARGE_KW,
    CONF_SLAVE,
)
from homeassistant.const import CONF_HOST, CONF_PORT


GATEWAY_INPUT = {
    CONF_HOST: "192.168.1.100",
    CONF_PORT: 502,
    CONF_SLAVE: 1,
}

BATTERY_INPUT = {
    CONF_BATTERY_MODEL: "MS-7K-U",
}

CLOUD_INPUT_DISABLED = {
    CONF_CLOUD_ENABLED: False,
    CONF_CLOUD_APP_KEY: "",
    CONF_CLOUD_APP_SECRET: "",
}

CLOUD_INPUT_ENABLED = {
    CONF_CLOUD_ENABLED: True,
    CONF_CLOUD_APP_KEY: "mykey",
    CONF_CLOUD_APP_SECRET: "mysecret",
}


class TestFallbackStepValidation:
    """Test monitoring-fallback step validation (no network required).

    The Open API keys live in their own step, apart from the atmocecloud.com
    login, so an owner without partner keys never sees these fields.
    """

    def _make_flow(self):
        flow = AtmoceConfigFlow()
        flow._data = {
            CONF_HOST: "192.168.1.100",
            CONF_BATTERY_MODEL: "MS-7K-U",
            CONF_CAPACITY_KWH: 7.0,
            CONF_CHARGE_KW: 3.75,
            CONF_DISCHARGE_KW: 4.5,
        }
        flow.hass = MagicMock()
        flow.context = {}
        # Stub async_set_unique_id and async_create_entry
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        return flow

    @pytest.mark.asyncio
    async def test_cloud_disabled_no_credentials_ok(self):
        flow = self._make_flow()
        result = await flow.async_step_fallback(CLOUD_INPUT_DISABLED)
        flow.async_create_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_cloud_enabled_with_credentials_ok(self):
        flow = self._make_flow()
        result = await flow.async_step_fallback(CLOUD_INPUT_ENABLED)
        flow.async_create_entry.assert_called_once()

    @pytest.mark.asyncio
    async def test_cloud_enabled_missing_key_fails(self):
        flow = self._make_flow()
        result = await flow.async_step_fallback({
            CONF_CLOUD_ENABLED: True,
            CONF_CLOUD_APP_KEY: "",
            CONF_CLOUD_APP_SECRET: "secret",
        })
        # Should show form again with error, not create entry
        flow.async_create_entry.assert_not_called()
        flow.async_show_form.assert_called_once()
        _, kwargs = flow.async_show_form.call_args
        assert kwargs["errors"]["base"] == "cloud_credentials_required"

    @pytest.mark.asyncio
    async def test_cloud_enabled_missing_secret_fails(self):
        flow = self._make_flow()
        result = await flow.async_step_fallback({
            CONF_CLOUD_ENABLED: True,
            CONF_CLOUD_APP_KEY: "mykey",
            CONF_CLOUD_APP_SECRET: "",
        })
        flow.async_create_entry.assert_not_called()
        flow.async_show_form.assert_called_once()

    @pytest.mark.asyncio
    async def test_cloud_enabled_both_missing_fails(self):
        flow = self._make_flow()
        result = await flow.async_step_fallback({
            CONF_CLOUD_ENABLED: True,
            CONF_CLOUD_APP_KEY: "",
            CONF_CLOUD_APP_SECRET: "",
        })
        flow.async_create_entry.assert_not_called()


class TestCloudLoginStep:
    """The atmocecloud.com login step: no partner keys, no validation gate."""

    def _make_flow(self):
        flow = AtmoceConfigFlow()
        flow._data = {CONF_HOST: "192.168.1.100"}
        flow.hass = MagicMock()
        flow.context = {}
        flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        flow.async_step_fallback = AsyncMock(return_value={"type": "form"})
        return flow

    @pytest.mark.asyncio
    async def test_login_is_stored_and_flow_continues_to_fallback(self):
        flow = self._make_flow()
        await flow.async_step_cloud({
            CONF_CLOUD_WEB_EMAIL: "me@example.com",
            CONF_CLOUD_WEB_PASSWORD: "hunter2",
        })

        assert flow._data[CONF_CLOUD_WEB_EMAIL] == "me@example.com"
        assert flow._data[CONF_CLOUD_WEB_PASSWORD] == "hunter2"
        flow.async_step_fallback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_blank_login_is_allowed(self):
        """Skipping the login must not block setup — it only drops SOC limits."""
        flow = self._make_flow()
        await flow.async_step_cloud({
            CONF_CLOUD_WEB_EMAIL: "",
            CONF_CLOUD_WEB_PASSWORD: "",
        })

        flow.async_step_fallback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_step_offers_no_partner_key_fields(self):
        """The Open API keys belong to the next step, not this one."""
        from custom_components.atmoce.config_flow import STEP_CLOUD_SCHEMA

        fields = {str(k) for k in STEP_CLOUD_SCHEMA.schema}
        assert fields == {CONF_CLOUD_WEB_EMAIL, CONF_CLOUD_WEB_PASSWORD}


class TestGatewayStepConnectivity:
    """Test gateway step — mocking the Modbus connection."""

    def _make_flow(self):
        flow = AtmoceConfigFlow()
        flow.hass = MagicMock()
        flow.context = {}
        flow.async_set_unique_id = AsyncMock()
        flow._abort_if_unique_id_configured = MagicMock()
        flow.async_show_form = MagicMock(return_value={"type": "form"})
        return flow

    @pytest.mark.asyncio
    async def test_connection_success_proceeds_to_battery(self):
        flow = self._make_flow()
        flow.async_step_battery = AsyncMock(return_value={"type": "form", "step_id": "battery"})

        with patch(
            "custom_components.atmoce.config_flow.AtmoceModbusClient"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.async_connect = AsyncMock()
            mock_client.async_read_serial_number = AsyncMock(return_value="SN123456")
            mock_client.async_close = AsyncMock()
            mock_client_cls.return_value = mock_client

            result = await flow.async_step_user(GATEWAY_INPUT)

        flow.async_step_battery.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connection_failure_shows_error(self):
        flow = self._make_flow()

        with patch(
            "custom_components.atmoce.config_flow.AtmoceModbusClient"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.async_connect = AsyncMock(side_effect=ConnectionError("refused"))
            mock_client_cls.return_value = mock_client

            result = await flow.async_step_user(GATEWAY_INPUT)

        flow.async_show_form.assert_called_once()
        _, kwargs = flow.async_show_form.call_args
        assert kwargs["errors"]["base"] == "cannot_connect"

    @pytest.mark.asyncio
    async def test_empty_form_shows_form(self):
        flow = self._make_flow()
        result = await flow.async_step_user(None)
        flow.async_show_form.assert_called_once()
