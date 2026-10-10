import asyncio
import itertools
import json
import time
import uuid

import pylsl
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from neurostate.config import (
    JsonTcpConfig,
    LslOutletConfig,
    OutputsConfig,
    ThinkGearConfig,
    WebSocketConfig,
)
from neurostate.estimators.fake import FakeStates
from neurostate.outputs.json_server import JsonTcpServer, WebSocketServer
from neurostate.outputs.lsl_outlet import LslOutlet
from neurostate.outputs.thinkgear_server import ThinkGearServer, poor_signal_level, thinkgear_packet
from neurostate.pipeline import OutputStartError, run_service, start_outputs
from neurostate.schema import BrainState, State

LOCAL = {"host": "127.0.0.1", "port": 0}


def make(**changes) -> BrainState:
    values = {
        "t": pylsl.local_clock(),
        "attention": 57.0,
        "relaxation": 41.0,
        "quality": 92.0,
        "state": State.OK,
        "calibrated": True,
    }
    return BrainState(**(values | changes))


async def wait_for_clients(server, n: int) -> None:
    async with asyncio.timeout(5):
        while server.n_clients < n:
            await asyncio.sleep(0.01)


def test_lsl_outlet_publishes_values_with_metadata():
    async def scenario():
        name = f"neurostate-test-{uuid.uuid4().hex[:8]}"
        outlet = LslOutlet(LslOutletConfig(name=name), rate_hz=4)
        await outlet.start()
        [info] = pylsl.resolve_byprop("name", name, timeout=10)
        inlet = pylsl.StreamInlet(info)
        full = inlet.info(timeout=5)
        inlet.open_stream(timeout=5)
        state = make(state=State.UNCALIBRATED, calibrated=False)
        outlet.publish(state)
        sample, timestamp = inlet.pull_sample(timeout=5)
        await outlet.close()
        return full, sample, timestamp, state

    info, sample, timestamp, state = asyncio.run(scenario())

    assert info.type() == "BrainState"
    assert info.nominal_srate() == 4
    assert info.desc().child_value("schema_version") == "1"
    channel = info.desc().child("channels").child("channel")
    labels = []
    while not channel.empty():
        labels.append(channel.child_value("label"))
        channel = channel.next_sibling()
    assert labels == ["attention", "relaxation", "quality", "state", "calibrated"]
    entry = info.desc().child("state_codes").child("state")
    codes = {}
    while not entry.empty():
        codes[entry.child_value("name")] = int(entry.child_value("code"))
        entry = entry.next_sibling()
    assert codes["uncalibrated"] == 3
    assert sample == [57.0, 41.0, 92.0, 3.0, 0.0]
    assert timestamp == pytest.approx(state.t)


def test_json_tcp_sends_one_line_per_update_to_every_client():
    async def scenario():
        server = JsonTcpServer(JsonTcpConfig(**LOCAL))
        await server.start()
        host, port = server.address.split(":")
        clients = [await asyncio.open_connection(host, int(port)) for _ in range(3)]
        await wait_for_clients(server, 3)
        clients[0][1].write(b'{"command": "ignored for now"}\n')
        for attention in (10, 20):
            server.publish(make(attention=attention))
        lines = [[await reader.readline() for _ in range(2)] for reader, _ in clients]
        for _, writer in clients:
            writer.close()
        await server.close()
        return lines

    for first, second in asyncio.run(scenario()):
        assert json.loads(first)["attention"] == 10
        assert json.loads(second)["attention"] == 20
        assert first.endswith(b"\n")


def test_json_tcp_keeps_serving_after_a_client_leaves():
    async def scenario():
        server = JsonTcpServer(JsonTcpConfig(**LOCAL))
        await server.start()
        host, port = server.address.split(":")
        _, leaving = await asyncio.open_connection(host, int(port))
        reader, staying = await asyncio.open_connection(host, int(port))
        await wait_for_clients(server, 2)
        leaving.close()
        async with asyncio.timeout(5):
            while server.n_clients > 1:
                await asyncio.sleep(0.01)
        server.publish(make())
        line = await reader.readline()
        staying.close()
        await server.close()
        return line

    assert json.loads(asyncio.run(scenario()))["state"] == "ok"


def test_websocket_sends_one_message_per_update_to_every_client():
    async def scenario():
        server = WebSocketServer(WebSocketConfig(**LOCAL))
        await server.start()
        url = server.description.removeprefix("WebSocket on ")
        clients = [await connect(url) for _ in range(3)]
        await wait_for_clients(server, 3)
        await clients[0].send("ignored for now")
        server.publish(make(relaxation=66.6))
        messages = [await client.recv() for client in clients]
        for client in clients:
            await client.close()
        await server.close()
        return messages

    for message in asyncio.run(scenario()):
        assert json.loads(message)["relaxation"] == 66.6


def test_websocket_allowed_origins_keep_out_other_pages():
    async def scenario():
        config = WebSocketConfig(allowed_origins=["http://localhost:5173"], **LOCAL)
        server = WebSocketServer(config)
        await server.start()
        url = server.description.removeprefix("WebSocket on ")
        allowed = await connect(url, origin="http://localhost:5173")
        no_origin = await connect(url)  # not a browser
        with pytest.raises(InvalidStatus):
            await connect(url, origin="https://example.com")
        await allowed.close()
        await no_origin.close()
        await server.close()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("state", "quality", "level"),
    [
        (State.OK, 92, 0),
        (State.UNCALIBRATED, 60, 0),
        (State.CALIBRATING, 80, 0),
        (State.POOR_SIGNAL, 35, 130),
        (State.POOR_SIGNAL, 100, 1),
        (State.POOR_SIGNAL, 0, 199),
        (State.NO_SIGNAL, 0, 200),
    ],
)
def test_poor_signal_level(state, quality, level):
    assert poor_signal_level(make(state=state, quality=quality)) == level


def test_thinkgear_packet_for_a_usable_signal():
    packet = thinkgear_packet(make(attention=57.4, relaxation=0.2))

    assert packet["eSense"] == {"attention": 57, "meditation": 1}
    assert packet["poorSignalLevel"] == 0
    assert set(packet["eegPower"]) == {
        "delta", "theta", "lowAlpha", "highAlpha", "lowBeta", "highBeta", "lowGamma", "highGamma",
    }  # fmt: skip


@pytest.mark.parametrize("state", [None, make(state=State.POOR_SIGNAL, quality=50)])
def test_thinkgear_packet_without_a_usable_signal_reports_esense_as_0(state):
    packet = thinkgear_packet(state)

    assert packet["eSense"] == {"attention": 0, "meditation": 0}
    assert packet["poorSignalLevel"] > 0


def test_thinkgear_server_sends_packets_ending_in_carriage_returns():
    async def scenario():
        server = ThinkGearServer(ThinkGearConfig(**LOCAL), interval_s=0.05)
        await server.start()
        host, port = server.address.split(":")
        reader, writer = await asyncio.open_connection(host, int(port))
        # What ThinkGear apps typically send first; it must not stop the packets.
        writer.write(b'{"appName":"Test","appKey":"0000"}')
        writer.write(b'{"enableRawOutput":false,"format":"Json"}')
        server.publish(make(attention=70))
        packets = [await reader.readuntil(b"\r") for _ in range(2)]
        writer.close()
        await server.close()
        return packets

    for packet in asyncio.run(scenario()):
        assert json.loads(packet)["eSense"]["attention"] == 70


def test_service_publishes_at_the_configured_rate_to_all_outputs():
    config = OutputsConfig(
        rate_hz=20,
        lsl=LslOutletConfig(name=f"neurostate-test-{uuid.uuid4().hex[:8]}"),
        json_tcp=JsonTcpConfig(**LOCAL),
        websocket=WebSocketConfig(**LOCAL),
        thinkgear=ThinkGearConfig(**LOCAL),
    )

    async def scenario():
        stop = asyncio.Event()
        started = asyncio.get_running_loop().create_future()
        service = asyncio.create_task(
            run_service(config, FakeStates(), on_started=started.set_result, stop=stop)
        )
        outputs = {output.key: output for output in await started}
        host, port = outputs["json_tcp"].address.split(":")
        reader, writer = await asyncio.open_connection(host, int(port))
        await wait_for_clients(outputs["json_tcp"], 1)
        websocket = await connect(outputs["websocket"].description.removeprefix("WebSocket on "))
        begin = time.monotonic()
        lines = [await reader.readline() for _ in range(10)]
        elapsed = time.monotonic() - begin
        message = await websocket.recv()
        stop.set()
        await service
        writer.close()
        return lines, elapsed, message

    lines, elapsed, message = asyncio.run(scenario())

    assert 0.35 < elapsed < 0.8  # 10 updates at 20 Hz
    stamps = [json.loads(line)["t"] for line in lines]
    assert all(b > a for a, b in itertools.pairwise(stamps))
    assert json.loads(message)["v"] == 1


def test_a_port_in_use_gives_a_clear_error_and_starts_nothing():
    async def scenario():
        blocker = JsonTcpServer(JsonTcpConfig(**LOCAL))
        await blocker.start()
        port = int(blocker.address.split(":")[1])
        first = WebSocketServer(WebSocketConfig(**LOCAL))
        clash = ThinkGearServer(ThinkGearConfig(host="127.0.0.1", port=port))
        try:
            with pytest.raises(OutputStartError, match=r"outputs\.thinkgear\.enabled: false"):
                await start_outputs([first, clash])
            assert first._server is None  # closed again
        finally:
            await blocker.close()

    asyncio.run(scenario())
