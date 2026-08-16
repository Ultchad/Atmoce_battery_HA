"""Switch, Number, Select and Button entities for Atmoce Battery."""
from __future__ import annotations

import logging
from typing import Any, ClassVar

from homeassistant.components.button import ButtonEntity
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import PERCENTAGE, UnitOfPower, UnitOfTime
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    END_OF_CHARGE_SOC_MAX,
    END_OF_CHARGE_SOC_MIN,
    END_OF_DISCHARGE_SOC_MAX,
    END_OF_DISCHARGE_SOC_MIN,
    FORCED_CMD_AUTO,
    FORCED_CMD_CHARGE,
    FORCED_CMD_DISCHARGE,
    FORCED_MODE_BOTH,
    FORCED_MODE_DURATION,
    FORCED_MODE_SOC,
    KEY_BATTERY_RESERVED_SOC,
    KEY_END_OF_CHARGE_SOC,
    KEY_END_OF_DISCHARGE_SOC,
)
from .coordinator import AtmoceCoordinator
from .sensor import _device_info

_LOGGER = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# SWITCH — Remote control mode
# ══════════════════════════════════════════════════════════════════════════════


class AtmoceRemoteControlSwitch(CoordinatorEntity[AtmoceCoordinator], SwitchEntity):
    """Switch to enable/disable remote Modbus control of the battery."""

    _attr_has_entity_name = True
    _attr_name = "Remote Control"
    _attr_icon = "mdi:remote"

    def __init__(self, coordinator: AtmoceCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial_number}_remote_control"
        self._attr_device_info = _device_info(coordinator)

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get("comm_control_mode") == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_remote_control(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_remote_control(False)
        await self.coordinator.async_request_refresh()


# ══════════════════════════════════════════════════════════════════════════════
# NUMBER entities
# ══════════════════════════════════════════════════════════════════════════════

class AtmoceNumber(CoordinatorEntity[AtmoceCoordinator], NumberEntity):
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX

    def __init__(self, coordinator: AtmoceCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.serial_number}_{key}"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        await self._async_write(value)
        await self.coordinator.async_request_refresh()

    async def _async_write(self, value: float) -> None:
        """Push `value` to the device. Subclasses must implement this."""
        raise NotImplementedError


class AtmoceForcedParam(AtmoceNumber):
    """A parameter of a forced charge or discharge, not a control of its own.

    Nothing is written when you type one. The value is staged in Home
    Assistant and the Battery Command select applies it when you actually ask
    for a forced charge or discharge. Writing on the spot would mean either
    losing it (the gateway discards writes in local mode) or taking remote
    control, which would knock the battery out of self-consumption or TOU just
    because a number was adjusted.
    """

    async def async_set_native_value(self, value: float) -> None:
        self.coordinator.stage_forced_param(self._key, value)


class AtmoceTargetSOC(AtmoceForcedParam):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:battery-arrow-up"

    def __init__(self, coordinator: AtmoceCoordinator) -> None:
        super().__init__(coordinator, "forced_target_soc", "Forced Target SOC")


class AtmoceForcedDuration(AtmoceForcedParam):
    _attr_native_min_value = 0
    _attr_native_max_value = 1440
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: AtmoceCoordinator) -> None:
        super().__init__(coordinator, "forced_duration", "Forced Duration")


class AtmoceForcedPower(AtmoceForcedParam):
    _attr_native_min_value = 0
    _attr_native_step = 0.1
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_icon = "mdi:flash"

    def __init__(self, coordinator: AtmoceCoordinator) -> None:
        super().__init__(coordinator, "forced_power", "Forced Power")
        # Max from battery catalogue
        self._attr_native_max_value = coordinator.max_charge_kw


class AtmoceDispatchPower(AtmoceNumber):
    """Direct power setpoint — a command in its own right, not a parameter.

    Unlike the forced-mode parameters this cannot be staged: there is no later
    moment that would apply it, since the battery follows it only while under
    remote control. So it is offered only when remote control is already on,
    rather than grabbing it and pulling the battery out of self-managed
    operation the moment someone nudges the value.
    """

    _attr_native_step = 0.05
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_icon = "mdi:battery-arrow-down-outline"

    def __init__(self, coordinator: AtmoceCoordinator) -> None:
        super().__init__(coordinator, "battery_dispatch_power", "Dispatch Power")
        self._attr_native_min_value = -coordinator.max_charge_kw
        self._attr_native_max_value = coordinator.max_discharge_kw

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.get("comm_control_mode") == 1

    @property
    def native_value(self) -> float | None:
        raw = self.coordinator.data.get("battery_dispatch_power")
        return round(raw / 1000, 2) if raw is not None else None

    async def _async_write(self, value: float) -> None:
        await self.coordinator.async_set_dispatch_power(int(value * 1000))


# ── Battery SOC limits (web portal login) ─────────────────────────────────────
# These map to the charge / discharge / safety-reserve limits editable in the
# ATMOZEN app. They are NOT available over Modbus, so they are read and written
# through the web-portal private API and are only available when the atmocecloud.com
# login (email + password) is configured.

class AtmoceWebSOCNumber(AtmoceNumber):
    """Base for a battery SOC limit backed by the web-portal login."""

    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE

    @property
    def available(self) -> bool:
        # Writing (and reading) these requires the web-portal login.
        return super().available and self.coordinator.soc_control_available

    async def async_set_native_value(self, value: float) -> None:
        # Deliberately bypasses AtmoceNumber's remote-control handover: these
        # go to the web portal, not to a Modbus register, so taking control of
        # the gateway would be a pointless write with a real side effect.
        await self.coordinator.async_set_web_soc_limit(self._key, int(value))


class AtmoceEndOfChargeSOC(AtmoceWebSOCNumber):
    """Charge limit — the SOC at which charging stops (endOfChargeSOC)."""

    _attr_native_min_value = END_OF_CHARGE_SOC_MIN
    _attr_native_max_value = END_OF_CHARGE_SOC_MAX
    _attr_icon = "mdi:battery-high"

    def __init__(self, coordinator: AtmoceCoordinator) -> None:
        super().__init__(coordinator, KEY_END_OF_CHARGE_SOC, "Charge Limit SOC")


class AtmoceEndOfDischargeSOC(AtmoceWebSOCNumber):
    """Discharge limit — the SOC at which discharging stops (endOfDischargeSOC)."""

    _attr_native_min_value = END_OF_DISCHARGE_SOC_MIN
    _attr_native_max_value = END_OF_DISCHARGE_SOC_MAX
    _attr_icon = "mdi:battery-low"

    def __init__(self, coordinator: AtmoceCoordinator) -> None:
        super().__init__(coordinator, KEY_END_OF_DISCHARGE_SOC, "Discharge Limit SOC")


class AtmoceBatteryReservedSOC(AtmoceWebSOCNumber):
    """Safety/backup reserve — battery stops discharging here except on a grid outage.

    Valid range is [endOfDischargeSOC, endOfChargeSOC]; the bounds follow the two
    other limits dynamically.
    """

    _attr_icon = "mdi:battery-lock"

    def __init__(self, coordinator: AtmoceCoordinator) -> None:
        super().__init__(coordinator, KEY_BATTERY_RESERVED_SOC, "Backup Reserve SOC")

    @property
    def native_min_value(self) -> float:
        low = self.coordinator.data.get(KEY_END_OF_DISCHARGE_SOC)
        return float(low) if low is not None else float(END_OF_DISCHARGE_SOC_MIN)

    @property
    def native_max_value(self) -> float:
        high = self.coordinator.data.get(KEY_END_OF_CHARGE_SOC)
        return float(high) if high is not None else float(END_OF_CHARGE_SOC_MAX)


# ══════════════════════════════════════════════════════════════════════════════
# SELECT entities
# ══════════════════════════════════════════════════════════════════════════════

class AtmoceForcedCommandSelect(CoordinatorEntity[AtmoceCoordinator], SelectEntity):
    """Select forced charge / discharge / auto mode."""

    _attr_has_entity_name = True
    _attr_name = "Battery Command"
    _attr_icon = "mdi:battery-sync"
    _CMD_TO_OPTION: ClassVar[dict[int, str]] = {
        FORCED_CMD_CHARGE:    "Forced charge",
        FORCED_CMD_DISCHARGE: "Forced discharge",
        FORCED_CMD_AUTO:      "Battery managed",
    }
    _OPTION_TO_CMD: ClassVar[dict[str, int]] = {
        v: k for k, v in _CMD_TO_OPTION.items()
    }

    def __init__(self, coordinator: AtmoceCoordinator) -> None:
        super().__init__(coordinator)
        # Set here rather than as a class attribute: SelectEntity declares
        # _attr_options as an instance attribute, so ClassVar would clash.
        self._attr_options = list(self._CMD_TO_OPTION.values())
        self._attr_unique_id = f"{coordinator.serial_number}_forced_command"
        self._attr_device_info = _device_info(coordinator)

    @property
    def current_option(self) -> str | None:
        raw = self.coordinator.data.get("forced_cmd")
        return self._CMD_TO_OPTION.get(raw) if raw is not None else None

    async def async_select_option(self, option: str) -> None:
        cmd = self._OPTION_TO_CMD[option]

        if cmd == FORCED_CMD_AUTO:
            # "Battery managed" hands full control back to the battery: besides
            # exiting forced mode, drop out of remote control so it self-manages
            # (self-use/TOU).
            await self.coordinator.async_set_forced_command(cmd)
            await self.coordinator.async_set_remote_control(False)
        else:
            # This is where a forced charge or discharge actually begins, so it
            # is where everything it needs comes together. The gateway ignores
            # Modbus writes in local mode, so take control first; then push the
            # parameters the owner has set, which have been waiting in Home
            # Assistant precisely so that adjusting them did not disturb the
            # battery; then give the order, which reads them.
            await self.coordinator.async_set_remote_control(True)
            await self.coordinator.async_apply_staged_params()
            await self.coordinator.async_set_forced_command(cmd)

        await self.coordinator.async_request_refresh()


class AtmoceForcedModeSelect(CoordinatorEntity[AtmoceCoordinator], SelectEntity):
    """Select how forced mode is measured: SOC, duration, or both."""

    _attr_has_entity_name = True
    _attr_name = "Forced Mode Type"
    _attr_icon = "mdi:tune"
    _MODE_TO_OPTION: ClassVar[dict[int, str]] = {
        FORCED_MODE_SOC:      "Target SOC",
        FORCED_MODE_DURATION: "Duration",
        FORCED_MODE_BOTH:     "SOC + Duration",
    }
    _OPTION_TO_MODE: ClassVar[dict[str, int]] = {
        v: k for k, v in _MODE_TO_OPTION.items()
    }

    def __init__(self, coordinator: AtmoceCoordinator) -> None:
        super().__init__(coordinator)
        # See AtmoceForcedCommandSelect for why this is not a class attribute.
        self._attr_options = list(self._MODE_TO_OPTION.values())
        self._attr_unique_id = f"{coordinator.serial_number}_forced_mode"
        self._attr_device_info = _device_info(coordinator)

    @property
    def current_option(self) -> str | None:
        raw = self.coordinator.data.get("forced_mode")
        return self._MODE_TO_OPTION.get(raw) if raw is not None else None

    async def async_select_option(self, option: str) -> None:
        mode = self._OPTION_TO_MODE[option]
        await self.coordinator.async_set_forced_mode(mode)
        await self.coordinator.async_request_refresh()


# ══════════════════════════════════════════════════════════════════════════════
# BUTTON entities
# ══════════════════════════════════════════════════════════════════════════════

class AtmoceResetButton(CoordinatorEntity[AtmoceCoordinator], ButtonEntity):
    """Button to reset the Atmoce gateway."""

    _attr_has_entity_name = True
    _attr_name = "Reset Gateway"
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: AtmoceCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.serial_number}_reset"
        self._attr_device_info = _device_info(coordinator)

    async def async_press(self) -> None:
        await self.coordinator.async_reset_gateway()
