import numpy as np

from neurostate.acquisition.mock_source import MockEEG
from neurostate.config import BadChannelConfig, MockConfig
from neurostate.preprocessing.channels import ChannelStatus, assess_channels

FS = 250
MAINS = [50.0, 100.0]


def window(n_channels: int, seconds: float = 2.0) -> np.ndarray:
    labels = [f"O{i}" for i in range(n_channels)]
    return MockEEG(MockConfig(channels=labels, seed=3)).generate(round(seconds * FS))


def statuses(samples: np.ndarray, sampling_rate: float = FS) -> list[ChannelStatus]:
    reports = assess_channels(samples, sampling_rate, MAINS, BadChannelConfig())
    return [report.status for report in reports]


def test_flat_noisy_and_mains_channels_are_told_apart():
    eeg = window(5)
    t = np.arange(len(eeg)) / FS
    rng = np.random.default_rng(0)
    eeg[:, 1] = 3000.0  # stuck at a DC level
    eeg[:, 2] += rng.normal(0, 200, len(eeg))
    eeg[:, 3] += 40 * np.sin(2 * np.pi * 50 * t)
    eeg[:, 4] += 5000 + 2000 * t  # offset and drift alone are fine

    assert statuses(eeg) == [
        ChannelStatus.OK,
        ChannelStatus.FLAT,
        ChannelStatus.NOISY,
        ChannelStatus.MAINS,
        ChannelStatus.OK,
    ]


def test_reports_give_rms_and_mains_ratio():
    eeg = window(1, seconds=10)
    [report] = assess_channels(eeg, FS, MAINS, BadChannelConfig())

    assert 5 < report.rms_uv < 25
    assert report.mains_ratio < 0.01


def test_mains_above_nyquist_is_ignored():
    eeg = MockEEG(MockConfig(channels=["O1"], sampling_rate_hz=100, seed=1)).generate(200)

    assert statuses(eeg, sampling_rate=100) == [ChannelStatus.OK]
