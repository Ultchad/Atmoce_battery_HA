"""Atmoce Cloud API client — read-only monitoring fallback (partner Open API).

Note: the battery SOC limits are handled by ``web_client.AtmoceWebClient`` (the
owner's normal login), not here — the Open API needs partner credentials that
most owners don't have.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import CLOUD_BASE_URL

_LOGGER = logging.getLogger(__name__)

_TOKEN_URL = f"{CLOUD_BASE_URL}/auth/token"
_SITES_URL = f"{CLOUD_BASE_URL}/sites/getSitesLastPower"


class AtmoceCloudError(Exception):
    """The Cloud Open API rejected the request or returned no usable data."""


class AtmoceCloudAuthError(AtmoceCloudError):
    """Authentication against the Cloud Open API failed."""


class AtmoceCloudClient:
    """Minimal async Cloud client for monitoring fallback."""

    def __init__(self, app_key: str, app_secret: str) -> None:
        self._app_key = app_key
        self._app_secret = app_secret
        self._access_token: str | None = None

    async def _async_authenticate(self) -> None:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                _TOKEN_URL,
                json={
                    "app_key": self._app_key,
                    "app_secret": self._app_secret,
                    "grant_type": "system",
                },
            )
            data = await resp.json()
        if not data.get("success"):
            raise AtmoceCloudAuthError(f"Cloud auth failed: {data.get('reason')}")
        self._access_token = data["data"]["access_token"]

    async def async_fetch_site_data(self, serial_number: str) -> dict[str, Any]:
        """Fetch latest site data and map to the same keys as Modbus fetch."""
        try:
            return await self._async_fetch_once(serial_number)
        except AtmoceCloudError:
            # A cached access token that the portal has since expired looks the
            # same as any other rejection, so drop it and retry once with a fresh
            # one. Without this the client stays wedged on a stale token forever.
            if self._access_token is None:
                raise
            _LOGGER.debug("Cloud fetch rejected — re-authenticating and retrying once")
            self._access_token = None
            return await self._async_fetch_once(serial_number)

    async def _async_fetch_once(self, serial_number: str) -> dict[str, Any]:
        if not self._access_token:
            await self._async_authenticate()

        headers = {"Authorization": f"Bearer {self._access_token}"}
        async with aiohttp.ClientSession(headers=headers) as session:
            resp = await session.get(
                _SITES_URL,
                params={"siteIds": serial_number},
            )
            payload = await resp.json()

        if not payload.get("success") or not payload.get("data"):
            raise AtmoceCloudError(f"Cloud data fetch failed: {payload.get('reason')}")

        site = payload["data"][0]

        # Map Cloud fields → coordinator keys (subset — Cloud has 15-min latency)
        return {
            "grid_power":              site.get("gridPower"),
            "pv_power":                site.get("solarGenerationPower"),
            "pv_energy_daily":         site.get("dailySolarGeneration"),
            "pv_energy_total":         site.get("lifetimeSolarGeneration"),
            "grid_energy_daily":       site.get("dailyFromGrid"),
            "grid_energy_total":       site.get("lifetimeFromGrid"),
            "elec_sales_daily":        site.get("dailyToGrid"),
            "elec_sales_total":        site.get("lifetimeToGrid"),
            "battery_soc":             site.get("batterySOC"),
            "battery_power":           site.get("batteryPower"),
            "battery_status":          site.get("batteryStatus"),
            "battery_charged_daily":   site.get("dailyBatteryCharging"),
            "battery_discharged_daily":site.get("dailyBatteryDischarge"),
            "battery_charged_total":   site.get("lifetimeBatteryCharging"),
            "battery_discharged_total":site.get("lifetimeBatteryDischarge"),
            # Fields not available from Cloud
            "grid_voltage": None,
            "grid_current": None,
            "battery_dispatch_power": None,
            "comm_control_mode": None,
            "forced_cmd": None,
            "forced_mode": None,
            "forced_target_soc": None,
            "forced_duration": None,
            "forced_power": None,
            "station_status": None,
        }
