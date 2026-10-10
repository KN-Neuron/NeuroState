import numpy as np
import pytest
from scipy import signal

from neurostate.acquisition.mock_source import MockEEG
from neurostate.config import MOCK_CHANNELS, MockConfig

FS = 250


def make(**settings) -> MockEEG:
    return MockEEG(MockConfig(seed=1, **settings))


def band_power(eeg: np.ndarray, low: float, high: float) -> np.ndarray:
    """Power per channel between low and high Hz, in µV²."""
    freqs, psd = signal.welch(eeg, fs=FS, nperseg=2 * FS, axis=0)
    in_band = (freqs >= low) & (freqs < high)
    return psd[in_band].sum(axis=0) * (freqs[1] - freqs[0])


def index(label: str) -> int:
    return MOCK_CHANNELS.index(label)


def test_shape_and_reproducibility():
    eeg = make().generate(500)

    assert eeg.shape == (500, len(MOCK_CHANNELS))
    np.testing.assert_array_equal(eeg, make().generate(500))
    assert not np.array_equal(eeg, MockEEG(MockConfig(seed=2)).generate(500))


def test_output_does_not_depend_on_chunk_sizes():
    settings = {"blinks_per_min": 40, "line_noise_uv": 5}
    whole = make(**settings).generate(5000)
    generator = make(**settings)
    chunks = [generator.generate(n) for n in [1, 7, 13, 250, 979, 3750]]

    np.testing.assert_allclose(np.concatenate(chunks), whole)


def test_amplitudes_are_rms_at_the_strongest_channels():
    alpha_only = make(background_uv=0, beta_uv=0, noise_uv=0, alpha_uv=20).generate(FS * 60)
    background_only = make(alpha_uv=0, beta_uv=0, noise_uv=0, background_uv=10).generate(FS * 60)

    assert alpha_only[:, index("O1")].std() == pytest.approx(20, rel=0.15)
    assert background_only.std(axis=0) == pytest.approx(np.full(len(MOCK_CHANNELS), 10), rel=0.25)


def test_alpha_strength_raises_occipital_alpha():
    weak = band_power(make(alpha_uv=2).generate(FS * 30), 8, 13)
    strong = band_power(make(alpha_uv=30).generate(FS * 30), 8, 13)

    assert strong[index("O1")] > 20 * weak[index("O1")]


def test_alpha_is_strongest_at_the_back_and_beta_at_the_front():
    eeg = make(alpha_uv=20, beta_uv=10, background_uv=1).generate(FS * 30)
    alpha = band_power(eeg, 8, 13)
    beta = band_power(eeg, 14, 24)

    assert alpha[index("O1")] > 5 * alpha[index("Fz")]
    assert beta[index("Fz")] > 5 * beta[index("O1")]


def test_blinks_only_reach_frontal_channels():
    n = FS * 60
    with_blinks = make(blinks_per_min=30, blink_uv=150).generate(n)
    without = make(blinks_per_min=0).generate(n)
    blink_wave = with_blinks[:, index("Fp1")] - without[:, index("Fp1")]
    peaks, props = signal.find_peaks(blink_wave, height=50)

    assert 15 <= len(peaks) <= 45
    assert np.all((props["peak_heights"] > 0.8 * 150 - 1) & (props["peak_heights"] < 1.2 * 150 + 1))
    np.testing.assert_array_equal(with_blinks[:, index("O1")], without[:, index("O1")])


def test_line_noise_adds_power_at_mains_frequency():
    clean = band_power(make().generate(FS * 10), 49, 51)
    hum = band_power(make(line_noise_uv=20, line_hz=50).generate(FS * 10), 49, 51)

    assert np.all(hum > 100 * clean)
