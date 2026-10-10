"""Minimal WebSocket client: prints the values neurostate publishes, reconnecting as needed.

Start the service first (uv run neurostate run --fake), then:

    uv run python examples/python/websocket_client.py
"""

import asyncio
import json

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

URL = "ws://127.0.0.1:13856"


async def main() -> None:
    print(f"Connecting to {URL}...")
    # Looping over connect() reconnects, with a growing delay, whenever the connection fails.
    async for websocket in connect(URL):
        print("Connected.")
        try:
            async for message in websocket:
                values = json.loads(message)
                # Use the values only when the state is "ok"; otherwise fall back to a neutral
                # default.
                print(
                    f"{values['state']:12}  attention {values['attention']:5.1f}  "
                    f"relaxation {values['relaxation']:5.1f}  quality {values['quality']:3.0f}"
                )
        except ConnectionClosed:
            pass
        print("Disconnected. Reconnecting...")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
