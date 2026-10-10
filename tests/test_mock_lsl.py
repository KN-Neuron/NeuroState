"""End-to-end check that the mock stream can be found and read over LSL."""

import time

import numpy as np
import pylsl

from neurostate.acquisition.lsl_source import describe, find_streams


def test_mock_stream_is_received_over_lsl(start_mock):
    config = start_mock(channels=["Fp1", "Fz", "O1", "O2"], seed=0)
    [info] = find_streams(config.stream_name, "EEG", timeout=10)
    inlet = pylsl.StreamInlet(info)
    about = describe(inlet.info(timeout=5))
    samples, stamps = [], []
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        chunk, chunk_stamps = inlet.pull_chunk(timeout=0.1)
        samples.extend(chunk)
        stamps.extend(chunk_stamps)

    assert about.type == "EEG"
    assert about.sampling_rate == 250
    assert about.manufacturer == "neurostate"
    assert [ch.label for ch in about.channels] == config.channels
    assert {(ch.type, ch.unit) for ch in about.channels} == {("EEG", "microvolts")}

    samples = np.array(samples)
    assert samples.shape[1] == 4
    assert len(samples) > 250
    assert 1 < samples.std() < 100
    np.testing.assert_allclose(np.diff(stamps), 1 / 250, atol=1e-6)
