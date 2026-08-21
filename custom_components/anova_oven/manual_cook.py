"""Builds ad-hoc single-stage cook payloads for live setpoint changes.

The Anova protocol has exactly two commands: CMD_APO_START (replace the whole
active cook with a new stage list + new cookId) and CMD_APO_STOP. There's no
partial-update command — nothing in AnovaOvenService.ts suggests one exists.
So when the climate/humidifier/fan entities let you drag a setpoint while the
oven is already cooking, "applying" that change means rebuilding the
currently-running stage from live state and re-issuing CMD_APO_START with
just the changed field swapped in. This is inferred from the protocol's
shape, not confirmed against a real oven — worth watching the first time you
use it live.

All three entities stage their pending change on the shared `PendingManualStage`
living on `AnovaOven.pending` (see api.py) rather than keeping their own state,
so turning the oven on from *any* of them (climate hvac_mode, humidifier
turn_on, fan turn_on) picks up whatever the others have staged too.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, fields
from typing import Any

from .util import get_path

# A reasonable starting point when there's no live state to derive from yet
# (e.g. the oven has never run a cook since HA connected). Same bake profile
# as const.POWER_ON_STAGES's second stage.
_FALLBACK_STAGE: dict[str, Any] = {
    "title": "Manual",
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
    "steamGenerators": {"mode": "relative-humidity", "relativeHumidity": {"setpoint": 0}},
}


@dataclass
class PendingManualStage:
    """Setpoint changes staged while idle, or about to be sent immediately
    while already cooking."""

    temperature_celsius: float | None = None
    humidity_percent: float | None = None
    steam_mode: str | None = None  # "relative-humidity" | "steam-percentage"
    fan_speed: float | None = None

    def is_empty(self) -> bool:
        return not any(getattr(self, f.name) is not None for f in fields(self))

    def clear(self) -> None:
        for f in fields(self):
            setattr(self, f.name, None)


def derive_current_stage(state: dict[str, Any] | None) -> dict[str, Any] | None:
    """Build a StagesEntity-shaped dict from live `nodes.*` readings.

    Always reads live actuator state rather than a locally cached value, so
    this reflects whatever's actually running — a named recipe, a previous
    manual change, or another client (the Anova app) changing things —
    instead of drifting from reality. Returns None if there isn't enough live
    data yet to build a valid stage from.
    """
    nodes = get_path(state, "nodes")
    if not nodes:
        return None
    bulbs = nodes.get("temperatureBulbs") or {}
    mode = bulbs.get("mode")
    if mode not in ("dry", "wet"):
        return None
    branch = bulbs.get(mode) or {}
    setpoint = branch.get("setpoint") or branch.get("current")
    if not setpoint:
        return None

    heating = nodes.get("heatingElements") or {}
    fan = nodes.get("fan") or {}
    vent = nodes.get("vent") or {}
    steam = nodes.get("steamGenerators") or {}

    stage: dict[str, Any] = {
        "title": "Manual",
        "type": "cook",
        "userActionRequired": False,
        "temperatureBulbs": {
            "mode": mode,
            mode: {
                "setpoint": {
                    "celsius": setpoint.get("celsius"),
                    "fahrenheit": setpoint.get("fahrenheit"),
                }
            },
        },
        "heatingElements": {
            part: {"on": bool((heating.get(part) or {}).get("on"))}
            for part in ("top", "bottom", "rear")
        },
        "fan": {"speed": fan.get("speed", 0)},
        "vent": {"open": bool(vent.get("open"))},
    }

    steam_mode = steam.get("mode")
    if steam_mode == "steam-percentage":
        stage["steamGenerators"] = {
            "mode": "steam-percentage",
            "steamPercentage": {
                "setpoint": get_path(steam, "steamPercentage", "setpoint") or 0
            },
        }
    else:
        stage["steamGenerators"] = {
            "mode": "relative-humidity",
            "relativeHumidity": {
                "setpoint": get_path(steam, "relativeHumidity", "setpoint") or 0
            },
        }
    return stage


def _with_temperature(stage: dict[str, Any], celsius: float) -> dict[str, Any]:
    stage = copy.deepcopy(stage)
    mode = stage["temperatureBulbs"]["mode"]
    stage["temperatureBulbs"][mode]["setpoint"] = {
        "celsius": round(celsius, 2),
        "fahrenheit": round(celsius * 9 / 5 + 32, 1),
    }
    return stage


def _with_humidity(
    stage: dict[str, Any], percent: float, steam_mode: str | None
) -> dict[str, Any]:
    stage = copy.deepcopy(stage)
    mode = steam_mode or get_path(stage, "steamGenerators", "mode") or "relative-humidity"
    key = "steamPercentage" if mode == "steam-percentage" else "relativeHumidity"
    stage["steamGenerators"] = {"mode": mode, key: {"setpoint": percent}}
    return stage


def _with_fan_speed(stage: dict[str, Any], speed: float) -> dict[str, Any]:
    stage = copy.deepcopy(stage)
    stage["fan"] = {"speed": speed}
    return stage


def build_stage(
    state: dict[str, Any] | None, pending: PendingManualStage
) -> dict[str, Any]:
    """Combine live actuator state with any staged overrides into one ad-hoc
    cook stage, ready for AnovaCloudHub.async_start_cook()."""
    stage = derive_current_stage(state) or copy.deepcopy(_FALLBACK_STAGE)
    if pending.temperature_celsius is not None:
        stage = _with_temperature(stage, pending.temperature_celsius)
    if pending.humidity_percent is not None or pending.steam_mode is not None:
        current = stage.get("steamGenerators") or {}
        mode = pending.steam_mode or current.get("mode", "relative-humidity")
        key = "steamPercentage" if mode == "steam-percentage" else "relativeHumidity"
        percent = pending.humidity_percent
        if percent is None:
            percent = get_path(current, key, "setpoint") or 0
        stage = _with_humidity(stage, percent, mode)
    if pending.fan_speed is not None:
        stage = _with_fan_speed(stage, pending.fan_speed)
    return stage
