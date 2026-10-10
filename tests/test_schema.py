import itertools
import json

import pytest
from pydantic import ValidationError

from neurostate.estimators.fake import FakeStates
from neurostate.schema import STATE_CODES, BrainState, State


def make(**changes) -> BrainState:
    values = {
        "t": 12345.6789,
        "attention": 57.04,
        "relaxation": 41.26,
        "quality": 92.0,
        "state": State.OK,
        "calibrated": True,
    }
    return BrainState(**(values | changes))


def test_json_message_is_compact_and_versioned():
    assert make().to_json() == (
        '{"v":1,"t":12345.679,"attention":57.0,"relaxation":41.3,"quality":92.0,'
        '"state":"ok","calibrated":true}'
    )


def test_json_includes_bands_only_when_present():
    bands = {"occipital": {"alpha": 1.2}}

    assert "bands" not in json.loads(make().to_json())
    assert json.loads(make(bands=bands).to_json())["bands"] == bands


def test_state_codes_never_change():
    # Apps reading the LSL outlet depend on these numbers.
    assert {state.value: code for state, code in STATE_CODES.items()} == {
        "no_signal": 0,
        "poor_signal": 1,
        "calibrating": 2,
        "uncalibrated": 3,
        "ok": 4,
    }


@pytest.mark.parametrize("field", ["attention", "relaxation", "quality"])
@pytest.mark.parametrize("value", [-0.1, 100.1])
def test_scores_stay_between_0_and_100(field, value):
    with pytest.raises(ValidationError):
        make(**{field: value})


@pytest.mark.parametrize(
    ("state", "usable"),
    [
        (State.NO_SIGNAL, False),
        (State.POOR_SIGNAL, False),
        (State.CALIBRATING, True),
        (State.UNCALIBRATED, True),
        (State.OK, True),
    ],
)
def test_signal_usable(state, usable):
    assert make(state=state).signal_usable is usable


def test_fake_values_are_slow_waves_within_range():
    fake = FakeStates()
    states = [fake(1000 + i / 4) for i in range(4 * 66)]
    attention = [s.attention for s in states]

    assert all(s.state is State.OK and s.quality == 95 for s in states)
    assert min(attention) < 20 and max(attention) > 80
    assert max(abs(a - b) for a, b in itertools.pairwise(attention)) < 3
    assert [s.attention for s in states[:5]] != [s.relaxation for s in states[:5]]


def test_fake_dropouts_end_each_minute_and_hold_the_values():
    fake = FakeStates(dropouts=True)
    states = {second: fake(500 + second) for second in range(121)}

    assert states[49].state is State.OK
    assert states[50].state is State.POOR_SIGNAL and states[50].quality == 35
    assert states[56].state is State.NO_SIGNAL and states[56].quality == 0
    assert states[60].state is State.OK
    assert states[110].state is State.POOR_SIGNAL
    assert states[50].attention == states[58].attention == states[49].attention
