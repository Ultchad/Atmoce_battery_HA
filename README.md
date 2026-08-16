<p align="left">
  <img src="custom_components/atmoce/brand/logo.png" alt="Atmoce Battery" width="300">
</p>

# Atmoce Battery — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![GitHub release](https://img.shields.io/github/release/pacorola/Atmoce_battery_HA.svg)](https://github.com/pacorola/Atmoce_battery_HA/releases)

Full local control and monitoring of **Atmoce solar + battery systems** via **Modbus TCP**, with an optional read-only Cloud API fallback.

Still under testing with the **Atmoce MS-7K-U** (7 kWh LFP battery). Should be compatible with MC100, MC100-T and MG100 gateways. Try on your installation and please report so any needed fix can be done.

---

## Features

- **27 sensor entities** — grid, PV, battery, system and computed metrics
- **Full battery control** — force charge/discharge, set target SOC (Requires cloud user and password for this function), duration and power or just let the battery manage itself. 
- **Battery count** in setup — say how many MS-7K-U units you have and the capacity and power limits follow; changeable later via **Reconfigure**, with manual entry for other hardware
- **Automatic Modbus→Cloud fallback** (optional) if the gateway is temporarily unreachable, although a very rare case (and requires ATMOCE to hand you API credentials)
- **Active data source sensor** — always know whether you are reading Modbus or Cloud
- **Computed sensors** — autonomy hours, PV self-consumption rate, battery health
- **Diagnostics support** — exportable debug info with sensitive fields redacted
- **Trilingual** — English, Spanish and French UI out of the box

---

## Installation via HACS

1. In Home Assistant go to **HACS → Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/pacorola/Atmoce_battery_HA` as an **Integration**.
3. Search for **Atmoce Battery** and install.
4. Restart Home Assistant.

---

## Setup

1. Go to **Settings → Devices & Services → Add Integration** and search for **Atmoce Battery**.
2. **Step 1 — Gateway**: enter the local IP address of your gateway (MC100 / MG100). The integration will verify connectivity before continuing.
3. **Step 2 — Batteries**: enter how many MS-7K-U units you have. Capacity and power limits are worked out from that. Tick **Enter specifications manually** for different hardware. You can change the count later with **Reconfigure**, without removing the integration.
4. **Step 3 — atmocecloud.com account (optional)**: your normal portal login. Only needed for the battery SOC limits (charge, discharge and backup reserve), which do not exist over Modbus.
5. **Step 4 — Cloud monitoring fallback (optional, advanced)**: almost nobody needs this — just submit it. It only covers the gateway going unreachable over Modbus, and it needs partner Open API keys that Atmoce support issues to installers on request.

> **Note**: The Atmoce Gateway must have **Modbus TCP enabled** (port 502, no authentication). This is the default factory setting.

---

## Entities

### Sensors

| Entity | Unit | Description |
|--------|------|-------------|
| `sensor.atmoce_grid_voltage` | V | Grid voltage |
| `sensor.atmoce_grid_current` | A | Grid current (signed) |
| `sensor.atmoce_grid_power` | W | Grid active power (positive = import) |
| `sensor.atmoce_grid_energy_daily` | kWh | Energy imported today |
| `sensor.atmoce_grid_energy_total` | kWh | Cumulative energy imported |
| `sensor.atmoce_electricity_sold_daily` | kWh | Energy exported today |
| `sensor.atmoce_electricity_sold_total` | kWh | Cumulative energy exported |
| `sensor.atmoce_pv_power` | W | Current solar generation |
| `sensor.atmoce_pv_energy_daily` | kWh | Solar produced today |
| `sensor.atmoce_pv_energy_total` | kWh | Cumulative solar produced |
| `sensor.atmoce_pv_self_consumption_rate` | % | Solar consumed directly (computed) |
| `sensor.atmoce_battery_soc` | % | State of charge |
| `sensor.atmoce_battery_power` | W | Charge/discharge power |
| `sensor.atmoce_battery_status` | — | charging / discharging / idle |
| `sensor.atmoce_battery_operating_mode` | — | self_consumption / tou / remote_control |
| `sensor.atmoce_battery_dispatch_power` | W | Dispatch setpoint readback |
| `sensor.atmoce_battery_charged_daily` | kWh | Charged today |
| `sensor.atmoce_battery_discharged_daily` | kWh | Discharged today |
| `sensor.atmoce_battery_charged_total` | kWh | Cumulative charged |
| `sensor.atmoce_battery_discharged_total` | kWh | Cumulative discharged |
| `sensor.atmoce_battery_autonomy` | h | Estimated hours of autonomy (computed) |
| `sensor.atmoce_station_status` | — | normal / fault |
| `sensor.atmoce_active_data_source` | — | Modbus / Cloud |
| `sensor.atmoce_connection_errors` | — | Cumulative Modbus failures |
| `binary_sensor.atmoce_battery_healthy` | — | False if battery appears stuck |

### Controls

| Entity | Description |
|--------|-------------|
| `number.atmoce_forced_target_soc` | Target SOC for forced charge/discharge (0–100 %) |
| `number.atmoce_forced_duration` | Duration for forced operation (0–1440 min) |
| `number.atmoce_forced_power` | Power for forced charge (0–max charge kW) |
| `number.atmoce_dispatch_power` | Dispatch power setpoint in kW (negative = charge) |
| `select.atmoce_battery_command` | Carga forzada / Descarga forzada / Administrado por batería |
| `select.atmoce_forced_mode_type` | SOC objetivo / Duración / SOC + Duración |
| `button.atmoce_reset_gateway` | Reset the Atmoce gateway |

### Battery SOC limits (Atmoce Cloud login)

These match the charge / discharge / safety-reserve limits editable in the ATMOZEN app. They are **not exposed over Modbus** (the Modbus protocol only offers read-only power limits and no reserve register), so they are read and written through the **same private web-portal API the app uses**, signed in with your **normal atmocecloud.com login (email + password)** — no partner API keys required. Enter your login in **Settings → Devices & Services → Atmoce Battery → Configure**. The values are read once at startup and refreshed after each change (no continuous polling). If no login is configured, these three entities stay unavailable and everything else (local Modbus) works normally.

| Entity | Portal field | Description |
|--------|--------------|-------------|
| `number.atmoce_charge_limit_soc` | `storageChargeCutoffSoc` | SOC at which charging stops (80–100 %) |
| `number.atmoce_discharge_limit_soc` | `storageDischargeCutoffSoc` | SOC at which discharging stops (0–30 %) |
| `number.atmoce_backup_reserve_soc` | `backupSoc` | Reserve kept for backup — the battery stops discharging here except during a grid outage (range between the two limits above) |

> This uses an unofficial API and may change if Atmoce updates their portal.

---

## Example automation — charge to 80 % at cheap-rate hours

```yaml
automation:
  - alias: "Atmoce — Force charge at night rate"
    trigger:
      - platform: time
        at: "01:00:00"
    action:
      - service: switch.turn_on
        target:
          entity_id: switch.atmoce_remote_control
      - delay: "00:00:02"
      - service: number.set_value
        target:
          entity_id: number.atmoce_forced_target_soc
        data:
          value: 80
      - service: number.set_value
        target:
          entity_id: number.atmoce_forced_power
        data:
          value: 3.5
      - service: select.select_option
        target:
          entity_id: select.atmoce_forced_mode_type
        data:
          option: "SOC objetivo"
      - service: select.select_option
        target:
          entity_id: select.atmoce_battery_command
        data:
          option: "Carga forzada"

  - alias: "Atmoce — Return to auto when SOC reached"
    trigger:
      - platform: numeric_state
        entity_id: sensor.atmoce_battery_soc
        above: 80
    action:
      - service: select.select_option
        target:
          entity_id: select.atmoce_battery_command
        data:
          option: "Administrado por batería"
```

---

## FAQ

**The integration fails to connect during setup.**
Make sure the gateway (MC100 / MG100) has Modbus TCP enabled on port 502. This is the default factory setting. If you changed the port, enter it in the setup wizard.

**Buttons / controls don't appear in Home Assistant.**
Reload the integration from Settings → Devices & Services → Atmoce Battery → ⋮ → Reload. If the problem persists, restart Home Assistant.

**The battery commands have no effect.**
The `switch.atmoce_remote_control` must be turned **ON** before sending any charge/discharge command. The battery ignores Modbus write commands when in local mode.

**Sensors show "unavailable" after a few hours.**
The gateway has stopped answering over Modbus. The Cloud fallback covers this, but it needs partner Open API keys (`app_key` / `app_secret`) that do not ship with the hardware — per the Open API manual §3.1.2 the installer requests them by email from Atmoce support. Without them, check the gateway's network connection instead; the fallback cannot be enabled.

**Where do I get the app_key and app_secret?**
You almost certainly do not need them: the battery SOC limits use your ordinary atmocecloud.com login, not these. They exist only for the Cloud monitoring fallback, are meant for installers managing several sites, and are issued by Atmoce support on request. There is no self-service page that generates them.

**How do I know if data is coming from Modbus or Cloud?**
Check `sensor.atmoce_active_data_source` — it shows `Modbus` or `Cloud`.

**Autonomy hours sensor is unavailable.**
The sensor needs at least a few minutes of data to calculate a rolling average consumption. It will appear automatically after the first valid readings.

---

## Contributing

Pull requests are welcome. No need to open an issue first — just submit the PR. ATMOCE technical documentation on Cloud API and MODBUS protocol are uploaded in the project wiki for reference.

## License

Public domain — see [LICENSE](LICENSE). No rights reserved.
