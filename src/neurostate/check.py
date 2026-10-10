"""The live view behind ``neurostate check``, for fitting the cap.

It shows the filtered signals coloured by channel status, how many good channels each region
has, gaps in the stream, and the spectrum over the back of the head, where alpha (8-13 Hz)
should rise clearly when the eyes close.
"""

import math
import signal
import time

import numpy as np
import pyqtgraph as pg
from pyqtgraph.Qt import QtCore
from scipy.signal import welch

from neurostate.acquisition.lsl_source import LslSource, RingBuffer
from neurostate.config import Config
from neurostate.montage import REGIONS, Montage
from neurostate.preprocessing.channels import ChannelReport, ChannelStatus, assess_channels
from neurostate.preprocessing.filters import CausalFilter

_SHOWN_S = 5.0
_SPACING_UV = 100.0
_SPECTRUM_S = 4.0
_SPECTRUM_MAX_HZ = 60.0
_REDRAW_MS = 50
_ASSESS_EVERY_S = 0.5

_COLORS = {
    ChannelStatus.OK: "#d0d0d0",
    ChannelStatus.FLAT: "#808080",
    ChannelStatus.NOISY: "#e05050",
    ChannelStatus.MAINS: "#f0a030",
}
_GOOD, _PARTLY, _BAD = "#60c060", "#f0a030", "#e05050"


def _colored(text: str, color: str) -> str:
    return f'<span style="color:{color}">{text}</span>'


class CheckWindow:
    """The live view. Call ``update()`` regularly to pull new data and redraw."""

    def __init__(self, source: LslSource, montage: Montage, config: Config):
        self._source = source
        self._config = config
        fs = source.sampling_rate
        n_channels = len(source.labels)
        self._filter = CausalFilter(config.filters, fs, n_channels)
        self._shown = RingBuffer(round(_SHOWN_S * fs), n_channels)
        self._regions = montage.region_indices(source.labels)
        self._spectrum_channels = self._regions["occipital"] or list(range(n_channels))
        self._reports: list[ChannelReport] = []
        self._last_assessed = -math.inf

        self.widget = pg.GraphicsLayoutWidget(title=f"neurostate check: {source.description.name}")
        self.widget.resize(1400, 900)
        self._status = self.widget.addLabel(row=0, col=0, colspan=2, justify="left")

        self._traces = self.widget.addPlot(row=1, col=0, title="Filtered signals")
        self._traces.setLabel("bottom", "seconds")
        self._traces.setXRange(-_SHOWN_S, 0, padding=0)
        self._traces.setYRange(-(n_channels - 0.5) * _SPACING_UV, 0.5 * _SPACING_UV, padding=0)
        ticks = [(-i * _SPACING_UV, label) for i, label in enumerate(source.labels)]
        self._traces.getAxis("left").setTicks([ticks])
        self._traces.setMouseEnabled(x=False, y=True)
        self._curves = [
            self._traces.plot(pen=pg.mkPen(_COLORS[ChannelStatus.OK])) for _ in source.labels
        ]

        names = ", ".join(source.labels[i] for i in self._spectrum_channels)
        title = f"Spectrum of {names}" if self._regions["occipital"] else "Spectrum, all channels"
        self._spectrum = self.widget.addPlot(row=1, col=1, title=title)
        self._spectrum.setLogMode(y=True)
        self._spectrum.setLabel("bottom", "Hz")
        self._spectrum.setLabel("left", "µV²/Hz")
        edge = pg.mkPen((90, 150, 255, 120))
        alpha = pg.LinearRegionItem(
            config.bands.alpha, movable=False, brush=(90, 150, 255, 50), pen=edge, hoverPen=edge
        )
        self._spectrum.addItem(alpha)
        self._spectrum_curve = self._spectrum.plot(pen=pg.mkPen("#70a8ff", width=2))
        self.widget.ci.layout.setColumnStretchFactor(0, 3)
        self.widget.ci.layout.setColumnStretchFactor(1, 1)

    def update(self) -> None:
        n_new = self._source.pull()
        if n_new:
            samples, stamps = self._source.buffer.latest(n_new)
            self._shown.extend(self._filter(samples), stamps)
            self._draw_traces()
        if time.monotonic() - self._last_assessed >= _ASSESS_EVERY_S:
            self._last_assessed = time.monotonic()
            self._assess()
            self._status.setText(self._status_html(), size="11pt")

    def _draw_traces(self) -> None:
        samples, stamps = self._shown.latest()
        seconds_ago = stamps - stamps[-1]
        for i, curve in enumerate(self._curves):
            curve.setData(seconds_ago, samples[:, i] - i * _SPACING_UV)

    def _assess(self) -> None:
        fs = self._source.sampling_rate
        raw, _ = self._source.buffer.latest(round(self._config.processing.window_s * fs))
        if len(raw) < fs / 2:
            return
        self._reports = assess_channels(
            raw, fs, self._config.filters.notch_hz, self._config.bad_channels
        )
        for curve, report in zip(self._curves, self._reports, strict=True):
            curve.setPen(pg.mkPen(_COLORS[report.status]))

        raw, _ = self._source.buffer.latest(round(_SPECTRUM_S * fs))
        freqs, psd = welch(
            raw[:, self._spectrum_channels],
            fs=fs,
            nperseg=min(len(raw), round(fs)),
            detrend="linear",
            axis=0,
        )
        shown = (freqs >= 1) & (freqs <= min(_SPECTRUM_MAX_HZ, fs / 2))
        # A floor keeps flat channels from producing log(0).
        self._spectrum_curve.setData(freqs[shown], np.maximum(psd[shown].mean(axis=1), 1e-6))

    def _status_html(self) -> str:
        source, gaps = self._source, self._source.gaps
        stream = [f"<b>{source.description.name}</b>: {len(source.labels)} EEG channels"]
        rate = gaps.effective_rate_hz
        stream.append(
            f"{source.sampling_rate:g} Hz nominal, {rate:.1f} received"
            if rate
            else f"{source.sampling_rate:g} Hz nominal"
        )
        idle = source.seconds_since_data()
        if idle is None:
            stream.append(_colored("waiting for data", _BAD))
        elif idle > self._config.input.no_signal_after_s:
            stream.append(_colored(f"no data for {idle:.0f} s", _BAD))
        plural = "" if gaps.n_gaps == 1 else "s"
        gap_text = f"{gaps.n_gaps} gap{plural}, {gaps.n_missing} samples missing"
        stream.append(_colored(gap_text, _BAD) if gaps.n_gaps else gap_text)

        if not self._reports:
            return " · ".join(stream) + "<br>Checking channels..."

        regions = []
        for region in REGIONS:
            positions = self._regions[region]
            good = sum(self._reports[i].status is ChannelStatus.OK for i in positions)
            color = _GOOD if positions and good == len(positions) else _PARTLY if good else _BAD
            regions.append(_colored(f"{region} {good}/{len(positions)} good", color))

        bad = [
            _colored(f"{label} {report.status}", _COLORS[report.status])
            for label, report in zip(self._source.labels, self._reports, strict=True)
            if report.status is not ChannelStatus.OK
        ]
        return "<br>".join(
            [
                " · ".join(stream),
                " · ".join(regions),
                "Problems: " + ", ".join(bad) if bad else _colored("All channels look fine", _GOOD),
            ]
        )


def run_check(source: LslSource, montage: Montage, config: Config) -> None:
    """Open the live view, and return when the window is closed or Ctrl+C is pressed."""
    app = pg.mkQApp("neurostate check")
    window = CheckWindow(source, montage, config)
    window.widget.show()
    timer = QtCore.QTimer()
    timer.timeout.connect(window.update)
    timer.start(_REDRAW_MS)
    # Qt's event loop would swallow Ctrl+C. The timer keeps handing control back to Python,
    # which then runs this handler.
    previous = signal.signal(signal.SIGINT, lambda *_: app.quit())
    try:
        pg.exec()
    finally:
        timer.stop()
        signal.signal(signal.SIGINT, previous)
