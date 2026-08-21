# Anova Oven for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A native Home Assistant integration for the **Anova Precision Oven**, talking Anova's cloud
protocol directly — no Homebridge, no HomeKit bridge in the middle. It's a port of
[homebridge-plugin-anova-toast](https://github.com/jon-bell/homebridge-plugin-anova-toast),
covering everything that plugin did (power, favorite recipes) plus live temperature/humidity/fan
control that the HomeKit switch model couldn't express.

There is still no local API for the Precision Oven — Anova's app doesn't talk to the oven
directly on your LAN, and neither does this. Everything here rides the same cloud
websocket the official app and the Homebridge plugin use.

## Entities

Per oven:

| Entity | Domain | What it does |
|---|---|---|
| `climate.<oven>` | climate | The oven's primary entity: `hvac_mode` off/heat, live `target_temperature`, and your favorite recipes as `preset_mode` options |
| `humidifier.<oven>_steam` | humidifier | `target_humidity` 0–100 plus a `mode` toggle between the oven's two steam modes |
| `fan.<oven>` | fan | Convection fan speed, 0–100% |
| `switch.<oven>_power` | switch | On while any cook is active; turns on a default preheat→bake sequence |
| `switch.<oven>_<recipe>` | switch | One per favorite recipe (defaults: Make Toast, Bake, Sous-Vide, Air Fry) |
| `sensor.<oven>_mode` / `_temperature` / `_target_temperature` / `_timer_remaining` / `_firmware_version` | sensor | Telemetry |
| `binary_sensor.<oven>_door` / `_water_tank_empty` / `_online` / `_problem` | binary_sensor | Door, water tank, connectivity, aggregate fault flag |

### Live setpoint changes

The Anova protocol only has two commands: replace the whole active cook with a new stage list,
or stop it — there's no partial-update command. So dragging `climate.target_temperature`,
`humidifier.target_humidity`/`mode`, or `fan.percentage` while the oven is already cooking
rebuilds the running stage from live state with just that one field changed, and re-issues a
start command. This mirrors how the official app almost certainly does live adjustment too, but
it's inferred from the protocol's shape rather than documented — worth watching the first time
you use it.

Change a setpoint while the oven is **idle** and it's just staged (shown optimistically in the
entity); it applies once you turn the oven on via `climate.hvac_mode`, a preset, or the
humidifier/fan `turn_on`. All three entities share one staging area per oven, so setting more
than one before turning the oven on combines into a single cook rather than each overwriting
the other.

### Editing the recipe list

Settings → Devices & Services → Anova Oven → **Configure**. One textarea, JSON — a list of
`{"name": ..., "stages": [...]}` objects. The stage shape matches the Anova app's own cook
programs (temperature, heating elements, fan, vent, steam, optional timer per stage); the
[original plugin's `config.json.example`](https://github.com/jon-bell/homebridge-plugin-anova-toast/blob/main/config.json.example)
is the best field reference. Changing this reloads the integration to rebuild the switches.

## Installation

### HACS (recommended)

This isn't in the default HACS store. Add it as a custom repository:

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Repository: `https://github.com/jon-bell/homeassistant-anova-oven`, Category: **Integration**
3. Install **Anova Oven**, then restart Home Assistant.

### Manual

Copy `custom_components/anova_oven/` from this repo into your Home Assistant `config/custom_components/`
directory, then restart.

## Setup

Settings → Devices & Services → Add Integration → **Anova Oven**. Enter the email/password for
the Anova account the oven is registered to — the same login as the Anova app. One config entry
per Anova account; every oven on that account shows up as its own device once its first state
push arrives after connecting.

No extra Python dependencies — the Firebase login and the websocket both ride Home Assistant's
existing shared `aiohttp` session.

## Protocol notes

This is a reverse-engineered API (see the plugin's README for the mitmproxy writeup that
originally figured it out) — nothing here is officially documented by Anova. In particular the
plugin's own type definitions don't fully pin down every field (e.g. a duplicated `WetStatus`
declaration means the wet-bulb setpoint's presence in the state payload isn't confirmed the way
the dry-bulb one is). Sensor/binary_sensor reads degrade to `unknown` on a missing key rather
than raising, so an `unknown` value where you'd expect data is worth checking against the raw
state payload before assuming a bug.

Auth failures trigger Home Assistant's standard reauth flow (a "reconfigure" prompt under
Settings → Devices & Services) rather than failing silently.

## Disclaimer

Not affiliated with or endorsed by Anova Culinary. "Anova" and "Precision Oven" are trademarks
of their respective owner, used here only to describe compatibility.

## License

[Apache License 2.0](LICENSE).
