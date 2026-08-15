"""Tests for diagnostics export."""
from unittest.mock import MagicMock

import pytest

from custom_components.atmoce.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)
from custom_components.atmoce.const import (
    CONF_CLOUD_APP_KEY,
    CONF_CLOUD_APP_SECRET,
    CONF_CLOUD_WEB_EMAIL,
    CONF_CLOUD_WEB_PASSWORD,
    DOMAIN,
)


def _make_hass_and_entry(data: dict, options: dict | None = None):
    coordinator = MagicMock()
    coordinator.active_source = "Modbus"
    coordinator.connection_errors = 0
    coordinator.serial_number = "SN123456"
    coordinator.firmware_version = "1.0.0"
    coordinator.hw_version = 1
    coordinator.battery_model = "MS-7K-U"
    coordinator.capacity_kwh = 7.0
    coordinator.max_charge_kw = 3.75
    coordinator.max_discharge_kw = 4.5
    coordinator.data = {"battery_soc": 80, "pv_power": 1500}

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = data
    entry.options = options or {}

    hass = MagicMock()
    hass.data = {DOMAIN: {"test_entry": coordinator}}

    return hass, entry


class TestDiagnosticsRedaction:
    @pytest.mark.asyncio
    async def test_cloud_credentials_are_redacted(self):
        data = {
            "host": "192.168.1.100",
            CONF_CLOUD_APP_KEY: "my-secret-key",
            CONF_CLOUD_APP_SECRET: "my-secret-value",
        }
        hass, entry = _make_hass_and_entry(data)
        result = await async_get_config_entry_diagnostics(hass, entry)

        assert result["config_entry"][CONF_CLOUD_APP_KEY] == "**REDACTED**"
        assert result["config_entry"][CONF_CLOUD_APP_SECRET] == "**REDACTED**"

    @pytest.mark.asyncio
    async def test_web_portal_login_is_redacted(self):
        """The atmocecloud.com login must never reach a diagnostics download."""
        data = {
            "host": "192.168.1.100",
            CONF_CLOUD_WEB_EMAIL: "owner@example.com",
            CONF_CLOUD_WEB_PASSWORD: "hunter2",
        }
        hass, entry = _make_hass_and_entry(data)
        result = await async_get_config_entry_diagnostics(hass, entry)

        assert result["config_entry"][CONF_CLOUD_WEB_EMAIL] == "**REDACTED**"
        assert result["config_entry"][CONF_CLOUD_WEB_PASSWORD] == "**REDACTED**"

    @pytest.mark.asyncio
    async def test_credentials_in_options_are_redacted(self):
        """The options flow stores the same credentials as the config flow."""
        options = {
            CONF_CLOUD_APP_KEY: "opt-key",
            CONF_CLOUD_APP_SECRET: "opt-secret",
            CONF_CLOUD_WEB_EMAIL: "owner@example.com",
            CONF_CLOUD_WEB_PASSWORD: "hunter2",
        }
        hass, entry = _make_hass_and_entry({"host": "192.168.1.100"}, options)
        result = await async_get_config_entry_diagnostics(hass, entry)

        for key in options:
            assert result["options"][key] == "**REDACTED**"

    @pytest.mark.asyncio
    async def test_no_secret_value_appears_anywhere_in_output(self):
        """Catch-all: no secret should survive in any part of the payload."""
        secrets = {
            CONF_CLOUD_APP_KEY: "sk-key-aaa",
            CONF_CLOUD_APP_SECRET: "sk-secret-bbb",
            CONF_CLOUD_WEB_EMAIL: "owner@example.com",
            CONF_CLOUD_WEB_PASSWORD: "hunter2-ccc",
        }
        hass, entry = _make_hass_and_entry({"host": "192.168.1.100", **secrets}, secrets)
        result = await async_get_config_entry_diagnostics(hass, entry)

        dumped = repr(result)
        for value in secrets.values():
            assert value not in dumped

    @pytest.mark.asyncio
    async def test_every_credential_key_is_in_to_redact(self):
        """Guard against a new credential being added without redaction."""
        assert TO_REDACT == {
            CONF_CLOUD_APP_KEY,
            CONF_CLOUD_APP_SECRET,
            CONF_CLOUD_WEB_EMAIL,
            CONF_CLOUD_WEB_PASSWORD,
        }

    @pytest.mark.asyncio
    async def test_host_is_not_redacted(self):
        data = {"host": "192.168.1.100", CONF_CLOUD_APP_KEY: "key"}
        hass, entry = _make_hass_and_entry(data)
        result = await async_get_config_entry_diagnostics(hass, entry)

        assert result["config_entry"]["host"] == "192.168.1.100"

    @pytest.mark.asyncio
    async def test_missing_credentials_dont_crash(self):
        # Entry without cloud credentials
        data = {"host": "192.168.1.100"}
        hass, entry = _make_hass_and_entry(data)
        result = await async_get_config_entry_diagnostics(hass, entry)

        assert CONF_CLOUD_APP_KEY not in result["config_entry"]

    @pytest.mark.asyncio
    async def test_original_entry_data_is_not_mutated(self):
        """Redaction must copy, not overwrite the live config entry."""
        data = {"host": "192.168.1.100", CONF_CLOUD_WEB_PASSWORD: "hunter2"}
        hass, entry = _make_hass_and_entry(data)
        await async_get_config_entry_diagnostics(hass, entry)

        assert data[CONF_CLOUD_WEB_PASSWORD] == "hunter2"

    @pytest.mark.asyncio
    async def test_coordinator_info_included(self):
        data = {"host": "192.168.1.100"}
        hass, entry = _make_hass_and_entry(data)
        result = await async_get_config_entry_diagnostics(hass, entry)

        coord_info = result["coordinator"]
        assert coord_info["active_source"] == "Modbus"
        assert coord_info["serial_number"] == "SN123456"
        assert coord_info["battery_model"] == "MS-7K-U"
        assert coord_info["capacity_kwh"] == 7.0

    @pytest.mark.asyncio
    async def test_last_data_included(self):
        data = {"host": "192.168.1.100"}
        hass, entry = _make_hass_and_entry(data)
        result = await async_get_config_entry_diagnostics(hass, entry)

        assert result["last_data"]["battery_soc"] == 80
        assert result["last_data"]["pv_power"] == 1500
