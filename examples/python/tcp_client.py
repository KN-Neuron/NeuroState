"""Minimal TCP client: reads one JSON object per line, reconnecting as needed.

Uses only the standard library, so it's a good template for languages without LSL or
WebSocket support. Start the service first (uv run neurostate run --fake), then:

    uv run python examples/python/tcp_client.py
"""

import json
import socket
import time

HOST, PORT = "127.0.0.1", 13855


def main() -> None:
    while True:
        try:
            # The timeout also catches a service that stops sending without disconnecting.
            with socket.create_connection((HOST, PORT), timeout=5) as connection:
                print("Connected.")
                for line in connection.makefile("r", encoding="utf-8"):
                    values = json.loads(line)
                    # Use the values only when the state is "ok"; otherwise fall back to a
                    # neutral default.
                    print(
                        f"{values['state']:12}  attention {values['attention']:5.1f}  "
                        f"relaxation {values['relaxation']:5.1f}  quality {values['quality']:3.0f}"
                    )
        except OSError as error:
            print(f"Not connected ({error}). Retrying in 2 s...")
        time.sleep(2)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
