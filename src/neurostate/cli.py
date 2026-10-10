"""Command-line interface: ``neurostate <command>``."""

from pathlib import Path
from typing import TYPE_CHECKING, Annotated, NoReturn

import typer
import yaml
from pydantic import ValidationError

from neurostate.config import Config, MockConfig, load_config
from neurostate.montage import REGIONS, Montage, load_montage

if TYPE_CHECKING:
    from neurostate.acquisition.lsl_source import LslSource

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
def check(
    ctx: typer.Context,
    stream: Annotated[
        str | None,
        typer.Option(
            help="LSL stream name. Default: input.stream_name, or else any stream of type "
            "input.stream_type."
        ),
    ] = None,
    montage: Annotated[
        str | None,
        typer.Option(help="Built-in montage name, or montage YAML file. Default: input.montage."),
    ] = None,
) -> None:
    """Show the live signal and per-channel quality, to help fit the cap.

    Prints what the stream reports about itself and, when the window closes, how many samples
    arrived and whether any were lost.
    """
    config: Config = ctx.obj
    try:
        layout = load_montage(montage or config.input.montage)
    except (ValueError, OSError, yaml.YAMLError, ValidationError) as error:
        _fail(f"Invalid montage:\n{error}")
    try:
        from neurostate.check import run_check
    except ImportError as error:
        _fail(f"The live view needs the gui extra. Install it with: uv sync --extra gui\n({error})")
    from neurostate.acquisition.lsl_source import LslSource, find_streams

    name = stream or config.input.stream_name
    wanted = f"named '{name}'" if name else f"of type {config.input.stream_type}"
    typer.echo(f"Looking for an LSL stream {wanted} (Ctrl+C to give up)...")
    try:
        while not (found := find_streams(name, config.input.stream_type, timeout=2.0)):
            pass
    except KeyboardInterrupt:
        _fail("No stream found.", code=1)
    if len(found) > 1:
        others = ", ".join(f"'{info.name()}'" for info in found[1:])
        typer.echo(f"Also found {others}; choose with --stream.")

    try:
        source = LslSource(found[0], layout)
    except (ValueError, TimeoutError) as error:
        _fail(str(error), code=1)
    _print_stream(source, layout)
    try:
        run_check(source, layout, config)
    finally:
        source.close()
    _print_reception(source)


def _print_stream(source: "LslSource", montage: Montage) -> None:
    about = source.description
    typer.echo(
        f"Stream '{about.name}' (type {about.type}) from {about.manufacturer or 'unknown maker'} "
        f"on {about.hostname}, source id '{about.source_id}'"
    )
    typer.echo(
        f"  {len(about.channels)} channels, {about.sampling_rate:g} Hz, {about.channel_format}"
    )
    typer.echo(f"  EEG channels ({len(source.labels)}): {' '.join(source.labels)}")
    units = sorted({channel.unit or "(none)" for channel in source.channels})
    typer.echo(f"  Units: {', '.join(units)}")
    if source.ignored_labels:
        ignored = " ".join(source.ignored_labels)
        typer.echo(f"  Ignored channels ({len(source.ignored_labels)}): {ignored}")
    positions = montage.region_indices(source.labels)
    for region in REGIONS:
        labels = " ".join(source.labels[i] for i in positions[region]) or "no channels"
        typer.echo(f"  {region.capitalize()} ({montage.name}): {labels}")
    for warning in source.warnings:
        typer.echo(f"  Warning: {warning}")


def _print_reception(source: "LslSource") -> None:
    gaps = source.gaps
    if gaps.n_samples == 0:
        typer.echo("No samples received.")
        return
    rate = gaps.effective_rate_hz
    per_second = f" ({rate:.2f} per second, nominal {source.sampling_rate:g})" if rate else ""
    typer.echo(f"Received {gaps.n_samples} samples over {gaps.elapsed_s:.1f} s{per_second}.")
    if gaps.n_gaps:
        plural = "" if gaps.n_gaps == 1 else "s"
        typer.echo(
            f"{gaps.n_gaps} gap{plural}: {gaps.n_missing} samples missing, "
            f"longest {gaps.longest_gap_s:.3f} s."
        )
    else:
        typer.echo("No gaps: no samples were lost.")
    if gaps.n_out_of_order:
        typer.echo(f"{gaps.n_out_of_order} timestamps were not later than the one before.")


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
    drops: Annotated[
        float | None, typer.Option(help="Chunks of samples lost in transit per minute.")
    ] = None,
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
        "drops_per_min": drops,
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
