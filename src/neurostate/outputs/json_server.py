"""JSON outputs: one object per line over TCP, and one object per message over WebSocket."""

from websockets.asyncio.server import Server, ServerConnection, broadcast, serve
from websockets.exceptions import ConnectionClosed

from neurostate.config import JsonTcpConfig, WebSocketConfig
from neurostate.outputs.tcp import TcpBroadcaster
from neurostate.schema import BrainState


class JsonTcpServer(TcpBroadcaster):
    key = "json_tcp"

    def __init__(self, config: JsonTcpConfig):
        super().__init__(config.host, config.port)

    @property
    def description(self) -> str:
        return f"JSON over TCP on {self.address}"

    def publish(self, state: BrainState) -> None:
        self.send(state.to_json().encode() + b"\n")


class WebSocketServer:
    """Sends every update to every connected WebSocket client.

    With ``allowed_origins`` set, browsers can only connect from those pages. Clients outside a
    browser send no origin and are always let in.
    """

    key = "websocket"

    def __init__(self, config: WebSocketConfig):
        self._config = config
        self._port = config.port
        self._server: Server | None = None

    @property
    def description(self) -> str:
        return f"WebSocket on ws://{self._config.host}:{self._port}"

    @property
    def n_clients(self) -> int:
        return 0 if self._server is None else len(self._server.connections)

    async def start(self) -> None:
        allowed = self._config.allowed_origins
        origins = None if allowed is None else [*allowed, None]
        self._server = await serve(
            self._serve, self._config.host, self._config.port, origins=origins
        )
        self._port = self._server.sockets[0].getsockname()[1]

    @staticmethod
    async def _serve(connection: ServerConnection) -> None:
        # Messages from apps are ignored until control commands arrive (milestone M6).
        try:
            async for _ in connection:
                pass
        except ConnectionClosed:
            pass

    def publish(self, state: BrainState) -> None:
        if self._server is not None:
            broadcast(self._server.connections, state.to_json())

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
