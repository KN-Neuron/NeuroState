import time
import uuid

import numpy as np
import pylsl
import pytest

from neurostate.acquisition.lsl_source import (
    ChannelInfo,
    GapTracker,
    LslSource,
    RingBuffer,
    describe,
    find_streams,
    microvolts_per_unit,
    select_eeg_channels,
)
from neurostate.montage import Montage, load_montage

STANDARD = load_montage("standard-1020")


def stream_info(channels: list[tuple[str, str, str]]) -> pylsl.StreamInfo:
    """Info for a stream with the given (label, type, unit) channels and a unique name."""
    name = f"neurostate-test-{uuid.uuid4().hex[:8]}"
    info = pylsl.StreamInfo(name, "EEG", len(channels), 250, pylsl.cf_float32, name)
    element = info.desc().append_child("channels")
    for label, kind, unit in channels:
        channel = element.append_child("channel")
        channel.append_child_value("label", label)
        channel.append_child_value("type", kind)
        channel.append_child_value("unit", unit)
    return info


def pull_for(source: LslSource, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        source.pull()
        time.sleep(0.05)


@pytest.mark.parametrize(
    ("unit", "factor"),
    [("microvolts", 1), ("uV", 1), ("µV", 1), ("mV", 1e3), ("volts", 1e6), ("V", 1e6)],
)
def test_known_units_convert_to_microvolts(unit, factor):
    assert microvolts_per_unit(unit) == factor


@pytest.mark.parametrize("unit", ["", "g", "counts"])
def test_unknown_units_are_not_guessed(unit):
    assert microvolts_per_unit(unit) is None


def test_describe_reads_channel_metadata():
    about = describe(stream_info([("Fp1", "EEG", "microvolts"), ("AccX", "ACC", "g")]))

    assert about.channels == [
        ChannelInfo("Fp1", "EEG", "microvolts"),
        ChannelInfo("AccX", "ACC", "g"),
    ]
    assert about.sampling_rate == 250


def test_describe_labels_channels_without_metadata():
    info = pylsl.StreamInfo("bare", "EEG", 3, 250, pylsl.cf_float32, "bare")

    assert [ch.label for ch in describe(info).channels] == ["ch1", "ch2", "ch3"]


def test_describe_fills_in_missing_labels():
    about = describe(stream_info([("Fp1", "EEG", ""), ("", "EEG", "")]))

    assert [ch.label for ch in about.channels] == ["Fp1", "ch2"]


def test_eeg_channels_are_picked_by_type_without_a_montage_channel_list():
    channels = [
        ChannelInfo("Fp1", "EEG", ""),
        ChannelInfo("AccX", "ACC", ""),
        ChannelInfo("O1", "", ""),
        ChannelInfo("O2", "eeg", ""),
    ]

    assert select_eeg_channels(channels, STANDARD) == [0, 2, 3]


def test_eeg_channels_are_picked_by_label_with_a_montage_channel_list():
    montage = Montage(name="cap", channels=["Fp1", "O1"], regions={"occipital": ["O1"]})
    channels = [ChannelInfo("FP1", "", ""), ChannelInfo("Cz", "EEG", ""), ChannelInfo("o1", "", "")]

    assert select_eeg_channels(channels, montage) == [0, 2]


def test_ring_buffer_keeps_the_most_recent_samples_in_order():
    buffer = RingBuffer(capacity=5, n_channels=2)
    assert len(buffer) == 0

    for start in range(0, 7, 3):  # 0-2, 3-5, 6-8: the third chunk wraps around
        stamps = np.arange(start, start + 3, dtype=float)
        buffer.extend(np.column_stack([stamps, -stamps]), stamps)

    data, stamps = buffer.latest()
    np.testing.assert_array_equal(stamps, [4, 5, 6, 7, 8])
    np.testing.assert_array_equal(data[:, 1], [-4, -5, -6, -7, -8])
    np.testing.assert_array_equal(buffer.latest(2)[1], [7, 8])
    assert len(buffer.latest(100)[1]) == 5


def test_ring_buffer_takes_a_chunk_bigger_than_itself():
    buffer = RingBuffer(capacity=4, n_channels=1)
    buffer.extend(np.zeros((1, 1)), np.array([0.0]))
    stamps = np.arange(1, 11, dtype=float)
    buffer.extend(stamps[:, np.newaxis], stamps)

    np.testing.assert_array_equal(buffer.latest()[1], [7, 8, 9, 10])
    buffer.extend(np.zeros((1, 1)), np.array([11.0]))
    np.testing.assert_array_equal(buffer.latest()[1], [8, 9, 10, 11])


FS = 250
PERIOD = 1 / FS


def test_regular_timestamps_have_no_gaps():
    tracker = GapTracker(FS)
    stamps = 100 + np.arange(1000) * PERIOD
    for chunk in np.array_split(stamps, 37):
        assert tracker.update(chunk) == []

    assert tracker.n_samples == 1000
    assert tracker.n_gaps == tracker.n_missing == tracker.n_out_of_order == 0
    assert tracker.effective_rate_hz == pytest.approx(FS)
    assert tracker.elapsed_s == pytest.approx(999 * PERIOD)


def test_gaps_are_found_within_and_between_chunks():
    tracker = GapTracker(FS)
    stamps = np.delete(100 + np.arange(100) * PERIOD, [20, 21, 22, 23, 24, 60])

    within = tracker.update(stamps[:55])  # ends with sample 59
    between = tracker.update(stamps[55:])  # starts with sample 61
    [gap_a], [gap_b] = within, between

    assert gap_a.missing == 5
    assert gap_a.duration_s == pytest.approx(5 * PERIOD)
    assert gap_b.missing == 1
    assert (tracker.n_gaps, tracker.n_missing) == (2, 6)
    assert tracker.longest_gap_s == pytest.approx(5 * PERIOD)


def test_timestamps_that_go_backwards_are_counted():
    tracker = GapTracker(FS)
    tracker.update(np.array([1.0, 1.004, 1.004, 1.002]))

    assert tracker.n_out_of_order == 2


def test_source_reads_the_mock_stream(start_mock):
    config = start_mock(channels=["Fp1", "Fz", "O1", "O2"], seed=0)
    [info] = find_streams(config.stream_name, "EEG", timeout=10)
    source = LslSource(info, STANDARD, buffer_s=10)
    pull_for(source, 1.5)

    assert source.labels == config.channels
    assert source.ignored_labels == []
    assert source.warnings == []
    assert len(source.buffer) > 250
    assert source.gaps.n_gaps == 0
    assert source.seconds_since_data() < 0.5
    samples, _ = source.buffer.latest()
    assert 1 < samples.std() < 100
    source.close()


def test_source_notices_dropped_samples(start_mock):
    config = start_mock(channels=["O1"], drops_per_min=1200)
    [info] = find_streams(config.stream_name, "EEG", timeout=10)
    source = LslSource(info, STANDARD)
    pull_for(source, 2.0)

    assert source.gaps.n_gaps > 0
    assert source.gaps.n_missing >= source.gaps.n_gaps
    source.close()


def test_source_drops_non_eeg_channels_and_converts_units():
    info = stream_info([("Fp1", "EEG", "volts"), ("AccX", "ACC", "g"), ("O1", "EEG", "mV")])
    outlet = pylsl.StreamOutlet(info)
    [found] = find_streams(info.name(), "EEG", timeout=10)
    source = LslSource(found, STANDARD)

    deadline = time.monotonic() + 5
    while len(source.buffer) == 0 and time.monotonic() < deadline:
        outlet.push_chunk(np.tile(np.float32([2e-5, 0.98, 0.03]), (10, 1)))
        time.sleep(0.05)
        source.pull()

    assert source.labels == ["Fp1", "O1"]
    assert source.ignored_labels == ["AccX"]
    samples, _ = source.buffer.latest()
    np.testing.assert_allclose(samples[-1], [20.0, 30.0], rtol=1e-5)
    source.close()


def test_source_warns_about_unknown_units():
    info = stream_info([("Fp1", "EEG", "counts")])
    outlet = pylsl.StreamOutlet(info)
    [found] = find_streams(info.name(), "EEG", timeout=10)
    source = LslSource(found, STANDARD)

    assert source.warnings == ["unrecognised channel units 'counts': assuming microvolts"]
    source.close()
    del outlet


def test_source_refuses_a_stream_without_eeg_channels():
    info = stream_info([("AccX", "ACC", "g")])
    outlet = pylsl.StreamOutlet(info)
    [found] = find_streams(info.name(), "EEG", timeout=10)

    with pytest.raises(ValueError, match="none of the channels"):
        LslSource(found, STANDARD)
    del outlet
