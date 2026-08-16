"""Tests for Switch, Number, Select and Button control entities."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.atmoce.controls import (
    AtmoceDispatchPower,
    AtmoceEndOfChargeSOC,
    AtmoceForcedCommandSelect,
    AtmoceForcedDuration,
    AtmoceForcedModeSelect,
    AtmoceForcedPower,
    AtmoceRemoteControlSwitch,
    AtmoceResetButton,
    AtmoceTargetSOC,
)
from custom_components.atmoce.const import (
    FORCED_CMD_AUTO,
    FORCED_CMD_CHARGE,
    FORCED_CMD_DISCHARGE,
    FORCED_MODE_BOTH,
    FORCED_MODE_DURATION,
    FORCED_MODE_SOC,
)


def _make_coordinator(data: dict = None, **kwargs):
    coord = MagicMock()
    coord.data = data or {}
    coord.serial_number = "SN123456"
    coord.battery_model = "MS-7K-U"
    coord.firmware_version = "1.0.0"
    coord.hw_version = 1
    coord.max_charge_kw = 3.75
    coord.max_discharge_kw = 4.5
    coord.config_entry.data = {"host": "192.168.1.100"}
    coord.async_request_refresh = AsyncMock()
    coord.async_set_remote_control = AsyncMock()
    coord.async_set_forced_command = AsyncMock()
    coord.async_set_forced_mode = AsyncMock()
    coord.async_set_forced_target_soc = AsyncMock()
    coord.async_set_forced_duration = AsyncMock()
    coord.async_set_forced_power = AsyncMock()
    coord.async_set_dispatch_power = AsyncMock()
    coord.async_reset_gateway = AsyncMock()
    coord.stage_forced_param = MagicMock()
    coord.async_apply_staged_params = AsyncMock()
    for k, v in kwargs.items():
        setattr(coord, k, v)
    return coord


def _make_entity(cls, coordinator):
    entity = cls.__new__(cls)
    entity.coordinator = coordinator
    entity._attr_unique_id = f"{coordinator.serial_number}_test"
    entity._attr_device_info = MagicMock()
    return entity


# ── Switch ────────────────────────────────────────────────────────────────────

class TestRemoteControlSwitch:
    def test_is_on_when_mode_1(self):
        coord = _make_coordinator({"comm_control_mode": 1})
        entity = _make_entity(AtmoceRemoteControlSwitch, coord)
        assert entity.is_on is True

    def test_is_off_when_mode_0(self):
        coord = _make_coordinator({"comm_control_mode": 0})
        entity = _make_entity(AtmoceRemoteControlSwitch, coord)
        assert entity.is_on is False

    def test_is_none_when_missing(self):
        coord = _make_coordinator({})
        entity = _make_entity(AtmoceRemoteControlSwitch, coord)
        assert entity.is_on is False

    @pytest.mark.asyncio
    async def test_turn_on(self):
        coord = _make_coordinator({"comm_control_mode": 0})
        entity = _make_entity(AtmoceRemoteControlSwitch, coord)
        await entity.async_turn_on()
        coord.async_set_remote_control.assert_awaited_once_with(True)
        coord.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_turn_off(self):
        coord = _make_coordinator({"comm_control_mode": 1})
        entity = _make_entity(AtmoceRemoteControlSwitch, coord)
        await entity.async_turn_off()
        coord.async_set_remote_control.assert_awaited_once_with(False)
        coord.async_request_refresh.assert_awaited_once()


# ── Number entities ───────────────────────────────────────────────────────────

class TestTargetSOC:
    def test_native_value(self):
        coord = _make_coordinator({"forced_target_soc": 80})
        entity = _make_entity(AtmoceTargetSOC, coord)
        entity._key = "forced_target_soc"
        assert entity.native_value == 80

    def test_native_value_none(self):
        coord = _make_coordinator({})
        entity = _make_entity(AtmoceTargetSOC, coord)
        entity._key = "forced_target_soc"
        assert entity.native_value is None

    @pytest.mark.asyncio
    async def test_set_value(self):
        coord = _make_coordinator({"forced_target_soc": 50})
        entity = _make_entity(AtmoceTargetSOC, coord)
        entity._key = "forced_target_soc"
        await entity.async_set_native_value(80.0)
        coord.stage_forced_param.assert_called_once_with("forced_target_soc", 80.0)


class TestForcedDuration:
    @pytest.mark.asyncio
    async def test_set_duration(self):
        coord = _make_coordinator()
        entity = _make_entity(AtmoceForcedDuration, coord)
        entity._key = "forced_duration"
        await entity.async_set_native_value(120.0)
        coord.stage_forced_param.assert_called_once_with("forced_duration", 120.0)


class TestForcedPower:
    @pytest.mark.asyncio
    async def test_set_power(self):
        coord = _make_coordinator()
        entity = _make_entity(AtmoceForcedPower, coord)
        entity._key = "forced_power"
        await entity.async_set_native_value(3.5)
        coord.stage_forced_param.assert_called_once_with("forced_power", 3.5)


class TestDispatchPower:
    def test_native_value_converted_from_watts(self):
        coord = _make_coordinator({"battery_dispatch_power": 2000})
        entity = _make_entity(AtmoceDispatchPower, coord)
        entity._key = "battery_dispatch_power"
        assert entity.native_value == pytest.approx(2.0)

    def test_native_value_none(self):
        coord = _make_coordinator({"battery_dispatch_power": None})
        entity = _make_entity(AtmoceDispatchPower, coord)
        entity._key = "battery_dispatch_power"
        assert entity.native_value is None

    @pytest.mark.asyncio
    async def test_set_dispatch_power(self):
        coord = _make_coordinator()
        entity = _make_entity(AtmoceDispatchPower, coord)
        entity._key = "battery_dispatch_power"
        await entity.async_set_native_value(2.5)
        coord.async_set_dispatch_power.assert_awaited_once_with(2500)


class TestForcedParamsAreStaged:
    """Adjusting a forced-mode parameter must not disturb the battery.

    Writing one on the spot would either be discarded in local mode or force a
    handover to remote control, which takes the battery out of self-consumption
    or TOU because a number was nudged.
    """

    @pytest.mark.parametrize(
        ("entity_cls", "key", "value"),
        [
            (AtmoceTargetSOC, "forced_target_soc", 80),
            (AtmoceForcedDuration, "forced_duration", 60),
            (AtmoceForcedPower, "forced_power", 3.5),
        ],
    )
    @pytest.mark.asyncio
    async def test_setting_stages_and_writes_nothing(self, entity_cls, key, value):
        coord = _make_coordinator({key: 0, "comm_control_mode": 0})
        entity = _make_entity(entity_cls, coord)
        entity._key = key

        await entity.async_set_native_value(value)

        coord.stage_forced_param.assert_called_once_with(key, value)
        coord.async_set_remote_control.assert_not_awaited()
        coord.async_set_forced_target_soc.assert_not_awaited()
        coord.async_set_forced_duration.assert_not_awaited()
        coord.async_set_forced_power.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_forcing_applies_the_staged_values_before_the_command(self):
        coord = _make_coordinator({"forced_cmd": FORCED_CMD_AUTO})
        entity = _make_entity(AtmoceForcedCommandSelect, coord)

        calls = []
        coord.async_set_remote_control = AsyncMock(
            side_effect=lambda v: calls.append("remote")
        )
        coord.async_apply_staged_params = AsyncMock(
            side_effect=lambda: calls.append("params")
        )
        coord.async_set_forced_command = AsyncMock(
            side_effect=lambda v: calls.append("cmd")
        )

        await entity.async_select_option("Forced charge")

        # Control, then the parameters the command reads, then the command.
        assert calls == ["remote", "params", "cmd"]

    @pytest.mark.asyncio
    async def test_battery_managed_applies_nothing(self):
        """Releasing control must not push staged parameters on the way out."""
        coord = _make_coordinator({"forced_cmd": FORCED_CMD_CHARGE})
        entity = _make_entity(AtmoceForcedCommandSelect, coord)

        await entity.async_select_option("Battery managed")

        coord.async_apply_staged_params.assert_not_awaited()


class TestDispatchPower:
    """A direct setpoint the battery only follows under remote control."""

    @pytest.mark.asyncio
    async def test_unavailable_while_the_battery_self_manages(self):
        coord = _make_coordinator({"battery_dispatch_power": 0, "comm_control_mode": 0})
        entity = _make_entity(AtmoceDispatchPower, coord)
        entity._key = "battery_dispatch_power"

        assert entity.available is False

    @pytest.mark.asyncio
    async def test_available_and_written_through_under_remote_control(self):
        coord = _make_coordinator({"battery_dispatch_power": 0, "comm_control_mode": 1})
        entity = _make_entity(AtmoceDispatchPower, coord)
        entity._key = "battery_dispatch_power"

        assert entity.available is True
        await entity.async_set_native_value(2.0)
        coord.async_set_dispatch_power.assert_awaited_once_with(2000)
        coord.async_set_remote_control.assert_not_awaited()


class TestCloudLimitsAreSeparate:
    @pytest.mark.asyncio
    async def test_cloud_soc_limits_do_not_touch_remote_control(self):
        """These go to the web portal — grabbing the gateway would be a no-op
        write with a real side effect on how the battery behaves."""
        coord = _make_coordinator({"end_of_charge_soc": 90})
        coord.async_set_web_soc_limit = AsyncMock()
        entity = _make_entity(AtmoceEndOfChargeSOC, coord)
        entity._key = "end_of_charge_soc"

        await entity.async_set_native_value(95)

        coord.async_set_web_soc_limit.assert_awaited_once_with("end_of_charge_soc", 95)
        coord.async_set_remote_control.assert_not_awaited()


# ── Select entities ───────────────────────────────────────────────────────────

class TestForcedCommandSelect:
    def _entity(self, cmd_value):
        coord = _make_coordinator({"forced_cmd": cmd_value})
        entity = _make_entity(AtmoceForcedCommandSelect, coord)
        return entity

    def test_current_option_charge(self):
        assert self._entity(FORCED_CMD_CHARGE).current_option == "Forced charge"

    def test_current_option_discharge(self):
        assert self._entity(FORCED_CMD_DISCHARGE).current_option == "Forced discharge"

    def test_current_option_auto(self):
        assert self._entity(FORCED_CMD_AUTO).current_option == "Battery managed"

    def test_current_option_none_when_missing(self):
        assert self._entity(None).current_option is None

    @pytest.mark.asyncio
    async def test_select_charge_takes_remote_control_first(self):
        """A forced command in local mode is silently ignored by the gateway."""
        coord = _make_coordinator({"forced_cmd": FORCED_CMD_AUTO})
        entity = _make_entity(AtmoceForcedCommandSelect, coord)

        calls = []
        coord.async_set_remote_control = AsyncMock(
            side_effect=lambda v: calls.append(("remote", v))
        )
        coord.async_set_forced_command = AsyncMock(
            side_effect=lambda v: calls.append(("cmd", v))
        )

        await entity.async_select_option("Forced charge")

        # Order matters: the order is discarded if it arrives while still local.
        assert calls == [("remote", True), ("cmd", FORCED_CMD_CHARGE)]

    @pytest.mark.asyncio
    async def test_select_discharge_takes_remote_control_first(self):
        coord = _make_coordinator({"forced_cmd": FORCED_CMD_AUTO})
        entity = _make_entity(AtmoceForcedCommandSelect, coord)

        await entity.async_select_option("Forced discharge")

        coord.async_set_remote_control.assert_awaited_once_with(True)
        coord.async_set_forced_command.assert_awaited_once_with(FORCED_CMD_DISCHARGE)

    @pytest.mark.asyncio
    async def test_select_auto_also_disables_remote(self):
        coord = _make_coordinator({"forced_cmd": FORCED_CMD_CHARGE})
        entity = _make_entity(AtmoceForcedCommandSelect, coord)
        await entity.async_select_option("Battery managed")
        coord.async_set_forced_command.assert_awaited_once_with(FORCED_CMD_AUTO)
        coord.async_set_remote_control.assert_awaited_once_with(False)

    @pytest.mark.asyncio
    async def test_auto_exits_forced_mode_before_releasing_control(self):
        """Releasing remote control first would strand the forced command."""
        coord = _make_coordinator({"forced_cmd": FORCED_CMD_CHARGE})
        entity = _make_entity(AtmoceForcedCommandSelect, coord)

        calls = []
        coord.async_set_remote_control = AsyncMock(
            side_effect=lambda v: calls.append(("remote", v))
        )
        coord.async_set_forced_command = AsyncMock(
            side_effect=lambda v: calls.append(("cmd", v))
        )

        await entity.async_select_option("Battery managed")

        assert calls == [("cmd", FORCED_CMD_AUTO), ("remote", False)]


class TestForcedModeSelect:
    def _entity(self, mode_value):
        coord = _make_coordinator({"forced_mode": mode_value})
        entity = _make_entity(AtmoceForcedModeSelect, coord)
        return entity

    def test_current_option_soc(self):
        assert self._entity(FORCED_MODE_SOC).current_option == "Target SOC"

    def test_current_option_duration(self):
        assert self._entity(FORCED_MODE_DURATION).current_option == "Duration"

    def test_current_option_both(self):
        assert self._entity(FORCED_MODE_BOTH).current_option == "SOC + Duration"

    @pytest.mark.asyncio
    async def test_select_duration(self):
        coord = _make_coordinator({"forced_mode": FORCED_MODE_SOC})
        entity = _make_entity(AtmoceForcedModeSelect, coord)
        await entity.async_select_option("Duration")
        coord.async_set_forced_mode.assert_awaited_once_with(FORCED_MODE_DURATION)


# ── Button entities ───────────────────────────────────────────────────────────

class TestResetButton:
    @pytest.mark.asyncio
    async def test_press_calls_reset(self):
        coord = _make_coordinator()
        entity = _make_entity(AtmoceResetButton, coord)
        await entity.async_press()
        coord.async_reset_gateway.assert_awaited_once()
