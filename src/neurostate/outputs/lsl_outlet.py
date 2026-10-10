"""The main output: an LSL stream with one sample per update."""

from pylsl import StreamInfo, StreamOutlet, cf_float32

from neurostate.config import LslOutletConfig
from neurostate.schema import SCHEMA_VERSION, STATE_CODES, BrainState

CHANNELS = (
    ("attention", "0-100"),
    ("relaxation", "0-100"),
    ("quality", "0-100"),
    ("state", "code"),
    ("calibrated", "0/1"),
)


class LslOutlet:
    """Publishes each update as one sample of a 5-channel float stream.

    The stream's metadata lists the channels and the state code table, so apps don't have to
    hardcode either.
    """

    key = "lsl"

    def __init__(self, config: LslOutletConfig, rate_hz: float):
        self._config = config
        self._rate_hz = rate_hz
        self._outlet: StreamOutlet | None = None

    @property
    def description(self) -> str:
        return f"LSL stream '{self._config.name}' (type {self._config.type})"

    async def start(self) -> None:
        info = StreamInfo(
            name=self._config.name,
            type=self._config.type,
            channel_count=len(CHANNELS),
            nominal_srate=self._rate_hz,
            channel_format=cf_float32,
            source_id=f"neurostate-{self._config.name}",
        )
        desc = info.desc()
        desc.append_child_value("manufacturer", "neurostate")
        desc.append_child_value("schema_version", str(SCHEMA_VERSION))
        channels = desc.append_child("channels")
        for label, unit in CHANNELS:
            channel = channels.append_child("channel")
            channel.append_child_value("label", label)
            channel.append_child_value("unit", unit)
            channel.append_child_value("type", self._config.type)
        codes = desc.append_child("state_codes")
        for state, code in STATE_CODES.items():
            entry = codes.append_child("state")
            entry.append_child_value("code", str(code))
            entry.append_child_value("name", state.value)
        self._outlet = StreamOutlet(info)

    def publish(self, state: BrainState) -> None:
        if self._outlet is None:
            return
        sample = [
            state.attention,
            state.relaxation,
            state.quality,
            STATE_CODES[state.state],
            float(state.calibrated),
        ]
        self._outlet.push_sample(sample, state.t)

    async def close(self) -> None:
        self._outlet = None
