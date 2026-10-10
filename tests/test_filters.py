import numpy as np
import pytest

from neurostate.config import FilterConfig
from neurostate.preprocessing.filters import CausalFilter

FS = 250
t = np.arange(FS * 10) / FS


def sine(freq: float, amplitude: float = 10.0) -> np.ndarray:
    return amplitude * np.sin(2 * np.pi * freq * t)[:, np.newaxis]


def settled(x: np.ndarray) -> np.ndarray:
    """The part after the first 3 s, once the filter has settled."""
    return x[3 * FS :]


def run(x: np.ndarray, sampling_rate: float = FS) -> np.ndarray:
    return CausalFilter(FilterConfig(), sampling_rate, x.shape[1])(x)


def test_a_large_dc_offset_is_removed_without_a_long_transient():
    out = run(20_000 + sine(10))

    assert np.abs(out[FS:]).max() < 15
    assert np.abs(settled(out).mean()) < 0.5


def test_eeg_frequencies_pass_unchanged():
    for freq in [4, 10, 20, 30]:
        assert settled(run(sine(freq))).std() == pytest.approx(10 / np.sqrt(2), rel=0.05)


@pytest.mark.parametrize("freq", [50, 100])
def test_mains_is_removed(freq):
    assert settled(run(sine(freq))).std() < 0.01 * sine(freq).std()


def test_chunked_filtering_equals_filtering_at_once():
    x = np.hstack([sine(10), sine(50), 300 + sine(3)])
    whole = run(x)
    filt = CausalFilter(FilterConfig(), FS, 3)
    chunks = [filt(chunk) for chunk in np.array_split(x, [1, 13, 200, 1000, 1001])]

    np.testing.assert_allclose(np.concatenate(chunks), whole)


def test_frequencies_above_nyquist_are_skipped():
    # At 100 Hz the 50 and 100 Hz notches sit at or above Nyquist; the 45 Hz low-pass still fits.
    out = CausalFilter(FilterConfig(), 100, 1)(np.ones((500, 1)))

    assert np.all(np.isfinite(out))
