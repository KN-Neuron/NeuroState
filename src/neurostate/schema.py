"""The values neurostate publishes: one versioned model shared by every output.

See ``docs/outputs.md`` for how each output carries them.
"""

import json
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = 1


class State(StrEnum):
    """What the values can currently be trusted for."""

    NO_SIGNAL = "no_signal"  # no stream, or no data for a while
    POOR_SIGNAL = "poor_signal"  # data arrives but too noisy to use
    CALIBRATING = "calibrating"  # a calibration is running
    UNCALIBRATED = "uncalibrated"  # usable, but scaled with population defaults
    OK = "ok"  # usable and calibrated for this user


# Numeric codes, for outputs that only carry numbers (the LSL outlet). Apps depend on these:
# never renumber them, only add new ones at the end.
STATE_CODES = {state: code for code, state in enumerate(State)}

Score = Annotated[float, Field(ge=0, le=100)]


class BrainState(BaseModel):
    """One update of the published values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    t: float  # LSL timestamp (pylsl.local_clock) of the data window the values describe
    attention: Score
    relaxation: Score
    quality: Score  # 0 means no usable signal
    state: State
    calibrated: bool  # whether a calibration profile is loaded
    bands: dict[str, dict[str, float]] | None = None  # region -> band -> log10 power in µV²

    @property
    def signal_usable(self) -> bool:
        return self.state not in (State.NO_SIGNAL, State.POOR_SIGNAL)

    def to_json(self) -> str:
        """The compact JSON message sent over TCP and WebSocket."""
        message: dict[str, object] = {
            "v": SCHEMA_VERSION,
            "t": round(self.t, 3),
            "attention": round(self.attention, 1),
            "relaxation": round(self.relaxation, 1),
            "quality": round(self.quality, 1),
            "state": self.state.value,
            "calibrated": self.calibrated,
        }
        if self.bands is not None:
            message["bands"] = self.bands
        return json.dumps(message, separators=(",", ":"))
