"""Fake EEG: a synthetic multi-channel LSL stream, for development without a cap."""

import math
import threading

import numpy as np
from numpy.typing import NDArray
from pylsl import StreamInfo, StreamOutlet, cf_float32, local_clock
from scipy import signal

from neurostate.config import MockConfig

# Pinking filter (J. O. Smith, "Spectral Audio Signal Processing"): turns white noise into noise
# with a 1/f power spectrum, the typical shape of background EEG.
_PINK_SOS = signal.tf2sos(
    [0.049922035, -0.095993537, 0.050612699, -0.004408786],
    [1.0, -2.494956002, 2.017265875, -0.522189400],
)
_ALPHA_HALF_WIDTH_HZ = 1.5
_BETA_BAND_HZ = (14.0, 24.0)
_BLINK_DURATION_S = 0.4
_PUSH_INTERVAL_S = 0.02

# Relative strength of alpha, beta and blinks by scalp region. The region is the letter part of a
# 10-20 label (Fp1 -> FP, POz -> PO). Alpha peaks over the back of the head, beta over the front
# and centre, and blinks only reach the electrodes nearest the eyes.
_REGION_WEIGHTS = {
    #      alpha  beta  blink
    "FP": (0.2, 0.8, 1.0),
    "AF": (0.25, 0.9, 0.6),
    "F": (0.3, 1.0, 0.3),
    "FC": (0.4, 1.0, 0.15),
    "FT": (0.4, 0.9, 0.1),
    "C": (0.5, 0.9, 0.05),
    "T": (0.4, 0.7, 0.05),
    "CP": (0.7, 0.7, 0.02),
    "TP": (0.6, 0.6, 0.02),
    "P": (0.9, 0.5, 0.0),
    "PO": (1.0, 0.4, 0.0),
    "O": (1.0, 0.3, 0.0),
    "I": (0.9, 0.3, 0.0),
}
_UNKNOWN_REGION_WEIGHTS = (0.5, 0.5, 0.0)


def _region_weights(label: str) -> tuple[float, float, float]:
    region = label.rstrip("0123456789zZ").upper()
    return _REGION_WEIGHTS.get(region, _UNKNOWN_REGION_WEIGHTS)


class _ShapedNoise:
    """Gaussian noise with unit RMS, shaped by a causal filter that keeps its state across calls."""

    def __init__(self, sos: NDArray[np.float64], n_channels: int, rng: np.random.Generator):
        self._sos = sos
        self._rng = rng
        self._n_channels = n_channels
        self._zi = np.zeros((sos.shape[0], 2, n_channels))
        impulse = np.zeros(20_000)
        impulse[0] = 1.0
        self._gain = 1.0 / math.sqrt(np.sum(signal.sosfilt(sos, impulse) ** 2))
        # Run the filter to its steady state, so the output starts at full strength.
        self(5_000)

    def __call__(self, n_samples: int) -> NDArray[np.float64]:
        white = self._rng.standard_normal((n_samples, self._n_channels))
        shaped, self._zi = signal.sosfilt(self._sos, white, axis=0, zi=self._zi)
        return self._gain * shaped


class MockEEG:
    """Generates synthetic EEG in µV, one chunk at a time.

    Each channel gets its own 1/f background and sensor noise. On top of that come an alpha
    rhythm, a beta rhythm and eye blinks shared by all channels and weighted by scalp region,
    and optional mains hum. Each component draws from its own random stream, so the output for a
    given seed doesn't depend on how it is split into chunks, or on the other components' settings.
    """

    def __init__(self, config: MockConfig):
        self._config = config
        fs = config.sampling_rate_hz
        n_channels = len(config.channels)
        rngs = [np.random.default_rng(s) for s in np.random.SeedSequence(config.seed).spawn(5)]

        weights = np.array([_region_weights(label) for label in config.channels])
        self._alpha_weights, self._beta_weights, self._blink_weights = weights.T

        alpha_band = (
            config.alpha_hz - _ALPHA_HALF_WIDTH_HZ,
            config.alpha_hz + _ALPHA_HALF_WIDTH_HZ,
        )
        self._background = _ShapedNoise(_PINK_SOS, n_channels, rngs[0])
        self._alpha = _ShapedNoise(_bandpass(alpha_band, fs), 1, rngs[1])
        self._beta = _ShapedNoise(_bandpass(_BETA_BAND_HZ, fs), 1, rngs[2])
        self._noise_rng = rngs[3]
        self._blink_rng = rngs[4]

        blink_len = round(_BLINK_DURATION_S * fs)
        self._blink_shape = 0.5 - 0.5 * np.cos(2 * np.pi * np.arange(blink_len) / blink_len)
        self._blinks: list[tuple[int, float]] = []  # (onset sample, peak) of blinks in progress
        self._next_blink = self._blink_interval()
        self._n_generated = 0

    @property
    def channels(self) -> list[str]:
        return self._config.channels

    def generate(self, n_samples: int) -> NDArray[np.float64]:
        """Return the next ``n_samples`` samples as an array of shape (n_samples, n_channels)."""
        cfg = self._config
        start = self._n_generated
        self._n_generated += n_samples
        t = np.arange(start, start + n_samples) / cfg.sampling_rate_hz

        eeg = cfg.background_uv * self._background(n_samples)
        eeg += cfg.alpha_uv * self._alpha(n_samples) * self._alpha_weights
        eeg += cfg.beta_uv * self._beta(n_samples) * self._beta_weights
        eeg += self._blink_wave(start, start + n_samples)[:, np.newaxis] * self._blink_weights
        eeg += cfg.noise_uv * self._noise_rng.standard_normal(eeg.shape)
        eeg += cfg.line_noise_uv * math.sqrt(2) * np.sin(2 * np.pi * cfg.line_hz * t)[:, np.newaxis]
        return eeg

    def _blink_interval(self) -> float:
        """Samples until the next blink: Poisson-distributed, but never overlapping the last one."""
        if self._config.blinks_per_min == 0:
            return math.inf
        mean = 60 * self._config.sampling_rate_hz / self._config.blinks_per_min
        return max(len(self._blink_shape), round(self._blink_rng.exponential(mean)))

    def _blink_wave(self, start: int, stop: int) -> NDArray[np.float64]:
        while self._next_blink < stop:
            peak = self._config.blink_uv * self._blink_rng.uniform(0.8, 1.2)
            self._blinks.append((int(self._next_blink), peak))
            self._next_blink += self._blink_interval()

        wave = np.zeros(stop - start)
        length = len(self._blink_shape)
        for onset, peak in self._blinks:
            lo, hi = max(onset, start), min(onset + length, stop)
            wave[lo - start : hi - start] += peak * self._blink_shape[lo - onset : hi - onset]
        self._blinks = [(onset, peak) for onset, peak in self._blinks if onset + length > stop]
        return wave


def _bandpass(band: tuple[float, float], fs: float) -> NDArray[np.float64]:
    return signal.butter(4, band, btype="bandpass", fs=fs, output="sos")


def stream_info(config: MockConfig) -> StreamInfo:
    """LSL stream info for the mock stream, with channel labels and units in its metadata."""
    info = StreamInfo(
        name=config.stream_name,
        type="EEG",
        channel_count=len(config.channels),
        nominal_srate=config.sampling_rate_hz,
        channel_format=cf_float32,
        source_id=f"neurostate-mock-{config.stream_name}",
    )
    desc = info.desc()
    desc.append_child_value("manufacturer", "neurostate")
    channels = desc.append_child("channels")
    for label in config.channels:
        channel = channels.append_child("channel")
        channel.append_child_value("label", label)
        channel.append_child_value("unit", "microvolts")
        channel.append_child_value("type", "EEG")
    return info


def run_mock(
    config: MockConfig, duration_s: float | None = None, stop: threading.Event | None = None
) -> None:
    """Stream mock EEG to LSL in real time, until ``duration_s`` has passed or ``stop`` is set."""
    generator = MockEEG(config)
    outlet = StreamOutlet(stream_info(config))
    fs = config.sampling_rate_hz
    total = math.inf if duration_s is None else round(duration_s * fs)
    stop = stop or threading.Event()

    t0 = local_clock()
    sent = 0
    while sent < total and not stop.is_set():
        due = min(int((local_clock() - t0) * fs) + 1, total) - sent
        if due > 0:
            chunk = generator.generate(due).astype(np.float32)
            # Timestamp from the sample count rather than the clock, so the stream has no jitter.
            outlet.push_chunk(chunk, t0 + (sent + due - 1) / fs)
            sent += due
        stop.wait(_PUSH_INTERVAL_S)
