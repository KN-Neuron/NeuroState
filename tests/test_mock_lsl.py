"""End-to-end check that the mock stream can be found and read over LSL."""

import threading
import time
import uuid

import numpy as np
import pylsl

from neurostate.acquisition.mock_source import run_mock
from neurostate.config import MockConfig


def channel_labels(info: pylsl.StreamInfo) -> list[str]:
    labels = []
    channel = info.desc().child("channels").child("channel")
    while not channel.empty():
        labels.append(channel.child_value("label"))
        channel = channel.next_sibling()
    return labels


def test_mock_stream_is_received_over_lsl():
    config = MockConfig(
        stream_name=f"neurostate-test-{uuid.uuid4().hex[:8]}",
        channels=["Fp1", "Fz", "O1", "O2"],
        seed=0,
    )
    stop = threading.Event()
    thread = threading.Thread(target=run_mock, args=(config,), kwargs={"stop": stop}, daemon=True)
    thread.start()
    try:
        [found] = pylsl.resolve_byprop("name", config.stream_name, timeout=10)
        inlet = pylsl.StreamInlet(found)
        info = inlet.info(timeout=5)
        samples, stamps = [], []
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            chunk, chunk_stamps = inlet.pull_chunk(timeout=0.1)
            samples.extend(chunk)
            stamps.extend(chunk_stamps)
    finally:
        stop.set()
        thread.join(timeout=5)

    assert info.type() == "EEG"
    assert info.channel_count() == 4
    assert info.nominal_srate() == 250
    assert channel_labels(info) == config.channels

    samples = np.array(samples)
    assert samples.shape[1] == 4
    assert len(samples) > 250
    assert 1 < samples.std() < 100
    np.testing.assert_allclose(np.diff(stamps), 1 / 250, atol=1e-6)
    assert not thread.is_alive()
