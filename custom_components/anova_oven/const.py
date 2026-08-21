"""Constants for the Anova Oven integration.

Ported from homebridge-plugin-anova-toast
(https://github.com/jon-bell/homebridge-plugin-anova-toast) — same cloud protocol,
same default recipe set, same "Power" stage sequence. See README.md in this directory
for what changed in the port.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "anova_oven"

CONF_RECIPES: Final = "recipes"

# Firebase client API key embedded in the Anova Oven Android app. Not a secret —
# it identifies the Firebase project to Google's auth endpoint, gated by Firebase
# project rules, and ships in the plugin source and the public APK alike.
FIREBASE_SIGN_IN_URL: Final = (
    "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
    "?key=AIzaSyCGJwHXUhkNBdPkH3OAkjc9-3xMMjvanfU"
)

# Protocol V2, per the plugin's README and AnovaOvenService.ts. V1
# (wss://app.oven.anovaculinary.io/) is not implemented — the plugin moved off
# it in its 1.1.0 release and there's no reason to carry it forward here.
WS_URL: Final = "wss://devices.anovaculinary.io/"
WS_PROTOCOL: Final = "ANOVA_V2"

SIGNAL_OVEN_UPDATE: Final = f"{DOMAIN}_oven_update"

COMMAND_TIMEOUT: Final = timedelta(seconds=5)
COMMAND_RETRIES: Final = 3
RECONNECT_MIN_DELAY: Final = 5
RECONNECT_MAX_DELAY: Final = 300
AUTH_TIMEOUT: Final = 15

# The "Power" switch's on-sequence: preheat to 350F then hold, bottom element,
# low fan. Verbatim from POWER_ON_DEFAULT_STAGES in the plugin's
# src/platformAccessory.ts — stage `id`s are generated fresh per cook.
POWER_ON_STAGES: Final = [
    {
        "title": "Pre-heat",
        "type": "preheat",
        "userActionRequired": False,
        "temperatureBulbs": {
            "mode": "dry",
            "dry": {"setpoint": {"celsius": 176.67, "fahrenheit": 350}},
        },
        "heatingElements": {
            "top": {"on": False},
            "bottom": {"on": True},
            "rear": {"on": False},
        },
        "fan": {"speed": 33},
        "vent": {"open": False},
    },
    {
        "title": "Bake",
        "type": "cook",
        "userActionRequired": False,
        "temperatureBulbs": {
            "mode": "dry",
            "dry": {"setpoint": {"celsius": 176.67, "fahrenheit": 350}},
        },
        "heatingElements": {
            "top": {"on": False},
            "bottom": {"on": True},
            "rear": {"on": False},
        },
        "fan": {"speed": 33},
        "vent": {"open": False},
    },
]

# The four favorite recipes shipped in the plugin's config.json.example, verbatim.
# Editable per-install via the integration's Options flow.
DEFAULT_RECIPES: Final = [
    {
        "name": "Make Toast",
        "stages": [
            {
                "title": "Start Cook",
                "type": "cook",
                "userActionRequired": True,
                "temperatureBulbs": {
                    "mode": "dry",
                    "dry": {"setpoint": {"celsius": 250, "fahrenheit": 482}},
                },
                "timer": {"initial": 180},
                "heatingElements": {
                    "top": {"on": True},
                    "bottom": {"on": False},
                    "rear": {"on": False},
                },
                "fan": {"speed": 0},
                "vent": {"open": False},
            },
            {
                "title": "Add Steam",
                "type": "cook",
                "userActionRequired": False,
                "temperatureBulbs": {
                    "mode": "dry",
                    "dry": {"setpoint": {"celsius": 250, "fahrenheit": 482}},
                },
                "steamGenerators": {
                    "mode": "steam-percentage",
                    "steamPercentage": {"setpoint": 100},
                },
                "timer": {"initial": 240},
                "heatingElements": {
                    "top": {"on": False},
                    "bottom": {"on": False},
                    "rear": {"on": True},
                },
                "fan": {"speed": 100},
                "vent": {"open": False},
            },
            {
                "title": "Cool Down",
                "type": "cook",
                "userActionRequired": False,
                "temperatureBulbs": {
                    "mode": "dry",
                    "dry": {"setpoint": {"celsius": 25, "fahrenheit": 77}},
                },
                "timer": {"initial": 60},
                "heatingElements": {
                    "top": {"on": False},
                    "bottom": {"on": True},
                    "rear": {"on": False},
                },
                "fan": {"speed": 0},
                "vent": {"open": False},
            },
        ],
    },
    {
        "name": "Bake",
        "stages": [
            {
                "title": "Pre-heat",
                "type": "preheat",
                "userActionRequired": False,
                "temperatureBulbs": {
                    "mode": "dry",
                    "dry": {"setpoint": {"celsius": 176.67, "fahrenheit": 350}},
                },
                "heatingElements": {
                    "top": {"on": False},
                    "bottom": {"on": True},
                    "rear": {"on": False},
                },
                "fan": {"speed": 33},
                "vent": {"open": False},
            },
            {
                "title": "Bake",
                "type": "cook",
                "userActionRequired": False,
                "temperatureBulbs": {
                    "mode": "dry",
                    "dry": {"setpoint": {"celsius": 176.67, "fahrenheit": 350}},
                },
                "heatingElements": {
                    "top": {"on": False},
                    "bottom": {"on": True},
                    "rear": {"on": False},
                },
                "fan": {"speed": 33},
                "vent": {"open": False},
            },
        ],
    },
    {
        "name": "Sous-Vide",
        "stages": [
            {
                "title": "Pre-heat",
                "type": "preheat",
                "userActionRequired": False,
                "temperatureBulbs": {
                    "mode": "wet",
                    "wet": {"setpoint": {"celsius": 54.44, "fahrenheit": 130}},
                },
                "steamGenerators": {
                    "mode": "relative-humidity",
                    "relativeHumidity": {"setpoint": 100},
                },
                "heatingElements": {
                    "top": {"on": False},
                    "bottom": {"on": False},
                    "rear": {"on": True},
                },
                "fan": {"speed": 100},
                "vent": {"open": False},
            },
            {
                "title": "Sous-Vide",
                "type": "cook",
                "userActionRequired": False,
                "temperatureBulbs": {
                    "mode": "wet",
                    "wet": {"setpoint": {"celsius": 54.44, "fahrenheit": 130}},
                },
                "steamGenerators": {
                    "mode": "relative-humidity",
                    "relativeHumidity": {"setpoint": 100},
                },
                "heatingElements": {
                    "top": {"on": False},
                    "bottom": {"on": False},
                    "rear": {"on": True},
                },
                "fan": {"speed": 100},
                "vent": {"open": False},
            },
        ],
    },
    {
        "name": "Air Fry",
        "stages": [
            {
                "title": "Pre-heat",
                "type": "preheat",
                "userActionRequired": False,
                "temperatureBulbs": {
                    "mode": "dry",
                    "dry": {"setpoint": {"celsius": 218.33, "fahrenheit": 425}},
                },
                "heatingElements": {
                    "top": {"on": False},
                    "bottom": {"on": False},
                    "rear": {"on": True},
                },
                "fan": {"speed": 100},
                "vent": {"open": False},
            },
            {
                "title": "Air Fry",
                "type": "cook",
                "userActionRequired": False,
                "temperatureBulbs": {
                    "mode": "dry",
                    "dry": {"setpoint": {"celsius": 218.33, "fahrenheit": 425}},
                },
                "heatingElements": {
                    "top": {"on": False},
                    "bottom": {"on": False},
                    "rear": {"on": True},
                },
                "fan": {"speed": 100},
                "vent": {"open": False},
            },
        ],
    },
]
