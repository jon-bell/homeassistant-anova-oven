"""Small shared helpers for reading the (undocumented) Anova state payload."""

from __future__ import annotations

from typing import Any


def get_path(source: dict[str, Any] | None, *path: str) -> Any:
    """Walk a chain of dict keys, returning None on any missing/None step.

    Used everywhere the sensor/binary_sensor platforms read EVENT_APO_STATE
    fields, since the cloud protocol is reverse-engineered and undocumented
    upstream — a missing key should degrade an entity to `unknown`, not raise.
    """
    value: Any = source
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value
