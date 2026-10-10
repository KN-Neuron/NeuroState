import time

import pytest
from typer.testing import CliRunner

from neurostate.acquisition import mock_source
from neurostate.cli import app

runner = CliRunner()


def test_help_lists_all_commands():
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ["check", "calibrate", "run", "record", "replay", "mock"]:
        assert command in result.output


@pytest.mark.parametrize("command", ["calibrate", "run", "record", "replay"])
def test_unimplemented_commands_say_so(command):
    result = runner.invoke(app, [command])

    assert result.exit_code == 1
    assert "Not implemented yet" in result.output


def test_invalid_config_file_is_reported(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("mock:\n  alpha_uv: -1\n", encoding="utf-8")

    result = runner.invoke(app, ["--config", str(path), "mock", "--duration", "0"])

    assert result.exit_code == 2
    assert "Invalid config file" in result.output


@pytest.fixture
def captured_mock(monkeypatch):
    """Replace the streaming loop, and collect the settings it would have been run with."""
    calls = []
    monkeypatch.setattr(
        mock_source, "run_mock", lambda config, duration_s: calls.append((config, duration_s))
    )
    return calls


def test_mock_options_override_config(tmp_path, captured_mock):
    path = tmp_path / "custom.yaml"
    path.write_text("mock:\n  alpha_uv: 5\n  beta_uv: 7\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["-c", str(path), "mock", "--alpha", "30", "--channels", "Fp1, O1,O2", "--duration", "3"],
    )

    assert result.exit_code == 0, result.output
    [(config, duration_s)] = captured_mock
    assert config.alpha_uv == 30
    assert config.beta_uv == 7
    assert config.channels == ["Fp1", "O1", "O2"]
    assert duration_s == 3


def test_invalid_mock_option_is_reported(captured_mock):
    result = runner.invoke(app, ["mock", "--srate", "40"])

    assert result.exit_code == 2
    assert "Invalid mock settings" in result.output
    assert captured_mock == []


def test_mock_runs_for_the_given_duration():
    result = runner.invoke(app, ["mock", "--duration", "0.2"])

    assert result.exit_code == 0, result.output
    assert "Streaming 'MockEEG'" in result.output


def test_check_rejects_an_unknown_montage():
    result = runner.invoke(app, ["check", "--montage", "no-such-cap"])

    assert result.exit_code == 2
    assert "Invalid montage" in result.output


def test_check_describes_the_stream_and_reports_reception(start_mock, monkeypatch):
    check = pytest.importorskip("neurostate.check")
    config = start_mock(channels=["Fp1", "Fz", "O1", "O2"])

    def read_for_a_second(source, montage, config):  # instead of opening the window
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            source.pull()
            time.sleep(0.05)

    monkeypatch.setattr(check, "run_check", read_for_a_second)
    result = runner.invoke(app, ["check", "--stream", config.stream_name])

    assert result.exit_code == 0, result.output
    assert f"Stream '{config.stream_name}' (type EEG) from neurostate" in result.output
    assert "4 channels, 250 Hz, float32" in result.output
    assert "EEG channels (4): Fp1 Fz O1 O2" in result.output
    assert "Units: microvolts" in result.output
    assert "Frontal (Standard 10-20): Fz" in result.output
    assert "Parietal (Standard 10-20): no channels" in result.output
    assert "Occipital (Standard 10-20): O1 O2" in result.output
    assert "No gaps: no samples were lost." in result.output
