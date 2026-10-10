"""Causal filtering that carries its state from one chunk to the next."""

import numpy as np
from numpy.typing import NDArray
from scipy import signal

from neurostate.config import FilterConfig

_ORDER = 4
_NOTCH_Q = 30.0


class CausalFilter:
    """High-pass, mains notches and low-pass, applied as one filter.

    It never uses future samples, and keeps its state between calls, so filtering a stream chunk
    by chunk gives the same result as filtering it all at once. Notches and the low-pass are
    left out if they're above the Nyquist frequency.
    """

    def __init__(self, config: FilterConfig, sampling_rate: float, n_channels: int):
        nyquist = sampling_rate / 2
        sections = [
            signal.butter(_ORDER, config.highpass_hz, "highpass", fs=sampling_rate, output="sos")
        ]
        for freq in config.notch_hz:
            if freq < nyquist:
                b, a = signal.iirnotch(freq, _NOTCH_Q, fs=sampling_rate)
                sections.append(signal.tf2sos(b, a))
        if config.lowpass_hz < nyquist:
            sections.append(
                signal.butter(_ORDER, config.lowpass_hz, "lowpass", fs=sampling_rate, output="sos")
            )
        self._sos = np.vstack(sections)
        self._n_channels = n_channels
        self._zi: NDArray[np.float64] | None = None

    def __call__(self, samples: NDArray[np.float64]) -> NDArray[np.float64]:
        """Filter samples of shape (n, n_channels) that follow on from the previous call."""
        if len(samples) == 0:
            return samples
        if self._zi is None:
            # Start as if the first value had always been there, so a large DC offset (common
            # with dry electrodes) doesn't ring through the high-pass for seconds.
            self._zi = signal.sosfilt_zi(self._sos)[:, :, np.newaxis] * samples[0]
        filtered, self._zi = signal.sosfilt(self._sos, samples, axis=0, zi=self._zi)
        return filtered
