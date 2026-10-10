"""Per-channel signal checks: flat, noisy or full of mains hum."""

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray
from scipy import signal

from neurostate.config import BadChannelConfig

_EEG_BAND_HZ = (1.0, 40.0)
_MAINS_HALF_WIDTH_HZ = 1.0


class ChannelStatus(StrEnum):
    OK = "ok"
    FLAT = "flat"
    NOISY = "noisy"
    MAINS = "mains"


@dataclass(frozen=True)
class ChannelReport:
    status: ChannelStatus
    rms_uv: float  # over 1-40 Hz
    mains_ratio: float  # mains power relative to 1-40 Hz power


def assess_channels(
    samples: NDArray[np.float64],
    sampling_rate: float,
    mains_hz: list[float],
    thresholds: BadChannelConfig,
) -> list[ChannelReport]:
    """Check each channel of a raw signal window of shape (n, n_channels), in µV.

    Works from the power spectrum, so DC offsets and slow drift don't count as noise. Mains
    frequencies above the Nyquist frequency are skipped.
    """
    freqs, psd = signal.welch(
        samples,
        fs=sampling_rate,
        nperseg=min(len(samples), round(sampling_rate)),
        detrend="linear",
        axis=0,
    )
    df = freqs[1] - freqs[0]
    in_band = (freqs >= _EEG_BAND_HZ[0]) & (freqs <= _EEG_BAND_HZ[1])
    band_power = psd[in_band].sum(axis=0) * df
    mains_power = np.zeros(samples.shape[1])
    for freq in mains_hz:
        if freq < sampling_rate / 2:
            near = np.abs(freqs - freq) <= _MAINS_HALF_WIDTH_HZ
            mains_power += psd[near].sum(axis=0) * df

    reports = []
    for power, mains in zip(band_power, mains_power, strict=True):
        rms = float(np.sqrt(power))
        ratio = float(mains / power) if power > 0 else float("inf")
        if rms < thresholds.flat_uv:
            status = ChannelStatus.FLAT
        elif rms > thresholds.noisy_uv:
            status = ChannelStatus.NOISY
        elif ratio > thresholds.mains_ratio:
            status = ChannelStatus.MAINS
        else:
            status = ChannelStatus.OK
        reports.append(ChannelReport(status, rms, ratio))
    return reports
