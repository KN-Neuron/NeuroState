"""Minimal LSL client: prints the values neurostate publishes.

Start the service first (uv run neurostate run --fake), then:

    uv run python examples/python/lsl_client.py
"""

import pylsl


def state_names(info: pylsl.StreamInfo) -> dict[int, str]:
    """The state code table from the stream's metadata."""
    names = {}
    entry = info.desc().child("state_codes").child("state")
    while not entry.empty():
        names[int(entry.child_value("code"))] = entry.child_value("name")
        entry = entry.next_sibling()
    return names


def main() -> None:
    print("Looking for the NeuroState stream...")
    found = []
    while not found:
        found = pylsl.resolve_byprop("type", "BrainState", timeout=2.0)

    # The inlet reconnects by itself if the service restarts.
    inlet = pylsl.StreamInlet(found[0])
    names = state_names(inlet.info())
    print("Connected.")
    while True:
        sample, _ = inlet.pull_sample(timeout=2.0)
        if sample is None:
            print("No values for 2 s. Is the service still running?")
            continue
        attention, relaxation, quality, code, _ = sample
        state = names.get(int(code), "unknown")
        # Use the values only when the state is "ok"; otherwise fall back to a neutral default.
        print(
            f"{state:12}  attention {attention:5.1f}  relaxation {relaxation:5.1f}  "
            f"quality {quality:3.0f}"
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
