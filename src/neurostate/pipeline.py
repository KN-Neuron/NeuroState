"""The service loop: on a fixed tick, get the latest values and publish them to every output."""

import asyncio
import contextlib
from collections.abc import Callable

from pylsl import local_clock

from neurostate.config import OutputsConfig
from neurostate.outputs import Output
from neurostate.outputs.json_server import JsonTcpServer, WebSocketServer
from neurostate.outputs.lsl_outlet import LslOutlet
from neurostate.outputs.thinkgear_server import ThinkGearServer
from neurostate.schema import BrainState

# Gets the values for the current time, as an LSL timestamp.
Estimator = Callable[[float], BrainState]


class OutputStartError(RuntimeError):
    pass


def make_outputs(config: OutputsConfig) -> list[Output]:
    outputs: list[Output] = []
    if config.lsl.enabled:
        outputs.append(LslOutlet(config.lsl, config.rate_hz))
    if config.json_tcp.enabled:
        outputs.append(JsonTcpServer(config.json_tcp))
    if config.websocket.enabled:
        outputs.append(WebSocketServer(config.websocket))
    if config.thinkgear.enabled:
        outputs.append(ThinkGearServer(config.thinkgear))
    return outputs


async def start_outputs(outputs: list[Output]) -> None:
    """Start every output, or none: if one fails, close the ones already started."""
    for i, output in enumerate(outputs):
        try:
            await output.start()
        except OSError as error:
            for started in outputs[:i]:
                await started.close()
            raise OutputStartError(
                f"Couldn't start the {output.key} output: {error}. Change outputs.{output.key} "
                f"in the config, or turn it off with outputs.{output.key}.enabled: false."
            ) from error


async def run_service(
    config: OutputsConfig,
    estimate: Estimator,
    *,
    on_started: Callable[[list[Output]], None] | None = None,
    stop: asyncio.Event | None = None,
) -> None:
    """Publish values at ``config.rate_hz`` until ``stop`` is set or the task is cancelled."""
    outputs = make_outputs(config)
    await start_outputs(outputs)
    if on_started is not None:
        on_started(outputs)

    stop = stop or asyncio.Event()
    loop = asyncio.get_running_loop()
    period = 1 / config.rate_hz
    next_tick = loop.time()
    try:
        while not stop.is_set():
            state = estimate(local_clock())
            for output in outputs:
                output.publish(state)
            # Schedule from the previous tick rather than from now, so the rate doesn't drift;
            # after a stall, carry on from now instead of catching up in a burst.
            next_tick = max(next_tick + period, loop.time())
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=next_tick - loop.time())
    finally:
        for output in outputs:
            await output.close()
