"""Config flow for Atmoce Battery integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import selector
from pymodbus.exceptions import ModbusException

from .const import (
    BATTERY_MODELS,
    CONF_BATTERY_COUNT,
    CONF_BATTERY_MODEL,
    CONF_CAPACITY_KWH,
    CONF_CHARGE_KW,
    CONF_CLOUD_APP_KEY,
    CONF_CLOUD_APP_SECRET,
    CONF_CLOUD_ENABLED,
    CONF_CLOUD_WEB_EMAIL,
    CONF_CLOUD_WEB_PASSWORD,
    CONF_DISCHARGE_KW,
    CONF_RETRY_COUNT,
    CONF_SLAVE,
    CREDENTIAL_KEYS,
    DEFAULT_BATTERY_COUNT,
    DEFAULT_PORT,
    DEFAULT_SLAVE,
    DOMAIN,
    MAX_BATTERY_COUNT,
    MODBUS_RETRY_COUNT,
)
from .modbus_client import AtmoceModbusClient

_LOGGER = logging.getLogger(__name__)

# ── Step 1: gateway connection ───────────────────────────────────────────────
def _gateway_schema(
    host: str = "",
    port: int = DEFAULT_PORT,
    slave: int = DEFAULT_SLAVE,
) -> vol.Schema:
    """Build the gateway connection schema."""
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=host): str,
            vol.Required(CONF_PORT, default=port): vol.All(
                int, vol.Range(min=1, max=65535)
            ),
            vol.Required(CONF_SLAVE, default=slave): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=247,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
        }
    )

# ── Step 2: battery model ────────────────────────────────────────────────────
STEP_BATTERY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BATTERY_MODEL, default="MS-7K-U"): vol.In(
            {k: v["label"] for k, v in BATTERY_MODELS.items()}
        ),
        vol.Required(CONF_BATTERY_COUNT, default=DEFAULT_BATTERY_COUNT): vol.All(
            int, vol.Range(min=1, max=MAX_BATTERY_COUNT)
        ),
    }
)

# ── Step 2b: manual battery specs ───────────────────────────────────────────
STEP_MANUAL_BATTERY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CAPACITY_KWH, default=7.0): vol.All(
            float, vol.Range(min=0.5, max=500.0)
        ),
        vol.Required(CONF_CHARGE_KW, default=3.75): vol.All(
            float, vol.Range(min=0.1, max=100.0)
        ),
        vol.Required(CONF_DISCHARGE_KW, default=4.5): vol.All(
            float, vol.Range(min=0.1, max=100.0)
        ),
    }
)

# ── Step 3: cloud (optional) ─────────────────────────────────────────────────
_PASSWORD_SELECTOR = selector.TextSelector(
    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
)

# The owner's own atmocecloud.com login — all that the battery SOC limits need.
STEP_CLOUD_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_CLOUD_WEB_EMAIL, default=""): str,
        vol.Optional(CONF_CLOUD_WEB_PASSWORD, default=""): _PASSWORD_SELECTOR,
    }
)

# ── Step 4: monitoring fallback (rarely needed) ──────────────────────────────
# Kept apart from the login above because it is a different feature backed by a
# different API: the partner Open API, whose app_key/app_secret are issued by
# Atmoce support to installers and do not ship with the hardware. Owners who
# only want the battery limits should never have to look at these fields.
STEP_FALLBACK_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CLOUD_ENABLED, default=False): bool,
        vol.Optional(CONF_CLOUD_APP_KEY, default=""): str,
        vol.Optional(CONF_CLOUD_APP_SECRET, default=""): str,
        vol.Optional(CONF_RETRY_COUNT, default=MODBUS_RETRY_COUNT): vol.All(
            int, vol.Range(min=1, max=20)
        ),
    }
)


# BATTERY_MODELS carries a "manual" placeholder whose specs are all None; it is
# a routing choice in the setup wizard, not something that can be multiplied.
CATALOGUE_MODELS = {
    k: v for k, v in BATTERY_MODELS.items() if v["capacity_kwh"] is not None
}


def _specs_for(model_key: str, count: int) -> dict[str, Any]:
    """Return the config keys for `count` stacked units of `model_key`.

    Capacity and power scale with the number of units. Rounded because floats
    like 3.75 * 3 land on values such as 11.249999999999998.
    """
    model = BATTERY_MODELS[model_key]
    return {
        CONF_BATTERY_MODEL: model_key,
        CONF_BATTERY_COUNT: count,
        CONF_CAPACITY_KWH: round(model["capacity_kwh"] * count, 2),
        CONF_CHARGE_KW: round(model["charge_kw"] * count, 2),
        CONF_DISCHARGE_KW: round(model["discharge_kw"] * count, 2),
    }


class AtmoceConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Atmoce config flow."""

    VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    # ── Step 1: gateway ──────────────────────────────────────────────────────
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input[CONF_PORT]
            slave = user_input.get(CONF_SLAVE, DEFAULT_SLAVE)

            client = AtmoceModbusClient(host, port, slave)
            try:
                await client.async_connect()
                sn = await client.async_read_serial_number()
                await client.async_close()
            except (ConnectionError, ModbusException, OSError):
                errors["base"] = "cannot_connect"
                sn = None

            if not errors:
                await self.async_set_unique_id(sn or f"{host}:{port}")
                self._abort_if_unique_id_configured()
                self._data[CONF_HOST] = host
                self._data[CONF_PORT] = port
                self._data[CONF_SLAVE] = slave
                self._data["serial_number"] = sn
                return await self.async_step_battery()

        return self.async_show_form(
            step_id="user",
            data_schema=_gateway_schema(),
            errors=errors,
        )

    # ── Step 2: battery model ────────────────────────────────────────────────
    async def async_step_battery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_BATTERY_MODEL] = user_input[CONF_BATTERY_MODEL]
            if user_input[CONF_BATTERY_MODEL] == "manual":
                return await self.async_step_manual_battery()
            # Pre-fill specs from catalogue
            self._data.update(
                _specs_for(
                    user_input[CONF_BATTERY_MODEL],
                    user_input.get(CONF_BATTERY_COUNT, DEFAULT_BATTERY_COUNT),
                )
            )
            return await self.async_step_cloud()

        return self.async_show_form(
            step_id="battery",
            data_schema=STEP_BATTERY_SCHEMA,
        )

    # ── Step 2b: manual battery specs ────────────────────────────────────────
    async def async_step_manual_battery(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_cloud()

        return self.async_show_form(
            step_id="manual_battery",
            data_schema=STEP_MANUAL_BATTERY_SCHEMA,
        )

    # ── Step 3: atmocecloud.com login (optional) ─────────────────────────────
    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_fallback()

        return self.async_show_form(
            step_id="cloud",
            data_schema=STEP_CLOUD_SCHEMA,
        )

    # ── Step 4: monitoring fallback (optional) ───────────────────────────────
    async def async_step_fallback(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            cloud_enabled = user_input.get(CONF_CLOUD_ENABLED, False)
            app_key = user_input.get(CONF_CLOUD_APP_KEY, "").strip()
            app_secret = user_input.get(CONF_CLOUD_APP_SECRET, "").strip()

            if cloud_enabled and (not app_key or not app_secret):
                errors["base"] = "cloud_credentials_required"

            if not errors:
                self._data.update(user_input)
                host = self._data[CONF_HOST]
                model = self._data.get(CONF_BATTERY_MODEL, "manual")
                title = f"Atmoce {model} @ {host}"
                return self.async_create_entry(title=title, data=self._data)

        return self.async_show_form(
            step_id="fallback",
            data_schema=STEP_FALLBACK_SCHEMA,
            errors=errors,
        )

    # ── Reconfigure (batteries added or removed) ─────────────────────────────
    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Re-state the battery stack without deleting the integration.

        Capacity and power limits are fixed at setup and feed the autonomy
        sensor and the forced-power sliders, so adding a second battery used to
        mean removing and re-adding the entry.
        """
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data_updates=_specs_for(
                    user_input[CONF_BATTERY_MODEL],
                    user_input[CONF_BATTERY_COUNT],
                ),
            )

        stored_model = entry.data.get(CONF_BATTERY_MODEL)
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BATTERY_MODEL,
                    # An entry set up with manual specs has no catalogue model to
                    # fall back on, so offer the default rather than "manual",
                    # whose specs are None and cannot be scaled.
                    default=(
                        stored_model
                        if stored_model in CATALOGUE_MODELS
                        else "MS-7K-U"
                    ),
                ): vol.In({k: v["label"] for k, v in CATALOGUE_MODELS.items()}),
                vol.Required(
                    CONF_BATTERY_COUNT,
                    default=entry.data.get(CONF_BATTERY_COUNT, DEFAULT_BATTERY_COUNT),
                ): vol.All(int, vol.Range(min=1, max=MAX_BATTERY_COUNT)),
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    # ── Reauth (IP changed) ──────────────────────────────────────────────────
    async def async_step_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)

            entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
            slave = entry.data.get(CONF_SLAVE, DEFAULT_SLAVE)

            client = AtmoceModbusClient(host, port, slave)
            try:
                await client.async_connect()
                await client.async_close()
            except (ConnectionError, ModbusException, OSError):
                errors["base"] = "cannot_connect"

            if not errors:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_HOST: host, CONF_PORT: port},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=self.context.get("host", "")): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AtmoceOptionsFlow:
        return AtmoceOptionsFlow()


class AtmoceOptionsFlow(config_entries.OptionsFlow):
    """Handle options (accessible from the integration card after setup)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            cloud_enabled = user_input.get(CONF_CLOUD_ENABLED, False)
            app_key = user_input.get(CONF_CLOUD_APP_KEY, "").strip()
            app_secret = user_input.get(CONF_CLOUD_APP_SECRET, "").strip()

            if cloud_enabled and (not app_key or not app_secret):
                errors["base"] = "cloud_credentials_required"

            if not errors:
                # Credentials belong in entry.data. Update them in place rather
                # than storing a second copy in entry.options, so the password
                # only ever exists once on disk.
                tunables = {k: v for k, v in user_input.items() if k not in CREDENTIAL_KEYS}
                credentials = {
                    k: user_input[k] for k in CREDENTIAL_KEYS if k in user_input
                }
                if credentials:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={**self.config_entry.data, **credentials},
                    )
                return self.async_create_entry(title="", data=tunables)

        # entry.data holds the credentials, entry.options the tunables — the form
        # needs both to pre-fill correctly.
        current = {**self.config_entry.data, **self.config_entry.options}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_RETRY_COUNT,
                    default=current.get(CONF_RETRY_COUNT, MODBUS_RETRY_COUNT),
                ): vol.All(int, vol.Range(min=1, max=20)),
                vol.Required(
                    CONF_CLOUD_ENABLED,
                    default=current.get(CONF_CLOUD_ENABLED, False),
                ): bool,
                vol.Optional(
                    CONF_CLOUD_APP_KEY,
                    default=current.get(CONF_CLOUD_APP_KEY, ""),
                ): str,
                vol.Optional(
                    CONF_CLOUD_APP_SECRET,
                    default=current.get(CONF_CLOUD_APP_SECRET, ""),
                ): str,
                vol.Optional(
                    CONF_CLOUD_WEB_EMAIL,
                    default=current.get(CONF_CLOUD_WEB_EMAIL, ""),
                ): str,
                vol.Optional(
                    CONF_CLOUD_WEB_PASSWORD,
                    default=current.get(CONF_CLOUD_WEB_PASSWORD, ""),
                ): _PASSWORD_SELECTOR,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            errors=errors,
        )
