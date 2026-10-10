"""Command-line interface: ``neurostate <command>``."""

from pathlib import Path
from typing import Annotated, NoReturn

import typer
import yaml
from pydantic import ValidationError

from neurostate.config import Config, MockConfig, load_config

app = typer.Typer(
    help="Real-time attention and relaxation levels from any LSL EEG stream.",
    no_args_is_help=True,
    add_completion=False,
)


def _fail(message: str, code: int = 2) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code)


def _not_implemented(milestone: str) -> NoReturn:
    _fail(f"Not implemented yet (planned for milestone {milestone}).", code=1)


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            "-c",
            exists=True,
            dir_okay=False,
            help="YAML config file. Keys it leaves out keep their defaults.",
        ),
    ] = None,
) -> None:
    try:
        ctx.obj = load_config(config)
    except (OSError, yaml.YAMLError, ValidationError) as error:
        _fail(f"Invalid config file {config}:\n{error}")


@app.command()
def check() -> None:
    """Show the live signal and per-channel quality, to help fit the cap."""
    _not_implemented("M1")


@app.command()
def calibrate() -> None:
    """Run the guided calibration protocol and save a per-user profile."""
    _not_implemented("M5")


@app.command()
def run() -> None:
    """Run the service: read EEG and publish attention and relaxation levels."""
    _not_implemented("M2")


@app.command()
def record() -> None:
    """Record a session: raw EEG, published values and app event markers."""
    _not_implemented("M8")


@app.command()
def replay() -> None:
    """Replay a recorded session as a live LSL stream."""
    _not_implemented("M8")


@app.command()
def mock(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Option(help="LSL stream name.")] = None,
    srate: Annotated[float | None, typer.Option(help="Sampling rate in Hz.")] = None,
    channels: Annotated[
        str | None, typer.Option(help="Comma-separated channel labels, e.g. Fp1,Fp2,O1,O2.")
    ] = None,
    alpha: Annotated[float | None, typer.Option(help="Alpha rhythm strength, µV RMS.")] = None,
    beta: Annotated[float | None, typer.Option(help="Beta rhythm strength, µV RMS.")] = None,
    blinks: Annotated[float | None, typer.Option(help="Eye blinks per minute.")] = None,
    noise: Annotated[float | None, typer.Option(help="White sensor noise, µV RMS.")] = None,
    line_noise: Annotated[float | None, typer.Option(help="Mains hum, µV RMS.")] = None,
    seed: Annotated[int | None, typer.Option(help="Seed for a reproducible signal.")] = None,
    duration: Annotated[
        float | None, typer.Option(min=0, help="Stop after this many seconds.")
    ] = None,
) -> None:
    """Stream fake EEG to LSL, for development without a cap.

    Options override the mock section of the config. Runs until Ctrl+C unless --duration is set.
    """
    config: Config = ctx.obj
    overrides = {
        "stream_name": name,
        "sampling_rate_hz": srate,
        "channels": [label.strip() for label in channels.split(",")] if channels else None,
        "alpha_uv": alpha,
        "beta_uv": beta,
        "blinks_per_min": blinks,
        "noise_uv": noise,
        "line_noise_uv": line_noise,
        "seed": seed,
    }
    given = {key: value for key, value in overrides.items() if value is not None}
    try:
        mock_config = MockConfig.model_validate(config.mock.model_dump() | given)
    except ValidationError as error:
        _fail(f"Invalid mock settings:\n{error}")

    # Imported here so the other commands don't pay for loading scipy and liblsl.
    from neurostate.acquisition.mock_source import run_mock

    typer.echo(
        f"Streaming '{mock_config.stream_name}' (type EEG): {len(mock_config.channels)} channels "
        f"at {mock_config.sampling_rate_hz:g} Hz. Press Ctrl+C to stop."
    )
    try:
        run_mock(mock_config, duration_s=duration)
    except KeyboardInterrupt:
        typer.echo("Stopped.")
