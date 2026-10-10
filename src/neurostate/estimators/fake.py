"""Made-up values, for building and testing apps without EEG."""

import math

from neurostate.schema import BrainState, State

_ATTENTION_PERIOD_S = 20.0
_RELAXATION_PERIOD_S = 33.0
_DROPOUT_CYCLE_S = 60.0
_POOR_SIGNAL_FROM_S = 50.0
_NO_SIGNAL_FROM_S = 56.0


class FakeStates:
    """Attention and relaxation as slow sine waves with different periods, so they're easy to
    tell apart.

    With ``dropouts``, each minute ends with 6 s of poor signal and then 4 s of no signal, so
    apps can check how they handle those states. Values hold still while the signal is out, as
    they will with real EEG.
    """

    def __init__(self, dropouts: bool = False):
        self._dropouts = dropouts
        self._start: float | None = None
        self._held = (50.0, 50.0)

    def __call__(self, t: float) -> BrainState:
        if self._start is None:
            self._start = t
        elapsed = t - self._start

        state, quality = State.OK, 95.0
        if self._dropouts:
            in_cycle = elapsed % _DROPOUT_CYCLE_S
            if in_cycle >= _NO_SIGNAL_FROM_S:
                state, quality = State.NO_SIGNAL, 0.0
            elif in_cycle >= _POOR_SIGNAL_FROM_S:
                state, quality = State.POOR_SIGNAL, 35.0

        if state is State.OK:
            self._held = (
                50 + 35 * math.sin(2 * math.pi * elapsed / _ATTENTION_PERIOD_S),
                50 + 35 * math.sin(2 * math.pi * elapsed / _RELAXATION_PERIOD_S),
            )
        attention, relaxation = self._held
        return BrainState(
            t=t,
            attention=attention,
            relaxation=relaxation,
            quality=quality,
            state=state,
            calibrated=True,
        )
