"""Atmoce Battery integration for Home Assistant."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CREDENTIAL_KEYS, DOMAIN
from .coordinator import AtmoceCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old config entry."""
    if entry.version == 1:
        # v1 wrote credentials to entry.data during setup and then a second copy
        # to entry.options whenever the Configure dialog was saved, leaving the
        # password persisted twice. Consolidate into entry.data and drop the
        # copy from options.
        data = {**entry.data}
        options = {**entry.options}
        moved = False
        for key in CREDENTIAL_KEYS:
            if key in options:
                value = options.pop(key)
                # Options were edited more recently, so they win — but never let
                # a blank field clobber a real credential in data.
                if value not in (None, ""):
                    data[key] = value
                moved = True

        hass.config_entries.async_update_entry(
            entry, data=data, options=options, version=2
        )
        if moved:
            _LOGGER.info(
                "Migrated Atmoce credentials out of entry options; they are now "
                "stored once, in the config entry data"
            )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Atmoce Battery from a config entry."""
    coordinator = AtmoceCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Load the battery SOC limits in the background (won't block setup).
    if coordinator.soc_control_available:
        entry.async_create_background_task(
            hass,
            coordinator.async_load_web_settings(),
            "atmoce_web_settings_load",
        )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: AtmoceCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        try:
            await coordinator._modbus.async_close()
        except OSError:
            pass
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
