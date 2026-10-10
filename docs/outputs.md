# Receiving values from neurostate

neurostate publishes the user's attention and relaxation levels, plus how far they can be
trusted, several times a second. Your app can receive them over any of four outputs, all
running at once, each with as many clients as you like.

To develop without an EEG cap, run the service with made-up values:

```sh
uv run neurostate run --fake              # slow waves in attention and relaxation
uv run neurostate run --fake --dropouts   # each minute ends with 6 s of poor signal, then 4 s of none
```

Use `--dropouts` to check that your app copes when the signal goes bad.

## Which output to use

| Output | Default address | Rate | Best for |
|---|---|---|---|
| [LSL](#lsl-stream) | stream `NeuroState`, type `BrainState` | 4/s | Unity, Unreal, C, C++, C#, Python, Java; recording alongside the EEG |
| [JSON over WebSocket](#json-over-websocket) | `ws://127.0.0.1:13856` | 4/s | Browser apps |
| [JSON over TCP](#json-over-tcp) | `127.0.0.1:13855` | 4/s | Anything that can open a socket and parse JSON |
| [ThinkGear](#thinkgear-compatible-tcp) | `127.0.0.1:13854` | 1/s | Existing apps written for NeuroSky MindWave headsets |

Working clients for most of these are in [examples/](../examples/).

## The values

Every output carries the same values (schema version 1):

| Field | Type | Meaning |
|---|---|---|
| `attention` | number, 0–100 | Smoothed attention level, relative to the user's calibration |
| `relaxation` | number, 0–100 | Smoothed relaxation level |
| `quality` | number, 0–100 | Signal quality; 0 means no usable signal |
| `state` | string | What the values can be trusted for right now (see below) |
| `calibrated` | true/false | Whether a calibration profile for this user is loaded |
| `t` | number | When the values were measured, in seconds on the [LSL clock](#about-t) |
| `bands` | object, optional | Log band powers per brain region, for apps with their own measures. Not sent yet; arrives with the EEG pipeline |

### States

| `state` | Code | Meaning | What your app should do |
|---|---|---|---|
| `no_signal` | 0 | No EEG stream, or no data for over 2 s | Show a "not connected" message; use neutral values |
| `poor_signal` | 1 | Data arrives, but it's too noisy to use | Show a "poor signal" message; use neutral values |
| `calibrating` | 2 | A calibration is running | Don't use the values yet |
| `uncalibrated` | 3 | Usable, but scaled for an average person rather than this user | Usable as a rough guide |
| `ok` | 4 | Usable, and calibrated for this user | Use the values |

The codes are only used by the LSL output, which can only carry numbers. They will never be
renumbered; new states, if any, get new codes.

### About `t`

`t` is a timestamp on the LSL clock (seconds since an arbitrary start, the same clock as
`pylsl.local_clock()`), not Unix time. It lets you line the values up with EEG and event
recordings made with LabRecorder. If you just want to know how fresh a value is, note when it
arrived instead.

### Delay

Values describe the last 2 seconds of EEG and are smoothed, so they lag behind the user by
1–2 seconds. Use them for gradual effects (music, lighting, difficulty) rather than instant
reactions.

## LSL stream

- Stream name `NeuroState`, type `BrainState`, source id `neurostate-NeuroState`.
- Five float channels, in this order: `attention`, `relaxation`, `quality`, `state` (the code
  from the [table above](#states)) and `calibrated` (1 or 0).
- A regular rate of 4 samples per second.
- Each sample's timestamp is `t`.
- The stream's metadata lists the channels (`desc/channels/channel/label`) and the state
  codes (`desc/state_codes/state/code` and `.../name`), so clients needn't hardcode them.

Find the stream by type `BrainState`. If the service restarts, LSL inlets reconnect by
themselves. In Unity, use the [LSL4Unity](https://github.com/labstreaminglayer/LSL4Unity)
package; see [examples/csharp](../examples/csharp/).

## JSON over WebSocket

Connect to `ws://127.0.0.1:13856`. Every message is one JSON object:

```json
{"v":1,"t":37749.512,"attention":57.3,"relaxation":41.0,"quality":92.0,"state":"ok","calibrated":true}
```

`v` is the schema version. Numbers have one decimal place. Messages you send are ignored for
now; control commands (start a calibration, load a profile) are planned.

Any web page open in the user's browser can connect, unless you list the allowed pages in the
config:

```yaml
outputs:
  websocket:
    allowed_origins: [http://localhost:5173, https://myapp.example]
```

Clients outside a browser (which send no origin) are always let in.

## JSON over TCP

Connect to `127.0.0.1:13855`. The same JSON objects as on the WebSocket, one per line, each
ending in `\n`. Anything you send is ignored.

## ThinkGear-compatible TCP

For apps written for NeuroSky MindWave headsets, which expect the ThinkGear Connector on
`127.0.0.1:13854`. Point them at neurostate instead; nothing in the app needs to change.

- Whatever the app sends (authorisation, configuration) is read and ignored.
- Once a second, every client gets one JSON packet ending in a carriage return (`\r`):

  ```json
  {"eSense":{"attention":57,"meditation":41},"eegPower":{"delta":0,"theta":0,"lowAlpha":0,"highAlpha":0,"lowBeta":0,"highBeta":0,"lowGamma":0,"highGamma":0},"poorSignalLevel":0}
  ```

- `meditation` is neurostate's `relaxation`.
- `poorSignalLevel` is exactly 0 whenever the signal is usable (states `ok`, `uncalibrated`
  and `calibrating`), because many ThinkGear apps treat anything above 0 as "not connected".
  With a poor signal it rises with worsening quality, from 1 to 199, and with no signal it is
  200.
- While `poorSignalLevel` is above 0, `attention` and `meditation` are 0, which is ThinkGear's
  way of saying "can't tell". Otherwise they run from 1 to 100.
- `eegPower` is all zeros for now. It will be filled from the band powers once the EEG
  pipeline exists.
- Raw EEG (`rawEeg`) and blink packets aren't sent.

The real ThinkGear Connector uses the same port, so only one of the two can run at a time.

## Connecting reliably

- **Keep retrying.** The service may start before or after your app, and may restart. All the
  [examples](../examples/) reconnect on their own.
- **Don't block your main loop.** Read on a background thread or with async I/O.
- **Check `state` before using the values.** When it isn't `ok`, fall back to a neutral value
  (for example 50) or tell the user. Treat "no message for 2 seconds" as `no_signal` too.

## Settings

All in the `outputs` section of the config; see [config/default.yaml](../config/default.yaml).
Each output can be turned off with `enabled: false`, or moved to another port. Servers listen
on `127.0.0.1`, so only apps on the same computer can connect. Set `host: 0.0.0.0` to accept
connections from other devices, such as a phone or a standalone VR headset, on the same
network. Remember that the values come from someone's brain activity: only do that on a
network you trust.
