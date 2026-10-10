# neurostate

A standalone service that reads EEG from any LSL (Lab Streaming Layer) stream and publishes the
user's attention and relaxation levels in real time. See [Plan.md](Plan.md) for the design and
milestones.

**Status:** milestone M1 (getting data in), in progress. `neurostate mock` and
`neurostate check` work; the other commands are placeholders.

## Setup

You need [uv](https://docs.astral.sh/uv/). It installs Python 3.12 if you don't have it.

```sh
uv sync --all-extras
```

`--all-extras` adds the `gui` extra (pyqtgraph and Qt, about 250 MB), which only
`neurostate check` needs. Leave it out on machines that just run the service.

## Usage

```sh
uv run neurostate --help
uv run neurostate mock                          # fake 32-channel EEG on LSL, until Ctrl+C
uv run neurostate mock --alpha 30 --blinks 15   # strong alpha, 15 blinks per minute
uv run neurostate mock --channels Fp1,Fp2,O1,O2 --line-noise 5
uv run neurostate mock --drops 20               # lose a chunk of samples 20 times a minute
uv run neurostate --config my.yaml mock         # settings from a config file
```

### Checking the signal

```sh
uv run neurostate check                         # first LSL stream of type EEG
uv run neurostate check --stream MockEEG        # a stream by name
uv run neurostate check --montage my-cap.yaml   # a montage other than standard 10-20
```

`check` first prints what the stream reports about itself: name, sampling rate, channel labels,
units, which channels it ignores (for example an accelerometer) and which channels cover each
brain region. It then opens a live view:

- **Signals**, filtered, coloured by channel status: grey for flat, red for noisy, orange for
  mains hum.
- **Status line**: how many good channels each region (frontal, parietal, occipital) has, the
  received sampling rate, and gaps in the stream.
- **Spectrum** over the back of the head (O1, Oz, O2). The alpha peak at 8–13 Hz should grow
  clearly when you close your eyes.

When you close the window (or press Ctrl+C), it prints how many samples arrived and how many
were lost.

### Config and montages

[config/default.yaml](config/default.yaml) lists every setting with its default. Your own config
file only needs the keys it changes.

A montage says which of a cap's channels are EEG and which brain region each one covers.
The built-in ones are in [src/neurostate/montages/](src/neurostate/montages/); `standard-1020`
works for any cap with standard 10-20 labels. You can also pass a path to your own montage
file.

The mock stream is a regular LSL stream of type `EEG`, so any LSL tool (LabRecorder,
`mne-lsl`'s viewer, etc.) can see it.

## Development

```sh
uv run pytest
uv run ruff check
uv run ruff format
```

CI runs the same checks on Linux and Windows for every push to `main` and every pull request.
