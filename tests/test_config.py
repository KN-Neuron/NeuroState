from pathlib import Path

import pytest
from pydantic import ValidationError

from neurostate.config import Config, load_config

DEFAULT_YAML = Path(__file__).parents[1] / "config" / "default.yaml"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_default_yaml_matches_built_in_defaults():
    assert load_config(DEFAULT_YAML) == Config()


def test_no_path_gives_defaults():
    assert load_config() == Config()


def test_empty_file_gives_defaults(tmp_path):
    assert load_config(write(tmp_path, "")) == Config()


def test_partial_file_keeps_other_defaults(tmp_path):
    config = load_config(
        write(tmp_path, "filters:\n  notch_hz: [60, 120]\nmock:\n  alpha_uv: 30\n")
    )

    assert config.filters.notch_hz == [60.0, 120.0]
    assert config.filters.highpass_hz == Config().filters.highpass_hz
    assert config.mock.alpha_uv == 30.0
    assert config.mock.channels == Config().mock.channels


@pytest.mark.parametrize(
    "text",
    [
        "filters:\n  highpas_hz: 2\n",
        "colour: blue\n",
        "bands:\n  alpha: [13, 8]\n",
        "bands:\n  alpha: [8, 10, 13]\n",
        "filters:\n  highpass_hz: 50\n",
        "processing:\n  window_s: 1\n  step_s: 2\n",
        "outputs:\n  thinkgear:\n    port: 70000\n",
        "mock:\n  sampling_rate_hz: 40\n",
        "mock:\n  alpha_uv: -1\n",
        "mock:\n  channels: []\n",
        "mock:\n  channels: [O1, O1]\n",
        "- not\n- a mapping\n",
    ],
)
def test_invalid_values_are_rejected(tmp_path, text):
    with pytest.raises(ValidationError):
        load_config(write(tmp_path, text))
