"""A ThinkGear Connector look-alike, so apps written for NeuroSky MindWave headsets work as-is.

Clients connect over TCP and usually send an authorisation and a configuration message, which
are ignored. Once a second every client gets a JSON packet ending in a carriage return.
"""

import asyncio
import contextlib
import json

from neurostate.config import ThinkGearConfig
from neurostate.outputs.tcp import TcpBroadcaster
from neurostate.schema import BrainState, State

_EEG_POWER_BANDS = (
    "delta", "theta", "lowAlpha", "highAlpha", "lowBeta", "highBeta", "lowGamma", "highGamma",
)  # fmt: skip


def poor_signal_level(state: BrainState | None) -> int:
    """ThinkGear's signal problem scale, 0-200. It is exactly 0 whenever the values are usable,
    because many ThinkGear apps treat anything above 0 as "not connected"."""
    if state is None or state.state is State.NO_SIGNAL:
        return 200
    if state.state is State.POOR_SIGNAL:
        return min(199, max(1, round(200 * (1 - state.quality / 100))))
    return 0


def thinkgear_packet(state: BrainState | None) -> dict[str, object]:
    """The packet for the latest update, or for none yet.

    eSense values run from 1 to 100; ThinkGear uses 0 to mean the signal is too poor to tell.
    """
    poor = poor_signal_level(state)

    def esense(value: float) -> int:
        return 0 if poor else min(100, max(1, round(value)))

    return {
        "eSense": {
            "attention": esense(state.attention) if state else 0,
            "meditation": esense(state.relaxation) if state else 0,
        },
        # Band powers come with the EEG pipeline (milestone M4); until then they're all 0.
        "eegPower": dict.fromkeys(_EEG_POWER_BANDS, 0),
        "poorSignalLevel": poor,
    }


class ThinkGearServer(TcpBroadcaster):
    key = "thinkgear"

    def __init__(self, config: ThinkGearConfig, interval_s: float = 1.0):
        super().__init__(config.host, config.port)
        self._interval_s = interval_s
        self._latest: BrainState | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def description(self) -> str:
        return f"ThinkGear-compatible TCP on {self.address}"

    async def start(self) -> None:
        await super().start()
        self._task = asyncio.create_task(self._send_regularly())

    def publish(self, state: BrainState) -> None:
        self._latest = state

    async def _send_regularly(self) -> None:
        while True:
            await asyncio.sleep(self._interval_s)
            packet = json.dumps(thinkgear_packet(self._latest), separators=(",", ":"))
            self.send(packet.encode() + b"\r")

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await super().close()
