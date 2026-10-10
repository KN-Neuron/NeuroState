"""Reading EEG from an LSL stream: finding it, keeping its EEG channels and tracking gaps."""

from dataclasses import dataclass

import numpy as np
import pylsl
from numpy.typing import NDArray

from neurostate.montage import Montage

_MAX_CHUNK = 1024
_GAP_FACTOR = 1.5

_MICROVOLTS_PER_UNIT = {
    "microvolts": 1.0,
    "microvolt": 1.0,
    "uv": 1.0,
    "µv": 1.0,
    "μv": 1.0,
    "millivolts": 1e3,
    "millivolt": 1e3,
    "mv": 1e3,
    "volts": 1e6,
    "volt": 1e6,
    "v": 1e6,
}


def microvolts_per_unit(unit: str) -> float | None:
    """The factor that converts a channel's unit to µV, or None if the unit isn't recognised."""
    return _MICROVOLTS_PER_UNIT.get(unit.strip().lower())


@dataclass(frozen=True)
class ChannelInfo:
    label: str
    type: str
    unit: str


@dataclass(frozen=True)
class StreamDescription:
    """What an LSL stream says about itself in its info and metadata."""

    name: str
    type: str
    source_id: str
    hostname: str
    manufacturer: str
    sampling_rate: float
    channel_format: str
    channels: list[ChannelInfo]


_CHANNEL_FORMATS = {
    pylsl.cf_float32: "float32",
    pylsl.cf_double64: "double64",
    pylsl.cf_string: "string",
    pylsl.cf_int32: "int32",
    pylsl.cf_int16: "int16",
    pylsl.cf_int8: "int8",
    pylsl.cf_int64: "int64",
}


def describe(info: pylsl.StreamInfo) -> StreamDescription:
    """Read a stream's description. Channels without metadata get the labels ch1, ch2, ..."""
    channels = []
    element = info.desc().child("channels").child("channel")
    while not element.empty():
        channels.append(
            ChannelInfo(
                element.child_value("label"),
                element.child_value("type"),
                element.child_value("unit"),
            )
        )
        element = element.next_sibling()
    if len(channels) != info.channel_count():
        channels = [ChannelInfo("", "", "") for _ in range(info.channel_count())]
    channels = [
        ChannelInfo(ch.label or f"ch{i + 1}", ch.type, ch.unit) for i, ch in enumerate(channels)
    ]
    return StreamDescription(
        name=info.name(),
        type=info.type(),
        source_id=info.source_id(),
        hostname=info.hostname(),
        manufacturer=info.desc().child_value("manufacturer"),
        sampling_rate=info.nominal_srate(),
        channel_format=_CHANNEL_FORMATS.get(info.channel_format(), "unknown"),
        channels=channels,
    )


def find_streams(name: str | None, stream_type: str, timeout: float) -> list[pylsl.StreamInfo]:
    """Streams with the given name or, without a name, of the given type.

    Waits up to ``timeout`` seconds for the first one, and returns an empty list if none appear.
    """
    if name is not None:
        return pylsl.resolve_byprop("name", name, timeout=timeout)
    return pylsl.resolve_byprop("type", stream_type, timeout=timeout)


def select_eeg_channels(channels: list[ChannelInfo], montage: Montage) -> list[int]:
    """Positions of the EEG channels: those the montage lists or, if it lists none, those the
    stream marks as EEG or leaves untyped."""
    if montage.channels is not None:
        wanted = {label.lower() for label in montage.channels}
        return [i for i, ch in enumerate(channels) if ch.label.lower() in wanted]
    return [i for i, ch in enumerate(channels) if ch.type.strip().lower() in {"eeg", ""}]


class RingBuffer:
    """The most recent samples of a multi-channel stream, with their timestamps."""

    def __init__(self, capacity: int, n_channels: int):
        self._data = np.zeros((capacity, n_channels))
        self._stamps = np.zeros(capacity)
        self._written = 0

    @property
    def capacity(self) -> int:
        return len(self._stamps)

    def __len__(self) -> int:
        return min(self._written, self.capacity)

    def extend(self, samples: NDArray[np.float64], stamps: NDArray[np.float64]) -> None:
        """Append samples of shape (n, n_channels) and their n timestamps."""
        skipped = max(0, len(stamps) - self.capacity)
        self._written += skipped
        positions = (self._written + np.arange(len(stamps) - skipped)) % self.capacity
        self._data[positions] = samples[skipped:]
        self._stamps[positions] = stamps[skipped:]
        self._written += len(positions)

    def latest(self, n: int | None = None) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Copies of the last ``n`` samples (all if None, fewer if not filled yet), oldest first."""
        n = len(self) if n is None else min(n, len(self))
        positions = (self._written - n + np.arange(n)) % self.capacity
        return self._data[positions], self._stamps[positions]


@dataclass(frozen=True)
class Gap:
    t: float  # timestamp of the first sample after the gap
    duration_s: float  # time without samples, beyond the normal sample interval
    missing: int  # estimated number of lost samples


class GapTracker:
    """Counts samples and finds gaps in a stream's timestamps.

    A gap is a step between consecutive timestamps of more than 1.5 sample intervals. This
    assumes the source timestamps its samples regularly, like the mock stream does.
    """

    def __init__(self, sampling_rate: float):
        self._period = 1.0 / sampling_rate
        self.n_samples = 0
        self.n_gaps = 0
        self.n_missing = 0
        self.n_out_of_order = 0
        self.longest_gap_s = 0.0
        self.first_t: float | None = None
        self.last_t: float | None = None

    def update(self, stamps: NDArray[np.float64]) -> list[Gap]:
        """Take the timestamps of newly arrived samples; return any gaps before or among them."""
        if len(stamps) == 0:
            return []
        if self.last_t is None:
            self.first_t = float(stamps[0])
            steps, after = np.diff(stamps), stamps[1:]
        else:
            steps, after = np.diff(stamps, prepend=self.last_t), stamps
        self.last_t = float(stamps[-1])
        self.n_samples += len(stamps)
        self.n_out_of_order += int(np.sum(steps <= 0))

        is_gap = steps > _GAP_FACTOR * self._period
        gaps = [
            Gap(float(t), float(step) - self._period, round(step / self._period) - 1)
            for step, t in zip(steps[is_gap], after[is_gap], strict=True)
        ]
        self.n_gaps += len(gaps)
        self.n_missing += sum(gap.missing for gap in gaps)
        self.longest_gap_s = max([self.longest_gap_s, *(gap.duration_s for gap in gaps)])
        return gaps

    @property
    def elapsed_s(self) -> float:
        """Time between the first and last sample seen."""
        if self.first_t is None or self.last_t is None:
            return 0.0
        return self.last_t - self.first_t

    @property
    def effective_rate_hz(self) -> float | None:
        """Samples actually received per second, or None until there are enough to tell."""
        if self.elapsed_s <= 0:
            return None
        return (self.n_samples - 1) / self.elapsed_s


class LslSource:
    """An LSL EEG stream read into a ring buffer, in µV, keeping only its EEG channels.

    Call ``pull()`` regularly to move newly arrived samples into ``buffer``. LSL reconnects on
    its own if the stream restarts; the time without data then shows up as a gap.
    """

    def __init__(self, info: pylsl.StreamInfo, montage: Montage, buffer_s: float = 10.0):
        self._inlet = pylsl.StreamInlet(info, processing_flags=pylsl.proc_clocksync)
        self.description = describe(self._inlet.info(timeout=10))
        if self.description.sampling_rate <= 0:
            raise ValueError(f"stream '{self.description.name}' has no regular sampling rate")

        self._indices = select_eeg_channels(self.description.channels, montage)
        if not self._indices:
            raise ValueError(
                f"none of the channels of stream '{self.description.name}' are EEG channels "
                f"of montage '{montage.name}'"
            )
        self.channels = [self.description.channels[i] for i in self._indices]
        self.labels = [ch.label for ch in self.channels]
        self.ignored_labels = [
            ch.label for i, ch in enumerate(self.description.channels) if i not in self._indices
        ]

        self.warnings: list[str] = []
        unknown_units = sorted(
            {ch.unit for ch in self.channels if microvolts_per_unit(ch.unit) is None}
        )
        if unknown_units:
            listed = ", ".join(f"'{unit}'" for unit in unknown_units)
            self.warnings.append(f"unrecognised channel units {listed}: assuming microvolts")
        self._scale = np.array([microvolts_per_unit(ch.unit) or 1.0 for ch in self.channels])

        self.buffer = RingBuffer(round(buffer_s * self.sampling_rate), len(self.labels))
        self.gaps = GapTracker(self.sampling_rate)
        self._last_arrival: float | None = None
        self._inlet.open_stream(timeout=10)

    @property
    def sampling_rate(self) -> float:
        return self.description.sampling_rate

    def pull(self) -> int:
        """Move all samples waiting in the inlet into the buffer, and return how many there were."""
        n_new = 0
        while True:
            samples, stamps = self._inlet.pull_chunk(timeout=0.0, max_samples=_MAX_CHUNK)
            if not stamps:
                return n_new
            stamps = np.asarray(stamps)
            self.gaps.update(stamps)
            self.buffer.extend(np.asarray(samples)[:, self._indices] * self._scale, stamps)
            self._last_arrival = pylsl.local_clock()
            n_new += len(stamps)

    def seconds_since_data(self) -> float | None:
        """Time since samples last arrived, or None if none have yet."""
        if self._last_arrival is None:
            return None
        return pylsl.local_clock() - self._last_arrival

    def close(self) -> None:
        self._inlet.close_stream()
