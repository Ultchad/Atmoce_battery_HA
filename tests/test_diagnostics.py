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


class TestStorageModelDump:
    """The raw portal model is what tells us which settings exist."""

    @pytest.mark.asyncio
    async def test_model_is_included(self):
        hass, entry = _make_hass_and_entry({"host": "192.168.1.100"})
        hass.data[DOMAIN]["test_entry"].web_model = {
            "workModel": 1,
            "gridCharge": 0,
            "storageChargeCutoffSoc": 90,
        }

        result = await async_get_config_entry_diagnostics(hass, entry)

        assert result["storage_model"]["workModel"] == 1
        assert result["storage_model"]["gridCharge"] == 0

    @pytest.mark.asyncio
    async def test_identifying_fields_are_redacted(self):
        """Diagnostics get attached to public issues."""
        hass, entry = _make_hass_and_entry({"host": "192.168.1.100"})
        hass.data[DOMAIN]["test_entry"].web_model = {
            "workModel": 1,
            "stationName": "Casa de Pablo",
            "ownerMail": "me@example.com",
            "latitude": 40.41,
            "nested": {"userPhone": "600000000", "gridCharge": 1},
        }

        result = await async_get_config_entry_diagnostics(hass, entry)
        model = result["storage_model"]

        assert model["stationName"] == "**REDACTED**"
        assert model["ownerMail"] == "**REDACTED**"
        assert model["latitude"] == "**REDACTED**"
        assert model["nested"]["userPhone"] == "**REDACTED**"
        # Settings still come through, including inside nested objects.
        assert model["workModel"] == 1
        assert model["nested"]["gridCharge"] == 1

    @pytest.mark.asyncio
    async def test_empty_without_a_portal_login(self):
        hass, entry = _make_hass_and_entry({"host": "192.168.1.100"})
        hass.data[DOMAIN]["test_entry"].web_model = {}

        result = await async_get_config_entry_diagnostics(hass, entry)

        assert result["storage_model"] == {}


class TestCredentialsStoredOnce:
    """Credentials must live in entry.data only — never a second copy in options."""

    @pytest.mark.asyncio
    async def test_migration_moves_credentials_out_of_options(self):
        from custom_components.atmoce import async_migrate_entry

        entry = MagicMock()
        entry.version = 1
        entry.data = {"host": "192.168.1.100", CONF_CLOUD_WEB_PASSWORD: "old-pw"}
        entry.options = {
            "modbus_retry_count": 5,
            CONF_CLOUD_WEB_EMAIL: "me@example.com",
            CONF_CLOUD_WEB_PASSWORD: "new-pw",
        }
        hass = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()

        assert await async_migrate_entry(hass, entry) is True

        kwargs = hass.config_entries.async_update_entry.call_args.kwargs
        # Secret consolidated into data, with the newer options value winning.
        assert kwargs["data"][CONF_CLOUD_WEB_PASSWORD] == "new-pw"
        assert kwargs["data"][CONF_CLOUD_WEB_EMAIL] == "me@example.com"
        # ...and gone from options, so it is no longer stored twice.
        assert CONF_CLOUD_WEB_PASSWORD not in kwargs["options"]
        assert CONF_CLOUD_WEB_EMAIL not in kwargs["options"]
        # Genuine tunables stay put.
        assert kwargs["options"]["modbus_retry_count"] == 5
        assert kwargs["version"] == 2

    @pytest.mark.asyncio
    async def test_migration_keeps_real_credential_over_blank_option(self):
        from custom_components.atmoce import async_migrate_entry

        entry = MagicMock()
        entry.version = 1
        entry.data = {CONF_CLOUD_WEB_PASSWORD: "real-pw"}
        entry.options = {CONF_CLOUD_WEB_PASSWORD: ""}
        hass = MagicMock()
        hass.config_entries.async_update_entry = MagicMock()

        await async_migrate_entry(hass, entry)

        kwargs = hass.config_entries.async_update_entry.call_args.kwargs
        assert kwargs["data"][CONF_CLOUD_WEB_PASSWORD] == "real-pw"
        assert CONF_CLOUD_WEB_PASSWORD not in kwargs["options"]
