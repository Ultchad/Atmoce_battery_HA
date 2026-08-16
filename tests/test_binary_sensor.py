"""Tests for the battery problem binary sensor."""
from unittest.mock import MagicMock

from homeassistant.components.binary_sensor import BinarySensorDeviceClass

from custom_components.atmoce.binary_sensor import AtmoceBatteryProblem


def _entity(data: dict):
    coord = MagicMock()
    coord.data = data
    coord.serial_number = "SN123456"
    entity = AtmoceBatteryProblem.__new__(AtmoceBatteryProblem)
    entity.coordinator = coord
    return entity


class TestBatteryProblem:
    """The coordinator computes health; the sensor reports the inverse."""

    def test_healthy_battery_reports_no_problem(self):
        assert _entity({"battery_healthy": True}).is_on is False

    def test_unhealthy_battery_reports_a_problem(self):
        assert _entity({"battery_healthy": False}).is_on is True

    def test_missing_value_is_unknown_not_a_problem(self):
        """Absent data must not raise an alarm on its own."""
        assert _entity({}).is_on is None

    def test_device_class_makes_on_mean_trouble(self):
        entity = _entity({"battery_healthy": True})
        assert entity.device_class == BinarySensorDeviceClass.PROBLEM
