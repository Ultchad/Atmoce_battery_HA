"""Diagnostics support for Atmoce Battery."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CLOUD_APP_KEY,
    CONF_CLOUD_APP_SECRET,
    CONF_CLOUD_WEB_EMAIL,
    CONF_CLOUD_WEB_PASSWORD,
    DOMAIN,
)
from .coordinator import AtmoceCoordinator

# Credentials that must never appear in a diagnostics download — these files are
# routinely attached to public GitHub issues.
TO_REDACT = {
    CONF_CLOUD_APP_KEY,
    CONF_CLOUD_APP_SECRET,
    CONF_CLOUD_WEB_EMAIL,
    CONF_CLOUD_WEB_PASSWORD,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: AtmoceCoordinator = hass.data[DOMAIN][entry.entry_id]

    return {
        # The options flow stores the same credentials as the initial config
        # flow, so both mappings need redacting.
        "config_entry": async_redact_data(entry.data, TO_REDACT),
        "options": async_redact_data(entry.options or {}, TO_REDACT),
        "coordinator": {
            "active_source": coordinator.active_source,
            "connection_errors": coordinator.connection_errors,
            "serial_number": coordinator.serial_number,
            "firmware_version": coordinator.firmware_version,
            "hw_version": coordinator.hw_version,
            "battery_model": coordinator.battery_model,
            "battery_count": coordinator.battery_count,
            "capacity_kwh": coordinator.capacity_kwh,
            "max_charge_kw": coordinator.max_charge_kw,
            "max_discharge_kw": coordinator.max_discharge_kw,
        },
        "last_data": coordinator.data,
    }
