"""Smoke test of the live view, drawn off-screen. Skipped locally without the gui extra."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.environ.get("CI"):
    # CI installs the gui extra, so failing to import it there is a real error, not a skip.
    import pyqtgraph as pg

    from neurostate import check
else:
    pg = pytest.importorskip("pyqtgraph")
    check = pytest.importorskip("neurostate.check")

from neurostate.acquisition.lsl_source import LslSource, find_streams
from neurostate.config import Config
from neurostate.montage import load_montage


def test_window_draws_live_data_and_status(start_mock):
    config = start_mock(channels=["Fp1", "Fz", "O1", "O2"], line_noise_uv=60, seed=0)
    [info] = find_streams(config.stream_name, "EEG", timeout=10)
    montage = load_montage("standard-1020")
    source = LslSource(info, montage)
    pg.mkQApp()
    window = check.CheckWindow(source, montage, Config())

    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline:
        window.update()
        time.sleep(0.05)

    x, _ = window._curves[0].getData()
    assert len(x) > 250
    assert x[-1] == 0
    status = window._status.text
    assert config.stream_name in status
    assert "frontal 0/1 good" in status
    assert "O1 mains" in status
    source.close()
