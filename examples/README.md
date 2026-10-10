# Example clients

Minimal apps that receive values from neurostate. Each one reconnects on its own and falls back
to neutral values when the signal can't be trusted. See [docs/outputs.md](../docs/outputs.md)
for what the values mean.

Start the service first. Without a cap, use made-up values:

```sh
uv run neurostate run --fake
```

| Example | Output | Run it with |
|---|---|---|
| [python/lsl_client.py](python/lsl_client.py) | LSL | `uv run python examples/python/lsl_client.py` |
| [python/websocket_client.py](python/websocket_client.py) | WebSocket | `uv run python examples/python/websocket_client.py` |
| [python/tcp_client.py](python/tcp_client.py) | TCP, standard library only | `uv run python examples/python/tcp_client.py` |
| [csharp/](csharp/) | LSL, from .NET or Unity | `dotnet run --project examples/csharp` |
| [javascript/index.html](javascript/index.html) | WebSocket, in the browser | Open the file in a browser |

Add `--dropouts` to the service to see how the examples handle a poor signal and no signal.
