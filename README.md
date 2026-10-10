# neurostate

A standalone service that reads EEG from any LSL (Lab Streaming Layer) stream and publishes the
user's attention and relaxation levels in real time. See [Plan.md](Plan.md) for the design and
milestones.

**Status:** milestone M0 (repo setup). So far only `neurostate mock` works; the other commands
are placeholders.

## Setup

You need [uv](https://docs.astral.sh/uv/). It installs Python 3.12 if you don't have it.

```sh
uv sync
```

## Usage

```sh
uv run neurostate --help
uv run neurostate mock                          # fake 32-channel EEG on LSL, until Ctrl+C
uv run neurostate mock --alpha 30 --blinks 15   # strong alpha, 15 blinks per minute
uv run neurostate mock --channels Fp1,Fp2,O1,O2 --line-noise 5
uv run neurostate --config my.yaml mock         # settings from a config file
```

[config/default.yaml](config/default.yaml) lists every setting with its default. Your own config
file only needs the keys it changes.

The mock stream is a regular LSL stream of type `EEG`, so any LSL tool (LabRecorder,
`mne-lsl`'s viewer, etc.) can see it.

## Development

```sh
uv run pytest
uv run ruff check
uv run ruff format
```

CI runs the same checks on Linux and Windows for every push to `main` and every pull request.
