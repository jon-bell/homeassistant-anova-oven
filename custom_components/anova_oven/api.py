"""Anova cloud client: Firebase login + persistent Protocol V2 websocket.

Ports src/AnovaOvenService.ts and the AnovaOven class from
homebridge-plugin-anova-toast. Notable differences from the Node original:

- Uses HA's shared aiohttp session for both the Firebase REST login and the
  websocket, instead of `axios` + `ws`. No extra pip requirement.
- The plugin re-logs-in and opens a fresh socket on every retried command
  (`sendOvenCommandWithRetries` calls `this.login()`). Here a single background
  task (`_run`) owns the socket and reconnects with backoff on any drop;
  `async_send_command_with_retries` just waits for that task to reconnect
  between attempts, so there's one reconnect path instead of two.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .const import (
    AUTH_TIMEOUT,
    FIREBASE_SIGN_IN_URL,
    RECONNECT_MAX_DELAY,
    RECONNECT_MIN_DELAY,
    SIGNAL_OVEN_UPDATE,
    WS_PROTOCOL,
    WS_URL,
)
from .manual_cook import PendingManualStage, build_stage

_LOGGER = logging.getLogger(__name__)


class AnovaApiError(Exception):
    """Generic Anova cloud API error."""


class AnovaAuthError(AnovaApiError):
    """Firebase rejected the email/password."""


def _steam_generators_equal(
    a: dict[str, Any] | None, b: dict[str, Any] | None
) -> bool:
    if not a and not b:
        return True
    if not a or not b:
        return False
    if a.get("mode") != b.get("mode"):
        return False
    mode = a.get("mode")
    if mode == "steam-percentage":
        return (a.get("steamPercentage") or {}).get("setpoint") == (
            b.get("steamPercentage") or {}
        ).get("setpoint")
    if mode == "relative-humidity":
        return (a.get("relativeHumidity") or {}).get("setpoint") == (
            b.get("relativeHumidity") or {}
        ).get("setpoint")
    raise ValueError(f"Unknown steam mode {mode}")


def _temperature_bulbs_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("mode") != b.get("mode"):
        return False
    mode = a.get("mode")
    if mode == "dry":
        return a["dry"]["setpoint"]["celsius"] == b["dry"]["setpoint"]["celsius"]
    if mode == "wet":
        return a["wet"]["setpoint"]["celsius"] == b["wet"]["setpoint"]["celsius"]
    raise ValueError(f"Unknown temperature bulb mode {mode}")


def stages_equal(stage1: dict[str, Any], stage2: dict[str, Any]) -> bool:
    """Port of stagesEqual() in AnovaOvenService.ts.

    Compares by content, not by stage/cook `id` — used to tell whether the
    oven's currently-running cook is the one a given recipe switch represents.
    """
    return (
        stage1["fan"]["speed"] == stage2["fan"]["speed"]
        and stage1["heatingElements"]["bottom"]["on"]
        == stage2["heatingElements"]["bottom"]["on"]
        and stage1["heatingElements"]["rear"]["on"]
        == stage2["heatingElements"]["rear"]["on"]
        and stage1["heatingElements"]["top"]["on"]
        == stage2["heatingElements"]["top"]["on"]
        and _steam_generators_equal(
            stage1.get("steamGenerators"), stage2.get("steamGenerators")
        )
        and _temperature_bulbs_equal(
            stage1["temperatureBulbs"], stage2["temperatureBulbs"]
        )
        and stage1["vent"]["open"] == stage2["vent"]["open"]
    )


async def async_fetch_id_token(
    session: aiohttp.ClientSession, email: str, password: str
) -> str:
    """Exchange email/password for a Firebase idToken.

    Standalone so both AnovaCloudHub and the config flow's credential check
    (which doesn't need a full hub) can call it without duplicating the
    Firebase REST call.
    """
    try:
        async with session.post(
            FIREBASE_SIGN_IN_URL,
            json={"email": email, "password": password, "returnSecureToken": True},
        ) as resp:
            if resp.status == 400:
                raise AnovaAuthError("Anova rejected the email/password")
            resp.raise_for_status()
            data = await resp.json()
    except aiohttp.ClientError as err:
        raise AnovaApiError(f"Cannot reach Anova/Firebase auth: {err}") from err
    return data["idToken"]


class AnovaOven:
    """Live state for one oven. Port of the AnovaOven class in the plugin."""

    def __init__(self, cooker_id: str, name: str) -> None:
        self.cooker_id = cooker_id
        self.name = name
        self.state: dict[str, Any] | None = None
        # Setpoint changes staged by climate/humidifier/fan; see manual_cook.py.
        self.pending = PendingManualStage()

    @property
    def system_info(self) -> dict[str, Any]:
        return (self.state or {}).get("systemInfo", {})

    @property
    def online(self) -> bool:
        return bool(self.system_info.get("online"))

    @property
    def mode(self) -> str | None:
        state = self.state
        return state["state"]["mode"] if state else None

    @property
    def is_on(self) -> bool:
        """Port of AnovaOven.isOn — true whenever any cook is active."""
        return self.mode == "cook"

    def is_cooking_stages(self, stages: list[dict[str, Any]]) -> bool:
        """Port of AnovaOven.isCooking() — true if the active cook matches `stages`."""
        cook = (self.state or {}).get("cook")
        if not cook:
            return False
        current_stages = cook.get("stages", [])
        if len(current_stages) != len(stages):
            return False
        return all(
            stages_equal(want, have)
            for want, have in zip(stages, current_stages, strict=True)
        )


class AnovaCloudHub:
    """Owns the Firebase login and the persistent Protocol V2 websocket."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, email: str, password: str
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._email = email
        self._password = password
        self.ovens: dict[str, AnovaOven] = {}

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._pending_names: dict[str, str] = {}
        self._pending_requests: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._oven_listeners: list[Callable[[AnovaOven], None]] = []

        self._connected_event = asyncio.Event()
        self._run_task: asyncio.Task | None = None
        self._stopped = False

        self._session = async_get_clientsession(hass)

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    def async_add_oven_listener(
        self, listener: Callable[[AnovaOven], None]
    ) -> Callable[[], None]:
        """Register a callback fired once for each oven discovered from now on."""
        self._oven_listeners.append(listener)

        def _remove() -> None:
            self._oven_listeners.remove(listener)

        return _remove

    async def async_start(self) -> None:
        """Validate credentials once, then hand the socket to a background task."""
        await self._login_token()  # raises AnovaAuthError / AnovaApiError early
        self._run_task = self._entry.async_create_background_task(
            self.hass, self._run(), f"anova_oven_listen_{self._entry.entry_id}"
        )
        try:
            async with asyncio.timeout(AUTH_TIMEOUT):
                await self._connected_event.wait()
        except TimeoutError as err:
            raise AnovaApiError(
                "Timed out waiting for the Anova cloud websocket to authenticate"
            ) from err

    async def async_stop(self) -> None:
        self._stopped = True
        if self._run_task:
            self._run_task.cancel()
        if self._ws is not None:
            await self._ws.close()

    async def _login_token(self) -> str:
        return await async_fetch_id_token(self._session, self._email, self._password)

    async def _run(self) -> None:
        """Background reconnect loop — owns `self._ws` for the entry's lifetime."""
        delay = RECONNECT_MIN_DELAY
        while not self._stopped:
            try:
                await self._connect_and_listen()
                delay = RECONNECT_MIN_DELAY
            except AnovaAuthError:
                _LOGGER.error(
                    "Anova cloud rejected our credentials; starting reauth"
                )
                self._entry.async_start_reauth(self.hass)
                return
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - reconnect loop must not die
                _LOGGER.warning(
                    "Anova cloud websocket disconnected, reconnecting in %ss",
                    delay,
                    exc_info=True,
                )
            finally:
                self._ws = None
                self._connected_event.clear()
            if self._stopped:
                return
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)

    async def _connect_and_listen(self) -> None:
        token = await self._login_token()
        url = f"{WS_URL}?token={token}&supportedAccessories=APO&platform=android"
        async with self._session.ws_connect(
            url, protocols=(WS_PROTOCOL,), heartbeat=30
        ) as ws:
            self._ws = ws
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._handle_message(json.loads(msg.data))
                elif msg.type in (
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                ):
                    break
        raise AnovaApiError("Anova cloud websocket closed")

    def _handle_message(self, message: dict[str, Any]) -> None:
        command = message.get("command")
        if command == "EVENT_APO_WIFI_LIST":
            for item in message["payload"]:
                cooker_id = item["cookerId"]
                oven = self.ovens.get(cooker_id)
                if oven:
                    oven.name = item["name"]
                else:
                    self._pending_names[cooker_id] = item["name"]
            if not self._connected_event.is_set():
                self._connected_event.set()
        elif command == "EVENT_APO_STATE":
            payload = message["payload"]
            cooker_id = payload["cookerId"]
            oven = self.ovens.get(cooker_id)
            is_new = oven is None
            if is_new:
                name = self._pending_names.get(
                    cooker_id, f"Oven {cooker_id[:4]}"
                )
                oven = AnovaOven(cooker_id, name)
                self.ovens[cooker_id] = oven
            oven.state = payload["state"]
            if is_new:
                for listener in list(self._oven_listeners):
                    listener(oven)
            async_dispatcher_send(self.hass, f"{SIGNAL_OVEN_UPDATE}_{cooker_id}")
        elif command == "RESPONSE":
            future = self._pending_requests.pop(message["requestId"], None)
            if future and not future.done():
                future.set_result(message["payload"])
        elif command == "EVENT_USER_STATE":
            pass  # not surfaced; Alexa/Google Home link status, irrelevant here
        else:
            _LOGGER.debug("Unknown Anova websocket message: %s", message)

    async def _send_command_once(
        self, command: str, payload: dict[str, Any], timeout: float = 5
    ) -> dict[str, Any]:
        if not self.connected:
            raise AnovaApiError("Anova cloud websocket is not connected")
        request_id = str(uuid.uuid4())
        future: asyncio.Future[dict[str, Any]] = self.hass.loop.create_future()
        self._pending_requests[request_id] = future
        msg = {"command": command, "payload": payload, "requestId": request_id}
        try:
            await self._ws.send_str(json.dumps(msg))
            async with asyncio.timeout(timeout):
                result = await future
        except TimeoutError:
            raise  # let the retry loop's own except clause see this as-is
        except (aiohttp.ClientError, OSError, RuntimeError) as err:
            # Covers a mid-send socket drop (send_str on a closing connection
            # raises here, not via the message loop) so it retries instead of
            # propagating a raw connection error to the entity.
            raise AnovaApiError(f"Failed sending command {command}: {err}") from err
        finally:
            self._pending_requests.pop(request_id, None)
        if result.get("status") != "ok":
            raise AnovaApiError(f"Command {command} failed: {result}")
        return result

    async def async_send_command_with_retries(
        self, command: str, payload: dict[str, Any], retries: int = 3
    ) -> dict[str, Any]:
        """Port of sendOvenCommandWithRetries(); see module docstring for the
        one behavioral difference (reconnect owned by `_run`, not re-dialed here).
        """
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return await self._send_command_once(command, payload)
            except (AnovaApiError, TimeoutError) as err:
                last_err = err
                if attempt < retries:
                    _LOGGER.debug(
                        "Command %s failed (attempt %s/%s), waiting for reconnect: %s",
                        command,
                        attempt + 1,
                        retries + 1,
                        err,
                    )
                    await self._wait_reconnected(timeout=15)
        raise AnovaApiError(
            f"Command {command} failed after {retries + 1} attempts"
        ) from last_err

    async def _wait_reconnected(self, timeout: float) -> None:
        if self.connected:
            return
        try:
            async with asyncio.timeout(timeout):
                await self._connected_event.wait()
        except TimeoutError:
            pass  # let the caller's own retry loop decide whether to give up

    async def async_start_cook(
        self, oven: AnovaOven, stages: list[dict[str, Any]]
    ) -> str:
        """Port of AnovaOven.startCook(). Assigns fresh stage/cook UUIDs."""
        stages = copy.deepcopy(stages)
        for stage in stages:
            stage.setdefault("id", str(uuid.uuid4()))
        cook_id = str(uuid.uuid4())
        await self.async_send_command_with_retries(
            "CMD_APO_START",
            {
                "payload": {"cookId": cook_id, "stages": stages},
                "type": "CMD_APO_START",
                "id": oven.cooker_id,
            },
        )
        # Any successful start makes prior staged climate/humidifier/fan
        # overrides moot — it either consumed them (async_apply_manual_stage)
        # or replaced them outright (a named recipe, Power).
        oven.pending.clear()
        return cook_id

    async def async_stop_cook(self, oven: AnovaOven) -> None:
        """Port of AnovaOven.stopCook()."""
        await self.async_send_command_with_retries(
            "CMD_APO_STOP",
            {"type": "CMD_APO_STOP", "id": oven.cooker_id},
        )
        oven.pending.clear()

    async def async_apply_manual_stage(self, oven: AnovaOven) -> None:
        """Start/replace the active cook using live state plus whatever
        climate/humidifier/fan have staged in `oven.pending`."""
        stage = build_stage(oven.state, oven.pending)
        await self.async_start_cook(oven, [stage])
