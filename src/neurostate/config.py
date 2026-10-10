"""Service configuration: a YAML file validated with pydantic.

Every setting has a built-in default, mirrored in ``config/default.yaml``, so a config file only
needs the keys it changes.
"""

from pathlib import Path
from typing import Annotated, Self

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeFloat,
    PositiveFloat,
    model_validator,
)


def _check_band(band: tuple[float, float]) -> tuple[float, float]:
    low, high = band
    if low >= high:
        raise ValueError(f"band must be [low, high] with low < high, got [{low}, {high}]")
    return band


Band = Annotated[tuple[NonNegativeFloat, PositiveFloat], AfterValidator(_check_band)]


class _Section(BaseModel):
    # Reject unknown keys, so a typo in the YAML fails loudly instead of being ignored.
    model_config = ConfigDict(extra="forbid")


class InputConfig(_Section):
    """The EEG stream to read."""

    stream_name: str | None = None
    stream_type: str = "EEG"
    montage: str = "standard-1020"
    no_signal_after_s: PositiveFloat = 2.0


class ProcessingConfig(_Section):
    """Timing of the processing loop."""

    pull_interval_s: PositiveFloat = 0.05
    window_s: PositiveFloat = 2.0
    step_s: PositiveFloat = 0.25

    @model_validator(mode="after")
    def _step_fits_window(self) -> Self:
        if self.step_s > self.window_s:
            raise ValueError("step_s must not be longer than window_s")
        return self


class FilterConfig(_Section):
    highpass_hz: PositiveFloat = 1.0
    lowpass_hz: PositiveFloat = 45.0
    notch_hz: list[PositiveFloat] = Field(default_factory=lambda: [50.0, 100.0])

    @model_validator(mode="after")
    def _highpass_below_lowpass(self) -> Self:
        if self.highpass_hz >= self.lowpass_hz:
            raise ValueError("highpass_hz must be below lowpass_hz")
        return self


class BadChannelConfig(_Section):
    """Per-channel checks on the raw signal. RMS values are over 1-40 Hz."""

    flat_uv: PositiveFloat = 0.5
    noisy_uv: PositiveFloat = 50.0
    mains_ratio: PositiveFloat = 1.0


class ArtifactConfig(_Section):
    max_amplitude_uv: PositiveFloat = 100.0


class BandsConfig(_Section):
    """Frequency bands in Hz, as [low, high]."""

    delta: Band = (1.0, 4.0)
    theta: Band = (4.0, 8.0)
    alpha: Band = (8.0, 13.0)
    beta: Band = (13.0, 25.0)


class ScalingConfig(_Section):
    smoothing_s: PositiveFloat = 3.0


class LslOutletConfig(_Section):
    enabled: bool = True
    name: str = "NeuroState"
    type: str = "BrainState"


Port = Annotated[int, Field(ge=0, le=65535)]  # 0 picks any free port


class JsonTcpConfig(_Section):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: Port = 13855


class WebSocketConfig(_Section):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: Port = 13856
    allowed_origins: list[str] | None = None


class ThinkGearConfig(_Section):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: Port = 13854


class OutputsConfig(_Section):
    rate_hz: PositiveFloat = 4.0
    lsl: LslOutletConfig = Field(default_factory=LslOutletConfig)
    json_tcp: JsonTcpConfig = Field(default_factory=JsonTcpConfig)
    websocket: WebSocketConfig = Field(default_factory=WebSocketConfig)
    thinkgear: ThinkGearConfig = Field(default_factory=ThinkGearConfig)


# A common 32-channel 10-20 layout. The BrainAccess cap's own labels are confirmed in M1.
MOCK_CHANNELS = (
    "Fp1", "Fp2", "AF3", "AF4", "F7", "F3", "Fz", "F4", "F8", "FC5", "FC1", "FC2", "FC6", "T7",
    "C3", "Cz", "C4", "T8", "CP5", "CP1", "CP2", "CP6", "P7", "P3", "Pz", "P4", "P8", "PO3",
    "PO4", "O1", "Oz", "O2",
)  # fmt: skip


class MockConfig(_Section):
    """The fake EEG stream sent by ``neurostate mock``.

    Amplitudes are in µV RMS on the channels where each signal is strongest, except
    ``blink_uv``, which is the peak of a blink at Fp1/Fp2.
    """

    stream_name: str = "MockEEG"
    sampling_rate_hz: float = Field(250.0, ge=100.0)
    channels: list[str] = Field(default_factory=lambda: list(MOCK_CHANNELS), min_length=1)
    background_uv: NonNegativeFloat = 10.0
    alpha_uv: NonNegativeFloat = 10.0
    alpha_hz: float = Field(10.0, ge=7.0, le=14.0)
    beta_uv: NonNegativeFloat = 3.0
    blinks_per_min: NonNegativeFloat = 0.0
    blink_uv: NonNegativeFloat = 150.0
    noise_uv: NonNegativeFloat = 1.0
    line_noise_uv: NonNegativeFloat = 0.0
    line_hz: PositiveFloat = 50.0
    drops_per_min: NonNegativeFloat = 0.0
    seed: int | None = None

    @model_validator(mode="after")
    def _unique_channels(self) -> Self:
        if len(set(self.channels)) != len(self.channels):
            raise ValueError("channel labels must be unique")
        return self


class Config(_Section):
    input: InputConfig = Field(default_factory=InputConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    filters: FilterConfig = Field(default_factory=FilterConfig)
    bad_channels: BadChannelConfig = Field(default_factory=BadChannelConfig)
    artifacts: ArtifactConfig = Field(default_factory=ArtifactConfig)
    bands: BandsConfig = Field(default_factory=BandsConfig)
    scaling: ScalingConfig = Field(default_factory=ScalingConfig)
    outputs: OutputsConfig = Field(default_factory=OutputsConfig)
    mock: MockConfig = Field(default_factory=MockConfig)


def load_config(path: Path | None = None) -> Config:
    """Load a config file, filling in defaults for missing keys. No path gives all defaults.

    Raises ``OSError`` if the file can't be read, ``yaml.YAMLError`` if it isn't valid YAML and
    ``pydantic.ValidationError`` if the values are wrong.
    """
    if path is None:
        return Config()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Config.model_validate(data or {})
