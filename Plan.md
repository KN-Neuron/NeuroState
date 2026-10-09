# neurostate: plan

A standalone service that reads EEG from any LSL (Lab Streaming Layer) stream, runs a full processing pipeline, and publishes the user's **attention** and **relaxation** levels in real time. Any app or game can consume these values, in any language or engine. The first target device is a 32-channel BrainAccess cap, but the service isn't tied to it.

## 1. Goal and design principles

- **App-agnostic.** The service knows nothing about the apps that use it. It publishes a small, documented set of values, and apps decide what to do with them.
- **Device-agnostic.** Any EEG source that streams to LSL works. Channel labels are mapped to brain regions by configuration, so caps with fewer channels still work, with reduced accuracy.
- **Several ways to connect.** Apps can choose LSL, a JSON stream over TCP or WebSocket, OSC, or the NeuroSky ThinkGear format. Many clients can be connected at once.
- **Honest about signal quality.** Every message carries a quality value and a state, so an app can tell "the user is relaxed" apart from "there is no usable signal".

```
                        ┌─────────────────────────────────── neurostate ───────────────────────────────────┐
EEG cap ─► LSL "EEG" ──►│ acquisition ─► filtering ─► artifacts ─► features ─► indices ─► scaling/smoothing │──► LSL outlet "NeuroState"
(BrainAccess Board,     │                                   ▲                                              │──► JSON over TCP / WebSocket
 SDK adapter, replay,   │                    calibration profile (per user)                                │──► OSC
 or mock)               └──────────────────────────────────────────────────────────────────────────────────┘──► ThinkGear-compatible TCP
```

## 2. Key decisions

| Decision | Choice | Why |
|---|---|---|
| Language | Python 3.12, managed with `uv` | It has the best EEG tooling (`pylsl`, `mne-lsl`, `scipy`, `mne`, `meegkit`, `pyriemann`) |
| EEG input | Any LSL stream of type `EEG`. For BrainAccess, use BrainAccess Board, with a fallback adapter built on the `brainaccess` SDK | Board uses LSL by default. The SDK also works on Linux (`/dev/rfcommX`) if Board isn't available there |
| Main output | An LSL outlet | LSL has bindings for C, C++, C#, Python, Java and others, plus Unity and Unreal plugins, and recordings stay time-synchronised with the EEG |
| Extra outputs | JSON over TCP/WebSocket, OSC, ThinkGear-compatible TCP | Web apps and simple clients can use JSON; creative tools (TouchDesigner, Max/MSP) use OSC; existing NeuroSky apps work unchanged |
| First attention model | Band-power indices, normalised per user by a short calibration | Easy to understand, and it works from the first session |
| Later attention model (optional) | A per-user classifier (`pyriemann` + `scikit-learn`) trained on calibration data | Can be more accurate, but needs recorded data to check it |

## 3. Output data model

Every output carries the same values, produced at a configurable rate (default 4 Hz).

| Field | Type | Meaning |
|---|---|---|
| `attention` | 0–100 | Smoothed attention/engagement index, relative to the user's calibration |
| `relaxation` | 0–100 | Smoothed relaxation index |
| `quality` | 0–100 | Signal quality; 0 means no usable signal |
| `state` | `no_signal` / `poor_signal` / `calibrating` / `uncalibrated` / `ok` | What the values can currently be trusted for |
| `calibrated` | bool | Whether a calibration profile is loaded |
| `t` | float | LSL timestamp of the window the values describe |
| `bands` (optional) | object | Raw log band powers per region, for apps that want their own measures |

### JSON message (TCP and WebSocket)

One object per line on TCP, one object per message on WebSocket. The `v` field is the schema version.

```json
{"v":1,"t":1728485123.512,"attention":57,"relaxation":41,"quality":92,"state":"ok","calibrated":true}
```

### LSL outlet

- Stream name `NeuroState`, type `BrainState`.
- Five float channels: attention, relaxation, quality, state code, calibrated flag.
- Regular rate equal to the output rate.
- Channel names and the state-code table go in the stream's description metadata.

### OSC

- `/attention`, `/relaxation`, `/quality` (floats) and `/state` (string).
- Sent to a configurable host and port.

### ThinkGear-compatible adapter

For apps written for NeuroSky MindWave headsets:
- Listens on `127.0.0.1:13854` (configurable). Reads and ignores the client's first configuration message.
- Sends `{"eSense":{"attention":..,"meditation":..},"eegPower":{..},"poorSignalLevel":..}` once per second.
- Maps `relaxation` to `meditation`, and quality to `poorSignalLevel`: 0 when `state` is `ok`, up to 200 for no signal.
- Always sends `eSense` together with `poorSignalLevel`.

Many ThinkGear clients treat any `poorSignalLevel` above 0 as "not connected", so the adapter must send exactly 0 whenever the signal is usable.

## 4. Processing pipeline (real time, causal)

The service pulls data every ~50 ms and recomputes features every 250 ms on a sliding 2 s window.

1. **Acquisition**
   - Find the stream by name or type `EEG`.
   - Read the sampling rate, channel count, labels and units from the stream info; don't hardcode them.
   - Drop non-EEG channels such as an accelerometer.
   - Keep recent samples in a ring buffer (`mne_lsl.stream.StreamLSL` provides one).
   - Use LSL timestamps to detect gaps when samples are dropped.
2. **Filtering**
   - High-pass at 1 Hz, then mains notches (50 Hz and 100 Hz by default, configurable for 60 Hz regions), then low-pass at 45 Hz.
   - Use causal SOS filters with carried-over state, so filtering never needs future samples.
3. **Channel handling**
   - Mark a channel bad if it's flat, has extreme variance, carries a lot of mains noise, or correlates poorly with its neighbours.
   - Re-reference to the common average of the good channels.
   - Map channel labels to regions using a montage config, so different caps work.
4. **Artifacts**
   - Phase 1: reject a window if it goes over ±100 µV, or if a lot of its power is above 30 Hz (muscle noise). Blinks show up as large slow waves on frontal channels (Fp1/Fp2).
   - On a rejected window, hold the last good value and lower the quality score.
   - Phase 2: Artifact Subspace Reconstruction (`meegkit.asr`), calibrated on the clean rest recording.
5. **Features**
   - Welch power spectra, then log band powers: delta 1–4, theta 4–8, alpha 8–13, beta 13–25 Hz.
   - Beta stops at 25 Hz on purpose: higher frequencies carry more muscle noise.
   - Average over regions of interest: frontal (Fz/F3/F4), parietal (Pz/P3/P4) and occipital (O1/O2/Oz).
6. **Indices**
   - Attention: combine the engagement index β/(α+θ) (Pope et al., 1995) with frontal theta / parietal alpha. The second measure is less affected by muscle tension.
   - Relaxation: relative alpha power in parietal and occipital channels, plus α/β.
   - If a cap lacks some regions, fall back to the regions it has and lower `quality` accordingly.
7. **Scaling to 0–100**
   - Z-score each index against the user's calibration baseline.
   - Map it to 0–100 with a logistic curve centred between the "rest" and "focus" averages.
   - Smooth with an exponential moving average (time constant configurable, about 3 s by default).
   - Before calibration, use default population constants and report `state: uncalibrated`.
8. **Quality and state**
   - `quality` comes from the share of good channels in the regions of interest and the recent artifact rate.
   - `no_signal` when there's no stream or a gap longer than 2 s.

## 5. Calibration (about 4 minutes)

Calibration can be run from the CLI, or started by an app through the control commands (milestone M6).

1. Signal check, 30 s. Fix electrodes until the required regions are good.
2. Eyes closed, 60 s. Alpha in O1/O2 should rise clearly. This checks that the pipeline and channel labels are right, and gives the "relaxed" reference.
3. Eyes open, looking at a fixation cross, 60 s. This is the low-attention baseline.
4. A focus task, 60–90 s. This is the high-attention reference. Ideally use a task similar to how the service will be used, for example tracking a moving target, a 2-back test or mental arithmetic. The task should be configurable.
5. Save a per-user profile (JSON) with each feature's mean and spread per condition, the mapping constants and the list of bad channels.

## 6. Repo layout

```
neurostate/
  pyproject.toml              # uv, ruff, pytest
  config/
    default.yaml              # input stream, bands, window/step, thresholds, outputs and ports
    montages/                 # channel label → region maps per cap (e.g. brainaccess-32.yaml)
  src/neurostate/
    acquisition/   lsl_source.py, brainaccess_sdk_source.py, mock_source.py
    preprocessing/ filters.py, channels.py, artifacts.py
    quality/       signal_quality.py
    features/      bandpower.py
    estimators/    indices.py, ml.py (later)
    calibration/   protocol.py, profile.py, normalizer.py
    outputs/       lsl_outlet.py, json_server.py, osc_sender.py, thinkgear_server.py
    control/       commands.py          # status, start calibration, load profile
    schema.py      # versioned output model shared by all outputs
    pipeline.py    # acquisition thread → 250 ms processing tick → output fan-out
    cli.py         # neurostate check | calibrate | run | record | replay | mock
  examples/
    python/        # minimal LSL and WebSocket clients
    csharp/        # minimal LSL client, usable from Unity
    javascript/    # minimal WebSocket client for browser apps
  tests/
  notebooks/       # offline analysis of recorded sessions
  docs/
```

## 7. Milestones and TODO list

### M0: Repo setup
- [ ] Set up the project with `uv`, `ruff`, `pytest`, GitHub Actions CI and a YAML config loaded with `pydantic`.
- [ ] Build the CLI skeleton.
- [ ] Add `neurostate mock`: a fake multi-channel LSL stream with configurable alpha/beta strength, blinks and noise.

### M1: Getting data in
- [ ] Stream from BrainAccess Board to LSL. Note the stream name, sampling rate, channel labels and units.
- [ ] Inlet plus ring buffer, with gap detection from timestamps.
- [ ] Montage config for the BrainAccess 32-channel cap.
- [ ] `neurostate check`: live plot of the signals and per-channel quality.
- [ ] Fallback adapter using the `brainaccess` SDK, in case Board isn't available on Linux.
- *Done when:* 10 minutes stream without dropped samples, and alpha visibly rises at O1/O2 with eyes closed.

### M2: Outputs first, with made-up values
- [ ] Define the output schema (`schema.py`) and document it in `docs/`.
- [ ] Implement the LSL outlet, the JSON server (TCP and WebSocket) and the ThinkGear adapter, all fed by a fake signal (for example a slow sine wave).
- [ ] Write the example clients in Python, C# and JavaScript.
- *Done when:* every example client, plus an existing ThinkGear client, receives and displays the values; several clients can be connected at once.

### M3: Filtering and signal quality
- [ ] Causal filters with state, bad-channel detection and common-average reference.
- [ ] Quality score and states.
- *Done when:* unit tests pass on simulated flat, noisy and mains-polluted channels.

### M4: Features and first values
- [ ] Band powers for the regions of interest, plus the attention and relaxation indices.
- [ ] Smoothing, and default constants for before calibration.
- *Done when:* on real data, attention is higher during mental arithmetic than at rest, and relaxation is higher with eyes closed.

### M5: Calibration
- [ ] `neurostate calibrate`: guided on-screen protocol, then save the profile.
- [ ] Per-user scaling to 0–100.
- *Done when:* calibration takes under 5 minutes and the rest and focus conditions clearly separate in the output.

### M6: Control commands for apps
- [ ] Commands over the WebSocket/TCP connection: `get_status`, `list_profiles`, `load_profile`, `start_calibration` (with progress events), `stop`.
- *Done when:* an example client can run a full calibration and then receive calibrated values, without using the CLI.

### M7: Handling noise
- [ ] Window rejection for blinks and muscle activity, holding the last good value.
- [ ] Artifact Subspace Reconstruction (phase 2).
- *Done when:* blinking, clenching your jaw or turning your head doesn't make attention jump.

### M8: Recording, replay and evaluation
- [ ] Record sessions with LabRecorder (raw EEG plus `NeuroState`, plus any event markers an app sends over LSL).
- [ ] Replay recordings with `mne_lsl.player.PlayerLSL`, so development doesn't need someone wearing the cap.
- [ ] Notebook that measures how well rest and focus separate, how stable values are, and the end-to-end delay. Tune the parameters with it.
- [ ] Optional: the `pyriemann` classifier, compared against the band-power indices.

### M9: Packaging and documentation
- [ ] One command to start (`neurostate run --profile <name>`), and a README covering cap setup, calibration, outputs and troubleshooting.
- [ ] An integration guide for app developers (section 8).
- [ ] Test on both Linux and Windows.

## 8. Integration guide for apps (to expand into `docs/`)

- **Connect and keep retrying.** The service may start before or after the app, and may restart. Don't connect only once at startup.
- **Read on a background thread or with async I/O.** Never block the app's main or render loop waiting for values.
- **Check `state` before using values.** When it isn't `ok`, fall back to a neutral default or show a "poor signal" message.
- **Expect smoothed values that lag by 1–2 seconds.** Use them for gradual effects, not instant reactions.
- **Send your own events over LSL** (for example task start/end or user actions). LabRecorder then records them time-aligned with the EEG, which makes offline evaluation much easier.

## 9. Risks to plan for

- **Muscle and eye noise often come from the task itself.** Squinting, frowning or jaw tension during a demanding task push up beta power, so a beta-based index could end up measuring tension rather than attention. That's why the plan caps beta at 25 Hz, checks for muscle noise, and leans on the theta/alpha measures.
- **Dry electrodes on many channels** take time to fit, and some will lose contact. The service should keep working with a few bad channels as long as the frontal, parietal and occipital regions are covered.
- **People differ a lot**, so calibration is necessary rather than optional. Present the output as a control signal, not a clinical measure.
- **Built-in delay** is about 1–2 seconds, from the 2 s window plus smoothing. The smoothing should be configurable so each app can trade responsiveness against stability.
- **Privacy:** EEG recordings are personal data. When recording other people, get their consent and store recordings without names.

## 10. Things to confirm early (in M1)

- Which BrainAccess kit we have, and the sampling rate, channel labels and units its LSL stream reports. These couldn't be confirmed from public documentation.
- Whether BrainAccess Board runs on Linux. If it doesn't, use the SDK adapter.
- Which outputs to build first. The plan assumes LSL plus JSON, with the ThinkGear adapter in the same milestone because it's small.

## References

- Pope, A. T., Bogart, E. H., & Bartolome, D. S. (1995). Biocybernetic system evaluates indices of operator engagement in automated task. *Biological Psychology*, 40(1–2), 187–195.
- [Neurotechnology press release: BrainAccess 32-channel kit and LSL in BrainAccess Board](https://neurotechnology.com/press_release_brainaccess_hyperscanning.html)
- [BrainAccess Python API (brainaccess.core)](https://neurotechnology.com/brainaccess-documentation/PythonAPI/brainaccess.core.html)
- [BrainAccess Core usage examples](https://neurotechnology.com/brainaccess-documentation/PythonAPI/usage.html)
- [mne-lsl StreamLSL](https://mne.tools/mne-lsl/stable/generated/api/mne_lsl.stream.StreamLSL.html)
